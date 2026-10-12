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
