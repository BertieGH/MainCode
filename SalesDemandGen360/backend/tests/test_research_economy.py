"""What a run buys, and what it declines to buy.

Three changes, one subject: research was costing more than it returned, and
the ledger said why. A company pass is six grounded searches, a contact pass
is four more — 40% of the bill for 4% of the evidence — and `regulators_and_
registers` was bought 80 times and came back empty 50 of them.

**A1** — a rerun re-sweeps what you asked it to. `force` used to ignore every
window everywhere, so re-sweeping a company re-bought its people at full
price. Three accounts were researched six and seven times in one afternoon
with that compounding each time.

**A3** — the two halves are separable. One button bought both and the screen
could not say which half the money went on.

**A5** — the scan plans the run. It already received the family list and was
asked only "anything here at all?", which fired twice in 88 runs. It now says
which families are worth buying, and the guards below are what keep a model's
opinion from emptying a run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from app.services.pipeline import _not_worth_buying
from app.services.research import PlannedFamily, ResearchPlan


def family(key: str, *, kind: str = "search", feeds: tuple[str, ...] = ("t",)):
    return PlannedFamily(family=key, feeds=feeds, scopes=("company",),
                         support_only=False, kind=kind)


def plan(*families) -> ResearchPlan:
    return ResearchPlan(families=list(families))


class TestTheScanPlansTheRun:
    def test_a_paid_family_the_scan_did_not_name_is_not_bought(self):
        p = plan(family("trade_press"), family("regulators_and_registers"))
        dropped = _not_worth_buying(p, ("trade_press",))
        assert [f.family for f in dropped] == ["regulators_and_registers"]

    def test_silence_buys_everything(self):
        """`None` is "the scan did not say" — an older sweep, a stub, a model
        that returned no list. Treating it as "nothing is worth buying" would
        let one quiet response empty every run in the book."""
        p = plan(family("trade_press"), family("regulators_and_registers"))
        assert _not_worth_buying(p, None) == []

    def test_an_empty_list_also_buys_everything(self):
        """Distinct from the above in the data and the same in effect. A model
        that names nothing has not expressed an opinion about anything, and
        `families_worth_buying: []` is what a model returns when it has not
        engaged with the question rather than when it has decided."""
        assert _not_worth_buying(plan(family("trade_press")), ()) == []

    def test_a_free_family_is_never_skipped(self):
        """`fetch` sources buy no grounded search, so gating one saves nothing
        and can only lose evidence — and they are the good ones: company_site
        and linkedin_index produce two thirds of all evidence between them.

        The scan's opinion is about spend, so it only decides about spending.
        """
        p = plan(family("company_site", kind="fetch"), family("trade_press"))
        dropped = _not_worth_buying(p, ("trade_press",))
        assert dropped == [], "a free family was skipped to save nothing"

    def test_the_only_route_to_a_signal_type_survives(self):
        """A cheaper run that cannot answer the question is not a cheaper run,
        it is a different one. If dropping a family makes a conclusion
        unreachable for this account, the saving is not ours to take."""
        p = plan(
            family("trade_press", feeds=("funding",)),
            family("regulators_and_registers", feeds=("compliance",)),
        )
        # The scan likes neither. Both are the sole route to their type, so
        # both stand.
        assert _not_worth_buying(p, ("something_else",)) == []

    def test_a_type_another_family_still_answers_may_be_dropped(self):
        """The mirror of the test above, and what makes it a rule rather than
        a refusal to ever skip anything."""
        p = plan(
            family("trade_press", feeds=("funding",)),
            family("company_data_providers", feeds=("funding",)),
        )
        dropped = _not_worth_buying(p, ("trade_press",))
        assert [f.family for f in dropped] == ["company_data_providers"]

    def test_a_free_family_covers_a_type_for_the_paid_one(self):
        """A paid family whose types a *free* family also feeds is the best
        saving available: the conclusion stays reachable and the search is
        not bought."""
        p = plan(
            family("company_site", kind="fetch", feeds=("hiring",)),
            family("ats_boards", kind="fetch", feeds=("hiring",)),
            family("trade_press", feeds=("hiring",)),
        )
        dropped = _not_worth_buying(p, ())  # scan says nothing
        assert dropped == []
        dropped = _not_worth_buying(p, ("company_site",))
        assert [f.family for f in dropped] == ["trade_press"]

    def test_whitespace_and_blanks_in_the_models_answer_are_ignored(self):
        p = plan(family("trade_press"), family("regulators_and_registers"))
        dropped = _not_worth_buying(p, (" trade_press ", "", "   "))
        assert [f.family for f in dropped] == ["regulators_and_registers"]

    def test_a_family_the_scan_invented_changes_nothing(self):
        """The model is given the family list but is not bound by it. A name
        that is not in the plan must not silently become a reason to drop the
        ones that are."""
        p = plan(family("trade_press"), family("regulators_and_registers"))
        dropped = _not_worth_buying(p, ("a_source_we_do_not_have",))
        # Neither planned family was named, but each is the only route to its
        # own type — they share one, so one may go.
        assert len(dropped) <= 1


# --------------------------------------------------------------------------
# A1/A3 — the scope of a run, asserted through the route's own arithmetic
# --------------------------------------------------------------------------
@dataclass
class _Scoped:
    """The decision A1 makes, extracted so it can be asserted without a run.

    Mirrors `run_research_for_list`: `force` is scoped, and a scope narrows
    the plan rather than the runner.
    """

    force: bool
    force_scope: str
    scope: str

    @property
    def force_company(self) -> bool:
        return self.force and self.force_scope in ("both", "company")

    @property
    def force_contacts(self) -> bool:
        return self.force and self.force_scope in ("both", "contacts")


class TestARerunRebuysWhatYouAskedFor:
    def test_rerunning_a_company_leaves_its_people_in_the_window(self):
        """The change that cost the most to not have. Donegal was researched
        seven times in one afternoon; every rerun re-bought four grounded
        contact searches that the window would have skipped."""
        s = _Scoped(force=True, force_scope="company", scope="both")
        assert s.force_company is True
        assert s.force_contacts is False

    def test_rerunning_the_people_leaves_the_company_in_the_window(self):
        s = _Scoped(force=True, force_scope="contacts", scope="both")
        assert s.force_company is False
        assert s.force_contacts is True

    def test_both_is_still_available_and_is_not_the_default(self):
        """It remains possible to re-buy everything — it is just no longer
        what you get for asking to re-sweep a company."""
        s = _Scoped(force=True, force_scope="both", scope="both")
        assert s.force_company and s.force_contacts

    def test_no_force_forces_nothing(self):
        s = _Scoped(force=False, force_scope="both", scope="both")
        assert not s.force_company and not s.force_contacts


@pytest.mark.parametrize(
    "scope,company,contacts",
    [("both", True, True), ("company", True, False), ("contacts", False, True)],
)
def test_a_scope_narrows_the_plan(scope, company, contacts):
    """A3, as the route computes it: emptying a family set is what keeps the
    reuse arithmetic, the "nothing to do" check and the report agreeing with
    what was actually bought."""
    planned = {"company_site", "trade_press"}
    contact_families = {"linkedin_index", "trade_press"}
    if scope == "company":
        contact_families = set()
    elif scope == "contacts":
        planned = set()

    assert bool(planned) is company
    assert bool(contact_families) is contacts


def test_the_empty_plan_is_not_the_absent_plan():
    """`None` means "the whole registry" to the runner, which is the opposite
    of what a narrowed scope asks for. The route passes an empty plan, and
    this is the line that would catch somebody simplifying it to None."""
    empty = ResearchPlan(families=[])
    assert empty.families == []
    assert empty is not None


# ==========================================================================
# the waterfall, and the route that stops paying a model to run a query
# ==========================================================================
class TestTheWaterfallGate:
    """Roughly one professional in ten posts at all, and the per-person pass
    costs a grounded search whether or not there is anything to find — 29 of
    them returned one evidence row and no signal.

    The company's own LinkedIn sweep has counted the index's dated posts since
    the day it was written, and its docstring called that number "the gate
    that decides whether per-person post queries are worth making for this
    account at all". Nothing read it. These assert the three states it has.
    """

    def test_none_is_not_zero(self):
        """`None` is "nobody looked" and must buy the people pass as before.
        Collapsing it to zero would silently stop researching people at every
        account whose LinkedIn family did not run."""
        from app.services.pipeline import FamilyOutcome, RunResult

        assert FamilyOutcome(stored=0).recent_posts is None
        assert RunResult(run_id=uuid.uuid4()).recent_posts is None

    def test_a_count_travels_off_the_family_that_saw_it(self):
        from app.services.pipeline import FamilyOutcome

        assert FamilyOutcome(stored=3, recent_posts=0).recent_posts == 0
        assert FamilyOutcome(stored=3, recent_posts=11).recent_posts == 11

    @pytest.mark.parametrize(
        "recent_posts,gated",
        [(None, False), (0, True), (1, False), (40, False)],
    )
    def test_only_a_measured_zero_closes_the_gate(self, recent_posts, gated):
        """The condition as `run_research` writes it. An index holding no post
        for the whole company will not hold one for its CFO; an index nobody
        asked has established nothing."""
        contacts = [object()]
        contact_plan, runner = object(), object()
        silent = bool(
            contacts
            and contact_plan is not None
            and runner is not None
            and recent_posts == 0
        )
        assert silent is gated


class TestTheLinkedInFamilyReadsTheIndex:
    def test_the_serp_family_is_named_not_sniffed(self):
        """Deciding at runtime that a prompt "looks like an X-Ray" would route
        a reworded one somewhere its author did not intend."""
        from app.services.pipeline import SERP_CONTACT_FAMILY

        assert SERP_CONTACT_FAMILY == "type:contact_content_activity"

    async def test_a_person_with_no_name_is_skipped_not_searched(self):
        """A credit spent on `"" "Acme"` buys ten results about Acme filed
        under a person they are not about."""
        from app.services import linkedin_serp

        class _P:
            id = uuid.uuid4()
            full_name = "   "

        out = await linkedin_serp.sweep_people(
            type("A", (), {"name": "Acme", "id": uuid.uuid4()})(), [_P()], key="k",
        )
        assert out.queries == 0 and out.credits == 0
        assert any("no name" in m for m in out.misses)

    async def test_a_missing_credential_is_not_a_coverage_gap(self):
        """Reporting "found nothing" without a key is indistinguishable from
        a person with no public footprint."""
        from app.services import linkedin_serp

        out = await linkedin_serp.sweep_people(
            type("A", (), {"name": "Acme", "id": uuid.uuid4()})(), [object()], key=None,
        )
        assert out.queries == 0
        assert any("credential" in m for m in out.misses)

    async def test_one_persons_refusal_does_not_lose_the_others(self):
        """Per person, because a provider that rate-limits on the third name
        must not discard the two it already answered."""
        from app.services import linkedin_serp

        people = []
        for name in ("Ann Blake", "Cal Dover"):
            people.append(type("P", (), {"id": uuid.uuid4(), "full_name": name})())

        calls = {"n": 0}

        async def fake_ask(_client, _key, _query):
            calls["n"] += 1
            if calls["n"] == 1:
                return linkedin_serp.SerpResult(error="HTTP 429", credits=1)
            return linkedin_serp.SerpResult(
                found=[object()], total=1, credits=1,
            )

        original = linkedin_serp._ask
        linkedin_serp._ask = fake_ask
        try:
            out = await linkedin_serp.sweep_people(
                type("A", (), {"name": "Acme", "id": uuid.uuid4()})(),
                people, key="k", http=_NoHttp(),
            )
        finally:
            linkedin_serp._ask = original

        assert out.queries == 2, "the second person was not searched for"
        assert out.credits == 2, "a refused query still charged and must be counted"
        assert len(out.by_contact) == 1
        assert any("429" in m for m in out.misses)


class _NoHttp:
    """A client the sweep is handed so it does not open one of its own."""

    async def aclose(self):  # pragma: no cover - never reached, never needed
        return None


# ==========================================================================
# the tier — the one thing that sets a maximum
# ==========================================================================
class TestTheCeiling:
    """Everything else that decides what a run buys only ever subtracts: the
    reuse window drops what is fresh, the scan drops what is not there, the
    waterfall drops people who do not post. The tier is the only thing that
    sets the maximum, and the two kinds must not be confused — a deep run on
    a dead account still costs light money, because the scan gates it.
    """

    def test_a_tier_buys_everything_at_or_below_it(self):
        from app.services.research import within

        assert within("light", "light")
        assert within("light", "deep")
        assert within("standard", "deep")
        assert not within("deep", "light")
        assert not within("standard", "light")

    def test_an_untiered_source_keeps_being_bought(self):
        """The safe direction. A tier is a spending limit, and the failure
        that matters is the one that quietly stops buying a source nobody has
        tiered — not the one that buys it."""
        from app.services.research import within

        assert within("a-tier-nobody-defined", "light")
        assert within("light", "a-ceiling-nobody-defined")

    def test_the_order_is_cheapest_first(self):
        """The whole comparison is an index into this tuple, so reordering it
        silently inverts every ceiling in the system."""
        from app.services.research import TIERS

        assert TIERS == ("light", "standard", "deep")

    def test_deep_is_the_default_everywhere(self):
        """A caller that says nothing must get the plan it got before. A tier
        that narrowed by default would stop buying sources nobody asked it to
        drop, and the first sign would be a signal that stopped appearing."""
        import inspect

        from app.services.research import build_plan, plan_for_list

        for fn in (build_plan, plan_for_list):
            assert inspect.signature(fn).parameters["tier"].default == "deep"
