# Milestones — UI Conversational AI (POC)

Each milestone is independently mergeable. Solo-eng estimates from the approved plan.

## M0 — Scaffold (done)
- Project tree, FastAPI gateway, agent stubs, orchestrator wiring, smoke tests, conversation API.
- Verify: `cd backend && pip install -r requirements.txt && pytest && uvicorn app.main:app --reload --port 8003`.

## M1 — Discovery + corpora ingestion (2.5 wk)
- Curate state UI policy + SOP (start: 1 state, e.g. CA or TX).
- Compile legal allowlist + forbidden topic list with state counsel input.
- Ingest curated question bank.
- Anonymized golden dataset (~200 historical weekly certs) with adjudicated outcomes.

## M2 — GCP bootstrap (1 wk)
- Project, IAM least-priv, VPC-SC, CMEK on Firestore/SQL/storage.
- Cloud Run service, Firestore + Cloud SQL provisioned.
- DLP inspect/deidentify templates.
- Vertex AI Search data stores created and indexed against M1 corpora.

## M3 — ADK orchestrator + Strategy/Phraser split (2 wk)
- Wire Strategy Planner to Gemini 2.5 Pro with structured-output schema for NextAction.
- Wire Dialog Phraser to Flash with NextAction → natural question.
- Replace stubbed Planner/Phraser bodies; keep orchestrator wiring unchanged.

## M4 — Intent Analyzer + Signal Extractor + Context Agent (3 wk)
- Flash classifiers behind contracts.
- Context Agent computes outstanding evidence gaps from rule set + known signals.
- Vertex AI Search lookups for policy snippets + question-bank candidates.

## M5 — Guards (2.5 wk)
- Inbound PII Guard via Cloud DLP + medical/3rd-party classifier.
- Outbound PII Guard.
- Legal-Relevance Guard with allowlist/forbidden corpora + Flash fallback.
- Audit log emits citation IDs with every emitted question.

## M6 — Fraud Scorer + Document Collector (2.5 wk)
- Deterministic fraud rules + Flash behavioral classifier.
- Document Collector wired to Vertex Document AI for paystub + separation letter processors.
- Cross-check extracted fields vs collected signals; emit contradiction signals upstream.

## M7 — Eligibility Evaluator (3 wk)
- Rule engine driven by `data/policy/<state>/rules.yaml`.
- Deterministic rules first, Pro for nuanced (separation-reason, jobsearch validity).
- Per-rule citations and confidence; band routing via Settings thresholds.

## M8 — Adjudicator Report + human-review UI (2 wk)
- Report Generator with cited findings.
- Backend `/api/claims` endpoints (list/get/decision).
- Adjudicator UI: claim queue, claim detail, decision-with-override.

## M9 — Conversational React UI (3 wk)
- Vite + React frontend.
- SSE streaming for agent replies.
- Document upload component.
- Transcript replay for adjudicators.

## M10 — Eval harness + training writeback (2.5 wk)
- Pre-prod: golden dataset replay against pinned model + prompt versions.
- In-prod: every closed claim auto-judged against adjudicator outcome.
- `training_records` table populated from adjudicator decisions.
- Weekly Vertex Pipeline retunes thresholds, grows golden set, scores Q-bank coverage.

## M11 — Security review + audit + pen-test prep (2 wk)
- PII red-team: claimants oversharing SSN/medical/3rd-party PII.
- Legal red-team: forbidden topics presented as innocent claimant questions.
- Cloud Logging audit retention configured.
- Final IAM and VPC-SC review.

## Out of POC scope (future)
- Voice channel (Speech-to-Text + Text-to-Speech).
- Initial intake flow.
- Appeals.
- Flipping AUTONOMOUS confidence band on for real decisions.
