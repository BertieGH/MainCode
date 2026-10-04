"""The shortlist a stage may be pointed at.

Two questions were being answered by one list. *What does the vendor offer* is
a fact about the vendor; *what is this installation willing to run* is a
commercial decision — a workspace entitled to the frontier model may still
choose to run extraction on the cheap one. Collapsing them put every model a
vendor sells into every dropdown, which is a standing invitation to point a
nightly batch at the most expensive thing available.

The load-bearing rule is the **in-use guard**. Removing a model an active stage
points at does not fail at save time; it fails at that stage's next real call,
mid-run, after research has been paid for, with an error naming a model rather
than the setting that removed it.
"""

from __future__ import annotations

import pytest

from app.services import availability


class _Session:
    """A database holding one availability row and some stage config."""

    def __init__(self, enabled=None, stages=()):
        self.enabled = enabled
        self.stages = list(stages)  # (provider, model, scenario)

    async def execute(self, stmt):
        rendered = str(stmt)
        outer = self

        class _Row:
            enabled = outer.enabled or {}

        class _R:
            def scalars(self):
                return self

            def __iter__(self):
                return iter([])

            def scalar_one_or_none(self):
                if "FROM model_availability" in rendered and outer.enabled is not None:
                    return _Row()
                return None

            def all(self):
                return list(outer.stages)

        return _R()


class TestResolvingTheShortlist:
    async def test_an_unset_provider_defaults_to_its_whole_catalogue(self):
        """A fresh install with an empty dropdown is a broken install.

        "We have not decided yet" is much closer to "all of them" than to
        "none of them".
        """
        state = await availability.resolve(_Session(enabled={}))
        gemini = state.for_provider("gemini")
        assert gemini.defaulted
        assert "gemini-3.8-flash" in gemini.enabled
        assert gemini.enabled == gemini.catalogue

    async def test_a_set_provider_is_narrowed_to_its_choice(self):
        state = await availability.resolve(
            _Session(enabled={"gemini": ["gemini-3.8-flash"]})
        )
        gemini = state.for_provider("gemini")
        assert not gemini.defaulted
        assert gemini.enabled == ["gemini-3.8-flash"]
        # The catalogue still reports everything, so the tick-list can show
        # what was turned off rather than hiding it.
        assert len(gemini.catalogue) > 1

    async def test_choosing_for_one_provider_does_not_narrow_another(self):
        state = await availability.resolve(
            _Session(enabled={"gemini": ["gemini-3.8-flash"]})
        )
        assert state.for_provider("anthropic").defaulted

    async def test_an_id_the_catalogue_does_not_know_is_kept_and_flagged(self):
        """Vendor ids drift — these were wrong in the catalogue once already."""
        state = await availability.resolve(
            _Session(enabled={"gemini": ["gemini-3.8-flash", "gemini-9-experimental"]})
        )
        gemini = state.for_provider("gemini")
        assert "gemini-9-experimental" in gemini.enabled
        assert gemini.custom == ["gemini-9-experimental"]

    async def test_a_provider_nobody_ships_still_gets_an_entry(self):
        state = await availability.resolve(
            _Session(enabled={"mistral": ["mistral-large-3"]})
        )
        entry = state.for_provider("mistral")
        assert entry.enabled == ["mistral-large-3"]
        assert entry.catalogue == []


class TestWhatAStageMayBePointedAt:
    async def test_a_shortlisted_model_is_allowed(self):
        state = await availability.resolve(
            _Session(enabled={"gemini": ["gemini-3.8-flash"]})
        )
        assert state.allows("gemini", "gemini-3.8-flash")

    async def test_a_real_model_that_is_not_shortlisted_is_not(self):
        """The dropdown and the save must agree.

        Offering a model that saving then rejects is a screen arguing with its
        own server.
        """
        state = await availability.resolve(
            _Session(enabled={"gemini": ["gemini-3.8-flash"]})
        )
        assert not state.allows("gemini", "gemini-3.1-pro-preview")

    async def test_an_added_provider_allows_anything(self):
        """We have no list to check against, and refusing would make a
        provider somebody added permanently unusable."""
        state = await availability.resolve(_Session(enabled={}))
        assert state.allows("mistral", "whatever-they-typed")


class TestTheInUseGuard:
    def _stages(self):
        return [
            ("anthropic", "claude-opus-5", "outreach_drafting"),
            ("anthropic", "claude-opus-5", "strategy_synthesis"),
            ("gemini", "gemini-3.8-flash", "pre_send_revalidation"),
        ]

    async def test_models_in_use_are_grouped_by_model(self):
        used = await availability.models_in_use(_Session(stages=self._stages()))
        opus = next(u for u in used if u.model == "claude-opus-5")
        assert opus.scenarios == ("outreach_drafting", "strategy_synthesis")

    async def test_removing_a_model_a_stage_uses_is_refused(self):
        session = _Session(stages=self._stages())
        with pytest.raises(availability.ModelInUseError) as exc:
            await availability.assert_no_stage_is_stranded(
                session, {"anthropic": ["claude-sonnet-5"]}
            )
        # Naming the stages is the point: "in use" alone leaves somebody
        # hunting through twelve rows.
        assert "outreach_drafting" in str(exc.value)
        assert exc.value.stranded[0].model == "claude-opus-5"

    async def test_keeping_it_and_adding_others_is_allowed(self):
        session = _Session(stages=self._stages())
        await availability.assert_no_stage_is_stranded(
            session,
            {
                "anthropic": ["claude-opus-5", "claude-sonnet-5"],
                "gemini": ["gemini-3.8-flash"],
            },
        )

    async def test_a_provider_left_out_entirely_is_not_treated_as_a_removal(self):
        """Absent means "no choice", which resolves to the whole catalogue.

        Reading it as "nothing allowed" would make every partial save strand
        every stage on every other provider.
        """
        session = _Session(stages=self._stages())
        await availability.assert_no_stage_is_stranded(
            session, {"gemini": ["gemini-3.8-flash"]}
        )

    async def test_an_unused_model_can_be_removed_freely(self):
        session = _Session(stages=self._stages())
        await availability.assert_no_stage_is_stranded(
            session,
            {
                "anthropic": ["claude-opus-5"],
                "gemini": ["gemini-3.8-flash"],
                "openai": ["gpt-5.2"],
            },
        )
