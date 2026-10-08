"""LinkedIn URLs, understood without being fetched. No network, no database."""

from __future__ import annotations

from datetime import date

import pytest

from app.services import linkedin

#: A real post URL from a public search result — Proxycurl's shutdown notice,
#: which went out in July 2025.
PROXYCURL_POST = (
    "https://www.linkedin.com/posts/maxkolysh_proxycurl-just-shut-down-after-linkedin-sued-"
    "activity-7351297064502206466-W_4c"
)


class TestPostDates:
    def test_the_date_is_written_into_the_url(self):
        assert linkedin.post_date(PROXYCURL_POST) == date(2025, 7, 16)

    def test_the_urn_form_reads_the_same(self):
        url = "https://www.linkedin.com/feed/update/urn:li:activity:7351297064502206466/"
        assert linkedin.post_date(url) == date(2025, 7, 16)

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.linkedin.com/company/bluewave-technology-group/",
            "https://www.linkedin.com/in/danareid",
            "https://example.com/posts/x-activity-7351297064502206466-ab",
            None,
        ],
    )
    def test_no_activity_id_or_not_linkedin_is_no_date(self, url):
        assert linkedin.post_date(url) is None

    def test_a_number_that_decodes_to_the_future_is_not_a_date(self):
        url = "https://www.linkedin.com/posts/x_y-activity-9223372036854775807-ab"
        assert linkedin.post_date(url, today=date(2026, 9, 13)) is None


class TestWhoAUrlBelongsTo:
    COMPANY = "https://linkedin.com/company/bluewave-technology-group"
    PERSON = "https://www.linkedin.com/in/danareid"

    def test_slugs(self):
        assert linkedin.company_slug(self.COMPANY + "/about/") == "bluewave-technology-group"
        assert linkedin.person_slug(self.PERSON + "/") == "danareid"
        assert linkedin.post_author(
            "https://www.linkedin.com/posts/bluewave-technology-group_ai-activity-7351297064502206466-x"
        ) == "bluewave-technology-group"

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://www.linkedin.com/company/bluewave-technology-group/", True),
            ("https://www.linkedin.com/company/blue-wave-surf-shop/", False),
            ("https://www.linkedin.com/posts/bluewave-technology-group_x-activity-1-a", True),
            ("https://www.linkedin.com/posts/someone-else_x-activity-1-a", False),
            ("https://www.linkedin.com/in/danareid", True),
            ("https://www.linkedin.com/in/dana-reid-namesake", False),
            ("https://www.linkedin.com/pulse/ai-networks-dana-reid", None),
            ("https://bluewave.net/news", None),
        ],
    )
    def test_belongs(self, url, expected):
        assert linkedin.belongs(url, company_url=self.COMPANY, person_url=self.PERSON) is expected

    def test_the_public_id_suffix_is_not_a_different_person(self):
        """One person, two spellings, and providers disagree about which.

        Apollo stored `/in/apoorv-bhargava-94100842`; his own post is at
        `/posts/apoorv-bhargava_…`. Compared exactly those are two people, and
        the first measurement of post authorship duly reported **zero**
        employees among forty-five authors — a number produced entirely by this
        mismatch, not by the data.
        """
        apollo = "https://www.linkedin.com/in/apoorv-bhargava-94100842"
        post = "https://www.linkedin.com/posts/apoorv-bhargava_speedtopower-activity-751-0IYT"
        assert linkedin.belongs(post, person_url=apollo) is True
        # And the other way round, since either side may carry the suffix.
        assert linkedin.same_slug("apoorv-bhargava", "apoorv-bhargava-94100842")

    def test_a_different_person_is_still_a_mismatch(self):
        """The suffix strip must not merge everybody with a similar name."""
        assert linkedin.belongs(
            "https://www.linkedin.com/posts/jane-doe_x-activity-1-a",
            person_url="https://www.linkedin.com/in/john-smith-12345678",
        ) is False
        assert not linkedin.same_slug("john-smith", "john-smithson")

    def test_a_short_tail_is_not_a_public_id(self):
        """Only a real disambiguator comes off. `dana-reid-ab` is a name, and
        treating a two-character tail as an id would merge genuine namesakes."""
        assert not linkedin.same_slug("dana-reid", "dana-reid-ab")

    def test_nothing_on_record_is_not_a_mismatch(self):
        """Without a stored page there is nothing to compare with — keep, not drop."""
        assert linkedin.belongs("https://www.linkedin.com/company/anyone/") is None


class TestCompanyPagesOnAHomepage:
    def test_a_footer_link_is_found_and_normalised(self):
        page = '<footer><a href="https://www.linkedin.com/company/bluewave-technology-group/?trk=x">in</a></footer>'
        assert linkedin.company_pages(page) == ["https://linkedin.com/company/bluewave-technology-group"]

    def test_the_same_page_linked_twice_is_one(self):
        page = (
            '<a href="https://www.linkedin.com/company/acme">a</a>'
            '<a href="https://linkedin.com/company/acme/">b</a>'
        )
        assert linkedin.company_pages(page) == ["https://linkedin.com/company/acme"]

    def test_two_different_pages_are_both_returned(self):
        """The caller decides; a site linking two company pages is ambiguous."""
        page = (
            '<a href="https://www.linkedin.com/company/acme">a</a>'
            '<a href="https://www.linkedin.com/company/acme-labs">b</a>'
        )
        assert len(linkedin.company_pages(page)) == 2

    def test_a_person_profile_is_not_a_company_page(self):
        assert linkedin.company_pages('<a href="https://www.linkedin.com/in/ceo">CEO</a>') == []


class TestWhereTheDateLands:
    """Through `store_found`, not `_to_row`.

    The derivation moved up to the caller when the staleness gate landed: the
    gate has to test the same date the row ends up carrying, and deriving it in
    both places would let a passage be admitted on one reading of its date and
    stored under another. These tests follow it, because asserting against
    `_to_row` would now pass while the real path did nothing.
    """

    async def test_a_stored_linkedin_passage_is_dated_from_its_url(self):
        import uuid

        from app.schemas.evidence import EvidenceBatch, FoundEvidence
        from app.services.evidence import store_found
        from tests.test_evidence_dedup import FakeSession

        session = FakeSession()
        outcome = await store_found(
            session,
            account_id=uuid.uuid4(),
            batch=EvidenceBatch(evidence=[
                FoundEvidence(
                    source_type="linkedin", source_url=PROXYCURL_POST,
                    excerpt="Proxycurl just shut down after LinkedIn sued.",
                )
            ]),
        )
        assert outcome.stored[0].observed_at == date(2025, 7, 16)

    async def test_a_date_the_source_gave_is_not_overridden(self):
        import uuid

        from app.schemas.evidence import EvidenceBatch, FoundEvidence
        from app.services.evidence import store_found
        from tests.test_evidence_dedup import FakeSession

        session = FakeSession()
        outcome = await store_found(
            session,
            account_id=uuid.uuid4(),
            batch=EvidenceBatch(evidence=[
                FoundEvidence(
                    source_type="linkedin", source_url=PROXYCURL_POST, excerpt="x",
                    observed_at=date(2025, 7, 1),
                )
            ]),
        )
        assert outcome.stored[0].observed_at == date(2025, 7, 1)


class TestAPassageFromSomeoneElsesPage:
    COMPANY = "https://linkedin.com/company/bluewave-technology-group"

    def batch(self, *urls):
        from app.schemas.evidence import EvidenceBatch, FoundEvidence

        return EvidenceBatch(
            evidence=[FoundEvidence(source_type="linkedin", source_url=u, excerpt=f"from {u}") for u in urls]
        )

    def test_a_namesakes_page_is_dropped_and_said(self):
        from app.services.pipeline import keep_own_linkedin

        kept, dropped = keep_own_linkedin(
            self.batch(
                "https://www.linkedin.com/company/bluewave-technology-group/",
                "https://www.linkedin.com/company/blue-wave-surf-shop/",
                "https://bluewave.net/news",
            ),
            company_url=self.COMPANY,
        )
        assert dropped == 1
        assert [e.source_url for e in kept.evidence] == [
            "https://www.linkedin.com/company/bluewave-technology-group/",
            "https://bluewave.net/news",
        ]
        assert "different company page or person" in kept.not_found[-1]

    def test_with_no_page_on_record_nothing_is_dropped(self):
        from app.services.pipeline import keep_own_linkedin

        batch = self.batch("https://www.linkedin.com/company/anyone/")
        kept, dropped = keep_own_linkedin(batch, company_url=None)
        assert dropped == 0
        assert kept is batch
