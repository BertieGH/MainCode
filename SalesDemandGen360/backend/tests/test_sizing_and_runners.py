"""Size bands, and the query-family runner axis.

Two vocabularies that changed shape together (`docs/09`). What is asserted here
is mostly about *absences* — the band that carries no multipliers, the families
a sweep must not run — because both changes exist to stop something happening
quietly rather than to make something new appear.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services import query_families, sizing


class TestSizeIsDerivedNotClassified:
    @pytest.mark.parametrize(
        "headcount,expected",
        [
            (1, "small"),
            (49, "small"),
            (50, "mid"),
            (999, "mid"),
            (1000, "large"),
            (250_000, "large"),
        ],
    )
    def test_the_bands_cut_where_they_say(self, headcount, expected):
        assert sizing.band_for(headcount) == expected

    def test_no_headcount_is_unknown_not_small(self):
        """An unmeasured account is not a small one.

        Defaulting into `small` would score every CSV import with no headcount
        column as a startup, and nothing on the screen would reveal it.
        """
        assert sizing.band_for(None) == "unknown"

    def test_a_negative_headcount_is_unknown_not_clamped(self):
        """Not a headcount. Clamping to zero would make a bad import the
        smallest band rather than an absent one."""
        assert sizing.band_for(-5) == "unknown"

    def test_zero_is_a_real_answer(self):
        """A holding company with no employees is small, not unmeasured."""
        assert sizing.band_for(0) == "small"

    def test_unknown_is_not_a_band_that_can_carry_multipliers(self):
        assert "unknown" not in sizing.BANDS
        assert set(sizing.BANDS) == {"small", "mid", "large"}

    def test_the_band_names_are_ours_not_lgm_shape_names(self):
        """`enterprise_8_23` and `startup_5_11` are registered in LGM and are
        not ours to rename (invariant 6). Mapping across the gap keeps the two
        vocabularies from being coupled by coincidence."""
        assert "enterprise" not in sizing.BANDS
        assert "startup" not in sizing.BANDS

    def test_every_band_has_a_label(self):
        for band in (*sizing.BANDS, "unknown"):
            assert sizing.LABELS[band]


class TestNotEveryFamilyIsASearch:
    """A sweep that ran every family would spend Apollo credits like tokens.

    `enrichment` is a metered provider waterfall and `manual` is a rep's
    keyboard. Neither is a web search, and "returned nothing" means something
    different for each — which is why they carry a runner rather than being
    treated as ordinary families that happen to be quiet.
    """

    def test_enrichment_is_a_provider_not_a_search(self):
        assert query_families.BY_KEY["enrichment"].runner == "provider"

    def test_manual_is_neither(self):
        assert query_families.BY_KEY["manual"].runner == "manual"

    def test_the_company_s_own_site_is_fetched_not_searched(self):
        """A feed is dated, first-hand and free to read. Asking a model to
        search for what a company published is paying to be told second-hand."""
        assert query_families.BY_KEY["company_site"].runner == "fetch"

    def test_the_job_board_is_read_not_searched(self):
        """An ATS publishes the company's open roles through a public API.
        Searching for what a board already lists is paying to be told less."""
        assert query_families.BY_KEY["ats_boards"].runner == "fetch"

    def test_everything_else_is_a_search(self):
        others = [
            f for f in query_families.QUERY_FAMILIES
            if f.key not in ("enrichment", "manual", "company_site", "ats_boards")
        ]
        assert others, "the fixture stopped describing the catalogue"
        assert all(f.runner == "search" for f in others)

    def test_searchable_excludes_the_two(self):
        keys = {f.key for f in query_families.searchable()}
        assert "enrichment" not in keys
        assert "manual" not in keys
        assert "trade_press" in keys

    def test_support_only_is_a_separate_question(self):
        """A source can be a genuine search that corroborates but never
        concludes. Conflating the two axes would either stop it running or let
        it create a signal on its own.

        Asserted against a source built here rather than a shipped one. The
        catalogue ships none since `review_sites` was trialled against three
        accounts, found nothing at any of them and was retired
        (`c1f7e3b89d24`) — but the rule still holds and `sources.validate`
        still enforces it, so the test outlives the row it used to use.
        """
        corroborating = query_families.QueryFamily(
            "review_sites", "Reviews", "Repeated themes only.", ("company",),
            support_only=True,
        )
        assert corroborating.runner == "search"
        assert corroborating.support_only is True
        assert not any(
            f.support_only for f in query_families.QUERY_FAMILIES
        ), "nothing ships support-only now; if that changes, say which and why"

    def test_a_provider_source_is_still_valid_provenance(self):
        """`role_change` really is produced by enrichment — a title that
        disagrees with the stored one is how a role change gets noticed. The
        runner changes who does the work, not whether the claim is true.

        Checked against the seed's own scopes here; that a *claim* on it is
        accepted is `test_research_sources.py`, which asks the registry.
        """
        enrichment = query_families.BY_KEY["enrichment"]
        assert enrichment.runner == "provider"
        assert "contact" in enrichment.scopes


class TestRecordingAHeadcount:
    """One place decides what a fresh observation means.

    It had no place at all before: `resolution` assigned the count **only when
    the field was empty**, so a second run never refreshed it, nothing recorded
    when it was true, and a change destroyed the value it replaced. A delta was
    uncomputable however good the source — which is the real reason tracking
    company growth did not work, not anything about LinkedIn or Google.
    """

    def _account(self, **fields):
        from types import SimpleNamespace

        base = dict(
            employee_count=None,
            employee_count_as_of=None,
            employee_count_before=None,
            employee_count_before_as_of=None,
        )
        return SimpleNamespace(**(base | fields))

    def test_the_first_observation_is_dated(self):
        a = self._account()
        change = sizing.record_headcount(a, 30, observed_on=date(2026, 3, 1))
        assert (change.outcome, change.after, change.delta) == ("first", 30, None)
        assert (a.employee_count, a.employee_count_as_of) == (30, date(2026, 3, 1))
        assert a.employee_count_before is None

    def test_the_same_number_refreshes_only_the_date(self):
        """We looked and it had not moved, which is information. Writing it into
        `before` as well would collapse the window a real change is measured
        over — the next change would read as "30 to 33 in zero days"."""
        a = self._account(employee_count=30, employee_count_as_of=date(2026, 3, 1))
        change = sizing.record_headcount(a, 30, observed_on=date(2026, 6, 1))
        assert change.outcome == "same"
        assert a.employee_count_as_of == date(2026, 6, 1)
        assert a.employee_count_before is None, "nothing was replaced"

    def test_a_change_keeps_what_it_replaced_and_the_window(self):
        a = self._account(employee_count=30, employee_count_as_of=date(2026, 3, 1))
        change = sizing.record_headcount(a, 33, observed_on=date(2026, 6, 1))
        assert (change.outcome, change.before, change.after) == ("changed", 30, 33)
        assert change.delta == 3
        assert change.over_days == 92, "the window the growth happened over"
        assert (a.employee_count, a.employee_count_as_of) == (33, date(2026, 6, 1))
        assert a.employee_count_before == 30
        assert a.employee_count_before_as_of == date(2026, 3, 1)

    def test_the_window_spans_the_last_real_change_not_the_last_run(self):
        """Three observations, one change. The pair must still describe the
        move, not the two most recent reads."""
        a = self._account(employee_count=30, employee_count_as_of=date(2026, 3, 1))
        sizing.record_headcount(a, 30, observed_on=date(2026, 4, 1))
        sizing.record_headcount(a, 30, observed_on=date(2026, 5, 1))
        change = sizing.record_headcount(a, 33, observed_on=date(2026, 6, 1))
        # April and May refreshed `as_of`, so the window is May→June rather
        # than March→June: the growth is known to have happened in that month,
        # and claiming three months would understate the rate.
        assert change.over_days == 31
        assert a.employee_count_before == 30

    def test_a_shrinking_company_is_recorded_the_same_way(self):
        a = self._account(employee_count=40, employee_count_as_of=date(2026, 1, 1))
        change = sizing.record_headcount(a, 31, observed_on=date(2026, 6, 1))
        assert change.delta == -9, "a loss is as much a signal as a gain"

    def test_an_unknown_count_never_clears_what_is_held(self):
        """Every source returns None for "I do not know". Letting that erase a
        stored number would make the value depend on which source answered
        last, and a company would lose its size by being looked at."""
        a = self._account(employee_count=30, employee_count_as_of=date(2026, 3, 1))
        change = sizing.record_headcount(a, None, observed_on=date(2026, 6, 1))
        assert change.outcome == "ignored"
        assert (a.employee_count, a.employee_count_as_of) == (30, date(2026, 3, 1))

    def test_a_first_change_with_no_prior_date_reports_no_window(self):
        """The eight accounts carrying a count today have no date — nothing was
        backfilled, because dating them today would claim we observed in
        October what arrived in a September CSV. A delta without a window is
        not a growth rate, so it says so rather than inventing one."""
        a = self._account(employee_count=30)
        change = sizing.record_headcount(a, 33, observed_on=date(2026, 6, 1))
        assert (change.delta, change.over_days) == (3, None)
