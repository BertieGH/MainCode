"""Which indexed LinkedIn posts are worth keeping, decided without a model call.

A SERP page returns ten posts whatever we ask for, and on this book four
companies in six return a full ten — so there are more than we fetch and the
question is which to keep, not how to get more. Keeping all ten is what the
first version did: ten passages an account, every one an extraction input token
later, most of them irrelevant.

**Scored lexically, on purpose.** The alternatives are worse here:

* an LLM call per post is the cost this exists to avoid — ranking the inputs to
  a model by asking a model is circular;
* an embedding needs infrastructure this installation does not have, and a
  two-hundred-character snippet is thin material for one.

A lexicon is free, deterministic, and — the part that decides it — **it can say
why**. A rep asking why a post ended up in their draft gets "it named ERP and
migration", which is an answer. A cosine distance is not.

**Two scores, because they are two questions.** "Is this person talking about
technology at all" and "is this relevant to what we sell" are independent: a
post about an ERP migration scores on both, a post about an AI conference
scores on the first, a post about outsourced QA scores on the second. Ranking on
one sum would let a long generic technology post outrank a short specific one.

What is *not* here: anything about how active a contact is. Measured across
seven accounts, 45 distinct post authors held **one** employee — the company
query returns whoever is talking *about* a company, mostly trade media and
analysts. These posts are third-party coverage, which is a real thing worth
keeping and not the same thing as a person's own activity.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

#: Terms that mark a post as being about technology at all. Deliberately broad
#: and deliberately *not* product names: a vendor list goes stale and a post
#: naming a competitor's product is still about technology.
TECHNOLOGY = (
    "ai", "artificial intelligence", "machine learning", "ml", "llm", "genai",
    "automation", "automate", "cloud", "aws", "azure", "gcp", "saas", "platform",
    "data", "analytics", "dashboard", "warehouse", "lakehouse", "etl", "pipeline",
    "erp", "crm", "plm", "mes", "wms", "integration", "api", "middleware",
    "migration", "modernis", "moderniz", "legacy", "replatform", "re-platform",
    "digital transformation", "cyber", "security", "devops", "kubernetes",
    "software", "engineering", "developer", "it team", "cio", "cto", "infrastructure",
)

#: Words that say a *change* is happening rather than an opinion being offered.
#: A post announcing a migration is worth more than one musing about migrations,
#: and this is the cheapest way to tell them apart.
#: Terms of five characters or more also match their inflections — `launch`
#: catches "launched" and "launching" — so only the short ones and the
#: irregulars need their own entry.
#:
#: The event words at the end were added from measurement: real posts reading
#: "confirms Nasdaq **delisting**" and "**axed** a $1.25B Arizona battery
#: plant" scored nothing and were dropped, and a plant closure is as much a
#: trigger as a launch.
MOVEMENT = (
    "launch", "announce", "partner", "acquire", "acquisition", "merge", "rollout",
    "roll out", "deploy", "implement", "select", "chose", "chosen", "replace",
    "upgrade", "expand", "invest", "raise", "funding", "appoint", "join", "joined",
    "joins", "hiring", "go live", "went live", "contract", "award", "certif",
    "delist", "bankrupt", "layoff", "restructur", "closure", "shut", "axed",
    "cancel", "divest", "spin off", "spinoff", "ipo", "nasdaq", "nyse",
)

#: Only a whole word counts. Without this, "ai" matches "maintain", "chair" and
#: "available", which on real snippets made almost every post a technology post.
_WORD = {}

#: Terms this long are matched as a **word prefix**, so one entry covers the
#: inflections. Below it they are matched whole.
#:
#: Measured, not guessed. With whole-word matching throughout, `join` did not
#: match "She **joined** Bollinger Innovations as its first…" and `acquire` did
#: not match "acquisition" — real leadership and M&A posts scored zero and were
#: dropped. Prefix matching fixes that; applying it to short terms would not,
#: because `ai` would then match "aid" and "air" and every post would score.
_PREFIX_FROM = 5


#: Boilerplate and spam, recognised by **shape rather than topic**.
#:
#: This is where the saving actually comes from, and it is safer than topic
#: filtering. Measured on real snippets: "KORE Power. 26,264 followers. 7mo.
#: Report this post" is LinkedIn's own chrome, and "ettitude Cozy Earth BAM
#: Clothing Thought Clothing" is a brand list with no sentence in it. Neither
#: says anything about a company whatever lexicon is applied, and both are
#: identifiable without knowing the subject.
_BOILERPLATE = (
    re.compile(r"\b[\d,]+\s+followers\b", re.I),
    re.compile(r"\breport this (?:post|comment)\b", re.I),
    re.compile(r"\b(?:see more|show more|close menu|skip to main)\b", re.I),
)
#: A run of capitalised names with nothing but separators between them is a
#: list, not a post: "ettitude Cozy Earth BAM Clothing Thought Clothing".
#:
#: Six, and no sentence test. The first version required five and also demanded
#: the snippet hold at most one full stop — which the brand lists defeated,
#: because a stored excerpt opens with "Sep 23, 2026 ..." and that is three
#: full stops before the list even starts. Six consecutive capitalised words
#: with no lower-case connective is enough on its own: real prose puts an "and"
#: or a verb in before it gets that far.
_LIST_LIKE = re.compile(r"(?:\b[A-Z][A-Za-z&]+\b[\s,·➤|/-]+){6,}")


def is_boilerplate(text: str | None) -> bool:
    """Whether a snippet is chrome or a name list rather than a post.

    Dropped before scoring, so it never competes for the budget. A topic filter
    cannot do this job — the fraud complaints on one account scored on the same
    terms as a real leadership hire — and a shape filter cannot accidentally
    drop a launch for being about the wrong subject.
    """
    if not text:
        return True
    if any(p.search(text) for p in _BOILERPLATE):
        return True
    return bool(_LIST_LIKE.search(text))


def _folded(text: str | None) -> str:
    """Lowercased, accent-stripped, punctuation turned to spaces.

    Accents matter: one real author slug on this book is
    `deborah-belyea-née-bell`, and a snippet carrying `née` must fold the same
    way a lexicon term does or the match depends on the keyboard someone used.
    """
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return " " + re.sub(r"[^a-z0-9]+", " ", plain.lower()).strip() + " "


def _hits(folded: str, terms: tuple[str, ...]) -> list[str]:
    """Which terms occur, as whole words, in order of the lexicon."""
    found = []
    for term in terms:
        pattern = _WORD.get(term)
        if pattern is None:
            body = re.sub(r"[^a-z0-9]+", " ", term)
            tail = r"[a-z]*" if len(term) >= _PREFIX_FROM else ""
            pattern = _WORD[term] = re.compile(
                r"(?<![a-z0-9])" + body + tail + r"(?![a-z0-9])"
            )
        if pattern.search(folded):
            found.append(term)
    return found


@dataclass
class Scored:
    """One post, with why it scored what it did."""

    index: int
    #: Whole-word technology terms the snippet used.
    technology: list[str] = field(default_factory=list)
    #: Terms drawn from what this installation sells.
    fit: list[str] = field(default_factory=list)
    #: Words saying something changed, rather than an opinion being offered.
    movement: list[str] = field(default_factory=list)
    #: Terms from the **active signal types** — the things extraction is
    #: actually looking for. Scored on the technology axis, because a post that
    #: a live signal type would match is relevant whether or not it happens to
    #: name a technology.
    signal: list[str] = field(default_factory=list)
    observed_at: date | None = None
    #: LinkedIn chrome or a brand list rather than a post. Never kept, and
    #: dropped before scoring so it cannot compete for the budget.
    boilerplate: bool = False

    @property
    def technology_score(self) -> int:
        return len(self.technology) + len(self.movement) + len(self.signal)

    @property
    def fit_score(self) -> int:
        return len(self.fit) + len(self.movement) + len(self.signal)

    @property
    def why(self) -> str:
        """The reason, in words, for a coverage note or a rep's question."""
        bits = []
        if self.technology:
            bits.append("technology: " + ", ".join(self.technology[:4]))
        if self.fit:
            bits.append("fit: " + ", ".join(self.fit[:4]))
        if self.signal:
            bits.append("signal: " + ", ".join(self.signal[:4]))
        if self.movement:
            bits.append("change: " + ", ".join(self.movement[:3]))
        return " · ".join(bits) or "no scoring term matched"


#: Words a service description is full of and that say nothing about a post.
#:
#: Derived from the real lexicon this produced on first run — `that`, `based`,
#: `without`, `faster`, `growing`, `build`, `ship`, `team`, `demo`. Each of
#: those matches a large share of any prose, so a fit score built on them would
#: rank every post equally and look like it was working.
#:
#: Function words plus the generic business verbs, and nothing domain-specific:
#: a word is only removed here if its presence in a post tells us nothing.
_TOO_COMMON = frozenset("""
about above after again against along also among another any anyone around
because been before being below best better between both build building built
came come coming could deliver delivered delivery demo does doing done down
during each either else enough even ever every faster from full gave gets
getting give given gives going gone good great grow growing grown hard have
having help helped helping here high hold into just keep keeping kind know
known large last late less let like likely long look looking made make makes
making many more most much must need needed needs never next none not now
often once only onto other others otherwise over own part parts people
perhaps place put ready really right same ship shipped should side since
small some something soon still such sure take taken takes team teams tell
than that their them then there these they thing things this those though
through time times into took toward under until upon used uses using very
want wanted ways well went were what when where which while whole will with
within without work worked working would your yours base based basis
""".split())


def fit_terms(*sources: object) -> tuple[str, ...]:
    """A fit lexicon from what this installation actually sells.

    Built from config rather than written down here: the service names,
    descriptions and positioning angles are already maintained on the Services
    screen, and a second hand-kept list would be the one that goes stale. An
    installation selling something else gets a different lexicon for free.

    Short words go, because a four-letter fragment of a service name matches
    everything, and so do the words in `_TOO_COMMON` — the first run of this
    produced `that`, `based` and `without` as fit terms, which would have made
    every post score.
    """
    out: set[str] = set()
    for source in sources:
        for value in source if isinstance(source, (list, tuple)) else [source]:
            for word in re.split(r"[^A-Za-z0-9]+", str(value or "")):
                lowered = word.lower()
                if len(lowered) >= 5 and lowered not in _TOO_COMMON:
                    out.add(lowered)
    return tuple(sorted(out))


def score(
    snippets: list[str],
    *,
    fit: tuple[str, ...] = (),
    signals: tuple[str, ...] = (),
    dates: list[date | None] | None = None,
) -> list[Scored]:
    """Score every post. Cheap enough to run on all of them before choosing.

    `signals` is what keeps this filter from undoing extraction's work. The
    first version scored on technology and fit alone and dropped a WeaveGrid
    post reading "After three remarkable years at WeaveGrid, it's time to…" —
    a departure, which `leadership_change_executive` exists to catch, carrying
    no technology word at all. Filtering before extraction means the filter has
    to know what extraction is looking for.
    """
    dates = dates or [None] * len(snippets)
    out = []
    for i, snippet in enumerate(snippets):
        folded = _folded(snippet)
        out.append(
            Scored(
                index=i,
                boilerplate=is_boilerplate(snippet),
                technology=_hits(folded, TECHNOLOGY),
                fit=_hits(folded, tuple(fit)),
                movement=_hits(folded, MOVEMENT),
                signal=_hits(folded, tuple(signals)),
                observed_at=dates[i] if i < len(dates) else None,
            )
        )
    return out


def pick(
    scored: list[Scored],
    *,
    per_bucket: int = 3,
    limit: int = 6,
    window_days: int | None = None,
    today: date | None = None,
) -> list[Scored]:
    """The posts worth storing: the best few on each axis, capped.

    Top `per_bucket` by technology and top `per_bucket` by fit, then merged —
    not a single ranking, because the two scores answer different questions and
    a combined sum lets a long generic post outrank a short specific one.

    Ties break by **recency**, which is free here: every post on this book
    carries a decodable date, 49 of 49 measured. An undated post sorts last
    rather than being dropped — a post with no decodable activity id is a
    parsing gap, not a worthless post.

    **A post scoring nothing is kept only if the budget is not spent.** The
    first version dropped every non-scorer, which measured as an 82% saving and
    a real loss: "Bollinger Innovations confirms Nasdaq delisting" and "Kore
    Power axed a $1.25B Arizona battery plant" both scored zero. A lexicon
    cannot be trusted to recognise every event worth citing, so it decides the
    *order* and the cap decides the *volume* — the saving comes from the cap and
    from `is_boilerplate`, neither of which can discard an event for being
    about an unexpected subject.
    """
    if not scored:
        return []
    live = [s for s in scored if not s.boilerplate]
    if window_days:
        cutoff = (today or date.today()).toordinal() - window_days
        # Undated survives the window: it is unknown, not old. Dropping it here
        # would silently prefer posts whose id happened to parse.
        live = [
            s for s in live
            if s.observed_at is None or s.observed_at.toordinal() >= cutoff
        ]

    def rank(key):
        return sorted(
            live,
            key=lambda s: (-key(s), -(s.observed_at.toordinal() if s.observed_at else 0)),
        )

    chosen: list[Scored] = []
    seen: set[int] = set()
    # Interleaved, so a cap smaller than two full buckets does not spend
    # itself entirely on the technology axis.
    by_tech = [s for s in rank(lambda s: s.technology_score) if s.technology_score][:per_bucket]
    by_fit = [s for s in rank(lambda s: s.fit_score) if s.fit_score][:per_bucket]
    for pair in zip(by_tech + [None] * per_bucket, by_fit + [None] * per_bucket):
        for s in pair:
            if s is not None and s.index not in seen and len(chosen) < limit:
                seen.add(s.index)
                chosen.append(s)

    # Budget left over goes to the most recent of whatever is left, scored or
    # not. This is the safety net for the event the lexicon cannot read, and it
    # costs nothing: the cap is the same either way, so the choice is between
    # storing a recent unscored post and storing nothing at all.
    if len(chosen) < limit:
        for s in sorted(
            (s for s in live if s.index not in seen),
            key=lambda s: -(s.observed_at.toordinal() if s.observed_at else 0),
        ):
            if len(chosen) >= limit:
                break
            seen.add(s.index)
            chosen.append(s)
    return chosen


def note(seen: int, kept: list[Scored]) -> str:
    """What the coverage row says about a decision whose inputs are not stored.

    The dropped posts leave no row — evidence is immutable, so anything stored
    is stored for good, and the point of ranking is not to store them. The
    count has to be written down somewhere or the filter is unauditable.
    """
    if not seen:
        return "no posts indexed"
    if not kept:
        return f"{seen} post(s) seen, all boilerplate or outside the window"
    scored = sum(1 for k in kept if k.technology_score or k.fit_score)
    filled = len(kept) - scored
    bits = [f"{seen} post(s) seen", f"{len(kept)} kept"]
    if filled:
        # Said out loud: these are in because the budget allowed it, not
        # because anything matched. A reader should know the difference.
        bits.append(f"{filled} on recency alone")
    if scored:
        bits.append(kept[0].why)
    return ", ".join(bits[:2]) + (" — " + " · ".join(bits[2:]) if len(bits) > 2 else "")
