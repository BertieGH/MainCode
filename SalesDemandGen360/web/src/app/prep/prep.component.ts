import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { PrepIndex, PrepRow, PrepService, ageLabel } from '../core/prep.service';
import { DataTableComponent } from '../shared/data-table.component';
import { ColumnDef } from '../shared/table-view';
import { NO_SORT, SortState } from '../shared/sortable';
import { sortRows } from '../shared/client-sort';
import { apiError } from '../shared/api-error';

/**
 * Sales Prep index — search any contact, plus a queue of those with a reason.
 *
 * Its own menu item rather than a tab on the account, because prep is on
 * demand and one contact at a time: the only part of the system with no batch
 * mode.
 *
 * **The queue is a convenience, not a gate.** A rep who wants to prepare
 * before there is a calendar invite should not be blocked by the data model, so
 * search covers every contact and the queue is additive. When the queue is
 * empty for a structural reason the screen says which — "no event can arrive
 * yet" is a build state, "nobody has replied" is a sales fact, and showing one
 * as the other would have a rep waiting for a list that cannot fill.
 */
@Component({
  selector: 'app-prep',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, DataTableComponent],
  template: `
    <div class="head">
      <div>
        <h2>Sales Prep</h2>
        <p class="sub">
          Prepare for a call or a meeting, one contact at a time. Search anyone —
          a meeting is not required.
        </p>
      </div>
    </div>

    <div class="searchbar">
      <input
        class="field"
        placeholder="Name, title, or company"
        [(ngModel)]="query"
        (keyup.enter)="search()" />
      <button class="btn" (click)="search()" [class.busy]="loading()"
              [disabled]="loading()">{{ loading() ? 'Searching…' : 'Search' }}</button>
      <button class="btn" (click)="query = ''; search()" *ngIf="query">Clear</button>
    </div>

    <p class="err" *ngIf="error()">{{ error() }}</p>

    <section *ngIf="data() as index">
      <div class="block">
        <div class="seclabel">Prep queue · a meeting booked, or a reply asking for a call</div>

        <div class="notice" *ngIf="index.queue_blocked">
          <strong>The queue is empty, and cannot fill yet.</strong>
          <p>{{ index.queue_blocked }}</p>
        </div>

        <app-data-table
          *ngIf="!index.queue_blocked"
          table="prep-queue"
          noun="queued contacts"
          emptyText="Nobody has a reason to prep right now."
          [columns]="columns"
          [data]="index.queue"
          [sort]="queueSort()"
          (sortChange)="queueSort.set($event)"
          (open)="open($event)"
          [cell]="prepCell">
        </app-data-table>
      </div>

      <div class="block">
        <div class="seclabel">
          {{ query ? 'Search results' : 'All contacts' }} · {{ index.total }}
        </div>
        <app-data-table
          table="prep-results"
          noun="contacts"
          emptyText="No contact matches that."
          [columns]="columns"
          [data]="sorted()"
          [sort]="sort()"
          (sortChange)="sort.set($event)"
          (open)="open($event)"
          [cell]="prepCell">
        </app-data-table>
      </div>
    </section>

    <ng-template #prepCell let-row let-column="column" let-value="value">
      <ng-container [ngSwitch]="column.key">
        <ng-container *ngSwitchCase="'contact_name'">
          <a [routerLink]="['/prep', row.contact_id]" class="link">{{ row.contact_name }}</a>
          <div class="row-sub" *ngIf="row.title">{{ row.title }}</div>
          <div class="row-sub danger" *ngIf="row.do_not_contact">do not contact</div>
        </ng-container>

        <ng-container *ngSwitchCase="'account_name'">
          <a [routerLink]="['/accounts', row.account_id]" class="link">{{ row.account_name }}</a>
        </ng-container>

        <ng-container *ngSwitchCase="'persona_role'">
          <span class="chip" *ngIf="row.persona_role">{{ row.persona_role }}</span>
          <span class="muted" *ngIf="!row.persona_role">—</span>
        </ng-container>

        <ng-container *ngSwitchCase="'why_now'">
          <span [class.muted]="row.why_now_kind === 'none'">{{ row.why_now }}</span>
          <div class="row-sub" [ngSwitch]="row.why_now_kind">
            <span *ngSwitchCase="'signal'">live signal</span>
            <span *ngSwitchCase="'thread'">from the strategy thread</span>
            <span *ngSwitchCase="'no_trigger'">approached without a live trigger</span>
            <span *ngSwitchCase="'none'">nothing has changed that we can see</span>
          </div>
        </ng-container>

        <ng-container *ngSwitchCase="'research_days'">
          <span class="badge" [ngClass]="researchTone(row)">{{ age(row.research_days) }}</span>
        </ng-container>

        <ng-container *ngSwitchCase="'engagement'">
          <span class="badge badge-accent" *ngIf="row.engagement">{{ row.engagement }}</span>
          <span class="muted" *ngIf="!row.engagement">nothing sent</span>
        </ng-container>

        <ng-container *ngSwitchDefault>{{ value }}</ng-container>
      </ng-container>
    </ng-template>
  `,
  styles: [
    `
      .head { margin-bottom: 20px; }
      .head h2 { font-size: 1.15rem; margin-bottom: 4px; }
      .sub { color: var(--muted); font-size: 0.85rem; margin: 0; max-width: 70ch; }
      .searchbar { display: flex; gap: 8px; align-items: center; margin-bottom: 24px; }
      .searchbar .field { max-width: 420px; }
      .block { margin-bottom: 30px; }
      .notice { border: 1px dashed var(--border-strong); border-radius: 12px;
                padding: 18px 20px; color: var(--muted); }
      .notice strong { color: var(--text); display: block; margin-bottom: 5px; }
      .notice p { margin: 0; font-size: 0.83rem; max-width: 80ch; }
      .link { color: var(--accent); text-decoration: none; font-weight: 500; }
      .link:hover { text-decoration: underline; }
      .danger { color: var(--critical); }
      .err { color: var(--critical); }
      td { white-space: normal; }
    `,
  ],
})
export class PrepComponent implements OnInit {
  private api = inject(PrepService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);

  query = '';
  data = signal<PrepIndex | null>(null);
  loading = signal(true);
  error = signal<string | null>(null);

  sort = signal<SortState>(NO_SORT);
  queueSort = signal<SortState>(NO_SORT);

  readonly age = ageLabel;

  /**
   * "Why now" is the column that earns the screen: it says what changed, not
   * that something did. Research age sits beside it because the two are read
   * together — a reason to call is worth less if the picture behind it is old.
   */
  columns: ColumnDef[] = [
    { key: 'contact_name', label: 'Contact', filter: 'text', value: (r) => r.contact_name },
    { key: 'persona_role', label: 'Persona', filter: 'enum', value: (r) => r.persona_role ?? '' },
    { key: 'account_name', label: 'Company', filter: 'text', value: (r) => r.account_name },
    { key: 'why_now', label: 'Why now', filter: 'text', value: (r) => r.why_now },
    {
      key: 'research_days',
      label: 'Research age',
      numeric: true,
      value: (r) => (r.research_days === null ? Number.MAX_SAFE_INTEGER : r.research_days),
    },
    { key: 'engagement', label: 'Engagement', filter: 'enum', value: (r) => r.engagement ?? '' },
  ];

  /**
   * Sorting reads the same values the columns filter by, so a column cannot
   * sort by one thing and filter by another.
   *
   * Never-looked sorts as the worst rather than the best: ascending by a null
   * read as 0 would put the least-known accounts at the top looking freshest.
   */
  private accessors: Record<string, (row: PrepRow) => unknown> = {
    contact_name: (r) => r.contact_name,
    persona_role: (r) => r.persona_role ?? '',
    account_name: (r) => r.account_name,
    why_now: (r) => r.why_now,
    research_days: (r) =>
      r.research_days === null ? Number.MAX_SAFE_INTEGER : r.research_days,
    engagement: (r) => r.engagement ?? '',
  };

  sorted = computed(() => sortRows(this.data()?.results ?? [], this.sort(), this.accessors));

  ngOnInit(): void {
    // Arriving from an account screen carries the company name, so the rep
    // lands on that company's people rather than on all 124 contacts and a
    // search box.
    this.query = this.route.snapshot.queryParamMap.get('q') ?? '';
    this.search();
  }

  search(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.index(this.query).subscribe({
      next: (index) => {
        this.data.set(index);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(apiError(err, 'Could not load contacts.'));
        this.loading.set(false);
      },
    });
  }

  open(row: unknown): void {
    this.router.navigate(['/prep', (row as PrepRow).contact_id]);
  }

  researchTone(row: PrepRow): string {
    if (row.research_days === null) return 'badge-critical';
    if (row.research_days <= 7) return 'badge-good';
    return row.research_days <= 30 ? 'badge-warn' : 'badge-critical';
  }
}
