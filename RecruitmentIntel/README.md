# Recruitment Intelligence Engine

End-to-end pipeline for turning venture-funding news into a curated recruitment outreach list.
Each layer is independently inspectable and re-runnable from the UI.

```
RSS feeds ─► News Log ─► Signal Log ─► Prospect Theams ─► Outreach
   (raw       (every       (extracted     (enriched +       (flat job
   articles)   article +    funding         job-crawled       list per
               LLM verdict) events)         companies)        prospect)
```

---

## Stack

| Layer | Tech |
|---|---|
| Frontend | Angular 17 (standalone components), Angular Material |
| Backend | FastAPI + SQLAlchemy (async), arq worker (Redis-optional, in-process fallback) |
| DB | SQLite for dev (auto-migrating ALTERs), PostgreSQL via Alembic for prod |
| LLM | Pluggable provider — Gemini (free / paid tier) or Ollama (local) |
| Scraping | httpx for fast fetches; Playwright (sync API in thread executor) for JS-rendered pages |
| Background | arq cron for scheduled ingestion; in-process `fire_and_forget` when Redis is down |

**Local dev:** `run.bat` launches both halves (`backend/dev_server.py` for the API on :8002, Angular dev server on :4200). The launcher pins `WindowsProactorEventLoopPolicy` before uvicorn starts so Playwright's subprocess works under `--reload`.

---

## Pipeline overview

### 1. Ingestion (`backend/app/services/rss_ingestion.py`)

Triggered by **Ingest Now** in News Log or by the configured cron interval (`fetch_interval_hours`).

For each active feed:
1. **Fetch** via `feedparser`, capped at `articles_per_feed_limit` per run.
2. **Dedup by URL** against existing rows.
3. **Keyword gate** — per-feed keywords win, fall back to globals. Empty gate = pass-through. No match → article saved with verdict `keyword_filtered` (NOT sent to LLM).
4. **Country tag** (cheap, regex-based, see `country_detection.py`) on title + summary, no LLM call.
5. **LLM extraction** (skipped if `auto_extract_on_ingest` is off — article stored as `pending`).
   - Article body resolved via httpx → Playwright fallback when the URL is a Google-News redirect shell.
   - Configurable extraction prompt (`{title}` / `{text}` / `{published}` placeholders).
   - **Date sanity guard**: if LLM-returned date is more than 14 days before the RSS feed's `published` date, prefer the feed date (catches "had previously raised X in May 2024" historical mentions).
   - **Location backfill**: when extraction returns funding=true with empty location, a focused 2nd-pass LLM call asks for the company's HQ (allowed to use general knowledge).
6. **Persist** — Article row records the verdict; if funding, a Signal row is created with a unique `source_url`. Article's country is upgraded from the precise HQ derived from the saved Signal location.

**Verdicts:** `funding`, `not_funding`, `keyword_filtered`, `parse_failed`, `validation_failed`, `quota_exceeded`, `service_unavailable`, `error`, `pending`.

### 2. News Log

Diagnostic view of every article we've seen.

| Feature | Notes |
|---|---|
| Verdict summary cards | Click to filter |
| Filters (collapsible card) | Verdict / Feed / Run / Country / Date range / Free-text search / Min keyword hits / Sort |
| Global keyword chips | Click to filter (ANY/ALL mode); "Refresh keyword matches" rescores all stored articles against current globals |
| Country column | Sortable; empty rows always sink to the bottom; **Backfill country (LLM)** runs on selection or up to 100 untagged rows |
| Date column | Article's RSS-published date (parsed RFC2822 / ISO / etc.), with hover tooltip showing both Published + Ingested timestamps |
| Pagination | Client-side over the loaded set (server returns up to 500 rows per request) |
| Per-row actions | Extract / Re-extract / Delete; Re-extract also updates `article.country` from the freshly extracted location |
| Recent Ingestion Runs | Collapsible accordion — header summarises the latest run; auto-opens after **Ingest Now** |

### 3. Signal Log (`backend/app/api/signals.py`)

Every funding event the LLM successfully extracted.

| Feature | Notes |
|---|---|
| Filters | Industry / Round / Amount range / Location text / Date range |
| Sortable columns | Company / Industry / Round / Amount / Location / Date / Source (all empty-last for nullable strings) |
| Per-row actions | Trash icon |
| Bulk actions | Multi-select → **Add to Theam** (creates new or appends to existing) or **Delete Selected** |
| Dedup on add | 3 layers: same `signal_id` already on theam, same normalised company name on theam, duplicate within the input batch |

### 4. Prospect Theams (`prospect-lists` page) → Prospect List view

Curated buckets of companies you're actively targeting.

**Theams index:**
- "New Prospect Theam" creates a named bucket.
- Cards show enrichment + crawl + jobs progress.
- Open → per-theam Prospect List view.

**Inside a theam:**
- Columns: Company / Industry / Round / Amount / Website / LinkedIn / Jobs / Actions.
- **LinkedIn cell** — green ✓ tick + tooltip + inline refresh icon when enrichment done.
- **Jobs cell** — coloured icon per crawl outcome:
  - green ✓ + count for `done`
  - amber ⓘ "0 jobs" for `empty` (career page validated, 0 listings)
  - red ⚠ "no page" for `failed` (no career page found)
  - spinner for `pending`
  - inline refresh icon on all settled outcomes
- **Actions cell** — Enrich / Crawl jobs / Delete (always visible; tooltip flips between "Enrich" ↔ "Re-enrich").
- **Live indicator** in header reads `live · refreshed Xs ago` with 1Hz tick + force-refresh button.
- **Polling is the source of truth** — single-prospect endpoints are sync, but if the response is dropped, polling watches the DB until the row settles. Snackbars on every status transition.

#### Enrichment cascade (`backend/app/services/enrichment.py`)
1. **LinkedIn discovery first** (Playwright on `/about/` unwraps the company website).
2. **Website discovery**: domain-guess (incl. abbreviation variants like `tech ↔ technology`) → Google search → LLM inference.
3. **Cross-verify** (`cross_verify_website_linkedin`): fetch website, extract self-reported LinkedIn link, swap if mismatch. Strategy suffix: `+verified` / `+reconciled` / `+unverified` / `+unreachable`.

#### Job-crawl pipeline (`backend/app/services/job_scraper.py`)
4-stage gated:
1. **Discover up to 8 careers candidates** across 5 strategies (URL pattern, homepage links, ATS host detection, Google search, LinkedIn).
2. **Classify each** as `listings` / `hub` / `junk` (JSON-LD JobPosting count, ATS-specific selectors, anchor heuristics with strong + loose signals; loose-signal `title_only` count of ≥5 catches Ashby's `/{slug}/{uuid}` URL pattern).
   - **External-ATS pivot**: a static company-careers page that delegates to a known ATS (`jobs.ashbyhq.com`, `boards.greenhouse.io`, `jobs.lever.co`, `apply.workable.com`, etc.) is detected by ≥3 outbound anchors to the same `host/first-path-segment` and the pipeline pivots to the derived tenant board.
   - **Playwright SPA retry**: junk classifications get a single Playwright retry; runs the sync Playwright API in a thread executor to bypass uvicorn's `--reload` SelectorEventLoop (Windows).
3. **Extract** per validated page — JSON-LD → ATS-specific (Greenhouse pulls title from `p.body--medium` and location from `p.body__secondary`; trailing-badge regex strips "New / Featured / Hot / Just Posted") → tightened generic → LLM gate.
4. **Match to target titles** (configurable, default empty = save all). Cheap substring pass first, then a single batched LLM call. Match coercion against the configured target list rejects paraphrases (`"Software engineer(any)"` → `"Software engineer(any IT)"`). Strict prompt rejects Engineering Managers, pre-sales Solutions Engineers, Customer Success, Recruiters, etc.
5. **Classify** dept / seniority / type / skills via LLM; title-keyed lookup tolerates partial responses.
6. **Persist** with `_dedupe_jobs` keyed by URL (with normalised trailing slash / fragment) and field merging — empty-location duplicates are merged with a populated row.

**Status semantics:** `failed` = no candidate validated; `empty` = pages validated but 0 jobs (or 0 after target match); `done` = ≥1 job saved.

### 5. Outreach (`backend/app/api/outreach.py`)

Flat job-list view across one or more theams.
- Theam selector at the top.
- Filter / sort by department, seniority, location, target match.
- Each row links to the actual ATS posting (Greenhouse / Lever / Ashby / etc.).
- CSV export.

---

## Configurable LLM prompts

Three job-crawl prompts (`job_extract_prompt`, `job_match_prompt`, `job_classify_prompt`) plus the funding-extraction prompt (`extraction_prompt`) are user-editable from **Settings**.

- Substitution uses `_render_prompt(template, **kwargs)` with plain `template.replace("{key}", value)` — users can write JSON examples with literal braces in the prompt editor (no Python-format escaping required).
- **Job Crawl Prompts** card has a preset selector (CRUD via `JobPromptProfile` model) so named prompt sets ("Strict IC engineer", "Generous match", etc.) can be saved/loaded.
- The funding-extraction prompt has its own preset system (`ExtractionProfile`) seeded with a Funding Scraper preset on first start.

---

## Country detection (`backend/app/services/country_detection.py`)

Cheap, regex-based, no LLM call.
- `COUNTRY_KEYWORDS` for US / GB / IN / CA / DE / FR / IL / SG / AU / NL / IE plus US 2-letter state codes (case-sensitive to avoid false matches on common short words).
- Pre-compiled per-country regex with `\b` word boundaries.
- `detect_country_from_text(title, summary)` for ingest-time tagging.
- `detect_country_from_location(location)` for upgrade after Signal extraction (more accurate).
- LLM backfill (`POST /articles/backfill-countries`) for rows the regex preset missed: optional `article_ids` runs only on selected rows, otherwise up to `limit` most-recent untagged articles. Output validated against `KNOWN_COUNTRY_CODES`.

---

## Settings panel

Persisted to the singleton `app_settings` row; mirrored onto the in-memory `pydantic` config at startup.

- **AI Provider** — Gemini (free / paid radio toggle, two masked keys; paid tier retries 429 with backoff, free tier bails the batch on first 429) or Ollama. Test connection button.
- **Extraction Intent** — funding-extraction prompt + global scrape keywords + preset CRUD.
- **Ingestion Schedule** — fetch interval, articles-per-feed limit, LLM article char budget (clamped 500–30000).
- **Job Crawl Strategy** — career-page patterns, fallback toggles, ATS detection list, target job titles (CSV input), max listings / sub-category page caps.
- **Job Crawl Prompts** — three editable prompts + preset CRUD.

---

## Per-page in-app help

Every major menu page has an **ⓘ** info icon next to the heading that opens a Material dialog with the page's full workflow rendered as a step-by-step diagram (icon badges, arrows, branch indentation, intricacies as bullets). Content lives in `src/app/components/info-dialog/workflows.ts`.

---

## Project layout

```
backend/
├── app/
│   ├── api/                FastAPI routers (signals, articles, prospect_lists, enrichment, job_crawl, outreach, settings, …)
│   ├── models/             SQLAlchemy ORM
│   ├── schemas/            Pydantic IO shapes
│   ├── services/
│   │   ├── rss_ingestion.py            ingest pipeline
│   │   ├── signal_extraction.py        LLM extraction + location/country backfill helpers + date sanity guard
│   │   ├── enrichment.py               website/LinkedIn discovery cascade
│   │   ├── career_discovery.py         5-strategy careers URL discovery
│   │   ├── job_scraper.py              4-stage gated job extraction + classification + match
│   │   ├── country_detection.py        regex country tagger
│   │   └── llm_provider.py / llm_gemini.py / llm_ollama.py
│   ├── tasks/worker.py     arq WorkerSettings (cron + on-demand jobs)
│   ├── background.py       fire_and_forget keeps in-process tasks GC-anchored
│   ├── database.py         engine + sqlite ALTER bootstrap
│   └── main.py             FastAPI app + lifespan
├── alembic/versions/       015 migrations and counting
├── dev_server.py           uvicorn launcher with ProactorEventLoopPolicy
└── recruitmentintel.db     local SQLite

src/app/
├── pages/
│   ├── news-log/
│   ├── signal-log/
│   ├── prospect-lists/
│   ├── prospect-detail/
│   ├── outreach/
│   ├── feeds/
│   └── settings/
├── components/
│   ├── nav-bar/
│   └── info-dialog/        shared workflow help dialog + per-page content
├── services/api.service.ts toCamel/toSnake auto-converter, every endpoint
└── models/interfaces.ts
```

---

## Running locally

```bat
run.bat
```

Starts:
- Backend on http://localhost:8002 (`backend/dev_server.py` → uvicorn with reload)
- Frontend on http://localhost:4200 (`npm start`)

Worker (only needed for production-style background jobs; in-process fallback works without it):

```bat
run-worker.bat
```

Note: `docker-compose.yml` exposes Redis on host port **6380**; `config.py` defaults to `redis://localhost:6379/0`. For full worker setup, set `RI_REDIS_URL=redis://localhost:6380/0` in `backend/.env`.

---

## Schema migrations

- **Postgres (prod):** `alembic upgrade head`. Migrations 001 → 015 cover everything: app_settings columns, articles, ingestion_runs, extraction_profiles, job_prompt_profiles, prospect diagnostics, country, etc.
- **SQLite (dev):** `database.py::_sqlite_add_missing_columns` runs in the lifespan hook and ALTERs the local DB on startup so schema changes don't force a DB reset.

---

## Settings field wiring (8-touchpoint precedent)

When you add a persisted setting, follow this pattern (used for `llm_article_char_budget`, `gemini_paid_api_key`, country, prompt fields, etc.):

1. `backend/app/config.py` — add to `Settings` with default
2. `backend/app/models/app_setting.py` — add `Mapped[T]` column
3. `backend/app/services/settings_store.py` — append name to `PERSISTED_FIELDS`
4. `backend/app/database.py::_sqlite_add_missing_columns` — `ALTER TABLE app_settings ADD COLUMN …`
5. `backend/alembic/versions/<NNN>_<name>.py` — `op.add_column`
6. `backend/app/schemas/feed.py` — add to `SettingsOut` and `SettingsUpdate`
7. `backend/app/api/settings.py::get_settings` — include in response
8. `src/app/models/interfaces.ts::AppSettings` + `settings.component.ts` UI wiring (snake_case ↔ camelCase auto-converter handles the wire format)

---

## Key non-obvious behaviours

- **Single-prospect enrich/crawl endpoints are sync** so the UI gets the full payload inline; bulk endpoints (`/prospect-lists/{id}/enrich`, `/crawl-jobs`) prefer the arq worker and fall back to in-process `fire_and_forget` if Redis is down.
- **`fire_and_forget(coro, name=…)`** in `app/background.py` keeps a process-wide strong reference set so in-process tasks aren't GC'd mid-execution.
- **Cron reschedule needs a worker restart** — `WorkerSettings` reads `fetch_interval_hours` at module load.
- **Live cron timezone & feed dates** — every relative date in the codebase is converted to absolute YYYY-MM-DD.
- **MatTable re-render** in Prospect List uses `@ViewChild(MatTable).renderRows()` after every row mutation plus `trackBy: id` — plain-array `[dataSource]` doesn't re-render on content change.
