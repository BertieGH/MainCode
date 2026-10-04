import { CommonModule } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';

import { ActivityEntry, ActivityService } from './activity.service';

/**
 * The Activity accordion at the top of every page.
 *
 * Collapsed: unseen errors, how many things happened today, and the latest
 * message. Open: every outcome, newest first, scrolling inside its own box so
 * the page underneath does not move — with each run's per-account results
 * folded under the message that reported it.
 */
@Component({
  selector: 'app-activity-bar',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="act" [class.open]="svc.open()" aria-label="Activity">
      <button type="button" class="head" (click)="svc.toggle()" [attr.aria-expanded]="svc.open()">
        <span class="chev" aria-hidden="true">›</span>
        <strong>Activity</strong>
        <span class="pill err" *ngIf="svc.unseenErrors() as n">{{ n }} error{{ n === 1 ? '' : 's' }}</span>
        <span class="pill" *ngIf="svc.todayCount() as n">{{ n }} today</span>
        <span class="latest" *ngIf="svc.entries()[0] as e; else none">{{ time(e.at) }} · {{ e.text }}</span>
        <ng-template #none><span class="latest">Results of what you run appear here.</span></ng-template>
      </button>

      <div class="body" *ngIf="svc.open()">
        <div class="tools">
          <button type="button" class="mini" [class.on]="filter() === 'all'" (click)="filter.set('all')">
            All {{ svc.entries().length }}
          </button>
          <button type="button" class="mini" [class.on]="filter() === 'problems'" (click)="filter.set('problems')">
            Errors and warnings {{ problems() }}
          </button>
          <span class="spacer"></span>
          <button type="button" class="mini" (click)="svc.clear()" [disabled]="!svc.entries().length">Clear</button>
        </div>
        <div class="list" role="log" aria-live="polite">
          <p class="empty" *ngIf="!shown().length">
            {{ filter() === 'problems' ? 'No errors or warnings.' : 'Nothing has run yet.' }}
          </p>
          <div *ngFor="let e of shown(); trackBy: byId" class="entry"
               [ngClass]="[e.kind, svc.highlight() === e.id ? 'hl' : '']" [attr.id]="'act-' + e.id">
            <span class="when">{{ time(e.at) }}</span>
            <span class="mark" aria-hidden="true"></span>
            <div class="what">
              <div>
                <strong>{{ e.text }}</strong>
                <span class="sub" *ngIf="e.where"> · {{ e.where }}</span>
                <span class="sub" *ngIf="e.run">
                  · {{ e.run.completed }} of {{ e.run.total }}{{ e.run.cancelled ? ' (stopped)' : '' }} · {{ e.run.elapsed }}
                </span>
              </div>
              <div class="sub" *ngIf="e.detail">{{ e.detail }}</div>
              <details *ngIf="e.items.length">
                <summary class="sub">
                  {{ e.items.length }} {{ e.items.length === 1 ? 'account' : 'accounts' }}<span
                    *ngIf="failed(e) as f"> · {{ f }} with problems</span>
                </summary>
                <div *ngFor="let i of e.items" class="item" [ngClass]="i.kind">
                  <span class="mark" aria-hidden="true"></span>{{ i.name }} — {{ i.text }}
                </div>
              </details>
            </div>
          </div>
        </div>
      </div>
    </section>
  `,
  styles: [
    `
      .act { border: 1px solid var(--line); border-radius: 8px; background: var(--card, #fff);
             margin: 0 0 16px; font-size: .82rem; }
      .head { display: flex; align-items: center; gap: 10px; width: 100%; border: none; background: none;
              font: inherit; color: inherit; padding: 7px 12px; cursor: pointer; text-align: left; }
      .chev { transition: transform .15s; color: var(--muted); }
      .open .chev { transform: rotate(90deg); }
      .pill { border-radius: 10px; padding: 0 8px; font-size: .72rem; background: var(--line); }
      .pill.err { background: var(--critical-soft, #f7dcd8); color: var(--critical, #b34a3f); }
      .latest { flex: 1; min-width: 0; color: var(--muted); white-space: nowrap; overflow: hidden;
                text-overflow: ellipsis; }
      .tools { display: flex; gap: 6px; padding: 6px 12px; border-top: 1px solid var(--line); }
      .spacer { flex: 1; }
      .mini.on { font-weight: 600; }
      .list { max-height: 320px; overflow-y: auto; border-top: 1px solid var(--line); }
      .empty { color: var(--muted); padding: 10px 12px; margin: 0; }
      .entry { display: grid; grid-template-columns: 74px 10px minmax(0, 1fr); gap: 8px;
               padding: 7px 12px; border-bottom: 1px solid var(--line); }
      .entry.hl { background: var(--accent-soft, #e3f0ee); }
      .when, .sub { color: var(--muted); }
      .mark { width: 8px; height: 8px; border-radius: 50%; margin-top: 5px; background: var(--muted); }
      .success > .mark, .item.success .mark { background: var(--good, #2f7a54); }
      .info > .mark { background: var(--accent, #1f6f64); }
      .warning > .mark, .item.warning .mark { background: var(--warn, #b8801f); }
      .error > .mark, .item.error .mark { background: var(--critical, #b34a3f); }
      .what { overflow-wrap: anywhere; }
      details { margin-top: 3px; }
      .item { display: flex; gap: 6px; align-items: baseline; padding: 1px 0 1px 8px; }
      .item .mark { flex: none; margin-top: 0; }
    `,
  ],
})
export class ActivityBarComponent {
  readonly svc = inject(ActivityService);
  readonly filter = signal<'all' | 'problems'>('all');

  readonly problems = computed(
    () => this.svc.entries().filter((e) => e.kind === 'error' || e.kind === 'warning').length,
  );
  readonly shown = computed(() =>
    this.filter() === 'all'
      ? this.svc.entries()
      : this.svc.entries().filter((e) => e.kind === 'error' || e.kind === 'warning'),
  );

  byId = (_: number, e: ActivityEntry) => e.id;

  failed(e: ActivityEntry): number {
    return e.items.filter((i) => i.kind !== 'success').length;
  }

  /** "10:42" today; "Sep 13, 10:42" before. */
  time(at: number): string {
    const d = new Date(at);
    const today = new Date().toDateString() === d.toDateString();
    const hm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return today ? hm : `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })}, ${hm}`;
  }
}
