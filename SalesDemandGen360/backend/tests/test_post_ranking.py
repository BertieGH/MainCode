"""Which indexed LinkedIn posts are kept, and why.

Every snippet here is a real one from the book, abbreviated. The fixtures matter
more than usual: each was something the first version of this got wrong, and the
whole point of ranking before storing is that a mistake here is permanent —
evidence is immutable, so a post dropped is a post never cited, and a post kept
is an extraction input token for good.
"""

from __future__ import annotations

from datetime import date

from app.services import post_ranking as pr

TODAY = date(2026, 10, 8)
FIT = ("engineering", "intelligence", "quality", "enterprise", "services")
SIGNALS = ("leadership", "change", "executive", "partnership", "alliance", "launch")


def one(text: str, when: date | None = None):
    return pr.score([text], fit=FIT, signals=SIGNALS, dates=[when])[0]


class TestWhatCountsAsATerm:
    def test_an_inflection_counts(self):
        """"She **joined** Bollinger Innovations as its first…" is a real
        leadership hire that scored zero and was dropped.

        Matched here by the explicit `joined` entry rather than by prefixing
        `join`, which is four characters and so matched whole — the inflection
        rule only applies from five up, because prefixing `ai` would match
        "aid" and "air" and every post would score. Short irregulars earn
        their own entry; the assertion is on the outcome, not the route.
        """
        assert one("She joined Bollinger Innovations as its first CTO.").movement

    def test_a_noun_form_counts(self):
        assert one("They closed the KORE Power acquisition in September.").movement

    def test_a_short_term_is_not_a_prefix(self):
        """`ai` matching "maintain", "chair" and "available" made almost every
        post a technology post, which is the failure mode of a lexicon."""
        scored = one("We chair the available committee and maintain the air supply.")
        assert "ai" not in scored.technology

    def test_a_short_term_still_matches_itself(self):
        assert "ai" in one("We are rolling out AI across the plant.").technology

    def test_accents_fold(self):
        """One real author on this book is `deborah-belyea-née-bell`. A match
        must not depend on the keyboard someone used."""
        assert one("Our naïve ERP rollout, née migration, is done.").technology

    def test_an_event_word_the_first_version_missed(self):
        """"confirms Nasdaq delisting" and "axed a $1.25B battery plant" both
        scored nothing. A plant closure is as much a trigger as a launch."""
        assert one("Bollinger Innovations confirms Nasdaq delisting.").movement
        assert one("Kore Power axed a $1.25B Arizona battery plant.").movement


class TestBoilerplateGoesByShapeNotTopic:
    """The saving comes from here, and it is the safe half.

    A topic filter cannot tell a customer's fraud complaint from a leadership
    hire — measured, they score on the same terms. A shape filter cannot
    accidentally discard an event for being about an unexpected subject.
    """

    def test_linkedin_chrome_is_not_a_post(self):
        assert pr.is_boilerplate("KORE Power. 26,264 followers. 7mo. Report this post")

    def test_a_brand_list_is_not_a_post(self):
        assert pr.is_boilerplate(
            "ettitude Cozy Earth BAM Clothing Thought Clothing Free Fly Apparel"
        )

    def test_a_date_prefix_does_not_rescue_a_brand_list(self):
        """The first version also demanded at most one full stop, which every
        stored excerpt defeats: they open with "Sep 23, 2026 ..." — three full
        stops before the list begins."""
        assert pr.is_boilerplate(
            "Sep 23, 2026 ... ettitude Cozy Earth BAM Clothing Thought Clothing Free Fly"
        )

    def test_real_prose_naming_several_companies_survives(self):
        """The case the shape filter must not break: an announcement naming
        four partners is prose, and a connective word breaks the run."""
        assert not pr.is_boilerplate(
            "WeaveGrid, PG&E and GM Energy announced a bundle for EV drivers today."
        )

    def test_boilerplate_never_reaches_the_budget(self):
        scored = pr.score(
            ["KORE Power. 26,264 followers. Report this post",
             "They closed the KORE Power acquisition in September."],
            fit=FIT, signals=SIGNALS, dates=[TODAY, TODAY],
        )
        kept = pr.pick(scored, limit=6, today=TODAY)
        assert [k.index for k in kept] == [1]


class TestChoosingWhatToKeep:
    def _posts(self):
        return [
            ("We launched an AI-driven ERP migration across the enterprise.", TODAY),
            ("A quality engineering services partnership was announced.", TODAY),
            ("Lovely weather at the trade show this week.", TODAY),
            ("Our team went to the fishing tournament.", date(2026, 10, 1)),
        ]

    def test_the_scorers_come_first(self):
        posts = self._posts()
        scored = pr.score([t for t, _ in posts], fit=FIT, signals=SIGNALS,
                          dates=[d for _, d in posts])
        kept = pr.pick(scored, per_bucket=3, limit=2, today=TODAY)
        assert {k.index for k in kept} == {0, 1}

    def test_spare_budget_goes_to_the_most_recent_unscored(self):
        """The safety net. Dropping every non-scorer measured as an 82% saving
        and a real loss — "confirms Nasdaq delisting" scored zero. The cap
        decides the volume; the lexicon only decides the order."""
        posts = self._posts()
        scored = pr.score([t for t, _ in posts], fit=FIT, signals=SIGNALS,
                          dates=[d for _, d in posts])
        kept = pr.pick(scored, per_bucket=3, limit=4, today=TODAY)
        assert len(kept) == 4
        # The unscored pair arrives newest-first, behind both scorers.
        assert [k.index for k in kept[2:]] == [2, 3]

    def test_the_cap_holds(self):
        posts = [(f"We launched an AI platform number {n}.", TODAY) for n in range(20)]
        scored = pr.score([t for t, _ in posts], fit=FIT, signals=SIGNALS,
                          dates=[d for _, d in posts])
        assert len(pr.pick(scored, per_bucket=3, limit=6, today=TODAY)) == 6

    def test_both_axes_get_a_share(self):
        """Two threes rather than one six: a single ranking lets a long generic
        technology post outrank a short specific one."""
        posts = [
            ("AI cloud data platform analytics migration automation.", TODAY),
            ("AI cloud data platform analytics devops kubernetes.", TODAY),
            ("AI cloud data warehouse etl integration api.", TODAY),
            ("Our quality engineering services for the enterprise.", TODAY),
        ]
        scored = pr.score([t for t, _ in posts], fit=FIT, signals=SIGNALS,
                          dates=[d for _, d in posts])
        kept = pr.pick(scored, per_bucket=3, limit=4, today=TODAY)
        assert 3 in {k.index for k in kept}, "the fit-only post must still get a place"

    def test_the_window_excludes_an_old_post(self):
        posts = [("We launched an AI ERP migration.", date(2025, 1, 1))]
        scored = pr.score([t for t, _ in posts], fit=FIT, signals=SIGNALS,
                          dates=[d for _, d in posts])
        assert pr.pick(scored, window_days=90, today=TODAY) == []

    def test_an_undated_post_survives_the_window(self):
        """Undated is unknown, not old. 49 of 49 posts on this book decoded a
        date, so this is the parsing gap, and dropping it here would silently
        prefer posts whose activity id happened to parse."""
        scored = pr.score(["We launched an AI ERP migration."], fit=FIT,
                          signals=SIGNALS, dates=[None])
        assert len(pr.pick(scored, window_days=90, today=TODAY)) == 1


class TestTheFitLexiconComesFromConfig:
    def test_generic_words_are_refused(self):
        """The first run produced `that`, `based`, `without`, `team` and `build`
        as fit terms — each matches a large share of any prose, so the score
        would have ranked every post alike and looked like it was working."""
        terms = pr.fit_terms(["Build better services faster, without the cliff"])
        assert "that" not in terms and "without" not in terms and "build" not in terms

    def test_the_distinctive_words_survive(self):
        terms = pr.fit_terms(["Enterprise Intelligence Amplification"])
        assert {"enterprise", "intelligence", "amplification"} <= set(terms)

    def test_short_words_go(self):
        assert "qa" not in pr.fit_terms(["QA engineering"])


class TestTheNoteExplainsItself:
    def test_it_says_how_many_were_seen_and_kept(self):
        scored = pr.score(["We launched an AI ERP migration."], fit=FIT,
                          signals=SIGNALS, dates=[TODAY])
        kept = pr.pick(scored, today=TODAY)
        note = pr.note(10, kept)
        assert "10 post(s) seen" in note and "1 kept" in note

    def test_it_says_when_a_post_is_in_on_recency_alone(self):
        """A reader has to be able to tell "this matched" from "there was room"."""
        scored = pr.score(["Lovely weather at the trade show."], fit=FIT,
                          signals=SIGNALS, dates=[TODAY])
        note = pr.note(4, pr.pick(scored, today=TODAY))
        assert "recency alone" in note

    def test_nothing_seen_is_not_nothing_kept(self):
        assert pr.note(0, []) == "no posts indexed"
        assert "boilerplate" in pr.note(5, [])
