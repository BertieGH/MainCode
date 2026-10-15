"""
Vertex Document AI wrapper — used by DocumentCollector.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.config import get_settings


@dataclass
class DocAIResult:
    extracted: dict
    raw_text: str
    confidence: float


class DocumentAI:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def process(self, document_type: str, content: bytes, mime_type: str) -> DocAIResult:
        # TODO: google.cloud.documentai.DocumentProcessorServiceAsyncClient.process_document
        # processor selected by document_type (paystub vs separation_letter).
        return DocAIResult(extracted={}, raw_text="", confidence=0.0)
