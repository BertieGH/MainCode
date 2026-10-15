from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Intents & signals
# ─────────────────────────────────────────────────────────────────────────────

class Intent(str, Enum):
    REPORT_WORK = "report_work"
    REPORT_EARNINGS = "report_earnings"
    REPORT_JOBSEARCH = "report_jobsearch"
    REFUSE_OFFER = "refuse_offer"
    MEDICAL_UNAVAILABLE = "medical_unavailable"
    AVAILABILITY_CONSTRAINT = "availability_constraint"
    CLARIFICATION = "clarification"
    OFF_TOPIC = "off_topic"
    PROVIDE_DOCUMENT = "provide_document"
    UNKNOWN = "unknown"


class Signal(BaseModel):
    """A single structured eligibility signal extracted from a claimant turn."""
    slot: str = Field(..., description="canonical slot name, e.g. 'hours_worked', 'gross_earnings'")
    value: Any
    confidence: float = Field(..., ge=0.0, le=1.0)
    source_turn_index: int
    rationale: str | None = None


class FraudSignal(BaseModel):
    kind: Literal[
        "velocity",
        "contradiction",
        "location_anomaly",
        "prior_claim_anomaly",
        "identity_mismatch",
        "behavioral",
    ]
    severity: float = Field(..., ge=0.0, le=1.0)
    description: str
    evidence_turn_indices: list[int] = []


# ─────────────────────────────────────────────────────────────────────────────
# Conversation state
# ─────────────────────────────────────────────────────────────────────────────

class ClaimantTurn(BaseModel):
    text: str
    received_at: datetime
    pii_redacted_text: str | None = None
    pii_findings: list[dict[str, Any]] = []


class AgentTurn(BaseModel):
    text: str
    sent_at: datetime
    legal_citation_ids: list[str] = []
    intended_signal_slot: str | None = None


class TurnRecord(BaseModel):
    index: int
    claimant: ClaimantTurn | None = None
    agent: AgentTurn | None = None


class ConversationState(BaseModel):
    conversation_id: str
    claim_id: str
    week_ending: str   # ISO date, the week this certification covers
    state_code: str    # US state, e.g. "CA", "TX"
    status: Literal["active", "awaiting_doc", "closed", "escalated"] = "active"
    turns: list[TurnRecord] = []
    signals: list[Signal] = []
    fraud_signals: list[FraudSignal] = []
    outstanding_evidence_gaps: list[str] = []
    documents_requested: list[str] = []
    documents_received: list[str] = []
    started_at: datetime
    closed_at: datetime | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Planner output
# ─────────────────────────────────────────────────────────────────────────────

class NextActionKind(str, Enum):
    PROBE_GAP = "probe_gap"
    PROBE_FRAUD = "probe_fraud"
    REQUEST_DOCUMENT = "request_document"
    CONFIRM_SIGNAL = "confirm_signal"
    FINALIZE = "finalize"
    ESCALATE = "escalate"


class NextAction(BaseModel):
    kind: NextActionKind
    target_slot: str | None = None
    target_fraud_kind: str | None = None
    document_type: str | None = None
    instruction: str = Field(..., description="Strategy-level instruction for the Phraser.")
    rationale: str
    cited_policy_ids: list[str] = []
    confidence: float = Field(..., ge=0.0, le=1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Guards
# ─────────────────────────────────────────────────────────────────────────────

class GuardVerdict(BaseModel):
    allowed: bool
    findings: list[dict[str, Any]] = []
    redacted_text: str | None = None
    reason: str | None = None


class LegalGuardVerdict(BaseModel):
    allowed: bool
    matched_allowlist_ids: list[str] = []
    forbidden_topic: str | None = None
    reason: str | None = None


class DocumentRequest(BaseModel):
    document_type: str
    reason: str
    required: bool = True
    accepted_formats: list[str] = ["pdf", "png", "jpg"]


# ─────────────────────────────────────────────────────────────────────────────
# Eligibility & adjudication
# ─────────────────────────────────────────────────────────────────────────────

class PolicyCitation(BaseModel):
    policy_id: str
    title: str
    snippet: str
    url: str | None = None


class EligibilityRuleResult(BaseModel):
    rule_id: str
    rule_title: str
    passed: bool
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_signal_slots: list[str] = []
    citations: list[PolicyCitation] = []
    notes: str | None = None


class ConfidenceBand(str, Enum):
    AUTONOMOUS = "autonomous"           # >= 0.90 all rules
    ADJUDICATOR = "adjudicator"         # 0.65 - 0.90
    ESCALATE = "escalate"               # < 0.65 or any legal/PII flag


class Decision(BaseModel):
    eligible: bool
    aggregate_confidence: float = Field(..., ge=0.0, le=1.0)
    band: ConfidenceBand
    rule_results: list[EligibilityRuleResult]
    fraud_signals: list[FraudSignal]
    notes: str | None = None


class AdjudicatorReport(BaseModel):
    conversation_id: str
    claim_id: str
    week_ending: str
    decision: Decision
    transcript: list[TurnRecord]
    signals: list[Signal]
    documents_received: list[str]
    generated_at: datetime
    generated_by_model: str


# ─────────────────────────────────────────────────────────────────────────────
# Audit
# ─────────────────────────────────────────────────────────────────────────────

class AuditEntry(BaseModel):
    conversation_id: str
    turn_index: int | None = None
    event: str
    agent: str | None = None
    payload: dict[str, Any] = {}
    occurred_at: datetime
