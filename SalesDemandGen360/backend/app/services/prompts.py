"""Reading and versioning the stage instructions.

`llm_config` decides how hard a stage thinks. This decides what it is asked to
do. Both are versioned per scenario and neither is edited in place.

Three things this module is careful about, each for a reason that bit
somewhere else first:

**The active row is the only answer.** The migration seeded v1 for every
scenario from the shipped `STAGE` dict, so there is no "database or code?"
branch at read time. A fallback would be the kind of thing that works in
development, silently takes the code path in production after a bad deploy, and
produces a book of research nobody can explain.

**A save supersedes, it never overwrites.** `content.prompt_version` records
which instructions wrote a row, and that is only worth anything if the row they
name still exists. This is the same reason evidence is never deleted.

**`_COMMON` is assembled in `instructions.block`, not here.** This module hands
back a body; the preamble is prepended downstream, where a stored body cannot
displace it.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import PromptTemplate
from app.services.instructions import STAGE

log = logging.getLogger(__name__)


class UnknownScenario(KeyError):
    """A scenario the code does not have a stage for."""


def shipped_default(scenario: str) -> str:
    """The text this installation shipped with — what "reset" restores.

    `STAGE` stopped being what runs when the prompts moved into the database.
    It is kept as the baseline to diff and reset against, which is the whole
    reason it is still in git.
    """
    if scenario not in STAGE:
        raise UnknownScenario(scenario)
    return STAGE[scenario].strip()


def known_scenarios() -> list[str]:
    return sorted(STAGE)


async def active(session: AsyncSession, scenario: str) -> PromptTemplate | None:
    """The live row for one scenario."""
    return (
        await session.execute(
            select(PromptTemplate).where(
                PromptTemplate.scenario == scenario,
                PromptTemplate.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()


async def active_map(session: AsyncSession) -> dict[str, PromptTemplate]:
    """Every live row, keyed by scenario. One query, not sixteen."""
    rows = (
        await session.execute(
            select(PromptTemplate).where(PromptTemplate.is_active.is_(True))
        )
    ).scalars()
    return {row.scenario: row for row in rows}


async def body_and_version(
    session: AsyncSession, scenario: str
) -> tuple[str | None, int | None]:
    """The text to run and the version to stamp on whatever it produces.

    Returns `(None, None)` when no row exists — which should not happen, since
    the migration seeds every scenario, but can if a scenario was added to
    `STAGE` in code without a migration seeding it. The caller then falls back
    to the shipped text rather than failing the run: a new stage that works on
    its shipped instructions is better than a stage that cannot run at all, and
    the warning says what to fix.
    """
    if scenario not in STAGE:
        raise UnknownScenario(scenario)
    row = await active(session, scenario)
    if row is None:
        log.warning(
            "prompts.no_active_row scenario=%s — running the shipped default; "
            "seed it so edits and version stamping work",
            scenario,
        )
        return None, None
    return row.body, row.version


async def history(session: AsyncSession, scenario: str) -> list[PromptTemplate]:
    """Every version of one scenario, newest first."""
    if scenario not in STAGE:
        raise UnknownScenario(scenario)
    return list(
        (
            await session.execute(
                select(PromptTemplate)
                .where(PromptTemplate.scenario == scenario)
                .order_by(PromptTemplate.version.desc())
            )
        ).scalars()
    )


async def save_version(
    session: AsyncSession,
    *,
    scenario: str,
    body: str,
    note: str | None = None,
) -> PromptTemplate:
    """Supersede the live row with a new version.

    Deactivate-then-insert in that order, inside the caller's transaction. The
    partial unique index permits exactly one active row per scenario, so doing
    it the other way round fails the constraint rather than racing — which is
    the behaviour worth having, but it means the order here is load-bearing
    and not merely tidy.
    """
    if scenario not in STAGE:
        raise UnknownScenario(scenario)
    text = body.strip()
    if not text:
        raise ValueError("a prompt cannot be empty")

    current = await active(session, scenario)
    if current is not None:
        if current.body == text:
            # Saving the same words would spend a version number and tell a
            # later reader that something changed on this date. Nothing did.
            return current
        current.is_active = False
        await session.flush()

    highest = (
        await session.scalar(
            select(func.max(PromptTemplate.version)).where(
                PromptTemplate.scenario == scenario
            )
        )
        or 0
    )
    row = PromptTemplate(
        scenario=scenario,
        body=text,
        note=(note or "").strip() or None,
        version=highest + 1,
        is_active=True,
    )
    session.add(row)
    await session.flush()
    log.info(
        "prompts.saved scenario=%s version=%d chars=%d",
        scenario, row.version, len(text),
    )
    return row


async def reset_to_default(
    session: AsyncSession, *, scenario: str, note: str | None = None
) -> PromptTemplate:
    """Restore the shipped text as a new version.

    A new version rather than a deletion of the edits. "We tried it and put it
    back" is a fact about this installation, and discarding the intervening
    versions would make the rows they produced unexplainable.
    """
    return await save_version(
        session,
        scenario=scenario,
        body=shipped_default(scenario),
        note=note or "reset to the shipped default",
    )


async def restore_version(
    session: AsyncSession, *, scenario: str, version: int
) -> PromptTemplate:
    """Bring an old version back as a new one.

    Copied forward rather than reactivated in place. Flipping `is_active` back
    to an old row would leave two different texts having been live under one
    version number, and `content.prompt_version` would no longer identify
    anything.
    """
    if scenario not in STAGE:
        raise UnknownScenario(scenario)
    old = (
        await session.execute(
            select(PromptTemplate).where(
                PromptTemplate.scenario == scenario,
                PromptTemplate.version == version,
            )
        )
    ).scalar_one_or_none()
    if old is None:
        raise ValueError(f"{scenario!r} has no version {version}")
    return await save_version(
        session,
        scenario=scenario,
        body=old.body,
        note=f"restored from version {version}",
    )
