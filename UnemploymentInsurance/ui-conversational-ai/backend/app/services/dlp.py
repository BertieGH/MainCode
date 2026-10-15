"""
Cloud DLP wrapper — used by the inbound PII guard.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.config import get_settings


@dataclass
class DLPResult:
    redacted_text: str
    findings: list[dict]


class DLPClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def deidentify(self, text: str) -> DLPResult:
        # TODO: google.cloud.dlp_v2.DlpServiceAsyncClient.deidentify_content
        # with settings.dlp_deidentify_template + inspect_template.
        return DLPResult(redacted_text=text, findings=[])
