from abc import ABC, abstractmethod


class LLMQuotaExceeded(Exception):
    """Raised when the provider returns 429 / RESOURCE_EXHAUSTED.

    The ingestion loop treats this as a "stop the batch" signal — once the
    quota wall is hit, every subsequent call will hit it too, so continuing
    just burns our remaining quota and floods the logs.
    """

    def __init__(self, message: str, retry_after_seconds: int | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class LLMServiceUnavailable(Exception):
    """Raised when the provider returns a 5xx after retries are exhausted.

    Typically Gemini returning 503 UNAVAILABLE during a demand spike. Retrying
    the whole batch minutes later usually succeeds, so we bail the batch the
    same way we do for quota errors.
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    @abstractmethod
    async def extract(self, prompt: str) -> str:
        """Send prompt, return raw text response."""
        ...

    @abstractmethod
    async def test_connection(self) -> bool:
        """Test if the provider is reachable."""
        ...
