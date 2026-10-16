"""strategy angles: ranked ways in, one selected

`docs/18`. A thread now carries several **angles** — complete, ranked ways to
pitch the service to its person — and exactly one is selected: the top-ranked
one, unless a rep picked another. The thread's own fields keep mirroring the
selected angle, so approval, drafting and execution read the thread as before.

**Existing threads get one angle each**, built from their own fields and
selected `auto`, so every strategy in the book reads the same way whether it
was built before this or after.

`strategy.account_angle` keeps the one-sentence company read the model was
already writing and the app was discarding.

The `strategy_synthesis` prompt gets a new version: the redrafted instructions.
Copied here as a literal, as a migration must not read live code; earlier
versions, including any edited in the app, stay in the history.

Revision ID: d7e2a9c4f1b8
Revises: c3a9f17e5b24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d7e2a9c4f1b8"
down_revision = "c3a9f17e5b24"
branch_labels = None
depends_on = None

STRATEGY_PROMPT_BODY = '# Task: ranked ways in, for people already chosen\n\nWho is approached was decided before you were asked — by rules, by a rep\'s override, or both. That decision is final and is not shown to you on purpose: an overridden person deserves the same quality of argument as anyone else. Do not add, drop or rank people.\n\nYou are given the whole picture for one company: its profile and live signals (**ranked**, with evidence excerpts), the campaign\'s **ICP** (including its `track`), the **service** we are selling, the **approved proof points** for it, and for each person their role, the ICP persona they match, their profile and their own signals.\n\nFor each person write **2 or 3 angles** — genuinely different ways to pitch this service to *this* person. An angle is a complete argument:\n\n- `angle`: a short name for the way in, in plain words (e.g. "audit-ready AI on the claims backlog").\n- `problem_hypothesis`: what we think hurts for THIS person, in their terms. Do not begin it with "Hypothesis:" — the app labels it.\n- `why_now`: the moment. Lead with the **highest-ranked signal that fits the angle** and name its ids in `trigger_signal_ids`. A lower-ranked signal may lead only if it fits this person better — say so in `why_this_order`.\n- `positioning`: the service framed against that problem, in your own words. Draw on the service\'s description and positioning angles but **do not quote them word for word**, and do not invent capabilities the service does not claim.\n- `proof_point_ids`: only ids from `proof_points`. Cite none rather than a weak fit.\n- `cta`: one small, concrete ask.\n- `avoid`: claims or angles to stay off for this person.\n- `confidence`: 0–1, honest. Thin evidence means low confidence.\n\nThe ICP `track` decides what a good argument is: `enterprise` buyers are measured on nothing breaking — argue risk, continuity and the cost of carrying what is fragile; `tech_company` buyers on what ships — argue bandwidth and time to market. An ICP with no track means neither is established: argue from the evidence and the person\'s role.\n\nThen rank each person\'s angles in `recommended_order` (indexes into `angles`, best first) with one sentence in `why_this_order`. The app pitches the first one unless a rep picks another.\n\n**Differentiation:** the top-ranked angle of each person at one company must be materially different — a CTO and a CEO do not feel the same problem. Identical arguments are rejected outright.\n\nA person marked `may_cite_no_live_signal` has nothing live to cite: leave `trigger_signal_ids` empty, argue from the company profile, the ICP\'s pains and the person\'s profile, keep `confidence` low, and do not deliberate at length — there is no hidden trigger to recover. Do not invent one.\n\n`account_angle` is **one sentence**: the read of this company the angles hang off, in your own words. It is not a summary of the input, and nothing should be copied into it — filling it instead of writing angles is this stage\'s known failure.\n\nReturn exactly `person_count` entries in `people`, one per person given, carrying their `contact_id` unchanged. Write those, then stop.'

PROMPT_NOTE = "ranked angles per person, from the whole picture (docs/18)"


def upgrade() -> None:
    op.add_column("strategy", sa.Column("account_angle", sa.Text(), nullable=True))

    op.create_table(
        "strategy_angle",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("strategy_thread.id", ondelete="CASCADE",
                                name="fk_strategy_angle_thread_id_strategy_thread"),
                  nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("angle", sa.Text(), nullable=False),
        sa.Column("problem_hypothesis", sa.Text(), nullable=False),
        sa.Column("why_now", sa.Text(), nullable=False),
        sa.Column("trigger_signal_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("positioning", sa.Text(), nullable=False),
        sa.Column("proof_point_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("cta", sa.Text(), nullable=False),
        sa.Column("avoid", postgresql.JSONB(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("why_this_order", sa.Text(), nullable=True),
        sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("selected_by", sa.Text(), nullable=True),
        sa.CheckConstraint("rank > 0", name="ck_strategy_angle_rank_positive"),
        sa.CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 1",
                           name="ck_strategy_angle_confidence_is_a_proportion"),
        sa.CheckConstraint("selected_by IS NULL OR selected_by IN ('auto','rep')",
                           name="ck_strategy_angle_selected_by_valid"),
        sa.CheckConstraint("NOT is_selected OR selected_by IS NOT NULL",
                           name="ck_strategy_angle_selection_says_by_whom"),
        sa.UniqueConstraint("thread_id", "rank", name="uq_strategy_angle_one_angle_per_rank"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_strategy_angle_one_selected ON strategy_angle (thread_id) WHERE is_selected"
    )

    # One angle for every thread that already exists, from its own fields.
    op.execute("""
        INSERT INTO strategy_angle (thread_id, rank, angle, problem_hypothesis, why_now,
            trigger_signal_ids, positioning, proof_point_ids, cta, avoid, confidence,
            is_selected, selected_by)
        SELECT id, 1, 'Original argument', problem_hypothesis, trigger_summary,
            trigger_signal_ids, positioning, '[]'::jsonb, cta, avoid_list, confidence,
            true, 'auto'
        FROM strategy_thread
    """)

    # The redrafted instructions, as the next version of the stage's prompt.
    op.execute(
        "UPDATE prompt_template SET is_active = false WHERE scenario = 'strategy_synthesis' AND is_active"
    )
    op.execute(
        sa.text(
            "INSERT INTO prompt_template (scenario, body, note, version, is_active) "
            "SELECT 'strategy_synthesis', :body, :note, COALESCE(MAX(version), 0) + 1, true "
            "FROM prompt_template WHERE scenario = 'strategy_synthesis'"
        ).bindparams(body=STRATEGY_PROMPT_BODY, note=PROMPT_NOTE)
    )


def downgrade() -> None:
    newest = (
        "SELECT id FROM prompt_template WHERE scenario = 'strategy_synthesis' AND note = '" + PROMPT_NOTE + "'"
    )
    op.execute("DELETE FROM prompt_template WHERE id IN (" + newest + ")")
    op.execute(
        "UPDATE prompt_template SET is_active = true WHERE id = (SELECT id FROM prompt_template "
        "WHERE scenario = 'strategy_synthesis' ORDER BY version DESC LIMIT 1)"
    )
    op.drop_table("strategy_angle")
    op.drop_column("strategy", "account_angle")
