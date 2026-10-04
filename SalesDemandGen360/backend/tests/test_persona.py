"""Title normalisation.

One shared taxonomy, so persona weighting and the Buyer dimension always agree
on who somebody is. Deterministic — no LLM call to classify a job title.
"""

from __future__ import annotations

import pytest

from app.services.persona import (
    classify,
    classify_buying_role,
    classify_department,
    classify_seniority,
    persona_role,
)


class TestSeniority:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Chief Technology Officer", "c_level"),
            ("CTO", "c_level"),
            ("Co-Founder & CEO", "c_level"),
            ("VP Engineering", "vp"),
            ("VP of Engineering", "vp"),
            ("Head of Platform", "vp"),
            ("SVP, Product", "vp"),
            ("Director of Data", "director"),
            ("Engineering Manager", "manager"),
            ("Team Lead", "manager"),
            ("Staff Software Engineer", "ic"),
            ("", "unknown"),
            (None, "unknown"),
        ],
    )
    def test_classification(self, title, expected):
        assert classify_seniority(title) == expected

    def test_vp_outranks_manager_in_a_title_containing_both(self):
        """'VP of Engineering Management' is a VP, not a manager.

        Order in the pattern list is what decides this, so it is worth pinning.
        """
        assert classify_seniority("VP of Engineering Management") == "vp"


class TestBuyingRole:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Chief Executive Officer", "economic_buyer"),
            ("CFO", "economic_buyer"),
            ("CTO", "technical_buyer"),
            ("VP Engineering", "technical_buyer"),
            ("Director of Procurement", "blocker"),
            ("General Counsel", "blocker"),
            ("Head of InfoSec", "blocker"),
            ("Director of Marketing", "champion"),
            ("Engineering Manager", "influencer"),
        ],
    )
    def test_classification(self, title, expected):
        assert classify_buying_role(title) == expected

    def test_procurement_director_is_a_blocker_not_a_champion(self):
        """Seniority alone would make this a champion.

        Blockers are checked first for exactly this case — a Director of
        Procurement outranks the seniority heuristic, and treating them as a
        champion would aim the whole thread at the wrong person.
        """
        assert classify_seniority("Director of Procurement") == "director"
        assert classify_buying_role("Director of Procurement") == "blocker"


class TestPersonaRole:
    def test_title_variants_collapse_to_one_key(self):
        """The reason this module exists.

        If these produced different keys, the Learning layer could not compare
        one VP Engineering to another across accounts.
        """
        keys = {
            persona_role("VP Engineering"),
            persona_role("VP of Engineering"),
            persona_role("Vice President, Engineering"),
        }
        assert len(keys) == 1, f"variants did not collapse: {keys}"

    def test_c_level_shorthand_is_preserved(self):
        assert persona_role("CTO") == "cto"
        assert persona_role("Chief Information Officer") == "cio"

    def test_unknown_title_yields_none(self):
        assert persona_role("Gardener") is None


class TestDepartment:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("VP Engineering", "engineering"),
            ("Head of Data", "data"),
            ("Chief Information Officer", "it"),
            ("Director of Demand Gen", "marketing"),
        ],
    )
    def test_classification(self, title, expected):
        assert classify_department(title) == expected


class TestClassifyBundle:
    def test_returns_every_facet(self):
        out = classify("VP of Engineering")
        assert out == {
            "seniority": "vp",
            "department": "engineering",
            "buying_role": "technical_buyer",
            "persona_role": "vp_engineering",
        }
