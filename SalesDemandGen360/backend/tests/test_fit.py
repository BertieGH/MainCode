"""Fit is arithmetic over the account and the ICP. No database, no model.

The case that made this necessary: BlueWave scored fit 75 one day and 0 the
next, from the same headcount and the same evidence, because a model decided
the second time that nothing it had been shown was about fit. The last test
here is BlueWave, as it actually is.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import fit

DEFAULT = {
    "employees": "50-500",
    "industries": ["SaaS", "Logistics", "Fintech", "Insurance"],
    "regions": ["US", "Canada"],
    "exclusions": ["Government", "Existing customers", "Defence"],
}


def account(**over):
    fields = {"industry": "SaaS", "employee_count": 180, "hq_country": "United States"}
    fields.update(over)
    return SimpleNamespace(**fields)


class TestSize:
    @pytest.mark.parametrize(
        ("count", "band", "outcome"),
        [
            (180, "50-500", "match"),
            (50, "50-500", "match"),
            (500, "50-500", "match"),
            (12, "50-500", "mismatch"),
            (2000, "1000+", "match"),
            (999, "1000+", "mismatch"),
        ],
    )
    def test_inclusive_bands(self, count, band, outcome):
        result = fit.assess(account(employee_count=count), {"employees": band})
        assert result.checks[0].outcome == outcome

    def test_an_unreadable_band_constrains_nothing_and_says_so(self):
        result = fit.assess(account(), {"employees": "mid-market"})
        assert result.checks[0].outcome == "unknown"
        assert "mid-market" in result.reason


class TestIndustry:
    def test_spelling_differences_are_not_mismatches(self):
        assert fit.assess(account(industry="  FinTech "), {"industries": ["Fintech"]}).score == 100

    def test_a_whole_phrase_inside_a_longer_label_matches(self):
        result = fit.assess(account(industry="Logistics and Supply Chain"), {"industries": ["Logistics"]})
        assert result.score == 100

    def test_no_leap_between_different_words(self):
        """"Financial Services and Software" is not "Fintech". Guessing that
        would score an account on a mapping nobody chose."""
        result = fit.assess(
            account(industry="Financial Services and Software"), {"industries": ["Fintech"]}
        )
        assert result.score == 0
        assert "Financial Services and Software" in result.reason
        assert "Fintech" in result.reason, "both sides are named, so the ICP can be fixed"


class TestRegion:
    def test_a_country_written_out_matches_its_chip(self):
        assert fit.assess(account(hq_country="United States"), {"regions": ["US"]}).score == 100

    def test_a_country_inside_a_group_matches(self):
        assert fit.assess(account(hq_country="Germany"), {"regions": ["EU"]}).score == 100

    def test_a_country_outside_is_a_mismatch(self):
        result = fit.assess(account(hq_country="Brazil"), {"regions": ["US", "Canada"]})
        assert result.score == 0
        assert "Brazil" in result.reason


class TestWhatCannotBeChecked:
    def test_unknowns_are_named_but_not_counted(self):
        """100 of what could be checked, and the reason says what could not."""
        result = fit.assess(account(hq_country=None), {"employees": "50-500", "regions": ["US"]})
        assert result.score == 100
        assert "no country" in result.reason
        assert "1 of 1" in result.reason

    def test_nothing_checkable_is_a_declared_absence(self):
        result = fit.assess(
            account(industry=None, employee_count=None, hq_country=None), DEFAULT
        )
        assert result.score == 0
        assert result.basis == "no_evidence"

    def test_an_icp_with_no_constraints_rules_nothing_out(self):
        result = fit.assess(account(), {"personas": [{"titles": ["CTO"]}]})
        assert result.score == 100
        assert result.basis == fit.FIRMOGRAPHICS


class TestExclusions:
    def test_an_excluded_industry_is_zero_whatever_else_matches(self):
        result = fit.assess(account(industry="Government"), DEFAULT, icp="Default")
        assert result.score == 0
        assert "do-not-target" in result.reason


class TestSeveralIcps:
    def test_the_best_one_counts_and_is_named(self):
        """A list worked for two ICPs needs the account to fit one of them."""
        result = fit.best(
            account(industry="Cybersecurity"),
            [("Default", DEFAULT), ("Security", {"industries": ["Cybersecurity"]})],
        )
        assert result.icp == "Security"
        assert result.score == 100

    def test_no_icps_means_no_computed_fit(self):
        assert fit.best(account(), []) is None


class TestTheCaseThatStartedThis:
    def test_bluewave(self):
        """160 people is inside 50-500; IT services is not one of the four
        industries Default names; there is no country on the account. So 1 of 2
        — the same answer on every run, and the reason says why."""
        bluewave = account(
            industry="information technology & services", employee_count=160, hq_country=None
        )
        result = fit.assess(bluewave, DEFAULT, icp="Default")
        assert result.score == 50
        assert result.basis == fit.FIRMOGRAPHICS
        assert "160 employees is inside 50-500" in result.reason
        assert "is not one of SaaS, Logistics, Fintech, Insurance" in result.reason
        assert "no country" in result.reason
        assert result.as_assessment()["evidence_ids"] == []


class TestTheProfileCountsWhenTheColumnsAreEmpty:
    """Fit scored 0 on an account whose profile named its industry, its size
    and where it is.

    That zero was `no_evidence` — "nothing to compare" — so an account plainly
    outside the ICP read as one nobody had researched. The two call for
    opposite actions, which is the whole reason the distinction exists.
    """

    ICP = {
        "industries": ["Logistics", "Fintech", "Insurance"],
        "regions": ["US", "Canada"],
        "employees": "1-500",
        "exclusions": ["Government", "Defence"],
    }

    def _account(self, **over):
        row = SimpleNamespace(
            industry=None, employee_count=None, hq_country=None, profile=None
        )
        for k, v in over.items():
            setattr(row, k, v)
        return row

    def test_a_profile_is_read_when_the_columns_are_null(self):
        result = fit.assess(
            self._account(
                profile={
                    "industries_served": ["Productivity Software", "SaaS"],
                    "size": "Approx. 100-110 employees",
                    "locations": ["Porto, Portugal", "Fully distributed worldwide"],
                }
            ),
            self.ICP,
        )
        # One of three: the headcount fits, the industry and the place do not.
        assert result.score == 33.33
        assert result.basis == fit.PROFILE
        outcomes = {c.factor: c.outcome for c in result.checks}
        assert outcomes == {"size": "match", "industry": "mismatch", "region": "mismatch"}

    def test_the_reason_says_where_the_values_came_from(self):
        """A column is what a provider asserted; a profile line is what a
        model read off a page. Both usable, not equally strong."""
        result = fit.assess(
            self._account(profile={"industries_served": ["Fintech"]}), self.ICP
        )
        assert "from the researched profile" in result.reason

    def test_a_column_still_wins_over_the_profile(self):
        """The profile is the fallback, never the override."""
        result = fit.assess(
            self._account(
                industry="Logistics",
                profile={"industries_served": ["Productivity Software"]},
            ),
            self.ICP,
        )
        industry = next(c for c in result.checks if c.factor == "industry")
        assert industry.outcome == "match"
        assert "from the researched profile" not in industry.detail

    def test_any_listed_industry_may_match(self):
        """A profile names several, the way one column names one."""
        result = fit.assess(
            self._account(
                profile={"industries_served": ["Productivity Software", "Insurance"]}
            ),
            self.ICP,
        )
        assert next(c for c in result.checks if c.factor == "industry").outcome == "match"

    def test_a_place_is_split_so_the_country_inside_it_is_found(self):
        """Profiles write for people: "Porto, Portugal", not "PT"."""
        result = fit.assess(
            self._account(profile={"locations": ["Toronto, Canada"]}), self.ICP
        )
        assert next(c for c in result.checks if c.factor == "region").outcome == "match"

    def test_a_size_range_is_compared_by_overlap(self):
        """400-600 against 1-500 is a real partial. Collapsing the range to
        one end would decide it by which end was picked."""
        result = fit.assess(
            self._account(profile={"size": "400-600 employees"}), self.ICP
        )
        assert next(c for c in result.checks if c.factor == "size").outcome == "match"

        outside = fit.assess(
            self._account(profile={"size": "about 900 people"}), self.ICP
        )
        assert next(c for c in outside.checks if c.factor == "size").outcome == "mismatch"

    def test_an_exclusion_in_the_profile_still_excludes(self):
        """An account kept because the column that would have excluded it was
        empty is the expensive kind of mistake."""
        result = fit.assess(
            self._account(profile={"industries_served": ["Defence", "Software"]}),
            self.ICP,
        )
        assert result.score == 0.0
        assert "do-not-target" in result.reason

    def test_an_empty_profile_still_says_nothing_to_compare(self):
        """The fallback adds a place to look, not an answer."""
        result = fit.assess(self._account(profile={}), self.ICP)
        assert result.score == 0.0
        assert result.basis == "no_evidence"

    def test_an_unreadable_size_does_not_invent_one(self):
        result = fit.assess(
            self._account(profile={"size": "a small team"}), self.ICP
        )
        assert next(c for c in result.checks if c.factor == "size").outcome == "unknown"

    def test_the_basis_stays_firmographics_when_the_profile_decided_nothing(self):
        """A profile value that came back unknown must not downgrade a fit the
        columns settled."""
        result = fit.assess(
            self._account(industry="Fintech", profile={"size": "a small team"}),
            self.ICP,
        )
        assert result.basis == fit.FIRMOGRAPHICS
