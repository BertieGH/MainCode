import { CommonModule } from '@angular/common';
import {
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnInit,
  Output,
  ViewChild,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  ConfigService,
  ModelInUse,
  ProviderAvailability,
  ProviderInfo,
} from '../core/config.service';
import { IconComponent } from '../shared/icon.component';
import { apiError } from '../shared/api-error';

/**
 * Entering a credential, and choosing what it may be used for.
 *
 * Its own component because it is opened from three places on the setup
 * screen — adding a provider to a slot, replacing a key, and editing a
 * provider's model list — and because the rules it has to hold are worth
 * testing in one place rather than three:
 *
 * * the secret is **cleared from component state** the moment it is stored. A
 *   value left in a bound field ends up in a component snapshot, a screenshot,
 *   or a browser autofill store;
 * * it is never rendered into the DOM, and the input is `type="password"`;
 * * the model shortlist saves **separately** from the value, because changing
 *   which models a key may drive should not require pasting the key again.
 */
@Component({
  selector: 'app-credential-form',
  standalone: true,
  imports: [CommonModule, FormsModule, IconComponent],
  template: `
    <div class="card form">
      <h3>{{ title }}</h3>

      <div style="display:flex;flex-direction:column;gap:12px;">
        <label class="fld">Provider
          <!-- Typeable, not a closed list. Which vendors a business buys from
               changes on a purchase order, not on a deploy. -->
          <input class="field" [attr.list]="listId" [(ngModel)]="draft.provider"
                 (ngModelChange)="onProviderChange()" autocomplete="off"
                 [placeholder]="placeholder()">
          <datalist [id]="listId">
            <option *ngFor="let p of suggestions()" [value]="p.key">{{ p.label }}</option>
          </datalist>
          <span class="row-sub bad" *ngIf="providerError()">{{ providerError() }}</span>
          <span class="row-sub" *ngIf="known() as k">
            {{ k.label }} —
            <span *ngIf="k.runnable">this build can run it.</span>
            <span *ngIf="!k.runnable">no adapter yet; a stage set to it will refuse.</span>
            <a class="link" *ngIf="k.console_url" [href]="k.console_url"
               target="_blank" rel="noopener">get a key ↗</a>
          </span>
        </label>

        <!-- Only asked for when we do not already know it. A provider we ship
             fills this in; one somebody adds has nowhere else to record where
             its keys come from. -->
        <label class="fld" *ngIf="!known()">
          Console link <span class="row-sub">optional — where this provider issues keys</span>
          <input class="field" [(ngModel)]="draft.console_url" autocomplete="off"
                 placeholder="https://…">
        </label>

        <label class="fld">Type
          <select class="field" [(ngModel)]="draft.credential_type">
            <option value="api_key">API key</option>
            <option value="token">Token</option>
            <option value="webhook_secret">Webhook secret</option>
            <option value="base_url">Base URL</option>
          </select>
        </label>

        <label class="fld">Value
          <!-- Deliberately NOT two-way bound. Angular reflects a banana-box
               binding into the DOM as an ng-reflect-model attribute in
               development builds, so binding a secret writes it into the
               markup — visible in devtools, in a DOM snapshot, and in any
               screenshot of one. Production builds strip those attributes,
               which is exactly what makes it a leak nobody notices.

               Read on input, cleared on save, never bound back. -->
          <input class="field" type="password" autocomplete="off" #valueInput
                 (input)="draft.value = valueInput.value"
                 placeholder="Pasted once, never shown again">
        </label>

        <div style="display:flex;gap:10px;align-items:center;">
          <button class="btn btn-primary" (click)="save()"
                  [disabled]="!draft.value || saving() || !!providerError()">
            {{ saving() ? 'Saving…' : 'Save credential' }}
          </button>
          <button class="btn" (click)="cancelled.emit()">Cancel</button>
          <span class="badge badge-good" *ngIf="saved()">Stored — input cleared</span>
        </div>
      </div>

      <!-- Which of this vendor's models the app may use. Beside the key
           because it is a property of the key: what a vendor sells is their
           fact, what you are willing to run is yours. -->
      <div class="models" *ngIf="llmProvider() as p">
        <strong>Models this app may use</strong>
        <p class="row-sub" style="max-width:62ch;margin:4px 0 8px;">
          These become the options in the <strong>Model</strong> column on Model config. A model a
          stage is already using cannot be unticked — it is shown with the stages holding it.
        </p>

        <label class="opt" *ngFor="let m of p.models">
          <input type="checkbox" [checked]="isEnabled(p.key, m.id)"
                 (change)="toggleModel(p.key, m.id)" [disabled]="isLocked(p.key, m.id)"
                 [attr.aria-label]="'Allow ' + m.id">
          <code>{{ m.id }}</code>
          <span class="row-sub" *ngIf="m.tier">{{ m.tier }}</span>
          <span class="row-sub" *ngIf="usedBy(p.key, m.id) as by">in use by {{ by }}</span>
        </label>

        <!-- Ids the catalogue does not know. Vendor ids drift. -->
        <label class="opt" *ngFor="let id of customFor(p.key)">
          <input type="checkbox" [checked]="true" (change)="toggleModel(p.key, id)"
                 [disabled]="isLocked(p.key, id)" [attr.aria-label]="'Allow ' + id">
          <code>{{ id }}</code><span class="row-sub">added by hand</span>
        </label>

        <div class="addrow">
          <input class="field" [(ngModel)]="customDraft" placeholder="another model id"
                 aria-label="Add a model id">
          <button class="btn" (click)="addCustom(p.key)" [disabled]="!customDraft.trim()">
            Add
          </button>
        </div>

        <div style="display:flex;gap:10px;align-items:center;margin-top:10px;">
          <button class="btn" (click)="saveModels(p.key)"
                  [disabled]="!modelsChanged(p.key) || savingModels()">
            {{ savingModels() ? 'Saving…' : 'Save model list' }}
          </button>
          <span class="row-sub" *ngIf="modelsSaved()">Saved.</span>
        </div>
      </div>

      <p class="row-sub bad" *ngIf="error()">{{ error() }}</p>
    </div>
  `,
  styles: [
    `
      .form { border-color: var(--accent); margin-top: 12px; }
      .form h3 { font-size: .95rem; margin-bottom: 12px; }
      .fld { display: flex; flex-direction: column; gap: 6px; font-size: .84rem; }
      .bad { color: var(--critical); }
      .link { color: var(--accent); text-decoration: none; margin-left: 6px; }
      .link:hover { text-decoration: underline; }
      .models { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--line); }
      .models strong { font-size: .86rem; }
      .opt { display: flex; gap: 8px; align-items: baseline; margin-bottom: 5px;
             font-size: .82rem; }
      .opt input[disabled] + code { opacity: .7; }
      .addrow { display: flex; gap: 8px; margin-top: 8px; align-items: center; }
      .addrow .field { flex: 1; }
    `,
  ],
})
export class CredentialFormComponent implements OnInit {
  private api = inject(ConfigService);

  /** Restricts the suggested providers. Omitted means every provider. */
  @Input() kind?: string;
  /** Pre-selects a provider — used when replacing a key or editing its models. */
  @Input() provider = '';
  @Input() title = 'Add or replace a credential';

  @Output() savedCredential = new EventEmitter<void>();
  @Output() cancelled = new EventEmitter<void>();

  /** Unique so two open forms cannot share a datalist. */
  readonly listId = `providers-${Math.random().toString(36).slice(2, 8)}`;

  providers = signal<ProviderInfo[]>([]);
  availability = signal<ProviderAvailability[]>([]);
  inUse = signal<ModelInUse[]>([]);

  saving = signal(false);
  saved = signal(false);
  savingModels = signal(false);
  modelsSaved = signal(false);
  error = signal<string | null>(null);
  known = signal<ProviderInfo | undefined>(undefined);
  providerError = signal<string | null>(null);

  customDraft = '';
  private draftEnabled: Record<string, string[]> = {};

  /** The password field, so it can be cleared without binding to it. */
  @ViewChild('valueInput') valueInput?: ElementRef<HTMLInputElement>;

  draft = { provider: '', credential_type: 'api_key', value: '', console_url: '' };

  ngOnInit(): void {
    this.draft.provider = this.provider;
    this.api.providers().subscribe({
      next: (p) => {
        this.providers.set(p);
        this.onProviderChange();
      },
    });
    this.api.modelAvailability().subscribe({
      next: (a) => {
        this.availability.set(a.providers);
        this.inUse.set(a.in_use);
      },
      error: (err) => this.error.set(apiError(err, 'Could not read the model list.')),
    });
  }

  /** Providers worth suggesting for this slot. */
  suggestions(): ProviderInfo[] {
    const all = this.providers();
    return this.kind ? all.filter((p) => p.kind === this.kind) : all;
  }

  placeholder(): string {
    const keys = this.suggestions().map((p) => p.key);
    return keys.length ? `${keys.join(', ')} — or type a new one` : 'provider key';
  }

  llmProvider(): ProviderInfo | undefined {
    const match = this.known();
    return match && match.kind === 'llm' ? match : undefined;
  }

  /**
   * The same shape the server enforces.
   *
   * Checked here as well because " Anthropic " and "anthropic" would become
   * two providers that look identical in the table and share no credential —
   * and a 422 after pasting a secret means pasting it again.
   */
  onProviderChange(): void {
    const value = this.draft.provider.trim();
    this.known.set(this.providers().find((p) => p.key === value));
    this.modelsSaved.set(false);
    this.providerError.set(
      !value || /^[a-z][a-z0-9_-]{1,39}$/.test(value)
        ? null
        : 'Lowercase letters, digits, - and _ only, starting with a letter.',
    );
  }

  save(): void {
    this.saving.set(true);
    this.saved.set(false);
    this.api
      .saveCredential({
        provider: this.draft.provider.trim(),
        credential_type: this.draft.credential_type,
        value: this.draft.value,
        console_url: this.draft.console_url.trim() || null,
      })
      .subscribe({
        next: () => {
          // Cleared immediately, from the component *and* the input element.
          // Only the component half would leave the secret sitting in the DOM
          // node with nothing bound to clear it.
          this.draft.value = '';
          if (this.valueInput) this.valueInput.nativeElement.value = '';
          this.saving.set(false);
          this.saved.set(true);
          this.savedCredential.emit();
        },
        error: (err) => {
          this.saving.set(false);
          this.error.set(apiError(err, 'Save failed.'));
        },
      });
  }

  // --- the model shortlist ---

  enabledFor(provider: string): string[] {
    if (this.draftEnabled[provider]) return this.draftEnabled[provider];
    return this.availability().find((p) => p.provider === provider)?.enabled ?? [];
  }

  customFor(provider: string): string[] {
    const known = new Set(
      (this.providers().find((p) => p.key === provider)?.models ?? []).map((m) => m.id),
    );
    return this.enabledFor(provider).filter((id) => !known.has(id));
  }

  isEnabled(provider: string, model: string): boolean {
    return this.enabledFor(provider).includes(model);
  }

  usedBy(provider: string, model: string): string | null {
    const hit = this.inUse().find((u) => u.provider === provider && u.model === model);
    return hit ? hit.scenarios.join(', ') : null;
  }

  /**
   * A model a stage is configured with cannot be unticked.
   *
   * Disabled rather than allowed-then-refused: the server rejects it either
   * way, and a checkbox that springs back after a round-trip teaches nothing
   * about why.
   */
  isLocked(provider: string, model: string): boolean {
    return this.isEnabled(provider, model) && this.usedBy(provider, model) !== null;
  }

  toggleModel(provider: string, model: string): void {
    if (this.isLocked(provider, model)) return;
    const next = [...this.enabledFor(provider)];
    const at = next.indexOf(model);
    if (at >= 0) next.splice(at, 1);
    else next.push(model);
    this.draftEnabled[provider] = next;
    this.modelsSaved.set(false);
  }

  addCustom(provider: string): void {
    const id = this.customDraft.trim();
    if (!id) return;
    if (!this.enabledFor(provider).includes(id)) {
      this.draftEnabled[provider] = [...this.enabledFor(provider), id];
    }
    this.customDraft = '';
    this.modelsSaved.set(false);
  }

  modelsChanged(provider: string): boolean {
    const saved = this.availability().find((p) => p.provider === provider)?.enabled ?? [];
    return (
      this.draftEnabled[provider] !== undefined &&
      this.draftEnabled[provider].join(',') !== saved.join(',')
    );
  }

  saveModels(provider: string): void {
    // Only providers that have actually chosen, plus this one. A provider left
    // out resolves to its whole catalogue, so sending the full map would
    // quietly turn every other provider's default into a fixed list.
    const payload: Record<string, string[]> = {};
    for (const entry of this.availability()) {
      if (!entry.defaulted || entry.provider === provider) {
        payload[entry.provider] = this.enabledFor(entry.provider);
      }
    }

    this.savingModels.set(true);
    this.api.saveModelAvailability(payload).subscribe({
      next: (a) => {
        this.savingModels.set(false);
        this.draftEnabled = {};
        this.availability.set(a.providers);
        this.inUse.set(a.in_use);
        this.modelsSaved.set(true);
      },
      error: (err) => {
        this.savingModels.set(false);
        this.error.set(apiError(err, 'Could not save the model list.'));
      },
    });
  }
}
