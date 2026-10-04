import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnInit, Output, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { ConfigService, IcpProfile, Service } from '../core/config.service';
import {
  CampaignPeople,
  CampaignPerson,
  PipelineService,
  StrategyBuild,
} from '../core/pipeline.service';
import { apiError } from '../shared/api-error';
import { ConfirmService } from '../shared/confirm.service';
import { BulkRun, DataTableComponent } from '../shared/data-table.component';
import { NotifyService } from '../shared/notify.service';
import { RunProgressComponent } from '../shared/run-progress.component';
import { RunItem, SequentialRun } from '../shared/sequential-run';
import { ColumnDef, RowAction } from '../shared/table-view';
import { DRAFT_STATE_COLUMN, draftStateClass } from '../shared/draft-state';
import { RATING_COLUMNS, bandClass, gateClass } from '../shared/rating-columns';

const DECISION: Record<string, string> = {
  pursue: 'pursue',
  below_threshold: 'below threshold',
  over_limit: 'over the limit',
  not_reachable: 'not reachable',
};

/** The message inside a `{detail: {message}}` refusal, or a fallback. */
function refusal(err: unknown, fallback: string): string {
  const detail = (err as { error?: { detail?: { message?: string } } })?.error?.detail;
  return detail?.message ?? apiError(err, fallback);
}

/**
 * Qualify and strategy — the campaign's people, against its service and ICP.
 *
 * Each person shows their company's score for this campaign, what the sales
 * rules decide by default, and the strategy built. Overrides are per person:
 * *pursue anyway* for someone the rules leave out, *allow without one* when
 * nothing live is known about their company. Both are recorded on the
 * strategy, and both send the sequence to be read in approval.
 */
@Component({
  selector: 'app-campaign-strategy',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, DataTableComponent, RunProgressComponent],
  template: `
    <p class="row-sub blocked" *ngIf="failed()">{{ failed() }}</p>

    <div class="card" *ngIf="view() && !view()!.ready" style="margin:6px 0 14px;max-width:760px;">
      <p class="row-sub" style="margin-bottom:10px;">{{ view()!.blocked }}</p>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;">
        <select class="field" [(ngModel)]="pick.service_id" (ngModelChange)="pick.icp_profile_id = ''" aria-label="Service">
          <option value="">Service…</option>
          <option *ngFor="let s of services()" [value]="s.id">{{ s.code }} — {{ s.name }}</option>
        </select>
        <select class="field" [(ngModel)]="pick.icp_profile_id" [disabled]="!pick.service_id" aria-label="ICP">
          <option value="">ICP…</option>
          <option *ngFor="let i of icpsFor(pick.service_id)" [value]="i.id">{{ i.name }}</option>
        </select>
        <button class="btn btn-primary" (click)="setTargets()" [class.busy]="working() === 'targets'"
                [disabled]="!pick.service_id || !pick.icp_profile_id || !!working()">
          Use for this campaign
        </button>
      </div>
    </div>

    <ng-container *ngIf="view()?.ready">
      <div class="cs-head">
        <span>For <strong>{{ view()!.service_code }}</strong> · ICP <strong>{{ view()!.icp_name }}</strong> v{{ view()!.icp_version }}</span>
        <span class="row-sub">
          By default a person is pursued at weight {{ view()!.threshold }} or more, at most {{ view()!.cap }} per company,
          with a live signal about their company. Tick an override to change that for one person.
          Select people, then build their strategy — one AI call per company. Click a name for their score, strategy and drafts.
        </span>
      </div>

      <app-run-progress [run]="batch"></app-run-progress>

      <app-data-table
        table="campaign-people"
        noun="people"
        emptyText="No people in this campaign."
        [columns]="columns"
        [data]="view()!.people"
        [selectable]="true"
        [openable]="false"
        [rowActions]="actions"
        [busyKey]="working()"
        [busyText]="working() === 'drafts' ? 'Drafting…' : 'Building…'"
        [idOf]="idOf"
        [label]="labelOf"
        (bulk)="onBulk($event)"
        (rowAction)="onBulk({ action: $event.action, rows: [$event.row], skipped: [] })"
        [cell]="cell">
      </app-data-table>
    </ng-container>

    <ng-template #cell let-row let-column="column" let-value="value">
      <ng-container [ngSwitch]="column.key">
        <a *ngSwitchCase="'full_name'" href="" class="link"
           (click)="$event.preventDefault(); openPerson.emit({ contact_id: row.contact_id, sequence_id: row.sequence_id })">{{ value }}</a>
        <a *ngSwitchCase="'account_name'" class="link" [routerLink]="['/accounts', row.account_id]">{{ value }}</a>
        <span *ngSwitchCase="'qualification_band'" class="badge" [ngClass]="bandClass(row.qualification_band)">{{ value }}</span>
        <span *ngSwitchCase="'gate'" class="badge" [ngClass]="gateClass(row.gate)" [title]="row.gate_detail">{{ value }}</span>
        <span *ngSwitchCase="'default_decision'" class="badge" [title]="row.decision_detail"
              [ngClass]="row.default_decision === 'pursue' ? 'badge-good' : 'badge-warn'">{{ value }}</span>
        <ng-container *ngSwitchCase="'pursue_anyway'">
          <label class="ovr" *ngIf="row.default_decision !== 'pursue'; else byRule">
            <input type="checkbox" [checked]="overrides().pursue.has(row.contact_id)" (change)="toggle('pursue', row.contact_id)"
                   [attr.aria-label]="'Pursue ' + row.full_name + ' anyway'"> pursue anyway
          </label>
          <ng-template #byRule><span class="row-sub">by the rules</span></ng-template>
        </ng-container>
        <ng-container *ngSwitchCase="'live_signals'">
          <label class="ovr" *ngIf="!row.live_signals; else live">
            <input type="checkbox" [checked]="overrides().allow.has(row.contact_id)" (change)="toggle('allow', row.contact_id)"
                   [attr.aria-label]="'Allow ' + row.full_name + ' without a live signal'"> {{ row.expired_signals ? 'none live (' + row.expired_signals + ' expired)' : 'none' }} · allow without one
          </label>
          <ng-template #live><span class="row-sub">{{ row.live_signals }} live</span></ng-template>
        </ng-container>
        <span *ngSwitchCase="'draft_state'" class="badge" [ngClass]="draftStateClass(row.draft_state)"
              [title]="row.touch_count ? row.touch_count + ' touches' + (row.edited ? ', edited by you' : '') : ''">
          {{ value }}
        </span>
        <span *ngSwitchCase="'strategy'" class="badge" [title]="row.problem_hypothesis || ''"
              [ngClass]="row.strategy_status ? (row.chosen_by_rep || row.without_live_trigger ? 'badge-warn' : 'badge-good') : 'badge-neutral'">
          {{ value }}
        </span>
        <ng-container *ngSwitchDefault>{{ value }}</ng-container>
      </ng-container>
    </ng-template>
  `,
  styles: [
    `
      .cs-head { display: flex; flex-direction: column; gap: 4px; margin: 4px 0 12px; }
      .cs-head .row-sub { max-width: 90ch; }
      .blocked { color: var(--critical); margin: 8px 0; }
      .ovr { display: inline-flex; gap: 5px; align-items: center; font-size: .78rem; cursor: pointer; }
      .link { color: var(--accent); text-decoration: none; }
    `,
  ],
})
export class CampaignStrategyComponent implements OnInit {
  @Input({ required: true }) campaignId = '';
  /** Emitted after a build, so the campaign page reloads approval and pre-flight. */
  @Output() changed = new EventEmitter<void>();
  /** A name was clicked: open the person's score, strategy and drafts. */
  @Output() openPerson = new EventEmitter<{ contact_id: string; sequence_id: string }>();
  /** Bumped by the campaign page when something changed elsewhere. */
  @Input() set refresh(n: number) {
    if (n && this.campaignId) this.load();
  }

  private api = inject(PipelineService);
  private config = inject(ConfigService);
  private notify = inject(NotifyService);
  private confirm = inject(ConfirmService);

  readonly batch = new SequentialRun();
  view = signal<CampaignPeople | null>(null);
  failed = signal<string | null>(null);
  working = signal<string | null>(null);
  services = signal<Service[]>([]);
  icps = signal<IcpProfile[]>([]);
  pick = { service_id: '', icp_profile_id: '' };
  /** Per-person overrides. A signal, so the bulk bar's counts follow a tick. */
  overrides = signal({ pursue: new Set<string>(), allow: new Set<string>() });

  readonly idOf = (p: CampaignPerson) => p.sequence_id;
  readonly labelOf = (p: CampaignPerson) => p.full_name;

  readonly columns: ColumnDef[] = [
    {
      key: 'full_name', label: 'Person', width: 170,
      // Said on the row itself. A withdrawn person used to read as an
      // ordinary one whose strategy simply would not build.
      value: (p) => (p.withdrawn ? `${p.full_name} · withdrawn` : p.full_name),
    },
    { key: 'title', label: 'Title', width: 180, value: (p) => p.title ?? '—' },
    { key: 'account_name', label: 'Company', width: 150 },
    ...RATING_COLUMNS,
    {
      key: 'default_decision', label: 'Default', width: 140, filter: 'enum',
      value: (p) =>
        p.withdrawn
          ? `withdrawn${p.withdraw_reason ? ' — ' + p.withdraw_reason : ''}`
          : (DECISION[p.default_decision] ?? p.default_decision),
    },
    { key: 'pursue_anyway', label: 'Override', width: 150, filter: 'none', value: () => '' },
    { key: 'live_signals', label: 'Live signals', width: 240, filter: 'none', value: (p) => p.live_signals },
    {
      key: 'strategy', label: 'Strategy', width: 150, filter: 'enum',
      value: (p) =>
        p.strategy_status ? (p.chosen_by_rep || p.without_live_trigger ? 'built · override' : 'built') : 'none',
    },
    DRAFT_STATE_COLUMN,
  ];

  readonly actions: RowAction[] = [
    {
      key: 'strategy',
      label: 'Build strategy',
      row: true,
      bulk: true,
      can: (p) =>
        !p.withdrawn &&
        (p.default_decision === 'pursue' || this.overrides().pursue.has(p.contact_id)) &&
        (p.live_signals > 0 || this.overrides().allow.has(p.contact_id)),
      // Withdrawal first: it is the answer whenever it applies, and an
      // override cannot undo it. Reinstating is a deliberate act elsewhere.
      why: 'withdrawn from this campaign, or needs an override — "pursue anyway" when below the rules, "allow without one" when no signal is live',
    },
    {
      // The next step, offered where the strategy was just built rather than
      // one tab away. Same call as the Cadence drafts tab makes.
      key: 'drafts',
      label: 'Write cadence drafts',
      row: true,
      bulk: true,
      can: (p) => !p.withdrawn && !!p.strategy_status && p.draft_state !== 'enrolled',
      why: 'withdrawn, or needs a strategy first — and nothing enrolled can change',
    },
  ];

  ngOnInit(): void {
    this.load();
  }

  toggle(kind: 'pursue' | 'allow', id: string): void {
    this.overrides.update((o) => {
      const next = new Set(o[kind]);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return { ...o, [kind]: next };
    });
  }

  readonly draftStateClass = draftStateClass;
  readonly bandClass = bandClass;
  readonly gateClass = gateClass;

  icpsFor(serviceId: string): IcpProfile[] {
    const code = this.services().find((s) => s.id === serviceId)?.code;
    return code ? this.icps().filter((i) => i.service_codes.includes(code)) : [];
  }

  load(): void {
    this.api.campaignPeople(this.campaignId).subscribe({
      next: (v) => {
        this.view.set(v);
        this.failed.set(null);
        if (!v.ready && !this.services().length) this.loadTargets();
      },
      error: (err) => this.failed.set(apiError(err, 'Could not load the campaign’s people.')),
    });
  }

  private loadTargets(): void {
    this.config.services().subscribe({ next: (s) => this.services.set(s.filter((x) => x.is_active)) });
    this.config.icpProfiles().subscribe({ next: (i) => this.icps.set(i) });
  }

  setTargets(): void {
    this.working.set('targets');
    this.api.setCampaignTargets(this.campaignId, this.pick).subscribe({
      next: (v) => {
        this.working.set(null);
        this.view.set(v);
        this.notify.success(`This campaign is for ${v.service_code} · ${v.icp_name}.`);
        this.changed.emit();
      },
      error: (err) => {
        this.working.set(null);
        this.notify.error('Could not set the service and ICP.', refusal(err, 'The server refused.'));
      },
    });
  }

  async onBulk(run: BulkRun): Promise<void> {
    const rows = run.rows as CampaignPerson[];
    if (!rows.length || this.working()) return;
    const companies: RunItem[] = [
      ...new Map(rows.map((p) => [p.account_id, { id: p.account_id, name: p.account_name }])).values(),
    ];
    if (run.action.key === 'strategy') await this.build(companies);
    if (run.action.key === 'drafts') await this.writeDrafts(rows);
  }

  /**
   * Write every touch for the people picked — one AI call each, from the
   * strategy just built. The Cadence drafts tab is where they are read and
   * edited; this only saves the trip back for the common case.
   */
  private async writeDrafts(rows: CampaignPerson[]): Promise<void> {
    const n = rows.length;
    const ok = await this.confirm.ask({
      title: `Write cadence drafts for ${n} ${n === 1 ? 'person' : 'people'}?`,
      body:
        'One AI call per person, filling every touch of their cadence from their strategy. '
        + 'Anyone already drafted is rewritten, and a saved or approved cadence goes back to '
        + 'drafting. Read and edit them on the Cadence drafts tab.',
      confirmLabel: 'Write drafts',
    });
    if (!ok) return;

    // Drafting is the dearest stage by wall clock — about half a minute per
    // person — so a hundred people took the better part of an hour when these
    // were issued one at a time from here.
    this.working.set('drafts');
    const names = new Map(rows.map((p) => [p.sequence_id, p.full_name]));

    this.api
      .writeDraftsBatch(this.campaignId, rows.map((p) => p.sequence_id))
      .subscribe({
        next: (r) => {
          this.working.set(null);
          this.load();
          this.changed.emit();
          const notes = Object.entries(r.errors).map(
            ([id, why]) => `${names.get(id) ?? 'someone'}: ${why}`,
          );
          const text = `Drafted ${r.drafted} of ${n} ${n === 1 ? 'person' : 'people'} · ${r.seconds}s.`;
          if (notes.length) this.notify.warning(text, notes.join(' · '));
          else this.notify.success(text);
        },
        error: (err) => {
          this.working.set(null);
          this.notify.error('Nothing was drafted.', refusal(err, 'The server refused.'));
        },
      });
  }

  private idsAt(accountId: string, set: Set<string>): string[] {
    return (this.view()?.people ?? [])
      .filter((p) => p.account_id === accountId && set.has(p.contact_id))
      .map((p) => p.contact_id);
  }

  private plural(n: number): string {
    return `${n} compan${n === 1 ? 'y' : 'ies'}`;
  }

  private async build(companies: RunItem[]): Promise<void> {
    const ok = await this.confirm.ask({
      title: `Build strategy for ${this.plural(companies.length)}?`,
      body:
        'One AI call per company, for everyone from it in this campaign whom the rules pursue or you ' +
        'ticked. Overrides are recorded and read in approval. A rebuild replaces the previous strategy.',
      confirmLabel: 'Build strategy',
    });
    if (!ok) return;

    // One request, run concurrently on the server. This used to be one call
    // per company issued from here, in order, so that a progress line could
    // count them — honest, and unusable at scale: sixty companies meant sixty
    // round trips end to end before drafting had begun.
    this.working.set('strategy');
    const ids = companies.map((c) => c.id);
    const names = new Map(companies.map((c) => [c.id, c.name]));

    this.api
      .buildCampaignStrategyBatch(this.campaignId, {
        account_ids: ids,
        pursue_anyway: ids.flatMap((id) => this.idsAt(id, this.overrides().pursue)),
        allow_without_signal: ids.flatMap((id) => this.idsAt(id, this.overrides().allow)),
      })
      .subscribe({
        next: (r) => {
          this.working.set(null);
          this.load();
          this.changed.emit();

          const pursued = r.results.reduce((n, x) => n + x.pursued.length, 0);
          const notes = [
            ...r.results.flatMap((x) =>
              x.excluded.map((e) => `${e.name}: ${e.reason}`),
            ),
            ...Object.entries(r.errors).map(
              ([id, why]) => `${names.get(id) ?? 'a company'}: ${why}`,
            ),
          ];
          const text =
            `Strategy built for ${pursued} ${pursued === 1 ? 'person' : 'people'} at ` +
            `${r.built} of ${this.plural(companies.length)} · ${r.seconds}s.`;
          if (notes.length) this.notify.warning(text, notes.join(' · '));
          else this.notify.success(text);
        },
        error: (err) => {
          this.working.set(null);
          this.notify.error(
            'No strategy was built.',
            refusal(err, 'The server refused.'),
          );
        },
      });
  }
}
