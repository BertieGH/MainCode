"""
Eligibility Evaluator — applies the state's weekly-cert rule set against
collected signals, producing a per-rule pass/fail + confidence + policy citations.

Hybrid: deterministic rule engine for the "obvious" facts (earnings cap,
hours cap, availability), Pro LLM for nuanced situations (separation reason
interpretation, jobsearch validity).

Rule set is state-scoped and lives in `data/policy/<state>/rules.yaml`.
"""
from __future__ import annotations

from ..models import ConfidenceBand, Decision, EligibilityRuleResult, FraudSignal, Signal
from ..core.config import get_settings
from .base import Agent


class EligibilityEvaluator(Agent):
    name = "eligibility_evaluator"

    async def evaluate(
        self,
        state_code: str,
        signals: list[Signal],
        fraud_signals: list[FraudSignal],
    ) -> Decision:
        self._audit("invoke", state_code=state_code, signal_count=len(signals))
        rule_results: list[EligibilityRuleResult] = []
        # TODO: load state rule set, run deterministic rules first, hand
        # ambiguous rules to Pro with context.
        agg = self._aggregate_confidence(rule_results)
        band = self._band(agg, has_fraud_or_legal_flag=bool(fraud_signals))
        eligible = all(r.passed for r in rule_results)
        return Decision(
            eligible=eligible,
            aggregate_confidence=agg,
            band=band,
            rule_results=rule_results,
            fraud_signals=fraud_signals,
        )

    @staticmethod
    def _aggregate_confidence(rule_results: list[EligibilityRuleResult]) -> float:
        if not rule_results:
            return 0.0
        # Minimum across rules — a chain is as confident as its weakest link.
        return min(r.confidence for r in rule_results)

    @staticmethod
    def _band(agg: float, *, has_fraud_or_legal_flag: bool) -> ConfidenceBand:
        s = get_settings()
        if has_fraud_or_legal_flag or agg < s.conf_adjudicator_min:
            return ConfidenceBand.ESCALATE
        if agg >= s.conf_autonomous_min:
            return ConfidenceBand.AUTONOMOUS
        return ConfidenceBand.ADJUDICATOR
