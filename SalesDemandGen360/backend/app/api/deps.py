"""Shared endpoint dependencies.

The sort dependency is the reason this module exists. Every list endpoint in the
system sorts, and the naive implementation — interpolating ``?sort=`` into an
ORDER BY — is a SQL injection hole that looks like a convenience feature.

The rule: a sort field is only ever a **key into a mapping the endpoint owns**.
Nothing from the request reaches a query builder as text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import UnaryExpression
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.database import get_session
from app.services import readiness

Direction = Literal["asc", "desc"]


@dataclass(frozen=True)
class Sort:
    """A validated sort, resolved to a real column."""

    field: str | None
    direction: Direction

    def apply(self, stmt, allowed: dict[str, InstrumentedAttribute], default: UnaryExpression):
        """Attach ORDER BY, falling back to the endpoint's default.

        ``allowed`` maps the public field name to the column object. The value
        is never a string, so there is no path from the query parameter into
        generated SQL.
        """
        if self.field is None:
            return stmt.order_by(default)
        column = allowed[self.field]
        return stmt.order_by(column.desc() if self.direction == "desc" else column.asc())


def sort_params(
    sort: str | None = Query(
        None,
        description="Field to sort by. Must be on the endpoint's allowlist.",
        max_length=64,
    ),
    dir: Direction = Query("asc", description="Sort direction."),
) -> Sort:
    return Sort(field=sort, direction=dir)


def validate_sort(sort: Sort, allowed: dict[str, InstrumentedAttribute]) -> Sort:
    """Reject anything not on the allowlist, naming what is permitted.

    A 422 rather than silently ignoring the parameter: a client sorting by a
    field that quietly does nothing looks like a broken sort, and the bug gets
    filed against the wrong system.
    """
    if sort.field is not None and sort.field not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "unsortable_field",
                "field": sort.field,
                "allowed": sorted(allowed),
            },
        )
    return sort


@dataclass(frozen=True)
class Page:
    limit: int
    offset: int


def page_params(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page:
    return Page(limit=limit, offset=offset)


def requires(*kinds: str):
    """A dependency refusing pipeline work until *these* capabilities exist.

    Per capability, not one flag for all three. Before this, every gated route
    asked the same question, so a missing La Growth Machine key — which only
    matters at send time — blocked parsing a CSV and asking Apollo for an
    address. The stages are independent and the gate now says so.

    Server-side and not only in the navigation, because a disabled menu item is
    a suggestion: the endpoints are reachable directly, and a queue promoted
    without an outreach credential produces sequences that can never enrol.

    Deliberately **not** applied to reads or to configuration endpoints — the
    point of a gate is that you can still get in and fix what it is blocking,
    and being unable to look at what you already imported would make an
    incomplete setup feel like data loss.

    409 rather than 403: nothing is forbidden, the system is in the wrong state
    for it, and that state is one the caller can change.
    """

    async def _gate(session: AsyncSession = Depends(get_session)) -> None:
        try:
            await readiness.require_ready(session, *kinds)  # type: ignore[arg-type]
        except readiness.NotReadyError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "error": "setup_incomplete",
                    # Names what is *missing*, not what is required. Listing
                    # every kind told a rep to "connect llm and outreach" when
                    # the LLM was connected and working — sending them to fix
                    # something that was not broken.
                    "message": (
                        "Connect "
                        + " and ".join(exc.missing or kinds)
                        + " before running this."
                    ),
                    "blockers": exc.blockers,
                },
            ) from exc

    return _gate


#: The whole installation. Kept for callers that genuinely need everything.
require_setup = requires(*readiness.MANDATORY_KINDS)
