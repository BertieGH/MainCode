import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  ConfigService,
  Credential,
  CredentialState,
  ProviderInfo,
  Readiness,
  Slot,
} from '../core/config.service';
import {
  statusExplanation,
  statusLabel,
  statusTone,
} from '../shared/credential-status';
import { IconComponent } from '../shared/icon.component';
import { CredentialFormComponent } from './credential-form.component';
import { apiError, apiErrorCode } from '../shared/api-error';

/**
 * API settings: the three connections this application cannot work without,
 * and everything to do with the keys behind them.
 *
 * This screen used to be two. Integrations listed the same credentials in the
 * same states with the same Test button, and the only thing it had that Setup
 * did not was the form for entering a key — so somebody adding a provider read
 * one list, navigated, read the same list again, and typed. The form now opens
 * inside the slot it belongs to, which also closes the one real mistake the
 * split allowed: entering an outreach key while reading the heading that said
 * contact enrichment.
 *
 * Two things carried over unchanged:
 *
 * **Readiness is never cached.** It is recomputed server-side from the
 * credential rows, so a revoked key or an exhausted account re-closes the gate
 * by itself. A stored "setup complete" flag would keep saying ready while
 * every run failed.
 *
 * **Verified means a real round-trip.** A key that merely decrypts proves the
 * encryption secret has not changed and nothing else — so `Test` is not
 * decoration, it is the thing that moves a slot to ready.
 */
@Component({
  selector: 'app-setup',
  standalone: true,
  imports: [CommonModule, FormsModule, IconComponent, CredentialFormComponent],
  template: `
    <div class="head">
      <div>
        <h2>API settings</h2>
        <p class="row-sub" style="max-width:70ch;">
          Three external connections are mandatory. Until each one is stored <em>and</em> verified
          by a live check, importing accounts, promoting a queue and executing a campaign are
          refused — by the server, not just by the menu.
        </p>
      </div>
      <span class="badge" [ngClass]="ready() ? 'badge-good' : 'badge-warn'">
        {{ ready() ? 'ready' : (done() + ' of 3') }}
      </span>
    </div>

    <div class="card" *ngIf="error()" style="border-color:var(--critical);margin-bottom:18px;">
      <strong style="color:var(--critical);">{{ error() }}</strong>
    </div>

    <!-- Which kind of installation this is. Above the slots because it changes
         what all three of them mean. -->
    <div class="card mode" [class.demo]="isDemo()">
      <div style="display:flex;justify-content:space-between;gap:16px;align-items:flex-start;">
        <div>
          <strong>{{ isDemo() ? 'Demo installation' : 'Production installation' }}</strong>
          <p class="row-sub" style="max-width:66ch;margin-top:4px;">
            <ng-container *ngIf="isDemo()">
              The three mandatory connections are satisfied by stubs so the whole application can
              be walked without real accounts. <strong>Nothing contacts an external service</strong>
              — no model is called, no contact is looked up, and nothing is sent. Anything the
              pipeline produces here is fixture data and is tagged as such.
            </ng-container>
            <ng-container *ngIf="!isDemo()">
              Real credentials are required and are checked with a live round-trip. Import,
              promote and execute stay refused until all three connections are verified.
            </ng-container>
          </p>
        </div>
        <span class="badge" [ngClass]="isDemo() ? 'badge-warn' : 'badge-good'">{{ mode() }}</span>
      </div>

      <p class="row-sub demo-data" *ngIf="demoRuns()">
        {{ demoRuns() }} run(s) here were produced in demo mode. Their evidence and signals are
        fixtures, and nothing on screen tells them apart from real ones.
      </p>

      <div style="display:flex;gap:10px;align-items:center;margin-top:12px;flex-wrap:wrap;">
        <button class="btn" *ngIf="!isDemo()" (click)="switchTo('demo')" [disabled]="switching()">
          Switch to demo
        </button>
        <button class="btn btn-primary" *ngIf="isDemo()" (click)="switchTo('production')"
                [disabled]="switching()">
          Switch to production
        </button>
        <span class="row-sub" *ngIf="switchNote()">{{ switchNote() }}</span>
      </div>

      <div class="ack" *ngIf="pendingAck()">
        <strong>{{ pendingAck() }}</strong>
        <div style="display:flex;gap:10px;margin-top:10px;">
          <button class="btn btn-primary" (click)="switchTo('production', true)">
            Switch anyway — I understand the data is mixed
          </button>
          <button class="btn" (click)="pendingAck.set(null)">Cancel</button>
        </div>
      </div>
    </div>

    <div class="card ready-note" *ngIf="ready()">
      <strong>All three are connected and verified.</strong>
      <span class="row-sub">
        The rest of the application is unlocked. This page stays accurate on its own — if a key is
        revoked or an account runs out of credit, the slot goes back to unverified the next time
        anything checks.
      </span>
    </div>

    <!-- One card per slot, in the order you would set them up. -->
    <div class="card slot" *ngFor="let s of slots(); let i = index" [class.done]="s.satisfied">
      <!-- Status and the action that changes it sit together at the right end,
           above a rule. Previously the button was the last thing on the card,
           below the table and the suggestions — so on a slot with two keys it
           was most of a screen away from the heading it belonged to, and the
           cards did not line up with each other. -->
      <div class="slot-head">
        <div class="step" [class.on]="s.satisfied">{{ s.satisfied ? '✓' : i + 1 }}</div>
        <div style="flex:1;min-width:0;">
          <h3>{{ s.title }}</h3>
          <p class="row-sub" style="max-width:64ch;">{{ s.why }}</p>
        </div>
        <span class="badge"
              [ngClass]="{
                'badge-good': s.state === 'ready',
                'badge-warn': s.state === 'unverified',
                'badge-neutral': s.state === 'missing'
              }">{{ s.state }}</span>
        <button class="btn" (click)="openFor(s.kind)" *ngIf="openSlot() !== s.kind">
          <app-icon name="plus" [size]="13" />
          {{ s.credentials.length ? 'Add provider' : 'Add a credential' }}
        </button>
      </div>

      <p class="row-sub blocker" *ngIf="s.blocker">{{ s.blocker }}</p>
      <p class="row-sub pending" *ngIf="s.warning">{{ s.warning }}</p>

      <!-- The keys themselves. This is the table Integrations used to hold. -->
      <div class="table-wrap" *ngIf="s.credentials.length" style="margin-top:12px;">
        <table class="data">
          <thead>
            <tr>
              <th>Provider</th><th>Key</th><th>Status</th><th>Models</th>
              <th class="actcol">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let c of s.credentials">
              <td>
                <strong>{{ c.label }}</strong>
                <div class="row-sub" *ngIf="c.console_url">
                  <a class="link" [href]="c.console_url" target="_blank" rel="noopener">
                    where its keys come from ↗
                  </a>
                </div>
                <div class="row-sub" *ngIf="!c.verifiable">this build cannot check this key</div>
                <div class="row-sub" *ngIf="c.verifiable && !c.runnable">
                  key verifiable · integration not built yet
                </div>
              </td>
              <td class="mono row-sub">{{ c.last_four ? '••••' + c.last_four : '—' }}</td>
              <td>
                <span class="badge" [ngClass]="tone(c)" [title]="explain(c)">{{ label(c) }}</span>
                <div class="row-sub" *ngIf="result() as r">
                  <ng-container *ngIf="r.provider === c.provider">{{ r.message }}</ng-container>
                </div>
              </td>
              <td class="row-sub mono models">{{ modelsFor(c.provider) }}</td>
              <td class="actcol" style="white-space:nowrap;">
                <ng-container *ngIf="!isStub(c)">
                  <button class="btn" style="padding:4px 10px;font-size:.74rem;"
                          (click)="test(c.provider)" [disabled]="testing() === c.provider">
                    {{ testing() === c.provider ? 'Testing…' : 'Test' }}
                  </button>
                  <button class="act-btn" (click)="openFor(s.kind, c.provider)"
                          [attr.aria-label]="'Edit the ' + c.provider + ' credential'"
                          title="Replace the key, or change which models it may run">
                    <app-icon name="edit" [size]="15" />
                  </button>
                  <button *ngIf="confirming() !== c.provider" class="act-btn danger"
                          (click)="confirming.set(c.provider)"
                          [attr.aria-label]="'Remove the ' + c.provider + ' credential'"
                          title="Remove this credential">
                    <app-icon name="trash" [size]="15" />
                  </button>
                  <ng-container *ngIf="confirming() === c.provider">
                    <span class="row-sub" style="margin:0 6px;">Remove it?</span>
                    <button class="act-btn danger" (click)="remove(c.provider)"
                            aria-label="Confirm removal" title="Yes, remove it">
                      <app-icon name="check" [size]="15" />
                    </button>
                    <button class="act-btn" (click)="confirming.set(null)"
                            aria-label="Keep it" title="Keep it">
                      <app-icon name="x" [size]="15" />
                    </button>
                  </ng-container>
                </ng-container>
                <span class="row-sub" *ngIf="isStub(c)">nothing to test</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="suggest" *ngIf="suggestionsFor(s.kind).length">
        <span class="row-sub">Providers you can connect:</span>
        <span class="row-sub sug" *ngFor="let p of suggestionsFor(s.kind)">
          <strong>{{ p.label }}</strong>
          <span class="row-sub" *ngIf="!p.runnable" style="opacity:.7;">(key only)</span>
          <a class="link" [href]="p.console_url" target="_blank" rel="noopener">get a key ↗</a>
        </span>
      </div>

      <!-- The form, inside the slot it belongs to. Entering an outreach key
           while reading the enrichment heading was possible while these were
           two screens; here the slot decides which providers are suggested. -->
      <app-credential-form *ngIf="openSlot() === s.kind"
                           [kind]="s.kind" [provider]="openProvider()"
                           [title]="formTitle(s)"
                           (savedCredential)="onSaved()" (cancelled)="closeForm()" />

      <!-- The waterfall lives on the enrichment card, where the decision is
           actually made, rather than on a separate page nobody visits. -->
      <div class="waterfall" *ngIf="s.kind === 'enrichment'">
        <strong style="font-size:.86rem;">Waterfall order</strong>
        <p class="row-sub" style="max-width:64ch;">
          Asked in this order; the first to return everything required ends the run. A waterfall,
          not a race — these are metered per call, so asking everyone and keeping the best answer
          multiplies the bill on every contact the first provider already resolved.
        </p>
        <ol class="order">
          <li *ngFor="let key of order(); let i = index">
            <span class="mono">{{ key }}</span>
            <button class="act-btn" (click)="move(i, -1)" [disabled]="i === 0"
                    [attr.aria-label]="'Move ' + key + ' earlier'" title="Earlier">↑</button>
            <button class="act-btn" (click)="move(i, 1)" [disabled]="i === order().length - 1"
                    [attr.aria-label]="'Move ' + key + ' later'" title="Later">↓</button>
          </li>
        </ol>
        <label class="per-persona">
          <strong style="font-size:.86rem;">Suggested contacts per persona</strong>
          <input class="field" type="number" min="1" max="25" aria-label="Suggested contacts per persona"
                 [ngModel]="perPersona()" (ngModelChange)="setPerPersona($event)">
          <span class="row-sub">
            How many people <em>Find contacts</em> may propose for each ICP persona at each account.
            Searching is free; each person accepted and revealed is an Apollo credit.
          </span>
        </label>
        <div style="display:flex;gap:10px;align-items:center;">
          <button class="btn btn-primary" (click)="saveOrder()" [disabled]="!orderChanged()">
            <app-icon name="check" [size]="13" />Save
          </button>
          <span class="row-sub" *ngIf="orderSaved()">Saved as a new version.</span>
        </div>
      </div>
    </div>

    <!-- Credentials that match no provider this build knows. They belong to no
         slot, so before this section they rendered nowhere at all: stored,
         encrypted, unusable, and impossible to delete without SQL. Provider
         names are typeable, so this is one keystroke away at any time. -->
    <div class="card orphans" *ngIf="orphans().length">
      <h3 style="font-size:1rem;margin-bottom:4px;">Unrecognised credentials</h3>
      <p class="row-sub" style="max-width:66ch;">
        Stored against a provider name this build does not know — almost always a typo.
        Nothing can test one and nothing can use one: it satisfies no step above, and it
        is not part of any waterfall. Deleting it removes the stored secret.
      </p>
      <div class="table-wrap" style="margin-top:12px;">
        <table>
          <thead>
            <tr><th>Provider</th><th>Key</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            <tr *ngFor="let c of orphans()">
              <td class="mono">{{ c.provider }}</td>
              <td class="mono">••••{{ c.last_four }}</td>
              <td>
                <!-- Read as a defect, not as "unknown". The key value may well be
                     fine — this one is a copy of a working key — but the row is
                     not: there is no provider by this name, so nothing can test
                     it and nothing can use it. "Not checkable" invited the
                     reading "might be OK, we just can't tell", which is the one
                     thing it is not. -->
                <span class="badge badge-critical" title="There is no provider by this name in this
build, so this row cannot be tested and cannot be used — it satisfies no step above and is in no
waterfall. Almost always a typo of a real provider name. The stored value may be a perfectly good
key; it is unreachable under this name. Delete it and re-enter it against the right provider.">invalid</span>
              </td>
              <td style="text-align:right;">
                <button class="act-btn" *ngIf="confirming() !== c.provider"
                        (click)="confirming.set(c.provider)"
                        [attr.aria-label]="'Remove the ' + c.provider + ' credential'"
                        title="Remove this credential">
                  <app-icon name="trash" [size]="13" />
                </button>
                <span *ngIf="confirming() === c.provider" style="display:inline-flex;gap:8px;">
                  <button class="act-btn" (click)="remove(c.provider)">Delete</button>
                  <button class="act-btn" (click)="confirming.set(null)">Cancel</button>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
  styles: [
    `
      .head { display: flex; justify-content: space-between; align-items: flex-start;
              gap: 20px; margin-bottom: 22px; }
      .head h2 { font-size: 1.15rem; margin-bottom: 4px; }
      /* display is declared, not assumed. A global '.slot { display: flex }'
         in styles.css — the LGM attribute chip, a different feature entirely —
         turned every card here into a flex row, laying the header, the table
         and the provider list out as three columns and squeezing the heading
         to one word per line. A component stylesheet that says nothing about
         display cannot win against a global one that does, however specific
         its scoping attribute is. That rule is now '.attr-slot'; this says
         block so the next collision cannot repeat it. */
      .slot { display: block; margin-bottom: 18px; border-color: var(--line); }
      .slot.done { border-color: var(--good, var(--line)); }
      /* center, not flex-start: the badge and the button are one
         control group and have to share a baseline. The rule under the
         row is what makes a header read as a header rather than as the
         first line of the card. */
      .slot-head { display: flex; gap: 14px; align-items: center;
                   padding-bottom: 12px; border-bottom: 1px solid var(--line); }
      .slot-head .btn { flex: none; white-space: nowrap; }
      .slot-head .badge { flex: none; }
      .slot h3 { font-size: 1rem; margin-bottom: 2px; }
      .step { width: 26px; height: 26px; border-radius: 50%; flex: none;
              display: flex; align-items: center; justify-content: center;
              font-size: .8rem; font-weight: 600;
              border: 1px solid var(--line); color: var(--muted); }
      .step.on { border-color: transparent; background: var(--good, #2f6f4f); color: #fff; }
      .blocker { margin-top: 10px; color: var(--warn); max-width: 64ch; }
      .pending { margin-top: 10px; opacity: .85; max-width: 64ch; }
      .ready-note { border-color: var(--good, var(--line)); margin-bottom: 18px; }
      .mode { margin-bottom: 18px; border-color: var(--line); }
      .mode.demo { border-color: var(--warn); border-style: dashed; }
      .demo-data { margin-top: 10px; color: var(--warn); max-width: 66ch; }
      .ack { margin-top: 14px; padding: 12px; border-radius: 6px;
             border: 1px solid var(--warn); max-width: 70ch; }
      .suggest { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 14px;
                 align-items: baseline; }
      .sug { display: inline-flex; gap: 6px; align-items: baseline; }
      .models { max-width: 30ch; opacity: .85; }
      .badge[title] { cursor: help; }
      .link { color: var(--accent); text-decoration: none; }
      .link:hover { text-decoration: underline; }
      .waterfall { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--line); }
      .orphans { margin-top: 18px; border-color: var(--warn); border-style: dashed; }
      .order { margin: 10px 0 12px; padding-left: 20px; }
      .order li { margin-bottom: 4px; display: flex; gap: 8px; align-items: center; }
      .per-persona { display: flex; flex-direction: column; gap: 4px; margin: 0 0 12px; max-width: 64ch; }
      .per-persona .field { max-width: 90px; }
    `,
  ],
})
export class SetupComponent implements OnInit {
  private api = inject(ConfigService);

  readinessState = signal<Readiness | null>(null);
  providers = signal<ProviderInfo[]>([]);
  /** Provider → the models it may run, for the table column. */
  enabledModels = signal<Record<string, string[]>>({});

  error = signal<string | null>(null);
  testing = signal<string | null>(null);
  confirming = signal<string | null>(null);
  result = signal<{ provider: string; message: string } | null>(null);

  /** Which slot has the credential form open, and for which provider. */
  openSlot = signal<string | null>(null);
  openProvider = signal('');

  order = signal<string[]>([]);
  private savedOrder: string[] = [];
  perPersona = signal(5);
  private savedPerPersona = 5;
  orderSaved = signal(false);

  switching = signal(false);
  switchNote = signal<string | null>(null);
  pendingAck = signal<string | null>(null);

  ngOnInit(): void {
    this.load();
    this.api.providers().subscribe({ next: (p) => this.providers.set(p) });
    this.loadModels();
  }

  ready(): boolean {
    return this.readinessState()?.ready ?? false;
  }

  slots(): Slot[] {
    return this.readinessState()?.slots ?? [];
  }

  done(): number {
    return this.slots().filter((s) => s.satisfied).length;
  }

  mode(): string {
    return this.readinessState()?.mode ?? 'production';
  }

  isDemo(): boolean {
    return this.mode() === 'demo';
  }

  demoRuns(): number {
    return this.readinessState()?.demo_runs ?? 0;
  }

  /** A stand-in rather than a stored credential. Named, never disguised. */
  isStub(c: { provider: string }): boolean {
    return c.provider.startsWith('demo_');
  }

  label(c: CredentialState): string {
    return statusLabel(c.status, c.last_test_code);
  }

  tone(c: CredentialState): string {
    return statusTone(c.status, c.last_test_code);
  }

  explain(c: CredentialState): string {
    return statusExplanation(c.status, c.last_test_code, c.last_test_detail);
  }

  modelsFor(provider: string): string {
    return (this.enabledModels()[provider] ?? []).join(', ');
  }

  formTitle(slot: Slot): string {
    return this.openProvider()
      ? `Edit ${this.openProvider()}`
      : `Add a ${slot.title.toLowerCase()} credential`;
  }

  /**
   * Providers whose key this build can at least verify.
   *
   * Not filtered to `runnable`: a Gemini key was checkable long before a stage
   * could run on it, and storing it then was reasonable. The ones that cannot
   * run anything are labelled rather than hidden.
   */
  suggestionsFor(kind: string): ProviderInfo[] {
    return this.providers().filter((p) => p.kind === kind && p.verifiable);
  }

  // --- the credential form ---

  openFor(kind: string, provider = ''): void {
    this.openSlot.set(kind);
    this.openProvider.set(provider);
    this.result.set(null);
  }

  /**
   * Credentials the backend could not put in a slot.
   *
   * A method rather than a computed: `readinessState` holds a plain object, and
   * a computed over one never recomputes when it is replaced wholesale — the
   * same trap that made the model list stale.
   */
  orphans(): CredentialState[] {
    return this.readinessState()?.unrecognised ?? [];
  }

  closeForm(): void {
    this.openSlot.set(null);
    this.openProvider.set('');
  }

  onSaved(): void {
    this.closeForm();
    this.load();
    this.loadModels();
  }

  remove(provider: string): void {
    this.api.credentials().subscribe({
      next: (creds) => {
        const match = creds.find((c) => c.provider === provider);
        if (!match) {
          this.confirming.set(null);
          return;
        }
        this.api.deleteCredential(match.id).subscribe({
          next: () => {
            this.confirming.set(null);
            // Removing the last key for a slot re-closes the gate, which is
            // correct — readiness is derived so it can follow the world down.
            this.load();
          },
          error: (err) => {
            this.confirming.set(null);
            this.error.set(apiError(err, 'Could not remove the credential.'));
          },
        });
      },
      error: () => this.confirming.set(null),
    });
  }

  /**
   * Test the credential behind a provider.
   *
   * Resolved to a credential id here rather than held on the slot: the
   * readiness view deliberately carries no ids, so nothing on this screen can
   * be used to address a credential directly.
   */
  test(provider: string): void {
    this.testing.set(provider);
    this.result.set(null);
    this.api.credentials().subscribe({
      next: (creds: Credential[]) => {
        const match = creds.find(
          (c) => c.provider === provider && c.credential_type === 'api_key',
        );
        if (!match) {
          this.testing.set(null);
          this.result.set({ provider, message: 'No API key stored for this provider.' });
          return;
        }
        this.api.testCredential(match.id).subscribe({
          next: (updated) => {
            this.testing.set(null);
            this.result.set({
              provider,
              message: statusExplanation(
                updated.status,
                updated.last_test_code,
                updated.last_test_detail,
              ),
            });
            // Re-read rather than patching locally: readiness is the server's
            // judgement, and a slot can flip on a credential this screen did
            // not touch.
            this.load();
          },
          error: (err) => {
            this.testing.set(null);
            this.result.set({ provider, message: apiError(err, 'Test failed') });
          },
        });
      },
      error: () => {
        this.testing.set(null);
        this.result.set({ provider, message: 'Could not read stored credentials.' });
      },
    });
  }

  // --- the enrichment waterfall ---

  orderChanged(): boolean {
    return (
      this.order().join(',') !== this.savedOrder.join(',') ||
      this.perPersona() !== this.savedPerPersona
    );
  }

  move(index: number, delta: number): void {
    const next = [...this.order()];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    this.order.set(next);
    this.orderSaved.set(false);
  }

  setPerPersona(value: unknown): void {
    this.perPersona.set(Math.max(1, Math.min(25, Math.round(Number(value) || 1))));
    this.orderSaved.set(false);
  }

  saveOrder(): void {
    this.api
      .saveEnrichmentConfig({
        provider_order: this.order(),
        required_fields: ['email'],
        suggestions_per_persona: this.perPersona(),
      })
      .subscribe({
        next: (cfg) => {
          this.savedOrder = [...cfg.provider_order];
          this.order.set([...cfg.provider_order]);
          this.savedPerPersona = cfg.suggestions_per_persona ?? 5;
          this.perPersona.set(this.savedPerPersona);
          this.orderSaved.set(true);
        },
        error: (err) =>
          this.error.set(apiError(err, 'Could not save the waterfall order.')),
      });
  }

  // --- installation mode ---

  switchTo(mode: 'production' | 'demo', acknowledge = false): void {
    this.switching.set(true);
    this.switchNote.set(null);
    this.api
      .setMode({
        mode,
        reason: 'changed from the setup screen',
        acknowledge_demo_data: acknowledge,
      })
      .subscribe({
        next: () => {
          this.switching.set(false);
          this.pendingAck.set(null);
          this.switchNote.set(`Now a ${mode} installation.`);
          this.load();
        },
        error: (err) => {
          this.switching.set(false);
          // The *code* decides the branch; the text is for display. Two
          // different questions, asked separately.
          if (apiErrorCode(err) === 'demo_data_present') {
            this.pendingAck.set(apiError(err));
            return;
          }
          this.error.set(apiError(err, 'Could not change the mode.'));
        },
      });
  }

  private loadModels(): void {
    this.api.modelAvailability().subscribe({
      next: (a) =>
        this.enabledModels.set(
          Object.fromEntries(a.providers.map((p) => [p.provider, p.enabled])),
        ),
      error: () => this.enabledModels.set({}),
    });
  }

  private load(): void {
    this.api.enrichmentConfig().subscribe({
      next: (cfg) => {
        this.savedPerPersona = cfg.suggestions_per_persona ?? 5;
        this.perPersona.set(this.savedPerPersona);
      },
      // None saved yet: the default applies.
      error: () => undefined,
    });
    this.api.readiness().subscribe({
      next: (r) => {
        this.readinessState.set(r);
        if (!this.orderChanged()) {
          this.savedOrder = [...r.enrichment_order];
          this.order.set([...r.enrichment_order]);
        }
      },
      error: (err) => this.error.set(apiError(err, 'Could not read setup status.')),
    });
  }
}
