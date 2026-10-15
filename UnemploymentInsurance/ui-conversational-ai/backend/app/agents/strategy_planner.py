"""
Strategy / Planner — THE BRAIN.

Gemini 2.5 Pro. Decides what the next turn should accomplish given the working
context. Emits a structured NextAction; never writes prose for the claimant
(that's the Phraser).

Decision space:
  PROBE_GAP        — ask a question to close an outstanding evidence gap
  PROBE_FRAUD      — clarify a fraud signal (e.g. earnings vs hours contradiction)
  REQUEST_DOCUMENT — ask claimant to upload a paystub / separation letter
  CONFIRM_SIGNAL   — ambiguous extraction; confirm a slot before relying on it
  FINALIZE         — sufficient evidence; close out and generate report
  ESCALATE         — situation outside POC scope; route to human immediately

Critically, the planner does NOT phrase the question or contact the claimant
itself — it only emits the structured NextAction. This keeps WHAT we ask
auditable separately from HOW it's phrased.
"""
from __future__ import annotations

from ..models import NextAction, NextActionKind
from .base import Agent
from .context_agent import WorkingContext


class StrategyPlanner(Agent):
    name = "strategy_planner"

    async def plan(self, ctx: WorkingContext) -> NextAction:
        self._audit(
            "invoke",
            outstanding_gaps=ctx.outstanding_gaps,
            known_signal_count=len(ctx.known_signals),
            fraud_signal_count=len(ctx.prior_fraud_signals),
        )
        # TODO: Pro structured-output call with full WorkingContext serialised.
        # Until then, default to ESCALATE so nothing accidentally autonomous.
        return NextAction(
            kind=NextActionKind.ESCALATE,
            instruction="Planner not yet implemented; escalate to human adjudicator.",
            rationale="placeholder",
            confidence=0.0,
        )
