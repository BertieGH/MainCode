"""Cadence shape selection and drift detection.

Gen360 never authors a cadence. It selects a registered shape and checks that
the registration still matches what is actually in LGM.

Drift is the dangerous case and it is silent. If someone edits the LGM sequence
— reorders two steps, inserts one — our `attribute_map` still says step 3 reads
`custom_attribute_3`, and the copy written there now lands in a different
message. Nothing errors. The right person receives a real message at a plausible
time saying the wrong thing. So enrolment is refused on any sign the mapping
might be stale, rather than on proof that it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.models.campaign import CadenceShape

#: Even with no reported change, a registration nobody has looked at for this
#: long is not trustworthy — LGM's `updated_at` is polled, and a poll that has
#: been quietly failing looks exactly like a campaign nobody edited.
VERIFICATION_BACKSTOP_DAYS = 90
#: LGM allows twenty custom attributes per lead, globally across campaigns.
#: Checked against a live account rather than taken from the documentation,
#: which said ten and said the overflow was dropped in silence. Writing a
#: twenty-first is refused outright, so a lower cap elsewhere would announce
#: itself rather than cost a touch.
ATTRIBUTE_BUDGET = 20


@dataclass(frozen=True)
class EnrolmentBlock:
    reason: str
    detail: str
    #: A blocker stops the write. A warning does not — it is a true statement
    #: about what will happen next that nobody should have to discover later.
    #: The distinction exists because one of these was a deadlock: see
    #: `never_launched` below.
    severity: str = "block"

    @property
    def blocking(self) -> bool:
        return self.severity == "block"


def check_enrolment(
    shape: CadenceShape, *, now: datetime | None = None
) -> list[EnrolmentBlock]:
    """Everything standing between this shape and an enrolment.

    Returns all blocks rather than the first, so a rep fixing a registration
    sees the whole list instead of discovering them one re-run at a time.
    """
    now = now or datetime.now(UTC)
    blocks: list[EnrolmentBlock] = []

    if not shape.active:
        blocks.append(EnrolmentBlock("inactive", f"shape {shape.key!r} is not active"))

    if not shape.lgm_audience_name:
        blocks.append(
            EnrolmentBlock(
                "no_audience",
                "no LGM audience is registered for this shape — a campaign there runs over an "
                "audience, and writing a lead into it is what enrols them",
            )
        )

    if shape.lgm_status == "ready":
        # A warning, not a blocker, and the reason is a deadlock we walked into
        # with a live account. LGM will not launch a campaign whose audience is
        # empty, and this is what fills it: a campaign runs over an audience,
        # and writing a lead into that audience *is* enrolling them. Blocking
        # the write until the campaign had launched meant it could never launch.
        #
        # Nothing sends in the meantime. The copy sits on the lead, the rep
        # launches once in the LGM app, and LGM starts from step 1.
        blocks.append(
            EnrolmentBlock(
                "never_launched",
                "the LGM campaign has never been launched — this writes the people and their copy "
                "into its audience, and the first launch has to happen in the La Growth Machine "
                "app afterwards. Nothing sends until it does",
                severity="warn",
            )
        )

    if shape.lgm_status == "missing":
        blocks.append(
            EnrolmentBlock(
                "missing_in_lgm",
                "the LGM campaign this shape registers no longer exists — writing leads into its "
                "audience would enrol them into nothing. Register the campaign that replaced it",
            )
        )

    if shape.lgm_status in ("paused", "archived"):
        blocks.append(
            EnrolmentBlock(
                "lgm_status",
                f"the LGM campaign is {shape.lgm_status} and cannot accept enrolments",
            )
        )

    if shape.verified_at is None:
        blocks.append(
            EnrolmentBlock(
                "never_verified",
                f"shape {shape.key!r} has never been checked against the live LGM sequence",
            )
        )
    else:
        verified = _aware(shape.verified_at)
        if shape.lgm_updated_at is not None and _aware(shape.lgm_updated_at) > verified:
            blocks.append(
                EnrolmentBlock(
                    "changed_in_lgm",
                    f"the LGM campaign changed at {_aware(shape.lgm_updated_at).isoformat()}, "
                    f"after this registration was verified at {verified.isoformat()}; "
                    "the attribute mapping may now write copy into the wrong step",
                )
            )
        if now - verified > timedelta(days=VERIFICATION_BACKSTOP_DAYS):
            blocks.append(
                EnrolmentBlock(
                    "stale_verification",
                    f"last verified {(now - verified).days} days ago, over the "
                    f"{VERIFICATION_BACKSTOP_DAYS}-day backstop",
                )
            )

    if shape.attributes_used > ATTRIBUTE_BUDGET:
        blocks.append(
            EnrolmentBlock(
                "attribute_budget",
                f"{shape.attributes_used} attributes exceeds the {ATTRIBUTE_BUDGET}-per-lead cap; "
                "LGM drops the overflow silently",
            )
        )

    mapped = len(shape.attribute_map or {})
    if mapped and mapped < shape.touch_count:
        blocks.append(
            EnrolmentBlock(
                "incomplete_map",
                f"{mapped} of {shape.touch_count} steps are mapped to an attribute; "
                "the unmapped steps would send whatever LGM already holds",
            )
        )

    return blocks


def may_enrol(shape: CadenceShape, *, now: datetime | None = None) -> bool:
    """Whether a lead may be written into this shape's audience.

    Warnings do not count. They describe what happens next — they are not
    reasons to refuse the write.
    """
    return not [b for b in check_enrolment(shape, now=now) if b.blocking]


def enrolment_warnings(shape: CadenceShape, *, now: datetime | None = None) -> list[EnrolmentBlock]:
    return [b for b in check_enrolment(shape, now=now) if not b.blocking]


# `durable_from_step` lived here: the step at and after which a touch could not
# cite a dated signal, derived from the cadence's span. It is gone because its
# only input is gone — LGM publishes no step timing, so a span could only ever
# be typed by a rep, and a rule computed from a typed number is policy wearing
# the costume of a derivation. Shapes registered before this keep the value
# they were given; nothing computes a new one. What stops a stale claim now is
# the pre-send freshness check, which runs against the real date.


def _aware(value: datetime) -> datetime:
    """Postgres gives tz-aware values back; hand-built ones may not be."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class SelectionInput:
    email_status: str
    #: `small`, `mid`, `large` or `unknown` — see `services.sizing`. Derived
    #: from headcount rather than classified, so a shape can be chosen for an
    #: account nobody has researched yet.
    size_band: str | None
    priority_band: str


def select_shape_key(facts: SelectionInput) -> tuple[str, dict]:
    """Deterministic, no LLM. Returns the shape key and why it was chosen.

    The `selection_log` this produces is what makes "why did this account get
    the enterprise cadence?" answerable from the row, months later.
    """
    if facts.email_status != "verified":
        return "linkedin_only_5_15", {
            "rule": "unverified_email",
            "fact": {"email_status": facts.email_status},
        }
    # Our band names, LGM's shape names. Deliberately different: the shapes are
    # registered in LGM and are not ours to rename, so mapping across the gap
    # keeps the two vocabularies from being coupled by coincidence.
    if facts.size_band == "large":
        return "enterprise_8_23", {"rule": "size_band", "fact": {"size_band": "large"}}
    if facts.size_band == "small":
        return "startup_5_11", {"rule": "size_band", "fact": {"size_band": "small"}}
    if facts.priority_band == "medium":
        return "nurture_4_21", {"rule": "priority_band", "fact": {"priority_band": "medium"}}
    return "standard_6_15", {"rule": "default", "fact": {}}
