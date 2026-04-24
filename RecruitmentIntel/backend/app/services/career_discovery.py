import logging
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.services.signal_extraction import get_primary_provider

logger = logging.getLogger(__name__)

# Known ATS patterns
ATS_PATTERNS = {
    "Greenhouse": [
        "boards.greenhouse.io/{slug}",
        "{domain}/greenhouse",
    ],
    "Lever": [
        "jobs.lever.co/{slug}",
    ],
    "Workable": [
        "apply.workable.com/{slug}",
        "{slug}.workable.com",
    ],
    "Ashby": [
        "jobs.ashbyhq.com/{slug}",
    ],
}


def _company_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _company_slug_hyphen(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


async def _check_url_ok(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.head(url, headers={"User-Agent": "Mozilla/5.0"})
            return resp.status_code < 400
    except Exception:
        return False


async def _get_page_text(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code < 400:
                return resp.text
    except Exception:
        pass
    return None


async def strategy_url_patterns(website: str) -> list[str]:
    """Strategy 1: Try common career page URL patterns. Returns all matches."""
    base = website.rstrip("/")
    out: list[str] = []
    for pattern in settings.career_patterns:
        url = f"{base}{pattern}"
        if await _check_url_ok(url):
            logger.info(f"Career candidate via URL pattern: {url}")
            out.append(url)
    return out


async def strategy_homepage_links(website: str, max_candidates: int = 3) -> list[str]:
    """Strategy 2: Crawl homepage for career-related links. Returns top matches."""
    html = await _get_page_text(website)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    career_keywords = ["career", "job", "join", "hiring", "work with us", "open position", "open role"]

    seen: set[str] = set()
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        link_text = a.get_text(strip=True).lower()
        href = a["href"].lower()
        if any(kw in link_text or kw in href for kw in career_keywords):
            full_url = urljoin(website, a["href"])
            if full_url in seen:
                continue
            seen.add(full_url)
            if await _check_url_ok(full_url):
                logger.info(f"Career candidate via homepage link: {full_url}")
                out.append(full_url)
                if len(out) >= max_candidates:
                    break
    return out


async def strategy_ats_detection(company_name: str) -> list[str]:
    """Strategy 3: Check known ATS platforms. Returns all matches."""
    slug = _company_slug(company_name)
    slug_h = _company_slug_hyphen(company_name)

    out: list[str] = []
    for ats_name in settings.ats_detection:
        patterns = ATS_PATTERNS.get(ats_name, [])
        for pattern in patterns:
            for s in [slug, slug_h]:
                url = "https://" + pattern.format(slug=s, domain=s)
                if await _check_url_ok(url):
                    logger.info(f"Career candidate via {ats_name}: {url}")
                    out.append(url)
    return out


async def strategy_google_search(company_name: str, max_candidates: int = 3) -> list[str]:
    """Strategy 4: Google search for career page."""
    if not settings.fallback_google:
        return []

    out: list[str] = []
    try:
        query = f"{company_name} careers jobs site"
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.google.com/search",
                params={"q": query, "num": 5},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                seen: set[str] = set()
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "/url?q=" in href:
                        real_url = href.split("/url?q=")[1].split("&")[0]
                        if any(kw in real_url.lower() for kw in ["career", "jobs", "greenhouse", "lever", "workable", "ashby"]):
                            if real_url in seen:
                                continue
                            seen.add(real_url)
                            logger.info(f"Career candidate via Google: {real_url}")
                            out.append(real_url)
                            if len(out) >= max_candidates:
                                break
    except Exception as e:
        logger.debug(f"Google career search failed: {e}")

    return out


async def strategy_linkedin_jobs(company_name: str, linkedin_url: str | None) -> list[str]:
    """Strategy 5: LinkedIn Jobs as final fallback."""
    if not settings.fallback_linkedin or not linkedin_url:
        return []
    jobs_url = linkedin_url.rstrip("/") + "/jobs"
    if await _check_url_ok(jobs_url):
        return [jobs_url]
    return []


async def discover_careers_candidates(
    company_name: str,
    website: str | None = None,
    linkedin_url: str | None = None,
    max_candidates: int = 8,
) -> list[tuple[str, str]]:
    """Aggregate all 5 strategies into a confidence-ordered candidate list.

    Returns `[(url, strategy_name), ...]`. Higher-confidence strategies appear first
    so the caller can validate them before paying the cost of low-confidence ones.
    Order: url_patterns > homepage_links > ats_detection > google_search > linkedin_jobs.
    """
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(urls: list[str], strategy: str) -> None:
        for u in urls:
            if u in seen:
                continue
            seen.add(u)
            candidates.append((u, strategy))

    if website:
        _add(await strategy_url_patterns(website), "url_patterns")
        _add(await strategy_homepage_links(website), "homepage_links")
    _add(await strategy_ats_detection(company_name), "ats_detection")
    _add(await strategy_google_search(company_name), "google_search")
    _add(await strategy_linkedin_jobs(company_name, linkedin_url), "linkedin_jobs")

    return candidates[:max_candidates]


async def discover_careers_page(
    company_name: str,
    website: str | None = None,
    linkedin_url: str | None = None,
) -> tuple[str | None, str]:
    """Backward-compatible wrapper: returns just the most-confident candidate."""
    candidates = await discover_careers_candidates(
        company_name, website=website, linkedin_url=linkedin_url, max_candidates=1
    )
    if candidates:
        return candidates[0]
    return None, "none"
