import { RATING_COLUMNS_COMPACT } from './rating-columns';
import { ColumnDef, RowAction } from './table-view';

/**
 * Suggested contacts — people Apollo's free search proposed — in the standard
 * table, so they filter, sort, select and act like accounts and contacts do.
 * The first version was a hand-built table with two buttons per row and no way
 * to narrow thirty people at five companies down to the CTOs.
 *
 * Nothing here is revealed: a first name, Apollo's obfuscated surname, a
 * title, and whether Apollo holds an email and a location.
 */
export const SUGGESTION_COLUMNS: ColumnDef[] = [
  { key: 'account_name', label: 'Company', width: 160 },
  ...RATING_COLUMNS_COMPACT,
  {
    key: 'person',
    label: 'Person',
    width: 170,
    value: (r) => [r.first_name, r.last_name_hint].filter(Boolean).join(' '),
  },
  {
    key: 'linkedin_url',
    label: 'LinkedIn',
    width: 100,
    filter: 'enum',
    // Apollo's free search returns no profile; the reveal does. Filterable, so
    // "revealed but no profile" can be picked out.
    value: (r) =>
      r.linkedin_url ? 'profile' : r.status === 'revealed' || r.contact_id ? 'none found' : 'on reveal',
  },
  { key: 'title', label: 'Title', width: 260, value: (r) => r.title ?? '—' },
  { key: 'persona', label: 'Persona', width: 130, filter: 'enum', value: (r) => r.persona ?? '—' },
  {
    key: 'status',
    label: 'Decision',
    width: 110,
    filter: 'enum',
    // `known` is somebody already on the list with nothing left to buy.
    value: (r) => (r.status === 'proposed' ? 'undecided' : r.status),
  },
  {
    key: 'has_email',
    label: 'Apollo has email',
    width: 100,
    filter: 'enum',
    value: (r) => (r.has_email ? 'yes' : 'no'),
  },
  {
    key: 'has_location',
    label: 'Location held',
    width: 110,
    filter: 'enum',
    defaultVisible: false,
    value: (r) => (r.has_location ? 'yes' : 'no'),
  },
  {
    key: 'contact_name',
    label: 'On the list as',
    width: 150,
    // Already a contact on the account: revealing fills them in rather than
    // adding a second row.
    value: (r) => r.contact_name ?? '—',
  },
  { key: 'buying_role', label: 'Buying role', width: 130, filter: 'enum', defaultVisible: false,
    value: (r) => r.buying_role ?? '—' },
  { key: 'account_domain', label: 'Domain', width: 160, defaultVisible: false,
    value: (r) => r.account_domain ?? '—' },
  { key: 'refreshed_at', label: 'Apollo refreshed', width: 130, numeric: true, filter: 'none',
    defaultVisible: false, value: (r) => (r.refreshed_at ?? '').slice(0, 10) || '—' },
  { key: 'note', label: 'Note', width: 200, defaultVisible: false, value: (r) => r.note ?? '—' },
];

export const SUGGESTION_ACTIONS: RowAction[] = [
  {
    key: 'accept',
    label: 'Accept',
    can: (r) => r.status === 'proposed' || r.status === 'rejected',
    why: 'already accepted, revealed or on the list',
  },
  {
    key: 'reveal',
    label: 'Reveal (Apollo credit)',
    // Paid: one credit per person Apollo has data for. Asked to confirm first.
    can: (r) => r.status === 'accepted',
    why: 'accept it first',
  },
  {
    key: 'undecide',
    label: 'Back to undecided',
    can: (r) => r.status === 'accepted' || r.status === 'rejected',
    why: 'not decided yet',
  },
  {
    key: 'reject',
    label: 'Reject',
    can: (r) => r.status === 'proposed' || r.status === 'accepted',
    why: 'already rejected, revealed or on the list',
    danger: true,
  },
];
