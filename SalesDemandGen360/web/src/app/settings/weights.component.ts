import { CommonModule } from '@angular/common';
import {
  Component, EventEmitter, Input, OnChanges, OnInit, Output, inject, signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ConfigService, IcpProfile, ScoringConfig } from '../core/config.service';
import { IconComponent } from '../shared/icon.component';
import { apiError } from '../shared/api-error';

const DIMENSIONS = ['fit', 'opportunity', 'buyer', 'commercial', 'intent', 'engagement'];

/**
 * What tilts a score, and how long an answer is reused before it is bought
 * again.
 *
 * This was the other half of a screen called "Sources & weights". The source
 * registry went to live beside the signal types that claim it; these three
 * sections came here, to the screen that already sets how the six dimensions
 * are weighed. One question per screen: where we look, against what it is
 * worth.
 *
 * Two multiplier tables rather than one, because market and size are separate
 * questions: a SaaS startup is both, and one column could only ever record it
 * as one of the two things it plainly was. See `docs/09` for the full history.
 *
 * **Industry rows are not editable here.** They come from the active ICP, so
 * the two lists cannot disagree: add an industry to an ICP and its row
 * appears. An "Add industry" button here would let somebody calibrate a
 * market they are not targeting.
 *
 * **Size rows are fixed**, because the band is derived from headcount rather
 * than chosen. `unknown` is deliberately absent: it is the absence of a
 * headcount, not a size, and giving it multipliers would score an unmeasured
 * account on a guess.
 *
 * The reuse window used to be here and is not: how often a source is read
 * again is a question about sources, and it moved to sit with them.
 */
@Component({
  selector: 'app-weights',
  standalone: true,
  imports: [CommonModule, FormsModule, IconComponent],
  template: `
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

  `,
  styles: [
    `
      .sec-head { display: flex; justify-content: space-between; align-items: center;
                  gap: 16px; margin-bottom: 4px; }
      /* The search logic, shown verbatim so it can be copied into a model and
         argued with. Scrolls rather than stretching the page: the research
         template runs to a few hundred lines. */
      .pre-wrap { white-space: pre-wrap; word-break: break-word; margin: 4px 0 12px;
                  font-size: .78rem; font-family: 'IBM Plex Mono', monospace;
                  max-height: 280px; overflow: auto; padding: 8px;
                  background: var(--bg-subtle); border: 1px solid var(--line);
                  border-radius: 4px; }
      .pill { display: inline-block; min-width: 1.4em; text-align: center;
              padding: 0 5px; margin-right: 4px; border-radius: 3px;
              background: var(--bg-subtle); border: 1px solid var(--line);
              font-family: 'IBM Plex Mono', monospace; font-size: .72rem; }
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
export class WeightsComponent implements OnInit, OnChanges {
  private api = inject(ConfigService);

  /** Held by Scoring, which embeds this. Never re-fetched here. */
  @Input() config: ScoringConfig | null = null;
  /** A new version was written — the parent reloads and passes it back down. */
  @Output() saved = new EventEmitter<void>();

  /** Working copies, cloned from the input so an abandoned edit does not
   *  quietly change the parent's object. */
  private industryMultipliers: Record<string, Record<string, number>> = {};
  private sizeMultipliers: Record<string, Record<string, number>> = {};

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

  icpIndustries = signal<string[]>([]);
  loading = signal(true);
  saving = signal(false);
  dirty = signal(false);
  error = signal<string | null>(null);
  help = signal(false);



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
          this.saved.emit();
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

  ngOnInit(): void {
    this.load();
  }

  private load(): void {
    this.loading.set(true);
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
    this.loading.set(false);
  }

  /**
   * The config comes from Scoring, which already holds it.
   *
   * Reading it here as well meant two requests for one object on a screen
   * that shows it once. The multipliers are cloned rather than bound, so an
   * edit abandoned without saving does not silently change the parent's copy.
   */
  ngOnChanges(): void {
    const c = this.config;
    if (!c) return;
    this.industryMultipliers = structuredClone(c.industry_multipliers ?? {});
    this.sizeMultipliers = structuredClone(c.size_multipliers ?? {});
    this.dirty.set(false);
  }
}
