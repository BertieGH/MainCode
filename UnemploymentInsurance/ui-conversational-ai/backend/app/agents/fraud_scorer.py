"""
Fraud Scorer — emits FraudSignal records for velocity, contradiction,
location anomaly, prior-claim anomaly, identity mismatch, and behavioral
heuristics.

Hybrid: deterministic rules + Flash classifier for ambiguous behavioral signals.
"""
from __future__ import annotations

from ..models import ConversationState, FraudSignal
from .base import Agent


class FraudScorer(Agent):
    name = "fraud_scorer"

    async def score(self, state: ConversationState) -> list[FraudSignal]:
        self._audit("invoke", turn_count=len(state.turns), signal_count=len(state.signals))
        signals: list[FraudSignal] = []
        # TODO: deterministic checks
        #   - earnings/hours contradiction
        #   - cert-time velocity (impossibly fast cert)
        #   - IP/geo vs claimant state mismatch
        #   - prior-week pattern (always says "no work" + reported earnings later)
        # TODO: Flash classifier for behavioral nuance
        return signals
