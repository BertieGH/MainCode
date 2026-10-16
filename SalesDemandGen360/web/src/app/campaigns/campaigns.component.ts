import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { CadenceShapeView, Campaign, LgmCampaignOption, PipelineService, blockersOf } from '../core/pipeline.service';
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

import { catchError, forkJoin, map, of } from 'rxjs';
import { DataTableComponent } from '../shared/data-table.component';
import { ColumnDef, RowAction } from '../shared/table-view';

import { AuthService } from '../core/auth.service';
import { ConfirmService } from '../shared/confirm.service';
import { NotifyService } from '../shared/notify.service';

/**
 * Campaigns, plus the cadence registrations they run on.
 *
 * A registered shape is a **mirror of LGM, not a source of truth**. The blocked
 * state on this screen is the one that matters: if LGM's campaign changed after
 * we last verified the mapping, our attribute map may now write copy into the
 * wrong step — and that failure is silent, because the message still sends, to
 * the right person, at a plausible time.
 */
@Component({
  selector: 'app-campaigns',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    IconComponent,
    FilterPanelComponent,
    SortableDirective, DataTableComponent],
  template: `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
      <h2 style="font-size:1.15rem;">Outreach</h2>
      <button class="act-btn" (click)="help.set(!help())"
              [attr.aria-expanded]="help()" aria-controls="camp-help"
              [attr.aria-label]="help() ? 'Hide help' : 'About campaigns'"
              title="How campaigns work">
        <app-icon name="info" [size]="15" />
      </button>
    </div>
    <p id="camp-help" class="row-sub" *ngIf="help()" style="max-width:72ch;margin-bottom:18px;">
      A campaign is created by promoting a queue, which locks it. Nothing sends until every thread
      is approved and every pre-flight check passes. After execute, the copy is frozen on the LGM
      lead — the only remaining levers are stopping one contact's sequence or the whole campaign.
      <br><br>
      A campaign that never reached LGM can be <strong>deleted</strong>, and its source queues
      unlock back to draft: the lock only exists to keep "which version fed this campaign?"
      answerable, and there is no longer a campaign to ask about. Once anything has been enrolled
      or sent, deletion is refused — that record outlives the campaign.
    </p>
    <div *ngIf="!help()" style="margin-bottom:14px;"></div>

    <div class="card" *ngIf="error()" style="border-color:var(--critical);margin-bottom:18px;">
      <strong style="color:var(--critical);">{{ error() }}</strong>
    </div>

    <app-data-table
      table="campaigns"
      noun="campaigns"
      emptyText="No campaigns yet. Promote a queue to create one."
      [columns]="columns"
      [data]="sortedCampaigns()"
      [sort]="sort()"
      (sortChange)="onSort($event)"
      [selectable]="true"
      [rowActions]="actions"
      [busyKey]="deleting() ? 'delete' : null"
      busyText="Deleting…"
      (open)="openCampaign($event)"
      (bulk)="onBulk($event)"
      (rowAction)="onBulk({ action: $event.action, rows: [$event.row], skipped: [] })"
      [cell]="campaignCell">
    </app-data-table>
    <ng-template #campaignCell let-row let-column="column" let-value="value">
      <ng-container [ngSwitch]="column.key">
        <a *ngSwitchCase="'label'" [routerLink]="['/campaigns', row.id]" class="link">{{ value }}</a>
        <span *ngSwitchCase="'status'" class="badge" [ngClass]="statusClass(row.status)">{{ value }}</span>
        <ng-container *ngSwitchDefault>{{ value }}</ng-container>
      </ng-container>
    </ng-template>

    <h3 style="font-size:.98rem;margin-bottom:4px;">Cadence registrations</h3>
    <p class="row-sub" style="max-width:72ch;margin-bottom:12px;">
      What we believe exists in LGM. Gen360 never authors a cadence — it selects a registered shape
      and fills its attribute slots. A blocked shape cannot enrol.
    </p>
    <!-- Read-only: Gen360 never authors a cadence (invariant 6), so there is
         nothing to select and nothing to act on here — only to find the
         blocked one. -->
    <app-data-table
      table="cadences"
      noun="shapes"
      emptyText="No cadence shapes registered."
      [columns]="shapeColumns"
      [data]="sortedShapes()"
      [sort]="shapeSort()"
      (sortChange)="onShapeSort($event)"
      [openable]="false"
      [rowActions]="shapeActions"
      [busyKey]="verifying()"
      busyText="Checking…"
      [idOf]="shapeId"
      [label]="shapeLabel"
      (rowAction)="onShapeAction($event.action.key, $any($event.row))"
      [cell]="shapeCell">
    </app-data-table>
    <div style="display:flex;gap:10px;align-items:center;margin:4px 0 12px;flex-wrap:wrap;">
      <button class="btn" (click)="openAdd()" [disabled]="adding()">
        <app-icon name="plus" [size]="13" />Add cadence from LGM
      </button>
      <span class="row-sub">
        The steps are read from the campaign in LGM — Gen360 never authors a cadence.
      </span>
    </div>

    <div class="queuepick" *ngIf="adding()">
      <select class="field" [(ngModel)]="newShape.lgm_campaign_id" (ngModelChange)="nameFromCampaign($event)"
              aria-label="LGM campaign">
        <option value="">choose the LGM campaign…</option>
        <option *ngFor="let c of lgmCampaigns()" [value]="c.id">
          {{ c.name }}{{ c.status ? ' · ' + c.status.toLowerCase() : '' }}{{ c.audience_name ? ' · ' + c.audience_name : '' }}
        </option>
      </select>
      <input class="field" [(ngModel)]="newShape.label" placeholder="name it here" aria-label="Cadence name">
      <button class="btn btn-primary" (click)="createShape()" [class.busy]="saving()"
              [disabled]="!newShape.lgm_campaign_id || !newShape.label.trim() || saving()">
        {{ saving() ? 'Reading LGM…' : 'Register' }}
      </button>
      <button class="btn" (click)="adding.set(false)">Cancel</button>
      <span class="row-sub">
        Everything is read from the campaign's templates: how many steps, which attribute each one
        sends, its channels and its audience. The schedule stays in LGM, which is the only place
        that knows it — nothing about timing is set here.
      </span>
    </div>

    <!-- A shape's registration: which LGM campaign it describes, and the
         audience that campaign runs over. Not the steps — those are LGM's. -->
    <div class="queuepick" *ngIf="editing() as shape">
      <span>Register <strong>{{ shape.label }}</strong> against</span>
      <!-- Picked from the account where we can: a 24-character hex id copied
           by eye is a registration pointing at the wrong sequence. -->
      <select class="field" *ngIf="lgmCampaigns().length" [(ngModel)]="registration.lgm_campaign_id"
              (ngModelChange)="adoptAudience($event)" aria-label="LGM campaign">
        <option value="">choose the LGM campaign…</option>
        <option *ngFor="let c of lgmCampaigns()" [value]="c.id">
          {{ c.name }}{{ c.status ? ' · ' + c.status.toLowerCase() : '' }}{{ c.audience_name ? ' · ' + c.audience_name : '' }}
        </option>
      </select>
      <input class="field" *ngIf="!lgmCampaigns().length" [(ngModel)]="registration.lgm_campaign_id"
             placeholder="LGM campaign id" aria-label="LGM campaign id">
      <input class="field" [(ngModel)]="registration.lgm_audience_name" placeholder="LGM audience name"
             aria-label="LGM audience name">
      <button class="btn btn-primary" (click)="saveRegistration()" [class.busy]="saving()"
              [disabled]="!registration.lgm_campaign_id.trim() || saving()">
        {{ saving() ? 'Saving…' : 'Save' }}
      </button>
      <button class="btn" (click)="editing.set(null)">Cancel</button>
      <span class="row-sub">
        Changing the campaign id clears the verification — check it against LGM afterwards. Leave the
        audience blank and <em>Check against LGM</em> will read it from the campaign.
      </span>
    </div>

    <ng-template #shapeCell let-row let-column="column" let-value="value">
      <ng-container [ngSwitch]="column.key">
        <ng-container *ngSwitchCase="'key'">
          <code>{{ row.key }}</code>
          <div class="row-sub">{{ row.label }}</div>
        </ng-container>
        <ng-container *ngSwitchCase="'enrolment'">
          <span class="badge" [ngClass]="blockersOf(row).length ? 'badge-warn' : 'badge-good'">{{ value }}</span>
          <div class="row-sub" *ngFor="let bk of row.blocks" style="margin-top:4px;">{{ bk.detail }}</div>
        </ng-container>
        <ng-container *ngSwitchDefault>{{ value }}</ng-container>
      </ng-container>
    </ng-template>
  `,
  styles: [
    `
      .actionmsg { margin: 6px 0; }
      .err { color: var(--critical); }
      td { white-space: normal; }
      .link { color: var(--accent); text-decoration: none; font-weight: 500; }
      .link:hover { text-decoration: underline; }
      .f { display: flex; flex-direction: column; gap: 4px; font-size: .78rem; }
      .f .field { min-width: 170px; }
      .f.chk { flex-direction: row; align-items: center; gap: 6px; }
    `,
  ],
})
export class CampaignsComponent implements OnInit {
  /** A shape's blockers. A warning is not one — see `blockersOf`. */
  readonly blockersOf = blockersOf;

  private api = inject(PipelineService);

  campaigns = signal<Campaign[]>([]);
  shapes = signal<CadenceShapeView[]>([]);

  // --- sorting and filtering ---
  //
  // Client-side: both lists load whole and are small. The rule is to sort where
  // the data is complete — a client-side sort over a paginated response sorts
  // one page and presents it as the whole list.
  sort = signal<SortState>(NO_SORT);
  shapeSort = signal<SortState>(NO_SORT);

  query = '';
  status = '';
  cadence = '';
  deletableOnly = false;
  /** Bumped on every filter edit so the derived view recomputes. */
  private revision = signal(0);

  private readonly accessors: Record<string, (c: Campaign) => unknown> = {
    label: (c) => c.label,
    cadence: (c) => c.cadence_shape_key,
    status: (c) => c.status,
  };

  private readonly shapeAccessors: Record<string, (s: CadenceShapeView) => unknown> = {
    key: (s) => s.key,
    touches: (s) => s.touch_count,
    verified: (s) => s.verified_at,
    lgm: (s) => s.lgm_status,
    // Blocked shapes first when ascending: a blocked cadence is the row worth
    // finding, and "ready" is the boring majority.
    enrolment: (s) => (blockersOf(s).length ? 0 : 1),
  };

  statuses = computed(() => distinct(this.campaigns(), (c) => c.status));
  cadences = computed(() => distinct(this.campaigns(), (c) => c.cadence_shape_key));

  visible = computed(() => {
    this.revision();
    const rows = this.campaigns().filter(
      (c) =>
        matchesText(c, this.query, [(r) => r.label]) &&
        matchesAny(c.status, this.status ? [this.status] : []) &&
        matchesAny(c.cadence_shape_key, this.cadence ? [this.cadence] : []) &&
        (!this.deletableOnly || this.deletable(c)),
    );
    return sortRows(rows, this.sort(), this.accessors);
  });

  visibleShapes = computed(() => sortRows(this.shapes(), this.shapeSort(), this.shapeAccessors));

  activeFilters = computed(() => {
    this.revision();
    return [
      this.query.trim(),
      this.status,
      this.cadence,
      this.deletableOnly ? 'deletable' : '',
    ].filter(Boolean).length;
  });

  filterSummary = computed(() => {
    this.revision();
    const parts: string[] = [];
    if (this.query.trim()) parts.push(`"${this.query.trim()}"`);
    if (this.status) parts.push(this.status.replace('_', ' '));
    if (this.cadence) parts.push(this.cadence);
    if (this.deletableOnly) parts.push('deletable');
    return parts.join(' · ');
  });

  /** ngModel writes to a plain field, which no signal is watching. */
  touch(): void {
    this.revision.update((n) => n + 1);
  }

  onSort(state: SortState): void {
    this.sort.set(state);
  }

  onShapeSort(state: SortState): void {
    this.shapeSort.set(state);
  }

  clearFilters(): void {
    this.query = '';
    this.status = '';
    this.cadence = '';
    this.deletableOnly = false;
    this.touch();
  }
  loading = signal(true);
  error = signal<string | null>(null);
  help = signal(false);

  private router = inject(Router);
  private confirm = inject(ConfirmService);
  private auth = inject(AuthService);
  private notify = inject(NotifyService);
  deleting = signal(false);

  sortedCampaigns = computed(() =>
    sortRows(this.campaigns(), this.sort(), {
      label: (c) => c.label,
      cadence_shape_key: (c) => c.cadence_shape_key,
      status: (c) => c.status,
    }),
  );

  sortedShapes = computed(() =>
    sortRows(this.shapes(), this.shapeSort(), {
      key: (x) => x.key,
      touch_count: (x) => x.touch_count,
      verified_at: (x) => x.verified_at,
      lgm_status: (x) => x.lgm_status,
      // Blocked first when ascending: a blocked cadence is the row worth finding.
      enrolment: (x) => (blockersOf(x).length ? 0 : 1),
    }),
  );

  readonly columns: ColumnDef[] = [
    { key: 'label', label: 'Campaign', width: 320 },
    { key: 'cadence_shape_key', label: 'Cadence', width: 180, filter: 'enum',
      value: (c) => c.cadence_shape_key ?? '—' },
    { key: 'status', label: 'Status', width: 150, filter: 'enum',
      value: (c) => (c.status as string).replace('_', ' ') },
  ];

  readonly shapeId = (s: CadenceShapeView) => s.key;
  readonly shapeLabel = (s: CadenceShapeView) => s.label;
  verifying = signal<string | null>(null);

  /** Read-only otherwise — invariant 6: Gen360 never authors a cadence. */
  readonly shapeActions: RowAction[] = [
    { key: 'verify', label: 'Check against LGM', row: true, bulk: false },
    {
      key: 'attach_audience',
      label: 'Give it an audience',
      row: true,
      bulk: false,
      can: (s: any) => !s.lgm_audience_name,
      why: 'it already runs over one',
    },
    { key: 'register', label: 'Edit LGM registration', row: true, bulk: false },
    { key: 'delete_shape', label: 'Delete shape', row: true, bulk: false, danger: true },
  ];

  editing = signal<CadenceShapeView | null>(null);
  saving = signal(false);
  registration = { lgm_campaign_id: '', lgm_audience_name: '' };
  lgmCampaigns = signal<LgmCampaignOption[]>([]);
  adding = signal(false);
  newShape = { lgm_campaign_id: '', label: '' };

  openRegistration(shape: CadenceShapeView): void {
    this.registration = {
      lgm_campaign_id: shape.lgm_campaign_id ?? '',
      lgm_audience_name: shape.lgm_audience_name ?? '',
    };
    this.editing.set(shape);
    this.loadLgmCampaigns();
  }

  /** Asked each time a panel opens: a campaign built a minute ago is the one
   *  somebody is here to register. Empty falls back to typing an id. */
  private loadLgmCampaigns(): void {
    this.api.lgmCampaigns().subscribe({
      next: (rows) => this.lgmCampaigns.set(rows),
      error: () => this.lgmCampaigns.set([]),
    });
  }

  /** Picking a campaign fills in the audience it actually runs over. */
  adoptAudience(campaignId: string): void {
    const picked = this.lgmCampaigns().find((c) => c.id === campaignId);
    if (picked?.audience_name) this.registration.lgm_audience_name = picked.audience_name;
  }

  openAdd(): void {
    this.newShape = { lgm_campaign_id: '', label: '' };
    this.adding.set(true);
    this.loadLgmCampaigns();
  }

  /** Named after the LGM campaign unless somebody types their own. */
  nameFromCampaign(campaignId: string): void {
    const picked = this.lgmCampaigns().find((c) => c.id === campaignId);
    if (picked && !this.newShape.label.trim()) this.newShape.label = picked.name;
  }

  createShape(): void {
    this.saving.set(true);
    const label = this.newShape.label.trim();
    this.api
      .createCadenceShape({
        lgm_campaign_id: this.newShape.lgm_campaign_id,
        label,
      })
      .subscribe({
        next: (r) => {
          this.saving.set(false);
          this.adding.set(false);
          this.ngOnInit();
          if (r.sound) this.notify.success(`${label} registered.`, r.detail);
          else this.notify.warning(`${label} registered with gaps.`, r.findings.join(' · '));
        },
        error: (err) => {
          this.saving.set(false);
          this.notify.error(
            'Could not register that cadence.',
            (err as { error?: { detail?: string } })?.error?.detail
              ?? apiError(err, 'The server refused.'),
          );
        },
      });
  }

  saveRegistration(): void {
    const shape = this.editing();
    if (!shape) return;
    this.saving.set(true);
    this.api
      .updateCadenceShape(shape.key, {
        lgm_campaign_id: this.registration.lgm_campaign_id.trim(),
        lgm_audience_name: this.registration.lgm_audience_name.trim(),
      })
      .subscribe({
        next: (updated) => {
          this.saving.set(false);
          this.editing.set(null);
          this.ngOnInit();
          this.notify.success(
            `${shape.label} points at ${updated.lgm_campaign_id}.`,
            updated.verified_at ? null : 'Check it against LGM to confirm its steps.',
          );
        },
        error: (err) => {
          this.saving.set(false);
          this.notify.error('Could not save that registration.', apiError(err, 'The server refused.'));
        },
      });
  }

  /**
   * Ask LGM what this campaign actually looks like now, and record it.
   *
   * The answer is worth more than a date: a campaign whose steps changed still
   * enrols, and writes our copy into whatever attribute the new step reads.
   */
  onShapeAction(key: string, shape: CadenceShapeView): void {
    if (key === 'verify') this.verifyShape(shape);
    if (key === 'register') this.openRegistration(shape);
    if (key === 'delete_shape') void this.deleteShape(shape);
    if (key === 'attach_audience') this.attachAudience(shape);
  }

  /**
   * Drop a registration nothing has used — the seeded placeholders, usually.
   *
   * The server refuses one a campaign or sequence points at, because what a
   * person actually received has to stay answerable; deactivating is the way
   * to retire those.
   */
  async deleteShape(shape: CadenceShapeView): Promise<void> {
    const ok = await this.confirm.ask({
      title: `Delete ${shape.label}?`,
      body:
        'Removes this cadence registration. Refused if any campaign or sequence has used it — '
        + 'those are deactivated instead, so what they ran stays answerable.',
      confirmLabel: 'Delete shape',
      danger: true,
    });
    if (!ok) return;
    this.api.deleteCadenceShape(shape.key).subscribe({
      next: () => {
        this.notify.success(`Deleted ${shape.label}.`);
        this.ngOnInit();
      },
      error: (err) =>
        this.notify.error(
          `Could not delete ${shape.label}.`,
          (err as { error?: { detail?: string } })?.error?.detail
            ?? apiError(err, 'The server refused.'),
        ),
    });
  }

  verifyShape(shape: CadenceShapeView): void {
    this.verifying.set('verify');
    this.api.verifyCadenceShape(shape.key).subscribe({
      next: (r) => {
        this.verifying.set(null);
        this.ngOnInit();
        if (!r.checked) this.notify.warning(`${shape.label} was not checked.`, r.detail);
        else if (r.sound) this.notify.success(`${shape.label} matches LGM.`, r.detail);
        else this.notify.warning(`${shape.label} does not match LGM.`, r.findings.join(' · '));
      },
      error: (err) => {
        this.verifying.set(null);
        this.notify.error('Could not check that shape.', apiError(err, 'The server refused.'));
      },
    });
  }

  /**
   * Give a campaign an audience to run over.
   *
   * Without one it cannot enrol anybody: a campaign runs over an audience and
   * writing a lead into it is the enrolment. LGM only allows the audience to
   * be set before the campaign's first launch, so a shape that needs this
   * usually needs it now.
   */
  attachAudience(shape: CadenceShapeView): void {
    this.verifying.set('attach_audience');
    this.api.attachAudience(shape.key).subscribe({
      next: (r) => {
        this.verifying.set(null);
        this.ngOnInit();
        this.notify.success(`${shape.label} now has an audience.`, r.detail);
      },
      error: (err) => {
        this.verifying.set(null);
        this.notify.error(
          'No audience was attached.',
          apiError(err, 'The server refused.'),
        );
      },
    });
  }

  readonly shapeColumns: ColumnDef[] = [
    { key: 'key', label: 'Shape', width: 240 },
    { key: 'touch_count', label: 'Touches', width: 130, numeric: true, filter: 'none',
      // The span is only shown where one was recorded before timing became
      // LGM's. "scheduled in LGM" is the truth for everything since.
      value: (x) => x.span_days ? `${x.touch_count} / ${x.span_days}d` : `${x.touch_count} steps` },
    { key: 'verified_at', label: 'Verified', width: 160, filter: 'none',
      value: (x) => (x.verified_at ? new Date(x.verified_at).toLocaleDateString() : 'never')
        + (x.verified_by ? ` · ${x.verified_by}` : '') },
    { key: 'lgm_status', label: 'LGM status', width: 130, filter: 'enum',
      value: (x) => x.lgm_status ?? '—' },
    { key: 'lgm_campaign_id', label: 'LGM campaign', width: 190, filter: 'none',
      value: (x) => x.lgm_campaign_id || 'not set' },
    { key: 'lgm_audience_name', label: 'LGM audience', width: 200, filter: 'enum',
      value: (x) => x.lgm_audience_name ?? 'not set' },
    { key: 'enrolment', label: 'Enrolment', width: 260, filter: 'enum',
      value: (x) => (blockersOf(x).length ? 'blocked' : x.blocks.length ? 'waiting' : 'ready') },
  ];

  /**
   * Deletable only before anything can have reached LGM — the same rule as
   * `deletable()`, which the server re-checks: a campaign can be executed
   * between this page rendering and the click.
   */
  readonly actions: RowAction[] = [
    {
      key: 'delete',
      label: 'Delete campaign',
      danger: true,
      can: (c) => this.deletable(c) && this.auth.can('delete_campaign'),
      why: this.auth.can('delete_campaign')
        ? 'something may already have been sent — stop it instead'
        : 'your role cannot delete campaigns',
    },
  ];

  openCampaign(c: any): void {
    this.router.navigate(['/campaigns', c.id]);
  }


  async onBulk(run: { action: RowAction; rows: any[]; skipped: any[] }): Promise<void> {
    if (run.action.key !== 'delete' || !run.rows.length) return;
    const rows = run.rows as Campaign[];
    const ok = await this.confirm.ask({
      title: rows.length === 1 ? `Delete ${rows[0].label}?` : `Delete ${rows.length} campaigns?`,
      body: 'Nothing has been sent. The queues they came from unlock and can be edited again.',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    this.deleting.set(true);
    forkJoin(
      rows.map((c) =>
        this.api.deleteCampaign(c.id).pipe(
          map(() => null),
          catchError((err) => of(apiError(err, 'refused'))),
        ),
      ),
    ).subscribe((results) => {
      this.deleting.set(false);
      const failed = results.filter((x) => x !== null) as string[];
      const done = results.length - failed.length;
      if (!failed.length) this.notify.success(`Deleted ${done} campaign${done === 1 ? '' : 's'}.`);
      // The server re-checks: a campaign can start sending between the page
      // rendering and the click, and then it is refused with the reason.
      else this.notify[done ? 'warning' : 'error'](
        `Deleted ${done} · ${failed.length} refused.`, failed[0]);
      this.ngOnInit();
    });
  }

  ngOnInit(): void {
    this.api.campaigns().subscribe({
      next: (c) => {
        this.campaigns.set(c);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(apiError(err, 'Could not load campaigns.'));
      },
    });
    this.api.cadenceShapes(true).subscribe({ next: (s) => this.shapes.set(s) });
  }

  /**
   * Before anything can have left this system.
   *
   * A hint, not the rule — the rule is on the server, which also checks for
   * enrolled sequences and execution records that this row cannot see.
   */
  deletable(c: Campaign): boolean {
    return c.status === 'draft' || c.status === 'pending_approval' || c.status === 'cancelled';
  }

  statusClass(status: string): string {
    if (status === 'executing') return 'badge-good';
    if (status === 'pending_approval') return 'badge-warn';
    if (status === 'cancelled') return 'badge-neutral';
    return 'badge-accent';
  }
}
