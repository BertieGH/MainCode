"""
Legal-Relevance Guard — the most important guard rail.

Every drafted question runs through this gate. Three layers:

  1. Allowlist (positive): permitted question topics compiled from state UI
     statute + agency SOP. Maintained in `data/allowlist/<state>/allowed.yaml`.
  2. Forbidden list (negative): protected-class, union activity, protected leave
     reasons absent ADA need, political affiliation, etc.
     Maintained in `data/allowlist/<state>/forbidden.yaml`.
  3. Flash classifier: catches paraphrases that aren't on either explicit list.

Verdict carries either:
  - allowed=True with matched_allowlist_ids (logged with the emitted question)
  - allowed=False with forbidden_topic + reason (planner re-plans, never re-tries
    the same draft)
"""
from __future__ import annotations

from ..models import LegalGuardVerdict
from .base import Agent


class LegalRelevanceGuard(Agent):
    name = "legal_relevance_guard"

    def __init__(self, allowed: list[dict] | None = None, forbidden: list[dict] | None = None) -> None:
        super().__init__()
        self.allowed = allowed or []
        self.forbidden = forbidden or []

    async def check(self, drafted_question: str, state_code: str) -> LegalGuardVerdict:
        self._audit("invoke", state_code=state_code, question_len=len(drafted_question))
        # TODO: substring/regex pass over forbidden list — fast reject
        # TODO: substring/regex pass over allowlist for citation IDs
        # TODO: Flash classifier with allowed/forbidden corpus as few-shot
        # When ambiguous: deny by default (fail closed)
        return LegalGuardVerdict(allowed=False, reason="guard not yet implemented; failing closed")
