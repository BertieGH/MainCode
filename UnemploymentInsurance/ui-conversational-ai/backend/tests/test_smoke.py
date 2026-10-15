"""
Smoke test — confirms the topology wires up and a turn flows through every agent
without errors, even though every agent body is still a stub. As real
implementations land, these tests stay green if the contracts are preserved.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.agents.orchestrator import Orchestrator
from app.models import ConversationState


@pytest.mark.asyncio
async def test_turn_pipeline_runs_through_all_agents():
    orch = Orchestrator()
    state = ConversationState(
        conversation_id="test-conv-1",
        claim_id="test-claim-1",
        week_ending="2026-05-24",
        state_code="CA",
        started_at=datetime.now(timezone.utc),
    )

    # Default planner returns ESCALATE → conversation closes without a reply.
    state, reply, closed = await orch.handle_turn(state, "I didn't work last week.")
    assert closed is True
    assert reply is None
    assert state.status == "escalated"
    assert len(state.turns) == 1
    assert state.turns[0].claimant is not None


@pytest.mark.asyncio
async def test_finalize_produces_report():
    orch = Orchestrator()
    state = ConversationState(
        conversation_id="test-conv-2",
        claim_id="test-claim-2",
        week_ending="2026-05-24",
        state_code="CA",
        started_at=datetime.now(timezone.utc),
    )
    report = await orch.finalize(state)
    assert report.conversation_id == "test-conv-2"
    assert report.decision is not None
