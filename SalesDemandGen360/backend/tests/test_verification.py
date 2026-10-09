"""The cross-check between importing a list and using it.

A CSV contact is a claim, not a route: the spreadsheet says the address exists,
and nobody has established that sending to it will not bounce a sending
domain's reputation. This pass is what turns one into the other.

The distinctions under test are all about *not lying about what happened*. A
pass that could not run, a pass that ran and found nobody, and a pass where the
provider was down are three different situations needing three different
actions — and collapsing any two of them is how a reachable contact gets
written off, or an unreachable one is retried forever.
"""

from __future__ import annotations

import uuid

import pytest

from app.services import verification
from app.services.providers import ContactRecord, Provider, ProviderError


class FakeProvider:
    """A provider that answers however the test needs it to."""

    def __init__(self, name: Provider, record: ContactRecord | None = None, fails=False):
        self.name = name
        self.record = record
        self.fails = fails
        self.calls = 0

    async def enrich(self, *, full_name, company_domain, linkedin_url):
        self.calls += 1
        if self.fails:
            raise ProviderError("provider unavailable")
        return self.record


class _Contact:
    """Enough of a Contact row for the write-back to be observable."""

    def __init__(
        self, name="Dana Reyes", email=None, status="unverified",
        title="Head of Operations",
    ):
        self.id = uuid.uuid4()
        self.full_name = name
        self.email = email
        self.email_status = status
        self.email_provider = None
        self.email_provider_record_id = None
        self.phone = None
        self.phone_status = "unverified"
        self.phone_provider = None
        self.phone_provider_record_id = None
        # A title by default: without one every contact lands in the
        # `unknown_persona` bucket and no test would reach the waterfall.
        self.title = title
        self.persona_role = None
        self.buying_role = None
        self.seniority = "unknown"
        self.linkedin_url = None


class _StubService:
    """The service a pass is run for. It names nobody: who to reach is the
    ICP's buyer personas, and only those."""

    def __init__(self, code="qa_engineering", is_active=True):
        self.id = uuid.uuid4()
        self.code = code
        self.is_active = is_active


class _StubProfile:
    """A named ICP. Identity only — the definition lives on the version.

    Split the way the real tables are, because links point at identity: a new
    version must not orphan the services that referenced the profile.
    """

    def __init__(self, name="Default"):
        self.id = uuid.uuid4()
        self.name = name


class _StubIcp:
    """One version of a profile. `definition` is what personas are read from."""

    def __init__(self, profile=None, definition=None, version=1):
        self.profile = profile or _StubProfile()
        self.icp_profile_id = self.profile.id
        # Names the default contact's title, so the waterfall tests reach the
        # waterfall. An ICP naming nobody is refused before any spend.
        self.definition = (
            definition
            if definition is not None
            else {"personas": [{"buying_role": "champion", "titles": ["Head of Operations"]}]}
        )
        self.version = version
        self.is_active = True


class _Session:
    def __init__(self, order=(), credentials=None, contacts=(), service=None, icp=None):
        self.order = list(order)
        self.credentials = credentials or {}
        self.contacts = list(contacts)
        self.flushed = False
        self.service = service if service is not None else _StubService()
        self.icp = icp if icp is not None else _StubIcp()

    async def get(self, model, pk):
        """`resolve_service` looks the service up by id."""
        return self.service if self.service and self.service.id == pk else None

    async def execute(self, stmt):
        rendered = str(stmt)
        outer = self

        class _Row:
            def __init__(self, provider, status):
                self.provider = provider
                self.credential_type = "api_key"
                self.status = status

        class _R:
            def scalars(self):
                return self

            def __iter__(self):
                if "FROM integration_credential" in rendered:
                    return iter(
                        [_Row(p, s) for p, s in outer.credentials.items()]
                    )
                if "FROM contact" in rendered:
                    return iter(outer.contacts)
                return iter([])

            def all(self):
                # `resolve_targeting` asks for the profiles linked to the
                # service before asking for each one's active version.
                if "FROM icp_profile JOIN service_icp_link" in rendered:
                    return [outer.icp.profile] if outer.icp else []
                return list(self)

            def scalar_one_or_none(self):
                if "FROM icp_profile_version" in rendered:
                    return outer.icp
                return None

        return _R()

    async def flush(self):
        self.flushed = True


class _ConfigSession(_Session):
    """Adds the active enrichment config that `get_active` looks for."""

    #: What the waterfall chases. Overridden per test — it is the lever that
    #: decides how many providers a contact costs.
    wanted = ["email"]

    async def execute(self, stmt):
        if "FROM enrichment_config" in str(stmt):
            outer = self

            class _R:
                def scalar_one_or_none(self):
                    class _Cfg:
                        provider_order = outer.order
                        required_fields = outer.wanted

                    return _Cfg()

            return _R()
        return await super().execute(stmt)


def _record(email="dana@northwind.example", source="contactout", status="verified"):
    return ContactRecord(
        full_name="Dana Reyes",
        email=email,
        email_status=status,
        sources={"email": source},
    )


class TestWhichProvidersCanActuallyRun:
    """A valid key on a vendor we cannot call is not a working provider.

    The same two facts the setup gate keeps apart, kept apart here for the same
    reason.
    """

    async def test_a_provider_without_a_verified_key_is_excluded(self):
        session = _ConfigSession(
            order=["contactout", "apollo"],
            credentials={"contactout": "untested", "apollo": "valid"},
        )
        usable, reasons = await verification.credentialled_providers(session)
        assert "contactout" not in usable
        assert any("no verified credential" in r for r in reasons)

    async def test_a_provider_with_no_client_blocks_the_pass_and_says_so(self):
        """The credential is fine; the client that fetches contacts is not
        written. Judged at the run, not in the credential check, because an
        injected client is a client."""
        session = _ConfigSession(
            order=["contactout"], credentials={"contactout": "valid"}
        )
        credentialled, _ = await verification.credentialled_providers(session)
        assert credentialled == ["contactout"]

        report = await verification.verify_list(
            session, list_id=uuid.uuid4(), service_id=session.service.id)
        assert not report.ran
        assert "no client for it yet" in report.blocked

    def test_the_shipped_clients_are_named_here(self):
        """Fails the day one is added, which is the point — whoever writes it
        has to come here rather than let the catalogue disagree with the code.

        Both are present now. The list is the claim "a client exists", which
        is weaker than "it works against the vendor" — Apollo's mapping came
        off a live response, ContactOut's did not.
        """
        assert verification.BUILT_IN_PROVIDERS == ("apollo", "contactout")

    async def test_the_configured_order_is_preserved(self):
        session = _ConfigSession(order=["apollo", "contactout"], credentials={})
        _, reasons = await verification.credentialled_providers(session)
        # A waterfall is an order, so the reasons come back in it too.
        assert reasons[0].startswith("Apollo.io")


class TestAPassThatCannotRunSaysSo:
    async def test_no_provider_means_blocked_not_zero_verified(self):
        """"0 verified" over a list nobody checked reads as a clean pass."""
        session = _ConfigSession(order=["contactout"], credentials={})
        report = await verification.verify_list(
            session, list_id=uuid.uuid4(), service_id=session.service.id, clients={})

        assert not report.ran
        assert report.blocked
        assert report.checked == 0
        assert "No enrichment provider could be called" in report.blocked

    async def test_the_reason_names_what_is_missing(self):
        session = _ConfigSession(
            order=["contactout"], credentials={"contactout": "invalid"}
        )
        report = await verification.verify_list(
            session, list_id=uuid.uuid4(), service_id=session.service.id, clients={})
        assert "no verified credential" in report.blocked


class TestTheWaterfall:
    def _session(self, contacts):
        return _ConfigSession(
            order=["contactout", "apollo"],
            credentials={"contactout": "valid", "apollo": "valid"},
            contacts=contacts,
        )

    async def test_a_verified_contact_is_written_back_with_its_source(self):
        contact = _Contact()
        session = self._session([contact])
        first = FakeProvider(Provider.CONTACTOUT, _record())

        report = await verification.verify_list(
            session, list_id=uuid.uuid4(), service_id=session.service.id, clients={"contactout": first}
        )

        assert report.verified == 1
        assert contact.email == "dana@northwind.example"
        assert contact.email_status == "verified"
        # Provenance, so a bad source is traceable without distrusting the
        # whole list later.
        assert contact.email_provider == "contactout"

    async def test_the_second_provider_is_not_called_when_the_first_answers(self):
        """Metered per call. Asking everyone multiplies the bill on every
        contact the first provider already resolved."""
        contact = _Contact()
        first = FakeProvider(Provider.CONTACTOUT, _record())
        second = FakeProvider(Provider.APOLLO, _record())

        await verification.verify_list(
            session := self._session([contact]),
            list_id=uuid.uuid4(),
            service_id=session.service.id,
            clients={"contactout": first, "apollo": second},
        )
        assert first.calls == 1
        assert second.calls == 0

    async def test_the_fallback_runs_when_the_first_has_nothing(self):
        contact = _Contact()
        first = FakeProvider(Provider.CONTACTOUT, None)
        second = FakeProvider(Provider.APOLLO, _record(source="apollo"))

        report = await verification.verify_list(
            session := self._session([contact]),
            list_id=uuid.uuid4(),
            service_id=session.service.id,
            clients={"contactout": first, "apollo": second},
        )
        assert second.calls == 1
        assert report.verified == 1
        assert contact.email_provider == "apollo"

    async def test_nobody_found_is_not_the_same_as_a_provider_failing(self):
        """Two situations, two actions: a different list, or a retry."""
        found_nothing = _Contact()
        report = await verification.verify_list(
            session := self._session([found_nothing]),
            list_id=uuid.uuid4(),
            service_id=session.service.id,
            clients={"contactout": FakeProvider(Provider.CONTACTOUT, None)},
        )
        assert report.not_found == 1
        assert report.unavailable == 0
        assert found_nothing.email_status == "unverified"

    async def test_a_failing_provider_leaves_the_contact_untouched(self):
        contact = _Contact()
        report = await verification.verify_list(
            session := self._session([contact]),
            list_id=uuid.uuid4(),
            service_id=session.service.id,
            clients={"contactout": FakeProvider(Provider.CONTACTOUT, fails=True)},
        )
        assert report.unavailable == 1
        # Unchanged, which is what makes a retry correct rather than a
        # duplicate charge on a contact already written off.
        assert contact.email_status == "unverified"
        assert contact.email is None

    async def test_a_spreadsheet_address_is_replaced_by_the_verified_one(self):
        contact = _Contact(email="typo@northwind.example")
        await verification.verify_list(
            session := self._session([contact]),
            list_id=uuid.uuid4(),
            service_id=session.service.id,
            clients={"contactout": FakeProvider(Provider.CONTACTOUT, _record())},
        )
        assert contact.email == "dana@northwind.example"


class TestAGuessIsNotAVerifiedAddress:
    """The provider grades the address; this pass does not overrule it.

    Apollo returns *guessed* addresses — its known format for a company applied
    to a name — alongside confirmed ones, and says which is which. This pass
    used to write `email_status = "verified"` for anything a provider returned,
    which made the guess indistinguishable from the confirmation and put the
    cost of being wrong on the sending domain's reputation.
    """

    def _session(self, contacts):
        return _ConfigSession(
            order=["apollo", "contactout"],
            credentials={"apollo": "valid", "contactout": "valid"},
            contacts=contacts,
        )

    async def test_a_guess_is_stored_as_risky_and_not_counted_verified(self):
        contact = _Contact()
        session = self._session([contact])
        apollo = FakeProvider(Provider.APOLLO, _record(source="apollo", status="risky"))

        report = await verification.verify_list(
            session, list_id=uuid.uuid4(), service_id=session.service.id, clients={"apollo": apollo}
        )

        assert report.verified == 0, "a guess was counted as a verified contact"
        assert report.risky == 1
        assert contact.email_status == "risky"

    async def test_the_address_is_still_written_so_a_rep_can_see_it(self):
        """Risky is not useless. It is unconfirmed, and a person may confirm it."""
        contact = _Contact()
        session = self._session([contact])
        apollo = FakeProvider(Provider.APOLLO, _record(source="apollo", status="risky"))

        await verification.verify_list(
            session, list_id=uuid.uuid4(), service_id=session.service.id, clients={"apollo": apollo}
        )

        assert contact.email == "dana@northwind.example"
        assert contact.email_provider == "apollo"

    async def test_the_detail_says_which_grade_and_who_gave_it(self):
        contact = _Contact()
        session = self._session([contact])
        apollo = FakeProvider(Provider.APOLLO, _record(source="apollo", status="risky"))

        report = await verification.verify_list(
            session, list_id=uuid.uuid4(), service_id=session.service.id, clients={"apollo": apollo}
        )

        detail = report.outcomes[0].detail
        assert "apollo" in detail and "risky" in detail

    async def test_risky_is_counted_apart_from_not_found(self):
        """Different work: a guess needs confirming, a miss needs a better key."""
        found, missing = _Contact(), _Contact()
        session = self._session([found, missing])

        class Mixed:
            name = Provider.APOLLO

            def __init__(self):
                self._calls = 0

            async def enrich(self, **_):
                self._calls += 1
                if self._calls == 1:
                    return _record(source="apollo", status="risky")
                return None

        report = await verification.verify_list(
            session, list_id=uuid.uuid4(), service_id=session.service.id, clients={"apollo": Mixed()}
        )

        assert (report.verified, report.risky, report.not_found) == (0, 1, 1)


class TestChasingAPhoneNumber:
    """`enrichment_config.required_fields` decides how far the waterfall goes.

    Adding `phone` to it is a decision with a bill attached: a contact whose
    email the first provider already resolved now costs a second call. These
    tests pin the two things that keep that bill honest — the extra call only
    happens when a provider could actually answer it, and a number that never
    turns up does not cost the contact their `verified` status.
    """

    def _session(self, contacts, wanted, order=("apollo", "contactout")):
        session = _ConfigSession(
            order=list(order),
            credentials={"apollo": "valid", "contactout": "valid"},
            contacts=contacts,
        )
        session.wanted = wanted
        return session

    async def test_the_waterfall_continues_for_a_phone_after_the_email_is_found(self):
        contact = _Contact()
        session = self._session([contact], ["email", "phone"])

        emailer = FakeProvider(Provider.APOLLO, _record(source="apollo"))
        emailer.supplies = frozenset({"email"})
        phoner = FakeProvider(
            Provider.CONTACTOUT,
            ContactRecord(full_name="Dana Reyes", phone="+1 555 0100"),
        )
        phoner.supplies = frozenset({"email", "phone"})

        report = await verification.verify_list(
            session,
            list_id=uuid.uuid4(),
            service_id=session.service.id,
            clients={"apollo": emailer, "contactout": phoner},
        )

        assert report.verified == 1
        assert contact.email == "dana@northwind.example"
        assert contact.phone == "+1 555 0100"
        assert report.with_phone == 1

    async def test_the_second_provider_is_not_called_when_phone_is_not_wanted(self):
        """The old behaviour, still correct when the config says email only."""
        contact = _Contact()
        session = self._session([contact], ["email"])

        emailer = FakeProvider(Provider.APOLLO, _record(source="apollo"))
        phoner = FakeProvider(
            Provider.CONTACTOUT,
            ContactRecord(full_name="Dana Reyes", phone="+1 555 0100"),
        )

        await verification.verify_list(
            session,
            list_id=uuid.uuid4(),
            service_id=session.service.id,
            clients={"apollo": emailer, "contactout": phoner},
        )

        assert phoner.calls == 0
        assert contact.phone is None

    async def test_a_provider_that_cannot_supply_a_phone_is_not_billed_for_one(self):
        """Apollo has no synchronous phone at all — asking is pure cost.

        `reveal_phone_number` is a 400 without a webhook receiver, so a call
        made solely to find a number could never have answered.
        """
        contact = _Contact()
        # ContactOut first, so the email is already resolved by the time Apollo
        # would be reached and `phone` is all that is outstanding.
        session = self._session(
            [contact], ["email", "phone"], order=("contactout", "apollo")
        )

        phoner = FakeProvider(
            Provider.CONTACTOUT, _record(source="contactout")
        )  # email only, no phone in the record
        phoner.supplies = frozenset({"email", "phone"})
        apollo = FakeProvider(Provider.APOLLO, _record(source="apollo"))
        apollo.supplies = frozenset({"email", "title"})

        await verification.verify_list(
            session,
            list_id=uuid.uuid4(),
            service_id=session.service.id,
            clients={"contactout": phoner, "apollo": apollo},
        )

        assert apollo.calls == 0, "Apollo was billed for a phone it cannot return"

    async def test_no_phone_found_still_leaves_the_contact_verified(self):
        """The gate is the address. A missing mobile is a gap, not a rejection."""
        contact = _Contact()
        session = self._session([contact], ["email", "phone"])

        emailer = FakeProvider(Provider.CONTACTOUT, _record(source="contactout"))
        emailer.supplies = frozenset({"email", "phone"})

        report = await verification.verify_list(
            session, list_id=uuid.uuid4(), service_id=session.service.id, clients={"contactout": emailer}
        )

        assert report.verified == 1, "a contactable person was written off"
        assert report.not_found == 0
        assert contact.email_status == "verified"
        assert contact.phone is None
        assert report.with_phone == 0

    async def test_the_report_says_what_was_chased(self):
        contact = _Contact()
        session = self._session([contact], ["email", "phone"])
        emailer = FakeProvider(Provider.CONTACTOUT, _record(source="contactout"))

        report = await verification.verify_list(
            session, list_id=uuid.uuid4(), service_id=session.service.id, clients={"contactout": emailer}
        )

        assert report.wanted == ["email", "phone"]


class TestWhatEndsUpOnTheContact:
    """Everything a provider returns that the row can hold gets held.

    The point of chasing a phone and a profile is that they are *stored* — a
    rep opening the contact sees the number and the LinkedIn link next to the
    address. A pass that found them and dropped them would have spent the extra
    provider call for nothing.
    """

    def _session(self, contacts):
        session = _ConfigSession(
            order=["contactout"],
            credentials={"contactout": "valid"},
            contacts=contacts,
        )
        session.wanted = ["email", "phone", "linkedin_url"]
        return session

    async def test_email_phone_and_linkedin_are_all_written(self):
        contact = _Contact()
        session = self._session([contact])
        provider = FakeProvider(
            Provider.CONTACTOUT,
            ContactRecord(
                full_name="Dana Reyes",
                email="dana@northwind.example",
                email_status="verified",
                phone="+15550100",
                linkedin_url="https://www.linkedin.com/in/danareyes",
                title="Head of Operations",
                provider_record_id="co_12345",
            ),
        )

        report = await verification.verify_list(
            session, list_id=uuid.uuid4(), service_id=session.service.id, clients={"contactout": provider}
        )

        assert contact.email == "dana@northwind.example"
        assert contact.phone == "+15550100"
        assert contact.linkedin_url == "https://www.linkedin.com/in/danareyes"
        assert contact.title == "Head of Operations"
        assert report.with_phone == 1
        assert report.with_linkedin == 1

    async def test_the_number_carries_its_source_and_its_standing(self):
        contact = _Contact()
        session = self._session([contact])
        provider = FakeProvider(
            Provider.CONTACTOUT,
            ContactRecord(
                full_name="Dana Reyes",
                email="dana@northwind.example",
                phone="+15550100",
            ),
        )

        await verification.verify_list(
            session, list_id=uuid.uuid4(), service_id=session.service.id, clients={"contactout": provider}
        )

        assert contact.phone_provider == "contactout"
        # Unverified, and correctly so: nobody grades phone numbers the way
        # Apollo grades addresses, so a published number is a published number.
        assert contact.phone_status == "unverified"

    async def test_the_providers_own_id_is_kept_for_the_next_pass(self):
        """So a re-enrichment asks about this record rather than this name.

        Matching on a name again is how two people who share one at a company
        become one contact.
        """
        contact = _Contact()
        session = self._session([contact])
        provider = FakeProvider(
            Provider.CONTACTOUT,
            ContactRecord(
                full_name="Dana Reyes",
                email="dana@northwind.example",
                provider_record_id="co_12345",
            ),
        )

        await verification.verify_list(
            session, list_id=uuid.uuid4(), service_id=session.service.id, clients={"contactout": provider}
        )

        assert contact.email_provider_record_id == "co_12345"

    async def test_a_number_already_on_the_row_is_not_overwritten(self):
        """A rep who typed a direct line knows something the vendor does not."""
        contact = _Contact()
        contact.phone = "+15559999"
        session = self._session([contact])
        provider = FakeProvider(
            Provider.CONTACTOUT,
            ContactRecord(
                full_name="Dana Reyes",
                email="dana@northwind.example",
                phone="+15550100",
            ),
        )

        await verification.verify_list(
            session, list_id=uuid.uuid4(), service_id=session.service.id, clients={"contactout": provider}
        )

        assert contact.phone == "+15559999"


class TestThePassIsForOneService:
    """Who gets enriched is decided by the service, before any money moves.

    Without this the pass ran alphabetically over every unverified contact,
    which is how a budget goes on a junior developer while the CTO the service
    actually needed stays unreachable — and the list still reads as enriched.
    """

    def _session(self, contacts, personas=(), icp=None):
        # Personas go on the ICP — the service row no longer carries any.
        definition = dict(icp or {})
        if personas:
            definition["personas"] = list(personas)
        return _ConfigSession(
            order=["contactout"],
            credentials={"contactout": "valid"},
            contacts=contacts,
            service=_StubService(),
            icp=_StubIcp(definition=definition, version=4),
        )

    async def test_a_contact_the_service_does_not_want_is_never_asked_about(self):
        junior = _Contact(title="Junior Developer")
        session = self._session([junior], personas=["CTO"])
        provider = FakeProvider(Provider.CONTACTOUT, _record())

        report = await verification.verify_list(
            session,
            list_id=uuid.uuid4(),
            service_id=session.service.id,
            clients={"contactout": provider},
        )

        assert provider.calls == 0, "paid a provider for somebody nobody can pitch to"
        assert report.out_of_persona == 1
        assert report.checked == 0

    async def test_a_contact_the_service_wants_is_enriched(self):
        cto = _Contact(title="CTO")
        session = self._session([cto], personas=["CTO"])
        provider = FakeProvider(Provider.CONTACTOUT, _record())

        report = await verification.verify_list(
            session,
            list_id=uuid.uuid4(),
            service_id=session.service.id,
            clients={"contactout": provider},
        )

        assert provider.calls == 1
        assert report.verified == 1
        assert report.out_of_persona == 0

    async def test_a_contact_with_nothing_to_judge_on_is_held_not_dropped(self):
        """Their title was never imported. That is not a rejection, and it is
        not permission to spend either — it is a decision for a rep."""
        nameless = _Contact(title=None)
        session = self._session([nameless], personas=["CTO"])
        provider = FakeProvider(Provider.CONTACTOUT, _record())

        report = await verification.verify_list(
            session,
            list_id=uuid.uuid4(),
            service_id=session.service.id,
            clients={"contactout": provider},
        )

        assert provider.calls == 0
        assert report.unknown_persona == 1
        assert report.out_of_persona == 0, "an unknown title is not a mismatch"

    async def test_the_two_skipped_buckets_are_reported_apart(self):
        """They need different work: a better list, versus a better import."""
        session = self._session(
            [_Contact(title="CTO"), _Contact(title="Intern"), _Contact(title=None)],
            personas=["CTO"],
        )
        provider = FakeProvider(Provider.CONTACTOUT, _record())

        report = await verification.verify_list(
            session,
            list_id=uuid.uuid4(),
            service_id=session.service.id,
            clients={"contactout": provider},
        )

        assert (report.verified, report.out_of_persona, report.unknown_persona) == (1, 1, 1)
        assert provider.calls == 1

    async def test_every_skip_is_named_not_just_counted(self):
        session = self._session([_Contact(title="Intern")], personas=["CTO"])
        report = await verification.verify_list(
            session,
            list_id=uuid.uuid4(),
            service_id=session.service.id,
            clients={"contactout": FakeProvider(Provider.CONTACTOUT, _record())},
        )
        outcome = report.outcomes[0]
        assert outcome.outcome == "out_of_persona"
        assert "Intern" in outcome.detail

    async def test_the_run_records_the_service_and_icp_version(self):
        """So "why were these contacts enriched?" survives the ICP moving on.

        The profile *name* is recorded beside the version number, not just the
        number: "v4" alone is unreadable once a run can target more than one
        profile, and the number restarts per profile.
        """
        session = self._session([_Contact(title="CTO")], personas=["CTO"])
        report = await verification.verify_list(
            session,
            list_id=uuid.uuid4(),
            service_id=session.service.id,
            clients={"contactout": FakeProvider(Provider.CONTACTOUT, _record())},
        )
        assert report.service_code == "qa_engineering"
        assert report.icp_versions == [("Default", 4)]

    async def test_the_icp_can_name_targets_the_service_row_does_not(self):
        session = self._session(
            [_Contact(title="VP Engineering")],
            personas=(),
            icp={"target_personas": ["VP Engineering"]},
        )
        provider = FakeProvider(Provider.CONTACTOUT, _record())
        await verification.verify_list(
            session,
            list_id=uuid.uuid4(),
            service_id=session.service.id,
            clients={"contactout": provider},
        )
        assert provider.calls == 1

    async def test_an_icp_naming_nobody_is_refused_before_any_spend(self):
        """No personas used to mean "enrich everyone".

        Buyer personas live on the ICP now, and an ICP that names nobody has
        not said who is worth a credit. Refused, with the fix named, rather than
        paying to find whoever happens to be on the list.
        """
        session = self._session([_Contact(title="Anyone")], personas=())
        provider = FakeProvider(Provider.CONTACTOUT, _record())
        with pytest.raises(verification.NoServiceIcpError, match="no buyer personas"):
            await verification.verify_list(
                session,
                list_id=uuid.uuid4(),
                service_id=session.service.id,
                clients={"contactout": provider},
            )
        assert provider.calls == 0


class TestOnlyUnverifiedContactsAreAsked:
    def test_the_query_excludes_verified_contacts(self):
        """Re-checking one spends money to learn what is already on the row.

        Asserted on the statement because the filter is the whole point and a
        fake session cannot demonstrate a WHERE clause.
        """
        import inspect

        source = inspect.getsource(verification.unverified_contacts)
        assert '!= "verified"' in source
        # And scoped to the list, not the whole book.
        assert "AccountListMember.list_id == list_id" in source

    def test_email_alone_decides_whether_a_contact_is_sendable(self):
        """The gate is not the same list as what the waterfall chases.

        Phone can be added to `enrichment_config.required_fields` — and has
        been — so the waterfall keeps asking for a number. It must never become
        a condition of being reachable: every channel here sends to an address,
        and gating on phone would write off contacts whose only gap is a mobile
        nobody published.
        """
        assert verification.GATING_FIELDS == ("email",)


class TestImportedContactsAreEligible:
    """The join between the two halves.

    The importer marks a CSV contact `unverified`/`manual` precisely so this
    pass picks it up. If it marked them verified, the waterfall would skip
    them and the first thing to notice a wrong address would be a bounce.
    """

    def _verdict(self, row, provider=None):
        from app.services import csv_import

        mapping = csv_import.suggest_mapping(list(row.keys()))

        def cell(r, field):
            header = mapping.get(field)
            return (r.get(header) or "").strip() if header else None

        return csv_import._email_verdict(cell, row, provider)

    def test_the_importer_writes_the_state_this_pass_looks_for(self):
        """Asserted on the verdict rather than on the source text.

        This read `'email_status="unverified"' in inspect.getsource(...)` and
        broke the moment that literal became a variable — while the behaviour
        it cares about was unchanged. A test that fails on a refactor and
        passes on a regression is checking the wrong thing.
        """
        assert self._verdict({"Email": "a@x.test"}) == ("unverified", "manual")

    def test_a_spreadsheet_claiming_verified_is_still_unverified(self):
        """The substance: if the importer trusted the cell, the waterfall
        would skip the contact and a bounce would be the first thing to
        notice a wrong address."""
        assert self._verdict(
            {"Email": "a@x.test", "Email Status": "verified"}
        ) == ("unverified", "manual")

    def test_a_named_provider_is_the_one_exception(self):
        """Apollo's rows carry Apollo's own verdict, and that is carried
        rather than re-asserted — see `csv_import._email_verdict`."""
        assert self._verdict(
            {"Email": "a@x.test", "Email Status": "verified"}, provider="apollo"
        ) == ("verified", "apollo")


class _Account:
    def __init__(self, domain="meridiancloud.io", linkedin_url=None):
        self.id = uuid.uuid4()
        self.domain = domain
        self.linkedin_url = linkedin_url


class _Lazy:
    """Stands in for SQLAlchemy's `awaitable_attrs`."""

    def __init__(self, account):
        self._account = account

    @property
    def account(self):
        async def load():
            return self._account

        return load()


def _at(account, **contact):
    person = _Contact(**contact)
    person.awaitable_attrs = _Lazy(account)
    return person


class TestLinkedInIsKeptWithoutAnAddress:
    """A person Apollo recognised, with a profile and no usable email, used to
    come back "not found" with the profile thrown away."""

    async def test_the_profile_is_kept_when_no_address_is_found(self):
        contact = _Contact()
        record = ContactRecord(
            full_name="Dana Reyes", title="Head of Operations", email=None,
            email_status="unverified", linkedin_url="http://www.linkedin.com/in/danareyes",
        )
        outcome = await verification._verify_one(
            None, contact=contact, providers=[FakeProvider(Provider.APOLLO, record)]
        )
        assert outcome.outcome == "not_found"
        assert contact.linkedin_url == "http://www.linkedin.com/in/danareyes"
        assert outcome.linkedin_filled is True

    async def test_a_profile_already_held_is_not_replaced(self):
        contact = _Contact()
        contact.linkedin_url = "https://www.linkedin.com/in/dana-own"
        record = ContactRecord(full_name="Dana Reyes", linkedin_url="https://www.linkedin.com/in/other")
        outcome = await verification._verify_one(
            None, contact=contact, providers=[FakeProvider(Provider.APOLLO, record)]
        )
        assert contact.linkedin_url == "https://www.linkedin.com/in/dana-own"
        assert outcome.linkedin_filled is False


class TestTheCompanyPageFromTheProvider:
    def record(self, domain):
        return ContactRecord(
            full_name="Dana Reyes", linkedin_url="https://www.linkedin.com/in/danareyes",
            organization_domain=domain,
            organization_linkedin_url="http://www.linkedin.com/company/meridian-cloud",
        )

    async def test_taken_when_the_organisation_is_the_accounts_own(self):
        account = _Account()
        contact = _at(account)
        outcome = await verification._verify_one(
            None, contact=contact, providers=[FakeProvider(Provider.APOLLO, self.record("meridiancloud.io"))]
        )
        assert account.linkedin_url == "https://linkedin.com/company/meridian-cloud"
        assert outcome.company_linkedin == account.linkedin_url

    async def test_not_taken_from_another_organisation(self):
        """Matched at a former employer or a parent: their page is not this account's."""
        account = _Account()
        contact = _at(account)
        await verification._verify_one(
            None, contact=contact, providers=[FakeProvider(Provider.APOLLO, self.record("parentco.com"))]
        )
        assert account.linkedin_url is None


class _Pages:
    def __init__(self, pages, fail=()):
        self.pages, self.fail = pages, set(fail)

    async def get(self, url):
        class R:
            def __init__(self, code, text):
                self.status_code, self.text = code, text

        if url in self.fail:
            raise ConnectionError("timed out")
        return R(200, self.pages[url]) if url in self.pages else R(404, "")

    async def aclose(self):
        return None


class TestLinkedInFromTheCompanysOwnSite:
    SITE = {
        "https://meridiancloud.io/": '<a href="https://www.linkedin.com/company/meridian-cloud/">in</a>',
        "https://meridiancloud.io/leadership": (
            '<h3>Dana Reyes</h3><a title="LinkedIn" href="https://www.linkedin.com/in/dana-reyes-12ab/"></a>'
        ),
    }

    async def test_company_page_and_profile_are_filled(self):
        account = _Account()
        contact = _at(account)
        report = verification.VerificationReport()
        await verification.fill_linkedin_from_sites([contact], report, http=_Pages(self.SITE))
        assert account.linkedin_url == "https://linkedin.com/company/meridian-cloud"
        assert contact.linkedin_url == "https://www.linkedin.com/in/dana-reyes-12ab"
        assert (report.company_linkedin_from_site, report.contact_linkedin_from_site) == (1, 1)

    async def test_what_is_held_is_left_alone(self):
        account = _Account(linkedin_url="https://linkedin.com/company/on-record")
        contact = _at(account)
        contact.linkedin_url = "https://www.linkedin.com/in/on-record"
        report = verification.VerificationReport()
        await verification.fill_linkedin_from_sites([contact], report, http=_Pages(self.SITE))
        assert account.linkedin_url == "https://linkedin.com/company/on-record"
        assert contact.linkedin_url == "https://www.linkedin.com/in/on-record"

    async def test_a_site_that_does_not_answer_is_noted(self):
        account = _Account(domain="gone.example")
        report = verification.VerificationReport()
        await verification.fill_linkedin_from_sites(
            [_at(account)], report, http=_Pages({}, fail={"https://gone.example/robots.txt"})
        )
        assert report.linkedin_notes == ["gone.example did not answer — no LinkedIn links read"]


class TestApolloIsGivenTheCompanyDomain:
    """Enrichment read the contact's account through `awaitable_attrs`, which
    these models do not have, so the account was always None, the domain was
    never sent, and Apollo — correctly refusing a bare name — was never asked
    about any contact without a LinkedIn URL."""

    class _Recorder:
        name = Provider.APOLLO

        def __init__(self):
            self.asked = []

        async def enrich(self, *, full_name, company_domain, linkedin_url):
            self.asked.append((full_name, company_domain, linkedin_url))
            return None

    class _RealContact:
        """Like a mapped row: an `account_id`, and no `awaitable_attrs`."""

        def __init__(self, account_id):
            self.__dict__.update(vars(_Contact()))
            self.account_id = account_id

    class _Session:
        def __init__(self, account):
            self.account = account

        async def get(self, model, pk):
            return self.account if pk == self.account.id else None

    async def test_the_domain_reaches_the_provider(self):
        account = _Account(domain="meridiancloud.io")
        contact = self._RealContact(account.id)
        provider = self._Recorder()
        await verification._verify_one(self._Session(account), contact=contact, providers=[provider])
        assert provider.asked == [("Dana Reyes", "meridiancloud.io", None)]

    async def test_the_website_pass_finds_the_account_the_same_way(self):
        account = _Account(domain="meridiancloud.io")
        contact = self._RealContact(account.id)
        report = verification.VerificationReport()
        await verification.fill_linkedin_from_sites(
            [contact], report, session=self._Session(account),
            http=_Pages(TestLinkedInFromTheCompanysOwnSite.SITE),
        )
        assert account.linkedin_url == "https://linkedin.com/company/meridian-cloud"

