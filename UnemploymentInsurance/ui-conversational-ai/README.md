# UI-Conversational AI

Agentic conversational AI for **weekly unemployment-insurance claim eligibility** (POC). Interviews claimants in natural language, evaluates eligibility against state policy + SOP, runs fraud heuristics, collects documents, and hands the human adjudicator a structured report with per-claim confidence scores.

Initiative: **Unemployment Insurance** (broader scope: full UI process — initial intake, appeals, etc.).
This module: **weekly certification only**.

## Status

POC scaffold. Architecture approved 2026-05-25.

## Agent topology

```
Claimant turn
  → ① PII Guard (inbound)
  → ② Intent Analyzer
  → ③ Signal Extractor
  → ④ Context Agent  (assembles working context)
  → ⑤ Strategy / Planner  (Gemini 2.5 Pro — the "brain")
       ├─→ ⑥ Fraud Scorer
       ├─→ ⑦ Eligibility Evaluator
       └─→ ⑧ Document Collector
  → ⑨ Dialog / Phraser
  → ⑩ Legal-Relevance Guard
  → ⑪ PII Guard (outbound)
  → claimant
At conversation close → ⑫ Adjudicator Report Generator
Data loops: ⑬ training-records writeback   ⑭ eval (pre-prod golden + in-prod auto-judge)
```

## Tech stack

- **LLM planner / report**: Gemini 2.5 Pro on Vertex AI
- **LLM classifiers / phraser**: Gemini 2.5 Flash
- **Agent framework**: Google ADK (Agent Development Kit)
- **RAG**: Vertex AI Search + Vector Search
- **Document AI**: Vertex Document AI
- **PII redaction**: Cloud DLP
- **Backend**: FastAPI on Cloud Run
- **State**: Firestore (live session) + Cloud SQL Postgres (claims, decisions, audit, training_records)
- **Frontend**: React + Vite, SSE streaming

## Confidence-band routing

| Band | POC behavior |
|--|--|
| ≥ 0.90 all rules | autonomous (shadow-log only in POC) |
| 0.65 – 0.90 | human adjudicator + inference + citations |
| < 0.65 or legal/PII flag | escalate, no auto-decision |

## Layout

```
backend/
  app/
    agents/      # one file per agent (PII guards, intent, signals, context,
                 # strategy/planner, phraser, legal guard, fraud, eligibility,
                 # document collector, adjudicator report)
    api/         # FastAPI routers (conversation, claims, health)
    core/        # config, db clients, audit middleware
    models/      # Pydantic schemas
    services/    # Vertex Search, DLP, Document AI wrappers
    main.py
  tests/
frontend/        # React + Vite (scaffold pending)
infra/           # Terraform / GCP setup (pending)
data/
  policy/            # state UI statute + SOP corpora
  question_bank/     # curated weekly-cert questions
  allowlist/         # legal-relevance allowlist + forbidden-topic lists
  golden_dataset/    # anonymized historical claims for eval
docs/
```

## Dev quickstart (pending GCP bootstrap)

```bash
cd backend
python -m venv .venv && source .venv/Scripts/activate   # Windows
pip install -r requirements.txt
cp .env.example .env       # fill in GCP project, model names, DB urls
uvicorn app.main:app --reload --port 8003
```

## Next milestones

See `docs/MILESTONES.md` (pending). Approved plan: `C:\Users\19254\.claude\plans\witty-sparking-kernighan.md`.
