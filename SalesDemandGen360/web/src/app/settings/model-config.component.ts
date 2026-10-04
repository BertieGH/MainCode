import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import {
  ConfigService,
  LlmConfig,
  LlmSpend,
  LlmSpendRow,
  ModelOption,
  ProviderAvailability,
  ProviderInfo,
} from '../core/config.service';
import { IconComponent } from '../shared/icon.component';
import { apiError } from '../shared/api-error';

const EFFORTS = ['low', 'medium', 'high', 'xhigh'];

/**
 * Per-stage model configuration.
 *
 * `docs/05` calls this route `/settings/prompts` and describes prompt templates
 * with named presets. Those do not exist yet — there is no prompt-template
 * table — so this screen is the half that is real: model, effort, token budget
 * and output contract per stage. Effort is the primary cost lever, and it is
 * tuned per stage rather than globally.
 */
@Component({
  selector: 'app-model-config',
  standalone: true,
  imports: [CommonModule, FormsModule, IconComponent, RouterLink],
  template: `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
      <h2 style="font-size:1.15rem;">Model configuration</h2>
      <button class="act-btn" (click)="help.set(!help())"
              [attr.aria-expanded]="help()" aria-controls="model-help"
              [attr.aria-label]="help() ? 'Hide help' : 'About model configuration'"
              title="How effort is used">
        <app-icon name="info" [size]="15" />
      </button>
    </div>
    <p id="model-help" class="row-sub" *ngIf="help()" style="max-width:72ch;margin-bottom:18px;">
      One model, tuned by <strong>effort</strong> — not a cascade of smaller models. Lower effort on
      a strong model generally beats higher effort on a weaker one, and a cascade forfeits prompt-cache
      reuse because caches are model-scoped.
      <br><br>
      Strategy runs at the highest effort because its gate is "would a senior BDE agree" — the
      hardest judgement in the pipeline. Extraction and evaluation sit lower because they are
      constrained transformations, not open reasoning. Tune per stage against gate metrics; never
      globally.
    </p>
    <div *ngIf="!help()" style="margin-bottom:14px;"></div>

    <div class="card" style="border-color:var(--warn);margin-bottom:18px;">
      <strong style="display:block;margin-bottom:4px;">
        Prompt text lives in git, not here.
      </strong>
      <span class="row-sub">
        <code>docs/05</code> specifies this route as prompt templates with named presets and
        reset-to-default. Each stage's instructions are in
        <code>app/services/instructions.py</code> instead — deliberately. A prompt change alters
        what every downstream artefact means, so it belongs in review and in a diff next to the
        output contract it has to satisfy, not in a text box.
        <br><br>
        What this screen edits is the <strong>model configuration</strong> each stage runs under:
        provider, model, effort, token budget and output contract. Editing writes a
        <strong>new version</strong> and activates it; the previous version is kept.
        <br><br>
        A stage can be pointed at a provider we have no adapter for. That is allowed and marked —
        it records an intention to switch. Until the adapter exists, that stage refuses to run
        rather than calling the wrong vendor.
        <br><br>
        <strong>Provider</strong> lists the vendors whose key has been verified, and
        <strong>Model</strong> lists the models you selected for that vendor on
        <a class="link" routerLink="/settings/setup">API settings</a>. Both are chosen there,
        beside the key they belong to.
      </span>
    </div>

    <div class="card" *ngIf="error()" style="border-color:var(--critical);margin-bottom:18px;">
      <strong style="color:var(--critical);">{{ error() }}</strong>
    </div>

    <div class="table-wrap">
      <table class="data">
        <thead>
          <tr>
            <th>Stage</th><th>Provider</th><th>Model</th><th>Effort</th><th>Max tokens</th>
            <th>Output contract</th><th class="actcol">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let c of configs()">
            <td>
              <code>{{ c.scenario }}</code>
              <div class="row-sub">
                v{{ c.version }}
                <span *ngIf="c.version > 1">· {{ c.version - 1 }} earlier version(s) kept</span>
              </div>
            </td>
            <td class="row-sub mono">
              <ng-container *ngIf="editing() !== c.scenario">
                {{ c.provider }}
                <!-- The whole point of showing provider separately: a stage can
                     be pointed at a vendor we cannot call yet, and that must be
                     visible here rather than discovered mid-run. -->
                <div class="row-sub" *ngIf="!c.runnable" style="color:var(--warn);">
                  no adapter — this stage will refuse
                </div>
              </ng-container>
              <!-- Only providers with a key the vendor accepted. A stage
                   pointed at a provider we cannot authenticate to fails on its
                   first real call, and the setting that caused it is three
                   screens away by then. -->
              <select *ngIf="editing() === c.scenario" class="field cell"
                      [(ngModel)]="edit.provider" (ngModelChange)="onProviderChange()"
                      [attr.aria-label]="'Provider for ' + c.scenario">
                <option *ngFor="let p of selectableProviders(c.provider)" [value]="p">
                  {{ providerLabel(p) }}
                </option>
              </select>
            </td>
            <td class="row-sub mono">
              <ng-container *ngIf="editing() !== c.scenario">
                {{ c.model }}
                <div class="row-sub" *ngIf="tierOf(c) as t" style="opacity:.75;">{{ t }}</div>
              </ng-container>
              <!-- A select when we ship a list for this provider, a free input
                   when we do not. A provider somebody added has no list to
                   offer, and refusing to let them type an id would make the
                   provider unusable the moment an adapter lands. -->
              <select *ngIf="editing() === c.scenario && modelsForEdit().length"
                      class="field cell-wide" [(ngModel)]="edit.model"
                      [attr.aria-label]="'Model for ' + c.scenario">
                <option *ngFor="let m of modelsForEdit()" [value]="m.id">
                  {{ m.label }}{{ m.tier ? ' · ' + m.tier : '' }}
                </option>
              </select>

              <!-- Cost is the decision; the model id is only how it is spelled.
                   Picking a tier keeps that decision legible when the ids
                   change under it, which they do. -->
              <div class="tiers" *ngIf="editing() === c.scenario && tiersForEdit().length">
                <button *ngFor="let t of tiersForEdit()" class="tier"
                        [class.on]="edit.model === t.id"
                        (click)="pickTier(t.id)"
                        [title]="t.notes ?? t.label">{{ t.tier }}</button>
              </div>
              <input *ngIf="editing() === c.scenario && !modelsForEdit().length"
                     class="field cell-wide" [(ngModel)]="edit.model"
                     placeholder="model id"
                     [attr.aria-label]="'Model for ' + c.scenario">
              <div class="row-sub" *ngIf="editing() === c.scenario && modelNote()">
                {{ modelNote() }}
              </div>
            </td>
            <td>
              <span *ngIf="editing() !== c.scenario" class="badge"
                    [ngClass]="effortClass(c.effort)">{{ c.effort }}</span>
              <select *ngIf="editing() === c.scenario" class="field cell"
                      [(ngModel)]="edit.effort" [attr.aria-label]="'Effort for ' + c.scenario">
                <option *ngFor="let e of efforts" [value]="e">{{ e }}</option>
              </select>
            </td>
            <td class="mono">
              <ng-container *ngIf="editing() !== c.scenario">{{ c.max_tokens }}</ng-container>
              <input *ngIf="editing() === c.scenario" class="field cell" type="number"
                     min="256" max="64000" step="256" [(ngModel)]="edit.max_tokens"
                     [attr.aria-label]="'Max tokens for ' + c.scenario">
            </td>
            <td class="row-sub mono">
              {{ c.output_contract }}
              <div class="row-sub" style="opacity:.75;">{{ c.thinking_mode }}</div>
            </td>
            <td class="actcol">
              <ng-container *ngIf="editing() === c.scenario">
                <button class="act-btn" (click)="saveEdit(c)"
                        aria-label="Save changes"
                        [title]="editBlocker() ?? 'Save — writes a new version of this stage'">
                  <app-icon name="check" [size]="15" />
                </button>
                <button class="act-btn" (click)="editing.set(null)"
                        aria-label="Cancel editing" title="Cancel">
                  <app-icon name="x" [size]="15" />
                </button>
              </ng-container>
              <button *ngIf="editing() !== c.scenario" class="act-btn" (click)="startEdit(c)"
                      [attr.aria-label]="'Edit ' + c.scenario"
                      [title]="'Edit ' + c.scenario + ' — writes a new version'">
                <app-icon name="edit" [size]="15" />
              </button>
            </td>
          </tr>
          <tr *ngIf="!loading() && configs().length === 0">
            <td colspan="7" class="row-sub" style="text-align:center;padding:22px;">
              No stage configuration yet.
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- What those settings actually cost. Put on this screen rather than its
         own, because effort and token budget are the levers and this is where
         they are pulled: a stage whose worst call dwarfs its average is
         misconfigured, and that is only visible next to the setting. -->
    <div style="display:flex;align-items:baseline;gap:10px;margin:26px 0 4px;">
      <h3 style="font-size:1rem;">What this has used</h3>
      <select class="field cell" [(ngModel)]="spendDays" (ngModelChange)="loadSpend()"
              aria-label="Period">
        <option [ngValue]="1">last 24 hours</option>
        <option [ngValue]="7">last 7 days</option>
        <option [ngValue]="30">last 30 days</option>
        <option [ngValue]="90">last 90 days</option>
      </select>
      <span class="spacer" style="flex:1"></span>
      <span class="row-sub" *ngIf="spend() as sp">
        {{ sp.calls }} call(s)<span *ngIf="sp.failed"> · {{ sp.failed }} failed</span>
      </span>
    </div>

    <p class="row-sub" *ngIf="spend() as sp" style="max-width:72ch;margin-bottom:10px;">
      {{ sp.note }}
    </p>

    <p class="row-sub" *ngIf="spend() as sp; else noSpend" style="margin-bottom:10px;">
      <strong>{{ sp.input_tokens | number }}</strong> in ·
      <strong>{{ sp.output_tokens | number }}</strong> out<span *ngIf="sp.cache_read_tokens">
      · {{ sp.cache_read_tokens | number }} read from cache</span>
    </p>
    <ng-template #noSpend>
      <p class="row-sub" style="margin-bottom:10px;">Nothing recorded yet for this period.</p>
    </ng-template>

    <div class="table-wrap" *ngIf="spend()?.by_stage?.length">
      <table class="data">
        <thead>
          <tr>
            <th>Stage</th><th>Model</th>
            <th style="text-align:right;">Calls</th>
            <th style="text-align:right;">Input</th>
            <th style="text-align:right;">Output</th>
            <th style="text-align:right;">Avg out</th>
            <th style="text-align:right;">Worst out</th>
            <th style="text-align:right;">Avg time</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let r of spend()!.by_stage">
            <td>
              <code>{{ r.scenario }}</code>
              <div class="row-sub" *ngIf="r.failed" style="color:var(--critical);">
                {{ r.failed }} failed
              </div>
            </td>
            <td class="row-sub mono">{{ r.model }}</td>
            <td style="text-align:right;">{{ r.calls | number }}</td>
            <td style="text-align:right;">{{ r.input_tokens | number }}</td>
            <td style="text-align:right;">{{ r.output_tokens | number }}</td>
            <td style="text-align:right;">{{ r.avg_output | number }}</td>
            <!-- Flagged when one call cost many times the average: that gap is
                 what runaway thinking looks like, and it is invisible in a mean. -->
            <td style="text-align:right;" [style.color]="runaway(r) ? 'var(--critical)' : null">
              {{ r.worst_output | number }}
              <span class="row-sub" *ngIf="runaway(r)" style="display:block;color:var(--critical);">
                {{ times(r) }}× the average
              </span>
            </td>
            <td style="text-align:right;" class="row-sub">{{ r.avg_ms | number }}ms</td>
          </tr>
        </tbody>
      </table>
    </div>
  `,
  styles: [
    `
      .tiers { display: flex; gap: 4px; margin-top: 6px; }
      .tier { font-size: .68rem; padding: 2px 7px; border-radius: 10px;
              border: 1px solid var(--line); background: transparent;
              color: var(--muted); cursor: pointer; }
      .tier.on { border-color: var(--accent); color: var(--accent); }
      .cell { width: 108px; padding: 4px 7px; font-size: .8rem; }
      .cell-wide { width: 170px; padding: 4px 7px; font-size: .8rem;
                   font-family: 'IBM Plex Mono', monospace; }
    `,
  ],
})
export class ModelConfigComponent implements OnInit {
  private api = inject(ConfigService);

  readonly efforts = EFFORTS;

  configs = signal<LlmConfig[]>([]);
  loading = signal(true);
  error = signal<string | null>(null);
  editing = signal<string | null>(null);
  help = signal(false);

  // --- spend ------------------------------------------------------------
  //
  // Tokens, never currency: a price is a fact about a contract with a vendor
  // and changes without notice, so the screen reports what was used and leaves
  // the arithmetic to whoever knows the rate.
  spend = signal<LlmSpend | null>(null);
  spendDays = 7;

  loadSpend(): void {
    this.api.llmSpend(this.spendDays).subscribe({
      next: (s) => this.spend.set(s.calls ? s : null),
      error: () => this.spend.set(null),
    });
  }

  /** One call costing many times the average is a configuration problem. */
  runaway(row: LlmSpendRow): boolean {
    return row.calls > 2 && row.avg_output > 0 && row.worst_output >= row.avg_output * 5;
  }

  times(row: LlmSpendRow): number {
    return Math.round(row.worst_output / Math.max(row.avg_output, 1));
  }

  providers = signal<ProviderInfo[]>([]);
  /** Read-only here. The shortlist is chosen on Integrations, beside the key. */
  availability = signal<ProviderAvailability[]>([]);
  /** Providers whose stored key the vendor actually accepted. */
  connected = signal<string[]>([]);

  edit = { provider: 'anthropic', model: '', effort: 'medium', max_tokens: 16000 };

  /**
   * The models this stage may be pointed at.
   *
   * The shortlist, not the catalogue — the catalogue is what the vendor sells
   * and the shortlist is what this installation allows. Offering a model that
   * saving would then reject is a dropdown that disagrees with the server.
   *
   * Catalogue entries carry a label and tier; ids added by hand carry only
   * themselves, and are listed rather than hidden.
   *
   * A method, not a `computed()`: `edit` is a plain object bound with ngModel,
   * so a computed over it tracks nothing and would never update.
   */
  modelsForEdit(): ModelOption[] {
    const allowed = this.enabledFor(this.edit.provider);
    const known = this.providers().find((p) => p.key === this.edit.provider)?.models ?? [];
    const byId = new Map(known.map((m) => [m.id, m]));
    return allowed.map(
      (id) =>
        byId.get(id) ?? {
          id,
          label: id,
          structured_output: true,
          effort: true,
          prompt_caching: false,
          tier: '',
          notes: null,
        },
    );
  }

  /** One model per tier for the provider being edited, in shortlist order. */
  tiersForEdit(): ModelOption[] {
    const seen = new Set<string>();
    return this.modelsForEdit().filter((m) =>
      !m.tier || seen.has(m.tier) ? false : (seen.add(m.tier), true),
    );
  }

  pickTier(modelId: string): void {
    this.edit.model = modelId;
  }

  /** The tier of a saved row's model, when we ship that provider's list. */
  tierOf(c: LlmConfig): string | null {
    return (
      this.providers()
        .find((p) => p.key === c.provider)
        ?.models.find((m) => m.id === c.model)?.tier ?? null
    );
  }

  modelNote(): string | null {
    const provider = this.providers().find((p) => p.key === this.edit.provider);
    if (!provider) return 'Not a provider we ship — the model id is not checked.';
    if (!provider.runnable) return `${provider.label} has no adapter yet; this stage will refuse.`;
    return provider.models.find((m) => m.id === this.edit.model)?.notes ?? null;
  }

  /**
   * Switching provider invalidates the model, so take that provider's first.
   *
   * Leaving the old one would point a stage at a model its new provider does
   * not have — which saves, and then fails at the first call.
   */
  onProviderChange(): void {
    const allowed = this.enabledFor(this.edit.provider);
    if (allowed.length && !allowed.includes(this.edit.model)) {
      this.edit.model = allowed[0];
    }
  }

  // --- the shortlist, chosen on Integrations ---

  private enabledFor(provider: string): string[] {
    return this.availability().find((p) => p.provider === provider)?.enabled ?? [];
  }

  /**
   * Providers this stage may be switched to.
   *
   * Those with a verified key, plus whatever this stage is already set to —
   * a key going invalid must not make an existing row unreadable, or the
   * dropdown silently rewrites a configuration nobody touched.
   */
  selectableProviders(current: string): string[] {
    const keys = [...this.connected()];
    if (current && !keys.includes(current)) keys.push(current);
    return keys;
  }

  providerLabel(key: string): string {
    return this.providers().find((p) => p.key === key)?.label ?? key;
  }

  private loadAvailability(): void {
    this.api.modelAvailability().subscribe({
      next: (a) => this.availability.set(a.providers),
      error: (err) =>
        this.error.set(apiError(err, 'Could not read the model list.')),
    });
  }

  private loadConnected(): void {
    this.api.credentials().subscribe({
      next: (creds) =>
        this.connected.set(
          creds
            .filter((c) => c.credential_type === 'api_key' && c.status === 'valid')
            .map((c) => c.provider),
        ),
      error: () => this.connected.set([]),
    });
  }

  ngOnInit(): void {
    this.load();
    this.loadAvailability();
    this.loadConnected();
    this.loadSpend();
    this.api.providers().subscribe({ next: (p) => this.providers.set(p) });
  }

  effortClass(effort: string): string {
    // xhigh reads as a cost warning rather than a good thing — it is the most
    // expensive setting in the system.
    return effort === 'xhigh' ? 'badge-warn' : effort === 'low' ? 'badge-neutral' : 'badge-accent';
  }

  startEdit(c: LlmConfig): void {
    this.editing.set(c.scenario);
    this.edit = {
      provider: c.provider,
      model: c.model,
      effort: c.effort,
      max_tokens: c.max_tokens,
    };
  }

  editBlocker(): string | null {
    if (!/^[a-z][a-z0-9_-]{1,39}$/.test(this.edit.provider.trim()))
      return 'Provider must be lowercase letters, digits, - or _, starting with a letter.';
    if (!this.edit.model.trim()) return 'A model id is required.';
    if (this.edit.max_tokens < 256) return 'Max tokens must be at least 256.';
    if (this.edit.max_tokens > 64000) return 'Max tokens caps at 64000 (streaming).';
    return null;
  }

  saveEdit(c: LlmConfig): void {
    if (this.editBlocker()) {
      this.error.set(this.editBlocker());
      return;
    }
    this.api
      .saveLlmConfig(c.scenario, {
        scenario: c.scenario,
        provider: this.edit.provider,
        model: this.edit.model,
        effort: this.edit.effort,
        max_tokens: this.edit.max_tokens,
        thinking_mode: c.thinking_mode,
        output_contract: c.output_contract,
      })
      .subscribe({
        next: (updated) => {
          this.configs.update((rows) =>
            rows.map((r) => (r.scenario === updated.scenario ? updated : r)),
          );
          this.editing.set(null);
        },
        error: (err) => this.error.set(apiError(err, 'Could not save.')),
      });
  }

  private load(): void {
    this.loading.set(true);
    this.api.llmConfigs().subscribe({
      next: (c) => {
        this.configs.set(c);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(apiError(err, 'Could not load model configuration.'));
      },
    });
  }
}
