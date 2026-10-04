import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { Account, AccountList, ListsService, asUnsortableField } from '../core/lists.service';
import { IconComponent } from '../shared/icon.component';
import { distinct, matchesAny, matchesText, sortRows } from '../shared/client-sort';
import { FilterPanelComponent } from '../shared/filter-panel.component';
import { NO_SORT, SortState, SortableDirective } from '../shared/sortable';
import { apiError } from '../shared/api-error';

import { catchError, firstValueFrom, forkJoin, map, of } from 'rxjs';
import { DataTableComponent } from '../shared/data-table.component';
import { ColumnDef, RowAction } from '../shared/table-view';

import { ConfirmService } from '../shared/confirm.service';
import { NotifyService } from '../shared/notify.service';

@Component({
  selector: 'app-lists',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, SortableDirective, IconComponent, FilterPanelComponent, DataTableComponent],
  template: `
    <div class="head">
      <div>
        <h2>Account Lists</h2>
        <p class="row-sub">
          Import sets. A list only grows by import or manual add — it never syncs outward,
          and everything downstream is a deliberate copy out of it.
        </p>
      </div>
      <button class="btn btn-primary" (click)="creating.set(!creating())">
        <app-icon name="plus" />New list
      </button>
    </div>

    <div class="card" *ngIf="creating()" style="margin-bottom:18px;max-width:520px;">
      <div style="display:flex;flex-direction:column;gap:12px;">
        <label style="display:flex;flex-direction:column;gap:6px;font-size:.84rem;">Label
          <input class="field" [(ngModel)]="draft.label" placeholder="Q3 DevOps ISVs - US">
        </label>
        <label style="display:flex;flex-direction:column;gap:6px;font-size:.84rem;">Description
          <input class="field" [(ngModel)]="draft.description" placeholder="Series A-C, 50-500 employees">
        </label>
        <div style="display:flex;gap:10px;align-items:center;">
          <button class="btn btn-primary" (click)="create()" [class.busy]="creatingBusy() === 'import'"
                  [disabled]="!draft.label || !!creatingBusy()">
            <app-icon *ngIf="creatingBusy() !== 'import'" name="check" [size]="13" />
            {{ creatingBusy() === 'import' ? 'Creating…' : 'Create and import' }}
          </button>
          <button class="btn" (click)="create(false)" [class.busy]="creatingBusy() === 'empty'"
                  [disabled]="!draft.label || !!creatingBusy()">
            {{ creatingBusy() === 'empty' ? 'Creating…' : 'Create empty' }}
          </button>
          <button class="btn" (click)="creating.set(false)">Cancel</button>
        </div>
        <span class="row-sub">
          A new list is empty. <strong>Create and import</strong> opens it with the CSV
          uploader ready; <strong>Create empty</strong> leaves it to fill in later.
        </span>
      </div>
    </div>


    <div class="card" *ngIf="error()" style="border-color:var(--critical);margin-bottom:18px;">
      <strong style="color:var(--critical);">{{ error() }}</strong>
    </div>

    <app-data-table
      table="lists"
      noun="lists"
      emptyText="No lists yet. Create one, then import a CSV into it."
      [columns]="columns"
      [data]="sortedLists()"
      [sort]="sort()"
      (sortChange)="onTableSort($event)"
      [selectable]="true"
      [rowActions]="actions"
      [busyKey]="deleting() ? 'delete' : null"
      busyText="Deleting…"
      [label]="listLabel"
      (open)="openList($event)"
      (bulk)="onBulk($event)"
      (rowAction)="onBulk({ action: $event.action, rows: [$event.row], skipped: [] })"
      [cell]="listCell">
    </app-data-table>
    <ng-template #listCell let-row let-column="column" let-value="value">
      <ng-container [ngSwitch]="column.key">
        <ng-container *ngSwitchCase="'label'">
          <a [routerLink]="['/lists', row.id]" class="link">{{ row.label }}</a>
          <div class="row-sub" *ngIf="row.description">{{ row.description }}</div>
        </ng-container>
        <ng-container *ngSwitchCase="'worked_for'">
          <!-- Absent is not blank: a list nobody has targeted cannot be
               enriched deliberately. -->
          <ng-container *ngIf="row.service_codes.length; else untargeted">
            <span class="chip" *ngFor="let c of row.service_codes">{{ c }}</span>
            <span class="chip icp" *ngFor="let n of row.icp_names">{{ n }}</span>
          </ng-container>
          <ng-template #untargeted><span class="pending">not set</span></ng-template>
        </ng-container>
        <ng-container *ngSwitchCase="'contacts'">
          <ng-container *ngIf="row.contact_count; else noContacts">
            {{ row.verified_count }}/{{ row.contact_count }}
            <span class="row-sub" *ngIf="row.verified_count === 0"> none verified</span>
          </ng-container>
          <ng-template #noContacts><span class="row-sub">—</span></ng-template>
        </ng-container>
        <span *ngSwitchCase="'source'" class="badge badge-neutral">{{ value }}</span>
        <ng-container *ngSwitchCase="'created_at'">
          {{ row.created_at | date: 'MMM d, y' }}
          <div class="row-sub">{{ row.created_by }}</div>
        </ng-container>
        <ng-container *ngSwitchDefault>{{ value }}</ng-container>
      </ng-container>
    </ng-template>

    <!-- Accounts on no list and in no campaign queue. Kept, not deleted: put
         one back on a list and its research and contacts come with it. -->
    <div class="card dormant">
      <div class="dormant-h">
        <button class="btn" (click)="toggleDormant()">
          {{ showDormant() ? 'Hide' : 'Show' }} dormant accounts
        </button>
        <span class="row-sub">
          On no list and in no campaign queue — kept with their research and contacts, hidden
          until a list takes them back.
        </span>
      </div>
      <ng-container *ngIf="showDormant()">
        <div class="dormant-bar">
          <input class="field" placeholder="Search name or domain" aria-label="Search dormant accounts"
                 [(ngModel)]="dormantQuery" (keyup.enter)="loadDormant()">
          <select class="field" aria-label="List to add to" [(ngModel)]="dormantTarget">
            <option value="">add to list…</option>
            <option *ngFor="let l of lists()" [value]="l.id">{{ l.label }}</option>
          </select>
          <button class="btn btn-primary" (click)="addDormant()"
                  [disabled]="!dormantTarget || !pickedDormant.size || addingDormant()">
            Add {{ pickedDormant.size || '' }} to list
          </button>
        </div>
        <p class="row-sub" *ngIf="!dormant().length">
          {{ loadingDormant() ? 'Loading…' : 'No dormant accounts.' }}
        </p>
        <div class="table-wrap" *ngIf="dormant().length">
          <table>
            <thead>
              <tr><th></th><th>Account</th><th>Domain</th><th>Dormant since</th><th>Why</th></tr>
            </thead>
            <tbody>
              <tr *ngFor="let a of dormant()">
                <td>
                  <input type="checkbox" [checked]="pickedDormant.has(a.id)" (change)="togglePick(a.id)"
                         [attr.aria-label]="'Select ' + a.name">
                </td>
                <td><a [routerLink]="['/accounts', a.id]" class="link">{{ a.name }}</a></td>
                <td class="mono">{{ a.domain || '—' }}</td>
                <td>{{ a.dormant_at | date: 'MMM d, y' }}</td>
                <td class="row-sub">{{ a.dormant_reason || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </ng-container>
    </div>
  `,
  styles: [
    `
      td { white-space: normal; }
      .chip { display:inline-block; padding:1px 7px; margin:1px 3px 1px 0;
              border:1px solid var(--line); border-radius:10px; font-size:.72rem; }
      .chip.icp { border-style:dashed; }
      .pending { color: var(--critical); font-size:.75rem; }
      .f { display: flex; flex-direction: column; gap: 4px; font-size: .78rem; }
      .f .field { min-width: 170px; }
      .f .narrow { min-width: 90px; }
      .f.chk { flex-direction: row; align-items: center; gap: 6px; }
      .head { display: flex; justify-content: space-between; align-items: flex-start;
              gap: 20px; margin-bottom: 22px; }
      .head h2 { font-size: 1.15rem; margin-bottom: 4px; }
      .head .row-sub { max-width: 62ch; }
      .link { color: var(--accent); text-decoration: none; font-weight: 500; }
      .link:hover { text-decoration: underline; }
      .dormant { margin-top: 18px; }
      .dormant-h, .dormant-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
      .dormant-bar { margin: 12px 0; }
      .dormant-bar .field { max-width: 240px; }
    `,
  ],
})
export class ListsComponent implements OnInit {
  private api = inject(ListsService);
  private router = inject(Router);
  private confirm = inject(ConfirmService);
  private notify = inject(NotifyService);

  lists = signal<AccountList[]>([]);

  // --- filtering ---
  //
  // Client-side, over the rows already loaded. Sorting stays on the server
  // because it has an allowlist and this endpoint supports it; filtering does
  // not exist there yet, and filtering one loaded page while presenting it as
  // the whole list is the failure to avoid — so the panel always reports
  // "showing N of M" from the rows it actually has.
  query = '';
  source = '';
  createdBy = '';
  nonEmptyOnly = false;
  private revision = signal(0);

  sources = computed(() => distinct(this.lists(), (l) => l.source));
  creators = computed(() => distinct(this.lists(), (l) => l.created_by));

  visible = computed(() => {
    this.revision();
    return this.lists().filter(
      (l) =>
        matchesText(l, this.query, [(r) => r.label, (r) => r.description ?? '']) &&
        matchesAny(l.source, this.source ? [this.source] : []) &&
        matchesAny(l.created_by, this.createdBy ? [this.createdBy] : []) &&
        (!this.nonEmptyOnly || l.account_count > 0),
    );
  });

  activeFilters = computed(() => {
    this.revision();
    return [
      this.query.trim(), this.source, this.createdBy, this.nonEmptyOnly ? 'non-empty' : '',
    ].filter(Boolean).length;
  });

  filterSummary = computed(() => {
    this.revision();
    const parts: string[] = [];
    if (this.query.trim()) parts.push(`"${this.query.trim()}"`);
    if (this.source) parts.push(this.source);
    if (this.createdBy) parts.push(`by ${this.createdBy}`);
    if (this.nonEmptyOnly) parts.push('has accounts');
    return parts.join(' · ');
  });

  /** ngModel writes to a plain field, which no signal is watching. */
  touch(): void {
    this.revision.update((n) => n + 1);
  }

  clearFilters(): void {
    this.query = '';
    this.source = '';
    this.createdBy = '';
    this.nonEmptyOnly = false;
    this.touch();
  }
  sort = signal<SortState>(NO_SORT);
  loading = signal(true);
  error = signal<string | null>(null);
  creating = signal(false);
  /** Which create button is working — the two go to different places after. */
  creatingBusy = signal<'import' | 'empty' | null>(null);
  deleting = signal(false);

  // --- dormant accounts ---
  showDormant = signal(false);
  dormant = signal<Account[]>([]);
  loadingDormant = signal(false);
  addingDormant = signal(false);
  pickedDormant = new Set<string>();
  dormantQuery = '';
  dormantTarget = '';

  toggleDormant(): void {
    this.showDormant.update((v) => !v);
    if (this.showDormant()) this.loadDormant();
  }

  loadDormant(): void {
    this.loadingDormant.set(true);
    this.api.accounts(NO_SORT, this.dormantQuery.trim() || undefined, 'only').subscribe({
      next: (rows) => {
        this.dormant.set(rows);
        this.loadingDormant.set(false);
        const shown = new Set(rows.map((r) => r.id));
        for (const id of [...this.pickedDormant]) if (!shown.has(id)) this.pickedDormant.delete(id);
      },
      error: (err) => {
        this.loadingDormant.set(false);
        this.notify.error('Could not load dormant accounts.', apiError(err, 'The server refused.'));
      },
    });
  }

  togglePick(id: string): void {
    if (this.pickedDormant.has(id)) this.pickedDormant.delete(id);
    else this.pickedDormant.add(id);
  }

  addDormant(): void {
    const ids = [...this.pickedDormant];
    const target = this.lists().find((l) => l.id === this.dormantTarget);
    if (!ids.length || !target) return;
    this.addingDormant.set(true);
    this.api.addToList(target.id, ids).subscribe({
      next: (r) => {
        this.addingDormant.set(false);
        this.pickedDormant.clear();
        this.notify.success(
          `Added ${r.added} to ${target.label}`
            + (r.revived ? ` · ${r.revived} brought back with their research and contacts` : '')
            + '.',
        );
        this.loadDormant();
        this.load();
      },
      error: (err) => {
        this.addingDormant.set(false);
        this.notify.error('Could not add those accounts.', apiError(err, 'The server refused.'));
      },
    });
  }

  draft = { label: '', description: '' };

  readonly listLabel = (l: AccountList) => l.label;

  /** Sorted in the browser; see load(). */
  sortedLists = computed(() =>
    sortRows(this.lists(), this.sort(), {
      label: (l) => l.label,
      worked_for: (l) => [...l.service_codes, ...l.icp_names].join(' ') || null,
      contacts: (l) => l.contact_count,
      source: (l) => l.source,
      account_count: (l) => l.account_count,
      created_at: (l) => l.created_at,
      created_by: (l) => l.created_by,
    }),
  );

  readonly columns: ColumnDef[] = [
    { key: 'label', label: 'List', width: 280 },
    { key: 'worked_for', label: 'Worked for', width: 200,
      value: (l) => [...l.service_codes, ...l.icp_names].join(' · ') || 'not set' },
    { key: 'contacts', label: 'Contacts', width: 120, numeric: true, filter: 'none',
      value: (l) => (l.contact_count ? `${l.verified_count}/${l.contact_count}` : '—') },
    { key: 'source', label: 'Source', width: 100, filter: 'enum' },
    { key: 'account_count', label: 'Accounts', width: 100, numeric: true, filter: 'none' },
    { key: 'created_at', label: 'Created', width: 140, filter: 'none' },
    { key: 'created_by', label: 'Created by', width: 120, filter: 'enum', defaultVisible: false },
  ];

  /**
   * Delete is always offered — the server refuses a list that is depended on
   * (researched, or promoted to a queue) and says why, and hiding the button
   * would make a mis-mapped import look permanent.
   */
  readonly actions: RowAction[] = [
    { key: 'import', label: 'Import CSV into it', bulk: false },
    { key: 'delete', label: 'Delete list', danger: true },
  ];

  onTableSort(next: SortState): void {
    this.sort.set(next);
  }

  openList(l: any): void {
    this.router.navigate(['/lists', l.id]);
  }

  async onBulk(run: { action: RowAction; rows: any[]; skipped: any[] }): Promise<void> {
    const rows = run.rows as AccountList[];
    if (!rows.length) return;
    if (run.action.key === 'import') {
      this.router.navigate(['/lists', rows[0].id], { queryParams: { import: 1 } });
      return;
    }
    if (run.action.key !== 'delete') return;

    const one = rows.length === 1 ? rows[0] : null;
    const accounts = rows.reduce((n, l) => n + l.account_count, 0);
    // Named, not generic: "Delete for good?" reads the same over fourteen
    // accounts as over none, and only one of those deserves a pause.
    const ok = await this.confirm.ask({
      title: one ? `Delete ${one.label}?` : `Delete ${rows.length} lists?`,
      body: one
        ? await this.deleteHint(one)
        : `${accounts} account(s) across them. Accounts still on another list or in a campaign `
          + 'queue stay as they are; the rest go dormant with their research and contacts kept, '
          + 'and any nobody worked on are deleted.',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    this.deleting.set(true);
    forkJoin(
      rows.map((l) =>
        this.api.deleteList(l.id).pipe(
          map((r) => ({ l, ok: true as const, r })),
          catchError((err) => of({ l, ok: false as const, err })),
        ),
      ),
    ).subscribe((results: any[]) => {
      this.deleting.set(false);
      const done = results.filter((x) => x.ok);
      const refused = results.filter((x) => !x.ok);
      // "14 deleted, 3 kept" is a different outcome from "17 deleted".
      const removed = done.reduce((n, x) => n + (x.r?.accounts_deleted ?? 0), 0);
      const kept = done.reduce((n, x) => n + (x.r?.accounts_kept ?? 0), 0);
      const asleep = done.reduce((n, x) => n + (x.r?.accounts_dormant ?? 0), 0);
      const gone = new Set(done.map((x) => x.l.id));
      this.lists.update((all) => all.filter((l) => !gone.has(l.id)));
      const summary = done.length
        ? `Deleted ${done.length === 1 ? done[0].l.label : done.length + ' lists'}`
          + (removed ? ` and ${removed} unworked account${removed === 1 ? '' : 's'}` : '')
          + (asleep ? `, ${asleep} now dormant` : '')
          + (kept ? `, ${kept} still in use` : '') + '.'
        : '';
      if (!refused.length) {
        this.notify.success(summary);
      } else {
        const reason = apiError(refused[0].err, 'The server refused.');
        this.notify[done.length ? 'warning' : 'error'](
          (summary ? summary + ' ' : '') + `${refused.length} refused.`, reason);
      }
    });
  }

  ngOnInit(): void {
    this.load();
  }

  onSort(next: SortState): void {
    this.sort.set(next);
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.api.lists(NO_SORT).subscribe({
      next: (rows) => {
        this.lists.set(rows);
        this.loading.set(false);
        this.error.set(null);
      },
      error: (err) => {
        this.loading.set(false);
        // A rejected sort field is a programming error in this component, not a
        // user error, so name the field rather than showing a generic failure.
        const bad = asUnsortableField(err);
        this.error.set(
          bad
            ? `Cannot sort by "${bad.field}". Allowed: ${bad.allowed.join(', ')}`
            : 'Could not load lists — is the API running?',
        );
      },
    });
  }

  /**
   * @param thenImport go straight to the new list with the uploader open.
   *
   * A freshly created list is empty and the CSV uploader lives on the detail
   * page, so staying here leaves you looking at a row with nothing in it and
   * no visible way to fill it.
   */
  create(thenImport = true): void {
    this.creatingBusy.set(thenImport ? 'import' : 'empty');
    this.api.createList({ ...this.draft, source: 'manual' }).subscribe({
      next: (created) => {
        this.creatingBusy.set(null);
        this.notify.success(`Created ${created.label}.`);
        this.draft = { label: '', description: '' };
        this.creating.set(false);
        if (thenImport) {
          this.router.navigate(['/lists', created.id], { queryParams: { import: 1 } });
          return;
        }
        this.load();
      },
      error: (err) => {
        // The form stays open with what was typed; the reason is in the corner.
        this.creatingBusy.set(null);
        this.notify.error('Could not create the list.', apiError(err, 'The server refused.'));
      },
    });
  }

  /** What the button promises before it is pressed. */
  /** What deleting one list does, asked of the server before it is confirmed. */
  async deleteHint(l: AccountList): Promise<string> {
    if (!l.account_count) return `Delete ${l.label} — it holds no accounts.`;
    const lead = `Delete ${l.label} and its ${l.account_count} account${l.account_count === 1 ? '' : 's'}?`;
    try {
      const p = await firstValueFrom(this.api.deletePreview(l.id));
      const parts = [
        p.in_queues ? `${p.in_queues} stay live through a campaign queue` : '',
        p.on_other_lists ? `${p.on_other_lists} stay on other lists` : '',
        p.dormant ? `${p.dormant} go dormant — research and contacts kept` : '',
        p.deleted ? `${p.deleted} deleted — nothing was done with them` : '',
      ].filter(Boolean);
      return `${lead} ${parts.join(' · ')}.`;
    } catch {
      return (
        `${lead} Accounts still on another list or in a campaign queue stay; the rest go ` +
        'dormant with their research and contacts kept, and any nobody worked on are deleted.'
      );
    }
  }

  /**
   * The confirmation names the number, because that is the fact somebody
   * needs at the moment they decide. "Delete for good?" over fourteen
   * accounts reads the same as over none.
   */


  /** Permitted only while the list is empty — the server is the authority. */
}
