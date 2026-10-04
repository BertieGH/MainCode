import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';

import { NO_SORT, SortState, SortableDirective, nextSort, sortParams } from './sortable';

/**
 * The three-state cycle is the kind of logic that breaks silently: a wrong
 * transition still produces a sorted table, just not the one that was asked
 * for. These pin every edge of it.
 */
describe('nextSort', () => {
  it('starts a new field ascending', () => {
    expect(nextSort(NO_SORT, 'name')).toEqual({ field: 'name', direction: 'asc' });
  });

  it('advances asc to desc on the same field', () => {
    expect(nextSort({ field: 'name', direction: 'asc' }, 'name')).toEqual({
      field: 'name',
      direction: 'desc',
    });
  });

  it('clears on the third click', () => {
    expect(nextSort({ field: 'name', direction: 'desc' }, 'name')).toEqual(NO_SORT);
  });

  it('completes a full cycle back to unsorted', () => {
    let s: SortState = NO_SORT;
    s = nextSort(s, 'size');
    s = nextSort(s, 'size');
    s = nextSort(s, 'size');
    expect(s).toEqual(NO_SORT);
  });

  it('switching field restarts at ascending rather than inheriting direction', () => {
    // Otherwise clicking a new column silently applies the previous column's
    // direction, and the arrow disagrees with the data.
    const from = { field: 'name', direction: 'desc' as const };
    expect(nextSort(from, 'size')).toEqual({ field: 'size', direction: 'asc' });
  });
});

describe('sortParams', () => {
  it('omits the parameter entirely when unsorted', () => {
    // Sending sort=null would be rejected by the backend allowlist as an
    // unknown field, turning "no sort" into a 422.
    expect(sortParams(NO_SORT)).toEqual({});
  });

  it('omits when a field is set but direction is not', () => {
    expect(sortParams({ field: 'name', direction: null })).toEqual({});
  });

  it('serialises a real sort', () => {
    expect(sortParams({ field: 'name', direction: 'desc' })).toEqual({
      sort: 'name',
      dir: 'desc',
    });
  });
});

@Component({
  standalone: true,
  imports: [SortableDirective],
  template: `
    <table>
      <thead>
        <tr>
          <th appSortable="name" [state]="state" (sortChange)="onSort($event)">Name</th>
          <th appSortable="size" [state]="state" (sortChange)="onSort($event)">Size</th>
        </tr>
      </thead>
    </table>
  `,
})
class HostComponent {
  state: SortState = NO_SORT;
  emitted: SortState[] = [];
  onSort(s: SortState) {
    this.emitted.push(s);
    this.state = s;
  }
}

describe('SortableDirective', () => {
  let fixture: ComponentFixture<HostComponent>;
  let host: HostComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [HostComponent] }).compileComponents();
    fixture = TestBed.createComponent(HostComponent);
    host = fixture.componentInstance;
    fixture.detectChanges();
  });

  function th(index: number): HTMLElement {
    return fixture.debugElement.queryAll(By.directive(SortableDirective))[index].nativeElement;
  }

  it('marks headers sortable', () => {
    expect(th(0).classList).toContain('sortable');
  });

  it('emits ascending on first click', () => {
    th(0).click();
    expect(host.emitted[0]).toEqual({ field: 'name', direction: 'asc' });
  });

  it('applies the direction class so the arrow matches the data', () => {
    th(0).click();
    fixture.detectChanges();
    expect(th(0).classList).toContain('sort-asc');

    th(0).click();
    fixture.detectChanges();
    expect(th(0).classList).toContain('sort-desc');
    expect(th(0).classList).not.toContain('sort-asc');
  });

  it('only the active column carries a direction class', () => {
    th(0).click();
    fixture.detectChanges();
    expect(th(1).classList).not.toContain('sort-asc');
    expect(th(1).classList).not.toContain('sort-desc');
  });

  it('announces the sort state to screen readers', () => {
    // The arrow glyph is invisible to assistive technology; aria-sort is not.
    expect(th(0).getAttribute('aria-sort')).toBe('none');
    th(0).click();
    fixture.detectChanges();
    expect(th(0).getAttribute('aria-sort')).toBe('ascending');
    th(0).click();
    fixture.detectChanges();
    expect(th(0).getAttribute('aria-sort')).toBe('descending');
  });

  it('is reachable and operable by keyboard', () => {
    expect(th(0).getAttribute('tabindex')).toBe('0');
    th(0).dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(host.emitted.at(-1)).toEqual({ field: 'name', direction: 'asc' });
  });
});
