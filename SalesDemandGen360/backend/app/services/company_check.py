"""Confirming a company before its people are searched: domain, country, LinkedIn page.

People search goes by domain, so a wrong domain finds the wrong company's
staff — confidently. And the company's country and LinkedIn page were mostly
empty on the Test Data list, because only a CSV ever wrote a country. Two
sources can answer, and they are asked in cost order:

* **The company's own website** (free) — whether it answers at all, whether it
  redirects to another domain (`vanguardtech.com` lands on `argylesg.com`), and
  which LinkedIn company pages it links.
* **Apollo's organisation record** (one credit) — country, state, LinkedIn
  page, and the domain Apollo files the company under. Asked only while the
  account still lacks a country or a LinkedIn page, and remembered for
  `APOLLO_REUSE_DAYS`, so a second check does not pay again.

**What agrees is filled; what disagrees is left for a rep.** An empty country
takes Apollo's. A LinkedIn page is taken when the site links exactly one and
Apollo does not point elsewhere, or when Apollo's is one of several the site
links. Anything else — two pages and no tie-break, a redirect, Apollo filing
the company under another domain, a country that differs from the one on
record — becomes a conflict with the candidates beside it. Apollo's facts are
not used at all when its record is for a different domain: that is often a
parent company, and its country is not this office's.

A settled conflict is remembered, so the next check does not raise it again.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services import site_links
from app.services.fit import REGIONS
from app.services.resolution import normalise_domain, normalise_linkedin
from app.services.site_sweep import client

log = logging.getLogger(__name__)

#: How long Apollo's organisation record is reused before it is asked again.
APOLLO_REUSE_DAYS = 90
#: What a rep can settle from the list screen.
SETTLEABLE = ("domain", "linkedin_url", "hq_country")

#: Alias sets that name one country. The EU set names many and is left out:
#: France and Germany are not "the same country".
_COUNTRY_ALIASES = tuple(
    REGIONS[key] for key in ("us", "uk", "canada", "india", "australia") if key in REGIONS
)


@dataclass(frozen=True)
class Option:
    value: str
    source: str


@dataclass
class Conflict:
    field: str
    current: str | None
    options: list[Option]
    note: str


@dataclass
class Website:
    answered: bool
    redirects_to: str | None = None
    company_pages: list[str] = field(default_factory=list)


@dataclass
class Decision:
    fills: dict[str, Option] = field(default_factory=dict)
    conflicts: list[Conflict] = field(default_factory=list)


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def org_facts(org: dict | None) -> dict:
    """The parts of Apollo's organisation record a check reads."""
    if not org:
        return {"found": False}
    return {
        "found": True,
        "name": _text(org.get("name")),
        "domain": normalise_domain(org.get("primary_domain") or org.get("website_url")),
        "country": _text(org.get("country")),
        "state": _text(org.get("state")),
        "city": _text(org.get("city")),
        "linkedin_url": normalise_linkedin(org.get("linkedin_url")),
    }


def same_country(a: str | None, b: str | None) -> bool:
    x, y = (a or "").strip().casefold(), (b or "").strip().casefold()
    if not x or not y:
        return False
    return x == y or any(x in names and y in names for names in _COUNTRY_ALIASES)


def _first_upper(text: str) -> str:
    return text[:1].upper() + text[1:]


def decide(
    domain: str | None,
    current: dict[str, str | None],
    website: Website,
    apollo: dict | None,
    settled: dict[str, str | None] | None = None,
) -> Decision:
    """What to fill and what to ask about. Pure — no network, no database."""
    settled = settled or {}
    decision = Decision()
    dom = normalise_domain(domain)

    def already_settled(name: str, value: str | None) -> bool:
        return name in settled and settled[name] == value

    found = apollo if apollo and apollo.get("found") else None
    # Apollo's record is only this company's when it is filed under this domain.
    usable = found if found and (not found.get("domain") or found["domain"] == dom) else None

    # --- the domain ---------------------------------------------------------
    options: list[Option] = []
    notes: list[str] = []
    if not website.answered:
        notes.append(f"{dom} does not answer")
    if website.redirects_to and website.redirects_to != dom:
        options.append(Option(website.redirects_to, "website redirect"))
        notes.append(f"{dom} redirects to {website.redirects_to}")
    if found and found.get("domain") and found["domain"] != dom:
        if found["domain"] not in {o.value for o in options}:
            options.append(Option(found["domain"], "apollo"))
        notes.append(f"Apollo files {found.get('name') or 'this company'} under {found['domain']}")
    if notes and not already_settled("domain", dom):
        decision.conflicts.append(
            Conflict("domain", dom, options, _first_upper("; ".join(notes)) + ".")
        )

    # --- the country --------------------------------------------------------
    if usable and usable.get("country"):
        have = current.get("hq_country")
        if not have:
            decision.fills["hq_country"] = Option(usable["country"], "apollo")
            if usable.get("state") and not current.get("hq_region"):
                decision.fills["hq_region"] = Option(usable["state"], "apollo")
        elif not same_country(have, usable["country"]):
            if not already_settled("hq_country", have):
                decision.conflicts.append(
                    Conflict(
                        "hq_country", have, [Option(usable["country"], "apollo")],
                        f"On record as {have}; Apollo places the company in {usable['country']}.",
                    )
                )
        elif usable.get("state") and not current.get("hq_region"):
            decision.fills["hq_region"] = Option(usable["state"], "apollo")

    # --- the LinkedIn page --------------------------------------------------
    site = list(dict.fromkeys(p for p in (normalise_linkedin(x) for x in website.company_pages) if p))
    theirs = usable.get("linkedin_url") if usable else None
    known = list(dict.fromkeys([*site, *([theirs] if theirs else [])]))

    def source_of(url: str) -> str:
        if url in site and url == theirs:
            return "website and apollo"
        return "website" if url in site else "apollo"

    have = normalise_linkedin(current.get("linkedin_url"))
    if have:
        if known and have not in known and not already_settled("linkedin_url", have):
            decision.conflicts.append(
                Conflict(
                    "linkedin_url", have, [Option(u, source_of(u)) for u in known],
                    "The page on record is not one the website or Apollo points to.",
                )
            )
    elif len(site) == 1 and (theirs is None or theirs == site[0]):
        decision.fills["linkedin_url"] = Option(site[0], source_of(site[0]))
    elif not site and theirs:
        decision.fills["linkedin_url"] = Option(theirs, "apollo")
    elif len(site) > 1 and theirs in site:
        decision.fills["linkedin_url"] = Option(theirs, "apollo, and linked from the website")
    elif known and not already_settled("linkedin_url", None):
        note = (
            f"The website links {len(site)} company pages."
            if len(site) > 1 and not theirs
            else "The website and Apollo point to different company pages."
        )
        decision.conflicts.append(
            Conflict("linkedin_url", None, [Option(u, source_of(u)) for u in known], note)
        )
    return decision


async def _landing_domain(domain: str, http) -> str | None:
    """Where the homepage ends up, after redirects."""
    own = http or client()
    owned = http is None
    try:
        response = await own.get(f"https://{domain}/")
        host = getattr(getattr(response, "url", None), "host", None)
        landed = normalise_domain(host) if isinstance(host, str) else None
    except Exception:  # noqa: BLE001 — an unreachable page is a finding, not a fault
        return None
    finally:
        if owned:
            await own.aclose()
    if landed and (landed == domain or landed.endswith("." + domain)):
        return domain
    return landed


async def read_website(domain: str, *, http=None) -> Website:
    links = await site_links.read_site(domain, http=http)
    if not links.answered:
        return Website(answered=False)
    return Website(
        answered=True,
        redirects_to=await _landing_domain(domain, http),
        company_pages=list(links.company_pages),
    )


@dataclass
class CheckOutcome:
    account_id: Any
    name: str
    filled: list[dict] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    website_answered: bool = False
    apollo_asked: bool = False
    #: Credits this check may have used — one per organisation lookup.
    apollo_credits: int = 0
    note: str = ""


def _fresh(prior: dict | None, domain: str, now: datetime) -> bool:
    if not prior or prior.get("asked_for") != domain:
        return False
    try:
        asked = datetime.fromisoformat(prior.get("asked_at") or "")
    except ValueError:
        return False
    return now - asked < timedelta(days=APOLLO_REUSE_DAYS)


async def check_account(account, *, people=None, http=None, now: datetime | None = None) -> CheckOutcome:
    """Check one account's domain, country and LinkedIn page; fill what agrees."""
    now = now or datetime.now(UTC)
    outcome = CheckOutcome(account.id, account.name)
    dom = normalise_domain(account.domain)
    if not dom:
        outcome.note = "no domain to check — confirm the company's identity first"
        return outcome

    previous = dict(account.company_check or {})
    settled = {s["field"]: s.get("value") for s in previous.get("settled") or [] if "field" in s}

    website = await read_website(dom, http=http)
    outcome.website_answered = website.answered

    apollo = previous.get("apollo")
    if not _fresh(apollo, dom, now):
        apollo = None
        if people is not None and (not account.hq_country or not account.linkedin_url):
            org = await people.organization(dom)
            apollo = {**org_facts(org), "asked_for": dom, "asked_at": now.isoformat()}
            outcome.apollo_asked = True
            outcome.apollo_credits = 1

    decision = decide(
        dom,
        {
            "hq_country": account.hq_country,
            "hq_region": account.hq_region,
            "linkedin_url": account.linkedin_url,
        },
        website,
        apollo,
        settled,
    )
    for name, option in decision.fills.items():
        setattr(account, name, option.value)
        outcome.filled.append({"field": name, "value": option.value, "source": option.source})
    outcome.conflicts = decision.conflicts

    # Reassigned, not mutated: JSONB changes are only noticed on assignment.
    account.company_check = {
        "checked_at": now.isoformat(),
        "domain": dom,
        "website": asdict(website),
        "apollo": apollo,
        "filled": outcome.filled,
        "conflicts": [asdict(c) for c in decision.conflicts],
        "settled": previous.get("settled") or [],
    }
    return outcome


def settle(account, field_name: str, value: str | None, *, now: datetime | None = None) -> None:
    """A rep's answer to one conflict: use this value, or keep what is on record.

    Raises ValueError for a field that cannot be settled here or a value that
    is not the right kind of thing.
    """
    if field_name not in SETTLEABLE:
        raise ValueError(f"{field_name} is not something a company check settles")
    now = now or datetime.now(UTC)
    if value is not None and value.strip():
        if field_name == "domain":
            cleaned = normalise_domain(value)
            if not cleaned:
                raise ValueError(f"{value!r} is not a domain")
        elif field_name == "linkedin_url":
            cleaned = normalise_linkedin(value)
            if not cleaned:
                raise ValueError("that is not a LinkedIn company page")
        else:
            cleaned = value.strip()
        setattr(account, field_name, cleaned)

    check = dict(account.company_check or {})
    check["conflicts"] = [c for c in check.get("conflicts") or [] if c.get("field") != field_name]
    check["settled"] = [
        s for s in check.get("settled") or [] if s.get("field") != field_name
    ] + [{"field": field_name, "value": getattr(account, field_name), "at": now.isoformat()}]
    account.company_check = check
