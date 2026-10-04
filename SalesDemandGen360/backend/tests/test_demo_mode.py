"""Demo mode, and the property that makes it safe to ship.

The obvious implementation of "unlock the app for a client walkthrough" is to
write fake credentials with `status='valid'`. That is the one to avoid: the
column means "a live round-trip succeeded", the setup gate is built entirely on
trusting it, and faking it once to open a menu makes it worthless everywhere —
including in production, where somebody will eventually debug a real outage by
reading it.

The dangerous version of the feature is worse than useless, though: a mode that
opens the gate while the code behind it still reaches for a real client. That
demo quietly bills an API, or sends a real message to a real prospect. So the
property under test here is not "demo mode works" — it is **demo mode cannot
reach the network**, checked at each seam before a client is constructed.
"""

from __future__ import annotations

import pytest

from app.services import demo, readiness


class _Session:
    """A database holding one mode row and nothing else."""

    def __init__(self, mode: str = "production", demo_runs: int = 0, creds=()):
        self.mode = mode
        self.demo_runs = demo_runs
        self.creds = list(creds)

    async def execute(self, stmt):
        rendered = str(stmt)
        outer = self

        class _R:
            def scalars(self):
                return self

            def __iter__(self):
                return iter(outer.creds if "FROM integration_credential" in rendered else [])

            def all(self):
                # Column-selecting queries (the ICP profile join in
                # `stages._active_icps`) never pass through `scalars()`.
                # Nothing here supplies ICPs, and a demo run should not have
                # any: the point of these tests is that egress is blocked
                # before a prompt is ever assembled.
                return []

            def scalar_one_or_none(self):
                if "FROM installation_mode" in rendered:
                    return outer.mode
                return None

            def scalar_one(self):
                return outer.demo_runs

        return _R()


class TestTheModeItself:
    async def test_production_is_the_default_when_nothing_is_stored(self):
        """An installation older than this feature is a production one.

        Defaulting to demo would silently unlock the setup gate on every
        existing deployment, which is the failure that only shows up after it
        has already happened.
        """
        assert await demo.current_mode(_Session(mode=None)) == "production"

    async def test_demo_is_read_from_the_active_row(self):
        assert await demo.is_demo(_Session(mode="demo"))
        assert not await demo.is_demo(_Session(mode="production"))


class TestDemoModeCannotReachTheNetwork:
    """The seams, each checked before a client is built.

    Checking afterwards, or relying on there being no credential, makes safety
    depend on configuration somebody can change — and a demo installation that
    still holds a working key would spend it.
    """

    def test_egress_is_refused_and_names_what_was_attempted(self):
        with pytest.raises(demo.EgressBlockedError) as exc:
            demo.assert_no_egress("demo", "a model call for 'signal_extraction'")
        assert "signal_extraction" in str(exc.value)
        # And it says how to get out of the state, not only that you are in it.
        assert "Switch to production" in str(exc.value)

    def test_production_lets_everything_through(self):
        demo.assert_no_egress("production", "a model call")

    async def test_a_stage_refuses_before_a_client_exists(self, monkeypatch):
        """The important ordering assertion.

        If the check ran after client construction, an installation holding a
        real key would build a real client — and one refactor later, use it.
        """
        from app.services import llm

        built = False

        def _tripwire(*a, **kw):
            nonlocal built
            built = True
            raise AssertionError("a client was constructed in demo mode")

        monkeypatch.setattr(llm, "_client", _tripwire)

        with pytest.raises(demo.EgressBlockedError):
            await llm.assert_may_call(_Session(mode="demo"), "signal_extraction")
        assert not built

    async def test_a_stage_call_site_is_blocked_end_to_end(self):
        from app.services import stages

        class _A:
            id = "00000000-0000-0000-0000-000000000001"
            name = "Northwind"
            domain = "northwind.example"

        with pytest.raises(demo.EgressBlockedError):
            await stages.research_family(
                _Session(mode="demo"), account=_A(), family="funding_and_growth"
            )

    async def test_an_injected_client_still_works_in_demo_mode(self):
        """Fixtures and tests supply their own client.

        That path is the caller taking responsibility for where the call goes,
        so it is not egress — and blocking it would make demo mode untestable
        and fixture data impossible to generate.
        """
        from app.schemas.draft import FreshnessVerdict
        from app.services import llm
        from app.services.prompt import PromptAssembly, SystemBlock
        from tests.test_llm_call_sites import FakeClient

        verdict = FreshnessVerdict(proceed=True)
        result = await llm.call_structured(
            config=llm.StageConfig(scenario="pre_send_revalidation"),
            prefix=PromptAssembly(blocks=[SystemBlock("s", "x")]),
            user_content="anything",
            output_model=FreshnessVerdict,
            client=FakeClient(verdict),
        )
        assert result.parsed is verdict


class TestDemoModeSatisfiesTheGate:
    async def test_every_mandatory_slot_is_filled_by_a_named_stub(self):
        state = await readiness.evaluate(_Session(mode="demo"))
        assert state.ready
        assert state.mode == "demo"
        for slot in state.slots:
            assert slot.satisfied
            assert len(slot.credentials) == 1
            # Named so it can never be mistaken for a real vendor on screen.
            assert slot.credentials[0].provider.startswith("demo_")
            assert "stub" in slot.credentials[0].label.lower()

    async def test_no_credential_row_is_invented(self):
        """The whole reason this is not implemented with fake credentials.

        The stub states carry no `last_four`, because there is no key — and
        nothing was written to `integration_credential` to produce them.
        """
        state = await readiness.evaluate(_Session(mode="demo"))
        assert all(c.last_four is None for s in state.slots for c in s.credentials)

    async def test_production_with_nothing_configured_is_still_blocked(self):
        state = await readiness.evaluate(_Session(mode="production"))
        assert not state.ready
        # Three provider slots plus the configuration requirement — an empty
        # production install has nothing to sell as well as nothing to sell it
        # with.
        assert len(state.blockers) == 4
        assert state.requirements


class TestSwitchingBack:
    """Leaving demo is the direction that needs care.

    Demo runs produce fixture evidence, and evidence is the bottom of every
    citation in the system. A book where some citations are fixtures cannot be
    trusted by the rep reading it, and nothing on screen tells them apart.
    """

    async def test_demo_runs_are_counted(self):
        assert await demo.demo_run_count(_Session(demo_runs=4)) == 4

    async def test_readiness_reports_them_even_in_production(self):
        state = await readiness.evaluate(_Session(mode="production", demo_runs=7))
        assert state.demo_runs == 7

    def test_a_run_carries_its_mode(self):
        """One column, because every artefact carries `run_id`.

        Tagging evidence, signals, context, qualification and strategy
        individually would be five chances to forget one.
        """
        from app.models.account import Run

        assert "mode" in Run.__table__.c
