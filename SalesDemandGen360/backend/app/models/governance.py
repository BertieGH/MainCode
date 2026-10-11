"""Domain 7 — Evaluation and approval.

Two gates, in order: the **Evaluation Agent** is automated and runs before a
human sees anything; the **Approval** is the final outbound control and is
always a person.

The sample is a stored row, not a value computed on request. That is what makes
"the rep cannot hand-pick it" true rather than merely intended: the drawn ids
are written server-side once, and acceptance is checked against them. A sample
recomputed per request could be reshaped by asking again until the answer
suited.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

#: `outreach_sequence` is here because evaluation runs at the same level
#: approval does — `docs/06 §7.3`: "Approve once, at sequence level. One
#: approval covers the arc." `docs/03` lists it for `approval.subject_type` but
#: omits it here; that omission predates the sequence-level decision, and
#: without it an arc-level evaluation has no valid subject to name.
SUBJECT_TYPES = (
    "research", "signal", "qualification", "strategy", "outreach_sequence",
    "draft", "sales_prep", "execution",
)
APPROVAL_SUBJECTS = ("strategy", "outreach_sequence", "draft")
DECISIONS = ("approve", "edit", "regenerate", "reject")
REJECT_REASONS = (
    "wrong_persona", "wrong_signal", "wrong_problem", "wrong_solution",
    "poor_message", "other",
)
#: individual — a human read this one.
#: sampled    — in the drawn sample, so a human read it.
#: inherited  — accepted on the strength of the sample, unread.
REVIEW_DEPTHS = ("individual", "sampled", "inherited")


class Evaluation(Base):
    """Polymorphic — one table for every stage's checks.

    No FK on `subject_id` by design: the alternative is seven nullable columns,
    six of which are null on every row.
    """

    __tablename__ = "evaluation"

    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    scores: Mapped[dict | None] = mapped_column(JSONB)
    #: Structured findings. A `fail` with no issue recorded is a verdict nobody
    #: can act on, so the constraint below requires one.
    issues: Mapped[list | None] = mapped_column(JSONB)
    evaluator_version: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "subject_type IN ('research','signal','qualification','strategy',"
            "'outreach_sequence','draft','sales_prep','execution')",
            name="subject_type_valid",
        ),
        # `rep` is a person pressing a button on the prep screen. It lives
        # here rather than in a table of its own because "was this any good"
        # has one home, and a rep's answer and the evaluator's belong in it
        # together.
        CheckConstraint(
            "method IN ('rules','llm','hybrid','rep')", name="method_valid"
        ),
        CheckConstraint("verdict IN ('pass','warn','fail')", name="verdict_valid"),
        CheckConstraint(
            "verdict = 'pass' OR (issues IS NOT NULL AND jsonb_array_length(issues) > 0)",
            name="a_warning_or_failure_says_what_is_wrong",
        ),
        Index("ix_evaluation_subject", "subject_type", "subject_id"),
    )


class ApprovalSample(Base):
    """One server-side draw over a campaign's clean stratum.

    Superseded rather than mutated when it is redrawn or doubled, so the
    history of "how hard did we actually look at this campaign" survives — that
    is the whole basis for later arguing the sample rate is safe.
    """

    __tablename__ = "approval_sample"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outreach_campaign.id", ondelete="CASCADE"), nullable=False
    )
    draw_number: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    #: The sequences drawn. Written once, server-side; acceptance is checked
    #: against exactly this list.
    sequence_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    #: How many clean threads the draw was taken from.
    stratum_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_rate: Mapped[float | None] = mapped_column()
    #: Rejections found in this draw. One doubles the next; two drops the whole
    #: batch to individual review.
    rejections: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    escalated_to_individual: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("sample_size >= 0", name="sample_size_non_negative"),
        CheckConstraint("stratum_size >= 0", name="stratum_size_non_negative"),
        # A sample bigger than the stratum it came from is arithmetic that
        # cannot be true, and would silently mean "everything was read".
        CheckConstraint(
            "sample_size <= stratum_size", name="sample_fits_inside_its_stratum"
        ),
        CheckConstraint("rejections >= 0", name="rejections_non_negative"),
        CheckConstraint("draw_number > 0", name="draw_number_positive"),
        CheckConstraint(
            "jsonb_array_length(sequence_ids) = sample_size",
            name="the_drawn_ids_match_the_stated_size",
        ),
        Index(
            "one_current_sample_per_campaign",
            "campaign_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )


class Approval(Base):
    """The human gate.

    `execution_record` insert requires a matching `decision='approve'` row —
    that is the interlock the whole outbound path hangs on.
    """

    __tablename__ = "approval"

    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    #: The delta on an edit is the most valuable learning signal in the system.
    edited_body: Mapped[str | None] = mapped_column(Text)
    reviewer_id: Mapped[str] = mapped_column(Text, nullable=False)
    #: How closely this was actually read. Without it the sampling model can
    #: only be assumed safe, never demonstrated.
    review_depth: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'individual'")
    )
    sample_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_sample.id")
    )
    sample_size: Mapped[int | None] = mapped_column(Integer)
    stratum_size: Mapped[int | None] = mapped_column(Integer)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(
            "subject_type IN ('strategy','outreach_sequence','draft')",
            name="subject_type_valid",
        ),
        CheckConstraint(
            "decision IN ('approve','edit','regenerate','reject')", name="decision_valid"
        ),
        CheckConstraint(
            "review_depth IN ('individual','sampled','inherited')", name="review_depth_valid"
        ),
        CheckConstraint(
            "reject_reason IS NULL OR reject_reason IN ('wrong_persona','wrong_signal',"
            "'wrong_problem','wrong_solution','poor_message','other')",
            name="reject_reason_valid",
        ),
        # A rejection without a reason teaches the Learning layer nothing, and
        # the rejection-reason distribution is an M4 gate metric.
        CheckConstraint(
            "decision <> 'reject' OR reject_reason IS NOT NULL",
            name="a_rejection_says_why",
        ),
        CheckConstraint(
            "decision <> 'edit' OR edited_body IS NOT NULL", name="an_edit_carries_its_delta"
        ),
        # Anything that was not read individually must point at the sample that
        # justified it, or "how closely was this read" has no evidence behind it.
        CheckConstraint(
            "review_depth = 'individual' OR sample_id IS NOT NULL",
            name="sampled_and_inherited_cite_their_sample",
        ),
        Index("ix_approval_subject", "subject_type", "subject_id"),
        Index("ix_approval_sample", "sample_id"),
    )
