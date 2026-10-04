"""LGM identity resolution — clustering contacts the way LGM would.

The case that drove this design: contact A has LinkedIn X and email E; contact
B has no LinkedIn and email E. Under a coalesce cascade they produce *different*
keys, so a unique index admits both — and LGM then merges them on the shared
email. Their sequences overwrite each other's attributes, which is the exact
state the enrolment lock exists to prevent.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.campaign import LgmIdentity
from app.services.lgm_identity import (
    UnresolvableContactError,
    keys_for,
    name_company_key,
    normalise_email,
    normalise_linkedin,
    resolve,
)

pytestmark = pytest.mark.db

TEST_DB = os.getenv("TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DB)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


class TestNormalisation:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.linkedin.com/in/Dana-Reyes/",
            "http://linkedin.com/in/dana-reyes",
            "linkedin.com/in/DANA-REYES/",
            "https://uk.linkedin.com/in/dana-reyes?trk=abc",
        ],
    )
    def test_one_profile_yields_one_key(self, url):
        """Host, casing, trailing slash and tracking params are all noise to
        LGM, and each would otherwise create a separate identity."""
        assert normalise_linkedin(url) == "dana-reyes"

    def test_a_non_profile_url_is_not_an_identifier(self):
        assert normalise_linkedin("https://linkedin.com/company/meridian") is None
        assert normalise_linkedin("https://example.com/dana") is None
        assert normalise_linkedin("   ") is None

    def test_email_is_lowercased_and_trimmed(self):
        assert normalise_email("  Dana@Meridian.IO ") == "dana@meridian.io"

    def test_a_string_without_an_at_is_not_an_email(self):
        assert normalise_email("dana") is None

    def test_the_name_key_ignores_punctuation_and_case(self):
        assert name_company_key("Dana O'Reyes", "Meridian Cloud") == name_company_key(
            "dana oreyes", "MERIDIAN  CLOUD"
        )

    def test_the_name_key_needs_both_halves(self):
        assert name_company_key("Dana", None) is None
        assert name_company_key(None, "Meridian") is None


class TestTheFallbackIsOnlyUsedWhenItIsTheFallback:
    def test_a_contact_with_linkedin_gets_no_name_key(self):
        """Computing it always would let a weak match cluster two people who
        share a name at one company."""
        keys = keys_for(
            linkedin_url="linkedin.com/in/dana-reyes",
            email="dana@meridian.io",
            full_name="Dana Reyes",
            company="Meridian Cloud",
        )
        assert keys.linkedin_slug == "dana-reyes"
        assert keys.email == "dana@meridian.io"
        assert keys.name_company_key is None

    def test_a_contact_with_neither_falls_back_to_the_name(self):
        keys = keys_for(
            linkedin_url=None, email=None, full_name="Dana Reyes", company="Meridian Cloud"
        )
        assert keys.name_company_key is not None

    def test_a_contact_with_nothing_has_no_keys(self):
        assert not keys_for(
            linkedin_url=None, email=None, full_name=None, company=None
        ).any


@requires_db
class TestResolution:
    async def test_a_new_contact_creates_an_identity(self, session):
        keys = keys_for(
            linkedin_url="linkedin.com/in/dana-reyes",
            email="dana@meridian.io", full_name="Dana Reyes", company="Meridian",
        )
        identity = await resolve(session, keys)
        assert identity.resolution_state == "resolved"
        assert identity.linkedin_slug == "dana-reyes"

    async def test_the_same_profile_resolves_to_the_same_identity(self, session):
        first = await resolve(
            session,
            keys_for(linkedin_url="https://www.linkedin.com/in/Dana-Reyes/",
                     email=None, full_name=None, company=None),
        )
        second = await resolve(
            session,
            keys_for(linkedin_url="linkedin.com/in/dana-reyes",
                     email=None, full_name=None, company=None),
        )
        assert first.id == second.id

    async def test_a_shared_email_resolves_to_one_identity_across_companies(self, session):
        """LGM merges on email regardless of company, so we must too."""
        first = await resolve(
            session,
            keys_for(linkedin_url=None, email="dana@meridian.io",
                     full_name="Dana", company="Meridian"),
        )
        second = await resolve(
            session,
            keys_for(linkedin_url=None, email="Dana@Meridian.IO",
                     full_name="Dana", company="Other Co"),
        )
        assert first.id == second.id

    async def test_a_later_linkedin_url_attaches_to_the_email_identity(self, session):
        """This is the merge LGM would perform, made visible to us."""
        first = await resolve(
            session,
            keys_for(linkedin_url=None, email="dana@meridian.io",
                     full_name=None, company=None),
        )
        second = await resolve(
            session,
            keys_for(linkedin_url="linkedin.com/in/dana-reyes",
                     email="dana@meridian.io", full_name=None, company=None),
        )
        assert first.id == second.id
        assert second.linkedin_slug == "dana-reyes"

    async def test_the_documented_hole_is_closed(self, session):
        """Contact A: LinkedIn X + email E. Contact B: email E only.

        A coalesce cascade gives them different keys and lets both through.
        Matching on *any* identifier puts them on one identity, which is what
        LGM does.
        """
        a = await resolve(
            session,
            keys_for(linkedin_url="linkedin.com/in/dana-reyes",
                     email="shared@meridian.io", full_name=None, company=None),
        )
        b = await resolve(
            session,
            keys_for(linkedin_url=None, email="shared@meridian.io",
                     full_name=None, company=None),
        )
        assert a.id == b.id, "B would have got its own identity and its own sequence"

    async def test_matching_two_identities_is_a_conflict_not_a_guess(self, session):
        """LGM's behaviour here is undocumented. Guessing which record it
        merges into risks corrupting whichever sequence guessed wrong."""
        session.add_all(
            [
                LgmIdentity(linkedin_slug="dana-reyes"),
                LgmIdentity(email="dana@meridian.io"),
            ]
        )
        await session.flush()

        result = await resolve(
            session,
            keys_for(linkedin_url="linkedin.com/in/dana-reyes",
                     email="dana@meridian.io", full_name=None, company=None),
        )
        assert result.resolution_state == "conflict"
        assert "undocumented" in result.conflict_detail

    async def test_a_contact_with_no_identifiers_is_refused(self, session):
        with pytest.raises(UnresolvableContactError):
            await resolve(
                session,
                keys_for(linkedin_url=None, email=None, full_name=None, company=None),
            )

    async def test_an_identity_needs_at_least_one_identifier(self, session):
        from sqlalchemy.exc import IntegrityError

        session.add(LgmIdentity())
        with pytest.raises(IntegrityError):
            await session.flush()
