from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agents.orchestrator import Orchestrator
from ..models import AdjudicatorReport, ConversationState

router = APIRouter()

# In-memory store for POC; replace with Firestore once GCP is wired.
_CONVERSATIONS: dict[str, ConversationState] = {}
_orch = Orchestrator()


class StartRequest(BaseModel):
    claim_id: str
    week_ending: str
    state_code: str


class StartResponse(BaseModel):
    conversation_id: str
    opening_message: str


class TurnRequest(BaseModel):
    text: str


class TurnResponse(BaseModel):
    reply: str | None
    closed: bool
    status: str


@router.post("/start", response_model=StartResponse)
async def start_conversation(req: StartRequest) -> StartResponse:
    conv_id = str(uuid.uuid4())
    state = ConversationState(
        conversation_id=conv_id,
        claim_id=req.claim_id,
        week_ending=req.week_ending,
        state_code=req.state_code,
        started_at=datetime.now(timezone.utc),
    )
    _CONVERSATIONS[conv_id] = state
    # Opening message is fixed and human-reviewed; not generated.
    opening = (
        "Hi — I'm going to ask you a few questions about your unemployment certification "
        f"for the week ending {req.week_ending}. Your answers help us process your claim. "
        "Let's start: did you do any work last week, even part-time or self-employment?"
    )
    return StartResponse(conversation_id=conv_id, opening_message=opening)


@router.post("/{conversation_id}/turn", response_model=TurnResponse)
async def post_turn(conversation_id: str, req: TurnRequest) -> TurnResponse:
    state = _CONVERSATIONS.get(conversation_id)
    if state is None:
        raise HTTPException(404, "conversation not found")
    if state.status != "active":
        raise HTTPException(409, f"conversation status is {state.status}")

    state, reply, closed = await _orch.handle_turn(state, req.text)
    _CONVERSATIONS[conversation_id] = state
    return TurnResponse(reply=reply, closed=closed, status=state.status)


@router.post("/{conversation_id}/close", response_model=AdjudicatorReport)
async def close_conversation(conversation_id: str) -> AdjudicatorReport:
    state = _CONVERSATIONS.get(conversation_id)
    if state is None:
        raise HTTPException(404, "conversation not found")
    report = await _orch.finalize(state)
    state.status = "closed"
    state.closed_at = datetime.now(timezone.utc)
    return report


@router.get("/{conversation_id}", response_model=ConversationState)
async def get_conversation(conversation_id: str) -> ConversationState:
    state = _CONVERSATIONS.get(conversation_id)
    if state is None:
        raise HTTPException(404, "conversation not found")
    return state
