"""Each stage is gated on the capability it actually uses.

Before this there was one boolean. Every gated route asked "is the whole
installation connected?", so a missing La Growth Machine credential — which
only matters when a sequence is *sent* — blocked parsing a CSV and blocked
asking Apollo for an address. Two stages away, and neither spends anything LGM
is involved in.

The rule this file holds: **a capability blocks the work that uses it, and
nothing else.**

* import           — nothing. It parses a spreadsheet.
* verify-contacts  — enrichment. It spends provider credits.
* campaigns        — llm. Promotion locks a queue and copies threads; no LGM
                     call happens until a sequence is enrolled.
* execute          — outreach. The send path, and the only place a missing LGM
                     credential stops anybody.

There is a real argument for the old design: someone who researches a hundred
accounts and then finds nothing can send has wasted the spend. But the remedy
was wrong — it blocked cheap, reversible steps to prevent a later
disappointment, and could not prevent it anyway, because the outreach routes
refuse on their own. A warning says the same thing without stopping work.
"""

from __future__ import annotations

import pytest

from app.services import readiness
from app.services.readiness import CredentialState, Readiness, Slot


def _state(**satisfied: bool) -> Readiness:
    """A real `Readiness`, built from real slots and credentials.

    Not a stub with an overridden `slot()`: `ready` iterates `self.slots` while
    `satisfies` goes through `slot()`, so faking one and not the other tests
    the fake rather than the split. A credential with `status="valid"` is what
    actually makes a slot satisfied, so that is what these are given.
    """
    state = Readiness()
    state.slots = [
        Slot(
            kind=kind,
            title=kind,
            why="",
            credentials=[
                CredentialState(
                    provider=f"{kind}-provider",
                    label=kind,
                    status="valid" if ok else "missing",
                )
            ]
            if ok
            else [],
        )
        for kind, ok in satisfied.items()
    ]
    return state


class TestWhatBlocksWhat:
    def test_a_missing_outreach_key_still_leaves_the_app_workable(self):
        """The state this whole change is about, and the one you are in."""
        state = _state(llm=True, enrichment=True, outreach=False)
        assert state.workable is True
        assert state.satisfies("enrichment") is True
        assert state.satisfies("outreach") is False

    def test_a_missing_enrichment_key_stops_enrichment(self):
        state = _state(llm=True, enrichment=False, outreach=True)
        assert state.satisfies("enrichment") is False
        assert state.workable is False
        # …but not sending, which uses a different vendor entirely.
        assert state.satisfies("outreach") is True

    def test_blockers_name_only_the_capability_asked_about(self):
        """Reporting every blocker is how the confusion started.

        Telling somebody who wants to enrich that they need an outreach
        credential is exactly the conflation this split removes.
        """
        state = _state(llm=True, enrichment=True, outreach=False)
        assert state.blockers_for("enrichment") == []
        # The slot writes its own sentence ("No outreach provider is
        # configured."); what matters is that it names outreach and nothing
        # else, not its exact wording.
        outreach = state.blockers_for("outreach")
        assert len(outreach) == 1
        assert "outreach" in outreach[0].lower()

    def test_a_configuration_gap_blocks_every_capability(self):
        """A service with no ICP is not a credential and belongs to no slot.

        It stops enrichment and strategy alike, so it counts against whatever
        is being asked about rather than against one slot.
        """
        state = _state(llm=True, enrichment=True, outreach=True)
        state.requirements = ["No active service has an ICP yet."]
        assert state.satisfies("enrichment") is False
        assert state.workable is False
        assert "ICP" in state.blockers_for("enrichment")[0]

    def test_ready_still_means_everything(self):
        """`ready` keeps its meaning; it just stops being the gate."""
        assert _state(llm=True, enrichment=True, outreach=True).ready is True
        assert _state(llm=True, enrichment=True, outreach=False).ready is False

    def test_workable_does_not_include_outreach(self):
        """The whole point, asserted directly so nobody re-adds it."""
        assert "outreach" not in readiness.WORKABLE_KINDS
        assert set(readiness.WORKABLE_KINDS) == {"llm", "enrichment"}


class TestTheGateItself:
    """The dependency `requires()` builds, exercised directly.

    Through the gate rather than by inspecting route metadata: what matters is
    that asking for one capability does not fail on another's absence, and that
    is behaviour rather than wiring.
    """

    async def _run(self, monkeypatch, kinds, state):
        from app.api import deps

        async def _evaluate(_session):
            return state

        monkeypatch.setattr(deps.readiness, "evaluate", _evaluate)
        gate = deps.requires(*kinds)
        return await gate(session=None)

    async def test_enrichment_passes_without_an_outreach_credential(
        self, monkeypatch
    ):
        """The state this change is about. Previously a 409."""
        state = _state(llm=True, enrichment=True, outreach=False)
        assert await self._run(monkeypatch, ("enrichment",), state) is None

    async def test_outreach_is_still_refused(self, monkeypatch):
        from fastapi import HTTPException

        state = _state(llm=True, enrichment=True, outreach=False)
        with pytest.raises(HTTPException) as caught:
            await self._run(monkeypatch, ("outreach",), state)
        assert caught.value.status_code == 409
        assert caught.value.detail["error"] == "setup_incomplete"

    async def test_the_refusal_names_only_the_missing_capability(
        self, monkeypatch
    ):
        """Not "setup incomplete" — which sends somebody hunting."""
        from fastapi import HTTPException

        state = _state(llm=True, enrichment=True, outreach=False)
        with pytest.raises(HTTPException) as caught:
            await self._run(monkeypatch, ("outreach",), state)
        blockers = caught.value.detail["blockers"]
        assert blockers and all("outreach" in b.lower() for b in blockers)
