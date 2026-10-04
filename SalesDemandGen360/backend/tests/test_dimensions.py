"""Buyer and engagement as facts; judged dimensions on steps. No database."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services import dimensions as dims

DEFAULT = {
    "personas": [
        {"buying_role": "economic_buyer", "titles": ["CEO"]},
        {"buying_role": "technical_buyer", "titles": ["CTO", "CIO", "IT head"]},
    ]
}


def person(name="Ana Diaz", title="CEO", **over):
    fields = {
        "full_name": name, "title": title, "persona_role": None, "buying_role": None,
        "seniority": "unknown", "email": None, "email_status": "unverified", "linkedin_url": None,
    }
    fields.update(over)
    return SimpleNamespace(**fields)


class TestReach:
    @pytest.mark.parametrize(
        ("over", "credit"),
        [
            ({"email": "a@x.io", "email_status": "verified"}, 1.0),
            ({"email": "a@x.io", "email_status": "risky"}, 0.6),
            ({"linkedin_url": "https://linkedin.com/in/a"}, 0.5),
            ({"email": "a@x.io", "email_status": "unverified"}, 0.4),
            ({}, 0.15),
            ({"email": "a@x.io", "email_status": "invalid"}, 0.15),
        ],
    )
    def test_the_best_route_counts(self, over, credit):
        assert dims.reach(person(**over))[0] == credit

    def test_linkedin_beats_an_unchecked_address(self):
        """LinkedIn is a channel La Growth Machine sends on; an unchecked
        address is one the send gate refuses."""
        both = person(email="a@x.io", email_status="unverified", linkedin_url="https://l.in/a")
        assert dims.reach(both) == (0.5, "LinkedIn profile")


class TestBuyer:
    def test_the_case_that_started_this(self):
        """BlueWave: its one persona contact is a Managing Director with no
        email and no LinkedIn, and nobody matches the technical buyer. The
        model had scored this 75."""
        md = person("Pat Lane", "Managing Director")
        result = dims.assess_buyer([md], DEFAULT, icp="Default")
        assert result.score == 7.5
        assert result.basis == dims.CONTACTS
        assert "economic buyer (CEO): Pat Lane, Managing Director — no working email or LinkedIn yet" in result.reason
        assert "technical buyer (CTO, CIO, IT head): nobody at the account matches" in result.reason

    def test_a_reachable_committee_scores_high(self):
        ceo = person("Ana Diaz", "CEO", email="ana@x.io", email_status="verified")
        cto = person("Raj Iyer", "CTO", linkedin_url="https://l.in/raj")
        assert dims.assess_buyer([ceo, cto], DEFAULT).score == 75.0

    def test_the_most_reachable_person_for_a_role_counts(self):
        named = person("Zed Young", "CEO")
        reachable = person("Amy Bond", "CEO", email="amy@x.io", email_status="verified")
        result = dims.assess_buyer([named, reachable], {"personas": [DEFAULT["personas"][0]]})
        assert result.score == 100.0
        assert "Amy Bond" in result.reason

    def test_the_same_person_is_named_every_time(self):
        """Two equally reachable people: the reason must not depend on row order."""
        a, b = person("Bea Cole", "CEO"), person("Al Ames", "CEO")
        one = dims.assess_buyer([a, b], {"personas": [DEFAULT["personas"][0]]})
        two = dims.assess_buyer([b, a], {"personas": [DEFAULT["personas"][0]]})
        assert one.reason == two.reason
        assert "Al Ames" in one.reason

    def test_nobody_at_all_is_zero_not_unknown(self):
        """"Can we reach anyone?" has an answer when there is nobody: no."""
        result = dims.assess_buyer([], DEFAULT)
        assert result.score == 0
        assert result.basis == dims.CONTACTS

    def test_no_personas_is_a_declared_absence(self):
        result = dims.assess_buyer([person()], {"industries": ["SaaS"]})
        assert result.basis == "no_evidence"
        assert result.score == 0

    def test_the_best_icp_counts(self):
        cto = person("Raj Iyer", "CTO", email="r@x.io", email_status="verified")
        result = dims.best_buyer(
            [cto],
            [("Default", DEFAULT), ("Tech", {"personas": [{"buying_role": "technical_buyer", "titles": ["CTO"]}]})],
        )
        assert result.icp == "Tech"
        assert result.score == 100.0

    def test_no_icps_means_nothing_computed(self):
        assert dims.best_buyer([person()], []) is None


class TestEngagement:
    def test_nothing_sent(self):
        result = dims.assess_engagement(sent=0, last_sent=None, replied=False)
        assert (result.score, result.basis) == (0.0, dims.OUTREACH)
        assert "nothing has been sent" in result.reason

    def test_sending_is_not_traction(self):
        result = dims.assess_engagement(sent=3, last_sent=datetime(2026, 9, 1), replied=False)
        assert result.score == 0.0
        assert "3 touches sent, last on 01 Sep 2026" in result.reason

    def test_a_reply_is(self):
        assert dims.assess_engagement(sent=2, last_sent=None, replied=True).score == 75.0


class TestTheScale:
    @pytest.mark.parametrize(
        ("raw", "step"),
        [(0, 0), (12, 0), (13, 25), (70, 75), (80, 75), (85, 75), (87.5, 100), (90, 100), (140, 100), (-5, 0)],
    )
    def test_nearest_step_ties_go_up(self, raw, step):
        assert dims.to_level(raw) == step

    def test_the_drift_that_started_this_collapses(self):
        """BlueWave's opportunity read 70, 75, 80 and 85 across runs."""
        assert {dims.to_level(s) for s in (70, 75, 80, 85)} == {75.0}


class TestTheFingerprint:
    BASE = dict(prompt="p1", evidence_ids={"e1", "e2"}, signal_ids={"s1"}, account={"industry": "SaaS"})

    def test_order_does_not_matter(self):
        a = dims.inputs_fingerprint(**self.BASE)
        b = dims.inputs_fingerprint(**{**self.BASE, "evidence_ids": {"e2", "e1"}})
        assert a == b

    @pytest.mark.parametrize(
        "change",
        [
            {"prompt": "p2"},
            {"evidence_ids": {"e1", "e2", "e3"}},
            {"signal_ids": set()},
            {"account": {"industry": "Fintech"}},
        ],
    )
    def test_any_change_is_a_different_fingerprint(self, change):
        assert dims.inputs_fingerprint(**self.BASE) != dims.inputs_fingerprint(**{**self.BASE, **change})

    def test_the_rubric_is_part_of_how_it_is_asked(self):
        assert dims.prompt_version("prefix", ["gemini", "m"]) == dims.prompt_version("prefix", ["gemini", "m"])
        assert dims.prompt_version("prefix", ["gemini", "m"]) != dims.prompt_version("prefix", ["gemini", "n"])
