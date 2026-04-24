import json
import logging
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.job import Job
from app.models.prospect import Prospect
from app.services.signal_extraction import get_primary_provider, parse_llm_response

logger = logging.getLogger(__name__)

# ATS-specific selectors for known platforms
ATS_SELECTORS = {
    "greenhouse.io": {
        "job_links": "div.opening a, tr.job-post a",
        "title": "div.opening a, td.cell-title a",
        "department": "td.cell-department, span.department",
    },
    "lever.co": {
        "job_links": "a.posting-title",
        "title": "h5[data-qa='posting-name']",
        "department": "span.team, div.posting-categories .sort-by-team",
    },
    "workable.com": {
        "job_links": "li[data-ui='job'] a, a.job-link",
        "title": "a.job-link span, li[data-ui='job'] a",
        "department": "span.department",
    },
    "ashbyhq.com": {
        "job_links": "a[href*='/jobs/']",
        "title": "a[href*='/jobs/'] h3, a[href*='/jobs/']",
        "department": "h4, .ashby-job-posting-department",
    },
}

# Tightened heuristics for the generic extractor + page classifier.
JOB_TITLE_REGEX = re.compile(
    r"\b(engineer|developer|programmer|architect|analyst|scientist|manager|director|"
    r"designer|specialist|coordinator|lead|head|chief|vp|president|consultant|"
    r"recruiter|associate|administrator|executive|representative|officer|technician|"
    r"strategist|advisor|controller|attorney|nurse|operator|writer|editor|producer)\b",
    re.IGNORECASE,
)
JOB_HREF_REGEX = re.compile(
    r"/(jobs?|positions?|careers?|opening|role|vacancy|posting)s?/[^/]",
    re.IGNORECASE,
)
NAV_FOOTER_TAGS = {"nav", "footer", "header"}
MARKETING_CTA_REGEX = re.compile(
    r"\b(join our team|we'?re hiring|see open|view open|browse jobs|all jobs|"
    r"learn more|read more|contact us|sign up|get started)\b",
    re.IGNORECASE,
)
DEPARTMENT_KEYWORDS = {
    "engineering", "engineer", "tech",
    "sales", "go-to-market", "gtm",
    "marketing",
    "product",
    "design", "ux", "ui",
    "operations", "ops",
    "data", "analytics", "ml",
    "hr", "people", "talent", "recruit",
    "finance", "accounting",
    "support", "customer-success", "cx",
    "research", "science",
    "legal",
    "security",
}

JOB_CLASSIFICATION_PROMPT = """Classify these job postings. For each job, determine:
- department (one of: Engineering, Product, Design, Sales, Marketing, Operations, HR, Finance, Legal, Data, Other)
- seniority (one of: Intern, Junior, Mid, Senior, Lead, Manager, Director, VP, C-Level, Unknown)
- job_type (one of: Full-time, Part-time, Contract, Internship)
- skills (list of 3-5 key technical skills, empty list if non-technical)

Input jobs:
{jobs_json}

Return ONLY a JSON array with objects containing: title, department, seniority, job_type, skills
No markdown, no explanation."""


# -------------------------------------------------------------------------
# ATS detection / extraction
# -------------------------------------------------------------------------


def _detect_ats(url: str) -> str | None:
    for ats_domain in ATS_SELECTORS:
        if ats_domain in url:
            return ats_domain
    return None


def _extract_jobs_from_ats(html: str, base_url: str, ats: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    selectors = ATS_SELECTORS[ats]
    jobs = []
    for a in soup.select(selectors["job_links"]):
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if not title or len(title) < 3:
            continue
        full_url = urljoin(base_url, href)
        dept = ""
        parent = a.find_parent("div") or a.find_parent("tr") or a.find_parent("li")
        if parent:
            dept_el = parent.select_one(selectors.get("department", ""))
            if dept_el:
                dept = dept_el.get_text(strip=True)
        jobs.append({"title": title, "url": full_url, "department_hint": dept, "location": ""})
    return jobs


# -------------------------------------------------------------------------
# Structured data + helpers
# -------------------------------------------------------------------------


def _is_in_chrome(el) -> bool:
    """True if the element sits inside a nav/footer/header section."""
    for ancestor in el.parents:
        if getattr(ancestor, "name", None) in NAV_FOOTER_TAGS:
            return True
    return False


def _anchor_title(a) -> str:
    """Cleanest job title text from an anchor.

    Many ATS-rendered cards wrap the title in an `<h3>` next to a `<p>` of
    metadata (department · location · type). Using `get_text(strip=True)` on
    the anchor concatenates them into one ugly blob; preferring the heading
    keeps the title clean.
    """
    heading = a.find(["h1", "h2", "h3", "h4", "h5", "h6"])
    if heading:
        t = heading.get_text(separator=" ", strip=True)
        if t:
            return t
    return a.get_text(separator=" ", strip=True)


def extract_jsonld_jobs(html: str, base_url: str) -> list[dict]:
    """Pull JobPosting JSON-LD blocks. Most reliable extractor when present."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph") if isinstance(item.get("@graph"), list) else [item]
            for entry in graph:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("@type", "")).lower() != "jobposting":
                    continue
                title = (entry.get("title") or "").strip()
                if not title:
                    continue
                url = entry.get("url") or ""
                location = ""
                location_obj = entry.get("jobLocation")
                if isinstance(location_obj, list) and location_obj:
                    location_obj = location_obj[0]
                if isinstance(location_obj, dict):
                    addr = location_obj.get("address")
                    if isinstance(addr, dict):
                        location = ", ".join(
                            p for p in [
                                addr.get("addressLocality"),
                                addr.get("addressRegion"),
                                addr.get("addressCountry"),
                            ] if p
                        )
                    elif isinstance(addr, str):
                        location = addr
                out.append({
                    "title": title,
                    "url": urljoin(base_url, url) if url else base_url,
                    "department_hint": "",
                    "location": location,
                })
    return out


def extract_subcategory_links(html: str, base_url: str) -> list[str]:
    """Per-team / per-department links from a careers hub page (same host only).

    A "subcategory" is a short link like "Engineering" / "Sales" that filters by
    department. Long anchors that look like specific job postings are skipped
    even if their text contains a department word — those are jobs, not hubs.
    """
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlparse(base_url).netloc
    seen: set[str] = set()
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(separator=" ", strip=True).lower()
        # Sub-category links are short labels, not concatenated job titles
        if len(text) > 60:
            continue
        # Skip anchors that look like individual job postings
        if JOB_TITLE_REGEX.search(text):
            continue
        href_lower = href.lower()
        if not any(kw in text or kw in href_lower for kw in DEPARTMENT_KEYWORDS):
            continue
        full_url = urljoin(base_url, href).split("#", 1)[0]
        parsed = urlparse(full_url)
        if parsed.netloc and parsed.netloc != base_host:
            continue
        if full_url == base_url or full_url in seen:
            continue
        seen.add(full_url)
        out.append(full_url)
    return out


def classify_careers_page(html: str, url: str) -> tuple[str, dict]:
    """Determine whether this page is `listings`, `hub`, or `junk`.

    Returns (category, signals) where signals can include:
      - job_count: int (rough)
      - subcategory_links: list[str]
    """
    if not html:
        return "junk", {}

    # JSON-LD JobPosting → listings, definitively
    jsonld_jobs = extract_jsonld_jobs(html, url)
    if jsonld_jobs:
        return "listings", {"job_count": len(jsonld_jobs), "subcategory_links": []}

    # ATS-rendered? Very strong signal.
    ats = _detect_ats(url)
    if ats:
        ats_jobs = _extract_jobs_from_ats(html, url, ats)
        if ats_jobs:
            return "listings", {"job_count": len(ats_jobs), "subcategory_links": []}

    soup = BeautifulSoup(html, "html.parser")
    # Strong-signal anchors: job-shaped href AND job-title-shaped text, outside chrome.
    # Loose-signal anchors: job-title-shaped text alone — covers ATS sites whose
    # URL pattern is `/{company-slug}/{uuid}` (Ashby) rather than `/jobs/{id}`.
    # Use separator=' ' so adjacent child elements (e.g. <h3>Title</h3><span>Dept</span>)
    # don't concatenate into "TitleDept" and defeat word-boundary regexes.
    strong = 0
    title_only = 0
    for a in soup.find_all("a", href=True):
        if _is_in_chrome(a):
            continue
        text = a.get_text(separator=" ", strip=True)
        if not (10 <= len(text) <= 200):
            continue
        if MARKETING_CTA_REGEX.search(text):
            continue
        has_title = bool(JOB_TITLE_REGEX.search(text))
        has_href = bool(JOB_HREF_REGEX.search(a["href"]))
        if has_title and has_href:
            strong += 1
        elif has_title:
            title_only += 1
    if strong >= 3:
        return "listings", {"job_count": strong, "subcategory_links": []}
    if title_only >= 5:
        return "listings", {"job_count": title_only, "subcategory_links": []}

    sub_links = extract_subcategory_links(html, url)
    if len(sub_links) >= 2:
        return "hub", {"job_count": strong + title_only, "subcategory_links": sub_links}

    return "junk", {"job_count": strong + title_only, "subcategory_links": []}


# -------------------------------------------------------------------------
# Generic + LLM extractors
# -------------------------------------------------------------------------


def _extract_jobs_generic(html: str, base_url: str) -> list[dict]:
    """Tightened generic extractor: must look like a job AND not be in chrome."""
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen_titles: set[str] = set()

    for a in soup.find_all("a", href=True):
        if _is_in_chrome(a):
            continue
        text = a.get_text(separator=" ", strip=True)
        if not (10 <= len(text) <= 200):
            continue
        href = a["href"]
        # Require either a job-shaped href OR a job-title-shaped text
        if not (JOB_HREF_REGEX.search(href) or JOB_TITLE_REGEX.search(text)):
            continue
        # Drop generic marketing CTAs
        if MARKETING_CTA_REGEX.search(text):
            continue
        title = _anchor_title(a)
        key = title.lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        full_url = urljoin(base_url, href)
        jobs.append({"title": title, "url": full_url, "department_hint": "", "location": ""})

    return jobs


async def _fetch_page(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            if resp.status_code < 400:
                return resp.text
    except Exception as e:
        logger.debug(f"Failed to fetch {url}: {e}")
    return None


async def _fetch_page_playwright(url: str) -> str | None:
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle", timeout=20000)
                html = await page.content()
            finally:
                await browser.close()
            return html
    except Exception as e:
        logger.debug(f"Playwright fetch failed for {url}: {e}")
    return None


async def _fetch_html(url: str) -> str | None:
    """Try fast HTTP first; fall back to Playwright for JS-rendered pages."""
    html = await _fetch_page(url)
    if html and len(html) > 500:
        return html
    pw_html = await _fetch_page_playwright(url)
    return pw_html or html


async def _llm_extract_jobs(html: str, base_url: str) -> list[dict]:
    """LLM extraction with explicit gate. Drops everything if not a job listings page."""
    provider = get_primary_provider()
    if not provider:
        return []

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)[:3500]

    prompt = f"""You are looking at the page at: {base_url}
Decide whether this page is actually a list of open job positions.
If it's a marketing page, blog post, About page, or just a single job posting, treat it as NOT a job listings page.

Page text:
{text}

Return ONLY a JSON object with shape:
{{"is_job_listings_page": true|false, "jobs": [{{"title": "...", "url": "...", "location": "..."}}]}}

Rules:
- If is_job_listings_page is false, jobs MUST be [].
- Skip generic CTAs like "Join our team" — only include rows with a specific role title.
- url is the link to the specific job posting if present in the page text; otherwise empty string.
"""

    try:
        response = await provider.extract(prompt)
        data = parse_llm_response(response)
        if isinstance(data, dict) and data.get("is_job_listings_page") is True:
            jobs = data.get("jobs") or []
            return [
                {
                    "title": (j.get("title") or "").strip(),
                    "url": urljoin(base_url, j.get("url") or "") if j.get("url") else base_url,
                    "department_hint": "",
                    "location": j.get("location", ""),
                }
                for j in jobs
                if isinstance(j, dict) and (j.get("title") or "").strip()
            ]
    except Exception as e:
        logger.debug(f"LLM job extraction failed: {e}")

    return []


async def _extract_one_page(html: str, url: str) -> list[dict]:
    """Try extractors in order: JSON-LD → ATS → generic → LLM."""
    jobs = extract_jsonld_jobs(html, url)
    if jobs:
        return jobs
    ats = _detect_ats(url)
    if ats:
        jobs = _extract_jobs_from_ats(html, url, ats)
        if jobs:
            return jobs
    jobs = _extract_jobs_generic(html, url)
    if jobs:
        return jobs
    return await _llm_extract_jobs(html, url)


def _dedupe_jobs(jobs: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for j in jobs:
        title = (j.get("title") or "").lower().strip()
        location = (j.get("location") or "").lower().strip()
        if not title:
            continue
        key = (title, location)
        if key in seen:
            continue
        seen.add(key)
        out.append(j)
    return out


# -------------------------------------------------------------------------
# Semantic title matching
# -------------------------------------------------------------------------


async def match_jobs_to_targets(jobs: list[dict], targets: list[str]) -> list[dict]:
    """Filter jobs to those whose titles semantically match any target.

    Empty targets → return jobs unchanged (today's behaviour).
    Each kept job gets a `match_target` field naming which configured target it matched.
    """
    if not jobs:
        return []
    target_list = [t.strip() for t in (targets or []) if t and t.strip()]
    if not target_list:
        return jobs

    # Cheap pass first: case-insensitive substring (catches the obvious cases
    # without burning an LLM call).
    out: list[dict] = []
    remaining: list[dict] = []
    for j in jobs:
        title_lower = (j.get("title") or "").lower()
        matched = next((t for t in target_list if t.lower() in title_lower), None)
        if matched:
            out.append({**j, "match_target": matched})
        else:
            remaining.append(j)

    if not remaining:
        return out

    provider = get_primary_provider()
    if not provider:
        # No LLM — only the cheap-match jobs survive.
        logger.info(
            "match_jobs_to_targets: no LLM provider; %d cheap matches kept, "
            "%d jobs dropped without semantic check.",
            len(out), len(remaining),
        )
        return out

    candidates_json = json.dumps([{"i": idx, "title": j.get("title", "")} for idx, j in enumerate(remaining)])
    targets_json = json.dumps(target_list)
    prompt = f"""You are filtering job postings to those a recruiter would care about.
Targets (the role families the recruiter is hiring for): {targets_json}
Candidates: {candidates_json}

For each candidate, decide if its title belongs to the SAME ROLE FAMILY as ANY target.
Examples of MATCHING: "Backend Engineer" → "Software Engineer"; "Senior Account Executive" → "Sales Engineer"; "Staff iOS Developer" → "Software Engineer"; "Product Designer" → "UX Designer".
Examples of NOT matching: "Marketing Manager" → "Software Engineer"; "Office Manager" → "Sales Engineer".

Return ONLY a JSON array of objects: [{{"i": 0, "match": "Software Engineer"}}, {{"i": 1, "match": null}}, ...]
- "match" is the EXACT target string from the targets list, or null if no match.
- One entry per candidate.
"""

    try:
        response = await provider.extract(prompt)
        data = parse_llm_response(response)
        if isinstance(data, list):
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                idx = entry.get("i")
                match = entry.get("match")
                if not isinstance(idx, int) or not isinstance(match, str) or not match.strip():
                    continue
                if 0 <= idx < len(remaining):
                    out.append({**remaining[idx], "match_target": match.strip()})
    except Exception as e:
        logger.debug(f"LLM target matching failed: {e}")

    return out


# -------------------------------------------------------------------------
# Classification (department/seniority/skills)
# -------------------------------------------------------------------------


async def classify_jobs(raw_jobs: list[dict]) -> list[dict]:
    """LLM-classify jobs by department, seniority, type, skills."""
    if not raw_jobs:
        return []

    provider = get_primary_provider()
    if not provider:
        return [
            {**j, "department": "Other", "seniority": "Unknown", "job_type": "Full-time", "skills": []}
            for j in raw_jobs
        ]

    classified = []
    batch_size = 20

    for i in range(0, len(raw_jobs), batch_size):
        batch = raw_jobs[i:i + batch_size]
        jobs_input = [{"title": j["title"], "department_hint": j.get("department_hint", "")} for j in batch]
        prompt = JOB_CLASSIFICATION_PROMPT.format(jobs_json=json.dumps(jobs_input))

        try:
            response = await provider.extract(prompt)
            text = response.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)

            if isinstance(data, list) and len(data) == len(batch):
                for j, c in zip(batch, data):
                    classified.append({
                        **j,
                        "department": c.get("department", "Other"),
                        "seniority": c.get("seniority", "Unknown"),
                        "job_type": c.get("job_type", "Full-time"),
                        "skills": c.get("skills", []),
                    })
            else:
                for j in batch:
                    classified.append({**j, "department": "Other", "seniority": "Unknown", "job_type": "Full-time", "skills": []})
        except Exception as e:
            logger.warning(f"Job classification failed: {e}")
            for j in batch:
                classified.append({**j, "department": "Other", "seniority": "Unknown", "job_type": "Full-time", "skills": []})

    return classified


# -------------------------------------------------------------------------
# Top-level pipeline
# -------------------------------------------------------------------------


async def crawl_prospect_jobs(db: AsyncSession, prospect: Prospect, force: bool = False) -> int:
    """Full job crawl pipeline for a single prospect.

    Pipeline:
      1. discover_careers_candidates → ranked list of URLs
      2. for each candidate: classify_careers_page → listings / hub / junk
         - hub: expand sub-category links and recurse one level
         - junk: skip
      3. extract_one_page on each validated listings page (JSON-LD → ATS → generic → LLM)
      4. dedupe + match_jobs_to_targets (semantic LLM filter against configured target titles)
      5. classify_jobs + persist

    Status semantics:
      - failed : no candidate validated as a listings page
      - empty  : pages validated but 0 jobs (or 0 after target match)
      - done   : ≥ 1 job saved
    """
    prospect.job_crawl_status = "pending"
    prospect.job_crawl_error = None
    prospect.job_crawl_raw_count = 0
    await db.commit()

    if force:
        from sqlalchemy import delete
        await db.execute(delete(Job).where(Job.prospect_id == prospect.id))
        prospect.careers_url = None
        prospect.job_crawl_strategy = None
        await db.commit()

    try:
        from app.services.career_discovery import discover_careers_candidates
        candidates = await discover_careers_candidates(
            prospect.company_name, prospect.website, prospect.linkedin_url, max_candidates=8,
        )

        if not candidates:
            prospect.job_crawl_status = "failed"
            prospect.job_crawl_error = (
                "No careers page found. All discovery strategies exhausted "
                "(URL patterns, homepage crawl, ATS detection, Google, LinkedIn)."
            )
            await db.commit()
            return 0

        max_listings = max(1, min(10, settings.job_max_listing_pages or 4))
        max_subs = max(1, min(20, settings.job_max_subcategory_pages or 6))

        validated: list[tuple[str, str, str]] = []  # (url, html, strategy_name)
        for cand_url, strategy in candidates:
            if len(validated) >= max_listings:
                break

            # Fast HTTP first.
            html = await _fetch_page(cand_url)
            cat, signals = classify_careers_page(html or "", cand_url)

            # Many modern careers pages (Ashby, Greenhouse, Lever, custom React)
            # are JS-rendered SPAs whose static HTML has no anchors. If the fast
            # fetch doesn't classify, retry once with Playwright before moving on.
            if cat == "junk":
                pw_html = await _fetch_page_playwright(cand_url)
                if pw_html and pw_html != html:
                    html = pw_html
                    cat, signals = classify_careers_page(html, cand_url)
                    logger.info(
                        "Playwright retry for %s → classified as %s", cand_url, cat,
                    )

            if not html:
                continue
            if cat == "listings":
                validated.append((cand_url, html, strategy))
                continue
            if cat == "hub":
                sub_links = signals.get("subcategory_links", [])[:max_subs]
                logger.info(
                    "Hub page at %s → expanding %d sub-categories", cand_url, len(sub_links),
                )
                for sub_url in sub_links:
                    if len(validated) >= max_listings:
                        break
                    sub_html = await _fetch_page(sub_url)
                    sub_cat, _ = classify_careers_page(sub_html or "", sub_url)
                    if sub_cat == "junk":
                        pw_sub = await _fetch_page_playwright(sub_url)
                        if pw_sub and pw_sub != sub_html:
                            sub_html = pw_sub
                            sub_cat, _ = classify_careers_page(sub_html, sub_url)
                    if sub_html and sub_cat == "listings":
                        validated.append((sub_url, sub_html, f"{strategy}+sub"))

        if not validated:
            prospect.job_crawl_status = "failed"
            prospect.job_crawl_error = (
                f"Examined {len(candidates)} candidate page(s) but none looked like a "
                f"job listings page. The site may use an unusual careers layout."
            )
            await db.commit()
            return 0

        # Persist the most-canonical validated URL
        prospect.careers_url = validated[0][0]
        prospect.job_crawl_strategy = validated[0][2]
        await db.commit()

        all_jobs: list[dict] = []
        for url, html, _ in validated:
            page_jobs = await _extract_one_page(html, url)
            all_jobs.extend(page_jobs)

        all_jobs = _dedupe_jobs(all_jobs)
        prospect.job_crawl_raw_count = len(all_jobs)

        if not all_jobs:
            prospect.job_crawl_status = "empty"
            prospect.job_crawl_error = (
                f"Validated {len(validated)} listings page(s) at {prospect.careers_url} "
                f"but extractors returned 0 jobs."
            )
            await db.commit()
            return 0

        targets = list(settings.job_target_titles or [])
        matched = await match_jobs_to_targets(all_jobs, targets)

        if targets and not matched:
            prospect.job_crawl_status = "empty"
            prospect.job_crawl_error = (
                f"Found {len(all_jobs)} job(s) on {prospect.careers_url}, "
                f"but none matched target titles {targets!r}."
            )
            await db.commit()
            return 0

        classified = await classify_jobs(matched)

        count = 0
        for j in classified:
            job = Job(
                prospect_id=prospect.id,
                list_id=prospect.list_id,
                company_name=prospect.company_name,
                title=j["title"][:512],
                department=j.get("department", "Other")[:100],
                seniority=j.get("seniority", "Unknown")[:50],
                job_type=j.get("job_type", "Full-time")[:50],
                location=(j.get("location") or prospect.location or "")[:255],
                url=j.get("url", "")[:2048],
                skills=j.get("skills", []),
                match_target=(j.get("match_target") or None),
            )
            db.add(job)
            count += 1

        prospect.job_crawl_status = "done"
        await db.commit()
        return count

    except Exception as e:
        logger.error(f"Job crawl failed for {prospect.company_name}: {e}")
        prospect.job_crawl_status = "failed"
        prospect.job_crawl_error = f"{type(e).__name__}: {e}"
        await db.commit()
        return 0
