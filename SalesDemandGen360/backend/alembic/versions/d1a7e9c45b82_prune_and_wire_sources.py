"""Stop paying for three things that produced nothing; point four sources at work.

Measured over ten accounts researched on 2026-10-05, reading `llm_call` and
`research_coverage` together:

    family                      calls   evidence
    fast_sweep                     13         25
    company_site                    8         11   (fetch - no model call)
    reviews                         8          4
    news                           11          3
    hiring                          8          2
    funding                         8          1
    leadership                     11          1
    tech_stack                      8          0
    type:contact_role_change        6          0

**The savings.** `tech_stack` and `funding` are technology-track sources being
run against a book of insurance brokerages: sixteen calls between them for one
piece of evidence. They are pruned from the ICP rather than paused globally, so
they remain available the day a technology ICP exists. `contact_role_change`
carried its own `search_instruction` — six calls, nothing found — and an
instruction is meant to be the exception that earns its extra search. This one
did not.

**The wiring.** Four sources were registered in `a9c3e7f21b64` and never ran: no
signal type named them in `produced_by`, so `build_plan` never planned them.
Registered and inert. They are pointed at the types they serve here.

**The arithmetic, stated because it is not obvious.** Three of the four cost a
model call; `trust_security_portals` is a fetch and costs none. So +3 against
-3: the same number of calls per account, aimed at places that returned
evidence under test (§65) rather than at a stack-detection index for a company
with no stack. The next run is the measurement that says whether the aim was
better.

Revision ID: d1a7e9c45b82
Revises: c8e2a4f71d03
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "d1a7e9c45b82"
down_revision = "c8e2a4f71d03"
branch_labels = None
depends_on = None

#: Pruned from this ICP, not from the registry: a book of brokerages does not
#: raise venture rounds or publish an engineering blog.
PRUNED = ["funding", "tech_stack"]

#: Added to the ICP so the plan may reach them at all.
ADDED = [
    "press_wire_aggregators",
    "regulatory_and_filings",
    "careers_domain_direct",
    "trust_security_portals",
]

#: source -> the signal types it feeds. A source nothing names is never
#: planned, which is why the four sat inert.
WIRING = {
    "press_wire_aggregators": [
        "m_and_a_integration",
        "leadership_change_executive",
        "vendor_consolidation",
        "strategic_partnership_alliance",
        "digital_transformation_mandate",
        "product_feature_launch",
    ],
    "regulatory_and_filings": [
        "m_and_a_integration",
        "compliance_security_deadline",
    ],
    "careers_domain_direct": [
        "hiring_bottleneck",
        "engineering_team_expansion",
        "tech_debt_modernization",
    ],
    "trust_security_portals": ["compliance_security_deadline"],
}


def upgrade() -> None:
    conn = op.get_bind()

    for source, types in WIRING.items():
        conn.execute(
            sa.text(
                """
                UPDATE signal_type
                   SET produced_by = array_append(produced_by, :s)
                 WHERE key = ANY(:t) AND NOT (:s = ANY(produced_by))
                """
            ).bindparams(s=source, t=types)
        )

    # Six calls, nothing found. An instruction is the exception that earns an
    # extra search per account; this one did not earn it.
    conn.execute(
        sa.text(
            "UPDATE signal_type SET search_instruction = NULL, search_group = NULL "
            "WHERE key = 'contact_role_change'"
        )
    )

    _retarget_icps(conn)


def _retarget_icps(conn) -> None:
    """Drop the technology-track sources from each ICP and add the new ones.

    Rewritten in Python rather than with a jsonb expression: the value is an
    array of strings being filtered and extended, and the SQL version of that
    is a `jsonb_array_elements` subquery nobody will read again.
    """
    rows = conn.execute(
        sa.text(
            "SELECT id, definition FROM icp_profile_version WHERE definition ? 'sources'"
        )
    ).all()
    for row_id, definition in rows:
        current = definition.get("sources") or []
        kept = [s for s in current if s not in PRUNED]
        # dict.fromkeys rather than a set: the order a rep put them in is worth
        # keeping, and re-running this migration must not duplicate an entry.
        definition["sources"] = list(dict.fromkeys([*kept, *ADDED]))
        conn.execute(
            sa.text(
                "UPDATE icp_profile_version SET definition = CAST(:d AS jsonb) "
                "WHERE id = :i"
            ).bindparams(d=json.dumps(definition), i=row_id)
        )


def downgrade() -> None:
    conn = op.get_bind()
    for source in WIRING:
        conn.execute(
            sa.text(
                "UPDATE signal_type SET produced_by = array_remove(produced_by, :s)"
            ).bindparams(s=source)
        )
    rows = conn.execute(
        sa.text(
            "SELECT id, definition FROM icp_profile_version WHERE definition ? 'sources'"
        )
    ).all()
    for row_id, definition in rows:
        kept = [s for s in (definition.get("sources") or []) if s not in ADDED]
        definition["sources"] = list(dict.fromkeys([*kept, *PRUNED]))
        conn.execute(
            sa.text(
                "UPDATE icp_profile_version SET definition = CAST(:d AS jsonb) "
                "WHERE id = :i"
            ).bindparams(d=json.dumps(definition), i=row_id)
        )
