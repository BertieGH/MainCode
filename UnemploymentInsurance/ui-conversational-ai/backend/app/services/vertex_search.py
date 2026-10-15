"""
Vertex AI Search wrapper — shared by ContextAgent and LegalRelevanceGuard.

Three data stores:
  - policy/SOP corpus      (state statute + agency procedures)
  - question bank          (curated weekly-cert questions)
  - allowlist corpus       (permitted + forbidden topics for the legal guard)
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.config import get_settings


@dataclass
class SearchHit:
    doc_id: str
    title: str
    snippet: str
    score: float
    metadata: dict


class VertexSearch:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def search_policy(self, query: str, k: int = 5) -> list[SearchHit]:
        # TODO: discoveryengine.SearchServiceAsyncClient against
        # settings.vertex_search_data_store_policy
        return []

    async def search_question_bank(self, slot: str, k: int = 5) -> list[SearchHit]:
        # TODO: same client, qbank data store; query is the canonical slot name
        return []

    async def search_allowlist(self, drafted_question: str, k: int = 3) -> list[SearchHit]:
        # TODO: returns matching allowlist entries (and any forbidden matches)
        return []
