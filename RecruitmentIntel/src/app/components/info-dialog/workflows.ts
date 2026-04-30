import { InfoDialogData } from './info-dialog.component';

/** Workflow shown by the (i) icon on the News Log page. */
export const NEWS_LOG_WORKFLOW: InfoDialogData = {
  title: 'How News Log works',
  intro:
    'News Log shows every article we saw during ingestion plus the LLM verdict on it. ' +
    'Use it to diagnose why a feed isn\'t producing signals.',
  sections: [
    {
      heading: 'Ingest pipeline (when you click "Ingest Now")',
      description: 'Each active RSS feed is fetched, filtered, then optionally LLM-extracted.',
      steps: [
        {
          icon: 'rss_feed', color: '#1976d2',
          title: 'Fetch feed',
          subtitle: 'feedparser pulls each active feed; "articles_per_feed_limit" caps per-run volume.',
          bullets: [
            'New URLs only — already-seen URLs are skipped (dedup by url).',
          ],
        },
        {
          icon: 'filter_alt', color: '#7b1fa2',
          title: 'Keyword gate',
          subtitle: 'Per-feed keywords win, fall back to global. Empty gate = pass everything through.',
          bullets: [
            'Case-insensitive substring match on title+summary.',
            'No match → article saved with verdict "keyword_filtered" (NOT sent to LLM).',
          ],
        },
        {
          icon: 'public', color: '#0288d1',
          title: 'Country tag (cheap)',
          subtitle: 'Regex match per-country preset (US/GB/IN/CA/DE/FR/IL/SG/AU/NL/IE) on title+summary.',
          bullets: [
            'Word-boundary safe (US state codes case-sensitive).',
            'No match → country = "" (backfillable later via LLM).',
          ],
        },
        {
          icon: 'auto_awesome', color: '#ef6c00',
          title: 'LLM extraction',
          subtitle: 'Skipped if "Auto extract" is off → article stored as "pending".',
          bullets: [
            'Article body fetched (httpx → Playwright fallback if redirect-shell).',
            'Extraction prompt asks for company, round, amount, industry, location, date, country.',
            'Date sanity guard: if LLM date is >14d before feed published, prefer feed date.',
            'Empty location → focused 2nd LLM call asks for company HQ (uses general knowledge).',
          ],
        },
        {
          icon: 'check_circle', color: '#43a047',
          title: 'Verdict + persist',
          subtitle: 'Article row records verdict; if funding, a Signal row is created and linked.',
          bullets: [
            'Verdicts: funding, not_funding, keyword_filtered, parse_failed, validation_failed, quota_exceeded, service_unavailable, error.',
            'Signal upgrades the article country from its precise HQ location.',
          ],
        },
      ],
    },
    {
      heading: 'View tools on this page',
      steps: [
        {
          icon: 'filter_list', color: '#5e35b1',
          title: 'Filters & search',
          bullets: [
            'Verdict / Feed / Run / Country / Date range dropdowns + free-text search.',
            'Keyword chips: click to filter by global keyword (ANY/ALL mode).',
            'Min keyword hits: hide articles below a threshold.',
            'Active count badge on the collapsed panel header.',
          ],
        },
        {
          icon: 'public', color: '#0288d1',
          title: 'Backfill country (LLM)',
          subtitle: 'Click button next to "Refresh keyword matches".',
          bullets: [
            'No selection → up to 100 most recent untagged articles.',
            'Selected rows → re-tag exactly those (overrides existing country).',
            'LLM gets company name + linked Signal location + article excerpt.',
          ],
        },
        {
          icon: 'refresh', color: '#43a047',
          title: 'Refresh keyword matches',
          subtitle: 'Re-scans every article\'s title+summary against current global keywords.',
          bullets: ['Pure scan — no LLM calls. Useful after editing global keywords.'],
        },
        {
          icon: 'auto_awesome', color: '#ef6c00',
          title: 'Per-row Extract / Re-extract',
          bullets: [
            'Extract: runs LLM on a row currently in pending/error/parse_failed/etc.',
            'Re-extract: wipes any existing Signal for the same URL and re-runs.',
            'Updates article.country from the freshly extracted location too.',
          ],
        },
      ],
    },
  ],
  notes: [
    'Date column shows the article\'s published date (parsed from RSS), with hover-tooltip showing both Published + Ingested timestamps.',
    'Pagination is client-side over the loaded set (server returns up to 500 rows per request).',
    '"keyword_filtered" articles are saved but never reach the LLM — they cost zero LLM tokens.',
  ],
};

/** Workflow shown on Signal Log. */
export const SIGNAL_LOG_WORKFLOW: InfoDialogData = {
  title: 'How Signal Log works',
  intro:
    'Signal Log lists every funding event the LLM successfully extracted. ' +
    'Each row is a structured deal you can promote into a Prospect Theam.',
  sections: [
    {
      heading: 'Where signals come from',
      steps: [
        {
          icon: 'rss_feed', color: '#1976d2',
          title: 'RSS ingest',
          subtitle: 'Triggered manually ("Ingest Now" on News Log) or on the configured cron schedule.',
        },
        {
          icon: 'auto_awesome', color: '#ef6c00',
          title: 'LLM extraction',
          subtitle: 'Only articles whose verdict = "funding" produce a Signal row.',
          bullets: [
            'Schema: company_name, industry, funding_round, amount, location, country, date.',
            'Empty location → 2nd-pass LLM call ("what city is X HQ\'d in?") fills it.',
            'Date sanity: never older than the article\'s feed-published date.',
          ],
        },
        {
          icon: 'fingerprint', color: '#5e35b1',
          title: 'Dedup by source URL',
          subtitle: 'Signal.source_url is unique — same article never produces two signals.',
        },
      ],
    },
    {
      heading: 'What you can do here',
      steps: [
        {
          icon: 'tune', color: '#7b1fa2',
          title: 'Filter the table',
          bullets: [
            'Industry, Round, Amount range, Location text, Date range.',
          ],
        },
        {
          icon: 'check_box', color: '#0288d1',
          title: 'Select rows',
          bullets: ['Use checkboxes to multi-select for bulk actions.'],
        },
        {
          icon: 'playlist_add', color: '#43a047',
          title: 'Add to Prospect Theam',
          subtitle: 'Pick existing theam OR create a new one.',
          bullets: [
            'Dedup runs server-side: same signal_id, same normalised company name (across the theam), or duplicate within the selection — all skipped with a per-row reason.',
          ],
        },
        {
          icon: 'delete', color: '#e53935',
          title: 'Delete signal(s)',
          subtitle: 'Per-row trash icon or bulk "Delete Selected".',
        },
      ],
    },
  ],
  notes: [
    'A signal\'s `location` is what later drives the country tag for the linked article and the prospect HQ.',
    'Promoting a signal into a Theam creates a Prospect row that downstream Enrichment + Job Crawl operate on.',
  ],
};

/** Workflow shown on Prospect Theams (the index of theams). */
export const PROSPECT_THEAMS_WORKFLOW: InfoDialogData = {
  title: 'How Prospect Theams work',
  intro:
    'A Prospect Theam is a curated bucket of companies you\'re actively targeting. ' +
    'Each theam tracks enrichment + job-crawl progress per row.',
  sections: [
    {
      heading: 'Theam lifecycle',
      steps: [
        {
          icon: 'add_circle', color: '#1976d2',
          title: 'Create theam',
          subtitle: '"New Prospect Theam" button — give it a name + optional description.',
        },
        {
          icon: 'playlist_add', color: '#7b1fa2',
          title: 'Add companies from Signal Log',
          subtitle: 'Multi-select on Signal Log → "Add to List" → pick theam.',
          bullets: [
            'Skips: signal already added, duplicate company name on theam, duplicate within the selection.',
          ],
        },
        {
          icon: 'list_alt', color: '#0288d1',
          title: 'Open a theam',
          subtitle: 'Click "Open" on a card → opens the per-theam Prospect List view.',
        },
      ],
    },
    {
      heading: 'Inside a theam (Prospect List)',
      steps: [
        {
          icon: 'search', color: '#ef6c00',
          title: 'Enrich (per row or "Enrich All")',
          subtitle: '3-strategy cascade discovers website + LinkedIn + careers URL.',
          bullets: [
            'LinkedIn discovery first (Playwright on /about/ unwraps the company website).',
            'Website discovery: domain-guess → Google search → LLM inference.',
            'Cross-verify: fetch website, look for self-reported LinkedIn link, swap if mismatch.',
            'Strategy label suffix: +verified / +reconciled / +unverified.',
          ],
        },
        {
          icon: 'bug_report', color: '#43a047',
          title: 'Crawl jobs (per row or "Crawl All")',
          subtitle: '4-stage gated pipeline turns careers page into Job rows.',
          bullets: [
            'Discover up to 8 careers candidates (URL pattern, homepage, ATS, Google, LinkedIn).',
            'Classify each: listings / hub / junk (JSON-LD, ATS selectors, anchor heuristics).',
            'External-ATS pivot: e.g. company.com/careers → 11 anchors to jobs.ashbyhq.com/<slug>/<uuid> → fetch the derived ATS root.',
            'Extract: JSON-LD → ATS-specific → tightened generic → LLM gate.',
            'Match to target titles (configurable in Settings) — strict; LLM coerced to exact target string.',
            'Classify dept/seniority/skills via LLM.',
          ],
        },
        {
          icon: 'green_circle', color: '#43a047',
          title: 'Visual cues per row',
          bullets: [
            'Green tick next to LinkedIn → enrichment done (hover for strategy detail).',
            'Green tick next to Jobs → job crawl done (hover for careers URL + counts).',
            'Refresh icon next to either → re-run that step in place.',
          ],
        },
        {
          icon: 'output', color: '#5e35b1',
          title: 'Send to Outreach',
          subtitle: 'When jobs exist, the theam\'s rows feed the Outreach view.',
        },
      ],
    },
  ],
  notes: [
    'Per-prospect single-action endpoints are sync (UI shows full payload inline). Bulk "All" endpoints use arq worker if Redis is up, else in-process asyncio fallback.',
    'job_crawl_status: pending → done | empty | failed. "empty" means we validated a careers page but extracted 0 matching jobs.',
    'enrichment_status: pending → done | failed. "failed" = no strategy returned anything (rare).',
  ],
};

/** Workflow shown on Outreach. */
export const OUTREACH_WORKFLOW: InfoDialogData = {
  title: 'How Outreach works',
  intro:
    'Outreach is the flat job-list view across one or more Prospect Theams. ' +
    'It\'s where you see every recruitable job we\'ve crawled and export them.',
  sections: [
    {
      heading: 'Where Outreach data comes from',
      steps: [
        {
          icon: 'list_alt', color: '#1976d2',
          title: 'Pick a theam',
          subtitle: 'Theam selector at the top filters which prospects feed this view.',
        },
        {
          icon: 'business', color: '#7b1fa2',
          title: 'Per-prospect job rows',
          subtitle: 'Every Job row from "Crawl jobs" lives here, joined to its company.',
          bullets: [
            'Job has: title, department, seniority, job_type, location, url, skills, match_target.',
            'match_target = which configured Target Job Title this matched (e.g. "Software engineer(any IT)").',
          ],
        },
      ],
    },
    {
      heading: 'What you can do',
      steps: [
        {
          icon: 'filter_alt', color: '#5e35b1',
          title: 'Filter / sort',
          bullets: [
            'Department, seniority, location, target-match column.',
          ],
        },
        {
          icon: 'open_in_new', color: '#0288d1',
          title: 'Click through to the listing',
          subtitle: 'URL is the actual ATS posting (Greenhouse / Lever / Ashby / etc.) — opens in new tab.',
        },
        {
          icon: 'download', color: '#43a047',
          title: 'CSV export',
          subtitle: 'Bulk-download for downstream outreach tooling.',
        },
      ],
    },
  ],
  notes: [
    'A row in Outreach is a Job, not a Prospect. One prospect typically yields several rows (one per matched listing).',
    'Re-running "Crawl jobs" in the Prospect Theam doesn\'t double-insert — dedup is by URL with field-merging (empty location is replaced by a populated one).',
    'Target-match is LLM-judged with a strict prompt; non-IC roles (Engineering Manager, Solutions Engineer pre-sales, etc.) are excluded.',
  ],
};
