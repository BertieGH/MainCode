"""The live La Growth Machine client — the one component that can reach a person.

Built against LGM's published API (`apiv2.lagrowthmachine.com/flow`). Three
facts about that API shaped everything here, and none of them are what our
adapter protocol originally assumed:

* **There is no "enrol this lead" call.** A campaign runs over an *audience*.
  A person is enrolled by being written into the audience the campaign reads,
  so `upsert_lead` carries the audience name and `enrol` only confirms the
  campaign is pointed at it. A campaign's audience can be changed only while it
  has never been started, and the **first launch has to happen in the LGM app** —
  so a shape is registered against a campaign somebody launched by hand.
* **Ten custom attributes, 1000 characters each.** The overflow is dropped
  silently by LGM, which is why the arc is checked before it reaches here.
* **50 calls per 10 seconds, per key.** Enforced here rather than left to the
  caller: one campaign is one call per person, and a fifty-person campaign
  would otherwise trip it halfway and leave the rest unwritten.

Nothing in this module echoes a response body into an error. LGM quotes the
request back on a rejection, and these strings reach an API — invariant 9.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.services.lgm import (
    ATTRIBUTE_BUDGET,
    ATTRIBUTE_MAX_CHARS,
    LgmCampaignMeta,
    LgmError,
    LgmLead,
    wire_attribute,
)

log = logging.getLogger(__name__)


def _verify_context():
    """Shared with the credential probes: the OS store, falling back to certifi."""
    from app.services.probes import _verify_context as store

    return store()

BASE_URL = "https://apiv2.lagrowthmachine.com/flow"
#: LGM's published limit, per key. Kept a little under it.
CALLS_PER_WINDOW = 45
WINDOW_SECONDS = 10.0
TIMEOUT_SECONDS = 30.0


@dataclass
class _RateLimit:
    """A small sliding window. One client, one key, one limiter."""

    calls: list[float] = field(default_factory=list)

    async def take(self) -> None:
        while True:
            now = time.monotonic()
            self.calls = [t for t in self.calls if now - t < WINDOW_SECONDS]
            if len(self.calls) < CALLS_PER_WINDOW:
                self.calls.append(now)
                return
            await asyncio.sleep(WINDOW_SECONDS - (now - self.calls[0]) + 0.05)


@dataclass
class LgmPerson:
    """What LGM matches a lead on, beyond the address itself."""

    first_name: str | None = None
    last_name: str | None = None
    company_name: str | None = None
    company_url: str | None = None
    job_title: str | None = None
    #: Our contact id, written to LGM's `crm_id`. It is the join key for
    #: everything that comes back — webhook events, conversations, stats.
    crm_id: str | None = None


def split_name(full_name: str | None) -> tuple[str, str]:
    """LGM keeps first and last names apart; we keep one field."""
    parts = (full_name or "").split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


class LiveLgmAdapter:
    """Reads campaign metadata, writes leads, pauses. It cannot edit a sequence."""

    def __init__(self, api_key: str, *, base_url: str | None = None, client: Any = None):
        self._key = api_key
        self._base = (base_url or BASE_URL).rstrip("/")
        self._client = client
        self._limit = _RateLimit()

    # ------------------------------------------------------------------ http
    async def _request(self, method: str, path: str, **kwargs) -> dict:
        import httpx

        await self._limit.take()
        url = f"{self._base}{path}"
        headers = {"Authorization": f"Bearer {self._key}", "accept": "application/json"}
        client = self._client
        try:
            if client is None:
                # The OS trust store, not certifi — the same reason `probes.py`
                # gives: a corporate TLS-inspecting proxy's root is installed
                # system-wide and certifi has never heard of it, so certifi
                # verification fails on exactly the networks this runs on. It
                # failed here as `ConnectError`, which reads as "the provider is
                # down" and is the most misleading answer available.
                async with httpx.AsyncClient(
                    timeout=TIMEOUT_SECONDS, verify=_verify_context()
                ) as owned:
                    response = await owned.request(method, url, headers=headers, **kwargs)
            else:
                response = await client.request(method, url, headers=headers, **kwargs)
        except Exception as exc:  # noqa: BLE001 — one failure mode for the caller
            log.warning("lgm.transport_failed %s %s: %s", method, path, type(exc).__name__)
            raise LgmError(f"La Growth Machine could not be reached ({type(exc).__name__})") from exc

        if response.status_code in (401, 403):
            raise LgmError("La Growth Machine rejected the API key")
        if response.status_code == 429:
            raise LgmError("La Growth Machine is rate limiting this key — try again shortly")
        if response.status_code >= 400:
            # The status and the route, never the body: a rejection quotes the
            # request back, and that can carry the key or a prospect's address.
            log.warning("lgm.refused %s %s -> %s", method, path, response.status_code)
            raise LgmError(f"La Growth Machine refused {method} {path} ({response.status_code})")
        try:
            body = response.json()
        except ValueError as exc:
            raise LgmError(f"La Growth Machine returned a non-JSON body for {path}") from exc
        return body if isinstance(body, dict) else {"data": body}

    # --------------------------------------------------------------- reading
    async def members(self) -> list[dict]:
        """Who is in the workspace. Also the cheapest proof a key works."""
        return list((await self._request("GET", "/members")).get("members") or [])

    async def campaign_meta(self, lgm_campaign_id: str) -> LgmCampaignMeta:
        body = (await self._request("GET", f"/campaigns/{lgm_campaign_id}")).get("campaign") or {}
        if not body:
            raise LgmError(f"campaign {lgm_campaign_id} was not found in La Growth Machine")
        updated = body.get("modifiedAt")
        return LgmCampaignMeta(
            campaign_id=str(body.get("id") or lgm_campaign_id),
            status=str(body.get("status") or "unknown"),
            # LGM sends epoch milliseconds.
            updated_at=(
                datetime.fromtimestamp(updated / 1000, UTC) if isinstance(updated, int | float) else None
            ),
            channels=tuple(body.get("channels") or ()),
        )

    async def campaign_audience(self, lgm_campaign_id: str) -> tuple[str | None, str | None]:
        """The audience a campaign runs over, as (id, name). This is enrolment."""
        body = (await self._request("GET", f"/campaigns/{lgm_campaign_id}")).get("campaign") or {}
        audience = body.get("audience") or {}
        return (
            str(audience.get("id")) if audience.get("id") else body.get("audienceId"),
            audience.get("name") or body.get("audienceName"),
        )

    async def campaign_steps(self, lgm_campaign_id: str) -> list[dict]:
        """Every step of the campaign, not only the ones carrying a message.

        Undocumented, and it answers what `/messages` cannot. A template's
        `order` is its position among *templates*; a step's `position` is its
        place in the campaign. On the first account this was read against, the
        two message templates sat at positions 4 and 5 — so three earlier steps
        (a profile visit, a connection request, a wait) send nothing of ours
        and are invisible to `/messages` entirely.

        It also carries `templateName`, which is where the intent lives:
        "Not Accepted - Email" and "Accepted - DM" are not step one and step
        two of a sequence, they are two branches of one.
        """
        body = await self._request("GET", f"/campaigns/{lgm_campaign_id}/steps")
        return list(body.get("data") or [])

    async def campaign_messages(self, lgm_campaign_id: str) -> list[dict]:
        """Every step's template — what a shape's attribute map is checked against."""
        body = await self._request("GET", f"/campaigns/{lgm_campaign_id}/messages")
        return list(body.get("data") or [])

    async def audiences(self) -> list[dict]:
        body = await self._request("GET", "/audiences")
        return list(body.get("audiences") or body.get("data") or [])

    async def create_audience(self, name: str) -> dict:
        return await self._request("POST", "/audiences/create", json={"name": name})

    async def update_campaign_settings(self, lgm_campaign_id: str, **settings) -> dict:
        """Change a campaign's settings. Only the keys sent are touched.

        `POST`, not `GET` — reading them back is not offered at all, which is
        why probing this path with a GET answered 404 and looked like a route
        that did not exist.
        """
        if not settings:
            raise LgmError("nothing to update")
        return await self._request(
            "POST", f"/campaigns/{lgm_campaign_id}/settings", json=dict(settings)
        )

    async def set_campaign_audience(self, lgm_campaign_id: str, audience_id: str) -> str:
        """Point a campaign at an audience — the one window in which this is allowed.

        LGM permits `audienceId` to change **only while the campaign has never
        been started** (`READY`). After the first launch the audience it runs
        over is fixed, so this is checked before the write rather than after:
        the alternative is a 404 that reads like a missing route.
        """
        meta = await self.campaign_meta(lgm_campaign_id)
        status = meta.status.upper()
        if status != "READY":
            raise LgmError(
                f"campaign {lgm_campaign_id} is {status.lower()}; La Growth Machine only allows "
                "the audience to be changed before a campaign's first launch"
            )
        await self.update_campaign_settings(lgm_campaign_id, audienceId=audience_id)
        return audience_id

    async def remove_from_audience(self, *, audience: str, **identifier) -> None:
        """Take a lead out of an audience — the withdrawal LGM actually offers.

        Not a delete: the lead and its history stay. Being absent from the
        audience is what un-enrols them, exactly as being present enrolled
        them. Silently ignored when they were not in it.
        """
        if not identifier:
            raise LgmError("a lead needs an identifier to be removed from an audience")
        await self._request(
            "POST", "/leads/removefromaudience", json={"audience": [audience], **identifier}
        )

    async def lead_logs(self, lead_id: str, *, limit: int = 25, skip: int = 0) -> list[dict]:
        """What LGM actually did to this person, step by step.

        Each entry carries `campaignId`, `stepId`, `channel`, `status` and
        `createdAt` — which makes this the only place the real schedule can be
        observed. LGM publishes no step timing up front; it can be read off
        here after the fact, as evidence rather than configuration.
        """
        body = await self._request(
            "GET", f"/leads/{lead_id}/logs",
            params={"skip": str(skip), "limit": str(max(1, min(limit, 100)))},
        )
        return list(body.get("logs") or body.get("data") or [])

    async def audience_leads(self, audience_id: str) -> list[dict]:
        """Every lead in an audience, with the attributes actually stored.

        The only way to see what LGM holds for a person: there is no route to
        read one lead by id (`GET /leads/:id` is a 404). This is what answers
        "did our copy arrive" before a campaign is launched, rather than after
        somebody receives the wrong thing.

        Note for anything that writes here: an empty string does **not** clear
        an attribute. LGM reads `""` as "leave it alone", so copy from an
        earlier enrolment stays on the lead until something overwrites it.
        """
        body = await self._request("GET", f"/audiences/{audience_id}/leads")
        return list(body.get("data") or [])

    #: LGM caps this route at 25 and answers a **404** when asked for more — a
    #: validation error wearing the status code of a moved endpoint. Paged
    #: rather than asked for in one go, because the first attempt at 100 read
    #: as "the campaigns route no longer exists".
    PAGE = 25

    async def campaigns(self, *, max_pages: int = 20) -> list[dict]:
        """Every campaign in the account — what a shape is registered against."""
        found: list[dict] = []
        for page in range(max_pages):
            body = await self._request(
                "GET", "/campaigns",
                params={"skip": str(page * self.PAGE), "limit": str(self.PAGE)},
            )
            rows = list(body.get("campaigns") or body.get("data") or [])
            found.extend(rows)
            if len(rows) < self.PAGE:
                break
        return found

    async def conversations(self, lgm_campaign_id: str, *, since=None, limit: int = 25) -> list[dict]:
        """Inbox conversations for one campaign, newest first.

        Filtered by time where we have a watermark: polling the whole inbox on
        every sync would re-read the same history and spend the rate limit on
        it.
        """
        params: dict[str, str] = {"campaignIds": lgm_campaign_id, "limit": str(limit)}
        if since is not None:
            params["lastMessageAtFrom"] = str(int(since.timestamp() * 1000))
        body = await self._request("GET", "/conversations/search", params=params)
        return list(body.get("data") or [])

    async def conversation_messages(self, conversation_id: str) -> list[dict]:
        """Every message in one conversation, oldest first."""
        body = await self._request("GET", f"/conversations/{conversation_id}/messages")
        return list(body.get("data") or [])

    async def lead_stats(self, lgm_campaign_id: str) -> list[dict]:
        """Per-lead status in a campaign — contacted, replied, completed."""
        body = await self._request("GET", f"/campaigns/{lgm_campaign_id}/statsleads")
        return list(body.get("leads") or [])

    async def campaign_stats(self, lgm_campaign_id: str) -> dict:
        """The campaign's own totals, as LGM counts them."""
        body = await self._request("GET", f"/campaigns/{lgm_campaign_id}/stats")
        return dict(body.get("engagementStats") or {})

    # ------------------------------------------------------- inbox webhooks
    async def inbox_webhooks(self) -> list[dict]:
        body = await self._request("GET", "/inboxWebhooks")
        return list(body.get("data") or body.get("webhooks") or (body if isinstance(body, list) else []))

    async def register_inbox_webhook(self, *, url: str, name: str, campaigns: list[str] | None = None) -> dict:
        """Ask LGM to push inbox events to us.

        LGM signs nothing, so the URL itself is the credential: it carries an
        unguessable token, and the receiver treats every payload as a claim to
        be checked rather than a fact.
        """
        payload: dict = {"url": url, "name": name}
        if campaigns:
            payload["campaigns"] = campaigns
        return await self._request("POST", "/inboxWebhooks", json=payload)

    async def delete_inbox_webhook(self, webhook_id: str) -> None:
        await self._request("DELETE", f"/inboxWebhooks/{webhook_id}")

    # --------------------------------------------------------------- writing
    async def upsert_lead(
        self,
        *,
        email: str | None,
        linkedin_url: str | None,
        attributes: dict[str, str],
        audience: str | None = None,
        person: LgmPerson | None = None,
    ) -> LgmLead:
        """Create or update the lead, with its copy, in the campaign's audience.

        One call, as the protocol requires: the attributes *are* the message
        bodies, and a second round trip is a window in which a campaign can
        start half-written.
        """
        person = person or LgmPerson()
        if not email and not linkedin_url and not (person.first_name and person.last_name):
            raise LgmError("a lead needs an email, a LinkedIn URL, or a full name to be matched")

        payload: dict[str, Any] = {}
        if audience:
            payload["audience"] = audience
        if email:
            payload["proEmail"] = email
        if linkedin_url:
            payload["linkedinUrl"] = linkedin_url
        for key, value in (
            ("firstname", person.first_name),
            ("lastname", person.last_name),
            ("companyName", person.company_name),
            ("companyUrl", person.company_url),
            ("jobTitle", person.job_title),
            # Accepted by LGM and then discarded — a lead written with a
            # `crm_id` reads it back empty. Sent anyway: it costs one field,
            # an unrecognised key is refused outright so this one is real, and
            # their own CRM integrations populate it. Replies match on the
            # lead id we store at execution.
            ("crm_id", person.crm_id),
        ):
            if value:
                payload[key] = value

        written = dict(sorted(attributes.items())[:ATTRIBUTE_BUDGET])
        for name, value in written.items():
            if len(value) > ATTRIBUTE_MAX_CHARS:
                # Refused rather than sent: LGM stores the truncated text and
                # the half-sentence still goes out.
                raise LgmError(
                    f"{name} is {len(value)} characters; La Growth Machine allows "
                    f"{ATTRIBUTE_MAX_CHARS} per attribute"
                )
            # Translated at the boundary, which is the only place that should
            # know LGM's spelling.
            payload[wire_attribute(name)] = value

        body = await self._request("POST", "/leads", json=payload)
        lead = body.get("lead") or body.get("data") or body
        lead_id = lead.get("id") or lead.get("leadId")
        if not lead_id:
            raise LgmError("La Growth Machine accepted the lead but returned no id")
        return LgmLead(
            lead_id=str(lead_id), email=email, linkedin_url=linkedin_url, attributes=written
        )

    async def enrol(self, *, lead_id: str, lgm_campaign_id: str) -> str:
        """Confirm the campaign is in a state where this membership means something.

        There is nothing to call: membership *is* enrolment. What this can do
        is refuse to report success when the campaign is in a state that will
        never send.

        `READY` — never launched — is **not** such a state, though it reads
        like one. LGM refuses to launch a campaign whose audience is empty, so
        writing the leads is what makes the launch possible. Refusing here left
        the two ends waiting on each other.
        """
        meta = await self.campaign_meta(lgm_campaign_id)
        if meta.status.upper() in ("ARCHIVED", "DELETED"):
            raise LgmError(f"campaign {lgm_campaign_id} is {meta.status.lower()} and cannot send")
        if meta.status.upper() == "READY":
            # Recorded distinctly, so the execution record says what is true:
            # written and waiting for a person to launch it.
            return f"{lgm_campaign_id}:{lead_id}:awaiting_launch"
        return f"{lgm_campaign_id}:{lead_id}"

    async def stop_lead(self, *, lead_id: str, lgm_campaign_id: str) -> None:
        """Halt this person's remaining touches. The only post-enrolment lever."""
        await self._request(
            "POST", "/leads/status", json={"leadId": lead_id, "status": "PAUSED"}
        )

    async def stop_campaign(self, lgm_campaign_id: str) -> None:
        meta = await self.campaign_meta(lgm_campaign_id)
        if meta.status.upper() != "RUNNING":
            # Pausing a paused campaign is a 400 there. Nothing to do here.
            return
        await self._request(
            "POST", f"/campaigns/{lgm_campaign_id}/status", json={"status": "PAUSED"}
        )


#: LGM's campaign states, in our vocabulary. `ready` means never launched.
CAMPAIGN_STATUS = {
    "RUNNING": "active",
    "PAUSED": "paused",
    "READY": "ready",
    "ARCHIVED": "archived",
    "DELETED": "archived",
}
#: Not one of LGM's — ours, for a campaign that is no longer in the account at
#: all. A deleted campaign leaves a registration behind that looks perfectly
#: healthy: verified, mapped, an audience named. Nothing in a stored row can
#: tell you it has gone, which is why it has to be asked.
STATUS_MISSING = "missing"
#: How a step's template refers to a lead attribute.
ATTRIBUTE_PATTERN = re.compile(r"customAttribute(\d{1,2})", re.IGNORECASE)
#: The translation lives in `lgm.py`, beside the protocol, so the stub is held
#: to the same rule — see `lgm.wire_attribute`.

#: LGM's step channels, in ours. `LGM` is their own multi-channel step; it has
#: no subject line, so it is read as LinkedIn for the purpose of asking whether
#: one can be written.
STEP_CHANNELS = {"GOOGLE": "email", "EMAIL": "email", "LINKEDIN": "linkedin", "LGM": "linkedin"}
#: Which channels can show a subject line at all.
SUBJECT_CHANNELS = ("email",)


def read_templates(templates: list[dict], steps: list[dict] | None = None) -> ShapeCheck:
    """The mapping a campaign's step templates describe.

    One reader, shared by registering a shape and re-checking one, because two
    readers drift and the whole point of this mapping is that it is the same
    fact the send path uses.

    Body and subject are read **separately**. They are separate fields in LGM,
    and an attribute named in the subject template is the only way a subject
    line of ours can appear — writing one anywhere else sends nothing.
    """
    check = ShapeCheck()
    active = [t for t in templates if t.get("active", True)]
    check.steps = len(active)
    for template in active:
        step = int(template.get("order") or 0) + 1
        body_text = template.get("contentHtml") or ""
        subject_text = template.get("subjectHtml") or ""
        check.channel_by_step[step] = STEP_CHANNELS.get(
            str(template.get("channel") or "").upper(), "linkedin"
        )

        body = sorted({int(n) for n in ATTRIBUTE_PATTERN.findall(body_text)})
        subject = sorted({int(n) for n in ATTRIBUTE_PATTERN.findall(subject_text)})
        if body:
            check.body_by_step[step] = f"custom_attribute_{body[0]}"
        # An attribute used by both would put the body in the subject line.
        for n in subject:
            if n not in body:
                check.subject_by_step[step] = f"custom_attribute_{n}"
                break

        check.attributes_by_step[step] = sorted(
            {f"custom_attribute_{n}" for n in body + subject}
        )

    # `/campaigns/:id/steps` knows things `/messages` cannot: where a step sits
    # in the whole campaign, and what a person called it. Matched on template
    # id, because neither list promises the same order.
    by_template = {
        str(s.get("templateId")): s for s in (steps or []) if s.get("templateId")
    }
    for template in active:
        step = int(template.get("order") or 0) + 1
        found = by_template.get(str(template.get("id")))
        if found:
            check.step_meta[step] = {
                "position": found.get("position"),
                "type": found.get("type"),
                "name": found.get("templateName"),
            }
    return check


def labels_for(shape) -> dict[str, str]:
    """What to call each slot this shape uses: derived, then rep overrides.

    Derived from the stored mapping rather than remembered, so a template that
    moves `custom_attribute_1` from step 2's body to step 1's subject renames
    it without anybody re-labelling anything.
    """
    view = ShapeCheck()
    view.channel_by_step = {int(k): v for k, v in (shape.step_channels or {}).items()}
    view.body_by_step = {int(k): v for k, v in (shape.attribute_map or {}).items()}
    view.subject_by_step = {
        int(k): v for k, v in (shape.subject_attribute_map or {}).items()
    }
    return {**derive_labels(view), **(shape.slot_labels or {})}


def derive_labels(check: ShapeCheck) -> dict[str, str]:
    """A readable name per slot: `email 1 body`, `email 1 subject`.

    LGM lets these be named in its own interface and publishes the names on no
    route, so they are derived from what each slot is actually used for. That
    also keeps them right when a template changes — a name read once would not.
    """
    labels: dict[str, str] = {}
    # Every step that maps anything, not only those whose channel is known:
    # a shape registered before channels were stored still deserves a name,
    # and gets "step 2 body" until somebody re-checks it against LGM.
    steps = set(check.channel_by_step) | set(check.body_by_step) | set(check.subject_by_step)
    for step in sorted(steps):
        what = check.channel_by_step.get(step) or "step"
        prefix = f"{what} {step}" if what != "step" else f"step {step}"
        if body := check.body_by_step.get(step):
            labels[body] = f"{prefix} body"
        if subject := check.subject_by_step.get(step):
            labels[subject] = f"{prefix} subject"
    return labels


@dataclass
class ShapeCheck:
    """What the live campaign says about a registered shape."""

    status: str | None = None
    updated_at: datetime | None = None
    channels: tuple[str, ...] = ()
    audience_id: str | None = None
    audience_name: str | None = None
    steps: int = 0
    #: step order → every attribute its templates read, body and subject alike.
    #: Kept for the mismatch check, which only asks "is our slot among them".
    attributes_by_step: dict[int, list[str]] = field(default_factory=dict)
    #: The mapping proper, read apart because body and subject are separate
    #: fields in LGM and a subject can only carry our words if its own template
    #: names an attribute. These are what a registration adopts.
    body_by_step: dict[int, str] = field(default_factory=dict)
    subject_by_step: dict[int, str] = field(default_factory=dict)
    #: step order → `email` or `linkedin`, in our vocabulary.
    channel_by_step: dict[int, str] = field(default_factory=dict)
    #: step order → what LGM calls this step and where it sits in the campaign:
    #: `{"position": 4, "type": "GOOGLE_SEND_EMAIL", "name": "Not Accepted - Email"}`.
    #: The name is the only place a branch announces itself as one.
    step_meta: dict[int, dict] = field(default_factory=dict)
    #: Everything that disagrees with what we have registered.
    findings: list[str] = field(default_factory=list)
    #: Slots that moved since this shape was registered. Not findings: a
    #: re-check adopts them, so they describe what was *corrected*. They still
    #: matter — copy already drafted carries the slot it was written for.
    changes: list[str] = field(default_factory=list)

    @property
    def sound(self) -> bool:
        return not self.findings


async def check_shape(adapter: LiveLgmAdapter, shape) -> ShapeCheck:
    """Read the campaign and its templates, and compare them with the registration.

    This is what `verified_by` used to mean by hand. The templates are the part
    worth reading: they name the attributes each step actually sends, so a map
    that points step 3 at an attribute nothing reads — or at one another step
    also reads — is visible here rather than after a prospect gets the wrong
    message.
    """
    try:
        meta = await adapter.campaign_meta(shape.lgm_campaign_id)
    except LgmError as exc:
        # Deleted, or moved out of this account. Either way nothing we hold
        # about it is still true, so the check ends here rather than reporting
        # on templates it cannot read.
        return ShapeCheck(
            status=STATUS_MISSING,
            findings=[
                f"campaign {shape.lgm_campaign_id} is no longer in the La Growth Machine "
                f"account — it was deleted or moved ({exc})"
            ],
        )
    check = ShapeCheck(
        status=CAMPAIGN_STATUS.get(meta.status.upper(), meta.status.lower()),
        updated_at=meta.updated_at,
        channels=meta.channels,
    )
    check.audience_id, check.audience_name = await adapter.campaign_audience(
        shape.lgm_campaign_id
    )

    # One reader for registering and re-checking alike: two would drift, and
    # this mapping is the same fact the send path writes against.
    templates = await adapter.campaign_messages(shape.lgm_campaign_id)
    try:
        steps = await adapter.campaign_steps(shape.lgm_campaign_id)
    except (LgmError, AttributeError):
        # Undocumented, so a plan or an older adapter may not serve it. The
        # mapping does not depend on it; only the labelling is poorer.
        steps = []
    read = read_templates(templates, steps)
    check.steps = read.steps
    check.attributes_by_step = read.attributes_by_step
    check.body_by_step = read.body_by_step
    check.subject_by_step = read.subject_by_step
    check.channel_by_step = read.channel_by_step
    check.step_meta = read.step_meta

    if check.steps and check.steps != shape.touch_count:
        check.findings.append(
            f"the LGM campaign has {check.steps} active steps; this shape registers "
            f"{shape.touch_count}"
        )
    # `ready` is deliberately not a finding. It means never launched, which is
    # the normal state of a campaign waiting for its first audience — and a
    # finding here makes `sound` false, which withholds `verified_at`, which
    # blocks enrolment for never having been verified. The campaign then
    # cannot be filled, so it cannot be launched, so it stays `ready`: the
    # same deadlock as §41, wearing a different hat. Enrolment surfaces the
    # state as a warning instead, where it belongs.
    if check.status in ("paused", "archived"):
        check.findings.append(f"the LGM campaign is {check.status}")
    if shape.lgm_audience_name and check.audience_name and shape.lgm_audience_name != check.audience_name:
        check.findings.append(
            f"the campaign now runs over audience {check.audience_name!r}; this shape writes "
            f"leads into {shape.lgm_audience_name!r}"
        )

    mapped = {int(k): v for k, v in (shape.attribute_map or {}).items() if str(k).isdigit()}
    # `getattr`, because this takes any object shaped like a registration —
    # including ones built before subjects were mapped at all.
    subjects = {
        int(k): v
        for k, v in (getattr(shape, "subject_attribute_map", None) or {}).items()
        if str(k).isdigit()
    }
    for step, attributes in check.attributes_by_step.items():
        ours = mapped.get(step)
        live = check.body_by_step.get(step)
        if ours and live and ours != live:
            check.changes.append(f"step {step}'s body moved from {ours} to {live}")
        elif live and not ours:
            check.changes.append(f"step {step}'s body reads {live}")
        if ours and not attributes:
            check.findings.append(
                f"step {step}'s template reads no lead attribute, so the copy written to {ours} "
                "would never appear"
            )

    for step, live in check.subject_by_step.items():
        ours = subjects.get(step)
        if ours != live:
            check.changes.append(
                f"step {step}'s subject "
                + (f"moved from {ours} to {live}" if ours else f"now reads {live}")
            )
    for step, ours in subjects.items():
        if step not in check.subject_by_step:
            check.changes.append(
                f"step {step}'s subject no longer reads an attribute — a written subject "
                f"would not appear"
            )
    return check


async def from_credentials(session, *, mode_checked: bool = False) -> LiveLgmAdapter | None:
    """The live adapter, or None when no usable key is stored.

    Never returns a live client in demo mode — that decision belongs to the
    caller and is asserted here as well, because this is the one client in the
    system that can reach a real person.
    """
    from sqlalchemy import select

    from app.models.config import IntegrationCredential
    from app.services import crypto, demo

    if not mode_checked and await demo.is_demo(session):
        return None

    async def stored(kind: str) -> str | None:
        row = (
            await session.execute(
                select(IntegrationCredential).where(
                    IntegrationCredential.provider == "lgm",
                    IntegrationCredential.credential_type == kind,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        try:
            return crypto.decrypt(row.value_encrypted).reveal()
        except crypto.CredentialError:
            log.warning("lgm_client.undecryptable kind=%s", kind)
            return None

    key = await stored("api_key")
    if not key:
        return None
    return LiveLgmAdapter(key, base_url=await stored("base_url") or None)
