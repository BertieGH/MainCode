"""Tier 0: identifying the company before anything is spent on it.

Every test here is about one failure, because it is the failure the step
exists to prevent: **researching the wrong company succeeds**. The evidence
parses, the signals cite it, the score computes, the draft reads well — and it
is all about a different business. Nothing downstream can detect it, which is
why the check has to happen here and why a near-miss must never be written in
as a fact.

So the assertions are mostly about what does *not* get stored.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.account import Account
from app.services import resolution
from app.services.resolution import (
    Candidate,
    ResolutionResult,
    ResolverError,
    normalise_domain,
    normalise_linkedin,
    resolve_account,
)


def account(**kw) -> Account:
    row = Account(
        id=kw.pop("id", uuid.uuid4()),
        name=kw.pop("name", "Acme"),
        resolution_status="unresolved",
    )
    for k, v in kw.items():
        setattr(row, k, v)
    return row


class StubResolver:
    def __init__(self, key: str, result: ResolutionResult | Exception):
        self.key = key
        self._result = result
        self.calls = 0

    async def resolve(self, account):
        self.calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def sure(domain="acme.com", **kw) -> ResolutionResult:
    return ResolutionResult(
        best=Candidate(
            name=kw.pop("name", "Acme"), domain=domain,
            confidence=kw.pop("confidence", 1.0),
            rationale="exact domain match", **kw,
        )
    )


class TestAConfidentMatchIsAccepted:
    async def test_an_exact_domain_match_resolves(self):
        acc = account(domain="acme.com")
        out = await resolve_account(
            None, account=acc, resolvers=[StubResolver("apollo_org", sure())]
        )
        assert out.outcome == "resolved"
        assert acc.resolution_status == "resolved"
        assert acc.resolution_note is None

    async def test_firmographics_are_kept(self):
        """The by-product that makes tier 0 pay for itself.

        `industry_key` feeds the scoring multipliers and `employee_count`
        derives the size band; today both come from the CSV or not at all.
        """
        acc = account(domain="acme.com")
        await resolve_account(
            None, account=acc,
            resolvers=[StubResolver(
                "apollo_org",
                sure(industry="Logistics", employee_count=420),
            )],
        )
        assert acc.industry == "Logistics"
        assert acc.industry_key == "logistics"
        assert acc.employee_count == 420

    async def test_the_waterfall_stops_at_the_first_confident_answer(self):
        first = StubResolver("apollo_org", sure())
        second = StubResolver("llm_web", sure())
        await resolve_account(None, account=account(domain="acme.com"),
                              resolvers=[first, second])
        assert first.calls == 1
        assert second.calls == 0, "spent a model call to confirm a known answer"


class TestANearMissIsNeverAFact:
    async def test_low_confidence_goes_to_review_not_resolved(self):
        acc = account()
        out = await resolve_account(
            None, account=acc,
            resolvers=[StubResolver("llm_web", sure(confidence=0.6))],
        )
        assert out.outcome == "needs_review"
        assert acc.resolution_status == "needs_review"
        assert "0.6" in acc.resolution_note

    async def test_two_close_candidates_go_to_review_even_when_confident(self):
        """The winner won on very little. Accepting it picks the wrong Acme."""
        acc = account()
        result = ResolutionResult(
            best=Candidate(name="Acme Ltd", domain="acme.co.uk",
                           confidence=0.88, rationale="UK filing"),
            others=[Candidate(name="Acme Inc", domain="acme.com",
                              confidence=0.80, rationale="US site")],
        )
        out = await resolve_account(
            None, account=acc, resolvers=[StubResolver("llm_web", result)]
        )
        assert out.outcome == "needs_review"
        assert "too close to call" in acc.resolution_note

    async def test_the_runners_up_are_kept_for_the_rep(self):
        """A rep asked to choose needs the options, not a second search."""
        acc = account()
        result = ResolutionResult(
            best=Candidate(name="Acme Ltd", domain="acme.co.uk",
                           confidence=0.88, rationale="UK filing"),
            others=[Candidate(name="Acme Inc", domain="acme.com",
                              confidence=0.80, rationale="US site")],
        )
        await resolve_account(None, account=acc,
                              resolvers=[StubResolver("llm_web", result)])
        assert len(acc.resolution_candidates) == 2
        assert {c["domain"] for c in acc.resolution_candidates} == {
            "acme.co.uk", "acme.com"
        }

    async def test_disagreeing_with_the_list_goes_to_review(self):
        """A human typed that domain. A provider is not grounds to overrule it."""
        acc = account(domain="acme.co.uk")
        out = await resolve_account(
            None, account=acc,
            resolvers=[StubResolver("apollo_org", sure(domain="acme.com"))],
        )
        assert out.outcome == "needs_review"
        assert acc.domain == "acme.co.uk", "overwrote a human's domain"
        assert "acme.com" in acc.resolution_note


class TestASourceMayNotConfirmItsOwnInput:
    """Both bugs the first live run exposed, on invented companies.

    The seed list carries domains like `ashcombehr.io` for businesses that do
    not exist. Apollo answered `organization: None` — honestly. The web
    fallback returned that same domain at **1.00** confidence, reasoning that
    "the spreadsheet row provides a specific name, domain and LinkedIn URL":
    citing the input as evidence for the input. Three fictional companies were
    stored as `resolved`.
    """

    async def test_the_answer_is_attributed_to_the_source_that_gave_it(self):
        """`resolved_by` said `apollo_org` for answers Apollo had declined.

        It picked the first source *called* rather than the one that answered,
        so provenance — the entire purpose of the field — was fiction.
        """
        acc = account(domain="acme.com")
        await resolve_account(
            None, account=acc,
            resolvers=[
                StubResolver("apollo_org", resolution.ResolutionResult()),
                StubResolver("llm_web", sure()),
            ],
        )
        assert acc.resolved_by == "llm_web", "credited a source that found nothing"

    async def test_the_candidate_records_its_own_source(self):
        acc = account(domain="acme.com")
        await resolve_account(
            None, account=acc,
            resolvers=[
                StubResolver("apollo_org", resolution.ResolutionResult()),
                StubResolver("llm_web", sure(confidence=0.5)),
            ],
        )
        assert acc.resolution_candidates[0]["source"] == "llm_web"

    async def test_echoing_the_supplied_domain_cannot_auto_resolve(self):
        """The live failure, as a test.

        A model shown `acme.com` and answering `acme.com` has established
        nothing. Apollo may confirm a domain because it would have said `None`;
        a model that was handed the answer may not.
        """
        from app.schemas.resolution import CompanyCandidate, CompanyResolution
        from app.services.resolution_clients import LlmWebResolver

        class FakeCall:
            parsed = CompanyResolution(
                candidates=[
                    CompanyCandidate(
                        name="Acme", domain="acme.com", confidence=1.0,
                        rationale="the row provides a specific name and domain",
                    )
                ]
            )

        async def fake_stage(*, account, client=None):
            return FakeCall()

        import app.services.stages as stages_mod

        original = stages_mod.resolve_company
        stages_mod.resolve_company = fake_stage
        try:
            acc = account(domain="acme.com")
            result = await LlmWebResolver().resolve(acc)
            assert result.best.confidence <= LlmWebResolver.ECHO_CEILING
            assert result.best.confidence < resolution.ACCEPT_ABOVE

            out = await resolve_account(
                None, account=acc,
                resolvers=[StubResolver("llm_web", result)],
            )
            assert out.outcome == "needs_review", "a fictional company auto-resolved"
        finally:
            stages_mod.resolve_company = original

    async def test_a_domain_it_actually_found_is_not_capped(self):
        """The cap must not punish the case the fallback exists for."""
        from app.schemas.resolution import CompanyCandidate, CompanyResolution
        from app.services.resolution_clients import LlmWebResolver

        class FakeCall:
            parsed = CompanyResolution(
                candidates=[
                    CompanyCandidate(
                        name="Acme", domain="acme.com", confidence=0.95,
                        rationale="matched the careers page to the HQ city",
                    )
                ]
            )

        async def fake_stage(*, account, client=None):
            return FakeCall()

        import app.services.stages as stages_mod

        original = stages_mod.resolve_company
        stages_mod.resolve_company = fake_stage
        try:
            # No domain on the row: nothing was supplied, so nothing is echoed.
            result = await LlmWebResolver().resolve(account(domain=None))
            assert result.best.confidence == 0.95
        finally:
            stages_mod.resolve_company = original


class TestResolvedMeansActionable:
    """Confidence answers *which* company. This answers whether we can act.

    A live run resolved "It Catalyst Global Solutions Inc" at 0.90 with no
    domain at all. It passed the gate and was cleared for research — with
    nothing for Apollo to look up and nothing for a search to anchor on. Being
    sure which company somebody means is not the same as being able to reach
    it.
    """

    async def test_a_confident_answer_with_no_identifier_goes_to_review(self):
        acc = account(domain=None)
        out = await resolve_account(
            None, account=acc,
            resolvers=[StubResolver("llm_web", ResolutionResult(
                best=Candidate(name="It Catalyst", domain=None,
                               confidence=0.9, rationale="found the company"),
            ))],
        )
        assert out.outcome == "needs_review"
        assert "nothing to research" in acc.resolution_note

    async def test_a_linkedin_page_is_enough_on_its_own(self):
        """Not every company has a findable domain; a company page is a real
        identifier and enrichment can use it."""
        acc = account(domain=None)
        out = await resolve_account(
            None, account=acc,
            resolvers=[StubResolver("llm_web", ResolutionResult(
                best=Candidate(
                    name="It Catalyst",
                    linkedin_url="https://linkedin.com/company/it-catalyst",
                    confidence=0.9, rationale="matched the company page",
                ),
            ))],
        )
        assert out.outcome == "resolved"

    async def test_a_domain_already_on_the_row_counts(self):
        """The source confirmed an identity the list already carried."""
        acc = account(domain="acme.com")
        out = await resolve_account(
            None, account=acc,
            resolvers=[StubResolver("apollo_org", ResolutionResult(
                best=Candidate(name="Acme", domain="acme.com",
                               confidence=1.0, rationale="exact domain match"),
            ))],
        )
        assert out.outcome == "resolved"


class TestFailuresAreToldApart:
    async def test_every_source_failing_is_unavailable_not_unresolved(self):
        """One needs a retry, the other needs a different identifier.

        Collapsing them either retries forever or writes off a company nobody
        actually failed to find.
        """
        acc = account(domain="acme.com")
        out = await resolve_account(
            None, account=acc,
            resolvers=[StubResolver("apollo_org", ResolverError("timeout"))],
        )
        assert out.outcome == "unavailable"
        assert acc.resolution_status == "unresolved", "a failure marked it settled"

    async def test_nobody_found_is_unresolved(self):
        acc = account()
        out = await resolve_account(
            None, account=acc,
            resolvers=[StubResolver("apollo_org", ResolutionResult())],
        )
        assert out.outcome == "unresolved"
        assert acc.resolution_status == "unresolved"

    async def test_a_failing_source_does_not_lose_the_next_ones_answer(self):
        acc = account(domain="acme.com")
        out = await resolve_account(
            None, account=acc,
            resolvers=[
                StubResolver("apollo_org", ResolverError("down")),
                StubResolver("llm_web", sure()),
            ],
        )
        assert out.outcome == "resolved"


class TestNormalising:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("https://WWW.Acme.com/about?x=1", "acme.com"),
            ("acme.com/", "acme.com"),
            ("  ACME.CO.UK  ", "acme.co.uk"),
            ("acme.com.", "acme.com"),
            # A bare word is a name. Stored as a domain it fails every lookup
            # that uses one, silently.
            ("Acme", None),
            ("two words", None),
            ("", None),
            (None, None),
        ],
    )
    def test_domains_converge_on_one_form(self, raw, expected):
        assert normalise_domain(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("https://www.linkedin.com/company/acme/",
             "https://linkedin.com/company/acme"),
            ("linkedin.com/company/acme?trk=x",
             "https://linkedin.com/company/acme"),
            # A person, not a company. Stored here it sends a rep to a
            # stranger's profile from the account page.
            ("https://linkedin.com/in/dana-reid", None),
            ("", None),
        ],
    )
    def test_only_company_pages_survive(self, raw, expected):
        assert normalise_linkedin(raw) == expected
