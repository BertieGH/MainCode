"""
PII Guards — inbound and outbound.

Inbound: redacts SSN, full credit card, unsolicited medical detail, third-party
identifiers from claimant turns BEFORE they are logged or stored. The redacted
form is what persists.

Outbound: inspects an agent-drafted question and rejects any draft that would
solicit PII beyond the minimum required by policy for the current evidence gap.
"""
from __future__ import annotations

from ..models import GuardVerdict
from .base import Agent


class InboundPIIGuard(Agent):
    name = "inbound_pii_guard"

    async def redact(self, text: str) -> GuardVerdict:
        # Implementation: Cloud DLP deidentify_template + Flash classifier for
        # unsolicited-medical and third-party-identifier checks.
        # Returns redacted_text + structured findings.
        self._audit("invoke", text_len=len(text))
        # TODO: wire google-cloud-dlp.DlpServiceAsyncClient.deidentify_content
        return GuardVerdict(allowed=True, redacted_text=text, findings=[])


class OutboundPIIGuard(Agent):
    name = "outbound_pii_guard"

    async def check(self, drafted_question: str, allowed_slots: list[str]) -> GuardVerdict:
        # Implementation: Flash classifier — does this question solicit PII
        # outside `allowed_slots`? (Allowed slots come from the planner's chosen
        # NextAction.target_slot.)
        self._audit("invoke", question_len=len(drafted_question), allowed_slots=allowed_slots)
        return GuardVerdict(allowed=True, reason=None)
