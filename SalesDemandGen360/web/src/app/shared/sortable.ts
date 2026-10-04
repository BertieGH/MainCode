import { Directive, EventEmitter, Input, Output, computed, signal } from '@angular/core';

/**
 * Shared sortable-header infrastructure.
 *
 * One directive for every table in the application. Built here in Phase 2,
 * before there are eight tables wanting it — retrofitting a sort convention
 * across screens that each invented their own is far more work than agreeing
 * one now.
 *
 * The cycle is three-state: none → asc → desc → none. The third state matters
 * because "unsorted" is a real thing a user wants back, and without it the only
 * way to clear a sort is to reload the page.
 */

export type SortDirection = 'asc' | 'desc' | null;

export interface SortState {
  field: string | null;
  direction: SortDirection;
}

export const NO_SORT: SortState = { field: null, direction: null };

/** Advance one field through the cycle, given the current state. */
export function nextSort(current: SortState, field: string): SortState {
  if (current.field !== field) return { field, direction: 'asc' };
  if (current.direction === 'asc') return { field, direction: 'desc' };
  return NO_SORT;
}

/**
 * Serialise for the API. Returns an empty object when unsorted, so the
 * parameter is absent rather than sent as `sort=null` — which the backend
 * allowlist would reject.
 */
export function sortParams(state: SortState): Record<string, string> {
  if (!state.field || !state.direction) return {};
  return { sort: state.field, dir: state.direction };
}

@Directive({
  selector: '[appSortable]',
  standalone: true,
  host: {
    '[class.sortable]': 'true',
    '[class.sort-asc]': 'isAsc()',
    '[class.sort-desc]': 'isDesc()',
    '[attr.aria-sort]': 'ariaSort()',
    '[attr.role]': '"columnheader"',
    '[attr.tabindex]': '0',
    '(click)': 'toggle()',
    '(keydown.enter)': 'toggle()',
    '(keydown.space)': 'toggle(); $event.preventDefault()',
  },
})
export class SortableDirective {
  /** The field name sent to the API. Must be on that endpoint's allowlist. */
  @Input({ required: true, alias: 'appSortable' }) field!: string;

  @Input() set state(value: SortState) {
    this._state.set(value);
  }

  @Output() sortChange = new EventEmitter<SortState>();

  private _state = signal<SortState>(NO_SORT);

  isAsc = computed(() => this._state().field === this.field && this._state().direction === 'asc');
  isDesc = computed(() => this._state().field === this.field && this._state().direction === 'desc');

  /** Screen readers announce the sort state; the arrow glyph alone does not. */
  ariaSort = computed(() =>
    this.isAsc() ? 'ascending' : this.isDesc() ? 'descending' : 'none',
  );

  toggle(): void {
    const next = nextSort(this._state(), this.field);
    this._state.set(next);
    this.sortChange.emit(next);
  }
}
