import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnInit, Output, signal } from '@angular/core';

import { IconComponent } from './icon.component';

/**
 * The filter accordion every list screen sits under.
 *
 * **Collapsed by default**, and that is the point. A filter panel is read once
 * and then occupies the top of the screen forever — on a laptop that is three
 * or four rows of the list somebody actually came to look at. Expanded-first
 * costs everyone height to serve the minority of visits that filter.
 *
 * Two things stop the collapse from hiding state, which is the usual failure
 * of this pattern:
 *
 * * the header carries a **count of active filters** and a one-line summary of
 *   what they are, so a collapsed panel never silently hides why the list is
 *   short — the single most confusing thing a filter can do;
 * * **Clear** is on the header, reachable without expanding, because the
 *   moment you notice a filter is on is the moment you want it gone.
 *
 * The open/closed choice is remembered per screen. Somebody who filters the
 * account list constantly and never filters queues should not have to keep
 * re-opening one and re-closing the other.
 */
@Component({
  selector: 'app-filter-panel',
  standalone: true,
  imports: [CommonModule, IconComponent],
  template: `
    <div class="panel" [class.open]="open()">
      <div class="bar">
        <button type="button" class="toggle" (click)="toggle()"
                [attr.aria-expanded]="open()" [attr.aria-controls]="bodyId">
          <span class="chev" [class.down]="open()">›</span>
          <strong>Filters</strong>
          <span class="badge badge-accent" *ngIf="activeCount">{{ activeCount }}</span>
          <span class="row-sub none" *ngIf="!activeCount">none</span>
        </button>

        <!-- The summary is what makes collapsing safe: a short list with no
             visible reason is the failure this pattern usually creates. -->
        <span class="row-sub summary" *ngIf="!open() && summary">{{ summary }}</span>

        <span class="row-sub count" *ngIf="showing !== null">
          {{ showing }}<span *ngIf="total !== null && total !== showing"> of {{ total }}</span>
          {{ noun }}
        </span>

        <button type="button" class="btn clear" *ngIf="activeCount" (click)="cleared.emit()">
          Clear
        </button>
      </div>

      <div class="body" [id]="bodyId" *ngIf="open()">
        <ng-content />
      </div>
    </div>
  `,
  styles: [
    `
      .panel { border: 1px solid var(--line); border-radius: 8px; margin-bottom: 14px; }
      .bar { display: flex; align-items: center; gap: 12px; padding: 8px 12px; flex-wrap: wrap; }
      .toggle { display: flex; align-items: center; gap: 8px; background: none;
                border: 0; padding: 0; font: inherit; color: inherit; cursor: pointer; }
      .toggle strong { font-size: .86rem; }
      .chev { display: inline-block; transition: transform .12s ease; opacity: .6; }
      .chev.down { transform: rotate(90deg); }
      .none { opacity: .6; }
      .summary { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis;
                 white-space: nowrap; opacity: .8; }
      .count { margin-left: auto; opacity: .7; white-space: nowrap; }
      .clear { padding: 2px 10px; font-size: .74rem; }
      .body { padding: 4px 12px 14px; border-top: 1px solid var(--line);
              display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-end; }
    `,
  ],
})
export class FilterPanelComponent implements OnInit {
  /** Distinguishes this screen's remembered open/closed state. */
  @Input({ required: true }) key!: string;
  /** How many filters are set. Shown collapsed, so nothing hides silently. */
  @Input() activeCount = 0;
  /** One line naming the active filters. */
  @Input() summary = '';
  /** Rows after filtering, and before — for the "12 of 40 accounts" line. */
  @Input() showing: number | null = null;
  @Input() total: number | null = null;
  @Input() noun = 'rows';

  @Output() cleared = new EventEmitter<void>();

  readonly bodyId = `filters-${Math.random().toString(36).slice(2, 8)}`;

  open = signal(false);

  ngOnInit(): void {
    this.open.set(this.remembered());
  }

  toggle(): void {
    const next = !this.open();
    this.open.set(next);
    try {
      localStorage.setItem(this.storageKey(), next ? '1' : '0');
    } catch {
      // Private browsing, or storage disabled. The panel still works for this
      // session; forgetting the preference is a far smaller problem than
      // throwing on a click.
    }
  }

  private remembered(): boolean {
    try {
      return localStorage.getItem(this.storageKey()) === '1';
    } catch {
      return false;
    }
  }

  private storageKey(): string {
    return `sdg360.filters.${this.key}`;
  }
}
