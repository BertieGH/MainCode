"""Asking a provider whether a credential actually works.

The setup gate is only worth having if "tested" means something. Decrypting a
stored value proves `SECRET_KEY` has not changed — it says nothing about the
key, and it reports `valid` for one that was mistyped, revoked, or belongs to
an exhausted account. That is precisely the state a rep is in when the pipeline
silently stops producing anything.

So every probe here makes a real request, and the interesting engineering is in
how failures are *classified*. Three outcomes look identical in a naive
implementation and mean completely different things:

* **401 / 403** — the provider rejected this key. Re-issue it.
* **404** — the endpoint we probe has moved. The key may be perfectly good;
  this is *our* staleness, and saying "your key is invalid" would send someone
  to rotate a working credential.
* **429 / 5xx** — reachable, temporarily unavailable. Not a credential problem.
* **A TLS trust failure** — the host is reachable and its certificate does not
  chain to a root we trust. On a corporate network that means a TLS-inspecting
  proxy, and the fix is a trust store, not a new key.

That last one was found the hard way. Every probe here uses the **operating
system's** certificate store rather than certifi's bundle, because a corporate
proxy's root lives in the OS store and not in certifi. Without it these probes
fail on exactly the networks this product is sold into — and they failed as
`ConnectError`, which reads as "the provider is down" and is the most
misleading answer available. The Anthropic probe never showed the problem
because the SDK enables `truststore` for itself.

Nothing here echoes a provider's response body. A rejection body can quote the
key that was sent, and these strings are returned by an API — `docs/01`
invariant 9.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.provider_catalogue import BY_KEY, ProbeSpec

log = logging.getLogger(__name__)

#: Probes must be fast. This runs while somebody watches a spinner on the setup
#: screen, and a provider that takes longer than this to answer an auth check
#: is not in a state worth calling "verified".
TIMEOUT_SECONDS = 12.0


#: Why a test ended as it did. The UI maps these to labels, so `status` no
#: longer has to carry meaning it cannot express — `expired` alone cannot
#: distinguish "this key has expired" from "this account has no credit", and
#: those are different sentences and different actions.
CODES = (
    "ok",              # the provider accepted the key
    "rate_limited",    # reachable; counted as working
    "rejected",        # the provider refused this key — re-issue it
    "no_credit",       # the key works, the account cannot be billed
    "unreachable",     # network or timeout — nothing was learned
    "endpoint_moved",  # our probe URL is stale, not their key
    "provider_error",  # the provider failed on its side
    "bad_request",     # our request shape is wrong — the key was not tested
    "tls_untrusted",   # reachable, but its certificate is not trusted here
    "not_checkable",   # no probe exists for this provider
    "demo",            # demo mode; nothing was contacted
)


@dataclass
class Probe:
    """What we learned. `ok` gates setup; `detail` is shown to a person."""

    ok: bool
    detail: str
    #: One of `CODES`. Carried separately from `detail` so the UI can decide on
    #: wording without parsing a sentence.
    code: str = "ok"
    #: True when the failure is ours (a stale endpoint, no adapter) rather than
    #: the credential's. The UI says "we could not check" instead of
    #: "your key is bad", which are different instructions to the reader.
    inconclusive: bool = False
    #: For outcomes the two booleans above cannot express. The case that forced
    #: it: an exhausted credit balance is not the key's fault and not
    #: inconclusive — the key is genuinely good and genuinely cannot be used.
    #: Deriving `invalid` there put "invalid" in the status column next to a
    #: detail line reading "the key is valid", which is a screen nobody can act
    #: on.
    status_override: str | None = None

    @property
    def status(self) -> str:
        if self.status_override:
            return self.status_override
        if self.ok:
            return "valid"
        return "untested" if self.inconclusive else "invalid"


async def probe(provider: str, api_key: str) -> Probe:
    """Verify one credential. Never raises — a probe reports, it does not fail."""
    if provider == "anthropic":
        return await _probe_anthropic(api_key)

    cat = BY_KEY.get(provider)
    if cat is None:
        return Probe(
            False,
            "no live check for a provider we do not ship — the value is stored "
            "and decrypts, but nothing has confirmed it works",
            code="not_checkable",
            inconclusive=True,
        )
    if cat.probe is None:
        return Probe(
            False,
            f"no live check for {cat.label} yet — the value is stored and decrypts",
            code="not_checkable",
            inconclusive=True,
        )
    return await _probe_http(cat.probe, api_key, label=cat.label)


async def _probe_anthropic(api_key: str) -> Probe:
    """The smallest real call that proves a key works.

    Uses the SDK rather than a raw request so it exercises the same client the
    stages do — a probe that passes through a different path can pass while the
    real one fails on a proxy, a base URL override, or a TLS trust store.
    """
    try:
        import anthropic
    except ImportError:
        return Probe(
            False,
            "the anthropic SDK is not installed",
            code="not_checkable",
            inconclusive=True,
        )

    try:
        client = (
            anthropic.AsyncAnthropic(api_key=api_key)
            if api_key
            else anthropic.AsyncAnthropic()
        )
        await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
    except Exception as exc:  # noqa: BLE001 — a probe reports, it never propagates
        name = type(exc).__name__
        # Logged in full, returned as a class. Without this a bug in the probe
        # is indistinguishable from a bad key.
        log.warning("probe.anthropic_failed error=%s: %s", name, exc)
        if "Authentication" in name or "PermissionDenied" in name:
            return Probe(False, "the provider rejected this key", code="rejected")
        if "RateLimit" in name:
            return Probe(True, "reachable — rate limited right now", code="rate_limited")
        if "credit balance" in str(exc).lower():
            # The key is good and the account cannot be billed. Not `invalid`
            # — re-issuing the key would change nothing — and not
            # inconclusive, because we know exactly what is wrong.
            return Probe(
                False,
                "the key itself is accepted — the workspace has no credit balance. "
                "Top it up in the Anthropic console; re-issuing the key will not help.",
                code="no_credit",
                status_override="expired",
            )
        if "APIConnection" in name or "Timeout" in name:
            return Probe(
                False, "could not reach the provider", code="unreachable", inconclusive=True
            )
        return Probe(False, f"the provider returned {name}", code="provider_error")

    return Probe(True, "reachable — the provider accepted this key", code="ok")


def _verify_context():
    """The certificate store to validate against.

    The OS store, not certifi. A corporate TLS-inspecting proxy presents its
    own certificate, its root is installed system-wide, and certifi has never
    heard of it — so certifi-based verification fails on precisely the networks
    an enterprise product runs on. `truststore` is already a dependency; the
    Anthropic SDK uses it, which is why only that probe ever worked.

    Falls back to the default when truststore is unavailable rather than
    failing: a working probe on a simple network beats no probe at all.
    """
    try:
        import ssl

        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # noqa: BLE001 — fall back to httpx's default
        log.info("probe.truststore_unavailable falling back to the bundled roots")
        return True


async def _probe_http(spec: ProbeSpec, api_key: str, *, label: str) -> Probe:
    """A declarative auth check. Reads nothing, writes nothing, changes nothing."""
    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx ships with the SDK
        return Probe(
            False, "httpx is not installed", code="not_checkable", inconclusive=True
        )

    headers = {spec.header: spec.value_template.format(key=api_key)}
    headers.update(spec.extra_headers)

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, verify=_verify_context()
        ) as client:
            response = await client.request(spec.method, spec.url, headers=headers)
    except Exception as exc:  # noqa: BLE001 — a probe reports, it never propagates
        log.warning(
            "probe.http_failed provider=%s error=%s: %s", label, type(exc).__name__, exc
        )
        return _classify_transport(exc, label=label)

    return _classify(
        response.status_code, label=label, url=spec.url, spec=spec, body=response.text
    )


def _flag_is_true(body: str, flag: str) -> bool:
    """Whether a named JSON field in the body is truthy.

    Parsed rather than substring-matched: `"is_logged_in":false` contains the
    field name, so a substring check would read every rejection as a success —
    which is the bug this function exists to close, in a slightly different
    disguise.
    """
    import json

    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return False
    return bool(isinstance(payload, dict) and payload.get(flag))


def _classify_transport(exc: Exception, *, label: str) -> Probe:
    """A connection that never completed. Which kind matters.

    "Could not reach" and "reachable, certificate not trusted" send somebody to
    completely different places — the network team, or the trust store — and
    collapsing them into the first is what hid this bug for a whole build.
    """
    text = str(exc)
    if "CERTIFICATE_VERIFY_FAILED" in text or "SSLCertVerification" in text:
        return Probe(
            False,
            f"{label} is reachable, but its certificate is not trusted by this "
            "machine — usually a corporate TLS-inspecting proxy whose root is "
            "not installed for this process. The key was not tested.",
            code="tls_untrusted",
            inconclusive=True,
        )
    return Probe(
        False,
        f"could not reach {label} — {type(exc).__name__}",
        code="unreachable",
        inconclusive=True,
    )


def _classify(
    status: int,
    *,
    label: str,
    url: str,
    spec: ProbeSpec | None = None,
    body: str = "",
) -> Probe:
    """Turn a response into an instruction for a person.

    Split out so the classification is testable without a network — it is the
    part with the actual judgement in it.
    """
    if 200 <= status < 300:
        # A 200 does not always mean authenticated. Apollo returns one for any
        # key and puts the answer in the body.
        if (
            spec is not None
            and spec.success_flag
            and not _flag_is_true(body, spec.success_flag)
        ):
            return Probe(
                False,
                f"{label} answered, but reported this key as not signed in",
                code="rejected",
            )
        return Probe(True, f"reachable — {label} accepted this key", code="ok")
    if status in (401, 403) or (spec is not None and status in spec.rejects_with):
        return Probe(False, f"{label} rejected this key", code="rejected")
    if status == 404:
        # Our staleness, not their key. Naming the URL is the only way whoever
        # reads this can fix it.
        return Probe(
            False,
            f"the {label} endpoint we check has moved ({url}) — the key may be "
            "fine; this check needs updating",
            code="endpoint_moved",
            inconclusive=True,
        )
    if status == 429:
        return Probe(
            True, f"reachable — {label} is rate limiting right now", code="rate_limited"
        )
    if status >= 500:
        return Probe(
            False,
            f"{label} returned a server error — try again shortly",
            code="provider_error",
            inconclusive=True,
        )
    # 400 and friends: the request shape is wrong, which is ours, not theirs.
    return Probe(
        False,
        f"{label} returned HTTP {status} for our check — the key was not tested",
        code="bad_request",
        inconclusive=True,
    )
