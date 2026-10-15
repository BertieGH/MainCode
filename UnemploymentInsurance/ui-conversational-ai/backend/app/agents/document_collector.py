"""
Document Collector — requests, ingests, OCRs, and validates supporting docs.

Triggered when the Planner emits NextAction.kind == REQUEST_DOCUMENT.
Calls Vertex Document AI for OCR + structured field extraction; validates
extracted fields against claimant-provided signals (e.g. paystub employer
matches reported employer, paystub period covers week_ending).

Returns enriched signals back into the conversation state.
"""
from __future__ import annotations

from ..models import DocumentRequest, Signal
from .base import Agent


class DocumentCollector(Agent):
    name = "document_collector"

    async def request(self, document_type: str, reason: str) -> DocumentRequest:
        self._audit("request", document_type=document_type)
        return DocumentRequest(document_type=document_type, reason=reason)

    async def ingest(self, document_type: str, file_bytes: bytes, mime_type: str) -> list[Signal]:
        self._audit("ingest", document_type=document_type, mime=mime_type, bytes=len(file_bytes))
        # TODO: Vertex Document AI call — pick processor by document_type.
        # TODO: cross-check extracted fields against existing signals; emit
        #       contradiction FraudSignal upstream if mismatch.
        return []
