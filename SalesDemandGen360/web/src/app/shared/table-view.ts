/**
 * A saved table view: which columns are shown, in what order, how wide.
 *
 * Every table in this app has the same problem from opposite ends. The account
 * list shows nine columns and a rep wants three; the contacts table has twenty
 * fields worth showing and no screen wide enough for them. Neither is solved by
 * choosing a fixed set — what is worth seeing depends on the stage somebody is
 * working at, and it changes hour to hour.
 *
 * So the choice belongs to the person and has to survive a reload. It lives in
 * `localStorage` keyed per table: this is a preference about *this browser*,
 * not a fact about the data, and sending it to the server would make one
 * person's layout everybody's.
 *
 * Stored, never assumed: a view records what somebody turned off *and* what
 * they turned on, so a column added to the code later appears for everybody
 * rather than staying invisible, and a column removed from the code disappears
 * without corrupting the rest. Both matter because this ships alongside a
 * schema that is still moving.
 */

/** One column a table can offer. */
export interface ColumnDef {
  key: string;
  label: string;
  /** Shown when the user has never chosen. Keeps a first visit legible. */
  defaultVisible?: boolean;
  /** Starting width in px. Absent means the browser decides. */
  width?: number;
  /** `text` filters by substring, `enum` by exact value from what is present. */
  filter?: 'text' | 'enum' | 'none';
  /** Read a row's value for filtering and sorting. */
  value?: (row: any) => unknown;
  /** Right-align and use the mono face — counts, scores, dates. */
  numeric?: boolean;
  /** Heading in the column dropdown. Columns sharing one must be adjacent —
   *  twenty ungrouped entries are a list nobody scans. */
  group?: string;
}

export interface SavedView {
  /**
   * Columns the user turned **off**, and columns they turned **on**.
   *
   * Both, not one. Storing only exclusions cannot express "show me a column
   * that is hidden by default", which is most of a twenty-field contacts
   * table. Storing only inclusions means a column added to the code later
   * stays invisible until every person goes looking for it.
   *
   * A key in neither list falls back to the definition's `defaultVisible`, so
   * new columns behave sensibly for everybody and explicit choices survive.
   */
  hidden: string[];
  shown: string[];
  widths: Record<string, number>;
  /** Column order, by key. Keys no longer defined are ignored on load. */
  order: string[];
}

const EMPTY: SavedView = { hidden: [], shown: [], widths: {}, order: [] };

function storageKey(table: string): string {
  return `sdg360.view.${table}`;
}

/**
 * Load a saved view, or an empty one.
 *
 * Every read is guarded: `localStorage` throws in a private window and in the
 * thumbnail capture some browsers run, and a layout preference is never worth
 * breaking a screen over.
 */
export function loadView(table: string): SavedView {
  try {
    const raw = localStorage.getItem(storageKey(table));
    if (!raw) return { ...EMPTY };
    const parsed = JSON.parse(raw) as Partial<SavedView>;
    return {
      hidden: Array.isArray(parsed.hidden) ? parsed.hidden.filter(isKey) : [],
      shown: Array.isArray(parsed.shown) ? parsed.shown.filter(isKey) : [],
      widths: isRecord(parsed.widths) ? numericOnly(parsed.widths) : {},
      order: Array.isArray(parsed.order) ? parsed.order.filter(isKey) : [],
    };
  } catch {
    return { ...EMPTY };
  }
}

export function saveView(table: string, view: SavedView): void {
  try {
    localStorage.setItem(storageKey(table), JSON.stringify(view));
  } catch {
    // A view that cannot be saved is a view that resets on reload. Worth
    // nothing, worth breaking nothing.
  }
}

export function clearView(table: string): void {
  try {
    localStorage.removeItem(storageKey(table));
  } catch {
    /* see saveView */
  }
}

function isKey(v: unknown): v is string {
  return typeof v === 'string' && v.length > 0;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

function numericOnly(v: Record<string, unknown>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [k, value] of Object.entries(v)) {
    // Clamped rather than trusted: a stored 4px column is invisible and
    // unrecoverable by dragging, which turns a saved view into a dead table.
    if (typeof value === 'number' && Number.isFinite(value)) {
      out[k] = Math.min(900, Math.max(60, Math.round(value)));
    }
  }
  return out;
}

/**
 * The columns to render, in order, given the definitions and a saved view.
 *
 * A definition the view never mentions is shown when `defaultVisible` is not
 * `false` — so adding a column to the code makes it appear for everybody
 * rather than staying invisible until each person goes looking.
 */
export function visibleColumns(defs: ColumnDef[], view: SavedView): ColumnDef[] {
  const hidden = new Set(view.hidden);
  const shown = new Set(view.shown);
  const visible = defs.filter((d) =>
    shown.has(d.key) ? true : hidden.has(d.key) ? false : d.defaultVisible !== false,
  );
  if (!view.order.length) return visible;

  const rank = new Map(view.order.map((key, i) => [key, i]));
  return [...visible].sort(
    (a, b) => (rank.get(a.key) ?? Number.MAX_SAFE_INTEGER) - (rank.get(b.key) ?? Number.MAX_SAFE_INTEGER),
  );
}

/** Every distinct value present in a column, for an enum filter's options. */
export function distinctValues(rows: unknown[], col: ColumnDef): string[] {
  const read = col.value ?? ((r: any) => r?.[col.key]);
  const seen = new Set<string>();
  for (const row of rows) {
    const v = read(row);
    if (v === null || v === undefined || v === '') continue;
    seen.add(String(v));
  }
  return [...seen].sort();
}

/**
 * Does a row pass every active filter?
 *
 * `text` matches a case-insensitive substring; `enum` matches exactly. A blank
 * filter is not a filter — an empty box must never hide rows.
 */
export function passesFilters(
  row: unknown,
  defs: ColumnDef[],
  filters: Record<string, string>,
): boolean {
  for (const col of defs) {
    const raw = (filters[col.key] ?? '').trim();
    if (!raw) continue;
    const read = col.value ?? ((r: any) => r?.[col.key]);
    const value = read(row);
    const text = value === null || value === undefined ? '' : String(value);
    if (col.filter === 'enum') {
      if (text !== raw) return false;
    } else if (!text.toLowerCase().includes(raw.toLowerCase())) {
      return false;
    }
  }
  return true;
}


/** Turn a column on or off, leaving the other choices alone. */
export function toggleColumn(view: SavedView, key: string, visible: boolean): SavedView {
  return {
    ...view,
    hidden: visible ? view.hidden.filter((k) => k !== key) : [...new Set([...view.hidden, key])],
    shown: visible ? [...new Set([...view.shown, key])] : view.shown.filter((k) => k !== key),
  };
}


/**
 * One action a row can take, and what it needs in order to take it.
 *
 * `can` is written once and read three times: to enable a row's menu item, to
 * count how many of a selection a bulk action covers, and to say what the
 * report skipped. Expressed as three separate `disabled` checks they drift,
 * and the report eventually disagrees with the button.
 */
export interface RowAction {
  key: string;
  label: string;
  /** True when this row can take it. Omitted means always. */
  can?: (row: any) => boolean;
  /** Why a row cannot — shown greyed beside the label, and in the report. */
  why?: string;
  /** Offered on the row menu. */
  row?: boolean;
  /** Offered on the bulk bar when rows are selected. */
  bulk?: boolean;
  /** Rendered in the critical colour. */
  danger?: boolean;
}

/** How a bulk action stands against the current selection. */
export interface ActionTally {
  action: RowAction;
  eligible: number;
  blocked: number;
}

/**
 * Split a selection by whether an action can run on it.
 *
 * The point of returning both halves: a bulk action runs on what it can and
 * *reports* the rest. Disabling a button because one row of twenty is
 * ineligible makes somebody deselect rows to hunt for the offender — work this
 * count exists to do for them.
 */
export function tally(action: RowAction, selected: unknown[]): ActionTally {
  const can = action.can ?? (() => true);
  const eligible = selected.filter((r) => can(r)).length;
  return { action, eligible, blocked: selected.length - eligible };
}

/**
 * Does a row match a free-text search across the columns on screen?
 *
 * Visible columns only. Matching a hidden one hides rows for a reason nothing
 * on screen explains.
 */
export function matchesSearch(
  row: unknown,
  cols: ColumnDef[],
  query: string,
): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return cols
    .map((c) => (c.value ? c.value(row) : (row as any)?.[c.key]))
    .filter((v) => v !== null && v !== undefined)
    .join(' ')
    .toLowerCase()
    .includes(q);
}
