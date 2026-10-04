import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import {
  CadenceShapeView,
  LgmCampaignOption,
  PipelineService,
  Queue,
  blockersOf,
} from '../core/pipeline.service';
import { ConfigService, IcpProfile, Service } from '../core/config.service';
import {
  matchesAny,
  matchesText,
  sortRows,
} from '../shared/client-sort';
import { FilterPanelComponent } from '../shared/filter-panel.component';
import { IconComponent } from '../shared/icon.component';
import { NO_SORT, SortState, SortableDirective } from '../shared/sortable';
import { apiError } from '../shared/api-error';

import { catchError, forkJoin, map, of } from 'rxjs';
import { DataTableComponent } from '../shared/data-table.component';
import { ColumnDef, RowAction } from '../shared/table-view';

import { ConfirmService } from '../shared/confirm.service';
import { NotifyService } from '../shared/notify.service';

/**
 * Campaign queues — the middle of the three selection layers.
 *
 * Each boundary is a **copy, not a link**: building a queue copies account rows
 * in, and nothing flows back. That is why there is no sync machinery anywhere
 * here, and why a locked queue can never be re-opened — "which version of the
 * queue did campaign 2 use?" has to stay answerable.
 */
@Component({
  selector: 'app-queues',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    IconComponent,
    FilterPanelComponent,
    SortableDirective, DataTableComponent],
  template: `
    <div class="head">
      <div>
        <div style="display:flex;align-items:center;gap:8px;">
          <h2>Campaign Queues</h2>
          <button class="act-btn" (click)="help.set(!help())"
                  [attr.aria-expanded]="help()" aria-controls="q-help"
                  [attr.aria-label]="help() ? 'Hide help' : 'About queues'"
                  title="How queues work">
            <app-icon name="info" [size]="15" />
          </button>
        </div>
        <p class="row-sub" *ngIf="!help()">
          A draft selection you can edit, promoted once into a campaign.
        </p>
      </div>
      <button class="btn btn-primary" (click)="creating.set(!creating())">
        <app-icon name="plus" [size]="13" />New queue
      </button>
    </div>

    <p id="q-help" class="row-sub" *ngIf="help()" style="max-width:72ch;margin-bottom:18px;">
      A queue <strong>copies</strong> accounts in from one or more lists. New imports into a source
      list never appear here, and status changes there never propagate — the source is recorded as
      a provenance stamp with no behaviour.
      <br><br>
      <strong>Promotion locks the queue permanently.</strong> To make a variant, clone it into a new
      draft. Re-opening a promoted queue would make "which version fed campaign 2?" unanswerable,
      and that question gets asked precisely when something has gone wrong.
    </p>

    <div class="card" *ngIf="error()" style="border-color:var(--critical);margin-bottom:18px;">
      <strong style="color:var(--critical);">{{ error() }}</strong>
    </div>

    <div class="card" *ngIf="creating()" style="margin-bottom:18px;max-width:520px;">
      <div style="display:flex;flex-direction:column;gap:12px;">
        <label style="display:flex;flex-direction:column;gap:6px;font-size:.84rem;">Label
          <input class="field" [(ngModel)]="draft.label" placeholder="Sept EIA push — VP Eng">
        </label>
        <label style="display:flex;flex-direction:column;gap:6px;font-size:.84rem;">Description
          <input class="field" [(ngModel)]="draft.description"
                 placeholder="Series B SaaS with an articulated QA problem">
        </label>
        <label style="display:flex;flex-direction:column;gap:6px;font-size:.84rem;">Service
          <select class="field" [(ngModel)]="draft.service_id" (ngModelChange)="draft.icp_profile_id = ''">
            <option value="">Choose the service everyone is approached about…</option>
            <option *ngFor="let s of services()" [value]="s.id">{{ s.code }} — {{ s.name }}</option>
          </select>
        </label>
        <label style="display:flex;flex-direction:column;gap:6px;font-size:.84rem;">ICP
          <select class="field" [(ngModel)]="draft.icp_profile_id" [disabled]="!draft.service_id">
            <option value="">{{ draft.service_id && !icpsFor(draft.service_id).length ? 'No ICP is linked to this service' : 'Choose the ICP it is built for…' }}</option>
            <option *ngFor="let i of icpsFor(draft.service_id)" [value]="i.id">{{ i.name }}</option>
          </select>
          <span class="row-sub">Qualification and strategy for the campaign are scored against these.</span>
        </label>
        <div style="display:flex;gap:10px;">
          <button class="btn btn-primary" (click)="create()" [class.busy]="creatingBusy()"
                  [disabled]="!draft.label.trim() || !draft.service_id || !draft.icp_profile_id || creatingBusy()">
            <app-icon *ngIf="!creatingBusy()" name="check" [size]="13" />
            {{ creatingBusy() ? 'Creating…' : 'Create' }}
          </button>
          <button class="btn" (click)="creating.set(false)">Cancel</button>
        </div>
      </div>
    </div>

    <!-- Promotion is the one irreversible step on this screen: the queues it
         takes are locked forever, and a variant means cloning one. Said here
         rather than only in the confirm, because the panel is where the
         decision is actually made. -->
    <div class="queuepick" *ngIf="pendingPromote() as rows">
      <span>Promote <strong>{{ rows.length }}</strong> {{ rows.length === 1 ? 'queue' : 'queues' }} to outreach as</span>
      <input class="field" [(ngModel)]="promotion.label" placeholder="campaign name"
             aria-label="Campaign name">
      <!-- The campaign in LGM, read live. Picking it picks the cadence. -->
      <select class="field" [(ngModel)]="promotion.lgm_campaign_id" aria-label="La Growth Machine campaign">
        <option value="">choose the LGM campaign…</option>
        <option *ngFor="let c of lgmCampaigns()" [value]="c.id">
          {{ c.name }}{{ c.status ? ' · ' + c.status.toLowerCase() : '' }}{{ registeredFor(c.id) ? ' · registered' : '' }}
        </option>
      </select>
      <span class="row-sub" *ngIf="!lgmCampaigns().length">
        No campaigns came back from La Growth Machine — either no key is stored, or the account
        has none. Check the connection on the
        <a class="link" routerLink="/campaigns">Campaigns</a> screen.
      </span>
      <button class="btn btn-primary" (click)="confirmPromote()" [class.busy]="bulkBusy() === 'promote'"
              [disabled]="!promotion.label.trim() || !promotion.lgm_campaign_id || !!bulkBusy()">
        {{ bulkBusy() === 'promote' ? 'Promoting…' : 'Lock and create outreach' }}
      </button>
      <button class="btn" (click)="pendingPromote.set(null)">Cancel</button>
      <span class="row-sub">Locks these queues permanently. Everyone in them gets a sequence;
        nothing is drafted, approved or sent by this.</span>
    </div>

    <app-data-table
      table="queues"
      noun="queues"
      emptyText="No queues yet. Create one, then add accounts from a list."
      [columns]="columns"
      [data]="sortedQueues()"
      [sort]="sort()"
      (sortChange)="onSort($event)"
      [selectable]="true"
      [rowActions]="actions"
      [busyKey]="bulkBusy()"
      [busyText]="bulkBusy() === 'clone' ? 'Cloning…' : 'Deleting…'"
      (open)="openQueue($event)"
      (bulk)="onBulk($event)"
      (rowAction)="onBulk({ action: $event.action, rows: [$event.row], skipped: [] })"
      [cell]="queueCell">
    </app-data-table>
    <ng-template #queueCell let-row let-column="column" let-value="value">
      <ng-container [ngSwitch]="column.key">
        <ng-container *ngSwitchCase="'label'">
          <a [routerLink]="['/queues', row.id]" class="link">{{ row.label }}</a>
          <div class="row-sub" *ngIf="row.description">{{ row.description }}</div>
          <div class="row-sub" *ngIf="row.service_code">for {{ row.service_code }} · {{ row.icp_name }}</div>
        </ng-container>
        <span *ngSwitchCase="'status'" class="badge"
              [ngClass]="row.status === 'draft' ? 'badge-accent' : 'badge-neutral'">{{ value }}</span>
        <ng-container *ngSwitchDefault>{{ value }}</ng-container>
      </ng-container>
    </ng-template>
  `,
  styles: [
    `
      .actionmsg { margin: 6px 0; }
      .err { color: var(--critical); }
      td { white-space: normal; }
      .head { display: flex; justify-content: space-between; align-items: flex-start;
              gap: 20px; margin-bottom: 22px; }
      .head h2 { font-size: 1.15rem; margin-bottom: 4px; }
      .link { color: var(--accent); text-decoration: none; font-weight: 500; }
      .link:hover { text-decoration: underline; }
      .f { display: flex; flex-direction: column; gap: 4px; font-size: .78rem; }
      .f .field { min-width: 180px; }
      .f .narrow { min-width: 90px; }
      .f.chk { flex-direction: row; align-items: center; gap: 6px; }
    `,
  ],
})
export class QueuesComponent implements OnInit {
  /** A shape's blockers. A warning is not one — see `blockersOf`. */
  readonly blockersOf = blockersOf;

  private api = inject(PipelineService);
  private config = inject(ConfigService);
  private router = inject(Router);
  shapes = signal<CadenceShapeView[]>([]);
  /** Draft queues waiting on a campaign name and a cadence. */
  pendingPromote = signal<Queue[] | null>(null);
  promotion = { label: '', lgm_campaign_id: '' };
  lgmCampaigns = signal<LgmCampaignOption[]>([]);
  services = signal<Service[]>([]);
  icps = signal<IcpProfile[]>([]);

  /** ICPs linked to the chosen service — a campaign argues for one pairing. */
  icpsFor(serviceId: string): IcpProfile[] {
    const code = this.services().find((s) => s.id === serviceId)?.code;
    return code ? this.icps().filter((i) => i.service_codes.includes(code)) : [];
  }

  queues = signal<Queue[]>([]);
  loading = signal(true);
  error = signal<string | null>(null);
  creating = signal(false);
  creatingBusy = signal(false);
  /** The bulk action running now — clone or delete. */
  bulkBusy = signal<string | null>(null);
  help = signal(false);

  draft = { label: '', description: '', service_id: '', icp_profile_id: '' };

  // --- sorting and filtering ---
  //
  // Client-side: the queue list loads whole and is small. Sorting on the server
  // would be a round-trip and an endpoint allowlist for something the browser
  // can do instantly — and the rule is to sort where the data is complete.
  sort = signal<SortState>(NO_SORT);

  query = '';
  status = '';
  minAccounts: number | null = null;
  clonesOnly = false;
  /** Bumped on every filter edit so the derived view recomputes. */
  private revision = signal(0);

  private readonly accessors: Record<string, (q: Queue) => unknown> = {
    label: (q) => q.label,
    accounts: (q) => q.account_count,
    status: (q) => q.status,
    locked: (q) => q.locked_at,
  };

  /** The rows actually rendered: filtered, then sorted. */
  visible = computed(() => {
    this.revision();
    const min = this.minAccounts;
    const rows = this.queues().filter(
      (q) =>
        matchesText(q, this.query, [(r) => r.label, (r) => r.description ?? '']) &&
        matchesAny(q.status, this.status ? [this.status] : []) &&
        (min === null || Number.isNaN(min) || q.account_count >= min) &&
        (!this.clonesOnly || !!q.cloned_from_queue_id),
    );
    return sortRows(rows, this.sort(), this.accessors);
  });

  activeFilters = computed(() => {
    this.revision();
    return [
      this.query.trim(),
      this.status,
      this.minAccounts === null || Number.isNaN(this.minAccounts) ? '' : 'min',
      this.clonesOnly ? 'clones' : '',
    ].filter(Boolean).length;
  });

  filterSummary = computed(() => {
    this.revision();
    const parts: string[] = [];
    if (this.query.trim()) parts.push(`"${this.query.trim()}"`);
    if (this.status) parts.push(this.status);
    if (this.minAccounts !== null && !Number.isNaN(this.minAccounts)) {
      parts.push(`${this.minAccounts}+ accounts`);
    }
    if (this.clonesOnly) parts.push('clones only');
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
    this.status = '';
    this.minAccounts = null;
    this.clonesOnly = false;
    this.touch();
  }

  ngOnInit(): void {
    this.config.services().subscribe({ next: (s) => this.services.set(s.filter((x) => x.is_active)) });
    this.api.cadenceShapes(true).subscribe({ next: (s) => this.shapes.set(s) });
    this.api.lgmCampaigns().subscribe({
      next: (rows) => this.lgmCampaigns.set(rows),
      error: () => this.lgmCampaigns.set([]),
    });
    this.config.icpProfiles().subscribe({ next: (i) => this.icps.set(i) });
    this.load();
  }

  private confirm = inject(ConfirmService);
  private notify = inject(NotifyService);

  /** Sorted here; the shared table only filters. */
  sortedQueues = computed(() =>
    sortRows(this.queues(), this.sort(), {
      label: (q) => q.label,
      account_count: (q) => q.account_count,
      status: (q) => q.status,
      locked_at: (q) => q.locked_at,
      cloned: (q) => (q.cloned_from_queue_id ? 1 : 0),
    }),
  );

  readonly columns: ColumnDef[] = [
    { key: 'label', label: 'Queue', width: 300 },
    { key: 'account_count', label: 'Accounts', width: 100, numeric: true, filter: 'none' },
    { key: 'status', label: 'Status', width: 110, filter: 'enum' },
    {
      key: 'locked_at',
      label: 'Locked',
      width: 130,
      filter: 'none',
      value: (q) => (q.locked_at ? new Date(q.locked_at).toLocaleDateString() : '—'),
    },
    {
      key: 'cloned',
      label: 'Cloned',
      width: 100,
      filter: 'enum',
      defaultVisible: false,
      value: (q) => (q.cloned_from_queue_id ? 'clone' : 'original'),
    },
  ];

  /**
   * A draft is edited in place; a locked queue fed a campaign and is kept as
   * the record of what it was, so the only way to vary it is a clone.
   */
  readonly actions: RowAction[] = [
    {
      key: 'promote',
      label: 'Promote to outreach',
      can: (q) => q.status === 'draft' && q.account_count + (q.contact_count ?? 0) > 0,
      why: 'already promoted, or nobody in it',
    },
    {
      key: 'clone',
      label: 'Clone to a new draft',
      can: (q) => q.status === 'locked',
      why: 'a draft can be edited directly',
    },
    {
      key: 'delete',
      label: 'Delete queue',
      danger: true,
      can: (q) => q.status === 'draft',
      why: 'it fed a campaign and is kept',
    },
  ];

  openQueue(q: any): void {
    this.router.navigate(['/queues', q.id]);
  }


  /**
   * Lock the chosen queues and open one campaign fed by them.
   *
   * One campaign from several queues is what the server supports, and it
   * refuses a set built for different services or ICPs — a campaign argues for
   * one pairing, so that refusal is passed through rather than worked around.
   */
  /** The registration for an LGM campaign, where one exists yet. */
  registeredFor(lgmCampaignId: string): CadenceShapeView | undefined {
    return this.shapes().find((s) => s.lgm_campaign_id === lgmCampaignId);
  }

  confirmPromote(): void {
    const rows = this.pendingPromote();
    const label = this.promotion.label.trim();
    const lgmId = this.promotion.lgm_campaign_id;
    if (!rows || !label || !lgmId) return;
    const known = this.registeredFor(lgmId);
    if (known) {
      this.promoteWith(known.id, rows, label);
      return;
    }
    // First use of this campaign: register it on the way through. The steps
    // and their attributes are read from LGM, never typed.
    this.bulkBusy.set('promote');
    const campaign = this.lgmCampaigns().find((c) => c.id === lgmId);
    this.api.createCadenceShape({ lgm_campaign_id: lgmId, label: campaign?.name ?? 'Cadence' })
      .subscribe({
        next: (r) => {
          if (!r.shape_id) {
            this.bulkBusy.set(null);
            this.notify.error('That campaign could not be registered.', r.detail);
            return;
          }
          if (r.findings.length) {
            this.notify.warning(`Registered ${campaign?.name ?? 'the campaign'}, with findings.`, r.findings.join(' · '));
          }
          this.api.cadenceShapes(true).subscribe({ next: (s) => this.shapes.set(s) });
          this.promoteWith(r.shape_id, rows, label);
        },
        error: (err) => {
          this.bulkBusy.set(null);
          this.notify.error(
            'That campaign could not be registered.',
            apiError(err, 'The server refused.'),
          );
        },
      });
  }

  private promoteWith(cadenceShapeId: string, rows: any[], label: string): void {
    this.bulkBusy.set('promote');
    this.api
      .promote({
        label,
        queue_ids: rows.map((q) => q.id),
        cadence_shape_id: cadenceShapeId,
      })
      .subscribe({
        next: (campaign: any) => {
          this.bulkBusy.set(null);
          this.pendingPromote.set(null);
          this.notify.success(
            `${label} created with ${campaign.sequences} sequence(s).`,
            (campaign.notes ?? []).join(' · ') || 'Strategy and drafts come next.',
          );
          void this.router.navigate(['/campaigns', campaign.id]);
        },
        error: (err) => {
          this.bulkBusy.set(null);
          this.notify.error('Could not promote.', apiError(err, 'The server refused.'));
        },
      });
  }

  async onBulk(run: { action: RowAction; rows: any[]; skipped: any[] }): Promise<void> {
    const rows = run.rows as Queue[];
    if (!rows.length) return;
    if (run.action.key === 'promote') {
      // Asked in a panel rather than a confirm: a campaign needs a name and a
      // cadence, and both are decisions, not acknowledgements.
      this.promotion = { label: rows[0].label, lgm_campaign_id: '' };
      this.pendingPromote.set(rows);
      return;
    }
    if (run.action.key === 'clone') {
      this.runEach(rows, (q) => this.api.cloneQueue(q.id, `${q.label} (copy)`), 'Cloned', 'clone');
      return;
    }
    if (run.action.key !== 'delete') return;
    const one = rows.length === 1 ? rows[0] : null;
    const accounts = rows.reduce((n, q) => n + q.account_count, 0);
    const ok = await this.confirm.ask({
      title: one ? `Delete ${one.label}?` : `Delete ${rows.length} draft queues?`,
      body: `${one ? 'It has' : 'They have'} never fed a campaign. `
        + `${accounts} account${accounts === 1 ? '' : 's'} leave the queue and stay on their lists.`,
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    this.runEach(rows, (q) => this.api.deleteQueue(q.id), 'Deleted', 'delete');
  }

  /** One request per queue; one refusal is reported without costing the rest. */
  private runEach(rows: Queue[], call: (q: Queue) => any, verb: string, key: string): void {
    this.bulkBusy.set(key);
    forkJoin(
      rows.map((q) =>
        call(q).pipe(
          map(() => null),
          catchError((err) => of(apiError(err, 'refused'))),
        ),
      ),
    ).subscribe((results: any) => {
      this.bulkBusy.set(null);
      const failed = (results as (string | null)[]).filter((x) => x !== null) as string[];
      const done = results.length - failed.length;
      const noun = `queue${done === 1 ? '' : 's'}`;
      if (!failed.length) this.notify.success(`${verb} ${done} ${noun}.`);
      else this.notify[done ? 'warning' : 'error'](
        `${verb} ${done} ${noun} · ${failed.length} refused.`, failed[0]);
      this.load();
    });
  }

  create(): void {
    const label = this.draft.label.trim();
    this.creatingBusy.set(true);
    this.api.createQueue({ ...this.draft }).subscribe({
      next: () => {
        this.creatingBusy.set(false);
        this.notify.success(`Created ${label}.`);
        this.draft = { label: '', description: '', service_id: '', icp_profile_id: '' };
        this.creating.set(false);
        this.load();
      },
      error: (err) => {
        // The form stays open with what was typed; the reason is in the corner.
        this.creatingBusy.set(false);
        this.notify.error('Could not create the queue.', apiError(err, 'The server refused.'));
      },
    });
  }

  private load(): void {
    this.loading.set(true);
    this.api.queues().subscribe({
      next: (q) => {
        this.queues.set(q);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(apiError(err, 'Could not load queues.'));
      },
    });
  }
}
