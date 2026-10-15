"""Common base for all agents — keeps audit + model-call surface uniform."""
from __future__ import annotations

from abc import ABC
from typing import Any

from ..core.audit import audit_event
from ..core.logging import get_logger


class Agent(ABC):
    name: str = "agent"

    def __init__(self) -> None:
        self.log = get_logger(f"agent.{self.name}")

    def _audit(self, event: str, **fields: Any) -> None:
        audit_event(f"agent.{self.name}.{event}", agent=self.name, **fields)
