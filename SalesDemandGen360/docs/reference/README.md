# Reference material

## prospect-engine-v2.html

The V2 approach document ("Prospect Engine — Architecture & Approach, V2"). This is the source of
truth for every design decision in `../01` through `../07`. Open it in a browser; it is
self-contained apart from a Google Fonts import.

What it contains (14 sections): the mechanism diagram, inputs, agent responsibilities table,
signal/evidence model, six-dimension qualification model, strategy layer with persona x service
weighting, outreach and sales prep, evaluation framework, human approval UX, guardrails, memory
architecture, build sequence, technical pattern, and ready-made skills.

## Third-party material adapted

### ai-sales-team-claude (MIT) — evaluated 2026-09-03

`https://github.com/zubair-trabzada/ai-sales-team-claude` — a Claude Code CLI plugin (14 skills,
5 subagent prompts, 4 Python scripts) for solo operators. **Not usable as a system** here: it has no
persistence, no approval gate, no evidence store, and writes standalone markdown per run — the
opposite shape from this governed, database-backed pipeline. Its prompt engineering and content,
however, were worth mining. What we adapted, and where:

| Adapted | Into |
|---|---|
| Persona / seniority / buying-role keyword taxonomy | [03 — `contact`](../03-data-model.md) |
| Business-context weighting (adapted: its six fixed archetypes became industry + a derived size band — see [09](../09-vocabulary-rework.md)) | [02 §5.1](../02-architecture.md), `account.industry_key` |
| Per-signal-type research query families + the three evidence rules | [06 §7.1](../06-llm-integration.md) |
| Feel-Felt-Found and Acknowledge-Bridge-Close objection frameworks | [06 §7.2](../06-llm-integration.md) |
| 11-section proposal outline | Not adopted — shown in the mockup as a proposed fourth Sales Prep artifact, pending a decision |

Deliberately **not** adapted: its hardcoded scoring constants (we use versioned `scoring_config`
rows), its single-channel outreach model (we run persona-weighted concurrent threads), its
`reportlab` PDF generator (we use Agent Skills), and its flow generally — nothing in it survives
contact with the human approval gate.

Attribution is carried inline at each adaptation point. MIT licence terms are satisfied by that
attribution; no source files were copied verbatim into this repository.

## Divergences from the source document

These docs deviate from the approach doc in exactly two places, both deliberate and both flagged:

1. **Claude Agent SDK -> Claude API + Tool Runner.** See `../06-llm-integration.md` section 1.
   Reason: nine of ten stages are single structured calls, not agentic loops.
2. **Qualification maths moved out of the LLM into Python.** See `../02-architecture.md` section 6.
   Reason: auditability, swappability, and free bulk re-scoring.

Everything else follows the source document as written.
