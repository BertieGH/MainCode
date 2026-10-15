"""
Claims router — stubs for the human-adjudicator surface.

Endpoints implemented in later milestones:
  GET  /api/claims                    list claims awaiting adjudication, filterable by band
  GET  /api/claims/{id}               get full claim + transcript + report
  POST /api/claims/{id}/decision      adjudicator confirms or overrides; writes to training_records
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("")
async def list_claims() -> dict:
    return {"items": [], "note": "not yet implemented"}
