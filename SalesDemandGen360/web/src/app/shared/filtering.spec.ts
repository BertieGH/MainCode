import { ComponentFixture, TestBed } from '@angular/core/testing';

import { distinct, matchesAny, matchesText, sortRows } from './client-sort';
import { FilterPanelComponent } from './filter-panel.component';
import { NO_SORT } from './sortable';

interface Row {
  name: string;
  domain: string | null;
  score: number | null;
  status: string;
  locked: boolean;
}

const ROWS: Row[] = [
  { name: 'Zephyr Data', domain: 'zephyr.io', score: 40, status: 'draft', locked: false },
  { name: 'acme corp', domain: null, score: null, status: 'locked', locked: true },
  { name: 'Northwind', domain: 'northwind.example', score: 90, status: 'draft', locked: false },
  { name: 'Ötzi Labs', domain: 'otzi.dev', score: 7, status: 'locked', locked: true },
];

describe('client-side sorting', () => {
  const by = {
    name: (r: Row) => r.name,
    score: (r: Row) => r.score,
    locked: (r: Row) => r.locked,
  };

  it('leaves the rows alone when unsorted', () => {
    expect(sortRows(ROWS, NO_SORT, by).map((r) => r.name)).toEqual(ROWS.map((r) => r.name));
  });

  it('does not mutate the array it was given', () => {
    // The caller usually holds the unsorted rows in a signal; sorting in place
    // would make the "no sort" state unreachable, because the original order
    // would already be gone.
    const original = ROWS.map((r) => r.name);
    sortRows(ROWS, { field: 'name', direction: 'asc' }, by);
    expect(ROWS.map((r) => r.name)).toEqual(original);
  });

  it('sorts text case-insensitively', () => {
    const sorted = sortRows(ROWS, { field: 'name', direction: 'asc' }, by);
    // A capitalised label must not jump the queue.
    expect(sorted[0].name).toBe('acme corp');
  });

  it('sorts numbers as numbers', () => {
    const sorted = sortRows(ROWS, { field: 'score', direction: 'asc' }, by);
    expect(sorted.map((r) => r.score)).toEqual([7, 40, 90, null]);
  });

  it('keeps blanks last in both directions', () => {
    // Blanks first on descending fills the top of the screen with rows that
    // have nothing in the column being sorted — the opposite of what somebody
    // sorting by that column wants.
    const asc = sortRows(ROWS, { field: 'score', direction: 'asc' }, by);
    const desc = sortRows(ROWS, { field: 'score', direction: 'desc' }, by);
    expect(asc[asc.length - 1].score).toBeNull();
    expect(desc[desc.length - 1].score).toBeNull();
  });

  it('sorts booleans', () => {
    const sorted = sortRows(ROWS, { field: 'locked', direction: 'desc' }, by);
    expect(sorted[0].locked).toBe(true);
  });

  it('orders embedded numbers naturally', () => {
    const steps = [{ label: 'step 10' }, { label: 'step 2' }];
    const sorted = sortRows(steps, { field: 'label', direction: 'asc' }, {
      label: (r: { label: string }) => r.label,
    });
    // Lexical ordering would put "step 10" first.
    expect(sorted.map((r) => r.label)).toEqual(['step 2', 'step 10']);
  });

  it('ignores a field it has no accessor for rather than throwing', () => {
    expect(sortRows(ROWS, { field: 'nonsense', direction: 'asc' }, by).length).toBe(4);
  });
});

describe('client-side filtering', () => {
  it('matches anywhere in the value, not only the start', () => {
    // Somebody searching a domain types the middle of it more often than the
    // beginning.
    expect(matchesText(ROWS[2], 'wind', [(r) => r.name])).toBe(true);
  });

  it('ignores case and accents', () => {
    expect(matchesText(ROWS[3], 'otzi', [(r) => r.name])).toBe(true);
    expect(matchesText(ROWS[0], 'ZEPHYR', [(r) => r.name])).toBe(true);
  });

  it('searches every field it is given', () => {
    expect(matchesText(ROWS[0], 'zephyr.io', [(r) => r.name, (r) => r.domain ?? ''])).toBe(true);
  });

  it('treats an empty query as no constraint', () => {
    expect(matchesText(ROWS[0], '   ', [(r) => r.name])).toBe(true);
  });

  it('treats an empty selection as no constraint', () => {
    // Otherwise a filter nobody set would hide everything.
    expect(matchesAny('draft', [])).toBe(true);
    expect(matchesAny('draft', ['locked'])).toBe(false);
    expect(matchesAny('draft', ['draft', 'locked'])).toBe(true);
  });

  it('builds options from the values actually present', () => {
    expect(distinct(ROWS, (r) => r.status)).toEqual(['draft', 'locked']);
    // Blanks are not an option — "any" already covers them.
    expect(distinct(ROWS, (r) => r.domain)).not.toContain('');
  });
});

describe('FilterPanelComponent', () => {
  let fixture: ComponentFixture<FilterPanelComponent>;
  let cmp: FilterPanelComponent;

  beforeEach(async () => {
    localStorage.removeItem('sdg360.filters.test');
    await TestBed.configureTestingModule({ imports: [FilterPanelComponent] }).compileComponents();
    fixture = TestBed.createComponent(FilterPanelComponent);
    cmp = fixture.componentInstance;
    cmp.key = 'test';
    fixture.detectChanges();
  });

  it('starts collapsed so the list gets the height', () => {
    // Expanded-first costs every visit three or four rows of the list somebody
    // actually came to look at, to serve the minority that filter.
    expect(cmp.open()).toBe(false);
    expect(fixture.nativeElement.querySelector('.body')).toBeNull();
  });

  it('expands and collapses', () => {
    cmp.toggle();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.body')).toBeTruthy();
    cmp.toggle();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.body')).toBeNull();
  });

  it('remembers the choice per screen', () => {
    // Somebody who filters accounts constantly and never filters queues should
    // not keep re-opening one and re-closing the other.
    cmp.toggle();
    expect(localStorage.getItem('sdg360.filters.test')).toBe('1');
  });

  it('shows the active count while collapsed', () => {
    cmp.activeCount = 2;
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.bar').textContent).toContain('2');
  });

  it('names the active filters while collapsed', () => {
    // A short list with no visible reason is the failure this pattern usually
    // creates.
    cmp.activeCount = 1;
    cmp.summary = 'status draft';
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.summary').textContent).toContain('status draft');
  });

  it('offers Clear without expanding', () => {
    // The moment you notice a filter is on is the moment you want it gone.
    cmp.activeCount = 1;
    fixture.detectChanges();
    const clear: HTMLElement = fixture.nativeElement.querySelector('.clear');
    expect(clear).toBeTruthy();

    let cleared = false;
    cmp.cleared.subscribe(() => (cleared = true));
    clear.click();
    expect(cleared).toBe(true);
  });

  it('offers no Clear when nothing is filtered', () => {
    cmp.activeCount = 0;
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.clear')).toBeNull();
  });

  it('reports how much of the list is showing', () => {
    cmp.showing = 3;
    cmp.total = 12;
    cmp.noun = 'accounts';
    fixture.detectChanges();
    const text = fixture.nativeElement.querySelector('.count').textContent.replace(/\s+/g, ' ');
    expect(text).toContain('3 of 12 accounts');
  });

  it('does not say "of" when nothing is filtered out', () => {
    cmp.showing = 12;
    cmp.total = 12;
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.count').textContent).not.toContain(' of ');
  });
});
