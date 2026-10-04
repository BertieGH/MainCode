"""Seed a walkthrough dataset by running the real services end to end.

This is not fixture SQL. Every row below goes through the same code the
pipeline uses — `store_batch` resolves citations, `score` does the weighted
roll-up, `select_threads` applies the cap, `store_arc` validates durability
banding, `draw` takes a server-side sample. So a successful seed is also a
demonstration that Phases 2–9 compose, and a failure here is a real defect
rather than a broken fixture.

What it does **not** do is call Claude. There are no LLM call sites in the
codebase yet; the summaries, hypotheses and copy below are written by hand and
marked as demo data so nobody mistakes them for model output.

    python scripts/seed_demo.py          # add the demo data
    python scripts/seed_demo.py --clear  # remove it again

Everything it creates is tagged so `--clear` can find it: accounts by domain,
config rows by the DEMO marker in their text.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models.account import Account, AccountList, AccountListMember, Contact  # noqa: E402
from app.models.campaign import (  # noqa: E402
    CadenceShape,
    CampaignQueue,
    LgmIdentity,
    OutreachSequence,
)
from app.models.config import (  # noqa: E402
    LlmConfig,
    OrgProfile,
    ProofPoint,
    SalesRules,
    ScoringConfig,
    ServiceCatalog,
    SignalType,
    WritingSample,
)
from app.models.content import Draft, Touch  # noqa: E402
from app.models.context import AccountContext, Qualification  # noqa: E402
from app.models.execution import ExecutionRecord  # noqa: E402
from app.models.governance import Approval, ApprovalSample, Evaluation  # noqa: E402
from app.models.research import ResearchCoverage  # noqa: E402
from app.models.signal import Evidence, Signal, signal_evidence  # noqa: E402
from app.models.strategy import PersonaServiceScore, Strategy, StrategyThread  # noqa: E402
from app.schemas.draft import DraftSet, TouchDraft  # noqa: E402
from app.schemas.qualification import DimensionAssessment, DimensionAssessments  # noqa: E402
from app.schemas.signal import SignalBatch  # noqa: E402
from app.services.approval import Candidate, draw, stratify  # noqa: E402
from app.services.cadence import durable_from_step  # noqa: E402
from app.services.context import build_context, store_qualification  # noqa: E402
from app.services.crm import StubCrmAdapter  # noqa: E402
from app.services.drafting import band_for_step, store_arc  # noqa: E402
from app.services.extraction import store_batch  # noqa: E402
from app.services.pipeline import run_research  # noqa: E402
from app.services import sizing  # noqa: E402
from app.services.promotion import add_member, promote  # noqa: E402
from app.services.scoring import score  # noqa: E402
from app.services.strategy import (  # noqa: E402
    PersonaInput,
    ServiceInput,
    build_matrix,
    select_threads,
)

#: Stamped on everything this script writes, so --clear is exact.
DEMO = "[demo]"
DOMAINS = ("MERIDIANCLOUD.DEMO", "NORTHWIND-LOGISTICS.DEMO")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
async def _active(session, model):
    return (
        await session.execute(select(model).where(model.is_active.is_(True)))
    ).scalar_one_or_none()


async def seed_config(session) -> dict:
    # Identity only. Who we sell *to* is seeded as an `IcpProfile` below,
    # linked to the services that sell to it.
    org = await _active(session, OrgProfile) or OrgProfile(
        name="CGVAK Software Exports",
        description=f"{DEMO} Engineering partner for product teams that need to ship faster.",
        version=1,
        is_active=True,
    )
    if org.id is None:
        session.add(org)

    have = {
        s.code for s in (await session.execute(select(ServiceCatalog))).scalars()
    }
    services = [
        ServiceCatalog(
            code="qa_engineering",
            name="QA engineering",
            description=f"{DEMO} Embedded QA that absorbs a growing engineering team.",
            positioning_angles=["ship faster without a quality cliff"],
            economic_buyer="VP Engineering",
        ),
        ServiceCatalog(
            code="data_platform",
            name="Data platform",
            description=f"{DEMO} Warehouse, pipelines and reporting that survive scale.",
            positioning_angles=["one number everyone trusts"],
            economic_buyer="CFO",
        ),
    ]
    services = [s for s in services if s.code not in have]
    if services:
        session.add_all(services)
    await session.flush()
    services = list(
        (
            await session.execute(
                select(ServiceCatalog).where(
                    ServiceCatalog.code.in_(("qa_engineering", "data_platform"))
                )
            )
        ).scalars()
    )

    have_pp = {
        p.title for p in (await session.execute(select(ProofPoint))).scalars()
    }
    proof_points = [
            ProofPoint(
                service_id=services[0].id,
                kind="case_study",
                title=f"{DEMO} Retail platform cut regression time 60%",
                body="An 80-engineer retail platform moved regression from 9 days to 3.",
                client_industry="Retail",
                client_size_band="200-500",
                metrics={"regression_days_before": 9, "regression_days_after": 3},
                is_approved=True,
            ),
            ProofPoint(
                service_id=services[1].id,
                kind="metric",
                title=f"{DEMO} Logistics client — unreviewed claim",
                body="Reported a 40% drop in reporting turnaround. Not yet verified.",
                is_approved=False,
            ),
    ]
    session.add_all([p for p in proof_points if p.title not in have_pp])

    have_ws = {
        w.body for w in (await session.execute(select(WritingSample))).scalars()
    }
    samples = [
            WritingSample(
                channel="email",
                subject="Quick one about your QA load",
                body=(
                    f"{DEMO} Saw you're hiring six backend engineers. Usually the "
                    "bottleneck that shows up next is regression, not headcount. "
                    "Worth fifteen minutes?"
                ),
                notes="Short, specific, no adjectives. This is the house voice.",
            ),
            WritingSample(
                channel="linkedin",
                body=f"{DEMO} Congrats on the round — what's the first thing that breaks at 2x?",
                notes="One line, one question, no pitch.",
            ),
    ]
    session.add_all([w for w in samples if w.body not in have_ws])

    # Reuse the active config only if it is actually usable. A row predating
    # the six-dimension validator scores every account on whatever it happens
    # to carry, so the seed adds a correct new version rather than mutating it
    # — which is the versioning pattern the config tables already use.
    current_scoring = await _active(session, ScoringConfig)
    usable = current_scoring is not None and set(current_scoring.dimension_weights) >= {
        "fit", "opportunity", "buyer", "commercial", "intent", "engagement"
    }
    if current_scoring is not None and not usable:
        current_scoring.is_active = False
        await session.flush()
        print(
            f"  note: scoring_config v{current_scoring.version} carried only "
            f"{sorted(current_scoring.dimension_weights)} — deactivated and superseded"
        )
    scoring = (current_scoring if usable else None) or ScoringConfig(
        version=1,
        dimension_weights={
            "fit": 20, "opportunity": 20, "buyer": 15,
            "commercial": 15, "intent": 20, "engagement": 10,
        },
        # Keyed on the normalised industry, so "SaaS" on the account matches.
        industry_multipliers={"saas": {"intent": 1.3, "engagement": 0.8}},
        size_multipliers={"large": {"intent": 0.25}},
        persona_role_weights={
            "economic_buyer": 60, "champion": 45, "technical_buyer": 40,
            "influencer": 20, "blocker": 5,
        },
        band_cutoffs={"high": 75, "medium": 50},
        man_view_enabled=True,
        is_active=True,
    )
    if scoring.id is None and current_scoring is not None:
        scoring.version = current_scoring.version + 1
    rules = await _active(session, SalesRules) or SalesRules(
        version=1,
        priority_threshold=65,
        persona_weight_threshold=30,
        max_concurrent_threads=2,
        thread_start_offset_days=3,
        signal_ttl_days={"funding": 300, "engineering_scaling": 60},
        sample_rate=0.4,
        no_go={"domains": ["competitor.example"], "reason": "competitor"},
        is_active=True,
    )
    for row in (scoring, rules):
        if row.id is None:
            session.add(row)
    await session.flush()

    existing = {
        s.key for s in (await session.execute(select(SignalType))).scalars()
    }
    for key, label, scope, ttl, weight, families in (
        ("funding", "Funding round raised", "company", 300, 2.0, ["funding", "news"]),
        ("engineering_scaling", "Hiring surge in engineering", "company", 60, 1.35, ["hiring"]),
        ("role_change", "New in role, under 6 months", "contact", 180, 1.45,
         ["leadership", "enrichment"]),
        ("public_pain_statement", "Said the problem out loud, publicly", "contact", 150, 1.7,
         ["content_activity"]),
    ):
        if key not in existing:
            session.add(
                SignalType(
                    key=key, label=label, scope=scope, default_ttl_days=ttl,
                    weight=weight, produced_by=families,
                )
            )

    # Per-stage model config, from docs/06 §3. Effort is the primary cost
    # lever and is tuned per stage, never globally.
    have_llm = {
        c.scenario for c in (await session.execute(select(LlmConfig))).scalars()
    }
    for scenario, effort, contract, tokens in (
        ("company_research", "high", "EvidenceBatch", 16000),
        ("decision_maker_enrichment", "medium", "ContactBatch", 8000),
        ("signal_scan", "high", "EvidenceBatch", 16000),
        ("signal_extraction", "medium", "SignalBatch", 16000),
        ("context_builder", "medium", "AccountContextPayload", 16000),
        ("qualification_assessment", "high", "DimensionAssessments", 16000),
        # The hardest judgement in the pipeline — its gate is "would a senior
        # BDE agree" — so it is the one stage where thoroughness pays for itself.
        ("strategy_synthesis", "xhigh", "StrategyProposal", 16000),
        ("outreach_drafting", "high", "DraftSet", 16000),
        ("sales_prep", "high", "SalesPrepPayload", 16000),
        ("evaluation", "medium", "EvaluationResult", 8000),
        ("manual_intel_structuring", "medium", "SignalBatch", 8000),
        # A constrained yes/no over a handful of facts, run before every send.
        ("pre_send_revalidation", "low", "FreshnessVerdict", 2000),
    ):
        if scenario not in have_llm:
            session.add(
                LlmConfig(
                    scenario=scenario, model="claude-opus-5", effort=effort,
                    max_tokens=tokens, thinking_mode="adaptive",
                    output_contract=contract, version=1, is_active=True,
                )
            )

    have_shapes = {
        c.key for c in (await session.execute(select(CadenceShape))).scalars()
    }
    shape = CadenceShape(
        key="standard_6_15",
        label="Standard 6 touches / 15 days",
        lgm_campaign_id="lgm-demo-standard",
        touch_count=6,
        span_days=15,
        attribute_map={str(i): f"custom_attribute_{i}" for i in range(1, 7)},
        attributes_used=6,
        selection_rule={"rule": "default"},
        verified_at=datetime.now(UTC) - timedelta(days=3),
        verified_by="bertie",
        lgm_updated_at=datetime.now(UTC) - timedelta(days=10),
        lgm_channels=["linkedin", "email"],
        lgm_status="active",
        durable_from_step=durable_from_step(6, 15),
        active=True,
    )
    # A second shape that is deliberately drifted, so the Cadence screen has
    # something to show in its blocked state.
    drifted = CadenceShape(
        key="enterprise_8_23",
        label="Enterprise 8 touches / 23 days",
        lgm_campaign_id="lgm-demo-enterprise",
        touch_count=8,
        span_days=23,
        attribute_map={str(i): f"custom_attribute_{i}" for i in range(1, 9)},
        attributes_used=8,
        verified_at=datetime.now(UTC) - timedelta(days=20),
        verified_by="bertie",
        lgm_updated_at=datetime.now(UTC) - timedelta(days=2),  # changed since verification
        lgm_status="active",
        durable_from_step=durable_from_step(8, 23),
        active=True,
    )
    # Every shape the deterministic selection rules can choose. Registering a
    # subset means a correct selection dead-ends at promotion, which reads as a
    # broken campaign rather than as missing configuration.
    others = [
        CadenceShape(
            key=key, label=label, lgm_campaign_id=f"lgm-demo-{key}",
            touch_count=touches, span_days=span,
            attribute_map={str(i): f"custom_attribute_{i}" for i in range(1, touches + 1)},
            attributes_used=touches,
            selection_rule={"rule": rule},
            verified_at=datetime.now(UTC) - timedelta(days=4),
            verified_by="bertie",
            lgm_updated_at=datetime.now(UTC) - timedelta(days=12),
            lgm_channels=channels,
            lgm_status="active",
            durable_from_step=durable_from_step(touches, span),
            active=True,
        )
        for key, label, touches, span, rule, channels in (
            ("linkedin_only_5_15", "LinkedIn only 5 / 15", 5, 15,
             "unverified_email", ["linkedin"]),
            ("startup_5_11", "Startup 5 / 11", 5, 11, "size_band", ["linkedin", "email"]),
            ("nurture_4_21", "Nurture 4 / 21", 4, 21, "priority_band", ["email"]),
        )
    ]
    session.add_all(
        [c for c in (shape, drifted, *others) if c.key not in have_shapes]
    )
    await session.flush()
    shape = (
        await session.execute(select(CadenceShape).where(CadenceShape.key == "standard_6_15"))
    ).scalar_one()
    return {"services": services, "shape": shape, "scoring": scoring, "rules": rules}


# ---------------------------------------------------------------------------
# accounts, evidence, signals
# ---------------------------------------------------------------------------
async def seed_account(session, cfg) -> dict:
    account = Account(
        # Queued below, so it must be a confirmed identity — a demo
        # showing a state the product refuses would mislead.
        resolution_status="resolved",
        name="Meridian Cloud",
        domain=DOMAINS[0],
        industry="SaaS",
        industry_key="saas",
        # 180 people — `mid`, so no size multipliers apply to this one.
        employee_count=180,
        revenue_band="10-25M",
        funding_stage="series_b",
        hq_country="US",
        icp_match_score=82,
        status="researching",
        research_status="complete",
        enrichment_status="complete",
        pipeline_note=f"{DEMO} walkthrough account",
    )
    second = Account(
        # Queued below, so it must be a confirmed identity — a demo
        # showing a state the product refuses would mislead.
        resolution_status="resolved",
        name="Northwind Logistics",
        domain=DOMAINS[1],
        industry="Logistics",
        industry_key="logistics",
        # 1,400 people — `large`, which is what used to be `enterprise`.
        employee_count=1400,
        hq_country="UK",
        icp_match_score=61,
        status="new",
        pipeline_note=f"{DEMO} walkthrough account",
    )
    session.add_all([account, second])
    await session.flush()

    dana = Contact(
        account_id=account.id, full_name="Dana Reyes", title="VP Engineering",
        seniority="vp", buying_role="technical_buyer", persona_role="engineering",
        linkedin_url="https://www.linkedin.com/in/dana-reyes-demo/",
        email="dana.reyes@meridiancloud.io", email_status="verified",
        email_confidence=0.94, email_provider="apollo",
    )
    sam = Contact(
        account_id=account.id, full_name="Sam Okafor", title="Chief Financial Officer",
        seniority="c_level", buying_role="economic_buyer", persona_role="finance",
        email="sam.okafor@meridiancloud.io", email_status="verified",
        email_confidence=0.88, email_provider="apollo",
    )
    lee = Contact(
        account_id=account.id, full_name="Lee Park", title="Senior Engineer",
        seniority="ic", buying_role="influencer", email_status="unverified",
    )
    # Northwind's committee. One deliberately unverified and one deliberately
    # low-confidence, so the "Needs your eyes" stratum has something in it —
    # a walkthrough where nothing is ever flagged never exercises the half of
    # the design that matters most.
    priya = Contact(
        account_id=second.id, full_name="Priya Nair", title="Head of Data",
        seniority="director", buying_role="technical_buyer", persona_role="data",
        email="priya.nair@northwind-logistics.demo",
        email_status="unverified",  # flags: no verified route for email touches
    )
    marcus = Contact(
        account_id=second.id, full_name="Marcus Hale", title="Chief Operating Officer",
        seniority="c_level", buying_role="economic_buyer", persona_role="operations",
        email="marcus.hale@northwind-logistics.demo", email_status="verified",
        email_confidence=0.91, email_provider="apollo",
    )
    session.add_all([dana, sam, lee, priya, marcus])
    await session.flush()

    # --- evidence: one document, three excerpts, plus two more sources ---
    evidence = [
        Evidence(
            account_id=account.id, source_type="news",
            source_url="https://techcrunch.example/meridian-series-b",
            source_name="TechCrunch", title="Meridian Cloud raises $32M Series B",
            excerpt="Meridian Cloud has raised a $32M Series B led by Fold Ventures.",
            observed_at=date.today() - timedelta(days=24),
            source_hash="doc-tc-1", excerpt_hash="ex-tc-1", raw_ref="s3://demo/tc-1",
            reliability=0.9,
        ),
        Evidence(
            account_id=account.id, source_type="news",
            source_url="https://techcrunch.example/meridian-series-b",
            source_name="TechCrunch", title="Meridian Cloud raises $32M Series B",
            excerpt="The company plans to double its engineering team over the next year.",
            observed_at=date.today() - timedelta(days=24),
            source_hash="doc-tc-1", excerpt_hash="ex-tc-2", raw_ref="s3://demo/tc-1",
            reliability=0.9,
        ),
        Evidence(
            account_id=account.id, source_type="jobs",
            source_url="https://meridiancloud.io/careers",
            source_name="Careers page", title="Open roles",
            excerpt="Six open backend roles and one QA lead, all marked urgent.",
            observed_at=date.today() - timedelta(days=6),
            source_hash="doc-careers-1", excerpt_hash="ex-careers-1",
            raw_ref="s3://demo/careers-1", reliability=0.8,
        ),
        Evidence(
            account_id=account.id, source_type="linkedin",
            source_url="https://www.linkedin.com/posts/dana-reyes-demo-qa",
            source_name="LinkedIn", title="Dana Reyes on regression",
            excerpt=(
                "Dana Reyes: 'Our regression suite takes nine days. That is the "
                "single biggest thing slowing us down right now.'"
            ),
            observed_at=date.today() - timedelta(days=11),
            source_hash="doc-li-1", excerpt_hash="ex-li-1", raw_ref="s3://demo/li-1",
            reliability=0.95,
        ),
    ]
    # One evidence row for Northwind so its qualification can cite something
    # rather than resting on nothing.
    northwind_pain = Evidence(
        account_id=second.id, source_type="linkedin",
        source_url="https://www.linkedin.com/posts/priya-nair-demo-reporting",
        source_name="LinkedIn", title="Priya Nair on the reporting backlog",
        excerpt=(
            "Priya Nair: 'Half my team's week goes on reporting requests that "
            "should never reach a human.'"
        ),
        observed_at=date.today() - timedelta(days=5),
        source_hash="doc-nw-2", excerpt_hash="ex-nw-2", raw_ref="s3://demo/nw-2",
        reliability=0.92,
    )
    northwind_evidence = Evidence(
        account_id=second.id, source_type="jobs",
        source_url="https://northwind-logistics.demo/careers",
        source_name="Careers page", title="Open roles",
        excerpt="Three data engineering roles open, all citing 'reporting backlog'.",
        observed_at=date.today() - timedelta(days=9),
        source_hash="doc-nw-1", excerpt_hash="ex-nw-1", raw_ref="s3://demo/nw-1",
        reliability=0.75,
    )
    evidence.extend([northwind_evidence, northwind_pain])
    session.add_all(evidence)
    await session.flush()

    # --- signals, through the real guard ---
    outcome = await store_batch(
        session,
        account_id=account.id,
        batch=SignalBatch(
            signals=[
                {
                    "signal_type": "funding",
                    "summary": "Raised a $32M Series B led by Fold Ventures",
                    "business_implication": (
                        "Fresh budget and board pressure to convert it into shipped product."
                    ),
                    "strength": "high", "confidence": 0.93,
                    "observed_at": (date.today() - timedelta(days=24)).isoformat(),
                    "evidence_ids": [str(evidence[0].id), str(evidence[1].id)],
                },
                {
                    "signal_type": "engineering_scaling",
                    "summary": "Six urgent backend roles and a QA lead open at once",
                    "business_implication": (
                        "Headcount is arriving faster than the quality process can absorb it."
                    ),
                    "strength": "high", "confidence": 0.88,
                    "observed_at": (date.today() - timedelta(days=6)).isoformat(),
                    "evidence_ids": [str(evidence[2].id)],
                },
                {
                    "signal_type": "public_pain_statement",
                    "summary": (
                        "VP Engineering named a nine-day regression suite as the top blocker"
                    ),
                    "business_implication": (
                        "The problem is already articulated; no education needed."
                    ),
                    "strength": "high", "confidence": 0.95,
                    "observed_at": (date.today() - timedelta(days=11)).isoformat(),
                    "evidence_ids": [str(evidence[3].id)],
                    "contact_id": str(dana.id),
                },
                {
                    # Deliberately citing an id that does not exist, so the
                    # dropped-signal path is visible in the seed output.
                    "signal_type": "funding",
                    "summary": "A conclusion resting on a citation that does not exist",
                    "strength": "medium", "confidence": 0.5,
                    "observed_at": date.today().isoformat(),
                    "evidence_ids": [str(uuid.uuid4())],
                },
            ]
        ),
    )
    # Northwind's own signal, through the same guard.
    await store_batch(
        session,
        account_id=second.id,
        batch=SignalBatch(
            signals=[
                {
                    "signal_type": "engineering_scaling",
                    "summary": "Three data engineering roles open, all citing a reporting backlog",
                    "business_implication": (
                        "They are hiring to dig out of a backlog rather than to build."
                    ),
                    "strength": "medium", "confidence": 0.74,
                    "observed_at": (date.today() - timedelta(days=9)).isoformat(),
                    "evidence_ids": [str(northwind_evidence.id)],
                },
                {
                    "signal_type": "public_pain_statement",
                    "summary": (
                        "Head of Data said reporting requests consume half the team's week"
                    ),
                    "business_implication": (
                        "The problem is already named by the person who owns it."
                    ),
                    "strength": "high", "confidence": 0.92,
                    "observed_at": (date.today() - timedelta(days=5)).isoformat(),
                    "evidence_ids": [str(northwind_pain.id)],
                    "contact_id": str(priya.id),
                },
            ]
        ),
    )

    return {
        "account": account, "second": second,
        "contacts": {"dana": dana, "sam": sam, "lee": lee},
        "second_contacts": {"priya": priya, "marcus": marcus},
        "evidence": evidence, "northwind_evidence": northwind_evidence,
        "northwind_pain": northwind_pain,
        "outcome": outcome,
    }


async def seed_pipeline(session, cfg, world) -> dict:
    account = world["account"]

    counts = {"funding": 2, "hiring": 1, "content_activity": 1, "news": 0,
              "leadership": 0, "enrichment": 0}

    async def run_family(_account, family):
        if family == "leadership":
            raise RuntimeError("provider returned 503")
        return counts.get(family, 0)

    result = await run_research(
        session, account=account, crm=StubCrmAdapter(), run_family=run_family,
        triggered_by="seed",
    )

    context = await build_context(session, account_id=account.id, run_id=result.run_id)

    assessments = DimensionAssessments(
        assessments=[
            DimensionAssessment(
                dimension="fit", score=84,
                reason="180-person US SaaS with a product engineering org — squarely in ICP.",
                evidence_ids=[str(world["evidence"][0].id)],
            ),
            DimensionAssessment(
                dimension="opportunity", score=88,
                reason="A nine-day regression suite named publicly as the top blocker.",
                evidence_ids=[str(world["evidence"][3].id)],
            ),
            DimensionAssessment(
                dimension="buyer", score=72,
                reason="VP Engineering is reachable and verified; CFO is mapped.",
                evidence_ids=[str(world["evidence"][2].id)],
            ),
            DimensionAssessment(
                dimension="commercial", score=79,
                reason="$32M Series B three weeks ago; budget exists.",
                evidence_ids=[str(world["evidence"][0].id)],
            ),
            DimensionAssessment(
                dimension="intent", score=76,
                reason="Six urgent roles plus a QA lead — actively spending on the problem.",
                evidence_ids=[str(world["evidence"][2].id)],
            ),
            DimensionAssessment(
                dimension="engagement", score=0,
                reason="No prior contact of any kind.",
                basis="no_evidence",
            ),
        ]
    )
    qualification_result = score(
        assessments,
        config=cfg["scoring"],
        industry=account.industry,
        size_band=sizing.band_for(account.employee_count),
    )
    qualification = await store_qualification(
        session, account_id=account.id, result=qualification_result,
        context_id=context.id, run_id=result.run_id,
    )
    # Northwind, qualified more thinly — a real book is not uniform.
    nw_assessments = DimensionAssessments(
        assessments=[
            DimensionAssessment(
                dimension=d, score=score_for,
                reason=reason, evidence_ids=[str(world["northwind_evidence"].id)],
            )
            for d, score_for, reason in (
                ("fit", 58, "Enterprise logistics — larger and slower than the core ICP."),
                ("opportunity", 64, "A reporting backlog they are hiring against."),
                ("buyer", 55, "COO mapped; the data lead is not contact-verified."),
                ("commercial", 71, "1,400 staff — budget exists, procurement is slow."),
                ("intent", 52, "Hiring, but no other active signal."),
            )
        ]
        + [
            DimensionAssessment(
                dimension="engagement", score=0,
                reason="No prior contact.", basis="no_evidence",
            )
        ]
    )
    nw_result = score(
        nw_assessments,
        config=cfg["scoring"],
        industry=world["second"].industry,
        size_band=sizing.band_for(world["second"].employee_count),
    )
    nw_context = await build_context(session, account_id=world["second"].id)
    nw_qualification = await store_qualification(
        session, account_id=world["second"].id, result=nw_result, context_id=nw_context.id
    )

    return {"run": result, "context": context, "qualification": qualification,
            "qual_result": qualification_result,
            "nw_qualification": nw_qualification, "nw_result": nw_result}


async def seed_strategy(session, cfg, world, pipe) -> dict:
    account, contacts = world["account"], world["contacts"]
    services = cfg["services"]

    dana_signal = (
        await session.execute(
            select(Signal).where(
                Signal.account_id == account.id, Signal.scope == "contact"
            )
        )
    ).scalars().first()

    personas = [
        PersonaInput(
            contacts["dana"].id, "Dana Reyes", buying_role="technical_buyer",
            signals=((dana_signal.id, "high"),) if dana_signal else (),
        ),
        PersonaInput(contacts["sam"].id, "Sam Okafor", buying_role="economic_buyer"),
        PersonaInput(
            contacts["lee"].id, "Lee Park", buying_role="influencer", contactable=False
        ),
    ]
    # The buying roles each demo service is pitched to. They used to be read off
    # `service_catalog.target_personas`, which is gone: personas live on the
    # ICP now. Kept here so the demo matrix scores as it always has.
    demo_target_roles = {
        "qa_engineering": ("technical_buyer", "champion"),
        "data_platform": ("economic_buyer", "technical_buyer"),
    }
    service_inputs = [
        ServiceInput(s.id, s.code, demo_target_roles.get(s.code, ())) for s in services
    ]

    cells = build_matrix(
        personas, service_inputs,
        persona_role_weights=cfg["scoring"].persona_role_weights,
    )
    threads = select_threads(
        cells,
        persona_weight_threshold=float(cfg["rules"].persona_weight_threshold),
        max_concurrent_threads=cfg["rules"].max_concurrent_threads,
        thread_start_offset_days=cfg["rules"].thread_start_offset_days,
    )

    strategy = Strategy(
        account_id=account.id, qualification_id=pipe["qualification"].id,
        run_id=pipe["run"].run_id, version=1, status="evaluated",
    )
    session.add(strategy)
    await session.flush()

    for cell in cells:
        session.add(
            PersonaServiceScore(
                strategy_id=strategy.id, contact_id=cell.contact_id,
                service_id=cell.service_id, weight=cell.weight,
                rationale=cell.rationale, evidence_ids=cell.evidence_ids,
            )
        )

    copy = {
        contacts["dana"].id: {
            "problem": (
                "A nine-day regression suite is about to meet six new backend engineers. "
                "Throughput goes up, confidence goes down."
            ),
            "trigger": "Series B three weeks ago, then six urgent backend roles and a QA lead.",
            "positioning": "Embedded QA that absorbs new headcount instead of queueing behind it.",
            "cta": "Fifteen minutes to compare regression timings?",
        },
        contacts["sam"].id: {
            "problem": (
                "£32M of new capital converting into headcount faster than it converts "
                "into shipped product."
            ),
            "trigger": "Series B closed three weeks ago; engineering headcount doubling.",
            "positioning": "Cost per shipped feature, not cost per engineer.",
            "cta": "Worth a short call on engineering spend efficiency?",
        },
    }

    made = []
    signal_ids = [
        str(s.id)
        for s in (
            await session.execute(select(Signal).where(Signal.account_id == account.id))
        ).scalars()
    ]
    for t in threads:
        text = copy.get(t.contact_id)
        if text is None:
            continue
        row = StrategyThread(
            strategy_id=strategy.id, contact_id=t.contact_id, service_id=t.service_id,
            weight=t.weight, rank=t.rank, thread_status=t.thread_status,
            problem_hypothesis=text["problem"], trigger_summary=text["trigger"],
            trigger_signal_ids=signal_ids[:2], positioning=text["positioning"],
            channel_sequence=["linkedin", "email"], cta=text["cta"],
            avoid_list=["do not mention the unapproved logistics metric"],
            confidence=0.82 if t.rank == 1 else 0.68,
            start_offset_days=t.start_offset_days,
        )
        session.add(row)
        made.append(row)
    await session.flush()

    # --- Northwind's strategy, with one deliberately low-confidence thread ---
    nw = world["second"]
    nw_contacts = world["second_contacts"]
    priya_signal = (
        await session.execute(
            select(Signal).where(
                Signal.account_id == nw.id,
                Signal.contact_id == nw_contacts["priya"].id,
            )
        )
    ).scalars().first()
    nw_personas = [
        PersonaInput(nw_contacts["marcus"].id, "Marcus Hale", buying_role="economic_buyer"),
        PersonaInput(
            nw_contacts["priya"].id, "Priya Nair", buying_role="technical_buyer",
            signals=((priya_signal.id, "high"),) if priya_signal else (),
        ),
    ]
    nw_cells = build_matrix(
        nw_personas, service_inputs,
        persona_role_weights=cfg["scoring"].persona_role_weights,
    )
    nw_threads = select_threads(
        nw_cells,
        persona_weight_threshold=float(cfg["rules"].persona_weight_threshold),
        max_concurrent_threads=cfg["rules"].max_concurrent_threads,
        thread_start_offset_days=cfg["rules"].thread_start_offset_days,
    )
    nw_strategy = Strategy(
        account_id=nw.id, qualification_id=pipe["nw_qualification"].id,
        version=1, status="evaluated",
    )
    session.add(nw_strategy)
    await session.flush()
    for cell in nw_cells:
        session.add(
            PersonaServiceScore(
                strategy_id=nw_strategy.id, contact_id=cell.contact_id,
                service_id=cell.service_id, weight=cell.weight,
                rationale=cell.rationale, evidence_ids=cell.evidence_ids,
            )
        )

    nw_signal_ids = [
        str(sig.id)
        for sig in (
            await session.execute(select(Signal).where(Signal.account_id == nw.id))
        ).scalars()
    ]
    nw_copy = {
        nw_contacts["marcus"].id: {
            "problem": (
                "Three data hires going into a reporting backlog rather than into "
                "anything new."
            ),
            "trigger": "Three open data engineering roles, all naming the backlog.",
            "positioning": "Clear the backlog once so the new hires build instead of catch up.",
            "cta": "Worth twenty minutes on where the backlog actually sits?",
            # Above the 0.60 floor — this one is clean.
            "confidence": 0.74,
        },
        nw_contacts["priya"].id: {
            "problem": "A reporting backlog absorbing the data team's whole week.",
            "trigger": "Roles opened against the backlog rather than against a roadmap.",
            "positioning": "Pipelines that survive scale, so reporting stops being manual.",
            "cta": "Fifteen minutes on the pipeline shape?",
            # Below the 0.60 floor *and* the contact is unverified, so this
            # thread flags for two independent reasons.
            "confidence": 0.48,
        },
    }
    for t in nw_threads:
        text = nw_copy.get(t.contact_id)
        if text is None:
            continue
        row = StrategyThread(
            strategy_id=nw_strategy.id, contact_id=t.contact_id, service_id=t.service_id,
            weight=t.weight, rank=t.rank, thread_status=t.thread_status,
            problem_hypothesis=text["problem"], trigger_summary=text["trigger"],
            trigger_signal_ids=nw_signal_ids[:1] or [str(uuid.uuid4())],
            positioning=text["positioning"],
            channel_sequence=["linkedin", "email"], cta=text["cta"],
            confidence=text["confidence"], start_offset_days=t.start_offset_days,
        )
        session.add(row)
        made.append(row)
    await session.flush()

    return {"strategy": strategy, "threads": made, "cells": cells + nw_cells}


#: Channels to cycle through when a shape does not dictate them. LinkedIn first
#: because a connection request is the cheapest possible opener.
_CHANNELS = ("linkedin_connect", "email", "linkedin_engage", "email", "inmail", "email",
             "linkedin_message", "email")


def _arc_for(shape: CadenceShape, thread: StrategyThread) -> DraftSet:
    """Build an arc that fits the shape the selection rules actually chose.

    Hardcoding six touches over fifteen days would fail `store_arc`'s shape
    agreement check on every cadence but the standard one — and the whole point
    of deterministic selection is that different accounts get different shapes.
    """
    count = shape.touch_count
    span = shape.span_days
    first = thread.problem_hypothesis.split(".")[0]

    touches = []
    for i in range(count):
        step = i + 1
        # Spread across the span, first touch on day 1, last on the final day.
        day = 1 if count == 1 else round(1 + (span - 1) * i / (count - 1))
        band = band_for_step(step, count)
        dependence = {"early": "dated", "middle": "implied", "late": "durable"}[band]

        if band == "early":
            body = f"{DEMO} {thread.trigger_summary} — {first.lower()}?"
        elif band == "middle":
            body = f"{DEMO} {thread.positioning}"
        elif step == count:
            body = f"{DEMO} Closing the loop — happy to revisit whenever it is useful."
        else:
            body = f"{DEMO} {thread.cta}"

        touches.append(
            TouchDraft(
                step_no=step,
                day_offset=day,
                channel=_CHANNELS[i % len(_CHANNELS)],
                purpose={"early": "Open on their fact", "middle": "Name the problem",
                         "late": "Soft close"}[band],
                subject="Nine days of regression" if step == 2 else None,
                body=body,
                signal_dependence=dependence,
                cited_signal_ids=(
                    list(thread.trigger_signal_ids)[:1] if dependence == "dated" else []
                ),
            )
        )
    return DraftSet(touches=touches)


async def seed_campaign(session, cfg, world, strat) -> dict:
    account = world["account"]

    lst = (
        await session.execute(select(AccountList).limit(1))
    ).scalar_one_or_none()
    queue = CampaignQueue(label=f"{DEMO} Sept EIA push — VP Eng", status="draft",
                          description="Series B SaaS with an articulated QA problem")
    session.add(queue)
    await session.flush()
    await add_member(
        session, queue_id=queue.id, account_id=account.id,
        source_list_id=lst.id if lst else None, added_by="seed",
    )
    await add_member(
        session, queue_id=queue.id, account_id=world["second"].id, added_by="seed"
    )

    # No label: it inherits the queue's, which is the continuity the boundary
    # is supposed to preserve.
    campaign = await promote(
        session, queue_ids=[queue.id], cadence_shape_id=cfg["shape"].id
    )
    campaign.status = "pending_approval"

    # `promote` created the sequences: it resolved each contact to an LGM
    # identity, chose a cadence shape from the deterministic rules, and copied
    # the pursued threads in. The seed's job from here is only the content,
    # because drafting is a separate stage.
    sequences = list(
        (
            await session.execute(
                select(OutreachSequence).where(OutreachSequence.campaign_id == campaign.id)
            )
        ).scalars()
    )
    threads_by_id = {t.id: t for t in strat["threads"]}

    for sequence in sequences:
        thread = threads_by_id.get(sequence.thread_id)
        if thread is None:
            continue
        shape = await session.get(CadenceShape, sequence.cadence_shape_id)
        await store_arc(
            session, sequence=sequence, shape=shape,
            draft_set=_arc_for(shape, thread),
        )
        sequence.status = "pending_approval"
    await session.flush()

    # A real evaluation warning on Sam's thread. Previously the seed invented
    # its flags with `contact_verified=i == 0`, which meant the summary claimed
    # a flagged thread while the screen — reading actual state — showed none.
    sam_sequence = next(
        (s for t, s in zip(strat["threads"], sequences, strict=False)
         if t.contact_id == world["contacts"]["sam"].id),
        None,
    )
    if sam_sequence is not None:
        session.add(
            Evaluation(
                # Sequence level, because that is where approval happens and
                # therefore where the evaluation preceding it belongs.
                subject_type="outreach_sequence",
                subject_id=sam_sequence.id,
                method="rules",
                verdict="warn",
                issues=[
                    {
                        "code": "unsupported_figure",
                        "detail": (
                            "Touch 2 states a funding amount the cited evidence does "
                            "not carry."
                        ),
                    }
                ],
                evaluator_version="demo",
            )
        )
        await session.flush()

    # Stratify from the same facts the screen reads, so the summary below and
    # the Approval tab can never disagree.
    threads_by_sequence = {
        s.id: t for t, s in zip(strat["threads"], sequences, strict=False)
    }
    candidates = []
    for s in sequences:
        thread = threads_by_sequence.get(s.id)
        contact = await session.get(Contact, thread.contact_id) if thread else None
        verdict = (
            await session.execute(
                select(Evaluation.verdict)
                .where(
                    Evaluation.subject_type == "outreach_sequence",
                    Evaluation.subject_id == s.id,
                )
                .limit(1)
            )
        ).scalar() or "pass"
        candidates.append(
            Candidate(
                sequence_id=s.id,
                contact_name=contact.full_name if contact else "",
                evaluation_verdict=verdict,
                contact_verified=bool(contact and contact.email_status == "verified"),
                strategy_confidence=float(thread.confidence)
                if thread and thread.confidence is not None
                else None,
            )
        )
    stratum = stratify(candidates)
    sample = await draw(
        session, campaign_id=campaign.id, stratum=stratum,
        rate=float(cfg["rules"].sample_rate),
    )
    await session.flush()
    # Reported so the summary shows deterministic selection actually varying,
    # rather than claiming one shape for everybody.
    shapes_used = []
    for sequence in sequences:
        thread = threads_by_id.get(sequence.thread_id)
        contact = await session.get(Contact, thread.contact_id) if thread else None
        shape = await session.get(CadenceShape, sequence.cadence_shape_id)
        if contact and shape:
            shapes_used.append(
                (contact.full_name, shape.key, shape.touch_count, shape.span_days)
            )

    return {"queue": queue, "campaign": campaign, "sequences": sequences,
            "stratum": stratum, "sample": sample,
            "shapes": sorted(shapes_used)}


# ---------------------------------------------------------------------------
async def clear(session) -> None:
    """Remove everything the seed created, newest dependency first."""
    accounts = list(
        (
            await session.execute(
                select(Account).where(
                    func.lower(Account.domain).in_([d.lower() for d in DOMAINS])
                )
            )
        ).scalars()
    )
    ids = [a.id for a in accounts]

    seqs = []
    if ids:
        seqs = list(
            (
                await session.execute(
                    select(OutreachSequence)
                    .join(StrategyThread, StrategyThread.id == OutreachSequence.thread_id)
                    .join(Contact, Contact.id == StrategyThread.contact_id)
                    .where(Contact.account_id.in_(ids))
                )
            ).scalars()
        )
    seq_ids = [s.id for s in seqs]
    if seq_ids:
        touches = list(
            (
                await session.execute(select(Touch).where(Touch.sequence_id.in_(seq_ids)))
            ).scalars()
        )
        if touches:
            await session.execute(
                delete(Draft).where(Draft.touch_id.in_([t.id for t in touches]))
            )
            await session.execute(delete(Touch).where(Touch.sequence_id.in_(seq_ids)))

    await session.execute(delete(Approval))
    await session.execute(delete(ApprovalSample))
    if seq_ids:
        # Execution records reference sequences and are written by `execute`,
        # so they have to go first. Added when Phase 10 landed — without this
        # the clear fails on any campaign that was actually run.
        await session.execute(
            delete(ExecutionRecord).where(ExecutionRecord.sequence_id.in_(seq_ids))
        )
        await session.execute(delete(OutreachSequence).where(OutreachSequence.id.in_(seq_ids)))

    if ids:
        strategies = list(
            (
                await session.execute(select(Strategy).where(Strategy.account_id.in_(ids)))
            ).scalars()
        )
        sids = [s.id for s in strategies]
        if sids:
            await session.execute(
                delete(PersonaServiceScore).where(PersonaServiceScore.strategy_id.in_(sids))
            )
            await session.execute(
                delete(StrategyThread).where(StrategyThread.strategy_id.in_(sids))
            )
            await session.execute(delete(Strategy).where(Strategy.id.in_(sids)))

        signals = list(
            (await session.execute(select(Signal).where(Signal.account_id.in_(ids)))).scalars()
        )
        if signals:
            await session.execute(
                signal_evidence.delete().where(
                    signal_evidence.c.signal_id.in_([s.id for s in signals])
                )
            )
            await session.execute(delete(Signal).where(Signal.account_id.in_(ids)))
        await session.execute(delete(Evidence).where(Evidence.account_id.in_(ids)))
        await session.execute(delete(Qualification).where(Qualification.account_id.in_(ids)))
        await session.execute(delete(AccountContext).where(AccountContext.account_id.in_(ids)))
        await session.execute(delete(ResearchCoverage).where(ResearchCoverage.account_id.in_(ids)))
        await session.execute(
            delete(AccountListMember).where(AccountListMember.account_id.in_(ids))
        )
        await session.execute(delete(Contact).where(Contact.account_id.in_(ids)))

    from app.models.campaign import (
        CampaignQueueMember,
        DeferredEnrolment,
        OutreachCampaign,
        OutreachCampaignSource,
    )

    await session.execute(delete(DeferredEnrolment))
    await session.execute(delete(OutreachCampaignSource))
    await session.execute(delete(CampaignQueueMember))
    demo_queues = list(
        (
            await session.execute(
                select(CampaignQueue).where(CampaignQueue.label.like(f"{DEMO}%"))
            )
        ).scalars()
    )
    if demo_queues:
        # A clone carries `cloned_from_queue_id` as a provenance stamp. The
        # clone itself may be a real queue somebody made, so detach the stamp
        # rather than deleting their work — a dangling provenance pointer is
        # exactly what the nullable column is for.
        await session.execute(
            CampaignQueue.__table__.update()
            .where(CampaignQueue.cloned_from_queue_id.in_([q.id for q in demo_queues]))
            .values(cloned_from_queue_id=None)
        )
        await session.flush()
    for q in demo_queues:
        await session.delete(q)
    for c in (
        await session.execute(
            select(OutreachCampaign).where(OutreachCampaign.label.like(f"{DEMO}%"))
        )
    ).scalars():
        await session.delete(c)
    await session.flush()

    for account in accounts:
        await session.delete(account)

    await session.execute(delete(LgmIdentity))

    # Campaigns and sequences outside the demo set may point at a demo shape.
    # Detach rather than delete their work — the reference is a selection
    # record, and nulling it is honest about the shape having gone.
    demo_shapes = [
        c.id
        for c in (
            await session.execute(
                select(CadenceShape).where(CadenceShape.lgm_campaign_id.like("lgm-demo-%"))
            )
        ).scalars()
    ]
    if demo_shapes:
        from app.models.campaign import OutreachCampaign as _Campaign

        await session.execute(
            _Campaign.__table__.update()
            .where(_Campaign.cadence_shape_id.in_(demo_shapes))
            .values(cadence_shape_id=None)
        )
        await session.execute(
            OutreachSequence.__table__.update()
            .where(OutreachSequence.cadence_shape_id.in_(demo_shapes))
            .values(cadence_shape_id=None)
        )
        await session.flush()
        await session.execute(delete(CadenceShape).where(CadenceShape.id.in_(demo_shapes)))
    # Only rows carrying the DEMO marker. `scoring_config` and `sales_rules` are
    # deliberately untouched: the seed reuses whatever is already active rather
    # than creating its own, so deleting them would destroy a person's config.
    await session.execute(
        delete(LlmConfig).where(LlmConfig.output_contract.in_((
            "EvidenceBatch", "ContactBatch", "SignalBatch", "AccountContextPayload",
            "DimensionAssessments", "StrategyProposal", "DraftSet", "SalesPrepPayload",
            "EvaluationResult", "FreshnessVerdict",
        )))
    )
    for model, column in (
        (ProofPoint, ProofPoint.title), (WritingSample, WritingSample.body),
        (ServiceCatalog, ServiceCatalog.description), (OrgProfile, OrgProfile.description),
    ):
        await session.execute(delete(model).where(column.like(f"%{DEMO}%")))
    await session.commit()


async def main(do_clear: bool) -> None:
    settings = get_settings()
    engine = create_async_engine(str(settings.database_url))
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as session:
        if do_clear:
            await clear(session)
            print("demo data removed")
            await engine.dispose()
            return

        existing = (
            await session.execute(
                select(Account).where(
                    func.lower(Account.domain).in_([d.lower() for d in DOMAINS])
                )
            )
        ).scalars().first()
        if existing is not None:
            print("demo data is already present — run with --clear first")
            await engine.dispose()
            return

        cfg = await seed_config(session)
        world = await seed_account(session, cfg)
        pipe = await seed_pipeline(session, cfg, world)
        strat = await seed_strategy(session, cfg, world, pipe)
        camp = await seed_campaign(session, cfg, world, strat)
        await session.commit()

        o = world["outcome"]
        q = pipe["qual_result"]
        contact_count = len(world["contacts"]) + len(world["second_contacts"])
        shape_lines = "\n".join(
            f"                      {name} — {key} ({touches} touches / {span}d)"
            for name, key, touches, span in camp["shapes"]
        )
        flag_lines = "\n".join(
            f"                      - {reason}"
            for reasons in camp["stratum"].reasons.values()
            for reason in reasons
        ) or "                      (none)"
        print(f"""
seeded, through the real services:

  accounts          2  (Meridian Cloud, Northwind Logistics)
  contacts          {contact_count}
  evidence          {len(world["evidence"])}  (one document supplying two excerpts)
  signals           {o.stored} stored, {len(o.dropped)} dropped by the citation guard
                    dropped: {o.dropped[0].reason if o.dropped else "-"}
  coverage          {len(pipe["run"].gaps)} gap(s) across {len(pipe["run"].plan.families)} families
                    failed: {[g.family for g in pipe["run"].gaps if g.is_failure]}
  context           v{pipe["context"].version}, {len(pipe["context"].signal_ids)} signals in scope
  qualification     {q.priority_score} ({q.priority_band}), config v{q.scoring_config_version}
  strategy          {len(strat["cells"])} matrix cells, {len(strat["threads"])} threads
  campaign          1, queue locked
  sequences         {len(camp["sequences"])}, each on the cadence its facts selected:
{shape_lines}
  approval sample   {camp["sample"].sample_size} of {camp["sample"].stratum_size} clean drawn
                    {len(camp["stratum"].flagged)} flagged, never sampled:
{flag_lines}

  remove with: python scripts/seed_demo.py --clear
""")
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clear", action="store_true", help="remove the demo data")
    args = parser.parse_args()
    asyncio.run(main(args.clear))
