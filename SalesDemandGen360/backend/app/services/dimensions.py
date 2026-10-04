"""The dimensions that are facts, and how the ones that are judgements stay put.

Qualification scores six dimensions (docs/02 §6). They are not all the same
kind of thing, and treating them alike is what made scores move between runs
over identical evidence:

* **Facts.** Fit (`services/fit.py`), buyer and engagement each answer a
  question the database already holds the answer to. Buyer — "can we reach
  someone who can say yes?" — is the contacts at the account against the ICP's
  buyer personas and how reachable each one is. Engagement — "have we already got
  traction?" — is the outreach history. A model reading news about a CIO scored
  BlueWave's buyer 75 while nobody at BlueWave had an email address we could use.
  Computed here, the same inputs give the same number, and the reason says why.

* **Judgements.** Opportunity, commercial and intent need a model: whether a
  company's situation is a problem *these services* solve is not arithmetic.
  They are kept steady two ways. The model chooses a step on a five-step scale
  (`LEVELS`), and anything else is rounded to the nearest step — a 25-point step
  does not flicker between 80 and 85. And when nothing the model would be shown
  has changed, the last judgement is kept without asking (`inputs_fingerprint`),
  which is the only way to guarantee the same inputs give the same judgement.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.services import personas
from app.services.verification import matches_persona

#: The basis a computed buyer is stored under.
CONTACTS = "contacts"
#: The basis a computed engagement is stored under.
OUTREACH = "outreach"

#: The steps a judged dimension may land on.
LEVELS = (0, 25, 50, 75, 100)

#: Bumped when the rubric in `instructions.qualification_assessment` or the
#: rounding here changes meaning, so an old judgement is not kept under a new
#: rubric. The prompt text is fingerprinted too; this covers a change made here.
RUBRIC_VERSION = "steps-1"

# ---------------------------------------------------------------- reach ---
#: How reachable a contact is, 0 to 1, by the best route we hold.
#:
#: A verified email is the only route the send gate accepts. A LinkedIn profile
#: is a real channel through La Growth Machine, which is why it outranks an
#: address nobody has checked. A name and a title with no route at all is worth
#: a little — we know who to enrich — and no more.
REACH_VERIFIED_EMAIL = 1.0
REACH_RISKY_EMAIL = 0.6
REACH_LINKEDIN = 0.5
REACH_UNVERIFIED_EMAIL = 0.4
REACH_NAMED_ONLY = 0.15


@dataclass(frozen=True)
class Computed:
    score: float
    basis: str
    reason: str
    icp: str | None = None

    def as_assessment(self) -> dict:
        """The shape every dimension is stored in."""
        return {"score": self.score, "reason": self.reason, "evidence_ids": [], "basis": self.basis}


def reach(contact) -> tuple[float, str]:
    """The best route to one contact, and how it reads to a rep."""
    email = (getattr(contact, "email", None) or "").strip()
    status = getattr(contact, "email_status", None)
    routes: list[tuple[float, str]] = []
    if email and status == "verified":
        routes.append((REACH_VERIFIED_EMAIL, "verified email"))
    elif email and status == "risky":
        routes.append((REACH_RISKY_EMAIL, "email the provider could not confirm"))
    elif email and status == "unverified":
        routes.append((REACH_UNVERIFIED_EMAIL, "email not verified yet"))
    if (getattr(contact, "linkedin_url", None) or "").strip():
        routes.append((REACH_LINKEDIN, "LinkedIn profile"))
    if not routes:
        return REACH_NAMED_ONLY, "no working email or LinkedIn yet"
    return max(routes)


def personas_of(definition: dict) -> list[tuple[str, tuple[str, ...]]]:
    """The ICP's buyer personas as (buying role, titles)."""
    out: list[tuple[str, tuple[str, ...]]] = []
    for entry in (definition or {}).get("personas") or []:
        if isinstance(entry, dict):
            titles = tuple(t for t in entry.get("titles") or [] if isinstance(t, str) and t.strip())
            role = entry.get("buying_role") or ""
            if role or titles:
                out.append((role, titles))
        elif isinstance(entry, str) and entry.strip():
            out.append(("", (entry,)))
    return out


def assess_buyer(contacts: Sequence, definition: dict, *, icp: str | None = None) -> Computed:
    """How reachable this ICP's buying committee is at one account."""
    label = icp or "the ICP"
    roles = personas_of(definition)
    if not roles:
        return Computed(
            0.0, "no_evidence", f"{label} names no buyer personas, so there is nobody to look for.", icp
        )

    credits: list[float] = []
    parts: list[str] = []
    for role, titles in roles:
        name = role.replace("_", " ") if role else "buyer"
        wanted = f"{name} ({', '.join(titles)})" if titles else name
        targets = tuple(t for t in (role, *titles) if t)
        matched = [c for c in contacts if matches_persona(c, targets)]
        if not matched:
            credits.append(0.0)
            parts.append(f"{wanted}: nobody at the account matches")
            continue
        # Best route first, then by name, so the person named is the same
        # person on every run rather than whichever row the database returned.
        best = sorted(matched, key=lambda c: (-reach(c)[0], c.full_name or ""))[0]
        credit, how = reach(best)
        credits.append(credit)
        who = best.full_name + (f", {best.title}" if getattr(best, "title", None) else "")
        parts.append(f"{wanted}: {who} — {how}")

    score = round(100.0 * sum(credits) / len(credits), 2)
    return Computed(score, CONTACTS, f"{label}: " + "; ".join(parts) + ".", icp)


def best_buyer(contacts: Sequence, icps: Sequence[tuple[str, dict]]) -> Computed | None:
    """The best across a list's ICPs, as fit does. None with no ICPs."""
    results = [assess_buyer(contacts, definition or {}, icp=name) for name, definition in icps]
    if not results:
        return None
    return max(results, key=lambda r: r.score)


# ----------------------------------------------------------- engagement ---
#: A reply is traction. Meetings and outcomes are not recorded yet, so a reply
#: is the most this can say — which is why the top of the scale is not reached.
ENGAGEMENT_REPLIED = 75.0


def assess_engagement(*, sent: int, last_sent: datetime | None, replied: bool) -> Computed:
    if replied:
        return Computed(
            ENGAGEMENT_REPLIED,
            OUTREACH,
            "A reply was received — a sequence stopped on it. Meetings are not recorded yet, "
            "so this is as far as it can say.",
        )
    if sent:
        when = f", last on {last_sent:%d %b %Y}" if last_sent else ""
        return Computed(
            0.0,
            OUTREACH,
            f"{sent} touch{'es' if sent != 1 else ''} sent{when}, and no reply recorded. "
            "Sending is not traction.",
        )
    return Computed(0.0, OUTREACH, "No outreach recorded: nothing has been sent to anyone here.")


# ------------------------------------------------------------ judgement ---
def to_level(score: float) -> float:
    """The nearest step. A tie goes up: halfway to "strong" is not "moderate"."""
    clamped = max(0.0, min(100.0, float(score)))
    return float(min(LEVELS, key=lambda level: (abs(level - clamped), -level)))


def prompt_version(prefix_fingerprint: str, model: Sequence) -> str:
    """Everything about *how* the model is asked: prompt, model, rubric."""
    return _digest({"prefix": prefix_fingerprint, "model": list(model), "rubric": RUBRIC_VERSION})


def inputs_fingerprint(
    *, prompt: str, evidence_ids: set[str], signal_ids: set[str], account: dict
) -> str:
    """Everything the model would be shown, and how it would be asked.

    The narrative overlay is left out on purpose: it is itself a model reading
    and differs run to run, so including it would mean nothing ever matched.
    """
    return _digest(
        {
            "prompt": prompt,
            "evidence": sorted(evidence_ids),
            "signals": sorted(signal_ids),
            "account": account,
        }
    )


def _digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = [
    "CONTACTS",
    "LEVELS",
    "OUTREACH",
    "RUBRIC_VERSION",
    "Computed",
    "assess_buyer",
    "assess_engagement",
    "best_buyer",
    "inputs_fingerprint",
    "personas",
    "personas_of",
    "prompt_version",
    "reach",
    "to_level",
]
