import { ColumnDef } from './table-view';

/**
 * The company's rating, read for whichever ICP the screen is working for, and
 * whether it clears the qualify gate.
 *
 * One definition shared by every table that shows a person, a suggestion or a
 * queue's people, so the number means the same thing and is sorted and
 * filtered the same way wherever a rep meets it. The ICP the rating was read
 * for is in the hover text, because the same company rates differently for
 * different buyers.
 */
export interface RatingFields {
  qualification_score: number | null;
  qualification_band: string | null;
  /** `pass`, `below` or `not_qualified` against the minimum band for queueing. */
  gate: string;
  gate_detail: string;
}

export const GATE_LABELS: Record<string, string> = {
  pass: 'passes',
  below: 'below gate',
  not_qualified: 'not qualified',
};

export const RATING_COLUMNS: ColumnDef[] = [
  {
    key: 'qualification_score',
    label: 'Company rating',
    width: 140,
    numeric: true,
    filter: 'none',
    value: (r: RatingFields) =>
      r.qualification_score == null ? null : Math.round(r.qualification_score),
  },
  {
    key: 'qualification_band',
    label: 'Band',
    width: 110,
    filter: 'enum',
    value: (r: RatingFields) => r.qualification_band ?? 'not qualified',
  },
  {
    key: 'gate',
    label: 'Qualify gate',
    width: 130,
    filter: 'enum',
    value: (r: RatingFields) => GATE_LABELS[r.gate] ?? r.gate,
  },
];

/** The same three, with the two narrow ones off until somebody asks for them. */
export const RATING_COLUMNS_COMPACT: ColumnDef[] = RATING_COLUMNS.map((c, i) =>
  i === 0 ? c : { ...c, defaultVisible: false },
);

export function bandClass(band: string | null): string {
  return band === 'high' ? 'badge-good' : band === 'medium' ? 'badge-accent' : 'badge-neutral';
}

export function gateClass(gate: string): string {
  return gate === 'pass' ? 'badge-good' : gate === 'below' ? 'badge-warn' : 'badge-neutral';
}
