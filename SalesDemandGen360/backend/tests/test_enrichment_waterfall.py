"""Apollo → ContactOut. A waterfall, not a race.

Both providers are metered per call, so the property under test is as much
"how many calls did that cost" as "what did it find".
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.providers import (
    ContactRecord,
    Provider,
    ProviderError,
    enrich,
)


@dataclass
class FakeProvider:
    name: Provider
    result: ContactRecord | None = None
    raises: str | None = None
    calls: int = 0

    async def enrich(self, *, full_name, company_domain, linkedin_url):
        self.calls += 1
        if self.raises:
            raise ProviderError(self.raises)
        return self.result


def apollo(**over) -> FakeProvider:
    return FakeProvider(name=Provider.APOLLO, **over)


def contactout(**over) -> FakeProvider:
    return FakeProvider(name=Provider.CONTACTOUT, **over)


class TestTheFallbackIsOnlyPaidForWhenNeeded:
    async def test_a_complete_primary_answer_never_calls_the_fallback(self):
        a = apollo(result=ContactRecord("Dana Reyes", email="dana@meridian.io"))
        c = contactout(result=ContactRecord("Dana Reyes", email="other@meridian.io"))

        outcome = await enrich(full_name="Dana Reyes", primary=a, fallback=c)

        assert outcome.called == [Provider.APOLLO]
        assert c.calls == 0, "the fallback was billed for nothing"
        assert outcome.contact.email == "dana@meridian.io"

    async def test_a_missing_field_triggers_the_fallback_even_without_an_error(self):
        """The trigger is an unusable result, not an exception. Waiting for
        errors would leave the waterfall permanently dry — Apollo returning a
        person with no email is a perfectly successful call."""
        a = apollo(result=ContactRecord("Dana Reyes", title="VP Engineering"))
        c = contactout(result=ContactRecord("Dana Reyes", email="dana@meridian.io"))

        outcome = await enrich(full_name="Dana Reyes", primary=a, fallback=c)

        assert outcome.called == [Provider.APOLLO, Provider.CONTACTOUT]
        assert outcome.contact.email == "dana@meridian.io"
        assert outcome.contact.title == "VP Engineering", "the primary's answer survives"

    async def test_the_primary_wins_every_contested_field(self):
        """Otherwise the result depends on call order in a way nobody can see —
        and the fallback is the fallback because it is trusted less."""
        a = apollo(result=ContactRecord("Dana Reyes", title="VP Engineering"))
        c = contactout(
            result=ContactRecord("Dana Reyes", title="Head of Eng", email="dana@meridian.io")
        )

        outcome = await enrich(full_name="Dana Reyes", primary=a, fallback=c)
        assert outcome.contact.title == "VP Engineering"

    async def test_each_field_records_where_it_came_from(self):
        a = apollo(result=ContactRecord("Dana Reyes", title="VP Engineering"))
        c = contactout(result=ContactRecord("Dana Reyes", email="dana@meridian.io"))

        outcome = await enrich(full_name="Dana Reyes", primary=a, fallback=c)

        assert outcome.contact.sources == {
            "title": "apollo",
            "email": "contactout",
        }


class TestFailureDoesNotLoseTheOtherProvider:
    async def test_a_dead_primary_still_lets_the_fallback_answer(self):
        a = apollo(raises="503 from Apollo")
        c = contactout(result=ContactRecord("Dana Reyes", email="dana@meridian.io"))

        outcome = await enrich(full_name="Dana Reyes", primary=a, fallback=c)

        assert outcome.contact.email == "dana@meridian.io"
        assert outcome.errors == {"apollo": "503 from Apollo"}

    async def test_both_failing_reports_both_and_finds_nothing(self):
        outcome = await enrich(
            full_name="Dana Reyes",
            primary=apollo(raises="503"),
            fallback=contactout(raises="timeout"),
        )
        assert outcome.contact is None
        assert set(outcome.errors) == {"apollo", "contactout"}
        assert outcome.still_missing == ("email",)

    async def test_nobody_knowing_the_person_is_not_an_error(self):
        outcome = await enrich(
            full_name="Nobody", primary=apollo(), fallback=contactout()
        )
        assert outcome.contact is None
        assert outcome.errors == {}
        assert outcome.still_missing == ("email",)


class TestWhatCountsAsResolved:
    async def test_still_missing_names_the_fields_that_never_arrived(self):
        outcome = await enrich(
            full_name="Dana Reyes",
            primary=apollo(result=ContactRecord("Dana Reyes", email="d@x.io")),
            required=("email", "phone"),
        )
        assert outcome.still_missing == ("phone",)

    async def test_the_fallback_runs_when_any_required_field_is_short(self):
        a = apollo(result=ContactRecord("Dana Reyes", email="d@x.io"))
        c = contactout(result=ContactRecord("Dana Reyes", phone="+1555"))

        outcome = await enrich(
            full_name="Dana Reyes", primary=a, fallback=c, required=("email", "phone")
        )

        assert outcome.called == [Provider.APOLLO, Provider.CONTACTOUT]
        assert outcome.still_missing == ()

    async def test_no_fallback_configured_is_not_an_error(self):
        outcome = await enrich(
            full_name="Dana Reyes", primary=apollo(result=ContactRecord("Dana Reyes"))
        )
        assert outcome.called == [Provider.APOLLO]
        assert outcome.still_missing == ("email",)


class TestTheCrmInterfaceCannotOverwrite:
    def test_there_is_no_update_or_delete_method(self):
        """`docs/02 §10`: CRM writes are create/append only. A method that does
        not exist cannot be called by a future adapter being careless."""
        from app.services.crm import CrmAdapter

        surface = {m for m in dir(CrmAdapter) if not m.startswith("_")}
        assert surface == {"find_account", "contacts_for", "create_account", "append_note"}

    @pytest.mark.parametrize("forbidden", ["update_account", "delete_account", "set_field"])
    def test_named_mutators_are_absent(self, forbidden):
        from app.services.crm import CrmAdapter

        assert not hasattr(CrmAdapter, forbidden)
