"""A rep pastes what they saw: a LinkedIn post, a profile line, a comment.

LinkedIn is the one place research may not read — it forbids automated access —
and the place a rep reads every day. So what a rep saw there comes in the way
a person brings it: pasted, attributed, and dated.

Stored as `manual` evidence, which the table requires to say who logged it and
how. There is no sign-in yet, so the author is "rep", as research runs are
triggered by "rep". The date is the one given, or the one written into a
LinkedIn post's URL, or none — never today's.

Nothing is concluded here. The passage is read into signals on the next
Re-read & score, the same as any other, and the text is data: an instruction
inside a pasted post is a quoted instruction, never one followed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.api.intelligence import EvidenceOut, _evidence_out
from app.models.account import Account, Contact
from app.models.signal import Evidence
from app.services import linkedin
from app.services.evidence import excerpt_hash, source_hash

router = APIRouter(tags=["evidence"])

#: What a rep's own reading is worth: first-hand, but unverifiable.
PASTED_RELIABILITY = 0.8


class PasteIn(BaseModel):
    text: str = Field(min_length=10, max_length=5000)
    #: Where it was seen. A LinkedIn post link also dates it.
    url: str | None = Field(default=None, max_length=2000)
    #: Who it is about. Absent means the company.
    contact_id: uuid.UUID | None = None
    #: When it was posted, when the rep knows and the link does not say.
    observed_at: date | None = None

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("paste at least a sentence")
        return value

    @field_validator("url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not value.startswith(("https://", "http://")):
            raise ValueError("the link must start with https://")
        return value


class PasteOut(BaseModel):
    evidence: EvidenceOut
    #: `given`, `post link`, or `unknown` — so the screen can say where the
    #: date came from rather than presenting a decoded one as typed.
    dated_from: str


@router.post(
    "/accounts/{account_id}/pasted-evidence", response_model=PasteOut, status_code=201
)
async def paste_evidence(
    account_id: uuid.UUID, payload: PasteIn, session: AsyncSession = Depends(get_session)
):
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "account not found")
    if payload.contact_id is not None:
        contact = await session.get(Contact, payload.contact_id)
        if contact is None or contact.account_id != account.id:
            # Filing a post under a person at another company is exactly the
            # wrong-person mistake research is built to refuse.
            raise HTTPException(422, "that contact is not at this account")

    from_link = linkedin.post_date(payload.url)
    observed = payload.observed_at or from_link
    dated_from = "given" if payload.observed_at else ("post link" if from_link else "unknown")
    if observed and observed > datetime.now(UTC).date():
        raise HTTPException(422, "that date is in the future")

    key = excerpt_hash(payload.url, payload.text)
    held = (
        await session.execute(
            select(Evidence.id).where(Evidence.account_id == account.id, Evidence.excerpt_hash == key)
        )
    ).scalar_one_or_none()
    if held is not None:
        raise HTTPException(409, "this passage is already stored for this account")

    row = Evidence(
        account_id=account.id,
        contact_id=payload.contact_id,
        family="manual",
        source_type="manual",
        source_url=payload.url,
        source_name="LinkedIn, pasted by a rep" if linkedin.is_linkedin(payload.url) else "Pasted by a rep",
        excerpt=payload.text,
        observed_at=observed,
        author_id="rep",
        capture_method="other",
        source_hash=source_hash(payload.url, None),
        excerpt_hash=key,
        raw_status="unavailable",
        reliability=PASTED_RELIABILITY,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return PasteOut(evidence=_evidence_out(row), dated_from=dated_from)
