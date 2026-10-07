"""Importing a file that has one row per *person*.

A sales list arrives as five rows for one company as often as it arrives as one
row per company, and until now the importer only understood the second shape.
The failure was the quiet kind: rows 2-5 matched row 1's domain, came back as
`duplicate_in_file`, and the report read "1 created, 4 duplicates" — which
looks like success while four people are discarded.

The sharper bug was in the same place. `linkedin` was aliased onto the
*account*, so importing a contact export stamped a person's profile URL onto
the company record, on every row, with nothing on screen to show it.
"""

from __future__ import annotations

import pytest

from app.services.csv_import import (
    ACCOUNT_ALIASES,
    CONTACT_ALIASES,
    classify_linkedin,
    detect_grain,
    suggest_mapping,
)


class TestLinkedInGoesWhereItBelongs:
    """Routed by the URL, because the column header is the thing that lies."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.linkedin.com/company/northwind",
            "http://linkedin.com/company/northwind/",
            "https://www.linkedin.com/showcase/northwind-eng",
        ],
    )
    def test_a_company_url_is_a_company(self, url):
        assert classify_linkedin(url) == "company"

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.linkedin.com/in/dana-reyes",
            "https://linkedin.com/in/dana-reyes/",
            "https://www.linkedin.com/pub/dana-reyes/1/2/3",
        ],
    )
    def test_a_person_url_is_a_person(self, url):
        assert classify_linkedin(url) == "person"

    @pytest.mark.parametrize("url", [None, "", "https://northwind.example", "not a url"])
    def test_anything_else_is_neither(self, url):
        assert classify_linkedin(url) is None

    def test_a_person_url_never_reaches_the_account(self):
        from app.services.csv_import import _company_linkedin

        # The bug this test exists for: on a contact export every row carried
        # a person's profile into the company record.
        assert _company_linkedin("https://linkedin.com/in/dana-reyes") is None
        assert (
            _company_linkedin("https://linkedin.com/company/northwind")
            == "https://linkedin.com/company/northwind"
        )

    def test_a_company_url_never_reaches_the_contact(self):
        from app.services.csv_import import _person_linkedin

        assert _person_linkedin("https://linkedin.com/company/northwind") is None

    def test_a_bare_linkedin_column_is_claimed_by_the_contact(self):
        """It was claimed by the account, which is how the bug happened."""
        assert "linkedin" not in ACCOUNT_ALIASES["linkedin_url"]
        assert "linkedin" in CONTACT_ALIASES["contact_linkedin_url"]


class TestDetectingTheGrain:
    """Detected, not declared. Asking somebody to state it is asking them to
    get it right, and getting it wrong discards people silently."""

    def _rows(self, *dicts):
        return [dict(d) for d in dicts]

    def test_a_company_file_is_account_grain(self):
        rows = self._rows(
            {"Company": "Northwind", "Website": "northwind.example"},
            {"Company": "Contoso", "Website": "contoso.example"},
        )
        mapping = suggest_mapping(["Company", "Website"])
        assert detect_grain(rows, mapping) == "account"

    def test_a_file_with_emails_is_contact_grain(self):
        headers = ["Company", "Website", "First Name", "Last Name", "Email", "Title"]
        rows = self._rows(
            {
                "Company": "Northwind", "Website": "northwind.example",
                "First Name": "Dana", "Last Name": "Reyes",
                "Email": "dana@northwind.example", "Title": "VP Engineering",
            }
        )
        assert detect_grain(rows, suggest_mapping(headers)) == "contact"

    def test_an_empty_person_column_does_not_make_it_a_contact_file(self):
        """A company export can carry an empty `title` column.

        Mapping alone is not evidence — the column has to be populated, or a
        perfectly ordinary account list gets read as a list of nobody.
        """
        headers = ["Company", "Website", "Title"]
        rows = self._rows({"Company": "Northwind", "Website": "northwind.example", "Title": ""})
        assert detect_grain(rows, suggest_mapping(headers)) == "account"


class TestMappingAContactExport:
    HEADERS = [
        "Company", "Website", "First Name", "Last Name",
        "Title", "Email", "LinkedIn", "Industry",
    ]

    def test_the_company_columns_still_map(self):
        mapping = suggest_mapping(self.HEADERS)
        assert mapping["name"] == "Company"
        assert mapping["domain"] == "Website"
        assert mapping["industry"] == "Industry"

    def test_the_person_columns_map_too(self):
        mapping = suggest_mapping(self.HEADERS)
        assert mapping["first_name"] == "First Name"
        assert mapping["last_name"] == "Last Name"
        assert mapping["email"] == "Email"
        assert mapping["title"] == "Title"

    def test_linkedin_maps_to_the_contact_not_the_account(self):
        mapping = suggest_mapping(self.HEADERS)
        assert mapping["contact_linkedin_url"] == "LinkedIn"
        assert mapping["linkedin_url"] is None

    def test_an_explicit_company_linkedin_still_reaches_the_account(self):
        mapping = suggest_mapping([*self.HEADERS, "Company LinkedIn"])
        assert mapping["linkedin_url"] == "Company LinkedIn"
        assert mapping["contact_linkedin_url"] == "LinkedIn"

    def test_name_goes_to_the_person_when_the_file_is_about_people(self):
        """`Name` is claimed by both, and on a person file it is the person.

        Reading it as the company puts a person's name in the account record —
        the same class of mistake as the LinkedIn one.
        """
        mapping = suggest_mapping(["Name", "Email", "Company Name", "Website"])
        assert mapping["full_name"] == "Name"
        assert mapping["name"] == "Company Name"

    def test_a_company_file_maps_no_person_columns_at_all(self):
        mapping = suggest_mapping(["Name", "Website", "Industry"])
        assert mapping["name"] == "Name"
        assert all(mapping[f] is None for f in CONTACT_ALIASES)


class TestBuildingAPersonsName:
    def _cell(self, row):
        def cell(r, field):
            return (r.get(field) or "").strip() or None

        return lambda r, f: cell(r, f)

    def test_split_names_are_joined(self):
        from app.services.csv_import import _full_name

        row = {"first_name": "Dana", "last_name": "Reyes"}
        assert _full_name(self._cell(row), row) == "Dana Reyes"

    def test_a_whole_name_is_preferred(self):
        from app.services.csv_import import _full_name

        row = {"full_name": "Dana Reyes", "first_name": "D"}
        assert _full_name(self._cell(row), row) == "Dana Reyes"

    def test_a_first_name_alone_is_still_a_name(self):
        from app.services.csv_import import _full_name

        row = {"first_name": "Dana"}
        assert _full_name(self._cell(row), row) == "Dana"

    def test_no_name_at_all_is_none(self):
        from app.services.csv_import import _full_name

        assert _full_name(self._cell({}), {}) is None


@pytest.mark.db
@pytest.mark.skipif(
    not __import__("os").getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — this writes real accounts and contacts",
)
class TestFiveContactsForOneCompany:
    """The shape that used to report success while discarding four people."""

    HEADERS = ["Company", "Website", "First Name", "Last Name", "Title", "Email", "LinkedIn"]

    def _rows(self):
        people = [
            ("Dana", "Reyes", "VP Engineering", "dana@northwind.example"),
            ("Marcus", "Hale", "CTO", "marcus@northwind.example"),
            ("Priya", "Nair", "Head of QA", "priya@northwind.example"),
            ("Sam", "Okafor", "Director of Platform", "sam@northwind.example"),
            ("Lee", "Chen", "Engineering Manager", "lee@northwind.example"),
        ]
        return [
            {
                "Company": "Northwind",
                "Website": "https://www.northwind.example/careers",
                "First Name": first,
                "Last Name": last,
                "Title": title,
                "Email": email,
                "LinkedIn": f"https://linkedin.com/in/{first.lower()}-{last.lower()}",
            }
            for first, last, title, email in people
        ]

    async def _run(self, session, list_id, rows, dry_run=False):
        from app.services.csv_import import run_import, suggest_mapping

        return await run_import(
            session,
            list_id=list_id,
            rows=rows,
            mapping=suggest_mapping(self.HEADERS),
            added_by="tests",
            dry_run=dry_run,
        )

    @pytest.fixture
    async def session_and_list(self):
        import os
        import uuid as _uuid

        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.models.account import AccountList

        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            row = AccountList(
                label=f"contacts-{_uuid.uuid4().hex[:6]}", source="csv", created_by="tests"
            )
            session.add(row)
            await session.flush()
            yield session, row.id
            await session.rollback()
        await engine.dispose()

    async def test_one_company_and_five_contacts(self, session_and_list):
        session, list_id = session_and_list
        report = await self._run(session, list_id, self._rows())

        assert report.grain == "contact"
        assert report.accounts_touched == 1, "the company should be resolved once"
        assert report.contacts_created == 5
        # The old behaviour: four of these were `duplicate_in_file`.
        assert "duplicate_in_file" not in report.counts

    async def test_the_company_record_gets_no_personal_profile(self, session_and_list):
        """The corruption this fixes.

        Every row carries `linkedin.com/in/<person>`; none of it belongs on the
        company.
        """
        from sqlalchemy import func, select

        from app.models.account import Account

        session, list_id = session_and_list
        await self._run(session, list_id, self._rows())

        account = (
            await session.execute(
                select(Account).where(func.lower(Account.domain) == "northwind.example")
            )
        ).scalar_one()
        assert account.linkedin_url is None

    async def test_each_contact_keeps_their_own_profile(self, session_and_list):
        from sqlalchemy import select

        from app.models.account import Contact

        session, list_id = session_and_list
        await self._run(session, list_id, self._rows())

        contacts = list(
            (await session.execute(select(Contact))).scalars()
        )
        assert len(contacts) == 5
        dana = next(c for c in contacts if c.full_name == "Dana Reyes")
        assert dana.linkedin_url == "https://linkedin.com/in/dana-reyes"
        assert dana.title == "VP Engineering"

    async def test_imported_contacts_are_marked_unverified_and_manual(
        self, session_and_list
    ):
        """They must not look like provider output.

        The waterfall skips a contact that already has a verified email, so
        mislabelling one here means a wrong address is never checked and the
        first thing that notices is a bounce.
        """
        from sqlalchemy import select

        from app.models.account import Contact

        session, list_id = session_and_list
        await self._run(session, list_id, self._rows())

        for contact in (await session.execute(select(Contact))).scalars():
            assert contact.email_status == "unverified"
            assert contact.email_provider == "manual"

    async def test_re_importing_fills_gaps_without_duplicating(self, session_and_list):
        from sqlalchemy import select

        from app.models.account import Contact

        session, list_id = session_and_list
        first_pass = [dict(r) for r in self._rows()]
        for row in first_pass:
            row["Title"] = ""
        await self._run(session, list_id, first_pass)

        again = await self._run(session, list_id, self._rows())
        assert again.contacts_created == 0
        assert again.contacts_updated == 5

        contacts = list((await session.execute(select(Contact))).scalars())
        assert len(contacts) == 5
        assert all(c.title for c in contacts)

    async def test_a_dry_run_writes_nothing(self, session_and_list):
        from sqlalchemy import func, select

        from app.models.account import Contact

        session, list_id = session_and_list
        report = await self._run(session, list_id, self._rows(), dry_run=True)

        assert report.grain == "contact"
        assert report.contacts_created == 5
        # The preview has to be trustworthy without being a write.
        assert (
            await session.execute(select(func.count()).select_from(Contact))
        ).scalar_one() == 0

    async def test_a_row_with_no_person_is_reported_not_silently_dropped(
        self, session_and_list
    ):
        session, list_id = session_and_list
        rows = self._rows()
        rows.append(
            {
                "Company": "Northwind",
                "Website": "northwind.example",
                "First Name": "", "Last Name": "", "Title": "", "Email": "", "LinkedIn": "",
            }
        )
        report = await self._run(session, list_id, rows)
        assert report.counts.get("skipped_no_contact") == 1


class TestAnApolloAccountExportImportsWholly:
    """A real Apollo export, under the names Apollo actually uses.

    Matching is exact on the lowered header, and three of Apollo's names were
    in no alias list: `# Employees`, `Company Country`, `Company State`. So a
    57-account export imported with **no headcount at all**, no country and no
    region — in silence. Resolution then paid Apollo per account for numbers
    that were already in the file, recovering eight of fifty-seven.

    Silent is what made it expensive. A dropped headcount reads downstream as a
    company nobody could size, which is indistinguishable from one Apollo has
    never heard of — `sizing.band_for` refuses to guess, by design — so the
    book scored on base weights and looked like a data desert rather than a
    mapping miss.
    """

    HEADERS = [
        "Company Name", "Company Name for Emails", "Account Stage", "Lists",
        "# Employees", "Industry", "Account Owner", "Website",
        "Company Linkedin Url", "Company City", "Company State",
        "Company Country", "Technologies", "Total Funding", "Latest Funding",
        "Annual Revenue", "Founded Year",
    ]

    def test_every_account_field_the_export_carries_is_mapped(self):
        mapping = suggest_mapping(self.HEADERS)
        assert mapping["name"] == "Company Name"
        assert mapping["domain"] == "Website"
        assert mapping["industry"] == "Industry"
        assert mapping["employee_count"] == "# Employees"
        assert mapping["hq_country"] == "Company Country"
        assert mapping["hq_region"] == "Company State"
        assert mapping["linkedin_url"] == "Company Linkedin Url"

    def test_it_is_still_read_as_a_company_file(self):
        """No person columns, so the grain must not flip. `Company Name for
        Emails` is the kind of header that looks person-shaped and is not."""
        mapping = suggest_mapping(self.HEADERS)
        assert mapping.get("email") is None
        assert mapping.get("first_name") is None
        # The company LinkedIn column must stay on the account, never the
        # person — the bug this module already guards against.
        assert mapping["linkedin_url"] == "Company Linkedin Url"

    def test_the_headcount_column_is_claimed_by_nothing_else(self):
        mapping = suggest_mapping(self.HEADERS)
        claimed = [f for f, col in mapping.items() if col == "# Employees"]
        assert claimed == ["employee_count"], claimed


class TestAnApolloContactExportImportsWholly:
    """The contact-grain twin of the account export, and it had a worse bug.

    An Apollo contacts export carries **both** `Country` (the person's) and
    `Company Country`. `suggest_mapping` takes the *first* alias that matches,
    the bare name came first, and so importing one stamped the contact's own
    location onto the company record — on every row, silently. That is the same
    shape as the `linkedin` bug this module already guards, and the reason
    company-qualified names now sort first.

    Two fields were simply absent: `Person Linkedin Url`, which is what
    `linkedin_index` queries per person, and the work phone.
    """

    HEADERS = [
        "First Name", "Last Name", "Title", "Company", "Email", "Email Status",
        "Seniority", "Work Direct Phone", "Mobile Phone", "Corporate Phone",
        "# Employees", "Industry", "Person Linkedin Url", "Website",
        "Company Linkedin Url", "City", "State", "Country",
        "Company City", "Company State", "Company Country", "Annual Revenue",
    ]

    def test_the_company_columns_win_over_the_persons(self):
        mapping = suggest_mapping(self.HEADERS)
        assert mapping["hq_country"] == "Company Country", "not the person's Country"
        assert mapping["hq_region"] == "Company State", "not the person's State"

    def test_the_persons_profile_url_is_mapped_to_the_person(self):
        mapping = suggest_mapping(self.HEADERS)
        assert mapping["contact_linkedin_url"] == "Person Linkedin Url"
        assert mapping["linkedin_url"] == "Company Linkedin Url"

    def test_a_work_number_is_preferred_over_a_mobile(self):
        """A personal mobile is the wrong channel for cold B2B outreach, which
        is why `apollo_people` never asks for one either."""
        mapping = suggest_mapping(self.HEADERS)
        assert mapping["phone"] == "Work Direct Phone"

    def test_an_account_export_still_maps_its_own_country(self):
        """The reorder must not cost the account file, which has only the
        company-qualified names."""
        mapping = suggest_mapping(
            ["Company Name", "Website", "# Employees", "Company Country", "Company State"]
        )
        assert mapping["hq_country"] == "Company Country"
        assert mapping["hq_region"] == "Company State"

    def test_a_plain_file_still_maps_bare_names(self):
        """And neither must it cost a hand-made file that says `country`."""
        mapping = suggest_mapping(["name", "domain", "country", "state", "employees"])
        assert mapping["hq_country"] == "country"
        assert mapping["hq_region"] == "state"
        assert mapping["employee_count"] == "employees"
