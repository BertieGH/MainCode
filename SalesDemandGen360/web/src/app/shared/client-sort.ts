import { SortState } from './sortable';

/**
 * Sorting and filtering a list the browser already holds whole.
 *
 * Two mechanisms exist in this application and the difference is not stylistic:
 * `lists` sorts on the server because an account book is unbounded, and every
 * other list — queues, campaigns, the threads in one campaign — is loaded
 * complete and small. Sorting those on the server would be a round-trip and an
 * endpoint allowlist for a job the client can do instantly.
 *
 * The rule for choosing: **sort where the data is complete.** A client-side
 * sort over a paginated response silently sorts one page and presents it as
 * the whole list, which is worse than no sort at all.
 */

/** Pull the comparable value for a field out of a row. */
export type Accessor<T> = (row: T) => unknown;

/**
 * Sort a copy of `rows`.
 *
 * Copies rather than sorting in place: the caller usually holds the unsorted
 * array in a signal, and `Array.sort` mutating it would make the "no sort"
 * state unreachable — the original order would already be gone.
 */
export function sortRows<T>(
  rows: readonly T[],
  state: SortState,
  accessors: Record<string, Accessor<T>>,
): T[] {
  const copy = [...rows];
  if (!state.field || !state.direction) return copy;

  const get = accessors[state.field];
  if (!get) return copy;

  const sign = state.direction === 'asc' ? 1 : -1;
  return copy.sort((a, b) => {
    const left = get(a);
    const right = get(b);
    const leftEmpty = isEmpty(left);
    const rightEmpty = isEmpty(right);

    // Emptiness is decided *outside* the direction multiplier, deliberately.
    // Folding it into `compare` and multiplying flips it on descending, which
    // fills the top of the screen with rows that have nothing in the column
    // being sorted — the opposite of what somebody sorting by it wants.
    if (leftEmpty || rightEmpty) {
      if (leftEmpty && rightEmpty) return 0;
      return leftEmpty ? 1 : -1;
    }
    return sign * compare(left, right);
  });
}

function isEmpty(value: unknown): boolean {
  return value === null || value === undefined || value === '';
}

/** Compare two present values. Emptiness is handled by the caller. */
function compare(a: unknown, b: unknown): number {
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  if (typeof a === 'boolean' && typeof b === 'boolean') return Number(a) - Number(b);

  // Numeric-aware so "step 2" sorts before "step 10", and case-insensitive so
  // a capitalised label does not jump the queue.
  return String(a).localeCompare(String(b), undefined, {
    numeric: true,
    sensitivity: 'base',
  });
}

/**
 * Whether a row matches free-text search across the given fields.
 *
 * Case- and accent-insensitive, and matches anywhere in the value — somebody
 * searching a domain types the middle of it more often than the start.
 */
export function matchesText<T>(row: T, query: string, fields: Accessor<T>[]): boolean {
  const needle = normalise(query);
  if (!needle) return true;
  return fields.some((get) => normalise(String(get(row) ?? '')).includes(needle));
}

function normalise(value: string): string {
  return value
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .trim();
}

/** An "any of these" match. An empty selection means no constraint. */
export function matchesAny(value: unknown, selected: readonly string[]): boolean {
  if (!selected.length) return true;
  return selected.includes(String(value ?? ''));
}

/** The distinct values of a column, for building a filter's options. */
export function distinct<T>(rows: readonly T[], get: Accessor<T>): string[] {
  const seen = new Set<string>();
  for (const row of rows) {
    const value = get(row);
    if (value !== null && value !== undefined && value !== '') seen.add(String(value));
  }
  return [...seen].sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }),
  );
}
