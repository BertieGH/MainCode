from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class JobPromptProfileCreate(BaseModel):
    name: str
    extract_prompt: str = ""
    match_prompt: str = ""
    classify_prompt: str = ""


class JobPromptProfileUpdate(BaseModel):
    name: str | None = None
    extract_prompt: str | None = None
    match_prompt: str | None = None
    classify_prompt: str | None = None


class JobPromptProfileOut(BaseModel):
    id: UUID
    name: str
    extract_prompt: str
    match_prompt: str
    classify_prompt: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
