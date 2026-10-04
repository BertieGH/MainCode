"""Is this installation actually able to do anything yet.

Three external dependencies are mandatory, and the application cannot do its
job without any one of them:

* **enrichment** — turns a name into a reachable contact. Without one, research
  produces accounts nobody can be written to.
* **llm** — turns evidence into signals, strategy and copy. Without one,
  nothing downstream of a raw web page exists.
* **outreach** — actually sends. Without it the pipeline stops at approval.

Everything else is configuration you can get wrong and fix. These three you
cannot get *started* without, so they are gated rather than warned about.

**Readiness is derived, never stored.** A stored "setup complete" flag is a
claim about the past: a key gets revoked, a workspace runs out of credit, and
the flag still says ready while every run fails. Computing it from the
credential rows means the gate reflects what is true now, and re-opens by
itself when something breaks.

**Verified means a real round-trip.** A credential that merely decrypts proves
`SECRET_KEY` has not changed and nothing else. Counting that as ready would
make the gate theatre — it would pass for a mistyped key and the first symptom
would be a failed run. Where we cannot check for real, the slot is reported as
`unverified` and says so, rather than being quietly promoted.

**A verified key and a usable provider are different things**, and the gate
treats them differently by kind, which is deliberate rather than sloppy:

* For `llm`, a verified key on a vendor with no adapter is a live foot-gun —
  every stage would raise `NoAdapterError` on the first run. An alternative
  exists today, so requiring an adapter is an instruction somebody can act on.
  It blocks.
* For `enrichment` and `outreach`, the work adapters are tracked build items
  (`docs/08` Phase 11 for LGM). Blocking on those would lock the application
  on work that has nothing to do with configuring a credential, so a verified
  key satisfies the slot and the missing adapter travels with it as a
  **warning**.

The asymmetry is the honest reading of "is there anything the user can do
about this".

**Demo mode short-circuits all of it**, by satisfying each slot with a named
stub rather than a credential. See `app/services/demo.py` for why that is not
done by writing fake rows into `integration_credential`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import EnrichmentConfig, IntegrationCredential
from app.services import demo
from app.services import provider_catalogue as catalogue
from app.services.provider_catalogue import MANDATORY_KINDS, Kind

#: What has to be connected before any useful work can happen.
#:
#: Outreach is deliberately absent. La Growth Machine is where a sequence is
#: *executed*; it is not an enrichment provider and appears in no waterfall, so
#: gating research, import and enrichment on it blocked cheap, reversible steps
#: to prevent a disappointment three stages later — and could not even prevent
#: that, since the outreach routes have their own gate.
WORKABLE_KINDS: tuple[Kind, ...] = ("llm", "enrichment")

#: What each slot is called on screen, and why it is mandatory. Kept next to
#: the logic so a slot cannot be added without a reason for it existing.
SLOT_COPY: dict[Kind, tuple[str, str]] = {
    "enrichment": (
        "Contact enrichment",
        "Turns a name into a reachable contact. At least one provider is "
        "required; add more as waterfall fallbacks.",
    ),
    "llm": (
        "Model provider",
        "Reads evidence and writes signals, strategy and copy. At least one "
        "key with a working adapter is required.",
    ),
    "outreach": (
        "Outreach delivery",
        "Enrols approved sequences and sends them. Nothing leaves this system "
        "without it.",
    ),
}


@dataclass
class CredentialState:
    """One stored credential, as the setup screen needs to see it."""

    provider: str
    label: str
    status: str
    last_four: str | None = None
    console_url: str | None = None
    #: Whether an adapter exists to do this provider's actual work. Storing
    #: and verifying its key is allowed either way; relying on it is not, and
    #: the difference has to be visible.
    runnable: bool = True
    #: Whether the key can be checked against the vendor at all. False means
    #: Test cannot prove anything, so this credential can never be verified and
    #: therefore can never satisfy a slot.
    verifiable: bool = True
    #: Why the last test ended as it did, for the badge and its tooltip.
    last_test_code: str | None = None
    last_test_detail: str | None = None

    @property
    def verified(self) -> bool:
        return self.status == "valid"


@dataclass
class Slot:
    kind: Kind
    title: str
    why: str
    credentials: list[CredentialState] = field(default_factory=list)

    @property
    def satisfied(self) -> bool:
        """A verified credential — plus an adapter, where that is actionable.

        See the module docstring for why `llm` is stricter than the other two.
        """
        verified = [c for c in self.credentials if c.verified]
        if not verified:
            return False
        if self.kind == "llm":
            return any(c.runnable for c in verified)
        return True

    @property
    def warning(self) -> str | None:
        """Satisfied, but something will still fail later.

        Separate from `blocker` because it must not gate — and separate from
        silence because "connected" would otherwise imply "working", and the
        first person to discover otherwise would be mid-campaign.
        """
        if not self.satisfied:
            return None
        pending = [c.label for c in self.credentials if c.verified and not c.runnable]
        if not pending:
            return None
        return (
            f"{', '.join(pending)} is connected and verified, but the client that "
            f"actually performs {self.title.lower()} is not built yet — the key is "
            "ready and the integration is still pending."
        )

    @property
    def state(self) -> str:
        """`missing` / `unverified` / `ready` — three different instructions.

        `unverified` is the one worth separating out. "You have not added a key"
        and "you added one and it has not passed a live check" send the reader
        to completely different places, and collapsing them into "not ready"
        makes the second look like the first.
        """
        if self.satisfied:
            return "ready"
        if self.credentials:
            return "unverified"
        return "missing"

    @property
    def blocker(self) -> str | None:
        if self.satisfied:
            return None
        if not self.credentials:
            return f"No {self.title.lower()} provider is configured."

        uncheckable = [c for c in self.credentials if not c.verifiable]
        if len(uncheckable) == len(self.credentials):
            names = ", ".join(c.label for c in uncheckable)
            return (
                f"{names} cannot be checked by this build, so its key can never "
                "be verified. Add a provider that can."
            )

        verified = [c for c in self.credentials if c.verified]
        if verified and self.kind == "llm":
            # Verified, and nothing can call it. Names the providers that do
            # work rather than one of them, so the message stays true as
            # adapters are added.
            names = ", ".join(c.label for c in verified)
            usable = ", ".join(
                p.label for p in catalogue.of_kind("llm") if p.runnable
            )
            return (
                f"{names} is verified, but no stage can run on it — this build has "
                f"model adapters for {usable}. Add a key for one of those, or the "
                "pipeline fails on its first call."
            )

        # A key that works on an account that cannot be billed. "Run Test
        # again" is the wrong instruction — it will keep failing, and the fix
        # is somewhere this application cannot reach.
        expired = [c for c in self.credentials if c.status == "expired"]
        if len(expired) == len(self.credentials):
            names = ", ".join(c.label for c in expired)
            return (
                f"{names} is reachable but the account cannot be used — usually "
                "an exhausted balance or a suspended workspace. Re-testing will "
                "not change it; fix it with the provider, or add another."
            )

        rejected = [c for c in self.credentials if c.status == "invalid"]
        if len(rejected) == len(self.credentials):
            names = ", ".join(c.label for c in rejected)
            return f"{names} rejected the stored key. Re-issue it and paste the new one."

        return (
            f"{self.title} is configured but not verified. Run Test on it — a "
            "stored key that has never round-tripped is not proof of anything."
        )


@dataclass
class Readiness:
    slots: list[Slot] = field(default_factory=list)
    #: `production` or `demo`. Returned so every screen can say which one it is
    #: looking at — an unlocked menu means two very different things.
    mode: str = "production"
    #: Runs produced while in demo mode. Non-zero in production is the state
    #: worth surfacing: fixture evidence sitting alongside real evidence.
    demo_runs: int = 0
    #: The waterfall order, so the setup screen can show it where it is decided
    #: rather than on a separate page nobody visits.
    enrichment_order: list[str] = field(default_factory=list)
    #: Stored credentials belonging to no slot — a provider name this build
    #: cannot classify, which in practice means a typo.
    #:
    #: Reported rather than dropped. Providers are typeable, so `appollo` is one
    #: keystroke away from `apollo`; the row is then stored and encrypted, can
    #: never be probed, can never satisfy anything — and, because every screen
    #: renders credentials per slot, was invisible. An invisible row cannot be
    #: deleted, so a live secret sat in the database with no way to remove it
    #: short of SQL. Surfacing them is what makes the delete button reachable.
    unrecognised: list[CredentialState] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        """Everything connected, including outreach.

        Kept as the whole-installation answer, but **not** what gates ordinary
        work any more — see `satisfies`. A missing La Growth Machine key stops
        sending; it has nothing to do with parsing a CSV or asking Apollo for
        an address, and blocking those on it stopped a usable installation
        from being used.
        """
        return all(s.satisfied for s in self.slots) and not self.requirements

    @property
    def workable(self) -> bool:
        """Can useful work happen at all?

        LLM and enrichment. Everything up to a draft — import, verify,
        research, qualify, strategise — needs these two and nothing else. This
        is what the navigation locks on, so an installation missing only its
        outreach credential is usable rather than sealed.
        """
        return self.satisfies(*WORKABLE_KINDS)

    def satisfies(self, *kinds: Kind) -> bool:
        """Are these particular capabilities all connected?

        The configuration requirements count against every capability, not one:
        a service with no ICP blocks enrichment and strategy alike, and it is
        not a credential so it belongs to no slot.
        """
        if self.requirements:
            return False
        return all(
            (slot := self.slot(kind)) is not None and slot.satisfied for kind in kinds
        )

    def blockers_for(self, *kinds: Kind) -> list[str]:
        """Why these capabilities are not available, and nothing else's reasons.

        Reporting every blocker would tell somebody trying to enrich that they
        need an outreach credential, which is the confusion this split exists
        to remove.
        """
        found = [
            b
            for kind in kinds
            if (slot := self.slot(kind)) is not None and (b := slot.blocker)
        ]
        return found + list(self.requirements)

    #: Configuration that must exist before the pipeline can spend anything,
    #: as ready-made blocker sentences. A second category alongside the provider
    #: slots: those are credentials, these are decisions nobody has made yet.
    #: A key connects you to a vendor; it does not tell the vendor who to look
    #: for.
    requirements: list[str] = field(default_factory=list)

    @property
    def blockers(self) -> list[str]:
        return [b for s in self.slots if (b := s.blocker)] + list(self.requirements)

    @property
    def warnings(self) -> list[str]:
        """Things that will fail later. Reported even when `ready` is true."""
        return [w for s in self.slots if (w := s.warning)]

    def slot(self, kind: Kind) -> Slot | None:
        return next((s for s in self.slots if s.kind == kind), None)


async def evaluate(session: AsyncSession) -> Readiness:
    """Compute the gate from what is stored right now."""
    mode = await demo.current_mode(session)
    demo_runs = await demo.demo_run_count(session)

    if mode == demo.DEMO:
        # Satisfied by stubs, and labelled as stubs on every screen. No
        # credential row is read, written or invented.
        return Readiness(
            mode=mode,
            demo_runs=demo_runs,
            slots=[
                Slot(
                    kind=kind,
                    title=SLOT_COPY[kind][0],
                    why=SLOT_COPY[kind][1],
                    credentials=[
                        CredentialState(
                            provider=demo.BY_KIND[kind].key,
                            label=demo.BY_KIND[kind].label,
                            status="valid",
                            runnable=True,
                            verifiable=True,
                        )
                    ],
                )
                for kind in MANDATORY_KINDS
            ],
            enrichment_order=[p.key for p in demo.DEMO_PROVIDERS if p.kind == "enrichment"],
        )

    rows = list(
        (
            await session.execute(
                select(IntegrationCredential).where(
                    IntegrationCredential.credential_type == "api_key"
                )
            )
        ).scalars()
    )

    by_kind: dict[Kind, list[CredentialState]] = {k: [] for k in MANDATORY_KINDS}
    unrecognised: list[CredentialState] = []
    for row in rows:
        cat = catalogue.BY_KEY.get(row.provider)
        state = CredentialState(
            provider=row.provider,
            label=cat.label if cat else row.provider,
            status=row.status,
            last_four=row.last_four,
            console_url=row.console_url,
            runnable=catalogue.is_runnable(row.provider),
            verifiable=catalogue.is_verifiable(row.provider),
            last_test_code=row.last_test_code,
            last_test_detail=row.last_test_detail,
        )
        kind = catalogue.kind_of(row.provider)
        if kind not in by_kind:
            # A CRM key, or a provider somebody added that we cannot classify.
            # Neither can satisfy a mandatory slot, and pretending otherwise
            # would let an unrelated key unlock the application — so it stays
            # out of `by_kind`. It does *not* stay out of the response: a row
            # nothing can see is a row nobody can delete.
            unrecognised.append(state)
            continue
        by_kind[kind].append(state)

    order = (
        await session.execute(
            select(EnrichmentConfig.provider_order).where(
                EnrichmentConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()

    requirements = await _configuration_requirements(session)

    return Readiness(
        mode=mode,
        demo_runs=demo_runs,
        slots=[
            Slot(
                kind=kind,
                title=SLOT_COPY[kind][0],
                why=SLOT_COPY[kind][1],
                credentials=by_kind[kind],
            )
            for kind in MANDATORY_KINDS
        ],
        enrichment_order=list(order or []),
        unrecognised=unrecognised,
        requirements=requirements,
    )


async def _configuration_requirements(session: AsyncSession) -> list[str]:
    """What has been left undecided, as sentences a rep can act on.

    Credentials are not the only prerequisite. A provider key connects you to a
    vendor; it does not tell the vendor who to look for. Enrichment without a
    service runs alphabetically over every unverified contact and pays a
    metered provider to find a junior developer when the service needed the
    CTO — and the list then looks finished. So something to sell, and an ICP
    that says who to sell it to, are as much a precondition as an API key.
    See `docs/11`.
    """
    from app.models.config import (
        IcpProfile,
        IcpProfileVersion,
        ServiceCatalog,
        service_icp_link,
    )
    from app.services.verification import target_personas

    services = list(
        (
            await session.execute(
                select(ServiceCatalog).where(ServiceCatalog.is_active.is_(True))
            )
        ).scalars()
    )
    if not services:
        return [
            "No active service is defined. Nothing can be researched, enriched or "
            "pitched until there is something to sell."
        ]

    # A service needs no ICP of its own. What has to exist is at least one ICP
    # that is for an active service, has an *active version*, and names buyer
    # personas: a profile nobody has written, or one naming nobody, would pass
    # a looser check and then hand enrichment and research no one to look for.
    rows = (
        await session.execute(
            select(IcpProfile.name, IcpProfileVersion.definition)
            .join(IcpProfileVersion, IcpProfileVersion.icp_profile_id == IcpProfile.id)
            .join(service_icp_link, service_icp_link.c.icp_profile_id == IcpProfile.id)
            .where(
                IcpProfileVersion.is_active.is_(True),
                service_icp_link.c.service_id.in_([s.id for s in services]),
            )
        )
    ).all()
    if not rows:
        return [
            "No ICP is for an active product or service yet. Create one under ICP "
            "profiles and pick what it is for — enrichment and research need to know "
            "who to look for."
        ]
    if not any(target_personas(definition) for _, definition in rows):
        names = ", ".join(sorted({name for name, _ in rows}))
        return [
            f"No ICP names its buyer personas yet ({names}). Add them under ICP "
            "profiles — enrichment and research pick people by them."
        ]
    # One usable ICP is enough to work with. Others missing personas are a
    # warning for their own screen, not a reason to lock the application.
    return []


class NotReadyError(RuntimeError):
    """A pipeline action was attempted before the mandatory setup is done.

    Raised at the API boundary rather than deep in a service, so the message
    can name every missing dependency at once. Telling somebody about one
    blocker, then the next, then the next, is three round-trips through a
    screen they did not want to visit.
    """

    def __init__(self, blockers: list[str], missing: list[str] | None = None):
        self.blockers = blockers
        #: The capability kinds actually unsatisfied — `["outreach"]`, not
        #: every kind the route asked about. The caller builds its message
        #: from this so it names what is broken rather than what is needed.
        self.missing = missing or []
        super().__init__(
            "Setup is incomplete: " + " ".join(blockers)
        )


async def require_ready(session: AsyncSession, *kinds: Kind) -> Readiness:
    """Raise unless the named capabilities are connected.

    `kinds` is required in practice: called bare it checks the whole
    installation, which is what every route used to do and why importing a CSV
    needed a sending credential.
    """
    state = await evaluate(session)
    wanted = kinds or MANDATORY_KINDS
    if not state.satisfies(*wanted):
        raise NotReadyError(
            state.blockers_for(*wanted),
            missing=[k for k in wanted if not state.satisfies(k)],
        )
    return state
