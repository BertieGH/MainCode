import json
import logging
import re
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.signal import Signal
from app.services.llm_provider import LLMProvider, LLMQuotaExceeded, LLMServiceUnavailable
from app.services.llm_gemini import GeminiProvider
from app.services.llm_ollama import OllamaProvider

logger = logging.getLogger(__name__)

DEFAULT_EXTRACTION_PROMPT = """You are extracting structured funding data from a news article.
Read the FULL article carefully — do not stop at the title or first sentence.

Your bias: if the article clearly describes a company raising money, ALWAYS
extract it. Don't reject a real funding story just because one field is uncertain
— partial data is better than no data.

Return ONLY a valid JSON object with these fields:

- company_name: The FULL official name of the company that raised funding, as
  written in the article body. Prefer the long form (e.g. "Anthropic PBC",
  "OpenAI, Inc.", "Stripe, Inc."), not the stock ticker, abbreviation, or bare
  domain. If the article describes a parent/subsidiary relationship, use the
  entity that actually received the funding. If only a short form is given
  (e.g. just "Stripe"), use that — do NOT return is_funding: false for this.

- funding_round: Exactly one of: Pre-Seed, Seed, Series A, Series B, Series C,
  Series D, Growth, Other. Use "Other" if the article mentions funding but the
  round type is unclear (bridge, extension, strategic, debt, etc.).

- amount: The funding amount in USD as a plain integer (e.g. 5000000 for $5M,
  120000000 for $120M). Convert from other currencies if mentioned. Use 0 if
  the article doesn't state an amount — still extract the signal.

- industry: Exactly one of: AI, Fintech, SaaS, Cybersecurity, HealthTech, EdTech,
  CleanTech, Other. Pick the closest match based on the company's product, not the
  investor's focus. Use "Other" if unclear.

- location: The company's HEADQUARTERS as the most specific format available.
  Prefer "City, State/Region, Country" (e.g. "San Francisco, CA, USA",
  "London, England, UK", "Bengaluru, Karnataka, India", "Berlin, Germany").
  Look in the article body for phrases like "based in", "headquartered in",
  "{{city}}-based startup", or a dateline. Do NOT use the investor's location
  or the article publisher's location. If the article doesn't mention a location,
  return an empty string "" — do NOT reject the article for this.

- date: YYYY-MM-DD. Use the announcement date if stated, otherwise today.

ONLY return {{"is_funding": false}} when the article is genuinely not about a
company raising investment capital — e.g. product launches, acquisitions, hires,
opinion pieces, earnings reports, or new VC fund-vehicle launches (where a VC
firm raises a fund, not a startup raising from VCs). If there is ANY funding
announcement in the article, extract it.

Article title: {title}
Article text: {text}

Return ONLY the JSON object — no markdown fences, no explanation, no preamble."""


def _llm_article_budget() -> int:
    """Current per-article char budget sent to the LLM, clamped to [500, 30000]."""
    raw = getattr(settings, "llm_article_char_budget", 3500) or 3500
    return max(500, min(30000, int(raw)))


def _resolve_prompt(title: str, text: str) -> str:
    """Build the extraction prompt using the user-configured template if set.

    Falls back to DEFAULT_EXTRACTION_PROMPT if the template is empty or
    missing the required {title}/{text} placeholders.
    """
    template = (settings.extraction_prompt or "").strip() or DEFAULT_EXTRACTION_PROMPT
    budget = _llm_article_budget()
    try:
        return template.format(title=title, text=text[:budget])
    except (KeyError, IndexError) as e:
        logger.warning(
            "Custom extraction_prompt failed to format (%s); falling back to default.", e,
        )
        return DEFAULT_EXTRACTION_PROMPT.format(title=title, text=text[:budget])


def _active_gemini_key() -> str:
    """Return the API key for the active Gemini tier.

    Paid tier prefers gemini_paid_api_key but falls back to gemini_api_key
    so users with a single key keep working even if they flip the toggle.
    """
    if settings.gemini_tier == "paid":
        return settings.gemini_paid_api_key or settings.gemini_api_key
    return settings.gemini_api_key


def get_primary_provider() -> LLMProvider | None:
    """Get the user's configured LLM provider."""
    if settings.llm_provider == "gemini":
        key = _active_gemini_key()
        if not key:
            return None
        return GeminiProvider(key, settings.gemini_model, tier=settings.gemini_tier)
    elif settings.llm_provider == "ollama":
        return OllamaProvider(settings.ollama_host, settings.ollama_model)
    return None


def get_secondary_provider() -> LLMProvider | None:
    """Get the fallback LLM provider."""
    if settings.llm_provider == "gemini":
        return OllamaProvider(settings.ollama_host, settings.ollama_model)
    elif settings.llm_provider == "ollama":
        key = _active_gemini_key()
        if key:
            return GeminiProvider(key, settings.gemini_model, tier=settings.gemini_tier)
    return None


_BOT_CHALLENGE_MARKERS = (
    "performing security verification",
    "enable javascript and cookies to continue",
    "checking your browser",
    "cloudflare",
    "attention required",
    "access to this page has been denied",
    "please verify you are human",
    "just a moment",
    "ddos protection by",
)


def _looks_like_bot_challenge(text: str) -> bool:
    """True if the fetched body is a bot-challenge / captcha shell, not a real article."""
    if not text:
        return False
    t = text.lower()
    if any(marker in t for marker in _BOT_CHALLENGE_MARKERS):
        return True
    return False


def _clean_body_text(html: str) -> str:
    """Strip navigation/script/style noise from HTML and return readable body text.

    Returns an empty string if the result is obviously a bot-challenge page —
    feeding that text to the LLM poisons extraction.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    article = (
        soup.find("article")
        or soup.find("main")
        or soup.find("div", class_=re.compile("content|article|post|story", re.I))
        or soup.find("div", id=re.compile("content|article|post|story", re.I))
    )
    container = article or soup.body or soup
    text = container.get_text(separator=" ", strip=True)
    if _looks_like_bot_challenge(text):
        logger.debug("Discarding bot-challenge shell text (%d chars)", len(text))
        return ""
    return text


async def _fetch_via_httpx(url: str) -> str:
    """Plain HTTP fetch — works for most direct article URLs, fails on JS redirects."""
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                },
            )
        if resp.status_code < 400:
            return _clean_body_text(resp.text)
    except Exception as e:
        logger.debug(f"httpx fetch failed for {url}: {e}")
    return ""


async def _fetch_via_playwright(url: str) -> str:
    """Chromium-rendered fetch — resolves JS-based redirects (e.g. Google News).

    Waits for the navigation to settle on the real destination URL, then returns
    the final page's cleaned body text.
    """
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                # Some redirect shells need a network-idle moment to swap URL
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                html = await page.content()
            finally:
                await browser.close()
            return _clean_body_text(html)
    except Exception as e:
        logger.debug(f"Playwright fetch failed for {url}: {e}")
    return ""


def _is_redirect_shell(url: str, body_text: str) -> bool:
    """Best-effort detection of JS-redirect pages (Google News etc.)."""
    host = url.lower()
    if "news.google.com" in host:
        return True
    # Heuristic: very short body on a URL that usually has an article
    if len(body_text) < 400:
        return True
    return False


async def resolve_article_content(url: str, summary: str) -> str:
    """Get article content for the LLM.

    Tries httpx first (fast). If the URL is a known JS-redirect page (Google News)
    or httpx returned essentially nothing, falls back to Playwright/Chromium,
    which can follow the redirect to the real article. Combines summary + body
    so the LLM sees both the RSS snippet and the real article text.
    """
    summary = (summary or "").strip()

    body_text = await _fetch_via_httpx(url)

    if _is_redirect_shell(url, body_text):
        pw_text = await _fetch_via_playwright(url)
        if len(pw_text) > len(body_text):
            body_text = pw_text

    # Combine summary + body so the LLM sees both context and detail.
    # Cap so the prompt-builder isn't starved: at least 5000 chars, or the
    # user-configured LLM budget if it's higher.
    if summary and body_text:
        if body_text[:200].strip() == summary[:200].strip():
            combined = body_text
        else:
            combined = f"{summary}\n\n{body_text}"
    elif body_text:
        combined = body_text
    else:
        combined = summary

    return combined[: max(5000, _llm_article_budget())]


def parse_llm_response(text: str) -> dict | None:
    """Parse LLM JSON response, handling markdown code blocks."""
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the response
        match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def validate_extracted_data(data: dict) -> dict | None:
    """Validate and normalize extracted funding data."""
    if data.get("is_funding") is False:
        return None  # Not a funding article

    company = data.get("company_name", "").strip()
    funding_round = data.get("funding_round", "").strip()
    if not company or not funding_round:
        return None

    amount = data.get("amount", 0)
    if isinstance(amount, str):
        amount = int(re.sub(r"[^\d]", "", amount) or "0")
    if amount < 0 or amount > 10_000_000_000:
        amount = 0

    try:
        d = data.get("date", "")
        parsed_date = datetime.strptime(d, "%Y-%m-%d").date() if d else date.today()
    except (ValueError, TypeError):
        parsed_date = date.today()

    return {
        "company_name": company[:255],
        "funding_round": funding_round[:50],
        "amount": amount,
        "industry": data.get("industry", "Other")[:100],
        "location": data.get("location", "")[:255],
        "date": parsed_date,
    }


async def extract_signal_from_article(
    article: dict, provider: LLMProvider, fallback: LLMProvider | None = None
) -> tuple[dict | None, str, str | None]:
    """Extract funding data from a single article.

    Returns ``(data, verdict, raw_response)``:
      * ``data`` — validated signal dict if extraction succeeded, else None
      * ``verdict`` — one of: funding | not_funding | parse_failed | validation_failed | error
      * ``raw_response`` — the raw LLM output (or error string), useful for the News Log
    """
    title = article.get("title", "")
    text = await resolve_article_content(article.get("url", ""), article.get("summary", ""))

    if not title and not text:
        return None, "error", "empty article (no title and no text)"

    prompt = _resolve_prompt(title, text)

    last_response: str | None = None
    last_error: str | None = None

    async def _run(p: LLMProvider) -> tuple[dict | None, str, str | None]:
        nonlocal last_response, last_error
        for attempt in range(2):
            try:
                response = await p.extract(prompt)
                last_response = response
                data = parse_llm_response(response)
                if data is None:
                    return None, "parse_failed", response
                validated = validate_extracted_data(data)
                if validated is None:
                    # is_funding=false OR missing required fields
                    if data.get("is_funding") is False:
                        return None, "not_funding", response
                    return None, "validation_failed", response
                validated["source_url"] = article.get("url", "")
                validated["source_title"] = title[:512]
                validated["raw_text"] = text[:5000]
                return validated, "funding", response
            except (LLMQuotaExceeded, LLMServiceUnavailable):
                raise
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(f"LLM extraction attempt {attempt + 1} failed: {e}")
                continue
        return None, "error", last_error

    try:
        result = await _run(provider)
        if result[1] != "error" or fallback is None:
            return result
    except (LLMQuotaExceeded, LLMServiceUnavailable):
        raise

    # Fallback path — only on hard error from primary
    try:
        return await _run(fallback)
    except (LLMQuotaExceeded, LLMServiceUnavailable):
        raise
    except Exception as e:
        logger.error(f"Fallback LLM also failed: {e}")
        return None, "error", f"primary: {last_error}; fallback: {type(e).__name__}: {e}"


async def extract_for_article_row(db: AsyncSession, article, force: bool = False) -> tuple[str, str | None, "Signal | None"]:
    """Run extraction on an already-persisted Article row.

    Updates the Article in place with the new verdict + LLM response, creates
    a Signal if funding was extracted, and returns (verdict, llm_response, signal).
    Used by the manual "Extract" buttons in the News Log.

    By default, if a Signal already exists for this URL we skip the LLM and just
    re-link the Article. Pass force=True to re-run the LLM; when a Signal already
    exists we UPDATE it in place (instead of delete+insert) to preserve any
    Prospect rows that reference it via signal_id.
    """
    provider = get_primary_provider()
    fallback = get_secondary_provider()
    if provider is None:
        article.verdict = "error"
        article.llm_response = "No LLM provider configured. Set API key in settings."
        await db.commit()
        return article.verdict, article.llm_response, None

    article_dict = {
        "url": article.url,
        "title": article.title,
        "summary": article.summary or "",
        "published": article.published or "",
    }

    existing_signal_q = await db.execute(select(Signal).where(Signal.source_url == article.url))
    existing = existing_signal_q.scalar_one_or_none()

    if existing is not None and not force:
        # Already extracted — relink article without re-running the LLM
        article.verdict = "funding"
        article.signal_id = existing.id
        await db.commit()
        return article.verdict, article.llm_response, existing

    # Run the LLM
    data, verdict, raw = await extract_signal_from_article(article_dict, provider, fallback)
    article.verdict = verdict
    article.llm_response = (raw[:8000] if raw else None)

    signal: Signal | None = None
    if data:
        if existing is not None:
            # Force re-extract + still a funding article → update in place
            existing.company_name = data["company_name"]
            existing.industry = data["industry"]
            existing.funding_round = data["funding_round"]
            existing.amount = data["amount"]
            existing.location = data["location"]
            existing.date = data["date"]
            existing.source_title = data["source_title"]
            existing.raw_text = data["raw_text"]
            existing.extraction_status = "complete"
            article.signal_id = existing.id
            signal = existing
        else:
            signal = await save_signal(db, data)
            article.signal_id = signal.id
    elif existing is not None:
        # Force re-extract flipped the verdict to not_funding / parse_failed / etc.
        # Leave the old Signal alone (a Prospect may reference it) and just
        # update the article. The stale Signal stays visible in Signal Log with
        # a note in logs; the user can delete it manually from the Prospect list
        # if they want to act on the new verdict.
        logger.warning(
            "Re-extract on article %s flipped from funding to %s; keeping existing Signal %s to avoid FK violation.",
            article.id, verdict, existing.id,
        )

    await db.commit()
    return verdict, article.llm_response, signal


async def save_signal(db: AsyncSession, data: dict) -> Signal:
    """Save extracted signal to database."""
    signal = Signal(
        company_name=data["company_name"],
        industry=data["industry"],
        funding_round=data["funding_round"],
        amount=data["amount"],
        location=data["location"],
        date=data["date"],
        source_url=data["source_url"],
        source_title=data["source_title"],
        raw_text=data["raw_text"],
        extraction_status="complete",
    )
    db.add(signal)
    await db.commit()
    await db.refresh(signal)
    return signal
