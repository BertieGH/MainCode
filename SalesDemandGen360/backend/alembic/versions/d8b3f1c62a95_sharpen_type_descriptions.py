"""Sharpen the descriptions the extractor chooses between, and name the gate.

A signal type's description is not documentation: it is what extraction reads to
decide which type a passage belongs to. Two pairs were colliding on the same
sentence, so the choice between them was a coin toss on the model's mood.

* `engineering_team_expansion` and `hiring_bottleneck` **both** offered "several
  related roles open at once" as evidence. They are opposite readings of one
  careers page - roles opening because the company is growing, against roles
  that will not fill. The phrase now belongs to expansion alone, and the
  bottleneck keeps duration and repetition, which is what actually distinguishes
  it.
* `tech_debt_modernization` and `digital_transformation_mandate` both offered
  "move to cloud". They are now anchored on different things: the first on **the
  old system being named**, the second on **the programme being declared**, with
  a stated tie-break (prefer the system, because a system is a fact and a
  programme is a plan).
* `strategic_partnership_alliance` and `product_launch` both covered "a new
  offering". A **second named party** is now the discriminator.
* `tech_stack_expansion` says adoption only, and points elsewhere for migration
  and for supplier reduction.
* `leadership_change_executive` says that its overlap with `contact_role_change`
  is deliberate and when to use which - it was true before and written nowhere.

Each one now names its sibling. A description that only says what a type *is*
leaves the extractor to infer the boundary; naming the neighbour makes the
boundary the thing it reads.

**The gate, which is the bigger half.** The active ICP's `signals_that_matter`
is what `ListPlan.type_keys` returns, and that is *what extraction may return* -
so a type absent from it cannot produce a signal however well it is configured.
Eight of fifteen were absent, including all seven Enterprise IT types added for
this book in `d7a4e1c93b26`: inert from the day they were created, and reported
only as "never produced anything". The list is corrected to name every live type
(ICP v11, through the API so the version chain is intact), and
`SignalTypeOut.extractable` now carries the answer so the next gap announces
itself.

Revision ID: d8b3f1c62a95
Revises: c1f7e3b89d24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d8b3f1c62a95"
down_revision = "c1f7e3b89d24"
branch_labels = None
depends_on = None

#: key -> the description the extractor reads. Written out in full rather than
#: patched, because a half-applied wording is worse than either version.
DESCRIPTIONS = {'digital_transformation_mandate': 'A leadership-level programme to digitise manual work, '
                                   'move to cloud, or build client or employee portals. '
                                   'Anchored on **the programme being declared**: it must '
                                   'be stated as an initiative the company is running, '
                                   'with a named programme or a named person behind it. An '
                                   'aspiration on a marketing page is not one.\\n\\nNot '
                                   'tech_debt_modernization, which is anchored on the old '
                                   'system being named. If the evidence names what is '
                                   'being replaced, that one is the better fit; this one '
                                   'is for a stated direction of travel where no specific '
                                   'legacy platform is identified.',
 'engineering_team_expansion': 'The company is growing a software engineering or technical '
                               'team: several related technical roles open at once, a '
                               'newly created engineering function, or stated growth of a '
                               'development team. The conclusion is capability being built '
                               'that was not there before.\\n\\nNot hiring_bottleneck, '
                               'which is the opposite reading of similar evidence: this '
                               'one is roles opening because the company is expanding, '
                               'that one is roles that will not fill. If the same role has '
                               'been re-posted or has sat open for months, it is the '
                               'bottleneck, not expansion. If you cannot tell which, say '
                               'so and pick the bottleneck — an unfilled role is the more '
                               'reliable reading, because an advert proves demand but not '
                               'growth.',
 'hiring_bottleneck': 'The company cannot fill roles it has been advertising. The evidence '
                      'is duration or repetition: a role open unusually long, or the same '
                      'role re-posted. Several roles open at once is NOT evidence for this '
                      'on its own — that is engineering_team_expansion, which is the '
                      'growth reading of the same page.\\n\\nFor a non-technology business '
                      'this is more often backfilling institutional knowledge after a '
                      'retirement or a resignation than scaling a team, and that is the '
                      'more useful reading, because the knowledge leaving is the problem.',
 'leadership_change_executive': 'A CIO, CTO, VP of IT, COO or head of operations started '
                                'at this company in the last ninety days. The conclusion '
                                'is not that a person changed job; it is that a review of '
                                'inherited systems and suppliers usually follows, and that '
                                'window is short.\\n\\nThis is the company-scoped reading '
                                'and it **overlaps contact_role_change on purpose**. Use '
                                'this one when the evidence tells us the seat changed — a '
                                'trade-press appointment notice, a team page — whether or '
                                'not that person is a contact we track. Use '
                                'contact_role_change when the person is one of our '
                                'contacts and the change is about them. Both firing on the '
                                'same evidence is acceptable: one is a fact about the '
                                'account, the other about a thread. Restricted to '
                                'technology and operations seats, because a new head of '
                                'marketing does not review the policy administration '
                                'system.',
 'product_launch': 'The company has brought something new to market on its own, and it is '
                   'live, not planned. Read this against whatever that company actually '
                   'sells: for a broker or carrier a new scheme, programme, cover or '
                   'service line; for an ISV or SaaS vendor a product or a named feature; '
                   'for anyone a new portal, platform or offering their customers can now '
                   'buy or use. A software feature is one instance of this and not the '
                   'definition — do not pass over a launch because nothing was shipped as '
                   'code.\\n\\nIf a second firm is named as a partner in the launch, it is '
                   'strategic_partnership_alliance instead. What makes it a signal either '
                   'way is that a company taking something to market has just taken on the '
                   'work of supporting, integrating and selling it.',
 'strategic_partnership_alliance': 'A named partnership, alliance, carrier appointment, or '
                                   'a new offering made jointly with another firm. **A '
                                   'second party must be named** — that is what separates '
                                   'this from product_launch, where the company brought '
                                   'something to market on its own. Keep both names and '
                                   'the date.\\n\\nWhat makes it a signal is integration '
                                   'work: two firms announcing a joint offering have '
                                   'committed to connecting two systems and supporting the '
                                   'result.',
 'tech_debt_modernization': 'The company is carrying ageing systems, or has said it is '
                            'replacing them. This type is anchored on **the old thing '
                            'being named**: an agency management system, an ERP, a claims '
                            'or policy administration system, an on-premise estate, an '
                            'end-of-support date, or a job advert asking for a legacy '
                            'skill, which is evidence the system is still '
                            'running.\\n\\nNot digital_transformation_mandate, which is '
                            'anchored on a declared programme. A cloud migration qualifies '
                            'here when the evidence names what is being migrated off, and '
                            'there when the evidence names the initiative and who owns it. '
                            'If both are named, prefer this one — the system is a fact and '
                            'the programme is a plan.',
 'tech_stack_expansion': 'A tool, platform or stack choice the company has adopted, named '
                         'publicly — in a job advert, an engineering post, an integrations '
                         'page or a stack-detection index. The conclusion is what the '
                         'delivery environment actually is.\\n\\nAdoption only. If the '
                         'evidence is about getting off something ageing, that is '
                         'tech_debt_modernization; if it is about cutting the number of '
                         'suppliers, that is vendor_consolidation. A tool appearing in a '
                         'list of requirements is adoption; a tool appearing next to the '
                         "word 'migration' usually is not."}


def upgrade() -> None:
    conn = op.get_bind()
    for key, description in DESCRIPTIONS.items():
        conn.execute(
            sa.text(
                "UPDATE signal_type SET description = :d, updated_at = now() "
                "WHERE key = :k"
            ).bindparams(d=description, k=key)
        )
    # Every live type becomes eligible for extraction. Written across the active
    # ICPs only: historical versions are the record of what a finished run was
    # told to look for, and rewriting them would make that unanswerable.
    conn.execute(
        sa.text(
            "UPDATE icp_profile_version SET definition = jsonb_set("
            "  definition, '{signals_that_matter}',"
            "  (SELECT coalesce(jsonb_agg(key ORDER BY key), '[]'::jsonb) FROM signal_type)"
            ") WHERE is_active AND definition ? 'signals_that_matter'"
        )
    )


def downgrade() -> None:
    """Nothing. A downgrade cannot restore wording it never recorded, and
    putting the old colliding descriptions back would reinstate the coin toss
    this migration exists to remove."""
