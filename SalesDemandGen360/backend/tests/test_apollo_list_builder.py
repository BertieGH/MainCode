"""Choosing people out of the Apollo contacts already owned.

Every title here is a real one from the live account. They are not decoration:
the pairing rule was wrong twice before measurement caught it, both times in a
way that looked right in a summary and wrong in the rows.
"""

from __future__ import annotations

from app.services import apollo_list_builder as alb


def row(name, title, company, domain="x.test", email="a@x.test", status="verified"):
    return {
        "id": f"id-{name}",
        "name": name,
        "title": title,
        "email": email,
        "email_status": status,
        "linkedin_url": f"https://linkedin.com/in/{name.lower().replace(' ', '-')}",
        "organization_name": company,
        "organization": {"primary_domain": domain, "linkedin_url": "https://x"},
    }


class TestOnePersonaPerPerson:
    def test_a_founder_who_is_also_a_cto_is_technical(self):
        """The bug that produced false pairs. Ranked on both ladders
        independently, "Co-founder & CTO" scored as an economic buyer, and a
        company with two co-founding CTOs came out as a matched pair."""
        assert alb.persona_of("Co-Founder & CTO")[0] == "technical buyer"
        assert alb.persona_of("Founder and Chief Technology Officer")[0] == "technical buyer"
        assert alb.persona_of("President and CTO, Founder")[0] == "technical buyer"

    def test_a_plain_founder_is_economic(self):
        assert alb.persona_of("Founder and CEO")[0] == "economic buyer"
        assert alb.persona_of("Co-Founder, Chief Executive Officer")[0] == "economic buyer"

    def test_an_unrecognised_title_gets_no_persona(self):
        """Apollo's title filter is coarse and lets these through. A person
        with no persona must not be dropped into a persona slot."""
        assert alb.persona_of("Head of Partnerships")[0] is None
        assert alb.persona_of(None)[0] is None

    def test_seniority_orders_within_a_persona(self):
        """A CEO outranks a VP; a CTO outranks an IT manager."""
        assert alb.persona_of("CEO")[1] < alb.persona_of("Vice President of Sales")[1]
        assert alb.persona_of("CTO")[1] < alb.persona_of("IT Manager")[1]


class TestAPairMeansTwoDifferentRoles:
    def test_two_co_founding_ctos_are_not_a_pair(self):
        """Measured: of 247 companies with two matching people in the under-50
        band, only 71 had one of each persona. This is the other 176."""
        out = alb.choose(
            [row("A", "Co-Founder & CTO", "Kortical"),
             row("B", "Co-founder, CEO & CTO", "Kortical")],
            per_company=2, limit=10,
        )
        assert out.chosen == []
        assert out.funnel.usable_companies == 0

    def test_a_ceo_and_a_cto_are_a_pair(self):
        out = alb.choose(
            [row("A", "Co-Founder & CEO", "Neurolabs"),
             row("B", "Co-Founder & CTO", "Neurolabs")],
            per_company=2, limit=10,
        )
        assert {c.persona for c in out.chosen} == {"economic buyer", "technical buyer"}
        assert out.funnel.usable_companies == 1

    def test_one_persona_asked_for_needs_only_that_one(self):
        out = alb.choose(
            [row("A", "Co-Founder & CEO", "Solo")],
            personas=("economic buyer",), per_company=1, limit=10,
        )
        assert len(out.chosen) == 1

    def test_the_most_senior_of_each_persona_wins(self):
        out = alb.choose(
            [row("Vp", "Vice President of Operations", "Acme"),
             row("Boss", "Chief Executive Officer", "Acme"),
             row("Cto", "Chief Technology Officer", "Acme")],
            per_company=2, limit=10,
        )
        assert {c.full_name for c in out.chosen} == {"Boss", "Cto"}


class TestHowManyPerCompany:
    def _acme(self):
        return [
            row("Boss", "Chief Executive Officer", "Acme"),
            row("Cto", "Chief Technology Officer", "Acme"),
            row("Vp", "Vice President of Operations", "Acme"),
            row("Cio", "Chief Information Officer", "Acme"),
        ]

    def test_one_per_company_still_needs_every_persona_present(self):
        """`per_company=1` with two personas asked for is a contradiction the
        caller can make. The company must still *have* both — what is stored is
        capped at one — because the alternative is a list silently missing the
        persona it was built for."""
        out = alb.choose(self._acme(), per_company=1, limit=10)
        assert len(out.chosen) == 1

    def test_three_per_company_fills_the_spare_slot_by_seniority(self):
        out = alb.choose(self._acme(), per_company=3, limit=10)
        assert len(out.chosen) == 3
        # The pair first, then the next most senior of whatever is left.
        assert {c.persona for c in out.chosen[:2]} == {"economic buyer", "technical buyer"}

    def test_a_company_cannot_give_more_than_it_has(self):
        out = alb.choose(
            [row("Boss", "CEO", "Tiny"), row("Cto", "CTO", "Tiny")],
            per_company=5, limit=10,
        )
        assert len(out.chosen) == 2


class TestTheLimit:
    def _many(self, n):
        rows = []
        for i in range(n):
            rows += [row(f"ceo{i}", "Chief Executive Officer", f"Co{i}", f"co{i}.test"),
                     row(f"cto{i}", "Chief Technology Officer", f"Co{i}", f"co{i}.test")]
        return rows

    def test_it_stops_at_the_limit(self):
        out = alb.choose(self._many(40), per_company=2, limit=50)
        assert len(out.chosen) == 50

    def test_a_company_is_never_half_taken(self):
        """Half a pair is the thing this is built to avoid, so the limit is
        reached by whole companies — 51 asked for, 50 given."""
        out = alb.choose(self._many(40), per_company=2, limit=51)
        assert len(out.chosen) == 50

    def test_the_note_says_so_when_the_filters_run_out(self):
        out = alb.choose(self._many(3), per_company=2, limit=100)
        assert "all the filters leave" in out.note
        assert out.funnel.available == 6

    def test_the_note_is_quiet_when_it_filled_the_order(self):
        out = alb.choose(self._many(40), per_company=2, limit=10)
        assert "all the filters leave" not in out.note


class TestWhatIsRefused:
    def test_a_contact_with_no_company_domain_is_skipped(self):
        """Without a domain there is no account to attach them to, and
        matching on company name alone is how two companies become one."""
        bad = row("A", "CEO", "Nameless", domain="")
        out = alb.choose([bad, row("B", "CTO", "Nameless", domain="")], limit=10)
        assert out.chosen == []

    def test_people_with_no_persona_do_not_make_a_company_usable(self):
        out = alb.choose(
            [row("A", "Head of Partnerships", "Acme"),
             row("B", "Head of Facilities", "Acme")],
            limit=10,
        )
        assert out.funnel.companies == 0


class TestTheNoteTellsTwoDifferentShortfallsApart:
    """"76 is all the filters leave" and "76 is all 1,300 contacts yielded,
    and there are 23,000 more" are different facts. Only one of them is a
    reason to widen the filters, and the first version said the first when it
    meant the second.
    """

    def _some(self, n):
        rows = []
        for i in range(n):
            rows += [row(f"ceo{i}", "Chief Executive Officer", f"Co{i}", f"co{i}.test"),
                     row(f"cto{i}", "Chief Technology Officer", f"Co{i}", f"co{i}.test")]
        return rows

    def test_filled_the_order(self):
        build = alb.choose(self._some(30), per_company=2, limit=20)
        assert alb._note(build, limit=20, per_company=2, exhausted=False) == (
            "20 contacts at 10 companies"
        )

    def test_apollo_had_no_more(self):
        build = alb.choose(self._some(3), per_company=2, limit=100)
        note = alb._note(build, limit=100, per_company=2, exhausted=True)
        assert "every company in these filters" in note

    def test_we_stopped_reading(self):
        """Not exhausted: there is more behind the page cap, so the advice is
        to narrow rather than to widen."""
        build = alb.choose(self._some(3), per_company=2, limit=100)
        note = alb._note(build, limit=100, per_company=2, exhausted=False)
        assert "contacts read" in note and "Narrowing" in note
