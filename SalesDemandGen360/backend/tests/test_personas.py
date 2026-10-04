"""Persona matching, against the titles that got it wrong.

Every row below is a title seen on a real list, or the rule it stands for. The
previous matcher admitted a VP of Sales, a VP of Business Development and a
Chief Security Officer for targets of `CEO, CTO, CIO, IT head`, and left out a
Managing Director. Each of those was a real buyer mis-sorted without an error:
the list simply looked enriched, for the wrong people.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.personas import matches, tokens
from app.services.verification import matches_persona

#: What the EIA service used to target, and what the Default ICP names now.
EIA = ("ceo", "cto", "cio", "it head")


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # Seen on the Test Data list.
        ("VP of Sales", False),
        ("VP of Business Development", False),
        ("Chief Security Officer", False),
        ("Managing Director", True),
        ("CEO", True),
        ("CTO", True),
        ("President", True),
        ("Director of IT", True),
        ("VP of Engineering", True),
        ("Head of Product", False),
        ("Operations Director", False),
        # The rules they stand for.
        ("Founder & CEO", True),
        ("Co-founder", True),
        ("Owner", True),
        ("Chief Technology Officer", True),
        ("Chief Information Officer", True),
        ("Chief Financial Officer", False),
        ("Senior Vice President, Marketing", False),
        ("Head of Sales", False),
        ("Junior Developer", False),
        ("Software Engineer", False),
    ],
)
def test_against_the_eia_targets(title, expected):
    assert any(matches(title, t) for t in EIA) is expected, title


class TestWhyEachRuleExists:
    def test_president_inside_vice_president_is_not_a_ceo(self):
        """The root of the VP-of-Sales mistake: `vice president` was read as
        two words, and `president` on its own is CEO rank."""
        assert tokens("Vice President of Sales") == ["vp", "sales"]
        assert not matches("VP of Sales", "ceo")

    def test_a_managing_director_runs_the_company(self):
        assert tokens("Managing Director") == ["md"]
        assert matches("Managing Director", "ceo")

    def test_business_development_is_sales_not_engineering(self):
        assert not matches("VP of Business Development", "cto")
        assert matches("VP of Business Development", "vp sales")

    def test_a_different_chief_is_not_the_chief_executive(self):
        """Chief level alone used to be enough for a target of CEO."""
        for title in ("Chief Security Officer", "CFO", "Chief Marketing Officer"):
            assert not matches(title, "ceo"), title

    def test_same_function_gets_one_step_of_slack(self):
        """Org charts disagree on titles within a function."""
        assert matches("VP, Technology", "it head")
        assert matches("Director of Information Technology", "it head")
        assert not matches("Director of IT", "cto"), "two steps below a CTO"

    def test_a_title_naming_no_function_is_judged_on_rank_alone(self):
        """A bare `vp` was the miss the first fix was for. It still reaches a
        target at or below its rank — without the slack a function earns."""
        assert matches("vp", "it head")
        assert not matches("vp", "ceo"), "no slack without a function"
        assert not matches("Director", "cto")


class _Contact:
    def __init__(self, title=None, buying_role=None):
        self.id = uuid.uuid4()
        self.title = title
        self.persona_role = None
        self.buying_role = buying_role
        self.seniority = "unknown"


class TestBuyingRolesAreNotTitles:
    """An ICP persona is a buying role plus titles, and both become targets.
    The role must never be read as a title: "technical_buyer" as words is a
    tech function with no rank, and every developer on a list answered it."""

    def test_a_developer_does_not_answer_a_buying_role(self):
        targets = ("technical_buyer", "cto")
        assert matches_persona(_Contact(title="Junior Developer"), targets) is False

    def test_a_contact_classified_with_the_role_does(self):
        assert matches_persona(_Contact(buying_role="technical_buyer"), ("technical_buyer",)) is True

    def test_the_titles_beside_the_role_still_match(self):
        targets = ("technical_buyer", "cto", "cio", "it head")
        assert matches_persona(_Contact(title="VP of Engineering"), targets) is True


def test_corporate_development_is_not_engineering():
    """Live on Apollo: BlueWave's SVP Corporate Development was suggested as a
    technical buyer, because with `corporate` dropped as noise `development`
    read as engineering."""
    from app.services import personas

    assert not personas.matches_any("SVP Corporate Development", ("CTO", "CIO", "IT head"))
    assert personas.tokens("VP of Business Development") == ["vp", "bizdev"]
    assert personas.tokens("Chief Information and Security Officer") == personas.tokens(
        "Chief Information Security Officer"
    )
