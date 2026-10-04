"""Persona × service weighting, and thread selection.

The weighting is deterministic Python for the same reason scoring is: it has to
be explainable to a rep who asks why the CFO was not contacted, and the answer
"the model felt that way" is not one. The LLM writes the hypothesis and the
positioning for the threads that were selected; it does not choose who is
worth talking to.

Ranking is driven by three things, in decreasing order of trust:

1. **Contact signals** — evidence about this specific person. Someone who
   posted about the problem last month outranks a guess from a job title.
2. **Buying role** — the configured `persona_role_weights`.
3. **Service fit** — whether the service targets this persona at all.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

DEFAULT_ROLE_WEIGHT = 20.0
#: What a contact-scoped signal is worth relative to a title. Deliberately
#: large: `docs/02` says evidence about someone beats a guess from their title,
#: and a small nudge would leave title-based ordering effectively untouched.
SIGNAL_WEIGHT = 25.0
#: Diminishing returns. Five signals about one person is not five times the
#: reason to contact them, and without this a noisy contact would crowd out a
#: better-placed one on volume alone.
SIGNAL_DECAY = 0.6


@dataclass(frozen=True)
class PersonaInput:
    contact_id: uuid.UUID
    full_name: str
    buying_role: str | None = None
    seniority: str | None = None
    #: Contact-scoped signals about this person, as (signal_id, strength).
    signals: tuple[tuple[uuid.UUID, str], ...] = ()
    contactable: bool = True


@dataclass(frozen=True)
class ServiceInput:
    service_id: uuid.UUID
    code: str
    target_personas: tuple[str, ...] = ()


@dataclass
class Cell:
    """One persona × service pair, scored and explained."""

    contact_id: uuid.UUID
    service_id: uuid.UUID
    weight: float
    rationale: str
    evidence_ids: list[str] = field(default_factory=list)


STRENGTH_VALUE = {"high": 1.0, "medium": 0.65, "low": 0.35}


def _signal_bonus(signals: tuple[tuple[uuid.UUID, str], ...]) -> float:
    """Strongest signal counts fully; each further one counts less."""
    ranked = sorted(
        signals, key=lambda s: STRENGTH_VALUE.get(s[1], 0.35), reverse=True
    )
    return sum(
        STRENGTH_VALUE.get(strength, 0.35) * SIGNAL_WEIGHT * (SIGNAL_DECAY**i)
        for i, (_, strength) in enumerate(ranked)
    )


def build_matrix(
    personas: list[PersonaInput],
    services: list[ServiceInput],
    *,
    persona_role_weights: dict[str, float] | None = None,
) -> list[Cell]:
    """Every persona against every service. Nothing is filtered out here.

    Cells that score zero are kept: the matrix is the record of a decision not
    to act, and that decision is invisible if only the winners are stored.
    """
    role_weights = {k: float(v) for k, v in (persona_role_weights or {}).items()}
    cells: list[Cell] = []

    for persona in personas:
        role = persona.buying_role or "unknown"
        role_score = role_weights.get(role, DEFAULT_ROLE_WEIGHT)
        bonus = _signal_bonus(persona.signals)

        for service in services:
            targeted = not service.target_personas or role in service.target_personas
            fit = 1.0 if targeted else 0.35

            weight = (role_score + bonus) * fit
            if not persona.contactable:
                # No verified way to reach them. Kept in the matrix with the
                # reason recorded, rather than dropped as though never
                # considered — "we could not reach them" is an answer.
                weight = 0.0

            reasons = [f"buying role {role} weighted {role_score:g}"]
            if bonus:
                reasons.append(f"{len(persona.signals)} contact signal(s) add {bonus:.1f}")
            if not targeted:
                reasons.append(f"service {service.code} does not target {role}")
            if not persona.contactable:
                reasons.append("no verified contact route")

            cells.append(
                Cell(
                    contact_id=persona.contact_id,
                    service_id=service.service_id,
                    weight=round(weight, 2),
                    rationale="; ".join(reasons),
                    evidence_ids=[str(sid) for sid, _ in persona.signals],
                )
            )

    return cells


@dataclass
class SelectedThread:
    contact_id: uuid.UUID
    service_id: uuid.UUID
    weight: float
    rank: int
    thread_status: str
    start_offset_days: int


def select_threads(
    cells: list[Cell],
    *,
    persona_weight_threshold: float,
    max_concurrent_threads: int,
    thread_start_offset_days: int,
) -> list[SelectedThread]:
    """Rank personas and apply the sales rules.

    One thread per contact — their best service, not every service they might
    plausibly care about. A person contacted twice about the same account is
    the failure this layer exists to prevent, and it does not become acceptable
    because the second message is about something else.

    The cap is a sales rule enforced here, not a judgement the model gets to
    make. Personas above the threshold but beyond the cap are `queued`: we
    would run them given room, which is a different fact from failing on merit.
    """
    best: dict[uuid.UUID, Cell] = {}
    for cell in cells:
        current = best.get(cell.contact_id)
        # Tie-broken on service_id so two equal services do not reorder
        # between runs and produce a different primary each time.
        if current is None or (cell.weight, str(cell.service_id)) > (
            current.weight,
            str(current.service_id),
        ):
            best[cell.contact_id] = cell

    ordered = sorted(
        best.values(), key=lambda c: (-c.weight, str(c.contact_id))
    )

    threads: list[SelectedThread] = []
    activated = 0
    for i, cell in enumerate(ordered, start=1):
        if cell.weight < persona_weight_threshold:
            status, offset = "not_activated", 0
        elif activated < max_concurrent_threads:
            status = "active_primary" if activated == 0 else "active_secondary"
            # Staggered so two contacts at one company are not touched the same
            # day. Offset counts activated threads, not rank, or a
            # `not_activated` persona would silently push the next one out.
            offset = activated * thread_start_offset_days
            activated += 1
        else:
            status, offset = "queued", 0

        threads.append(
            SelectedThread(
                contact_id=cell.contact_id,
                service_id=cell.service_id,
                weight=cell.weight,
                rank=i,
                thread_status=status,
                start_offset_days=offset,
            )
        )
    return threads


class DifferentiationError(ValueError):
    """Two threads at one account making the same argument.

    Not a style problem. Two people at one company receiving materially the
    same message is how an account learns it is being automated at, and the
    whole premise of multi-threading is that different roles feel a different
    version of the problem.
    """


def assert_differentiated(hypotheses: dict[uuid.UUID, str]) -> None:
    """Reject identical problem hypotheses across active threads."""
    seen: dict[str, uuid.UUID] = {}
    for contact_id, text in hypotheses.items():
        key = " ".join(text.lower().split())
        if key in seen:
            raise DifferentiationError(
                f"contacts {seen[key]} and {contact_id} were given the same problem "
                "hypothesis; multi-threading requires a per-persona argument"
            )
        seen[key] = contact_id


def check_triggers(
    trigger_signal_ids: list[str], live_signal_ids: set[str]
) -> list[str]:
    """Return the cited triggers that are no longer live.

    A thread whose trigger has expired is pitching on a stale premise — "I saw
    you raised a round" about a round from two years ago is worse than saying
    nothing, because it reads as automation that did not check.
    """
    return [s for s in trigger_signal_ids if s not in live_signal_ids]
