import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  ConfigService, IcpProfile, ResearchSource, ScoringConfig, SignalType,
} from '../core/config.service';
import { IconComponent } from '../shared/icon.component';
import { apiError } from '../shared/api-error';

const DIMENSIONS = ['fit', 'opportunity', 'buyer', 'commercial', 'intent', 'engagement'];

/**
 * Research behaviour: what tilts the score, and which query families exist for
 * a signal type to claim.
 *
 * Two multiplier tables rather than one, because market and size are separate
 * questions: a SaaS startup is both, and one column could only ever record it
 * as one of the two things it plainly was. See `docs/09` for the full history.
 *
 * **Industry rows are not editable here.** They come from the active ICP, so
 * the two lists cannot disagree: add an industry under Org profile and its row
 * appears. An "Add industry" button on this screen would let somebody calibrate
 * a market they are not targeting.
 *
 * **Size rows are fixed**, because the band is derived from headcount rather
 * than chosen. `unknown` is deliberately absent: it is the absence of a
 * headcount, not a size, and giving it multipliers would score an unmeasured
 * account on a guess.
 *
 * **Sources** are the third section and the one that changed most. They used to
 * be a closed set in code, because a source the agents do not run is
 * indistinguishable from one that ran and found nothing. They are a registry
 * now — the key is still checked before a signal type may claim it, the
 * registry is just something a person can add to.
 *
 * What goes beside each one is the part that stops the list rotting: how often
 * it was read lately and what it produced. A registry only ever grows, and
 * without those two numbers on the same screen a source added in March is still
 * costing a read per account in December and nobody knows.
 */
@Component({
  selector: 'app-research',
  standalone: true,
  imports: [CommonModule, FormsModule, IconComponent],
  template: `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
      <h2 style="font-size:1.15rem;">Research</h2>
      <button class="act-btn" (click)="help.set(!help())"
              [attr.aria-expanded]="help()" aria-controls="research-help"
              [attr.aria-label]="help() ? 'Hide help' : 'About research settings'"
              title="What these control">
        <app-icon name="info" [size]="15" />
      </button>
    </div>
    <p id="research-help" class="row-sub" *ngIf="help()" style="max-width:72ch;margin-bottom:18px;">
      <strong>Industry multipliers</strong> tilt the six dimensions for a market — a regulated
      insurer turns on the buying committee more than a design agency does. Rows come from the
      industries named by your ICPs, so there is nothing to keep in step by hand.
      <br><br>
      <strong>Size multipliers</strong> do the same for company size, banded from headcount rather
      than judged. Both sets apply together and are <em>renormalised once</em>, so they change the
      balance between dimensions without inflating the score.
      <br><br>
      <strong>Sources</strong> are the places research reads — a company's own feed, news, job
      boards, a trade publication you add. Each one is read once per account per run, and
      everything it returns is interpreted against <em>every</em> signal type, so a leadership
      change mentioned in a job posting is still found. Which sources actually run for a list
      comes from its ICP, not from this screen: here you define what exists.
    </p>
    <div *ngIf="!help()" style="margin-bottom:14px;"></div>

    <div class="card" *ngIf="error()" style="border-color:var(--critical);margin-bottom:18px;">
      <strong style="color:var(--critical);">{{ error() }}</strong>
    </div>

    <!-- the reuse window -->
    <div class="card" style="margin-bottom:22px;">
      <h3 style="font-size:.98rem;margin-bottom:2px;">Reuse window</h3>
      <p class="row-sub" style="max-width:72ch;margin-bottom:10px;">
        Research younger than this is reused rather than paid for again. <em>Run research</em>
        skips any family already answered for an account inside the window — so a second list
        working the same company pays only for what is new. <em>Rerun research</em> on an account
        list ignores it. A family that failed is never reused. Saving writes a new version.
      </p>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
        <label style="display:flex;align-items:center;gap:8px;">
          <span class="row-sub">Reuse results younger than</span>
          <input class="field" type="number" min="1" max="365" step="1" style="width:90px;"
                 [(ngModel)]="reuseDays" aria-label="Reuse window in days">
          <span class="row-sub">days</span>
        </label>
        <button class="btn btn-primary" (click)="saveReuse()" [class.busy]="savingReuse()"
                [disabled]="savingReuse() || !reuseValid() || reuseDays === reuseSaved">
          <app-icon *ngIf="!savingReuse()" name="check" [size]="13" />
          {{ savingReuse() ? 'Saving…' : 'Save' }}
        </button>
        <span class="row-sub" *ngIf="!reuseValid()" style="color:var(--critical);">
          Between 1 and 365 days.
        </span>
        <span class="row-sub" *ngIf="reuseValid() && reuseDays === reuseSaved">
          {{ reuseVersion ? 'Version ' + reuseVersion : 'Default' }} · {{ reuseSaved }} days.
        </span>
      </div>
    </div>

    <!-- industry multipliers: rows are the ICP's industries -->
    <h3 style="font-size:.98rem;margin-bottom:4px;">Industry multipliers</h3>
    <p class="row-sub" style="margin-bottom:12px;max-width:70ch;">
      One row per industry in your ICP — edit that list under <strong>Org profile</strong> and these
      follow. ×1.00 leaves a dimension as the base weights set it; blank cells are ×1.00.
    </p>

    <div class="table-wrap" style="margin-bottom:12px;">
      <table class="data">
        <thead>
          <tr>
            <th>Industry</th>
            <th *ngFor="let d of dimensions" class="mono">{{ d }}</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let row of industryRows(); trackBy: trackRow"
              [class.orphan-row]="row.orphan">
            <td>
              <code>{{ row.label }}</code>
              <div class="row-sub" *ngIf="row.orphan" style="color:var(--critical);">
                no longer in your ICP
              </div>
            </td>
            <td *ngFor="let d of dimensions">
              <input class="field cell" type="number" min="0" max="5" step="0.05"
                     [ngModel]="multiplierFor(industry, row.key, d)"
                     (ngModelChange)="setMultiplier(industry, row.key, d, $event)"
                     [attr.aria-label]="'Multiplier for ' + row.label + ' ' + d">
            </td>
          </tr>
          <tr *ngIf="industryRows().length === 0">
            <td [attr.colspan]="dimensions.length + 1" class="row-sub"
                style="text-align:center;padding:20px;">
              No industries in any ICP yet — add some under ICP profiles and they appear here.
              Until then every account scores on the base weights.
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p class="row-sub" *ngIf="orphanCount() as n" style="color:var(--critical);max-width:64ch;">
      {{ n }} {{ n === 1 ? 'row is' : 'rows are' }} calibrated for
      {{ n === 1 ? 'an industry' : 'industries' }} no longer named by any ICP. Nothing scores against
      {{ n === 1 ? 'it' : 'them' }} — clear the values to drop
      {{ n === 1 ? 'the row' : 'the rows' }}, or put the industry back.
    </p>

    <!-- size multipliers: bands are derived, so the rows are fixed -->
    <h3 style="font-size:.98rem;margin:22px 0 4px;">Size multipliers</h3>
    <p class="row-sub" style="margin-bottom:12px;max-width:70ch;">
      Banded from <code>employee_count</code>, so nothing classifies an account and nothing has to be
      kept up to date. An account with no headcount carries no size multipliers at all — it scores on
      the base weights rather than on a guess.
    </p>

    <div class="table-wrap" style="margin-bottom:12px;">
      <table class="data">
        <thead>
          <tr>
            <th>Size</th>
            <th *ngFor="let d of dimensions" class="mono">{{ d }}</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let band of sizeBands">
            <td><code>{{ band.key }}</code> <span class="row-sub">{{ band.label }}</span></td>
            <td *ngFor="let d of dimensions">
              <input class="field cell" type="number" min="0" max="5" step="0.05"
                     [ngModel]="multiplierFor(size, band.key, d)"
                     (ngModelChange)="setMultiplier(size, band.key, d, $event)"
                     [attr.aria-label]="'Multiplier for ' + band.key + ' ' + d">
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div style="display:flex;gap:10px;align-items:center;margin-bottom:30px;">
      <button class="btn btn-primary" (click)="save()" [disabled]="saving() || !dirty()">
        <app-icon name="check" [size]="13" />
        {{ saving() ? 'Saving…' : 'Save as new scoring version' }}
      </button>
      <span class="row-sub">
        {{ dirty()
            ? 'Multipliers live on the scoring config, so this writes a new version of it.'
            : 'No changes.' }}
      </span>
    </div>

    <!-- the source registry -->
    <div class="sec-head" style="margin:28px 0 4px;">
      <h3 style="font-size:.98rem;">Sources</h3>
      <button class="btn" (click)="adding.set(!adding())">
        {{ adding() ? 'Cancel' : '+ Add a source' }}
      </button>
    </div>
    <p class="row-sub" style="margin-bottom:12px;max-width:76ch;">
      Where research looks. A signal type names the ones its fact usually lives in; an ICP decides
      which actually run for its lists. Everything a source returns is read against every signal
      type, so naming one here narrows what gets <em>opened</em>, never what gets found in it.
    </p>

    <!-- adding one: a search, always. A feed reader or a paid waterfall needs
         code behind it, and a row claiming one with nothing behind it is the
         silent coverage gap this registry exists to prevent. -->
    <div class="card" *ngIf="adding()" style="margin-bottom:16px;">
      <div class="form-grid">
        <label>Key
          <input class="field" [(ngModel)]="draft.key" placeholder="trade_press">
          <span class="row-sub">Lowercase and underscores. Permanent — coverage is filed under it.</span>
        </label>
        <label>Name
          <input class="field" [(ngModel)]="draft.label" placeholder="Trade press">
        </label>
        <label style="grid-column:1/-1;">What lives there
          <textarea class="field" rows="2" [(ngModel)]="draft.description"
                    placeholder="Sector publications, their newsletters and award lists."></textarea>
          <span class="row-sub">
            This is the brief a search runs. Describe the <em>place</em>, not a conclusion — what
            to conclude is every signal type's job, on everything this returns.
          </span>
        </label>
        <label>Reads about
          <select class="field" [(ngModel)]="draft.scope">
            <option value="company">companies</option>
            <option value="contact">people</option>
            <option value="both">both</option>
          </select>
        </label>
        <label>Re-read after
          <input class="field" type="number" min="1" max="3650" [(ngModel)]="draft.reuse_days"
                 placeholder="blank = the window above">
          <span class="row-sub">News is worth a week, filings a quarter.</span>
        </label>
        <label style="grid-column:1/-1;display:flex;align-items:center;gap:8px;flex-direction:row;">
          <input type="checkbox" [(ngModel)]="draft.support_only">
          <span class="row-sub">
            Can corroborate a signal but never create one on its own — like reviews, where a single
            complaint is noise and a repeated theme is evidence.
          </span>
        </label>
      </div>
      <div style="display:flex;gap:10px;align-items:center;margin-top:12px;">
        <button class="btn btn-primary" (click)="addSource()"
                [disabled]="savingSource() || !draftValid()">
          {{ savingSource() ? 'Adding…' : 'Add source' }}
        </button>
        <span class="row-sub" *ngIf="!draftValid()">A key, a name and a brief are needed.</span>
      </div>
    </div>

    <div class="table-wrap">
      <table class="data">
        <thead>
          <tr>
            <th>Source</th><th>Reads</th><th>What lives there</th>
            <th>Claimed by</th><th>Lately</th><th class="actcol">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let f of sources()" [class.retired-row]="f.status !== 'active'">
            <td>
              <code>{{ f.key }}</code>
              <div class="row-sub" *ngIf="editing() !== f.key">{{ f.label }}</div>
              <input *ngIf="editing() === f.key" class="field cell-input" [(ngModel)]="edit.label"
                     [attr.aria-label]="'Name for ' + f.key">
              <div class="row-sub" *ngIf="f.builtin" title="Shipped with the product">built in</div>
              <div class="row-sub" *ngIf="f.status !== 'active'" style="color:var(--warn);">
                {{ f.status }}
              </div>
              <!-- Beside the status, not in a tooltip: this is read by someone
                   about to turn the source back on, and the reason is the
                   whole input to that decision. -->
              <details class="why" *ngIf="f.status !== 'active' && f.status_reason">
                <summary class="row-sub">why</summary>
                <p class="row-sub">{{ f.status_reason }}</p>
              </details>
            </td>
            <td>
              <span class="badge" *ngFor="let s of f.scopes"
                    [ngClass]="s === 'company' ? 'badge-accent' : 'badge-warn'"
                    style="margin-right:4px;">{{ s }}</span>
              <div class="row-sub" *ngIf="f.kind !== 'search'">{{ kindWord(f.kind) }}</div>
            </td>
            <td class="row-sub brief">
              <ng-container *ngIf="editing() !== f.key">{{ f.description }}</ng-container>
              <textarea *ngIf="editing() === f.key" class="field cell-input" rows="2"
                        [(ngModel)]="edit.description"
                        [attr.aria-label]="'What lives in ' + f.key"></textarea>
              <div *ngIf="f.support_only" style="color:var(--warn);margin-top:3px;">
                Supports a signal but never creates one on its own.
              </div>
            </td>
            <td class="row-sub mono">{{ feedsFor(f.key) || '— nothing yet' }}</td>
            <td class="row-sub">
              <ng-container *ngIf="f.attempts">
                {{ f.attempts }} read{{ f.attempts === 1 ? '' : 's' }} ·
                {{ f.evidence }} passage{{ f.evidence === 1 ? '' : 's' }}
                <div *ngIf="f.dead_weight" style="color:var(--warn);">
                  nothing found in any of them
                </div>
              </ng-container>
              <span *ngIf="!f.attempts">not read yet</span>
            </td>
            <td class="actcol">
              <ng-container *ngIf="editing() !== f.key">
                <button class="act-btn" (click)="startEdit(f)" title="Edit"
                        [attr.aria-label]="'Edit ' + f.key">
                  <app-icon name="edit" [size]="15" />
                </button>
                <button class="act-btn" *ngIf="f.status === 'active'" (click)="setStatus(f, 'paused')"
                        title="Stop reading this, reversibly"
                        [attr.aria-label]="'Pause ' + f.key">
                  <app-icon name="pause" [size]="15" />
                </button>
                <button class="act-btn" *ngIf="f.status === 'paused'" (click)="setStatus(f, 'active')"
                        title="Read it again" [attr.aria-label]="'Resume ' + f.key">
                  <app-icon name="play" [size]="15" />
                </button>
              </ng-container>
              <ng-container *ngIf="editing() === f.key">
                <button class="act-btn" (click)="saveEdit(f)" title="Save"
                        [attr.aria-label]="'Save ' + f.key">
                  <app-icon name="check" [size]="15" />
                </button>
                <button class="act-btn" (click)="editing.set(null)" title="Cancel"
                        [attr.aria-label]="'Cancel editing ' + f.key">
                  <app-icon name="x" [size]="15" />
                </button>
              </ng-container>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="row-sub" style="margin-top:10px;max-width:76ch;">
      A source is retired rather than deleted: its key is written into every coverage row that
      records reading it, and a report that cannot resolve one prints a bare key where a name
      should be.
    </p>
  `,
  styles: [
    `
      .sec-head { display: flex; justify-content: space-between; align-items: center;
                  gap: 16px; margin-bottom: 4px; }
      .cell { width: 74px; padding: 4px 7px; font-size: .8rem;
              font-family: 'IBM Plex Mono', monospace; text-align: right; }
      .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
      .form-grid label { display: flex; flex-direction: column; gap: 4px; font-size: .84rem; }
      td.brief { white-space: normal; max-width: 300px; }
      .retired-row { opacity: .6; }
      .why > summary { cursor: pointer; color: var(--accent); }
      .why p { margin: 4px 0 0; max-width: 48ch; }
      .cell-input { width: 100%; padding: 4px 7px; font-size: .8rem; }
    `,
  ],
})
export class ResearchComponent implements OnInit {
  private api = inject(ConfigService);

  readonly dimensions = DIMENSIONS;

  /** Which table a cell belongs to. Two tables, one set of handlers. */
  readonly industry = 'industry' as const;
  readonly size = 'size' as const;

  /**
   * Fixed, and deliberately without `unknown`.
   *
   * The bands mirror `services/sizing.py`; an account with no headcount is
   * unmeasured rather than small, and giving that state multipliers would score
   * a guess. The names are ours — `enterprise_8_23` and `startup_5_11` are LGM
   * shapes, and mapping `large` onto one across the gap keeps the two
   * vocabularies from being coupled by coincidence.
   */
  readonly sizeBands = [
    { key: 'small', label: 'under 50' },
    { key: 'mid', label: '50–999' },
    { key: 'large', label: '1000+' },
  ];

  sources = signal<ResearchSource[]>([]);
  types = signal<SignalType[]>([]);
  adding = signal(false);
  savingSource = signal(false);
  editing = signal<string | null>(null);
  edit = { label: '', description: '' };
  draft = {
    key: '',
    label: '',
    description: '',
    scope: 'company' as 'company' | 'contact' | 'both',
    reuse_days: null as number | null,
    support_only: false,
  };
  icpIndustries = signal<string[]>([]);
  loading = signal(true);
  saving = signal(false);
  dirty = signal(false);
  error = signal<string | null>(null);
  help = signal(false);

  /** The reuse window as edited, and as last saved. */
  reuseDays = 30;
  reuseSaved = 30;
  reuseVersion = 0;
  savingReuse = signal(false);

  reuseValid(): boolean {
    const n = Number(this.reuseDays);
    return Number.isInteger(n) && n >= 1 && n <= 365;
  }

  saveReuse(): void {
    this.savingReuse.set(true);
    this.api.saveResearchSettings(Number(this.reuseDays)).subscribe({
      next: (s) => {
        this.savingReuse.set(false);
        this.reuseDays = this.reuseSaved = s.freshness_days;
        this.reuseVersion = s.version;
      },
      error: (err) => {
        this.savingReuse.set(false);
        this.error.set(apiError(err, 'Could not save the reuse window.'));
      },
    });
  }

  private config: ScoringConfig | null = null;
  private industryMultipliers: Record<string, Record<string, number>> = {};
  private sizeMultipliers: Record<string, Record<string, number>> = {};

  ngOnInit(): void {
    this.load();
  }

  /** Same normalisation as `scoring.normalise_industry`, for the same reason. */
  private key(industry: string): string {
    return industry.trim().replace(/\s+/g, ' ').toLowerCase();
  }

  private bag(table: 'industry' | 'size'): Record<string, Record<string, number>> {
    return table === 'industry' ? this.industryMultipliers : this.sizeMultipliers;
  }

  /**
   * One row per ICP industry, plus any calibrated industry the ICP no longer
   * names.
   *
   * A method rather than a computed: these read plain objects that are replaced
   * wholesale on load, and a computed over one never recomputes.
   */
  industryRows(): { key: string; label: string; orphan: boolean }[] {
    const fromIcp = this.icpIndustries().map((label) => ({
      key: this.key(label),
      label,
      orphan: false,
    }));
    const known = new Set(fromIcp.map((r) => r.key));
    // Kept, not dropped. An industry removed from the ICP still has values
    // somebody set, and silently discarding them on the next save would change
    // how the whole book scores without appearing in any diff a person reads.
    const orphans = Object.keys(this.industryMultipliers)
      .filter((k) => !known.has(k) && Object.keys(this.industryMultipliers[k] ?? {}).length)
      .sort()
      .map((k) => ({ key: k, label: k, orphan: true }));
    return [...fromIcp, ...orphans];
  }

  /**
   * Identity for `*ngFor`, and not optional here.
   *
   * `industryRows()` builds fresh objects on every change-detection pass, so
   * under the default identity tracking Angular tears down and rebuilds every
   * row — inputs included — on each pass. Rebuilding an `ngModel` input inside
   * a form schedules another pass, and the page spins. Tracking by the stable
   * key reuses the DOM instead, which also keeps focus while somebody is
   * typing a multiplier rather than dropping it after each keystroke.
   */
  trackRow = (_: number, row: { key: string }): string => row.key;

  orphanCount(): number {
    return this.industryRows().filter((r) => r.orphan).length;
  }

  multiplierFor(table: 'industry' | 'size', key: string, dimension: string): number {
    return this.bag(table)[key]?.[dimension] ?? 1;
  }

  setMultiplier(
    table: 'industry' | 'size', key: string, dimension: string, value: number,
  ): void {
    const n = Number(value);
    const bag = this.bag(table);
    bag[key] ??= {};
    if (!n || n === 1) {
      // x1.00 is the absence of a preference, so it is stored as absent rather
      // than as a row of ones nobody can distinguish from a deliberate choice.
      delete bag[key][dimension];
      if (!Object.keys(bag[key]).length) delete bag[key];
    } else {
      bag[key][dimension] = n;
    }
    this.dirty.set(true);
  }

  draftValid(): boolean {
    return (
      /^[a-z][a-z0-9_]*$/.test(this.draft.key.trim()) &&
      this.draft.label.trim().length > 0 &&
      this.draft.description.trim().length > 0
    );
  }

  /** Why a source has no coverage of its own, in words rather than a code. */
  kindWord(kind: string): string {
    if (kind === 'fetch') return 'read directly, no search';
    if (kind === 'provider') return 'a metered provider — never auto-run';
    if (kind === 'manual') return 'entered by a rep';
    return '';
  }

  addSource(): void {
    this.savingSource.set(true);
    const scopes =
      this.draft.scope === 'both' ? ['company', 'contact'] : [this.draft.scope];
    this.api
      .createResearchSource({
        key: this.draft.key.trim(),
        label: this.draft.label.trim(),
        description: this.draft.description.trim(),
        scopes,
        support_only: this.draft.support_only,
        reuse_days: this.draft.reuse_days ? Number(this.draft.reuse_days) : null,
      })
      .subscribe({
        next: () => {
          this.savingSource.set(false);
          this.adding.set(false);
          this.draft = {
            key: '', label: '', description: '', scope: 'company',
            reuse_days: null, support_only: false,
          };
          this.load();
        },
        error: (err) => {
          this.savingSource.set(false);
          this.error.set(apiError(err, 'Could not add that source.'));
        },
      });
  }

  startEdit(row: ResearchSource): void {
    this.editing.set(row.key);
    this.edit = { label: row.label, description: row.description };
  }

  saveEdit(row: ResearchSource): void {
    const changes: { label?: string; description?: string } = {};
    if (this.edit.label.trim() !== row.label) changes.label = this.edit.label.trim();
    if (this.edit.description.trim() !== row.description) {
      // The brief is what a search is told to read for, so editing it changes
      // what every later read of this source returns.
      changes.description = this.edit.description.trim();
    }
    if (!Object.keys(changes).length) {
      this.editing.set(null);
      return;
    }
    this.api.updateResearchSource(row.key, changes).subscribe({
      next: () => {
        this.editing.set(null);
        this.load();
      },
      error: (err) => {
        this.editing.set(null);
        this.error.set(apiError(err, 'Could not save that source.'));
      },
    });
  }

  /**
   * Pause or resume. Never a delete: the key is written into every coverage
   * row that recorded reading it.
   */
  setStatus(row: ResearchSource, status: string): void {
    this.api.updateResearchSource(row.key, { status }).subscribe({
      next: () => this.load(),
      error: (err) => this.error.set(apiError(err, 'Could not change that source.')),
    });
  }

  feedsFor(family: string): string {
    return this.types()
      .filter((t) => t.status === 'active' && t.produced_by.includes(family))
      .map((t) => t.key)
      .join(', ');
  }

  save(): void {
    if (!this.config) return;
    this.saving.set(true);
    this.api
      .saveScoring({
        dimension_weights: this.config.dimension_weights,
        industry_multipliers: this.industryMultipliers,
        size_multipliers: this.sizeMultipliers,
        persona_role_weights: this.config.persona_role_weights,
        band_cutoffs: this.config.band_cutoffs,
        man_view_enabled: this.config.man_view_enabled,
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.dirty.set(false);
          this.load();
        },
        error: (err) => {
          this.saving.set(false);
          this.error.set(
            apiError(
              err,
              'Could not save. The active scoring config may predate the six-dimension rule.',
            ),
          );
        },
      });
  }

  private load(): void {
    this.loading.set(true);
    this.api.researchSources().subscribe({
      next: (f) => {
        this.sources.set(f);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.error.set('Could not load research sources.');
      },
    });
    this.api.signalTypes().subscribe({ next: (t) => this.types.set(t) });
    this.api.researchSettings().subscribe({
      next: (s) => {
        this.reuseDays = this.reuseSaved = s.freshness_days;
        this.reuseVersion = s.version;
      },
      error: () => undefined,
    });
    // The industry rows are the ICPs' industries, so this screen reads them
    // rather than keeping a second list that could disagree.
    //
    // The **union** across every defined profile: an industry named by any ICP
    // is one accounts will be scored against, so it needs a multiplier row.
    // Profiles with no definition contribute nothing — they describe nobody.
    this.api.icpProfiles().subscribe({
      next: (rows: IcpProfile[]) => {
        const seen = new Set<string>();
        for (const row of rows) {
          const listed = row.definition?.['industries'];
          if (!Array.isArray(listed)) continue;
          for (const v of listed) if (typeof v === 'string' && v.trim()) seen.add(v);
        }
        this.icpIndustries.set([...seen]);
      },
      error: () => undefined,
    });
    this.api.getScoring().subscribe({
      next: (c) => {
        this.config = c;
        this.industryMultipliers = structuredClone(c.industry_multipliers ?? {});
        this.sizeMultipliers = structuredClone(c.size_multipliers ?? {});
        this.dirty.set(false);
      },
      error: () => undefined,
    });
  }
}
