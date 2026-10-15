"""
Intent Analyzer — maps a free-text claimant turn to one canonical Intent.

Cheap Gemini Flash classifier. Multi-intent turns return the dominant one;
secondary intents land in Signal Extractor anyway. Confidence below threshold
returns Intent.UNKNOWN so the planner can decide to clarify.
"""
from __future__ import annotations

from ..models import Intent
from .base import Agent


class IntentAnalyzer(Agent):
    name = "intent_analyzer"

    async def analyze(self, redacted_turn_text: str) -> tuple[Intent, float]:
        self._audit("invoke", text_len=len(redacted_turn_text))
        # TODO: Flash call with structured-output JSON schema {intent, confidence}.
        return Intent.UNKNOWN, 0.0
