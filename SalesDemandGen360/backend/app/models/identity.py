"""Who is using the installation.

One organisation today — CGVAK — and the table exists anyway, so that a later
split into several costs a column rather than a redesign (`docs/17`). Nothing
else carries an organisation id yet, deliberately: tenancy was costed and
declined, and threading it through fifty tables "just in case" is the expensive
half of that decision.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

#: The four roles. TEXT + CHECK rather than an enum, per the convention:
#: adding a role is then a constraint change, not an enum migration.
ROLES = ("admin", "aiops", "marketing", "demandgen")
STATUSES = ("active", "deactivated")


class Organization(Base):
    __tablename__ = "organization"

    name: Mapped[str] = mapped_column(Text, nullable=False)


class User(Base):
    """A person who can sign in.

    Created only by an admin, who sets the password and tells them it — there
    is no self-registration and no email (`docs/17`). Never deleted: approvals
    and sends will point here, and "who did this" must stay answerable after
    someone leaves. Deactivation is the way out.

    `app_user` because `user` is reserved in Postgres and quoting it everywhere
    is a bug waiting for the one query that forgets.
    """

    __tablename__ = "app_user"
    __table_args__ = (
        CheckConstraint(f"role IN {ROLES!r}", name="role_valid"),
        CheckConstraint(f"status IN {STATUSES!r}", name="status_valid"),
        # One account per address, whatever its case. People type their own
        # email with a capital letter about as often as not.
        Index("uq_app_user_email_lower", text("lower(email)"), unique=True),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")

    #: scrypt, as `admin_gate` — raw bytes, with the cost parameters kept per
    #: row so raising them later invalidates nobody.
    password_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    salt: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    n: Mapped[int] = mapped_column(Integer, nullable=False)
    r: Mapped[int] = mapped_column(Integer, nullable=False)
    p: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Part of every session token. Bumping it signs this person out
    #: everywhere at once — on a password change, a reset or a deactivation —
    #: without a session table to sweep.
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Null for the first admin, who is made from the command line.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
