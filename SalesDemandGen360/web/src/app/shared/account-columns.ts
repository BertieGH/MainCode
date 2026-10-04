import { ColumnDef, RowAction } from './table-view';

/**
 * Every account field worth putting on a screen, and which start visible.
 *
 * Grouped so the dropdown stays scannable: identity is what the account *is*,
 * firmographics are what it looks like, pipeline is how far it has got.
 *
 * Six on by default. Nine were shown before and a rep wanted three; the answer
 * is not a better fixed set but a choice that survives a reload.
 */
export const ACCOUNT_COLUMNS: ColumnDef[] = [
  { key: 'name', label: 'Company', width: 210, group: 'identity' },
  {
    // Ranking the book is what the score is for, so it belongs where the book
    // is read. Sorted server-side, where unjudged accounts sort last rather
    // than opening "best first" with everything nobody has scored.
    key: 'priority_score',
    label: 'Company rating',
    width: 130,
    filter: 'enum',
    group: 'identity',
    value: (r) =>
      r.priority_score == null ? 'not qualified' : `${r.priority_band} ${r.priority_score}`,
  },
  {
    key: 'domain',
    label: 'Domain',
    width: 190,
    group: 'identity',
    // The identity key: resolution, deduplication and Apollo all use it.
    value: (r) => r.domain ?? '—',
  },
  {
    key: 'resolution_status',
    label: 'Identity',
    // Wide enough for the badge, the confidence and Accept / Edit / Reject —
    // the cell is where a rep settles an identity, not just where it is shown.
    width: 250,
    filter: 'enum',
    group: 'identity',
    value: (r) =>
      ({
        resolved: 'confirmed',
        needs_review: 'check this',
        unresolved: 'not identified',
        rejected: 'rejected',
      })[r.resolution_status as string] ?? r.resolution_status,
  },
  {
    key: 'resolution_confidence',
    label: 'Confidence',
    width: 100,
    numeric: true,
    filter: 'none',
    defaultVisible: false,
    group: 'identity',
    value: (r) =>
      r.resolution_confidence == null ? '—' : Number(r.resolution_confidence).toFixed(2),
  },
  {
    key: 'resolved_by',
    label: 'Resolved by',
    width: 115,
    filter: 'enum',
    defaultVisible: false,
    group: 'identity',
    // Provenance: a wrong domain should be traceable to whoever supplied it.
    value: (r) => r.resolved_by ?? '—',
  },
  {
    key: 'linkedin_url',
    label: 'LinkedIn',
    width: 90,
    filter: 'none',
    defaultVisible: false,
    group: 'identity',
    value: (r) => (r.linkedin_url ? 'yes' : '—'),
  },

  {
    key: 'industry',
    label: 'Industry',
    width: 150,
    filter: 'enum',
    group: 'firmographics',
    value: (r) => r.industry ?? '—',
  },
  {
    key: 'employee_count',
    label: 'Employees',
    width: 100,
    numeric: true,
    filter: 'none',
    defaultVisible: false,
    group: 'firmographics',
    value: (r) => r.employee_count ?? '—',
  },
  {
    key: 'hq_country',
    label: 'Country',
    width: 100,
    filter: 'enum',
    defaultVisible: false,
    group: 'firmographics',
    value: (r) => r.hq_country ?? '—',
  },

  {
    key: 'icp_match_score',
    label: 'ICP fit',
    width: 90,
    numeric: true,
    filter: 'none',
    group: 'scoring',
    value: (r) => r.icp_match_score ?? '—',
  },

  {
    key: 'research_status',
    label: 'Research',
    width: 120,
    filter: 'enum',
    defaultVisible: false,
    group: 'pipeline',
  },
  {
    key: 'enrichment_status',
    label: 'Enrichment',
    width: 120,
    filter: 'enum',
    defaultVisible: false,
    group: 'pipeline',
  },
  { key: 'status', label: 'Status', width: 110, filter: 'enum', group: 'pipeline' },
];

/**
 * What can be done to an account, and what each needs first.
 *
 * `can` is written once and read three times — to enable a row's menu item, to
 * count how many of a selection a bulk action covers, and to say what the
 * report skipped. The rules mirror what the API actually enforces, so the
 * screen refuses for the same reasons the server would rather than guessing.
 */
export const ACCOUNT_ACTIONS: RowAction[] = [
  {
    key: 'resolve',
    label: 'Resolve identity',
    // Only `unresolved`. The resolver skips settled accounts *and* ones
    // awaiting review — re-running the same sources on a `needs_review`
    // account returns the same doubt. Offering it there was a button that
    // did nothing, which is exactly what it looked like.
    can: (r) => r.resolution_status === 'unresolved',
    why: 'already resolved, or waiting for your review',
  },
  {
    key: 'recheck',
    label: 'Re-check identity',
    // For accounts waiting for review, after something changed — a corrected
    // domain, or a source added. Runs the whole waterfall again, including the
    // website check, and may spend a model call.
    can: (r) => r.resolution_status === 'needs_review',
    why: 'only for accounts waiting for review',
  },
  {
    key: 'accept',
    label: 'Accept identity',
    // The human half of resolution. Needs a domain, because accepting "no
    // domain" confirms nothing and research would still have nothing to use.
    can: (r) =>
      (r.resolution_status === 'needs_review' || r.resolution_status === 'unresolved') &&
      !!r.domain,
    why: 'already settled, or no domain to confirm',
  },
  {
    key: 'reject',
    label: 'Reject identity',
    can: (r) => r.resolution_status !== 'rejected',
    why: 'already rejected',
    danger: true,
  },
  {
    key: 'enrich',
    label: 'Enrich contacts',
    // After identity, not before: paying a provider for the people at a
    // company nobody has confirmed is the wrong-company failure, bought.
    can: (r) => r.resolution_status === 'resolved',
    why: 'identity not confirmed',
  },
  {
    key: 'check_company',
    label: 'Check company',
    // Before finding people: the search goes by domain, so a domain that
    // redirects elsewhere finds another company's staff. The website is free;
    // Apollo's organisation record is a credit, only while something is missing.
    can: (r) => r.resolution_status === 'resolved' && !!r.domain,
    why: 'identity not confirmed, or no domain',
  },
  {
    key: 'find_contacts',
    label: 'Find contacts (Apollo)',
    // A free search for the ICP's personas. Suggestions only — nothing is
    // revealed, or paid for, until a rep accepts them.
    can: (r) => r.resolution_status === 'resolved' && !!r.domain,
    why: 'identity not confirmed, or no domain',
  },
  {
    key: 'qualify',
    label: 'Re-read & score',
    // Interpretation only: read the evidence already held into signals, then
    // score. No search, no credits — which is what makes it the answer to a
    // signal type added today, or a TTL widened today.
    can: (r) => r.resolution_status === 'resolved',
    why: 'identity not confirmed',
  },
  {
    key: 'research',
    label: 'Run research',
    // `pipeline.run_research` refuses anything unconfirmed — researching the
    // wrong company succeeds and nothing downstream can tell. Reuses anything
    // answered inside the reuse window.
    can: (r) => r.resolution_status === 'resolved',
    why: 'identity not confirmed',
  },
  {
    key: 'rerun',
    label: 'Rerun research',
    // Ignores the reuse window and pays again. Only where there is research
    // to redo — on a never-researched account it is just Run research.
    can: (r) => r.resolution_status === 'resolved' && r.research_status !== 'not_started',
    why: 'not researched yet',
  },
  {
    key: 'promote',
    label: 'Add to a campaign queue',
    can: (a) => a.resolution_status === 'resolved',
    why: 'identity not confirmed',
  },
  {
    key: 'queue',
    label: 'Add to queue',
    can: (r) => r.resolution_status === 'resolved' && r.status !== 'disqualified',
    why: 'not confirmed, or disqualified',
  },
  {
    key: 'remove',
    label: 'Remove from list',
    // Membership only. The account is kept — a list is a selection, not an
    // owner, and the same company legitimately sits on several.
    danger: true,
  },
];
