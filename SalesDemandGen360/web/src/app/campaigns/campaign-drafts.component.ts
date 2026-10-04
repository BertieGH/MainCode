import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ArcView, DraftRow, PipelineService, StrategyBuild } from '../core/pipeline.service';
import { apiError } from '../shared/api-error';
import { ConfirmService } from '../shared/confirm.service';
import { BulkRun, DataTableComponent } from '../shared/data-table.component';
import { NotifyService } from '../shared/notify.service';
import { RunProgressComponent } from '../shared/run-progress.component';
import { RunItem, SequentialRun } from '../shared/sequential-run';
import { ColumnDef, RowAction } from '../shared/table-view';
import { RATING_COLUMNS, bandClass, gateClass } from '../shared/rating-columns';

/** The message inside a `{detail: {message}}` refusal, or a fallback. */
function refusal(err: unknown, fallback: string): string {
  const detail = (err as { error?: { detail?: { message?: string } | string } })?.error?.detail;
  if (detail && typeof detail === 'object' && detail.message) return detail.message;
  return apiError(err, fallback);
}

/**
 * Cadence drafts — every person in the campaign, the cadence chosen for them,
 * and where their drafts stand. Write drafts with AI (one call per person),
 * open a person to edit any touch, then save them for approval. The campaign is
 * approved on the Approval tab once people are saved.
 */
@Component({
  selector: 'app-campaign-drafts',
  standalone: true,
  imports: [CommonModule, RouterLink, DataTableComponent, RunProgressComponent],
  template: `
    <p class="row-sub" style="max-width:90ch;margin:4px 0 12px;">
      Each person's cadence was chosen at promotion — LGM owns the touch count and timing; drafting
      fills in the words. <strong>Write drafts</strong> is one AI call per person, from their strategy.
      Open a person to read and edit every touch, then <strong>Save for approval</strong>.
    </p>
    <p class="row-sub" style="color:var(--critical);" *ngIf="failed()">{{ failed() }}</p>

    <app-run-progress [run]="batch"></app-run-progress>

    <app-data-table
      table="campaign-drafts"
      noun="people"
      emptyText="No people in this campaign."
      [columns]="columns"
      [data]="rows()"
      [selectable]="true"
      [openable]="false"
      [rowActions]="actions"
      [busyKey]="working()"
      [busyText]="working() === 'write' ? 'Drafting…' : working() === 'force_strategy' ? 'Building strategy…' : 'Saving…'"
      [idOf]="idOf"
      [label]="labelOf"
      (bulk)="onBulk($event)"
      (rowAction)="onBulk({ action: $event.action, rows: [$event.row], skipped: [] })"
      [cell]="cell">
    </app-data-table>

    <ng-template #cell let-row let-column="column" let-value="value">
      <ng-container [ngSwitch]="column.key">
        <a *ngSwitchCase="'full_name'" href="" style="color:var(--accent);text-decoration:none;"
           (click)="$event.preventDefault(); openPerson.emit({ contact_id: row.contact_id, sequence_id: row.sequence_id })">{{ value }}</a>
        <a *ngSwitchCase="'account_name'" style="color:var(--accent);text-decoration:none;"
           [routerLink]="['/accounts', row.account_id]">{{ value }}</a>
        <span *ngSwitchCase="'qualification_band'" class="badge" [ngClass]="bandClass(row.qualification_band)">{{ value }}</span>
        <span *ngSwitchCase="'gate'" class="badge" [ngClass]="gateClass(row.gate)" [title]="row.gate_detail">{{ value }}</span>
        <span *ngSwitchCase="'state'" class="badge" [ngClass]="stateClass(row.state)">{{ value }}</span>
        <span *ngSwitchCase="'edited'" class="badge badge-accent" [hidden]="!row.edited">edited by you</span>
        <ng-container *ngSwitchDefault>{{ value }}</ng-container>
      </ng-container>
    </ng-template>
  `,
})
export class CampaignDraftsComponent implements OnChanges {
  @Input({ required: true }) campaignId = '';
  /** Bumped by the campaign page when something changed elsewhere. */
  @Input() refresh = 0;
  @Output() changed = new EventEmitter<void>();
  @Output() openPerson = new EventEmitter<{ contact_id: string; sequence_id: string }>();

  private api = inject(PipelineService);
  private notify = inject(NotifyService);
  private confirm = inject(ConfirmService);

  readonly batch = new SequentialRun();
  rows = signal<DraftRow[]>([]);
  failed = signal<string | null>(null);
  working = signal<string | null>(null);

  readonly bandClass = bandClass;
  readonly gateClass = gateClass;
  readonly idOf = (r: DraftRow) => r.sequence_id;
  readonly labelOf = (r: DraftRow) => r.full_name;

  readonly columns: ColumnDef[] = [
    { key: 'full_name', label: 'Person', width: 170 },
    { key: 'title', label: 'Title', width: 170, value: (r) => r.title ?? '—' },
    { key: 'account_name', label: 'Company', width: 140 },
    ...RATING_COLUMNS,
    {
      key: 'cadence', label: 'Cadence', width: 190, filter: 'enum',
      value: (r) => (r.cadence_label ? `${r.cadence_label} · ${r.cadence_touches} / ${r.cadence_days}d` : 'none selected'),
    },
    { key: 'has_strategy', label: 'Strategy', width: 100, filter: 'enum', value: (r) => (r.has_strategy ? 'built' : 'none') },
    { key: 'touch_count', label: 'Touches', width: 90, numeric: true, filter: 'none' },
    { key: 'state', label: 'Cadence drafts', width: 170, filter: 'enum', value: (r) => r.state_label },
    { key: 'edited', label: 'Edited', width: 120, filter: 'none', value: (r) => (r.edited ? 'yes' : '') },
  ];

  readonly actions: RowAction[] = [
    {
      // The way out of "needs a strategy first" without leaving this tab. It
      // ticks both overrides — pursue although the rules left them out, and
      // argue with no live signal — which is exactly what a rep means by
      // "draft them anyway". Both are recorded and read in approval.
      key: 'force_strategy',
      label: 'Build strategy (override)',
      row: true,
      bulk: true,
      can: (r) => !r.has_strategy && r.state !== 'enrolled',
      why: 'they already have a strategy',
    },
    {
      key: 'write', label: 'Write drafts', row: true, bulk: true,
      can: (r) => r.has_strategy && r.state !== 'enrolled',
      why: 'needs a strategy first, and nothing enrolled can change',
    },
    {
      key: 'save', label: 'Save for approval', row: true, bulk: true,
      can: (r) => r.state === 'drafted',
      why: 'only people drafted and not yet saved',
    },
  ];

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['campaignId'] || changes['refresh']) this.load();
  }

  load(): void {
    if (!this.campaignId) return;
    this.api.campaignDrafts(this.campaignId).subscribe({
      next: (r) => {
        this.rows.set(r);
        this.failed.set(null);
      },
      error: (err) => this.failed.set(apiError(err, 'Could not load the cadence drafts.')),
    });
  }

  stateClass(state: string): string {
    if (state === 'approved' || state === 'enrolled') return 'badge-good';
    if (state === 'saved') return 'badge-accent';
    return 'badge-warn';
  }

  async onBulk(run: BulkRun): Promise<void> {
    const rows = run.rows as DraftRow[];
    if (!rows.length || this.working()) return;
    const items: RunItem[] = rows.map((r) => ({ id: r.sequence_id, name: r.full_name }));
    if (run.action.key === 'force_strategy') await this.forceStrategy(rows);
    if (run.action.key === 'write') await this.write(rows, items);
    if (run.action.key === 'save') await this.save(items);
  }

  private people(n: number): string {
    return `${n} ${n === 1 ? 'person' : 'people'}`;
  }

  /**
   * Build a strategy for people the sales rules left out, or whose company has
   * nothing live to cite. One AI call per company, as on the Strategy tab —
   * the difference is only that both overrides are ticked for everyone picked.
   */
  private async forceStrategy(rows: DraftRow[]): Promise<void> {
    const byAccount = new Map<string, { item: RunItem; contacts: string[] }>();
    for (const r of rows) {
      const found = byAccount.get(r.account_id) ?? {
        item: { id: r.account_id, name: r.account_name },
        contacts: [],
      };
      found.contacts.push(r.contact_id);
      byAccount.set(r.account_id, found);
    }
    const companies = [...byAccount.values()];
    const ok = await this.confirm.ask({
      title: `Build strategy for ${this.people(rows.length)}, overriding the rules?`,
      body:
        'Pursues them although the sales rules left them out — below the persona weight, over the '
        + 'per-company limit, or with no live signal about their company. One AI call per company. '
        + 'Both overrides are recorded on the strategy, and approval makes you read these sequences '
        + 'individually rather than sampling them.',
      confirmLabel: 'Build strategy',
    });
    if (!ok) return;

    this.working.set('force_strategy');
    let built = 0;
    const notes: string[] = [];
    const out = await this.batch.run<StrategyBuild>({
      verb: 'Building strategy',
      items: companies.map((c) => c.item),
      call: (id) =>
        this.api.buildCampaignStrategy(this.campaignId, {
          account_id: id,
          pursue_anyway: byAccount.get(id)?.contacts ?? [],
          allow_without_signal: byAccount.get(id)?.contacts ?? [],
        }),
      describe: (_, r) => ({
        kind: r.built ? 'success' : 'warning',
        text: r.built
          ? `v${r.version} for ${r.pursued.join(', ')}`
          : r.note || 'no strategy came back',
      }),
      onResult: (_, r) => {
        built += r.pursued.length;
        notes.push(...r.excluded.map((e) => `${e.name}: ${e.reason}`));
        return undefined;
      },
      onError: (item, err) => {
        notes.push(`${item.name}: ${refusal(err, 'could not build')}`);
        return (err as { status?: number })?.status === 409 ? 'stop' : undefined;
      },
      summary: () => `${built} built`,
    });
    this.finish(
      `Strategy built for ${this.people(built)}${out.cancelled ? ' (stopped)' : ''}. `
        + 'Write their drafts next.',
      notes,
    );
  }

  private async write(rows: DraftRow[], items: RunItem[]): Promise<void> {
    const redraft = rows.filter((r) => r.touch_count > 0).length;
    const ok = await this.confirm.ask({
      title: `Write cadence drafts for ${this.people(items.length)}?`,
      body:
        'One AI call per person, from their strategy, filling every touch of their cadence.' +
        (redraft
          ? ` ${this.people(redraft)} already drafted will be rewritten — edits stay in each touch's history, and a saved or approved cadence goes back to drafting.`
          : ''),
      confirmLabel: 'Write drafts',
    });
    if (!ok) return;
    this.working.set('write');
    let done = 0;
    const notes: string[] = [];
    const out = await this.batch.run<ArcView>({
      verb: 'Drafting',
      items,
      call: (id) => this.api.writeDrafts(id),
      describe: (_, a) => ({ kind: 'success', text: `${a.touches.length} touches drafted` }),
      onResult: () => {
        done += 1;
        return undefined;
      },
      onError: (item, err) => {
        notes.push(`${item.name}: ${refusal(err, 'could not draft')}`);
        return (err as { status?: number })?.status === 409 && /model call/.test(String(refusal(err, ''))) ? 'stop' : undefined;
      },
      summary: () => `${done} drafted`,
    });
    this.finish(`Drafted ${done} of ${this.people(items.length)}${out.cancelled ? ' (stopped)' : ''}.`, notes);
  }

  private async save(items: RunItem[]): Promise<void> {
    this.working.set('save');
    let done = 0;
    const notes: string[] = [];
    const out = await this.batch.run<ArcView>({
      verb: 'Saving for approval',
      items,
      call: (id) => this.api.saveDrafts(id),
      describe: () => ({ kind: 'success', text: 'saved for approval' }),
      onResult: () => {
        done += 1;
        return undefined;
      },
      onError: (item, err) => {
        notes.push(`${item.name}: ${refusal(err, 'could not save')}`);
        return undefined;
      },
      summary: () => `${done} saved`,
    });
    this.finish(`Saved ${done} of ${this.people(items.length)} for approval${out.cancelled ? ' (stopped)' : ''}.`, notes);
  }

  private finish(text: string, notes: string[]): void {
    this.working.set(null);
    this.load();
    this.changed.emit();
    if (notes.length) this.notify.warning(text, notes.join(' · '));
    else this.notify.success(text);
  }
}
