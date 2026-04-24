import logging
import re

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prospect import Prospect
from app.services.signal_extraction import get_primary_provider

logger = logging.getLogger(__name__)

COMMON_TLDS = [".com", ".io", ".ai", ".co", ".dev", ".tech"]

# Words that commonly get dropped or abbreviated when a company picks a domain.
# e.g. "Point2 Technology" -> "point2tech.com"; "Acme Labs Inc" -> "acme.com"
_STRIPPABLE_SUFFIXES = {
    "technology", "technologies", "inc", "corp", "corporation",
    "llc", "ltd", "labs", "lab", "group", "co", "ai", "holdings",
    "systems", "solutions",
}
_WORD_ABBREVIATIONS = {
    "technology": "tech",
    "technologies": "tech",
    "solutions": "sol",
    "systems": "sys",
}


def _normalize_company_name(name: str) -> str:
    """Convert company name to potential domain slug."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _name_variants(company_name: str) -> list[str]:
    """Generate name variants for domain-guess.

    Ordered most-specific → least-specific to reduce false positives from
    unrelated sites with short generic slugs (e.g. point2.com is a real
    estate site, not "Point2 Technology"). We try the full/abbreviated
    forms first and only fall back to the stripped form last.
    """
    words = [w for w in re.split(r"[^a-zA-Z0-9]+", company_name.lower()) if w]
    if not words:
        return []

    variants: list[str] = []

    # 1. Abbreviate known words (Point2 Technology -> point2tech)
    abbreviated = [_WORD_ABBREVIATIONS.get(w, w) for w in words]
    if abbreviated != words:
        variants.append("".join(abbreviated))
        variants.append("-".join(abbreviated))

    # 2. Full name (Point2 Technology -> point2technology)
    variants.append("".join(words))
    variants.append("-".join(words))

    # 3. Last resort: strip trailing filler suffixes (Point2 Technology -> point2)
    stripped = list(words)
    while stripped and stripped[-1] in _STRIPPABLE_SUFFIXES:
        stripped.pop()
    if stripped and stripped != words:
        variants.append("".join(stripped))
        variants.append("-".join(stripped))

    # Dedup while preserving order
    seen = set()
    out = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _guess_domains(company_name: str) -> list[str]:
    """Generate candidate domain URLs from company name."""
    candidates: list[str] = []
    for slug in _name_variants(company_name):
        for tld in COMMON_TLDS:
            candidates.append(f"https://{slug}{tld}")
    return candidates


async def _check_url(url: str) -> bool:
    """Check if a URL returns 200 OK."""
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.head(url, headers={"User-Agent": "Mozilla/5.0"})
            return resp.status_code < 400
    except Exception:
        return False


_SOCIAL_HOSTS = (
    "linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com",
    "crunchbase.com", "wikipedia.org", "youtube.com", "tiktok.com",
    "github.com", "medium.com", "bloomberg.com", "google.com",
)


def _is_social_or_aggregator(url: str) -> bool:
    return any(host in url for host in _SOCIAL_HOSTS)


async def _discover_website_from_linkedin(linkedin_url: str) -> str | None:
    """Render a LinkedIn company page with Playwright and extract the website link.

    LinkedIn's public company overview shows the website URL under the
    'Overview' card. Many company pages redirect anonymous visitors through
    an auth wall, but /about/ is often accessible and the website link is
    embedded as an `<a>` with a tracking-redirect `href` pointing to the
    real site.
    """
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return None

    # Normalize to the /about/ page
    url = linkedin_url.rstrip("/")
    if not url.endswith("/about"):
        url = url + "/about"
    url = url + "/"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except Exception:
                await browser.close()
                return None
            html = await page.content()
            await browser.close()
    except Exception as e:
        logger.debug(f"Playwright LinkedIn fetch failed for {linkedin_url}: {e}")
        return None

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # Preferred: <a data-tracking-control-name="...about_website..."> or the dl/dt Website row
    for a in soup.find_all("a", href=True):
        control = a.get("data-tracking-control-name", "")
        href = a["href"]
        if "about_website" in control or "website" in control.lower():
            candidate = _unwrap_linkedin_redirect(href)
            if candidate and not _is_social_or_aggregator(candidate):
                return candidate

    # Fallback: any external http(s) link in the page that's not social/LinkedIn itself
    for a in soup.find_all("a", href=True):
        href = a["href"]
        candidate = _unwrap_linkedin_redirect(href)
        if not candidate:
            continue
        if not candidate.startswith("http"):
            continue
        if _is_social_or_aggregator(candidate):
            continue
        return candidate

    return None


def _unwrap_linkedin_redirect(href: str) -> str | None:
    """LinkedIn wraps external links in /redir/redirect?url=... — unwrap that."""
    from urllib.parse import urlparse, parse_qs, unquote

    if not href:
        return None
    if "linkedin.com/redir" in href or "/redir/redirect" in href:
        q = parse_qs(urlparse(href).query)
        if "url" in q and q["url"]:
            return unquote(q["url"][0])
    return href


def _linkedin_company_slug(url: str | None) -> str | None:
    """Extract the company slug from a LinkedIn URL (e.g. linkedin.com/company/foo/ -> 'foo').

    Case-insensitive; trailing slash and /about suffix ignored.
    """
    if not url:
        return None
    m = re.search(r"linkedin\.com/company/([^/?#]+)", url, re.IGNORECASE)
    if not m:
        return None
    slug = m.group(1).strip("/").lower()
    return slug or None


async def _fetch_website_html(url: str) -> str | None:
    """Fetch a website's HTML. Simple httpx first; falls back to Playwright
    for JS-heavy pages where the LinkedIn link is injected client-side."""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code < 400 and resp.text:
                if "linkedin.com/company/" in resp.text.lower():
                    return resp.text
                # Keep the HTML but try Playwright too if no LinkedIn in static HTML
                static_html = resp.text
            else:
                static_html = None
    except Exception:
        static_html = None

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                html = await page.content()
            finally:
                await browser.close()
            if html and "linkedin.com/company/" in html.lower():
                return html
            return html or static_html
    except Exception as e:
        logger.debug(f"Playwright website fetch failed for {url}: {e}")
        return static_html


def _extract_linkedin_from_html(html: str) -> str | None:
    """Return the first linkedin.com/company/... URL found in the HTML (any form)."""
    if not html:
        return None
    # Match href="https://www.linkedin.com/company/slug/..." with optional subdomain
    m = re.search(
        r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[^\s\"'<>]+",
        html,
        re.IGNORECASE,
    )
    return m.group(0) if m else None


async def cross_verify_website_linkedin(
    website: str | None, linkedin_url: str | None
) -> tuple[str, str | None]:
    """Final QA: fetch the website, find its LinkedIn link, compare to the discovered one.

    Returns (state, replacement_linkedin_url):
      - ("verified", None)            — website links to the same LinkedIn slug
      - ("reconciled", <url>)         — website links to a different LinkedIn; caller
                                        should trust the website's self-reported URL
      - ("unverified", None)          — website has no LinkedIn link; can't confirm
      - ("unreachable", None)         — website didn't fetch
      - ("skipped", None)             — one of the inputs was missing
    """
    if not website or not linkedin_url:
        return "skipped", None

    html = await _fetch_website_html(website)
    if not html:
        return "unreachable", None

    site_linkedin = _extract_linkedin_from_html(html)
    if not site_linkedin:
        return "unverified", None

    site_slug = _linkedin_company_slug(site_linkedin)
    known_slug = _linkedin_company_slug(linkedin_url)
    if site_slug and known_slug and site_slug == known_slug:
        return "verified", None

    # Website advertises a different LinkedIn — prefer the self-reported one.
    # Normalize to the canonical /company/<slug>/ form.
    if site_slug:
        return "reconciled", f"https://www.linkedin.com/company/{site_slug}"
    return "unverified", None


async def discover_website(
    company_name: str,
    location: str = "",
    linkedin_url: str | None = None,
) -> tuple[str | None, str]:
    """4-strategy cascade to find company website. Returns (url, strategy_name).

    If a LinkedIn URL is provided, the LinkedIn about-page scrape runs first
    — it's the most reliable for companies whose names don't map cleanly to
    their domains (e.g. "Point2 Technology" -> point2tech.com).
    """

    # Strategy 0 (if known): LinkedIn About page scrape
    if linkedin_url:
        url = await _discover_website_from_linkedin(linkedin_url)
        if url and await _check_url(url):
            logger.info(f"Website found via LinkedIn about page: {url}")
            return url, "linkedin_about"

    # Strategy 1: Domain guess
    for url in _guess_domains(company_name):
        if await _check_url(url):
            logger.info(f"Website found via domain guess: {url}")
            return url, "domain_guess"

    # Strategy 2: Google search (scrape approach)
    try:
        query = f"{company_name} official website"
        if location:
            query += f" {location}"
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.google.com/search",
                params={"q": query, "num": 5},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            if resp.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    # Extract real URLs from Google redirect links
                    if "/url?q=" in href:
                        real_url = href.split("/url?q=")[1].split("&")[0]
                        if not _is_social_or_aggregator(real_url):
                            logger.info(f"Website found via Google: {real_url}")
                            return real_url, "google_search"
    except Exception as e:
        logger.debug(f"Google search failed for {company_name}: {e}")

    # Strategy 3: LLM inference
    provider = get_primary_provider()
    if provider:
        try:
            prompt = f"What is the official website URL of {company_name}"
            if location:
                prompt += f", the startup based in {location}"
            prompt += "? Return ONLY the URL, nothing else."
            response = await provider.extract(prompt)
            url = response.strip().strip('"').strip("'")
            if url.startswith("http") and await _check_url(url):
                logger.info(f"Website found via LLM: {url}")
                return url, "llm_inference"
        except Exception as e:
            logger.debug(f"LLM website inference failed: {e}")

    return None, "none"


async def discover_linkedin(company_name: str) -> tuple[str | None, str]:
    """2-strategy cascade to find LinkedIn company page. Returns (url, strategy)."""
    slug = _normalize_company_name(company_name)
    slug_hyphen = re.sub(r"[^a-z0-9]+", "-", company_name.lower()).strip("-")

    # Strategy 1: URL pattern guess
    for s in [slug, slug_hyphen]:
        url = f"https://www.linkedin.com/company/{s}"
        if await _check_url(url):
            return url, "url_pattern"

    # Strategy 2: Google site-search
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.google.com/search",
                params={"q": f'site:linkedin.com/company "{company_name}"', "num": 3},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            if resp.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "linkedin.com/company/" in href:
                        if "/url?q=" in href:
                            href = href.split("/url?q=")[1].split("&")[0]
                        return href, "google_search"
    except Exception as e:
        logger.debug(f"LinkedIn Google search failed: {e}")

    return None, "none"


async def enrich_prospect(db: AsyncSession, prospect: Prospect):
    """Run full enrichment for a single prospect, recording which strategy worked.

    Order: LinkedIn first, then website (which can leverage the LinkedIn
    about page when domain-guess fails).
    """
    prospect.enrichment_status = "pending"
    prospect.enrichment_error = None
    await db.commit()

    try:
        linkedin, li_strategy = await discover_linkedin(prospect.company_name)
        website, web_strategy = await discover_website(
            prospect.company_name, prospect.location, linkedin_url=linkedin
        )

        # Final QA: cross-check website ↔ LinkedIn.
        # If the site advertises a different LinkedIn, trust the site's self-reported
        # URL (it's authoritative — the LinkedIn guess could have hit a different
        # company that happens to share a slug).
        verify_state, replacement = await cross_verify_website_linkedin(website, linkedin)
        if verify_state == "reconciled" and replacement:
            logger.info(
                f"Reconciled LinkedIn for {prospect.company_name}: "
                f"{linkedin} -> {replacement} (website self-report)"
            )
            linkedin = replacement
            li_strategy = "website_ref"

        prospect.website = website
        prospect.linkedin_url = linkedin

        if website or linkedin:
            prospect.enrichment_status = "done"
            base = (
                f"website:{web_strategy}" if website else f"linkedin:{li_strategy}"
            )
            # Encode the verification outcome so the UI tooltip can surface confidence.
            prospect.enrichment_strategy = f"{base}+{verify_state}"
        else:
            prospect.enrichment_status = "failed"
            prospect.enrichment_strategy = "none"
            prospect.enrichment_error = (
                "All strategies exhausted — no website via domain guess, "
                "LinkedIn-about, Google, or LLM; no LinkedIn via URL pattern or Google."
            )
    except Exception as e:
        logger.error(f"Enrichment failed for {prospect.company_name}: {e}")
        prospect.enrichment_status = "failed"
        prospect.enrichment_strategy = "none"
        prospect.enrichment_error = f"{type(e).__name__}: {e}"

    await db.commit()


async def enrich_all_in_list(db: AsyncSession, list_id, force: bool = False):
    """Enrich prospects in a list. By default re-runs not_started/failed AND any
    `pending` rows (the route's eager UPDATE marks targets pending so the UI can
    poll; the worker must still pick them up). Pass force=True to re-run every
    prospect including those already 'done'.
    """
    query = select(Prospect).where(Prospect.list_id == list_id)
    if not force:
        query = query.where(Prospect.enrichment_status.in_(["not_started", "failed", "pending"]))
    result = await db.execute(query)
    prospects = result.scalars().all()

    results = {"total": len(prospects), "done": 0, "failed": 0}
    for prospect in prospects:
        await enrich_prospect(db, prospect)
        if prospect.enrichment_status == "done":
            results["done"] += 1
        else:
            results["failed"] += 1

    return results
