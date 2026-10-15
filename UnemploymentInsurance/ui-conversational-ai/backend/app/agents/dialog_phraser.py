"""
Dialog / Phraser — turns the Planner's structured NextAction into a natural,
conversational, legally-safe question or statement.

Flash. Constrained by:
  - target_slot from NextAction (must drive the question toward that slot)
  - allowlist citation IDs (must NOT contradict permitted topics)
  - tone profile (warm, plain English, 8th-grade reading level by default)

Output is always passed to the Legal-Relevance Guard before reaching the
claimant; if guard blocks, control returns to the Planner for replanning.
"""
from __future__ import annotations

from ..models import NextAction
from .base import Agent


class DialogPhraser(Agent):
    name = "dialog_phraser"

    async def phrase(self, action: NextAction, prior_turn_text: str | None = None) -> str:
        self._audit("invoke", kind=action.kind.value, target_slot=action.target_slot)
        # TODO: Flash call with action + prior_turn_text in prompt.
        # Few-shot examples per NextActionKind.
        return action.instruction
