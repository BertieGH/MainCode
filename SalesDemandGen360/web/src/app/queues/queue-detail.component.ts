import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { catchError, forkJoin, map, of } from 'rxjs';

import {
  Account,
  AccountList,
  ListsService,
  Contact,
} from '../core/lists.service';
import {
  CadenceShapeView,
  LgmCampaignOption,
  PipelineService,
  Queue,
  QueueMember,
  QueueContact,
  blockersOf,
} from '../core/pipeline.service';
import {
  distinct,
  matchesAny,
  matchesText,
  sortRows,
} from '../shared/client-sort';
import { FilterPanelComponent } from '../shared/filter-panel.component';
import { IconComponent } from '../shared/icon.component';
import { NO_SORT, SortState, SortableDirective } from '../shared/sortable';
import { apiError } from '../shared/api-error';

/**
 * One queue: its members while it is a draft, and the promotion that ends that.
 *
 * Promotion is presented as the one-way door it is. The warning above the
 * button is not decoration — after it, the queue is a historical record and the
 * only way to make a variant is to clone it.
 */
import { DataTableComponent } from '../shared/data-table.component';
import { RATING_COLUMNS_COMPACT, gateClass, bandClass as ratingBand } from '../shared/rating-columns';
import { ColumnDef, RowAction } from '../shared/table-view';

import { ConfirmService } from '../shared/confirm.service';
import { NotifyService } from '../shared/notify.service';
import { ReadinessService } from '../shared/readiness.service';

@Component({
  selector: 'app-queue-detail',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, IconComponent, FilterPanelComponent, SortableDirective, DataTableComponent],
  template: `
    <a routerLink="/queues" class="back"><app-icon name="back" [size]="14" />All queues</a>

    <div class="card" *ngIf="error()" style="border-color:var(--critical);margin:14px 0;">
      <strong style="color:var(--critical);">{{ error() }}</strong>
    </div>

    <div class="head">
      <div>
        <h2>{{ queue()?.label ?? 'Queue' }}</h2>
        <p class="row-sub">
          {{ people().length }} {{ people().length === 1 ? 'person' : 'people' }} ·
          {{ members().length }} account(s)
          <span *ngIf="queue()?.service_code"> · for {{ queue()?.service_code }} · ICP {{ queue()?.icp_name }}</span>
          <span *ngIf="queue()?.status === 'locked'">
            · locked {{ queue()?.locked_at | date: 'MMM d, y' }}
          </span>
        </p>
      </div>
      <div style="display:flex;gap:10px;">
        <button *ngIf="draftQueue()" class="btn" (click)="adding.set(!adding())">
          <app-icon name="plus" [size]="13" />Add people or accounts
        </button>
        <button *ngIf="draftQueue()" class="btn btn-primary"
                (click)="openPromote()"
                [disabled]="!members().length && !people().length"
                title="Lock this queue and start an outreach campaign from it">
          Promote to outreach
        </button>
        <button *ngIf="draftQueue()" class="btn" [class.busy]="deleting()" [disabled]="deleting()"
                (click)="removeQueue()" title="Delete this queue — it has never fed a campaign">
          <app-icon *ngIf="!deleting()" name="trash" [size]="13" />{{ deleting() ? 'Deleting…' : 'Delete' }}
        </button>
      </div>
    </div>

    <!-- Said here rather than enforced on the button: promoting, drafting and
         approving touch nothing at La Growth Machine. Only enrolling does. -->
    <p class="row-sub gate" *ngIf="draftQueue() && outreachReady() === false">
      La Growth Machine is not connected, so nothing can be <em>sent</em> yet —
      <a routerLink="/settings/setup" class="link">connect it in API settings</a>.
      Promoting this queue, drafting and approving all work without it.
    </p>
    <div class="card lock-note" *ngIf="queue()?.status === 'locked'">
      <strong>This queue is locked.</strong>
      <span class="row-sub">
        It fed a campaign and is now a historical record. To make a variant, clone it from the
        queue list — re-opening it would make "which version fed that campaign?" unanswerable.
      </span>
    </div>

    <!-- add members: pick a list, then cherry-pick from it -->
    <div class="card builder" *ngIf="adding()">
      <p class="row-sub" style="margin-bottom:12px;max-width:70ch;">
        A queue is built <strong>from lists</strong>, and can draw from several. Pick a list, take
        as many or as few of its accounts as you want, then switch lists and take more — the
        source is recorded per account as a provenance stamp with no behaviour.
      </p>

      <div class="lists">
        <button *ngFor="let l of lists()" class="chip" [class.on]="sourceList()?.id === l.id"
                (click)="pickList(l)">
          {{ l.label }}
          <span class="row-sub">{{ l.account_count }}</span>
        </button>
        <a routerLink="/lists" class="chip chip-link">
          <app-icon name="plus" [size]="12" />New list
        </a>
      </div>

      <ng-container *ngIf="sourceList() as l">
        <!-- People first: a campaign sends to people. Whole accounts can still
             be queued, and bring the people their strategy pursues. -->
        <div class="modes">
          <button type="button" class="chip" [class.on]="addMode() === 'people'" (click)="addMode.set('people')">
            People <span class="row-sub">{{ listContacts().length }}</span>
          </button>
          <button type="button" class="chip" [class.on]="addMode() === 'accounts'" (click)="addMode.set('accounts')">
            Accounts <span class="row-sub">{{ listAccounts().length }}</span>
          </button>
        </div>
        <!-- The chosen list's accounts, in the same table as everywhere else.
             Selecting and adding is the selection bar's job; ineligible rows
             say why rather than sitting disabled with no reason. -->
        <app-data-table *ngIf="addMode() === 'accounts'"
          table="queue-add"
          noun="accounts"
          emptyText="This list has no accounts yet."
          [columns]="addColumns"
          [data]="listAccounts()"
          [selectable]="true"
          [rowActions]="addActions"
          [busyKey]="busy() ? 'add' : null"
          busyText="Adding…"
          [openable]="false"
          [scopeLabel]="l.label"
          (bulk)="onAddBulk($event)"
          (rowAction)="onAddBulk({ action: $event.action, rows: [$event.row], skipped: [] })"
          [cell]="addCell">
        </app-data-table>
        <ng-template #addCell let-row let-column="column" let-value="value">
          <ng-container [ngSwitch]="column.key">
            <span *ngSwitchCase="'in_queue'" class="badge"
                  [ngClass]="isMember(row.id) ? 'badge-neutral' : 'badge-good'">{{ value }}</span>
            <ng-container *ngSwitchDefault>{{ value }}</ng-container>
          </ng-container>
        </ng-template>

        <app-data-table *ngIf="addMode() === 'people'"
          table="queue-add-people"
          noun="people"
          emptyText="This list has no contacts yet."
          [columns]="addPeopleColumns"
          [data]="listContacts()"
          [selectable]="true"
          [rowActions]="addPeopleActions"
          [busyKey]="busy() ? 'add' : null"
          busyText="Adding…"
          [openable]="false"
          [scopeLabel]="l.label"
          (bulk)="onAddPeople($event)"
          (rowAction)="onAddPeople({ action: $event.action, rows: [$event.row], skipped: [] })"
          [cell]="addPeopleCell">
        </app-data-table>
        <ng-template #addPeopleCell let-row let-column="column" let-value="value">
          <ng-container [ngSwitch]="column.key">
            <span *ngSwitchCase="'in_queue'" class="badge"
                  [ngClass]="isPerson(row.id) ? 'badge-neutral' : 'badge-good'">{{ value }}</span>
            <ng-container *ngSwitchDefault>{{ value }}</ng-container>
          </ng-container>
        </ng-template>
      </ng-container>

      <p class="row-sub" *ngIf="!sourceList()" style="padding:18px 0;">
        Choose a list above to see its people and accounts.
      </p>
    </div>

    <!-- promote -->
    <div class="card promote" *ngIf="promoting()">
      <strong style="display:block;margin-bottom:6px;">Promote to a campaign</strong>
      <p class="row-sub" style="margin-bottom:12px;max-width:70ch;">
        This <strong>locks the queue permanently</strong> and gives each chosen person a sequence in
        a new campaign (whole accounts bring their strategy's people). A strategy is needed for
        each person before anything is executed. Nothing sends, and no content is written yet — drafting
        is a separate stage, and the campaign opens for approval only once an arc exists.
      </p>
      <div class="form-grid">
        <label>Campaign name
          <input class="field" [(ngModel)]="promotion.label">
          <span class="row-sub">
            Carried over from the queue so the work keeps one name end to end. Change it only if
            the campaign is genuinely a different thing.
          </span>
        </label>
        <!-- The LGM campaign itself, read live, rather than the shapes we
             happen to have registered. Picking it is picking the cadence: its
             steps, its channels, its audience and the schedule LGM runs it on.
             One that has not been registered here yet is registered on the
             way through — that used to be a separate errand on another
             screen, and the list on this one looked empty or stale. -->
        <label>La Growth Machine campaign
          <select class="field" [(ngModel)]="promotion.lgm_campaign_id">
            <option [ngValue]="null">— choose a campaign —</option>
            <option *ngFor="let c of lgmCampaigns()" [ngValue]="c.id">
              {{ c.name }}{{ c.status ? ' · ' + c.status.toLowerCase() : '' }}{{ registeredKey(c.id) ? ' · registered' : '' }}
            </option>
          </select>
          <span class="row-sub" *ngIf="lgmCampaigns().length">
            Its steps decide how many touches get written, and LGM keeps the schedule. A campaign
            not registered here yet is registered when you promote.
          </span>
          <span class="row-sub" *ngIf="!lgmCampaigns().length">
            No campaigns came back from La Growth Machine — either no key is stored, or the
            account has none. Check the connection on the
            <a class="link" routerLink="/campaigns">Campaigns</a> screen.
          </span>
        </label>
      </div>
      <div style="display:flex;gap:10px;align-items:center;margin-top:14px;">
        <button class="btn btn-primary" (click)="promote()" [class.busy]="promotingBusy()"
                [disabled]="promotingBusy() || !promotion.label.trim() || !promotion.lgm_campaign_id">
          <app-icon *ngIf="!promotingBusy()" name="check" [size]="13" />
          {{ promotingBusy() ? 'Promoting…' : 'Lock queue and create outreach' }}
        </button>
        <button class="btn" (click)="promoting.set(false)">Cancel</button>
      </div>
    </div>

    <!-- The people this queue sends to. -->
    <h3 class="section">People <span class="row-sub">{{ people().length }}</span></h3>
    <app-data-table
      table="queue-people"
      noun="people"
      emptyText="No people yet — add them from a list. A campaign sends to people."
      [columns]="peopleColumns"
      [data]="people()"
      [selectable]="draftQueue()"
      [rowActions]="peopleActions"
      [busyKey]="removing() ? 'remove' : researching() ? 'research' : null"
      [busyText]="removing() ? 'Removing…' : 'Researching…'"
      [idOf]="personId"
      [label]="personLabel"
      (open)="openPerson($event)"
      (bulk)="onPeopleBulk($event)"
      (rowAction)="onPeopleBulk({ action: $event.action, rows: [$event.row], skipped: [] })"
      [cell]="personCell">
    </app-data-table>
    <ng-template #personCell let-row let-column="column" let-value="value">
      <ng-container [ngSwitch]="column.key">
        <a *ngSwitchCase="'account_name'" class="link"
           [routerLink]="['/accounts', row.account_id]">{{ value }}</a>
        <span *ngSwitchCase="'reachable_by'" class="badge"
              [ngClass]="row.reachable_by === 'not reachable' ? 'badge-critical' : 'badge-good'">{{ value }}</span>
        <span *ngSwitchCase="'qualification_band'" class="badge" [ngClass]="ratingBand(row.qualification_band)"
              [title]="row.gate_detail">{{ value }}</span>
        <span *ngSwitchCase="'gate'" class="badge" [ngClass]="gateClass(row.gate)"
              [title]="row.gate_detail">{{ value }}</span>
        <ng-container *ngSwitchDefault>{{ value }}</ng-container>
      </ng-container>
    </ng-template>

    <h3 class="section">Accounts <span class="row-sub">{{ members().length }}</span></h3>
    <!-- The queue's members. Selectable only while the queue is a draft — a
         locked queue is a historical record, and nothing about it changes. -->
    <app-data-table
      table="queue-members"
      noun="accounts"
      emptyText="No accounts yet. Add some before promoting."
      [columns]="memberColumns"
      [data]="sortedMembers()"
      [sort]="sort()"
      (sortChange)="onSort($event)"
      [selectable]="draftQueue()"
      [rowActions]="memberActions"
      [busyKey]="removing() ? 'remove' : researching() ? 'research' : null"
      [busyText]="removing() ? 'Removing…' : 'Researching…'"
      [idOf]="memberId"
      [label]="memberLabel"
      (open)="openMember($event)"
      (bulk)="onMemberBulk($event)"
      (rowAction)="onMemberBulk({ action: $event.action, rows: [$event.row], skipped: [] })"
      [cell]="memberCell">
    </app-data-table>
    <ng-template #memberCell let-row let-column="column" let-value="value">
      <ng-container [ngSwitch]="column.key">
        <a *ngSwitchCase="'account_name'" class="link"
           [routerLink]="['/accounts', row.account_id]">{{ value }}</a>
        <ng-container *ngSwitchCase="'priority_score'">
          <span *ngIf="row.priority_band" class="badge" [ngClass]="bandClass(row.priority_band)">
            {{ row.priority_band }} {{ row.priority_score }}
          </span>
          <span *ngIf="!row.priority_band" class="row-sub">not qualified</span>
        </ng-container>
        <ng-container *ngSwitchDefault>{{ value }}</ng-container>
      </ng-container>
    </ng-template>
  `,
  styles: [
    `
      .gate { margin: 0 0 14px; }
      .err { color: var(--critical); }
      .f { display: flex; flex-direction: column; gap: 4px; font-size: .78rem; }
      .f .field { min-width: 170px; }
      .f .narrow { min-width: 90px; }
      .f.chk { flex-direction: row; align-items: center; gap: 6px; }
      .back { display: inline-flex; align-items: center; gap: 5px; color: var(--accent);
              text-decoration: none; font-size: .84rem; margin-bottom: 14px; }
      .head { display: flex; justify-content: space-between; align-items: flex-start;
              gap: 20px; margin-bottom: 18px; }
      .head h2 { font-size: 1.15rem; margin-bottom: 2px; }
      .link { color: var(--accent); text-decoration: none; font-weight: 500; }
      .lock-note { border-color: var(--line); margin-bottom: 18px; }
      .promote { border-color: var(--warn); margin-bottom: 18px; }
      .builder { margin-bottom: 18px; }
      .section { font-size: .95rem; margin: 18px 0 8px; }
      .modes { display: flex; gap: 8px; margin: 2px 0 12px; }
      .lists { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
      .chip { display: inline-flex; align-items: center; gap: 7px; padding: 6px 12px;
              border: 1px solid var(--line); border-radius: 999px; background: none;
              cursor: pointer; font-size: .82rem; color: inherit; text-decoration: none; }
      .chip.on { border-color: var(--accent); background: var(--accent-soft, transparent);
                 font-weight: 500; }
      .chip-link { color: var(--accent); }
      .pick-head { display: flex; justify-content: space-between; align-items: center;
                   gap: 16px; margin-bottom: 10px; }
      .all { display: flex; align-items: center; gap: 8px; font-size: .84rem; cursor: pointer; }
      .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
      .form-grid label { display: flex; flex-direction: column; gap: 5px; font-size: .84rem; }
      @media (max-width: 720px) { .form-grid { grid-template-columns: 1fr; } }
    `,
  ],
})
export class QueueDetailComponent implements OnInit {
  /** A shape's blockers. A warning is not one — see `blockersOf`. */
  readonly blockersOf = blockersOf;

  private api = inject(PipelineService);
  private listsApi = inject(ListsService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private confirm = inject(ConfirmService);
  private notify = inject(NotifyService);
  private readiness = inject(ReadinessService);
  deleting = signal(false);
  removing = signal(false);
  promotingBusy = signal(false);
  /** `false` only once known to be missing — unknown never blocks. */
  outreachReady = computed(() => this.readiness.satisfied('outreach'));

  queueId = '';
  queue = signal<Queue | null>(null);
  members = signal<QueueMember[]>([]);
  shapes = signal<CadenceShapeView[]>([]);
  lists = signal<AccountList[]>([]);
  sourceList = signal<AccountList | null>(null);
  listAccounts = signal<Account[]>([]);
  selected = signal<Set<string>>(new Set());
  loading = signal(true);
  busy = signal(false);
  error = signal<string | null>(null);
  adding = signal(false);
  promoting = signal(false);

  // --- sorting and filtering ---
  //
  // Client-side: a queue's members load whole. The rule is to sort where the
  // data is complete.
  sort = signal<SortState>(NO_SORT);

  query = '';
  band = '';
  source = '';
  private revision = signal(0);

  private readonly memberAccessors: Record<string, (m: QueueMember) => unknown> = {
    name: (m) => m.account_name,
    domain: (m) => m.domain,
    // Unqualified accounts sort as the lowest score rather than as blanks, so
    // "worst first" actually surfaces them — they are the ones needing work.
    priority: (m) => m.priority_score ?? -1,
    source: (m) => (m.source_list_id ? 'from a list' : 'added directly'),
  };

  bands = computed(() => distinct(this.members(), (m) => m.priority_band));

  visibleMembers = computed(() => {
    this.revision();
    const rows = this.members().filter((m) => {
      if (!matchesText(m, this.query, [(r) => r.account_name, (r) => r.domain ?? ''])) {
        return false;
      }
      if (this.band === '__none' && m.priority_band) return false;
      if (this.band && this.band !== '__none' && m.priority_band !== this.band) return false;
      if (this.source === 'list' && !m.source_list_id) return false;
      if (this.source === 'direct' && m.source_list_id) return false;
      return true;
    });
    return sortRows(rows, this.sort(), this.memberAccessors);
  });

  activeFilters = computed(() => {
    this.revision();
    return [this.query.trim(), this.band, this.source].filter(Boolean).length;
  });

  filterSummary = computed(() => {
    this.revision();
    const parts: string[] = [];
    if (this.query.trim()) parts.push(`"${this.query.trim()}"`);
    if (this.band) parts.push(this.band === '__none' ? 'not qualified' : this.band);
    if (this.source) parts.push(this.source === 'list' ? 'from a list' : 'added directly');
    return parts.join(' · ');
  });

  /** ngModel writes to a plain field, which no signal is watching. */
  touch(): void {
    this.revision.update((n) => n + 1);
  }

  onSort(state: SortState): void {
    this.sort.set(state);
  }

  clearFilters(): void {
    this.query = '';
    this.band = '';
    this.source = '';
    this.touch();
  }


  // --- people ---
  people = signal<QueueContact[]>([]);
  listContacts = signal<Contact[]>([]);
  addMode = signal<'people' | 'accounts'>('people');

  readonly personId = (p: QueueContact) => p.contact_id;
  readonly personLabel = (p: QueueContact) => p.full_name;

  readonly ratingBand = ratingBand;
  readonly gateClass = gateClass;

  readonly peopleColumns: ColumnDef[] = [
    { key: 'full_name', label: 'Person', width: 190 },
    { key: 'title', label: 'Title', width: 200, value: (p) => p.title ?? '—' },
    { key: 'account_name', label: 'Company', width: 180 },
    ...RATING_COLUMNS_COMPACT,
    { key: 'reachable_by', label: 'Reachable by', width: 120, filter: 'enum' },
    { key: 'email', label: 'Email', width: 210, value: (p) => p.email ?? '—' },
  ];

  readonly peopleActions: RowAction[] = [
    // Offered here as well as on the account screen, because this is where a
    // rep reads a queue before promoting it: finding somebody thin is exactly
    // the moment to look into them, and sending them to the account screen to
    // do it loses the queue they were checking.
    //
    // Allowed on a locked queue, unlike removal. Research changes what is
    // known about a person, not who is in the queue, so nothing a lock
    // protects is touched.
    //
    // No do-not-contact gate, unlike the account screen's copy: queues refuse
    // a suppressed person on the way in, so one cannot be sitting here. A
    // `can` reading a field this row does not carry would be a gate that
    // always passes, dressed up as a check.
    {
      key: 'research',
      label: 'Research this person',
      row: true,
      bulk: true,
    },
    {
      key: 'remove',
      label: 'Remove from queue',
      danger: true,
      can: () => this.draftQueue(),
      why: 'the queue is locked',
    },
  ];

  readonly addPeopleColumns: ColumnDef[] = [
    { key: 'full_name', label: 'Person', width: 190 },
    { key: 'title', label: 'Title', width: 200, value: (c) => c.title ?? '—' },
    { key: 'account_name', label: 'Company', width: 170 },
    { key: 'email_status', label: 'Email status', width: 110, filter: 'enum',
      value: (c) => c.email_status ?? 'unverified' },
    { key: 'linkedin', label: 'LinkedIn', width: 90, filter: 'enum',
      value: (c) => (c.linkedin_url ? 'yes' : 'no') },
    { key: 'in_queue', label: 'In queue', width: 120, filter: 'enum',
      value: (c) => (this.isPerson(c.id) ? 'already in queue' : 'not yet') },
  ];

  /** The server's rule, mirrored: reachable, and not already here. */
  readonly addPeopleActions: RowAction[] = [
    {
      key: 'add',
      label: 'Add to this queue',
      can: (c) =>
        !this.isPerson(c.id) && ((c.email_status === 'verified' && !!c.email) || !!c.linkedin_url),
      why: 'already in the queue, or no verified email or LinkedIn profile',
    },
  ];

  isPerson(contactId: string): boolean {
    return this.people().some((p) => p.contact_id === contactId);
  }

  openPerson(p: any): void {
    this.router.navigate(['/accounts', p.account_id]);
  }

  onAddPeople(run: { action: RowAction; rows: any[]; skipped: any[] }): void {
    if (!run.rows.length) return;
    const source = this.sourceList();
    this.busy.set(true);
    this.api.addQueueContacts(this.queueId, run.rows.map((c) => c.id), source?.id ?? null).subscribe({
      next: (r) => {
        this.busy.set(false);
        const text = `${r.added} ${r.added === 1 ? 'person' : 'people'} added`
          + (r.already ? ` · ${r.already} already here` : '')
          + (r.refused.length ? ` · ${r.refused.length} refused` : '') + '.';
        const reasons = [...new Set(r.refused.map((x) => x.reason))].join('; ') || null;
        if (!r.refused.length) this.notify.success(text);
        else if (r.added) this.notify.warning(text, reasons);
        else this.notify.error(text, reasons);
        this.load();
      },
      error: (err) => {
        this.busy.set(false);
        this.notify.error('Could not add those people.', apiError(err, 'The server refused.'));
      },
    });
  }

  async onPeopleBulk(run: { action: RowAction; rows: any[]; skipped: any[] }): Promise<void> {
    if (run.action.key === 'research') {
      this.researchPeople(run.rows as QueueContact[]);
      return;
    }
    if (run.action.key !== 'remove' || !run.rows.length) return;
    const n = run.rows.length;
    const ok = await this.confirm.ask({
      title: `Remove ${n} ${n === 1 ? 'person' : 'people'} from this queue?`,
      body: 'They stay on their lists and can be added again while the queue is a draft.',
      confirmLabel: 'Remove',
      danger: true,
    });
    if (!ok) return;
    this.removing.set(true);
    forkJoin(
      run.rows.map((p: QueueContact) =>
        this.api.removeQueueContact(this.queueId, p.contact_id).pipe(
          map(() => null),
          catchError((err) => of(apiError(err, 'refused'))),
        ),
      ),
    ).subscribe((results) => {
      this.removing.set(false);
      const failed = results.filter((x) => x !== null) as string[];
      const done = results.length - failed.length;
      if (!failed.length) this.notify.success(`Removed ${done} from the queue.`);
      else this.notify[done ? 'warning' : 'error'](`Removed ${done} · ${failed.length} refused.`, failed[0]);
      this.load();
    });
  }

  researching = signal(false);

  /**
   * Research the people picked here.
   *
   * **Grouped by company, one request each.** The endpoint is per account —
   * what research looks for comes from the account's list ICPs — and a queue's
   * people come from wherever they were queued from, so a selection spanning
   * three companies is three plans, not one. Sending them as a single call
   * would have to pick a company and quietly research the wrong people.
   */
  researchPeople(rows: QueueContact[]): void {
    const byAccount = new Map<string, string[]>();
    for (const person of rows ?? []) {
      if (!person.account_id || !person.contact_id) continue;
      byAccount.set(person.account_id, [
        ...(byAccount.get(person.account_id) ?? []),
        person.contact_id,
      ]);
    }
    if (!byAccount.size) return;

    this.researching.set(true);
    forkJoin(
      [...byAccount].map(([accountId, contactIds]) =>
        this.listsApi.researchAccount(accountId, { contactIds }).pipe(
          map((r: any) => ({ ok: !!r?.ran && !r?.blocked, why: r?.blocked as string | null, r })),
          catchError((err) => of({ ok: false, why: apiError(err, 'refused'), r: null })),
        ),
      ),
    ).subscribe((results) => {
      this.researching.set(false);
      const failed = results.filter((x) => !x.ok);
      const signals = results.reduce((n, x) => n + (x.r?.signals_stored ?? 0), 0);
      const evidence = results.reduce((n, x) => n + (x.r?.evidence_stored ?? 0), 0);
      const people = rows.length;
      const what =
        `${people} ${people === 1 ? 'person' : 'people'} at ${byAccount.size} ` +
        `compan${byAccount.size === 1 ? 'y' : 'ies'} · ${evidence} evidence · ${signals} signal(s)`;
      if (!failed.length) this.notify.success(`Researched ${what}.`);
      else
        this.notify[failed.length < results.length ? 'warning' : 'error'](
          `Researched ${results.length - failed.length} of ${results.length} companies.`,
          failed[0].why ?? undefined,
        );
      this.load();
    });
  }

  /** The accounts picked here, one request each. No contact ids, so the
   *  company's own families are what gets planned. */
  researchCompanies(rows: QueueMember[]): void {
    const ids = [...new Set((rows ?? []).map((m) => m.account_id).filter(Boolean))];
    if (!ids.length) return;
    this.researching.set(true);
    forkJoin(
      ids.map((id) =>
        this.listsApi.researchAccount(id).pipe(
          map((r: any) => ({ ok: !!r?.ran && !r?.blocked, why: r?.blocked as string | null, r })),
          catchError((err) => of({ ok: false, why: apiError(err, 'refused'), r: null })),
        ),
      ),
    ).subscribe((results) => {
      this.researching.set(false);
      const failed = results.filter((x) => !x.ok);
      const signals = results.reduce((n, x) => n + (x.r?.signals_stored ?? 0), 0);
      const reused = results.filter((x) => x.r?.reused).length;
      const done = results.length - failed.length;
      const note = `${done} compan${done === 1 ? 'y' : 'ies'} · ${signals} signal(s)`
        + (reused ? ` · ${reused} reused, nothing bought` : '');
      if (!failed.length) this.notify.success(`Researched ${note}.`);
      else
        this.notify[done ? 'warning' : 'error'](
          `Researched ${done} of ${results.length}.`, failed[0].why ?? undefined,
        );
      this.load();
    });
  }

  readonly memberId = (m: QueueMember) => m.account_id;
  readonly memberLabel = (m: QueueMember) => m.account_name;

  /** Members, sorted here — this screen sorts in the browser, and the table
   *  only filters. */
  sortedMembers = computed(() =>
    sortRows(this.members(), this.sort(), {
      account_name: (m) => m.account_name,
      domain: (m) => m.domain,
      priority_score: (m) => m.priority_score,
      source: (m) => (m.source_list_id ? 'from a list' : 'added directly'),
    }),
  );

  readonly memberColumns: ColumnDef[] = [
    { key: 'account_name', label: 'Account', width: 240 },
    { key: 'domain', label: 'Domain', width: 200, value: (m) => m.domain ?? '—' },
    {
      key: 'priority_score',
      label: 'Priority',
      width: 140,
      filter: 'enum',
      // Filtered by band, sorted by score: the band is what a rep scans for.
      value: (m) => m.priority_band ?? 'not qualified',
    },
    {
      key: 'source',
      label: 'Source',
      width: 140,
      filter: 'enum',
      value: (m) => (m.source_list_id ? 'from a list' : 'added directly'),
    },
  ];

  /** Built here rather than shared: removal depends on this queue's state. */
  readonly memberActions: RowAction[] = [
    // The company's own families, where the people action researches a person.
    // Both are here because a queue is read before it is promoted, and that is
    // when a thin account is noticed.
    { key: 'research', label: 'Research this company', row: true, bulk: true },
    {
      key: 'remove',
      label: 'Remove from queue',
      danger: true,
      can: () => this.draftQueue(),
      why: 'the queue is locked',
    },
  ];

  readonly addColumns: ColumnDef[] = [
    { key: 'name', label: 'Account', width: 230 },
    { key: 'domain', label: 'Domain', width: 190, value: (a) => a.domain ?? '—' },
    {
      key: 'resolution_status',
      label: 'Identity',
      width: 120,
      filter: 'enum',
      value: (a) =>
        ({ resolved: 'confirmed', needs_review: 'check this', unresolved: 'not identified',
           rejected: 'rejected' })[a.resolution_status as string] ?? a.resolution_status,
    },
    { key: 'icp_match_score', label: 'ICP fit', width: 90, numeric: true, filter: 'none',
      value: (a) => a.icp_match_score ?? '—' },
    { key: 'status', label: 'Status', width: 110, filter: 'enum' },
    { key: 'in_queue', label: 'In queue', width: 120, filter: 'enum',
      value: (a) => (this.isMember(a.id) ? 'already in queue' : 'not yet') },
  ];

  /**
   * The same rule the server enforces in `promotion.add_member`, so the
   * picker refuses for the reasons the server would: a confirmed identity,
   * not disqualified — and not already here.
   */
  readonly addActions: RowAction[] = [
    {
      key: 'add',
      label: 'Add to this queue',
      can: (a) =>
        !this.isMember(a.id) && a.resolution_status === 'resolved' && a.status !== 'disqualified',
      why: 'already in the queue, not confirmed, or disqualified',
    },
  ];


  openMember(m: any): void {
    this.router.navigate(['/accounts', m.account_id]);
  }

  /**
   * Add through the bulk endpoint, which reports each refusal by name. The
   * old picker sent one request per account and gave up on the first 409 —
   * "Could not add every account", with no word on which or why.
   */
  /** Through the bulk endpoint, which names each refusal. */
  onAddBulk(run: { action: RowAction; rows: any[]; skipped: any[] }): void {
    if (!run.rows.length) return;
    const source = this.sourceList();
    this.busy.set(true);
    this.listsApi.addToQueue(this.queueId, run.rows.map((a) => a.id), source?.id ?? null).subscribe({
      next: (r) => {
        this.busy.set(false);
        const text = `${r.added} added`
          + (r.already ? ` · ${r.already} already here` : '')
          + (r.refused.length ? ` · ${r.refused.length} refused` : '') + '.';
        const reasons = [...new Set(r.refused.map((x) => x.reason))].join('; ') || null;
        if (!r.refused.length) this.notify.success(text);
        else if (r.added) this.notify.warning(text, reasons);
        else this.notify.error(text, reasons);
        this.load();
      },
      error: (err) => {
        this.busy.set(false);
        this.notify.error('Could not add those accounts.', apiError(err, 'The server refused.'));
      },
    });
  }

  /** Remove one or many; each is its own request, and one failure is reported
   *  without costing the rest. */
  /** Remove one or many; one refusal is reported without costing the rest. */
  async onMemberBulk(run: { action: RowAction; rows: any[]; skipped: any[] }): Promise<void> {
    if (run.action.key === 'research') {
      this.researchCompanies(run.rows as QueueMember[]);
      return;
    }
    if (run.action.key !== 'remove' || !run.rows.length) return;
    const n = run.rows.length;
    const ok = await this.confirm.ask({
      title: `Remove ${n} account${n === 1 ? '' : 's'} from this queue?`,
      body: 'They stay on their lists and can be added again while the queue is a draft.',
      confirmLabel: 'Remove',
      danger: true,
    });
    if (!ok) return;
    this.removing.set(true);
    forkJoin(
      run.rows.map((m: QueueMember) =>
        this.api.removeQueueMember(this.queueId, m.account_id).pipe(
          map(() => null),
          catchError((err) => of(apiError(err, 'refused'))),
        ),
      ),
    ).subscribe((results) => {
      this.removing.set(false);
      const failed = results.filter((x) => x !== null) as string[];
      const done = results.length - failed.length;
      if (!failed.length) this.notify.success(`Removed ${done} from the queue.`);
      else this.notify[done ? 'warning' : 'error'](
        `Removed ${done} · ${failed.length} refused.`, failed[0]);
      this.load();
    });
  }

  promotion = { label: '', lgm_campaign_id: null as string | null };
  lgmCampaigns = signal<LgmCampaignOption[]>([]);

  /** The registration for an LGM campaign, where one exists. */
  registeredKey(lgmCampaignId: string): CadenceShapeView | undefined {
    return this.shapes().find((s) => s.lgm_campaign_id === lgmCampaignId);
  }

  ngOnInit(): void {
    this.readiness.refresh();
    this.queueId = this.route.snapshot.paramMap.get('id') ?? '';
    this.load();
    this.api.cadenceShapes(true).subscribe({ next: (s) => this.shapes.set(s) });
    this.api.lgmCampaigns().subscribe({
      next: (rows) => this.lgmCampaigns.set(rows),
      error: () => this.lgmCampaigns.set([]),
    });
      }

  async removeQueue(): Promise<void> {
    const label = this.queue()?.label ?? 'this queue';
    const n = this.members().length;
    const ok = await this.confirm.ask({
      title: `Delete ${label}?`,
      body: `It has never fed a campaign. Its ${n} account${n === 1 ? '' : 's'} stay on `
        + 'their lists and can be queued again.',
      confirmLabel: 'Delete queue',
      danger: true,
    });
    if (!ok) return;
    this.deleting.set(true);
    this.api.deleteQueue(this.queueId).subscribe({
      next: () => {
        this.deleting.set(false);
        this.notify.success(`Deleted ${label}.`);
        this.router.navigate(['/queues']);
      },
      error: (err) => {
        this.deleting.set(false);
        this.notify.error('Could not delete the queue.', apiError(err, 'The server refused.'));
      },
    });
  }

  openPromote(): void {
    if (!this.promoting()) {
      // Default the campaign to the queue's own name — continuity is the
      // point, and a rep who wants a different one can still type it.
      this.promotion.label = this.queue()?.label ?? '';
    }
    this.promoting.set(!this.promoting());
  }

  draftQueue(): boolean {
    return this.queue()?.status === 'draft';
  }

  isMember(accountId: string): boolean {
    return this.members().some((m) => m.account_id === accountId);
  }

  bandClass(band: string): string {
    return band === 'high' ? 'badge-good' : band === 'medium' ? 'badge-accent' : 'badge-neutral';
  }

  pickList(l: AccountList): void {
    this.sourceList.set(l);
    this.selected.set(new Set());
    this.listsApi.listAccounts(l.id, NO_SORT).subscribe({
      next: (a) => this.listAccounts.set(a),
      error: () => this.listAccounts.set([]),
    });
    this.listsApi.listContacts(l.id, NO_SORT).subscribe({
      next: (c) => this.listContacts.set(c),
      error: () => this.listContacts.set([]),
    });
  }

  /** Accounts in the open list that are not already queue members. */
  addable(): Account[] {
    return this.listAccounts().filter((a) => !this.isMember(a.id));
  }

  allSelectable(): boolean {
    const addable = this.addable();
    return addable.length > 0 && addable.every((a) => this.selected().has(a.id));
  }

  toggleAll(): void {
    const addable = this.addable();
    this.selected.set(
      this.allSelectable() ? new Set() : new Set(addable.map((a) => a.id)),
    );
  }

  toggleOne(id: string): void {
    this.selected.update((set) => {
      const next = new Set(set);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  /**
   * Promote onto the chosen LGM campaign, registering it if this is the first
   * time it has been used. Registration reads the steps and the attribute each
   * one sends straight from LGM — Gen360 never authors a cadence — so doing it
   * here costs one call and saves an errand on another screen.
   */
  promote(): void {
    const lgmId = this.promotion.lgm_campaign_id;
    if (!lgmId) return;
    const known = this.registeredKey(lgmId);
    if (known) {
      this.promoteWith(known.id);
      return;
    }
    this.promotingBusy.set(true);
    const campaign = this.lgmCampaigns().find((c) => c.id === lgmId);
    this.api.createCadenceShape({ lgm_campaign_id: lgmId, label: campaign?.name ?? 'Cadence' })
      .subscribe({
        next: (r) => {
          if (!r.shape_id) {
            this.promotingBusy.set(false);
            this.notify.error('That campaign could not be registered.', r.detail);
            return;
          }
          if (r.findings.length) {
            this.notify.warning(`Registered ${campaign?.name ?? 'the campaign'}, with findings.`, r.findings.join(' · '));
          }
          this.api.cadenceShapes(true).subscribe({ next: (s) => this.shapes.set(s) });
          this.promoteWith(r.shape_id);
        },
        error: (err) => {
          this.promotingBusy.set(false);
          this.notify.error(
            'That campaign could not be registered.',
            apiError(err, 'The server refused.'),
          );
        },
      });
  }

  private promoteWith(cadenceShapeId: string): void {
    this.promotingBusy.set(true);
    this.api
      .promote({
        label: this.promotion.label.trim() || null,
        queue_ids: [this.queueId],
        cadence_shape_id: cadenceShapeId,
      })
      .subscribe({
        next: (c) => {
          this.promotingBusy.set(false);
          if (c.notes?.length) {
            // Smaller than its queue: say why before the rep navigates away.
            this.notify.warning(
              `Promoted with ${c.sequences} sequence(s) — some accounts were skipped.`,
              c.notes.join('; '),
            );
          } else {
            this.notify.success(`Promoted to a campaign with ${c.sequences} sequence(s).`);
          }
          this.router.navigate(['/campaigns', c.id]);
        },
        error: (err) => {
          this.promotingBusy.set(false);
          // The card stays open so nothing typed is lost; the reason is in the
          // notice. It used to close and put the error above the fold.
          this.notify.error('Could not promote the queue.', apiError(err, 'The server refused.'));
        },
      });
  }

  private load(): void {
    this.loading.set(true);
    this.listsApi.lists(NO_SORT).subscribe({ next: (l) => this.lists.set(l) });
    this.api.queues().subscribe({
      next: (all) => this.queue.set(all.find((q) => q.id === this.queueId) ?? null),
    });
    this.api.queueContacts(this.queueId).subscribe({
      next: (p) => this.people.set(p),
      error: () => this.people.set([]),
    });
    this.api.queueMembers(this.queueId).subscribe({
      next: (m) => {
        this.members.set(m);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(apiError(err, 'Could not load the queue.'));
      },
    });
  }
}
