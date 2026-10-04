import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ConfigService, ScoringConfig } from '../core/config.service';
import { IconComponent } from '../shared/icon.component';

const DIMENSIONS = [
  ['fit', 'Is this the kind of company we sell to?'],
  ['opportunity', 'Is there a problem we can solve?'],
  ['buyer', 'Can we reach someone who can say yes?'],
  ['commercial', 'Can they afford it, and is the deal worth it?'],
  ['intent', 'Are they showing active interest?'],
  ['engagement', 'Have we already got traction?'],
] as const;

/**
 * The six dimensions, their weights, and where the bands fall.
 *
 * The running total is shown live because the weights are a **distribution**:
 * they must sum to 100 or the priority score stops reading as a percentage and
 * the band cut-offs quietly stop meaning what they were set to mean. The server
 * rejects a bad total; this screen makes it obvious before the round trip.
 */
@Component({
  selector: 'app-scoring',
  standalone: true,
  imports: [CommonModule, FormsModule, IconComponent],
  template: `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
      <h2 style="font-size:1.15rem;">Scoring</h2>
      <button class="act-btn" (click)="help.set(!help())"
              [attr.aria-expanded]="help()" aria-controls="scoring-help"
              [attr.aria-label]="help() ? 'Hide help' : 'About scoring'"
              title="How the roll-up works">
        <app-icon name="info" [size]="15" />
      </button>
    </div>
    <p id="scoring-help" class="row-sub" *ngIf="help()" style="max-width:72ch;margin-bottom:18px;">
      A model assesses each dimension against cited evidence; <strong>this page decides what each
      assessment is worth</strong>, and the roll-up itself is deterministic Python. That is what
      makes re-scoring the whole book after a change here a cheap batch job instead of thousands
      of model calls — and why any score can be explained afterwards.
      <br><br>
      The six weights are a <strong>distribution and must total 100</strong>. Doubling them all
      would rank accounts identically but double every score, so your priority threshold and band
      cut-offs would silently stop meaning what you set them to. Industry and size multipliers apply
      <em>on top</em> and are renormalised, so they shift the balance between dimensions without
      inflating the result.
    </p>
    <div *ngIf="!help()" style="margin-bottom:14px;"></div>

    <div class="card" *ngIf="error()" style="border-color:var(--critical);margin-bottom:18px;">
      <strong style="color:var(--critical);">{{ error() }}</strong>
    </div>

    <div class="card" style="max-width:820px;">
      <h3 style="font-size:.95rem;margin-bottom:4px;">Dimension weights</h3>
      <p class="row-sub" style="margin-bottom:14px;">
        A distribution across the six. Must total 100.
      </p>

      <div class="dim" *ngFor="let d of dimensions">
        <div>
          <strong style="font-size:.88rem;">{{ d[0] }}</strong>
          <div class="row-sub">{{ d[1] }}</div>
        </div>
        <input class="field" type="number" min="0" max="100" step="1"
               [ngModel]="weights[d[0]]"
               (ngModelChange)="setWeight(d[0], $event)"
               [attr.aria-label]="'Weight for ' + d[0]">
      </div>

      <div class="total" [class.total-bad]="total() !== 100">
        <span>Total</span>
        <strong class="mono">{{ total() }}</strong>
        <span class="row-sub" *ngIf="total() !== 100">
          must be 100 — {{ total() > 100 ? 'remove' : 'add' }} {{ diff() }}
        </span>
        <span class="row-sub" *ngIf="total() === 100">a valid distribution</span>
      </div>

      <h3 style="font-size:.95rem;margin:24px 0 4px;">Band cut-offs</h3>
      <p class="row-sub" style="margin-bottom:12px;">
        Inclusive: a high cut-off of 75 means a score of exactly 75 is High.
      </p>
      <div class="form-grid">
        <label>High at or above
          <input class="field" type="number" min="0" max="100" [(ngModel)]="cutoffs.high">
        </label>
        <label>Medium at or above
          <input class="field" type="number" min="0" max="100" [(ngModel)]="cutoffs.medium">
        </label>
      </div>

      <label class="fieldlab" style="display:block;margin-top:18px;max-width:60ch;">
        Minimum band to join a queue
        <select class="field" [(ngModel)]="minQueueBand" style="max-width:220px;">
          <option value="low">low — no restriction</option>
          <option value="medium">medium and above</option>
          <option value="high">high only</option>
        </select>
        <span class="row-sub" style="display:block;margin-top:4px;">
          Above <code>low</code>, an account with no qualification is refused too — "not
          qualified yet" is a different instruction from "too weak". Identity and human
          approval remain the other gates; nothing thin can reach a send regardless.
        </span>
      </label>

      <label class="toggle">
        <input type="checkbox" [(ngModel)]="manView">
        <span>
          Show the MAN view
          <span class="row-sub" style="display:block;">
            Money / Authority / Need, derived from commercial, buyer and opportunity. A lens on the
            six, never a separate judgement.
          </span>
        </span>
      </label>

      <div style="display:flex;gap:10px;align-items:center;margin-top:18px;">
        <button class="btn btn-primary" (click)="save()" [disabled]="!!blocker() || saving()">
          <app-icon name="check" [size]="13" />
          {{ saving() ? 'Saving…' : 'Save as new version' }}
        </button>
        <span class="row-sub" [style.color]="blocker() ? 'var(--warn)' : ''">
          {{ blocker() ?? 'Saving writes a new version and activates it.' }}
        </span>
      </div>
    </div>

    <h3 style="font-size:.98rem;margin:26px 0 10px;">Versions</h3>
    <div class="table-wrap">
      <table class="data">
        <thead>
          <tr><th>Version</th><th>Weights</th><th>Bands</th><th>Created</th><th>Status</th></tr>
        </thead>
        <tbody>
          <tr *ngFor="let v of versions()">
            <td class="mono">v{{ v.version }}</td>
            <td class="row-sub mono">{{ summarise(v.dimension_weights) }}</td>
            <td class="row-sub mono">
              H {{ v.band_cutoffs['high'] }} · M {{ v.band_cutoffs['medium'] }}
            </td>
            <td class="row-sub">{{ v.created_at | date: 'MMM d, y' }}</td>
            <td>
              <span class="badge" [ngClass]="v.is_active ? 'badge-good' : 'badge-neutral'">
                {{ v.is_active ? 'active' : 'superseded' }}
              </span>
            </td>
          </tr>
          <tr *ngIf="!loading() && versions().length === 0">
            <td colspan="5" class="row-sub" style="text-align:center;padding:22px;">
              No scoring config saved yet.
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  `,
  styles: [
    `
      .dim { display: flex; justify-content: space-between; align-items: center; gap: 16px;
             padding: 9px 0; border-bottom: 1px solid var(--line); }
      .dim input { width: 92px; text-align: right; font-family: 'IBM Plex Mono', monospace; }
      .total { display: flex; align-items: baseline; gap: 10px; padding: 12px 0 0; }
      .total strong { font-size: 1.05rem; }
      .total-bad strong { color: var(--warn); }
      .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
      .form-grid label { display: flex; flex-direction: column; gap: 5px; font-size: .84rem; }
      .toggle { display: flex; gap: 10px; align-items: flex-start; margin-top: 20px;
                font-size: .86rem; cursor: pointer; }
      .toggle input { margin-top: 3px; }
    `,
  ],
})
export class ScoringComponent implements OnInit {
  private api = inject(ConfigService);

  readonly dimensions = DIMENSIONS;

  versions = signal<ScoringConfig[]>([]);
  loading = signal(true);
  saving = signal(false);
  error = signal<string | null>(null);
  help = signal(false);

  weights: Record<string, number> = {
    fit: 20, opportunity: 20, buyer: 15, commercial: 15, intent: 20, engagement: 10,
  };
  cutoffs = { high: 75, medium: 50 };
  manView = false;
  /** The weakest band that may join a queue. `low` is no restriction. */
  minQueueBand: 'low' | 'medium' | 'high' = 'low';
  private industryMultipliers: Record<string, Record<string, number>> = {};
  private sizeMultipliers: Record<string, Record<string, number>> = {};
  private roleWeights: Record<string, number> = {};

  private weightsSignal = signal(0);
  total = computed(() => {
    this.weightsSignal();
    return round2(Object.values(this.weights).reduce((a, b) => a + (Number(b) || 0), 0));
  });
  diff = computed(() => round2(Math.abs(100 - this.total())));

  setWeight(dimension: string, value: number): void {
    this.weights[dimension] = Number(value) || 0;
    // A plain object is not reactive, so the running total has to be nudged.
    this.weightsSignal.update((n) => n + 1);
  }

  blocker(): string | null {
    if (this.total() !== 100) {
      return `Weights total ${this.total()} — they are a distribution and must total 100.`;
    }
    if (this.cutoffs.high <= this.cutoffs.medium) {
      return 'The high cut-off must sit above medium, or every Medium account also clears High.';
    }
    return null;
  }

  summarise(w: Record<string, number>): string {
    return DIMENSIONS.map(([d]) => `${d[0]}${w[d] ?? '–'}`).join(' ');
  }

  ngOnInit(): void {
    this.load();
  }

  save(): void {
    if (this.blocker()) return;
    this.saving.set(true);
    this.api
      .saveScoring({
        dimension_weights: this.weights,
        industry_multipliers: this.industryMultipliers,
        size_multipliers: this.sizeMultipliers,
        persona_role_weights: this.roleWeights,
        band_cutoffs: this.cutoffs,
        man_view_enabled: this.manView,
        min_queue_band: this.minQueueBand,
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.load();
        },
        error: (err) => {
          this.saving.set(false);
          this.error.set(detailOf(err) ?? 'Could not save the scoring config.');
        },
      });
  }

  private load(): void {
    this.loading.set(true);
    this.api.getScoring().subscribe({
      next: (c) => {
        // A config written before the six-dimension rule may be missing some,
        // so anything absent is filled with 0 rather than left undefined —
        // which would render an empty box and total to NaN.
        for (const [d] of DIMENSIONS) this.weights[d] = Number(c.dimension_weights[d] ?? 0);
        this.cutoffs = {
          high: Number(c.band_cutoffs['high'] ?? 75),
          medium: Number(c.band_cutoffs['medium'] ?? 50),
        };
        this.manView = c.man_view_enabled;
        // Anything the server has not heard of reads as no restriction, which
        // is the safe direction: a gate nobody set must not start refusing.
        const band = c.min_queue_band ?? 'low';
        this.minQueueBand = band === 'medium' || band === 'high' ? band : 'low';
        this.industryMultipliers = c.industry_multipliers ?? {};
        this.sizeMultipliers = c.size_multipliers ?? {};
        this.roleWeights = c.persona_role_weights ?? {};
        this.weightsSignal.update((n) => n + 1);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        if (err?.status !== 404) {
          this.error.set(detailOf(err) ?? 'Could not load the scoring config.');
        }
      },
    });
    this.api.scoringVersions().subscribe({
      next: (v) => this.versions.set(v),
      error: () => this.versions.set([]),
    });
  }
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/** FastAPI validation errors arrive as a list, not a string. */
function detailOf(err: unknown): string | null {
  const detail = (err as { error?: { detail?: unknown } })?.error?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: string };
    return first?.msg?.replace('Value error, ', '') ?? null;
  }
  return null;
}
