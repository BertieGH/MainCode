"""Trialling a source before it is stored.

The guarantee under test is narrow and load-bearing: a trial runs **the real
call** and writes **nothing**. Either half failing makes the feature worse than
not having it — a trial that takes a shortcut tells you a source works when it
does not, and a trial that stores its findings has silently done a research run
nobody asked for.
"""

from __future__ import annotations

import uuid

import pytest

from app.schemas.evidence import EvidenceBatch, FoundEvidence
from app.services import source_trial

pytestmark = pytest.mark.anyio


CANDIDATE = {
    "key": "state_licence_registers",
    "label": "State licence registers",
    "description": "A state insurance department's own licence register.",
    "scopes": ["company"],
    "kind": "search",
}


class _Account:
    """Fully populated by default.

    Every field matters: `source_trial.ACCOUNT_INPUTS` reports the empty ones,
    and a half-filled stub makes every verdict read "the sample is missing
    things" — which is right about that account and misleading about the test.
    """

    def __init__(self, name="Northwind", domain="northwind.example", **blank):
        self.id = uuid.uuid4()
        self.name = name
        self.domain = domain
        self.linkedin_url = "https://www.linkedin.com/company/northwind"
        self.industry = "Insurance"
        self.hq_country = "US"
        for field_name, value in blank.items():
            setattr(self, field_name, value)


def _batch(n=1) -> EvidenceBatch:
    return EvidenceBatch(
        evidence=[
            FoundEvidence(
                source_type="web",
                source_url=f"https://example.test/{i}",
                excerpt="licence 1234 surrendered",
            )
            for i in range(n)
        ],
        not_found=[] if n else ["nothing filed"],
    )


class _Result:
    def __init__(self, parsed):
        self.parsed = parsed
        self.input_tokens = 100
        self.output_tokens = 20


class TestARouteWithNoClientIsRefused:
    """`provider` and `manual` have nothing to run.

    Refused by name rather than trialled and reported as empty: "no evidence"
    and "no implementation" look identical in a result and mean opposite
    things. `linkedin_serp` sat configured for a day with no credential, no
    client and nothing saying so, which is the failure this guards.
    """

    @pytest.mark.parametrize("route", ["provider", "manual", "nonsense"])
    async def test_it_raises_rather_than_returning_an_empty_trial(self, route):
        with pytest.raises(source_trial.NotTestable) as caught:
            await source_trial.try_source(
                None, candidate={**CANDIDATE, "kind": route}, account_ids=[uuid.uuid4()]
            )
        assert route in str(caught.value)
        assert "search" in str(caught.value), "it should say what can be trialled"


class TestItRunsTheRealPathAndStoresNothing:
    async def test_the_candidates_own_wording_reaches_the_call(self, monkeypatch):
        """A trial is mostly a test of the description, because that is what the
        research prompt reads as "what to read this source for". If the trial
        fell back to a registry row — or to nothing — it would be testing some
        other source's words."""
        seen: list[dict] = []

        async def fake_research_family(session, *, account, family, candidate=None, client=None):
            seen.append({"family": family, "candidate": candidate})
            return _Result(_batch(1))

        account = _Account()
        monkeypatch.setattr(
            "app.services.stages.research_family", fake_research_family, raising=True
        )

        report = await source_trial.try_source(
            _SessionReturning([account]), candidate=CANDIDATE, account_ids=[account.id]
        )

        assert seen, "the real stage was never called"
        assert seen[0]["candidate"]["description"] == CANDIDATE["description"]
        assert seen[0]["family"] == CANDIDATE["key"]
        assert report.found == 1

    async def test_no_evidence_is_stored(self, monkeypatch):
        """The whole point. `store_found` is the only way evidence is written,
        so the assertion is that it is never reached."""
        stored: list = []

        async def fake_research_family(session, *, account, family, candidate=None, client=None):
            return _Result(_batch(2))

        async def exploding_store(*args, **kwargs):
            stored.append(kwargs)
            raise AssertionError("a trial must not store evidence")

        account = _Account()
        monkeypatch.setattr(
            "app.services.stages.research_family", fake_research_family, raising=True
        )
        monkeypatch.setattr(
            "app.services.evidence.store_found", exploding_store, raising=True
        )

        report = await source_trial.try_source(
            _SessionReturning([account]), candidate=CANDIDATE, account_ids=[account.id]
        )
        assert report.found == 2
        assert stored == []


class TestOneBadAccountDoesNotEndTheTrial:
    async def test_a_failure_is_reported_per_account(self, monkeypatch):
        """One account whose site refuses us says nothing about the candidate;
        five do. Raising on the first would hide the difference, which is the
        only thing a sample is for."""
        account_ok, account_bad = _Account("Good"), _Account("Bad")
        calls: list[str] = []

        async def flaky(session, *, account, family, candidate=None, client=None):
            calls.append(account.name)
            if account.name == "Bad":
                raise TimeoutError("read timed out")
            return _Result(_batch(1))

        monkeypatch.setattr("app.services.stages.research_family", flaky, raising=True)

        report = await source_trial.try_source(
            _SessionReturning([account_bad, account_ok]),
            candidate=CANDIDATE,
            account_ids=[account_bad.id, account_ok.id],
        )

        assert calls == ["Bad", "Good"], "it kept going, in the order asked for"
        assert (report.found, report.failed, report.accounts) == (1, 1, 2)
        assert "TimeoutError" in report.trials[0].error
        assert report.trials[1].ok


class TestTheVerdict:
    async def test_nothing_anywhere_says_do_not_store_it(self, monkeypatch):
        async def empty(session, *, account, family, candidate=None, client=None):
            return _Result(EvidenceBatch(not_found=["looked, nothing there"]))

        monkeypatch.setattr("app.services.stages.research_family", empty, raising=True)
        accounts = [_Account("A"), _Account("B")]
        report = await source_trial.try_source(
            _SessionReturning(accounts),
            candidate=CANDIDATE,
            account_ids=[a.id for a in accounts],
        )
        assert report.dry == 2
        assert "do not store" in report.verdict

    async def test_an_empty_account_is_not_blamed_on_the_wording(self, monkeypatch):
        """A company with no stored website finds nothing for every source.

        Saying "do not store this, change the wording" there sends somebody to
        rewrite a brief that was never the problem, which is the dead end this
        whole panel exists to avoid.
        """
        async def empty(session, *, account, family, candidate=None, client=None):
            return _Result(EvidenceBatch(not_found=["nothing to search with"]))

        monkeypatch.setattr("app.services.stages.research_family", empty, raising=True)
        starved = _Account("Nameless", domain="", linkedin_url="")
        report = await source_trial.try_source(
            _SessionReturning([starved]), candidate=CANDIDATE, account_ids=[starved.id]
        )
        assert report.trials[0].missing == ["its website", "its LinkedIn page"]
        assert "may not be the wording" in report.verdict
        assert "do not store" not in report.verdict

    async def test_an_ab_reports_both_sides_from_one_call(self, monkeypatch):
        """Both wordings against the same account on the same day. Two separate
        runs are not a comparison — §74 saw the same request return a sound
        answer on 411 tokens and nothing usable on 790, minutes apart."""
        seen: list[str] = []

        async def by_wording(session, *, account, family, candidate=None, client=None):
            seen.append(candidate["description"])
            n = 2 if "wires" in candidate["description"] else 0
            return _Result(_batch(n) if n else EvidenceBatch(not_found=["nothing"]))

        monkeypatch.setattr("app.services.stages.research_family", by_wording, raising=True)
        account = _Account()
        report = await source_trial.try_source(
            _SessionReturning([account]),
            candidate=CANDIDATE,
            account_ids=[account.id],
            description_b="Trade publications and the wires.",
        )

        assert seen == [CANDIDATE["description"], "Trade publications and the wires."]
        assert len(report.side("A")) == 1 and len(report.side("B")) == 1
        assert report.accounts == 1, "one account, tried twice"
        assert "B found 2, A found 0" in report.verdict

    async def test_an_ab_halves_the_account_ceiling(self, monkeypatch):
        """The cap is on calls, not rows: running both wordings everywhere would
        otherwise double what a trial costs."""
        async def one(session, *, account, family, candidate=None, client=None):
            return _Result(_batch(1))

        monkeypatch.setattr("app.services.stages.research_family", one, raising=True)
        many = [_Account(f"A{i}") for i in range(source_trial.MAX_ACCOUNTS + 4)]
        report = await source_trial.try_source(
            _SessionReturning(many),
            candidate=CANDIDATE,
            account_ids=[a.id for a in many],
            description_b="A different wording.",
        )
        assert report.accounts == source_trial.MAX_ACCOUNTS // 2
        assert len(report.trials) == source_trial.MAX_ACCOUNTS

    async def test_the_sample_is_capped(self, monkeypatch):
        """A trial is a sample, not a run. An uncapped list would let a test
        cost more than the source it is testing."""
        async def one(session, *, account, family, candidate=None, client=None):
            return _Result(_batch(1))

        monkeypatch.setattr("app.services.stages.research_family", one, raising=True)
        many = [_Account(f"A{i}") for i in range(source_trial.MAX_ACCOUNTS + 4)]
        report = await source_trial.try_source(
            _SessionReturning(many), candidate=CANDIDATE, account_ids=[a.id for a in many]
        )
        assert report.accounts == source_trial.MAX_ACCOUNTS


class _SessionReturning:
    """Just enough session to answer the one `select(Account)` the service makes."""

    def __init__(self, accounts):
        self._accounts = list(accounts)

    async def execute(self, _stmt):
        return self

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self._accounts)
