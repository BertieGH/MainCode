# Sales Demand Gen360

A Claude-powered sales intelligence and demand-generation system for **CGVAK outbound sales**.
Internally the engine is referred to as the **Prospect Engine** (per the V2 approach document);
`SalesDemandGen360` is the product/repo name.

It turns account research into evidence-backed signals, assembles a versioned Account Context,
qualifies across six dimensions, produces an approved Strategy, and lets Outreach and Sales Prep
*execute* that strategy rather than invent one. A human approves every outbound message;
La Growth Machine does the sending.

---

## Status

| | |
|---|---|
| Phase | Design — architecture docs complete, no code written |
| Location | `C:\Users\19254\MainCode\SalesDemandGen360` |
| Stack | Angular 17 + FastAPI (Python 3.12) + PostgreSQL 16 + Redis |
| LLM | Claude via the Anthropic Python SDK (`claude-opus-5`) |
| Source of truth | `docs/reference/prospect-engine-v2.html` (V2 approach doc) |

## Documents

| Doc | What it covers |
|---|---|
| [01 — Project Plan](docs/01-project-plan.md) | Scope, milestones M0–M6, gate criteria, out-of-scope list, risks |
| [02 — Architecture](docs/02-architecture.md) | Component map, stage contracts, memory stores, governance model |
| [03 — Data Model](docs/03-data-model.md) | PostgreSQL schema — 30 tables across 8 domains |
| [04 — API Surface](docs/04-api-surface.md) | FastAPI routers and endpoint list |
| [05 — Frontend Spec](docs/05-frontend-spec.md) | Angular routes, pages, and the Review Queue design |
| [06 — LLM Integration](docs/06-llm-integration.md) | Which Claude surface per stage, model config, caching, cost model |
| [07 — Open Questions](docs/07-open-questions.md) | Decisions still needed before M0 starts |

## The pipeline, in one line

```
Accounts → Research (parallel) → Evidence → Signals → Account Context →
Qualification (6 dims) → Strategy (per-persona threads) →
Outreach drafts + Sales Prep → Evaluation → Human Approval →
La Growth Machine → Engagement → Outcome → Learning ↺
```

## Non-negotiables

1. **No message sends without a human approval.** The send capability is application-gated, not prompt-gated.
2. **Every conclusion traces to dated, sourced evidence.** Nothing reaches Qualification as a bare claim.
3. **Qualification and Strategy are separate decisions.** "Is this worth pursuing?" ≠ "How do we pursue it?"
4. **Hypotheses are tagged as hypotheses**, in storage and in the UI. A guess never hardens into a fact.
5. **Business rules live outside the model** — config files and DB rows, not prompts.
