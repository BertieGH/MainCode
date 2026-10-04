/**
 * A saved table view.
 *
 * The failures worth testing are all quiet ones. A layout that forgets a
 * choice, a column that can never be turned back on, a stored width of 4px
 * that leaves a column invisible and un-draggable — none of them throw, and
 * all of them make a table useless until somebody clears their browser
 * storage.
 */

import {
  ColumnDef, SavedView, clearView, distinctValues, loadView, passesFilters,
  saveView, toggleColumn, visibleColumns,
} from './table-view';

const cols: ColumnDef[] = [
  { key: 'name', label: 'Name' },
  { key: 'title', label: 'Title' },
  { key: 'email', label: 'Email' },
  // Most of a twenty-field contacts table looks like this.
  { key: 'phone_provider', label: 'Phone provider', defaultVisible: false },
];

const view = (over: Partial<SavedView> = {}): SavedView => ({
  hidden: [], shown: [], widths: {}, order: [], ...over,
});

describe('visibleColumns', () => {
  it('shows everything a first visit should see', () => {
    expect(visibleColumns(cols, view()).map((c) => c.key)).toEqual([
      'name', 'title', 'email',
    ]);
  });

  it('can turn on a column that is hidden by default', () => {
    // The case a hidden-only model cannot express. Most contact fields
    // default to off, so without this they could never be switched on.
    const v = toggleColumn(view(), 'phone_provider', true);
    expect(visibleColumns(cols, v).map((c) => c.key)).toContain('phone_provider');
  });

  it('can turn off a column that is shown by default', () => {
    const v = toggleColumn(view(), 'title', false);
    expect(visibleColumns(cols, v).map((c) => c.key)).not.toContain('title');
  });

  it('reverses cleanly, leaving no stale record behind', () => {
    let v = toggleColumn(view(), 'title', false);
    v = toggleColumn(v, 'title', true);
    expect(visibleColumns(cols, v).map((c) => c.key)).toContain('title');
    expect(v.hidden).not.toContain('title');
  });

  it('shows a column added to the code after the view was saved', () => {
    // A saved view predating a new column must not hide it forever — nobody
    // would think to go looking for a column they have never seen.
    const saved = toggleColumn(view(), 'title', false);
    const withNew = [...cols, { key: 'buying_role', label: 'Buying role' }];
    expect(visibleColumns(withNew, saved).map((c) => c.key)).toContain('buying_role');
  });

  it('ignores a saved key whose column no longer exists', () => {
    const stale = view({ hidden: ['gone'], order: ['gone', 'email', 'name'] });
    expect(() => visibleColumns(cols, stale)).not.toThrow();
    expect(visibleColumns(cols, stale).map((c) => c.key)).toEqual([
      'email', 'name', 'title',
    ]);
  });

  it('honours a saved order', () => {
    const ordered = view({ order: ['email', 'name', 'title'] });
    expect(visibleColumns(cols, ordered).map((c) => c.key)).toEqual([
      'email', 'name', 'title',
    ]);
  });
});

describe('persistence', () => {
  afterEach(() => clearView('t'));

  it('round-trips a view', () => {
    saveView('t', view({ hidden: ['title'], widths: { name: 220 } }));
    const back = loadView('t');
    expect(back.hidden).toEqual(['title']);
    expect(back.widths['name']).toBe(220);
  });

  it('clamps a width that would make a column unusable', () => {
    // A 4px column cannot be seen or grabbed, so the layout is stuck until
    // storage is cleared by hand.
    saveView('t', view({ widths: { name: 4, title: 5000 } }));
    const back = loadView('t');
    expect(back.widths['name']).toBeGreaterThanOrEqual(60);
    expect(back.widths['title']).toBeLessThanOrEqual(900);
  });

  it('survives corrupt storage rather than breaking the table', () => {
    localStorage.setItem('sdg360.view.t', '{not json');
    expect(loadView('t')).toEqual(view());
  });

  it('ignores junk of the wrong type inside a valid document', () => {
    localStorage.setItem(
      'sdg360.view.t',
      JSON.stringify({ hidden: 'title', widths: { name: 'wide' }, order: 42 }),
    );
    const back = loadView('t');
    expect(back.hidden).toEqual([]);
    expect(back.widths).toEqual({});
    expect(back.order).toEqual([]);
  });

  it('returns an empty view for a table nobody has customised', () => {
    expect(loadView('never-seen')).toEqual(view());
  });
});

describe('filtering', () => {
  const rows = [
    { name: 'Dana', title: 'CTO', email_status: 'verified' },
    { name: 'Sam', title: 'VP Engineering', email_status: 'risky' },
    { name: 'Ali', title: null, email_status: 'verified' },
  ];
  const defs: ColumnDef[] = [
    { key: 'name', label: 'Name' },
    { key: 'title', label: 'Title' },
    { key: 'email_status', label: 'Status', filter: 'enum' },
  ];

  it('matches a substring, case-insensitively', () => {
    const kept = rows.filter((r) => passesFilters(r, defs, { title: 'cto' }));
    expect(kept.map((r) => r.name)).toEqual(['Dana']);
  });

  it('matches an enum exactly, so "verified" excludes "unverified"', () => {
    const kept = rows.filter((r) => passesFilters(r, defs, { email_status: 'verified' }));
    expect(kept.map((r) => r.name)).toEqual(['Dana', 'Ali']);
  });

  it('treats a blank filter as no filter', () => {
    // An empty box hiding rows is the bug people report as "the table broke".
    const kept = rows.filter((r) => passesFilters(r, defs, { title: '   ' }));
    expect(kept.length).toBe(3);
  });

  it('combines filters with AND', () => {
    const kept = rows.filter((r) =>
      passesFilters(r, defs, { title: 'e', email_status: 'risky' }),
    );
    expect(kept.map((r) => r.name)).toEqual(['Sam']);
  });

  it('excludes a row whose value is null when that column is filtered', () => {
    const kept = rows.filter((r) => passesFilters(r, defs, { title: 'c' }));
    expect(kept.map((r) => r.name)).toEqual(['Dana']);
  });

  it('offers only the values actually present as enum options', () => {
    expect(distinctValues(rows, defs[2])).toEqual(['risky', 'verified']);
    // Nulls are not an option somebody can usefully pick.
    expect(distinctValues(rows, defs[1])).toEqual(['CTO', 'VP Engineering']);
  });
});
