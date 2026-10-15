"""
Signal Extractor — pulls structured eligibility slots from a claimant turn.

Distinct from Intent: where Intent says "what kind of thing did they say",
Signal Extractor says "what facts are now known". Each slot carries its own
confidence so the Eligibility Evaluator can weight evidence.

Canonical slots (extend as new states/policies are onboarded):
  hours_worked            : float
  gross_earnings          : float (USD, week)
  employer_name           : str
  separation_reason       : str   (laid_off | quit | fired | reduced_hours | other)
  jobsearch_contacts      : int
  jobsearch_details       : list[{employer, date, method}]
  availability_constraint : str   (none | childcare | medical | transport | other)
  medical_unavailable     : bool
  refused_offer           : bool
  refused_offer_reason    : str
  outside_state_travel    : bool
"""
from __future__ import annotations

from ..models import Intent, Signal
from .base import Agent


class SignalExtractor(Agent):
    name = "signal_extractor"

    async def extract(
        self,
        redacted_turn_text: str,
        intent: Intent,
        turn_index: int,
    ) -> list[Signal]:
        self._audit("invoke", intent=intent.value, turn_index=turn_index)
        # TODO: Flash structured-output call; Pro fallback when confidence < 0.5.
        # Prompt is intent-conditioned so we only ask for the slots that intent implies.
        return []
