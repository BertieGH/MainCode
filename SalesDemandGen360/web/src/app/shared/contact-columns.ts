import { RATING_COLUMNS_COMPACT } from './rating-columns';
import { ColumnDef } from './table-view';

/**
 * Every contact field worth putting on a screen, and which ones start visible.
 *
 * Defined once and shared by the list view and the account view, so a rep who
 * learns the layout in one place recognises it in the other — and so a field
 * added to the API reaches both without being remembered twice.
 *
 * Most default to hidden. Twenty columns at once is not a table anybody reads;
 * the six that start on are the ones that answer "is this person reachable and
 * are they the right person". The rest are there for the moment somebody is
 * asking a narrower question — *which provider found this address*, *why is
 * this one risky* — and the picker is how they get there.
 */
export const CONTACT_COLUMNS: ColumnDef[] = [
  { key: 'full_name', label: 'Name', width: 170 },
  { key: 'title', label: 'Title', width: 200 },
  { key: 'account_name', label: 'Company', width: 190 },
  ...RATING_COLUMNS_COMPACT,

  {
    key: 'email',
    label: 'Email',
    width: 210,
    // Blank is the common state before enrichment runs, and an empty cell
    // reads as a rendering fault rather than as "nobody has found it yet".
    value: (r) => r.email ?? '—',
  },
  {
    key: 'email_status',
    label: 'Email status',
    width: 110,
    filter: 'enum',
    // The field the send gate turns on: only `verified` may be written to,
    // and a provider's own `guessed` arrives here as `risky`.
    // A verified address older than 90 days says so: people move on, and a
    // revived account's addresses may date from a check nobody remembers.
    value: (r) => (r.email_recheck ? 'verified · re-check' : r.email_status ?? 'unverified'),
  },
  {
    key: 'email_provider',
    label: 'Found by',
    width: 100,
    filter: 'enum',
    // Provenance. A bad address should cost trust in one source, not in every
    // address on the list.
    value: (r) => r.email_provider ?? '—',
  },

  { key: 'seniority', label: 'Seniority', width: 100, filter: 'enum', defaultVisible: false },
  {
    key: 'buying_role',
    label: 'Buying role',
    width: 130,
    filter: 'enum',
    defaultVisible: false,
    // What they do to a purchase — distinct from `persona_role`, which is the
    // part of the business they sit in.
    value: (r) => r.buying_role ?? '—',
  },
  {
    key: 'persona_role',
    label: 'Function',
    width: 120,
    filter: 'enum',
    defaultVisible: false,
    value: (r) => r.persona_role ?? '—',
  },

  {
    key: 'phone',
    label: 'Phone',
    width: 140,
    defaultVisible: false,
    value: (r) => r.phone ?? '—',
  },
  {
    key: 'phone_status',
    label: 'Phone status',
    width: 110,
    filter: 'enum',
    defaultVisible: false,
    value: (r) => r.phone_status ?? '—',
  },
  {
    key: 'phone_provider',
    label: 'Phone found by',
    width: 120,
    filter: 'enum',
    defaultVisible: false,
    value: (r) => r.phone_provider ?? '—',
  },

  {
    key: 'linkedin_url',
    label: 'LinkedIn',
    width: 90,
    filter: 'none',
    defaultVisible: false,
    value: (r) => (r.linkedin_url ? 'yes' : '—'),
  },
  {
    key: 'do_not_contact',
    label: 'Do not contact',
    width: 150,
    filter: 'enum',
    // The reason is the column's whole point: "why is this person off limits"
    // is asked later, by somebody who was not there when it was set.
    value: (r) => (r.do_not_contact ? r.do_not_contact_reason || 'do not contact' : '—'),
  },
  { key: 'account_domain', label: 'Domain', width: 160, defaultVisible: false },
  {
    key: 'email_confidence',
    label: 'Confidence',
    width: 100,
    numeric: true,
    filter: 'none',
    defaultVisible: false,
    value: (r) => (r.email_confidence == null ? '—' : Number(r.email_confidence).toFixed(2)),
  },
  {
    key: 'is_hypothesis',
    label: 'Inferred',
    width: 90,
    filter: 'enum',
    defaultVisible: false,
    // A model guessed this person rather than a provider or a file naming
    // them. Never treated as fact, so it has to be visible when it is true.
    value: (r) => (r.is_hypothesis ? 'yes' : 'no'),
  },
  {
    key: 'created_at',
    label: 'Added',
    width: 110,
    filter: 'none',
    defaultVisible: false,
    value: (r) => (r.created_at ? String(r.created_at).slice(0, 10) : '—'),
  },
];
