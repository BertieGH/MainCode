"""An ICP per service, and what enrichment refuses without one.

The rule this file exists to hold: **a metered call is never made until
somebody has said who it is looking for.** Enrichment used to run alphabetically
over every unverified contact on a list, which pays Apollo to find a junior
developer's address when the service needed the CTO — and the list then *looks*
enriched, which is the part that costs more than the credits.

So a pass takes a service, the service must have an ICP, and contacts that
match neither are reported rather than quietly paid for. See `docs/11`.
"""

from __future__ import annotations

import uuid

import pytest

from app.services import verification
from app.services.verification import (
    NoServiceIcpError,
    matches_persona,
    target_personas,
)


class _Service:
    """A service names nobody. Who to reach is the ICP's question."""

    def __init__(self, code="qa_engineering", is_active=True):
        self.id = uuid.uuid4()
        self.code = code
        self.is_active = is_active


class _Profile:
    """An ICP's identity. Links point here, not at a version."""

    def __init__(self, name="Default"):
        self.id = uuid.uuid4()
        self.name = name


class _Icp:
    """One version of a profile — the part that holds the definition."""

    def __init__(self, profile=None, definition=None, version=3):
        self.profile = profile or _Profile()
        self.icp_profile_id = self.profile.id
        self.definition = definition or {}
        self.version = version
        self.is_active = True


class _Contact:
    def __init__(self, title=None, persona_role=None, buying_role=None, seniority="unknown"):
        self.id = uuid.uuid4()
        self.full_name = "Dana Reyes"
        self.title = title
        self.persona_role = persona_role
        self.buying_role = buying_role
        self.seniority = seniority


class _Session:
    """Serves one service and one linked ICP; either can be absent.

    Two queries to answer now rather than one: `resolve_targeting` asks which
    profiles are linked to the service, then asks each for its active version.
    The split is the point — a profile can be linked and still have nothing
    written against it, and that has to be distinguishable.
    """

    def __init__(self, service=None, icp=None, linked=None):
        self.service = service
        self.icp = icp
        #: Profiles linked to the service. Defaults to the ICP's own profile,
        #: so the common case needs no wiring; set explicitly to test a link
        #: pointing at a profile with no active version.
        self.linked = linked if linked is not None else ([icp.profile] if icp else [])

    async def get(self, model, pk):
        return self.service if self.service and self.service.id == pk else None

    async def execute(self, stmt):
        outer = self
        rendered = str(stmt)

        class _R:
            def scalars(self):
                return self

            def all(self):
                if "FROM icp_profile JOIN service_icp_link" in rendered:
                    return list(outer.linked)
                return []

            def scalar_one_or_none(self):
                if "FROM icp_profile_version" in rendered:
                    return outer.icp
                return None

        return _R()


class TestBothMustExistBeforeSpending:
    async def test_an_unknown_service_is_refused(self):
        with pytest.raises(NoServiceIcpError, match="does not exist"):
            await verification.resolve_targeting(_Session(), service_id=uuid.uuid4())

    async def test_a_service_with_no_icp_is_refused(self):
        """The whole point. A credential connects you to a vendor; it does not
        tell the vendor who to look for."""
        service = _Service()
        with pytest.raises(NoServiceIcpError, match="has no ICP yet"):
            await verification.resolve_targeting(
                _Session(service=service), service_id=service.id
            )

    async def test_an_inactive_service_is_refused(self):
        """Nothing will be pitched to whoever it finds, so finding them is
        spending for an outcome that cannot happen."""
        service = _Service(is_active=False)
        session = _Session(service=service, icp=_Icp())
        with pytest.raises(NoServiceIcpError, match="not an active service"):
            await verification.resolve_targeting(session, service_id=service.id)

    async def test_the_error_names_which_half_is_missing(self):
        """A missing credential and a missing ICP need different work, so the
        message has to say which — not "setup incomplete"."""
        service = _Service(code="eia")
        with pytest.raises(NoServiceIcpError) as caught:
            await verification.resolve_targeting(
                _Session(service=service), service_id=service.id
            )
        assert "eia" in str(caught.value)

    async def test_a_link_to_an_unwritten_profile_is_refused(self):
        """Linked is not the same as described.

        A service can be linked to a profile whose definition nobody has
        written. Treating that as described would satisfy the gate and then
        hand enrichment no personas at all — which is the indiscriminate pass
        this whole file exists to prevent, reached by a different route.
        """
        service = _Service(code="eia")
        session = _Session(service=service, icp=None, linked=[_Profile("Mid-market")])
        with pytest.raises(NoServiceIcpError, match="no active version"):
            await verification.resolve_targeting(session, service_id=service.id)

    async def test_a_described_service_resolves(self):
        service = _Service()
        icp = _Icp(version=7)
        got_service, got_icps = await verification.resolve_targeting(
            _Session(service=service, icp=icp), service_id=service.id
        )
        assert got_service is service
        assert [v.version for v in got_icps] == [7]


class TestWhoTheIcpIsLookingFor:
    """Buyer personas come from the ICP and nowhere else.

    The service row used to add its own `target_personas`, holding job titles
    on one service and buying roles on another. It meant an ICP could never
    narrow what a service had already widened. A service now says only who
    signs off, broadly, and that is not a filter.
    """

    def test_both_halves_of_a_persona_become_targets(self):
        """Titles are what a CSV carries; the role is what a classified
        contact carries. Either is enough to match."""
        targets = target_personas(
            {"personas": [{"buying_role": "technical_buyer", "titles": ["CTO", "IT head"]}]}
        )
        assert set(targets) == {"technical_buyer", "cto", "it head"}

    def test_several_icps_are_a_union(self):
        """A contact worth reaching for either profile is worth reaching."""
        targets = target_personas(
            {"personas": [{"buying_role": "economic_buyer", "titles": ["CEO"]}]},
            {"target_personas": ["VP Engineering"]},
        )
        assert set(targets) == {"economic_buyer", "ceo", "vp engineering"}

    def test_an_icp_naming_nobody_targets_nobody(self):
        assert target_personas({}, None) == ()

    def test_an_older_list_of_bare_titles_is_still_read(self):
        titles = target_personas({"personas": ["CTO"]})
        assert matches_persona(_Contact(title="Chief Technology Officer, CTO"), titles)

    def test_a_role_matches_a_classified_contact(self):
        roles = target_personas({"personas": [{"buying_role": "technical_buyer", "titles": []}]})
        assert matches_persona(_Contact(buying_role="technical_buyer"), roles)

    def test_duplicates_collapse(self):
        assert target_personas(
            {"personas": ["CTO", "cto", " CTO "]}, {"target_personas": ["CTO"]}
        ) == ("cto",)


class TestTheThirdAnswer:
    """`matches_persona` returns True, False **or None**, and None is the point.

    A contact with no title is not a bad match, they are an unknown one.
    Collapsing the two either drops real buyers whose title was never imported,
    or spends the entire budget on people nobody can use.
    """

    def test_a_match_is_true(self):
        assert matches_persona(_Contact(title="CTO"), ("cto",)) is True

    def test_a_clear_mismatch_is_false(self):
        assert matches_persona(_Contact(title="Junior Developer"), ("cto",)) is False

    def test_nothing_to_judge_on_is_none(self):
        assert matches_persona(_Contact(), ("cto",)) is None

    def test_no_targets_at_all_is_none_not_a_rejection(self):
        """A service that named nobody has not rejected everybody."""
        assert matches_persona(_Contact(title="CTO"), ()) is None

    def test_any_field_can_carry_the_match(self):
        for contact in (
            _Contact(title="Head of Engineering"),
            _Contact(persona_role="engineering"),
            _Contact(buying_role="engineering_lead"),
        ):
            assert matches_persona(contact, ("engineering",)) is True

    def test_seniority_counts_only_when_it_is_known(self):
        """`unknown` is a placeholder, not a role. Matching on it would make
        every unclassified contact match a target called `unknown`."""
        assert matches_persona(_Contact(seniority="unknown"), ("unknown",)) is None
        assert matches_persona(_Contact(seniority="c_level"), ("c_level",)) is True
