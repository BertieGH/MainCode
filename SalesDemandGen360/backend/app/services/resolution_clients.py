"""The sources tier 0 can ask, behind the `Resolver` protocol.

Two, and they answer different questions:

* **`apollo_org`** — given a domain, who is this? Confirmed live: `POST
  /organizations/enrich` returns `linkedin_url`, `industry`,
  `estimated_num_employees`, `founded_year` and more. It needs a domain to
  start, so it cannot help a row that has only a company name.
* **`llm_web`** — given a name, what is their domain? A web-search call, which
  is the one fallback already proven in this codebase because the research
  stages use the same tooling.

Apollo first, and not only because it is cheaper. It answers from a database
and returns a confidence we can reason about; the model answers from search
results and is the right tool only when there is nothing to look up.

**Apollo has no usage endpoint.** `/usage_stats/api_usage_stats` and
`/credit_usage` both 404, so it will not tell us what a call cost. Whatever
tier 0 turns out to bill, we will only know it from our own records — which is
why every call here logs what it was for.
"""

from __future__ import annotations

import logging
import ssl
from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.services.resolution import (
    Candidate,
    Resolver,
    ResolverError,
    ResolutionResult,
    normalise_domain,
)

log = logging.getLogger(__name__)

APOLLO_BASE = "https://api.apollo.io/api/v1"
TIMEOUT_SECONDS = 25.0


def _client(timeout: float = TIMEOUT_SECONDS):
    """An httpx client trusting the OS certificate store.

    Same reason as `probes.py` and `enrichment_clients.py`: certifi does not
    carry a corporate proxy's root, and the handshake failure that follows
    reads as "the provider is down".
    """
    import httpx

    try:
        import truststore

        verify: Any = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # noqa: BLE001 — fall back to the bundled roots
        verify = True
    return httpx.AsyncClient(timeout=timeout, verify=verify)


class ApolloOrgResolver:
    """Apollo's organisation lookup. Needs a domain; returns firmographics.

    Confidence is 1.0 when the returned domain matches the one we asked about,
    because that is not a guess — it is the same key coming back. A different
    domain (Apollo followed an acquisition, or the row carried a redirect)
    scores lower and lands in review, which is the correct place for it.
    """

    key = "apollo_org"

    def __init__(self, api_key: str, base_url: str = APOLLO_BASE):
        self._key = api_key
        self._base = base_url.rstrip("/")

    async def resolve(self, account: Account) -> ResolutionResult:
        domain = normalise_domain(account.domain)
        if not domain:
            # Nothing to look up. Asking with a bare name returns whichever
            # company Apollo thinks is most famous, which is exactly the
            # confident-but-wrong answer this whole step exists to prevent.
            return ResolutionResult()

        async with _client() as client:
            try:
                response = await client.post(
                    f"{self._base}/organizations/enrich",
                    headers={
                        "x-api-key": self._key,
                        "accept": "application/json",
                        "content-type": "application/json",
                    },
                    params={"domain": domain},
                )
            except Exception as exc:  # noqa: BLE001 — one error type upward
                raise ResolverError(
                    f"could not reach Apollo: {type(exc).__name__}"
                ) from exc

        if response.status_code in (401, 403):
            # Never the body: a rejection can quote the key that was sent.
            raise ResolverError("Apollo rejected this key")
        if response.status_code == 429:
            raise ResolverError("Apollo rate limit reached")
        if response.status_code == 404:
            return ResolutionResult()
        if response.status_code >= 400:
            raise ResolverError(f"Apollo returned HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ResolverError("Apollo returned a non-JSON response") from exc

        org = (payload or {}).get("organization")
        if not isinstance(org, dict) or not org:
            return ResolutionResult()

        returned = normalise_domain(
            org.get("primary_domain") or org.get("website_url")
        )
        exact = bool(returned) and returned == domain
        if not exact:
            log.info(
                "resolution.apollo_domain_differs asked=%s got=%s", domain, returned
            )

        headcount = org.get("estimated_num_employees")
        return ResolutionResult(
            best=Candidate(
                name=org.get("name") or None,
                domain=returned or domain,
                linkedin_url=org.get("linkedin_url") or None,
                industry=org.get("industry") or None,
                employee_count=int(headcount) if isinstance(headcount, int) else None,
                confidence=1.0 if exact else 0.6,
                rationale=(
                    "Apollo matched the domain exactly"
                    if exact
                    else f"Apollo returned {returned or 'a different domain'} for {domain}"
                ),
            )
        )


class WebsiteResolver:
    """The row's own domain, read: does it exist, answer, and name the company? Free.

    Between Apollo and the model. Apollo confirms a domain from its database;
    this confirms one from the company's own homepage — the only way a real
    company Apollo does not hold gets confirmed at all — and it runs before the
    model, so a site that settles it spends no model call.

    * **no DNS record** — the domain does not exist, and the note says so.
    * **registered but nothing answering, parked, or an error page** — said.
    * **redirects elsewhere** — the landing domain is the candidate, and since
      it differs from the row it always goes to review: `vanguardtech.com`
      landing on `argylesg.com` is an acquisition or a mistake, and a person
      decides which.
    * **answers and names the company** — confirmed on the row's domain.
    * **answers but names something else** — a low candidate; the model is asked.
    """

    key = "website"
    #: The homepage on the row's own domain names the company.
    NAMED = 0.9
    #: It lands on another domain that names the company. Above the threshold
    #: so the model is not asked, but the differing domain sends it to review.
    REDIRECT_NAMED = 0.8
    #: It answers, but nothing on the homepage names the company.
    UNNAMED = 0.4

    def __init__(self, inspect: Any | None = None):
        self._inspect = inspect

    async def resolve(self, account: Account) -> ResolutionResult:
        from app.services import site_identity

        domain = normalise_domain(account.domain)
        if not domain:
            return ResolutionResult()
        site = await (self._inspect or site_identity.inspect)(domain)

        if not site.exists:
            return ResolutionResult(finding=f"{domain} does not exist — it has no DNS record")
        if not site.answered:
            return ResolutionResult(finding=f"{domain} is registered, but no website answers on it")
        if site.parked:
            return ResolutionResult(finding=f"{domain} is a parked domain, not a company website")
        if site.status and site.status >= 400:
            return ResolutionResult(finding=f"{domain} answers only with HTTP {site.status}")

        named = site_identity.name_matches(account.name, site.names)
        calls = site.calls_itself
        says = f", which calls itself {calls!r}" if calls else ""
        page = site.company_pages[0] if len(site.company_pages) == 1 else None
        if site.redirected:
            return ResolutionResult(
                best=Candidate(
                    name=calls, domain=site.final_domain, linkedin_url=page,
                    confidence=self.REDIRECT_NAMED if named else self.UNNAMED,
                    rationale=f"{domain} redirects to {site.final_domain}{says}",
                )
            )
        if named:
            return ResolutionResult(
                best=Candidate(
                    name=calls or account.name, domain=domain, linkedin_url=page,
                    confidence=self.NAMED,
                    rationale=f"{domain} answers and its homepage names the company{says}",
                )
            )
        return ResolutionResult(
            best=Candidate(
                name=calls, domain=domain, linkedin_url=page, confidence=self.UNNAMED,
                rationale=f"{domain} answers, but its homepage does not name {account.name!r}{says}",
            )
        )


class LlmWebResolver:
    """Find a company's domain from its name, using web search.

    Only reached when Apollo had nothing to look up, which is the case this
    exists for: a CSV with company names and no domains at all.

    The model is asked for **candidates with confidence**, not for an answer.
    Asked for one company it will always name one; asked which companies match
    and how sure it is, it can say "three firms trade under this name" — and
    that is the answer a rep needs in order to pick correctly.

    **It may not confirm the domain it was shown.** Given a row carrying
    `ashcombehr.io`, the first live run returned that domain at confidence 1.0
    with the rationale "the spreadsheet row provides a specific name, domain
    and LinkedIn URL" — citing the input as evidence for the input, for a
    company that does not exist. Apollo can confirm a domain because it looks
    it up and answers `None` when it has never heard of it; a model shown the
    answer cannot. So agreeing with the input is capped below the acceptance
    threshold and goes to a human, which is what the review step is for.
    """

    #: Ceiling for a candidate that merely repeats the domain we supplied.
    #: Below `resolution.ACCEPT_ABOVE`, so it always reaches review.
    ECHO_CEILING = 0.5

    key = "llm_web"

    #: A domain the model proposed that has no working website.
    NO_SITE_CEILING = 0.3
    #: One whose homepage answers but does not name the company.
    UNNAMED_CEILING = 0.6

    def __init__(self, client: Any | None = None, inspect: Any | None = None):
        self._client = client
        # When given, every domain the model proposes *other than the row's*
        # is read before it is offered. Live, it offered brightbyte.software at
        # 0.95 for a row whose own domain did not exist, and "check this 0.95"
        # read as nearly certain.
        self._inspect = inspect

    async def resolve(self, account: Account) -> ResolutionResult:
        from app.services import stages

        if not (account.name or "").strip():
            return ResolutionResult()

        try:
            result = await stages.resolve_company(
                account=account, client=self._client
            )
        except Exception as exc:  # noqa: BLE001 — one error type upward
            raise ResolverError(f"web resolution failed: {type(exc).__name__}") from exc

        found = result.parsed
        supplied = normalise_domain(account.domain)
        candidates = []
        for c in found.candidates or []:
            confidence = float(c.confidence)
            rationale = c.rationale
            if supplied and normalise_domain(c.domain) == supplied:
                # It agreed with what it was shown. That is not verification,
                # and at face value it would auto-resolve a company that does
                # not exist.
                if confidence > self.ECHO_CEILING:
                    log.info(
                        "resolution.llm_echoed_input domain=%s claimed=%.2f capped=%.2f",
                        supplied, confidence, self.ECHO_CEILING,
                    )
                    confidence = self.ECHO_CEILING
                rationale = (
                    f"{rationale} [capped: repeats the domain already on the row, "
                    "so nothing was independently established]"
                )
            candidates.append(
                Candidate(
                    name=c.name,
                    domain=c.domain,
                    linkedin_url=c.linkedin_url,
                    industry=c.industry,
                    employee_count=c.employee_count,
                    confidence=confidence,
                    rationale=rationale,
                )
            )
        missing: list[str] = []
        if self._inspect is not None:
            candidates, missing = await self._check_alternatives(account, candidates)
        finding = (
            f"the model suggested {', '.join(missing)}, which "
            f"{'does' if len(missing) == 1 else 'do'} not exist"
            if missing
            else None
        )
        if not candidates:
            return ResolutionResult(finding=finding)
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return ResolutionResult(best=candidates[0], others=candidates[1:], finding=finding)

    async def _check_alternatives(
        self, account: Account, candidates: list[Candidate]
    ) -> tuple[list[Candidate], list[str]]:
        from app.services import site_identity

        supplied = normalise_domain(account.domain)
        kept: list[Candidate] = []
        missing: list[str] = []
        for c in candidates:
            domain = normalise_domain(c.domain)
            if not domain or domain == supplied:
                kept.append(c)
                continue
            site = await self._inspect(domain)
            if not site.exists:
                missing.append(domain)
                continue
            who = c.name or account.name
            if not site.answered or site.parked or (site.status or 0) >= 400:
                c = replace(
                    c, confidence=min(c.confidence, self.NO_SITE_CEILING),
                    rationale=f"{c.rationale} [capped: {domain} has no working website]",
                )
            elif not site_identity.name_matches(who, site.names):
                c = replace(
                    c, confidence=min(c.confidence, self.UNNAMED_CEILING),
                    rationale=f"{c.rationale} [capped: {domain}'s homepage does not name {who!r}]",
                )
            kept.append(c)
        return kept, missing


def build(key: str, api_key: str | None) -> Resolver | None:
    """The resolver for a source key, or None where it cannot be built."""
    if key == "apollo_org":
        return ApolloOrgResolver(api_key) if api_key else None
    if key == "website":
        return WebsiteResolver()
    if key == "llm_web":
        # No credential of its own — it goes through `llm.call_structured`,
        # which resolves the configured provider and its stored key.
        from app.services import site_identity

        return LlmWebResolver(inspect=site_identity.inspect)
    return None


async def build_all(
    session: AsyncSession, order: list[str]
) -> dict[str, Resolver]:
    """Construct every source in the configured order that can be built.

    Keys are decrypted here and handed straight to the client — never logged,
    never returned by an endpoint, never held longer than the pass. Invariant 9.
    """
    from app.models.config import IntegrationCredential
    from app.services import crypto

    built: dict[str, Resolver] = {}
    for key in order:
        api_key: str | None = None
        if key == "apollo_org":
            row = (
                await session.execute(
                    select(IntegrationCredential).where(
                        IntegrationCredential.provider == "apollo",
                        IntegrationCredential.credential_type == "api_key",
                        IntegrationCredential.status == "valid",
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                continue
            try:
                api_key = crypto.decrypt(row.value_encrypted).reveal()
            except crypto.CredentialError:
                log.warning("resolution.undecryptable provider=apollo")
                continue
        resolver = build(key, api_key)
        if resolver is not None:
            built[key] = resolver
    return built
