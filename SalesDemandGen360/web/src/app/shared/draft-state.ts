import { ColumnDef } from './table-view';

/**
 * Where a person's cadence drafts stand, as a column.
 *
 * Shared so the Strategy and Cadence drafts tabs say the same thing: strategy
 * and drafts are two different gates, and picking rows by one while acting on
 * the other is the mistake this column exists to prevent.
 */
export const DRAFT_STATE_COLUMN: ColumnDef = {
  key: 'draft_state',
  label: 'Cadence drafts',
  width: 170,
  filter: 'enum',
  value: (r: { draft_state_label?: string; draft_state?: string }) =>
    r.draft_state_label || r.draft_state || 'not drafted',
};

export function draftStateClass(state: string): string {
  if (state === 'approved' || state === 'enrolled') return 'badge-good';
  if (state === 'saved') return 'badge-accent';
  return 'badge-warn';
}
