"""Size bands, and the query-family runner axis.

Two vocabularies that changed shape together (`docs/09`). What is asserted here
is mostly about *absences* — the band that carries no multipliers, the families
a sweep must not run — because both changes exist to stop something happening
quietly rather than to make something new appear.
"""

from __future__ import annotations

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
        assert query_families.BY_KEY["job_board"].runner == "fetch"

    def test_everything_else_is_a_search(self):
        others = [
            f for f in query_families.QUERY_FAMILIES
            if f.key not in ("enrichment", "manual", "company_site", "job_board")
        ]
        assert others, "the fixture stopped describing the catalogue"
        assert all(f.runner == "search" for f in others)

    def test_searchable_excludes_the_two(self):
        keys = {f.key for f in query_families.searchable()}
        assert "enrichment" not in keys
        assert "manual" not in keys
        assert "funding" in keys

    def test_support_only_is_a_separate_question(self):
        """`reviews` is a genuine search that may corroborate but never
        conclude. Conflating the two axes would either stop it running or let
        it create a signal on its own."""
        reviews = query_families.BY_KEY["reviews"]
        assert reviews.runner == "search"
        assert reviews.support_only is True

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
