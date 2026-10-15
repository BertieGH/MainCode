"""
Orchestrator — the conductor.

Owns the per-turn pipeline and the conversation lifecycle. Holds one instance
of each agent. Stateless across conversations; conversation state is loaded
from / written to Firestore (live) and Postgres (final).

Per-turn pipeline (called by the conversation API on each claimant message):

    handle_turn(state, claimant_text) -> (state, agent_reply | None, closed)

      1. inbound_pii_guard.redact(claimant_text)
      2. intent_analyzer.analyze(redacted)
      3. signal_extractor.extract(redacted, intent)
         → append to state.signals
      4. fraud_scorer.score(state)
         → append to state.fraud_signals
      5. context_agent.assemble(state)
      6. strategy_planner.plan(ctx)                                   ┐
         if NextAction.kind == FINALIZE  →  close + report (no reply) │
         if NextAction.kind == ESCALATE  →  escalate (no reply)       │ planning
         if NextAction.kind == REQUEST_DOCUMENT → emit doc-request    │ loop
                                                                      │ (bounded)
      7. dialog_phraser.phrase(action)                                │
      8. legal_relevance_guard.check(drafted)                         │
         if blocked → loop back to (6) with "avoid topic X" hint      │
         (max MAX_PLANNER_STEPS_PER_TURN attempts)                    ┘
      9. outbound_pii_guard.check(drafted, allowed_slots=[action.target_slot])
         if blocked → loop back to (6)
     10. emit drafted to claimant; record AgentTurn

At conversation close:
    finalize(state) -> AdjudicatorReport
      eligibility_evaluator.evaluate(...) → decision
      adjudicator_report.generate(state, decision)
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..core.audit import audit_event, set_conversation_id
from ..core.config import get_settings
from ..models import (
    AdjudicatorReport,
    AgentTurn,
    ClaimantTurn,
    ConversationState,
    NextAction,
    NextActionKind,
    TurnRecord,
)
from .adjudicator_report import AdjudicatorReportAgent
from .context_agent import ContextAgent
from .dialog_phraser import DialogPhraser
from .document_collector import DocumentCollector
from .eligibility_evaluator import EligibilityEvaluator
from .fraud_scorer import FraudScorer
from .intent_analyzer import IntentAnalyzer
from .legal_relevance_guard import LegalRelevanceGuard
from .pii_guard import InboundPIIGuard, OutboundPIIGuard
from .signal_extractor import SignalExtractor
from .strategy_planner import StrategyPlanner


class Orchestrator:
    def __init__(self) -> None:
        self.inbound_pii = InboundPIIGuard()
        self.intent = IntentAnalyzer()
        self.signals = SignalExtractor()
        self.context = ContextAgent()
        self.planner = StrategyPlanner()
        self.fraud = FraudScorer()
        self.eligibility = EligibilityEvaluator()
        self.docs = DocumentCollector()
        self.phraser = DialogPhraser()
        self.legal_guard = LegalRelevanceGuard()
        self.outbound_pii = OutboundPIIGuard()
        self.report = AdjudicatorReportAgent()

    async def handle_turn(
        self,
        state: ConversationState,
        claimant_text: str,
    ) -> tuple[ConversationState, str | None, bool]:
        """
        Process one claimant turn. Returns (updated_state, agent_reply, closed).
        agent_reply is None when the conversation closes or escalates without a final question.
        """
        set_conversation_id(state.conversation_id)
        settings = get_settings()
        turn_index = len(state.turns)

        # 1. inbound PII guard
        pii_verdict = await self.inbound_pii.redact(claimant_text)
        redacted = pii_verdict.redacted_text or claimant_text

        claimant_turn = ClaimantTurn(
            text=claimant_text if False else "",   # never persist raw text — only redacted
            received_at=datetime.now(timezone.utc),
            pii_redacted_text=redacted,
            pii_findings=pii_verdict.findings,
        )
        state.turns.append(TurnRecord(index=turn_index, claimant=claimant_turn))

        # 2. intent
        intent, intent_conf = await self.intent.analyze(redacted)

        # 3. signals
        new_signals = await self.signals.extract(redacted, intent, turn_index)
        state.signals.extend(new_signals)

        # 4. fraud (runs over the whole conversation, not just this turn)
        state.fraud_signals = await self.fraud.score(state)

        # 5. context
        ctx = await self.context.assemble(state)

        # 6-9. planner -> phraser -> guards (bounded retry loop)
        action: NextAction | None = None
        drafted: str | None = None
        avoid_hints: list[str] = []
        for attempt in range(settings.max_planner_steps_per_turn):
            action = await self.planner.plan(ctx)
            audit_event(
                "planner.action",
                turn_index=turn_index,
                attempt=attempt,
                kind=action.kind.value,
                target_slot=action.target_slot,
                confidence=action.confidence,
            )

            if action.kind in (NextActionKind.FINALIZE, NextActionKind.ESCALATE):
                drafted = None
                break
            if action.kind == NextActionKind.REQUEST_DOCUMENT:
                # phraser still writes a friendly ask for the doc
                pass

            drafted = await self.phraser.phrase(action, prior_turn_text=redacted)

            legal = await self.legal_guard.check(drafted, state.state_code)
            if not legal.allowed:
                audit_event(
                    "legal_guard.blocked",
                    turn_index=turn_index,
                    forbidden_topic=legal.forbidden_topic,
                    reason=legal.reason,
                )
                avoid_hints.append(legal.forbidden_topic or "blocked")
                # TODO: feed avoid_hints back into planner via ctx
                continue

            allowed_slots = [action.target_slot] if action.target_slot else []
            pii_out = await self.outbound_pii.check(drafted, allowed_slots=allowed_slots)
            if not pii_out.allowed:
                audit_event("outbound_pii.blocked", turn_index=turn_index, reason=pii_out.reason)
                continue

            break
        else:
            # exhausted planning attempts — escalate
            audit_event("planner.exhausted", turn_index=turn_index)
            state.status = "escalated"
            return state, None, True

        # 10. emit reply or close
        if action and action.kind == NextActionKind.FINALIZE:
            state.status = "closed"
            state.closed_at = datetime.now(timezone.utc)
            return state, None, True
        if action and action.kind == NextActionKind.ESCALATE:
            state.status = "escalated"
            state.closed_at = datetime.now(timezone.utc)
            return state, None, True

        if drafted:
            state.turns[-1].agent = AgentTurn(
                text=drafted,
                sent_at=datetime.now(timezone.utc),
                legal_citation_ids=[],   # filled when LegalRelevanceGuard is implemented
                intended_signal_slot=action.target_slot if action else None,
            )

        if len(state.turns) >= settings.max_turns_per_conversation:
            state.status = "escalated"
            audit_event("turn_limit.exhausted", turn_count=len(state.turns))
            return state, drafted, True

        return state, drafted, False

    async def finalize(self, state: ConversationState) -> AdjudicatorReport:
        set_conversation_id(state.conversation_id)
        decision = await self.eligibility.evaluate(
            state_code=state.state_code,
            signals=state.signals,
            fraud_signals=state.fraud_signals,
        )
        report = await self.report.generate(state, decision)
        audit_event(
            "conversation.finalized",
            eligible=decision.eligible,
            band=decision.band.value,
            confidence=decision.aggregate_confidence,
        )
        return report
