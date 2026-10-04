"""Domain 4 — what research actually looked at.

`docs/03` defines no table for this; it is an addition. Coverage has to be
stored rather than derived, because the interesting fact is a **negative**: the
hiring family ran and found nothing. Absence of evidence rows cannot express
that — it is indistinguishable from the family never having run, from the run
crashing halfway, and from nobody having configured the family at all.

`docs/06 §7.1` requires the difference to reach the rep: "a family that returns
nothing is reported to the rep as a gap, not silently omitted."
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

#: What happened when a family ran.
#:
#: `empty` and `failed` are deliberately distinct. Empty is an answer — there
#: is no funding news about this company — and it is often the correct one.
#: Failed means we do not know, and the two must never be shown to a rep as the
#: same thing: one is intelligence, the other is a broken pipeline.
COVERAGE_STATUS = ("ran", "empty", "failed", "skipped")


class ResearchCoverage(Base):
    """One row per (run, family): did it look, and did it find anything."""

    __tablename__ = "research_coverage"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    family: Mapped[str] = mapped_column(Text, nullable=False)
    #: The person this row is about; null for the company. Per person, so the
    #: reuse window can skip one person's fresh families and not another's.
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    #: Why it was skipped, or how it failed. Shown to the rep verbatim.
    detail: Mapped[str | None] = mapped_column(Text)
    #: What the family searched for and could not establish — the model's own
    #: `not_found`, including any passages grounding discarded. This is what
    #: turns `empty` from "nothing found" into "looked for these; none of it is
    #: there", which is the version a rep can trust.
    not_found: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    #: Remarks about the *shape* of what came back, not about what is missing:
    #: "20 newer entries beyond the 10 kept", "nothing published in 18 months".
    #: These used to share `not_found`, so a sweep that found thirty entries
    #: and kept ten was reported as having failed to establish something.
    notes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('ran','empty','failed','skipped')", name="status_valid"
        ),
        # 'ran' means it found something; the count is what distinguishes it
        # from 'empty', so the two must agree or the strip lies.
        CheckConstraint(
            "(status = 'ran') = (evidence_count > 0)", name="count_matches_status"
        ),
        CheckConstraint("evidence_count >= 0", name="count_non_negative"),
        # A failure a rep cannot read is a failure a rep cannot act on.
        CheckConstraint(
            "status <> 'failed' OR detail IS NOT NULL", name="failed_needs_a_reason"
        ),
        # One company row per family per run, and one row per person beside it.
        # NULLS NOT DISTINCT so two company rows (contact null) still collide.
        UniqueConstraint(
            "run_id", "family", "contact_id",
            name="one_row_per_family_per_run",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_research_coverage_account", "account_id"),
    )
