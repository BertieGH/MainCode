import asyncio
import re

from google import genai
from google.genai import errors as genai_errors

from app.services.llm_provider import LLMProvider, LLMQuotaExceeded, LLMServiceUnavailable


# Retry 5xx up to N times with exponential backoff. 503s during demand spikes
# are usually resolved within 5-10 seconds. Total attempts = len(delays) + 1
# (initial call + each retry). Currently 3 attempts: 1 initial + 2 retries
# with 1s and 3s backoff. Keeps a single failed article's retry budget at ~4s
# so a sustained Gemini outage produces fast `service_unavailable` flips
# rather than minute-long hangs per article.
_SERVER_RETRY_DELAYS = (1, 3)  # seconds — 2 retries → 3 total attempts


def _retry_seconds_from_error(err: genai_errors.APIError) -> int | None:
    """Best-effort: pull the retry-after seconds out of a 429 error payload."""
    details = getattr(err, "details", None)
    candidates: list[dict] = []
    if isinstance(details, dict):
        candidates.append(details)
        for v in details.values():
            if isinstance(v, list):
                candidates.extend(x for x in v if isinstance(x, dict))
            elif isinstance(v, dict):
                candidates.append(v)

    for d in candidates:
        if isinstance(d.get("retryDelay"), str):
            m = re.match(r"(\d+)", d["retryDelay"])
            if m:
                return int(m.group(1))
        if isinstance(d.get("retry_delay"), dict) and "seconds" in d["retry_delay"]:
            try:
                return int(d["retry_delay"]["seconds"])
            except (TypeError, ValueError):
                pass

    # Fallback: regex the stringified message ("retry_delay { seconds: 19 }" form)
    m = re.search(r"retry_delay\s*{?\s*seconds:\s*(\d+)", str(err))
    if m:
        return int(m.group(1))
    return None


def _translate(err: Exception) -> Exception:
    """Convert a google-genai error into our domain exception when applicable."""
    if isinstance(err, genai_errors.APIError):
        code = getattr(err, "code", None)
        if code == 429:
            return LLMQuotaExceeded(str(err), retry_after_seconds=_retry_seconds_from_error(err))
        if isinstance(code, int) and 500 <= code < 600:
            return LLMServiceUnavailable(str(err), status_code=code)
    return err


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", tier: str = "free"):
        self.api_key = api_key
        self.model_name = model
        # "free" → bail the batch on the first 429 (free tier RPD is small, so
        # burning more requests is wasted). "paid" → treat 429 as a transient
        # burst and retry with backoff like 5xx, since paid 429s usually clear in seconds.
        self.tier = tier if tier in ("free", "paid") else "free"
        self.client = genai.Client(api_key=api_key)

    async def _call_with_retry(self, contents: str) -> str:
        """Call generate_content, retrying transient 5xx with exponential backoff.

        Paid tier: 429 is also retried with backoff. Free tier: 429 raises
        LLMQuotaExceeded immediately so the caller can stop the batch.
        """
        last_server_error: Exception | None = None
        for attempt in range(len(_SERVER_RETRY_DELAYS) + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name, contents=contents,
                )
                return response.text or ""
            except Exception as e:
                code = (
                    getattr(e, "code", None)
                    if isinstance(e, genai_errors.APIError) else None
                )
                # 429: paid tier retries with backoff; free tier bails immediately.
                if code == 429:
                    if self.tier == "paid" and attempt < len(_SERVER_RETRY_DELAYS):
                        last_server_error = e
                        await asyncio.sleep(_SERVER_RETRY_DELAYS[attempt])
                        continue
                    raise _translate(e) from e
                # 5xx: retry with backoff unless we're out of attempts.
                if (
                    isinstance(code, int)
                    and 500 <= code < 600
                    and attempt < len(_SERVER_RETRY_DELAYS)
                ):
                    last_server_error = e
                    await asyncio.sleep(_SERVER_RETRY_DELAYS[attempt])
                    continue
                # Anything else (4xx != 429, or 5xx after final retry) — translate + raise.
                translated = _translate(e)
                if translated is not e:
                    raise translated from e
                raise
        # Should be unreachable but keeps type checker happy
        raise LLMServiceUnavailable(
            f"Gemini 5xx/429 persisted after {len(_SERVER_RETRY_DELAYS)} retries: {last_server_error}",
            status_code=getattr(last_server_error, "code", None),
        )

    async def extract(self, prompt: str) -> str:
        return await self._call_with_retry(prompt)

    async def test_connection(self) -> bool:
        response_text = await self._call_with_retry("Reply with the word OK")
        return "OK" in (response_text or "").upper()
