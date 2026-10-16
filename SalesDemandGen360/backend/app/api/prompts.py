"""The prompt editor's routes.

Reads are open; writes need the gate. Seeing a prompt is not the risk —
changing one quietly is, because every artefact produced afterwards means
something different and nothing on the screen would say so.

Its own router rather than more of `config.py`, which is already two thousand
lines and answers a dozen unrelated questions.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.api.auth import current_user
from app.models.identity import User
from app.services import admin_gate, instructions, prompt_export, prompts

router = APIRouter(prefix="/config", tags=["prompts"])


# --------------------------------------------------------------------------
# contracts
# --------------------------------------------------------------------------
class AdminUnlockIn(BaseModel):
    password: str


class AdminPasswordIn(BaseModel):
    password: str
    #: Required once one is set. Absent on first run, when there is nothing to
    #: authenticate against yet.
    current_password: str | None = None


class PromptIn(BaseModel):
    body: str = Field(min_length=1)
    #: Why, in the editor's words. "Which instructions wrote this?" is
    #: answerable from the version; "why were they changed?" only if someone
    #: said.
    note: str | None = Field(default=None, max_length=500)


class PromptSummaryOut(BaseModel):
    scenario: str
    version: int | None
    differs_from_default: bool
    note: str | None
    updated_at: datetime | None
    chars: int
    #: False when no row exists for a scenario the code has — a stage added
    #: without a migration to seed it. It runs on its shipped text; the screen
    #: should say so rather than imply it is edited.
    seeded: bool


class PromptVersionOut(BaseModel):
    version: int
    is_active: bool
    note: str | None
    created_at: datetime
    chars: int
    body: str


class PromptDetailOut(BaseModel):
    scenario: str
    body: str
    version: int | None
    note: str | None
    updated_at: datetime | None
    shipped_default: str
    differs_from_default: bool
    #: Shown so the admin can see what their text sits beneath. Read-only
    #: everywhere, including here: it carries invariant 10, and a screen that
    #: let someone delete the prompt-injection guard would be a hole rather
    #: than a feature.
    common_preamble: str
    seeded: bool


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------
async def _require_gate(session: AsyncSession, token: str | None, user: User | None = None) -> None:
    """Refuse a write unless the caller unlocked recently — or is signed in.

    A signed-in caller reached here only because the role grid gave them edit
    on Model & Prompts (`require_user`), which is the decision this password
    stood in for before there were people. The password still guards anonymous
    callers, until phase 3 makes there be none (`docs/17`).

    A 409 when no password is set rather than a 401: "you got it wrong" and
    "there is nothing to get right yet" need different words, because they need
    different actions from whoever reads them.
    """
    if user is not None:
        return
    if not await admin_gate.is_configured(session):
        raise HTTPException(
            409, "no admin password is set — set one before editing prompts"
        )
    if not admin_gate.token_is_valid(token):
        raise HTTPException(401, "unlock with the admin password first")


@router.get("/prompts/gate")
async def gate_state(session: AsyncSession = Depends(get_session)):
    """Whether a password exists. Says nothing about what it is."""
    return {
        "configured": await admin_gate.is_configured(session),
        "token_header": admin_gate.TOKEN_HEADER,
        "ttl_seconds": admin_gate.TOKEN_TTL_SECONDS,
        "min_password_length": admin_gate.MIN_PASSWORD_LENGTH,
    }


@router.post("/prompts/gate")
async def set_password(
    payload: AdminPasswordIn,
    session: AsyncSession = Depends(get_session),
):
    """Set the password, or change it.

    First run needs no token — there is nothing to authenticate against yet,
    and refusing would lock the owner out of their own installation with no way
    back short of a database edit. Every change afterwards needs the current
    one.
    """
    if await admin_gate.is_configured(session):
        if not payload.current_password or not await admin_gate.verify(
            session, payload.current_password
        ):
            raise HTTPException(401, "the current password is wrong")
    try:
        await admin_gate.set_password(session, payload.password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await session.commit()
    # Issued straight away, so setting a password does not then require typing
    # it again to use the screen it just unlocked.
    return {"token": admin_gate.issue_token(), "ttl_seconds": admin_gate.TOKEN_TTL_SECONDS}


@router.post("/prompts/unlock")
async def unlock(
    payload: AdminUnlockIn, session: AsyncSession = Depends(get_session)
):
    if not await admin_gate.is_configured(session):
        raise HTTPException(409, "no admin password is set")
    if not await admin_gate.verify(session, payload.password):
        # One message for a wrong password, with nothing in it that narrows
        # down the right one.
        raise HTTPException(401, "wrong password")
    return {
        "token": admin_gate.issue_token(),
        "ttl_seconds": admin_gate.TOKEN_TTL_SECONDS,
    }


# --------------------------------------------------------------------------
# the prompts
# --------------------------------------------------------------------------
@router.get("/prompts", response_model=list[PromptSummaryOut])
async def list_prompts(session: AsyncSession = Depends(get_session)):
    """Every stage, with whether anyone has changed it.

    `differs_from_default` is the first question a new admin asks — "what have
    we changed?" — and answering it here saves the screen from holding sixteen
    shipped texts to compare against.
    """
    live = await prompts.active_map(session)
    out: list[PromptSummaryOut] = []
    for scenario in prompts.known_scenarios():
        row = live.get(scenario)
        default = prompts.shipped_default(scenario)
        out.append(
            PromptSummaryOut(
                scenario=scenario,
                version=row.version if row else None,
                differs_from_default=bool(row and row.body.strip() != default),
                note=row.note if row else None,
                updated_at=row.updated_at if row else None,
                chars=len(row.body) if row else len(default),
                seeded=row is not None,
            )
        )
    return out


# Declared **before** `/prompts/{scenario}`: FastAPI matches routes in
# declaration order, so the other way round "export" arrives as a scenario name
# and the download 404s.
@router.get("/prompts/export")
async def export_prompts(session: AsyncSession = Depends(get_session)):
    """Every instruction the models receive, as one Word document.

    Open, like the other reads. The preamble and the stage bodies are all
    visible on the screen already; collecting them into a file changes how
    convenient they are to review, not who can see them.
    """
    data = await prompt_export.export(session)
    return Response(
        content=data,
        media_type=prompt_export.MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{prompt_export.FILENAME}"',
            # The browser is fetching this through `HttpClient`, which cannot
            # read a header the server does not expose. Without this the
            # filename is unreachable and the download lands as "download".
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/prompts/{scenario}", response_model=PromptDetailOut)
async def read_prompt(scenario: str, session: AsyncSession = Depends(get_session)):
    try:
        default = prompts.shipped_default(scenario)
    except KeyError as exc:
        raise HTTPException(404, f"no stage named {scenario!r}") from exc
    row = await prompts.active(session, scenario)
    return PromptDetailOut(
        scenario=scenario,
        body=row.body if row else default,
        version=row.version if row else None,
        note=row.note if row else None,
        updated_at=row.updated_at if row else None,
        shipped_default=default,
        differs_from_default=bool(row and row.body.strip() != default),
        common_preamble=instructions.COMMON,
        seeded=row is not None,
    )


@router.get("/prompts/{scenario}/history", response_model=list[PromptVersionOut])
async def prompt_history(scenario: str, session: AsyncSession = Depends(get_session)):
    try:
        rows = await prompts.history(session, scenario)
    except KeyError as exc:
        raise HTTPException(404, f"no stage named {scenario!r}") from exc
    return [
        PromptVersionOut(
            version=r.version,
            is_active=r.is_active,
            note=r.note,
            created_at=r.created_at,
            chars=len(r.body),
            body=r.body,
        )
        for r in rows
    ]


@router.post("/prompts/{scenario}", response_model=PromptDetailOut)
async def save_prompt(
    scenario: str,
    payload: PromptIn,
    session: AsyncSession = Depends(get_session),
    x_admin_token: str | None = Header(default=None, alias=admin_gate.TOKEN_HEADER),
    user: User | None = Depends(current_user),
):
    """Supersede the live text with a new version."""
    await _require_gate(session, x_admin_token, user)
    try:
        await prompts.save_version(
            session, scenario=scenario, body=payload.body, note=payload.note
        )
    except KeyError as exc:
        raise HTTPException(404, f"no stage named {scenario!r}") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await session.commit()
    return await read_prompt(scenario, session)


@router.post("/prompts/{scenario}/reset", response_model=PromptDetailOut)
async def reset_prompt(
    scenario: str,
    session: AsyncSession = Depends(get_session),
    x_admin_token: str | None = Header(default=None, alias=admin_gate.TOKEN_HEADER),
    user: User | None = Depends(current_user),
):
    """Restore the shipped text — as a new version, not by deleting the edits."""
    await _require_gate(session, x_admin_token, user)
    try:
        await prompts.reset_to_default(session, scenario=scenario)
    except KeyError as exc:
        raise HTTPException(404, f"no stage named {scenario!r}") from exc
    await session.commit()
    return await read_prompt(scenario, session)


@router.post("/prompts/{scenario}/restore/{version}", response_model=PromptDetailOut)
async def restore_prompt(
    scenario: str,
    version: int,
    session: AsyncSession = Depends(get_session),
    x_admin_token: str | None = Header(default=None, alias=admin_gate.TOKEN_HEADER),
    user: User | None = Depends(current_user),
):
    """Bring an old version back, copied forward as a new one."""
    await _require_gate(session, x_admin_token, user)
    try:
        await prompts.restore_version(session, scenario=scenario, version=version)
    except KeyError as exc:
        raise HTTPException(404, f"no stage named {scenario!r}") from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await session.commit()
    return await read_prompt(scenario, session)
