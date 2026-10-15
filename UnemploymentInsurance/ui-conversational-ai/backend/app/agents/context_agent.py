"""
Context Agent — assembles the per-turn working context for the Strategy Planner.

Deterministic + retrieval hybrid. The Planner never decides what to retrieve;
this agent always serves a pre-packaged bundle.

Bundle contents (per turn):
  - claimant profile (state, claim id, week-ending, base questions answered so far)
  - prior weeks' certifications summary (counts, last refused-offer, etc.)
  - current-week known signals (from SignalExtractor over all turns this conv)
  - OUTSTANDING EVIDENCE GAPS  (set difference: required-for-state - known)
  - relevant policy snippets (Vertex AI Search, scoped to current gaps)
  - candidate next questions (Vertex AI Search over question bank)
  - fraud history for this claimant
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import ConversationState, FraudSignal, PolicyCitation, Signal
from .base import Agent


@dataclass
class WorkingContext:
    state_code: str
    week_ending: str
    known_signals: list[Signal]
    outstanding_gaps: list[str]
    policy_snippets: list[PolicyCitation]
    candidate_questions: list[dict]
    prior_fraud_signals: list[FraudSignal]
    base_questions_remaining: list[str]


class ContextAgent(Agent):
    name = "context_agent"

    # Five base questions every weekly cert must cover, per the user's spec.
    # Exact wording is configurable per state.
    BASE_QUESTIONS = [
        "did_work",
        "earnings_reported",
        "available_for_work",
        "able_to_work",
        "actively_seeking",
    ]

    def __init__(self, search_client=None) -> None:
        super().__init__()
        self.search = search_client

    async def assemble(self, state: ConversationState) -> WorkingContext:
        self._audit("invoke", turn_index=len(state.turns), known_signals=len(state.signals))
        # TODO: compute outstanding_gaps from known signals + state-specific rule set.
        # TODO: Vertex AI Search calls for policy snippets + candidate questions.
        return WorkingContext(
            state_code=state.state_code,
            week_ending=state.week_ending,
            known_signals=state.signals,
            outstanding_gaps=state.outstanding_evidence_gaps,
            policy_snippets=[],
            candidate_questions=[],
            prior_fraud_signals=state.fraud_signals,
            base_questions_remaining=self.BASE_QUESTIONS,
        )
