"""
Adjudicator Report Generator — runs once at conversation close.

Produces a structured JSON the human adjudicator (or, eventually, the autonomous
band) sees. Pro model takes the full transcript + signals + decision and writes:
  - One-paragraph plain-English summary of the claimant's situation
  - Per-rule findings with cited policy snippets
  - Fraud flags with severity
  - Documents received with extracted-field summary
  - Suggested disposition + confidence band

The decision (eligible/not + band) is what the EligibilityEvaluator already
produced — this agent does NOT recompute. It explains.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..core.config import get_settings
from ..models import AdjudicatorReport, ConversationState, Decision
from .base import Agent


class AdjudicatorReportAgent(Agent):
    name = "adjudicator_report"

    async def generate(self, state: ConversationState, decision: Decision) -> AdjudicatorReport:
        self._audit("invoke", conversation_id=state.conversation_id, band=decision.band.value)
        # TODO: Pro structured-output call with state.turns + decision.rule_results
        # serialised; output Pydantic-validated AdjudicatorReport.
        return AdjudicatorReport(
            conversation_id=state.conversation_id,
            claim_id=state.claim_id,
            week_ending=state.week_ending,
            decision=decision,
            transcript=state.turns,
            signals=state.signals,
            documents_received=state.documents_received,
            generated_at=datetime.now(timezone.utc),
            generated_by_model=get_settings().planner_model,
        )
