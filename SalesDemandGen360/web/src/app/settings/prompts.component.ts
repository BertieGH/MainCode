import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ConfigService, PromptDetail, PromptSummary, PromptVersion } from '../core/config.service';
import { IconComponent } from '../shared/icon.component';
import { apiError } from '../shared/api-error';

/**
 * The prompt editor.
 *
 * These lived in `services/instructions.py` and in git until 2026-10-04. The
 * reason they were there is worth keeping in mind while using this screen: a
 * prompt change alters what every downstream artefact means, so the same
 * account researched under two texts produces two different books. That is why
 * every save is a new version, why old versions are kept, and why the rows a
 * stage writes record which version produced them.
 *
 * Two things on this screen are not editable and that is the point:
 *
 * - **The preamble.** It carries the rule that retrieved text is data and
 *   never an instruction, and the rule that nothing is asserted without a
 *   citation. It is prepended server-side, below where a stored body can reach
 *   it. Shown here read-only so an admin can see what their words sit beneath.
 * - **The stage list.** Scenarios are code; a stage with no prompt is a bug in
 *   a migration, not something to add from a form.
 */
@Component({
  selector: 'app-prompts',
  standalone: true,
  imports: [CommonModule, FormsModule, IconComponent],
  template: `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
      <h2 style="font-size:1.15rem;">Prompts</h2>
      <button class="act-btn" (click)="help.set(!help())"
              [attr.aria-expanded]="help()" aria-controls="prompts-help"
              title="What this screen changes, and what it cannot change">
        <app-icon name="info" [size]="15" />
      </button>
    </div>

    <div class="card" id="prompts-help" *ngIf="help()" style="margin-bottom:14px;">
      <p class="row-sub" style="max-width:76ch;margin:0 0 8px;">
        What each stage is <strong>asked to do</strong>. The model it runs on, and how hard it
        thinks, are in <strong>Model config</strong> — a different question with a different answer.
      </p>
      <p class="row-sub" style="max-width:76ch;margin:0 0 8px;">
        Editing a prompt changes what every later run <em>means</em>. The same account researched
        under two texts produces two different books, so each save is a new version and the rows a
        stage writes record which version wrote them. Nothing is overwritten and nothing is lost —
        <strong>Reset</strong> restores the shipped text as a new version rather than deleting your
        edits.
      </p>
      <p class="row-sub" style="max-width:76ch;margin:0;">
        The grey preamble above each box is prepended to every stage and cannot be edited here or
        anywhere. It holds the rule that retrieved pages are data rather than instructions — the
        guard against a researched page telling the model what to do — and the rule that nothing is
        claimed without a citation.
      </p>
    </div>

    <div *ngIf="error()" class="card" style="border-color:var(--critical);margin-bottom:14px;">
      <strong style="color:var(--critical);">{{ error() }}</strong>
    </div>

    <!-- the gate -->
    <div class="card lock" *ngIf="!unlocked()" style="margin-bottom:16px;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
        <app-icon name="lock" [size]="15" />
        <strong style="font-size:.92rem;">
          {{ gateConfigured() ? 'Locked' : 'No admin password set' }}
        </strong>
      </div>

      <p class="row-sub" style="max-width:70ch;margin:0 0 10px;">
        <ng-container *ngIf="gateConfigured()">
          Prompts can be read by anyone. Changing one needs the admin password.
        </ng-container>
        <ng-container *ngIf="!gateConfigured()">
          Set one before anyone can edit a prompt. Note that this locks
          <strong>this screen only</strong> — every other part of this application is open, and
          this is not a substitute for proper sign-in.
        </ng-container>
      </p>

      <div class="lock-row">
        <input class="field" type="password" [(ngModel)]="password"
               (keyup.enter)="gateConfigured() ? unlock() : setPassword()"
               [attr.placeholder]="gateConfigured() ? 'Admin password' : 'Choose a password'"
               aria-label="Admin password">
        <input class="field" type="password" *ngIf="!gateConfigured()"
               [(ngModel)]="passwordAgain" (keyup.enter)="setPassword()"
               placeholder="Type it again" aria-label="Confirm the password">
        <button class="btn primary" *ngIf="gateConfigured()" (click)="unlock()"
                [disabled]="busy() || !password.trim()">
          {{ busy() ? 'Checking…' : 'Unlock' }}
        </button>
        <button class="btn primary" *ngIf="!gateConfigured()" (click)="setPassword()"
                [disabled]="busy() || !canSetPassword()">
          {{ busy() ? 'Saving…' : 'Set password' }}
        </button>
      </div>
      <p class="row-sub" *ngIf="!gateConfigured()" style="margin:8px 0 0;">
        At least {{ minLength() }} characters.
      </p>
    </div>

    <p class="row-sub unlocked-note" *ngIf="unlocked()">
      <app-icon name="check" [size]="13" />
      Unlocked for {{ ttlMinutes() }} minutes.
      <button class="linkish" (click)="lock()">Lock now</button>
    </p>

    <p class="row-sub" *ngIf="loading()">Loading…</p>

    <!-- the stages -->
    <table class="data" *ngIf="!loading() && !editing()">
      <thead>
        <tr>
          <th>Stage</th>
          <th>Version</th>
          <th>Length</th>
          <th>State</th>
          <th>Last change</th>
          <th class="actcol">Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr *ngFor="let p of rows()">
          <td>
            <code>{{ p.scenario }}</code>
            <div class="row-sub" *ngIf="p.note">{{ p.note }}</div>
          </td>
          <td class="mono">v{{ p.version ?? '—' }}</td>
          <td class="mono">{{ p.chars }}</td>
          <td>
            <span class="badge" [class.badge-warn]="p.differs_from_default"
                  [class.badge-neutral]="!p.differs_from_default"
                  [title]="p.differs_from_default
                    ? 'Edited here — no longer the text this installation shipped with'
                    : 'Unchanged from the shipped text'">
              {{ p.differs_from_default ? 'edited' : 'shipped' }}
            </span>
            <span class="badge badge-warn" *ngIf="!p.seeded" style="margin-left:6px;"
                  title="No stored row for this stage — it runs on its shipped text. A migration should seed it.">
              not stored
            </span>
          </td>
          <td class="row-sub">{{ p.updated_at ? (p.updated_at | date: 'MMM d, y') : '—' }}</td>
          <td class="actcol">
            <button class="act-btn" (click)="open(p.scenario)"
                    [attr.aria-label]="'Open ' + p.scenario"
                    [title]="unlocked() ? 'Edit ' + p.scenario : 'Read ' + p.scenario + ' — unlock to edit'">
              <app-icon [name]="unlocked() ? 'edit' : 'eye'" [size]="15" />
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- one stage -->
    <ng-container *ngIf="editing() as d">
      <div class="card" style="margin-bottom:14px;">
        <div class="sec-head" style="margin-bottom:10px;">
          <div>
            <code style="font-size:.95rem;">{{ d.scenario }}</code>
            <span class="row-sub" style="margin-left:8px;">
              v{{ d.version ?? '—' }}{{ d.differs_from_default ? ' · edited' : ' · shipped' }}
            </span>
          </div>
          <button class="btn" (click)="close()">Back to all stages</button>
        </div>

        <!-- read-only, and not for decoration -->
        <div class="preamble">
          <div class="row-sub preamble-h">
            <app-icon name="lock" [size]="12" />
            Prepended to every stage · not editable
          </div>
          <pre>{{ d.common_preamble }}</pre>
        </div>

        <label style="display:block;margin-top:12px;">
          Instructions for this stage
          <textarea class="field mono-ish" rows="18" [(ngModel)]="draftBody"
                    [disabled]="!unlocked()"
                    [attr.aria-label]="'Instructions for ' + d.scenario"></textarea>
        </label>

        <label style="display:block;margin-top:10px;">
          Why this change
          <input class="field" [(ngModel)]="draftNote" [disabled]="!unlocked()"
                 placeholder="optional — the version records what, this records why"
                 [attr.aria-label]="'Note for ' + d.scenario">
        </label>

        <div class="sec-head" style="margin-top:12px;">
          <span class="row-sub">
            {{ draftBody.length }} characters<span *ngIf="dirty()"> · unsaved</span>
          </span>
          <span style="display:flex;gap:8px;">
            <button class="btn" (click)="revert()" [disabled]="!dirty()">Discard</button>
            <button class="btn" (click)="reset()"
                    [disabled]="busy() || !unlocked() || !d.differs_from_default"
                    title="Restore the text this installation shipped with, as a new version">
              Reset to shipped
            </button>
            <button class="btn primary" (click)="save()"
                    [disabled]="busy() || !unlocked() || !dirty() || !draftBody.trim()">
              {{ busy() ? 'Saving…' : 'Save as new version' }}
            </button>
          </span>
        </div>
      </div>

      <div class="card">
        <div class="sec-head" style="margin-bottom:8px;">
          <strong style="font-size:.88rem;">History</strong>
          <span class="row-sub">Every version is kept. Restoring copies one forward.</span>
        </div>
        <table class="data">
          <thead>
            <tr><th>Version</th><th>Length</th><th>Why</th><th>When</th><th class="actcol"></th></tr>
          </thead>
          <tbody>
            <tr *ngFor="let v of versions()">
              <td class="mono">
                v{{ v.version }}
                <span class="badge badge-good" *ngIf="v.is_active" style="margin-left:6px;">live</span>
              </td>
              <td class="mono">{{ v.chars }}</td>
              <td class="row-sub">{{ v.note || '—' }}</td>
              <td class="row-sub">{{ v.created_at | date: 'MMM d, y, HH:mm' }}</td>
              <td class="actcol">
                <button class="act-btn" *ngIf="!v.is_active" (click)="restore(v.version)"
                        [disabled]="busy() || !unlocked()"
                        [attr.aria-label]="'Restore version ' + v.version"
                        [title]="'Bring v' + v.version + ' back as a new version'">
                  <app-icon name="undo" [size]="15" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </ng-container>
  `,
  styles: [
    `
      .lock { border-style: dashed; }
      .lock-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
      .lock-row .field { max-width: 220px; }
      .unlocked-note { display: flex; align-items: center; gap: 6px; margin: 0 0 12px; }
      .linkish { background: none; border: 0; padding: 0 0 0 4px; cursor: pointer;
                 font: inherit; color: var(--accent); text-decoration: underline; }
      /* Visibly not an input. It is prepended to whatever is typed below and
         there is no path to changing it, so it must not look like a field
         somebody failed to enable. */
      .preamble { border: 1px solid var(--line); border-radius: 6px;
                  background: var(--surface-2, #f6f7f6); padding: 10px 12px; }
      .preamble-h { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
      .preamble pre { margin: 0; white-space: pre-wrap; font-size: .78rem; opacity: .85;
                      font-family: 'IBM Plex Mono', monospace; }
      .mono-ish { font-family: 'IBM Plex Mono', monospace; font-size: .82rem; line-height: 1.5; }
      .sec-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
    `,
  ],
})
export class PromptsComponent implements OnInit {
  private api = inject(ConfigService);

  rows = signal<PromptSummary[]>([]);
  editing = signal<PromptDetail | null>(null);
  versions = signal<PromptVersion[]>([]);
  loading = signal(true);
  busy = signal(false);
  error = signal<string | null>(null);
  help = signal(false);

  gateConfigured = signal(false);
  minLength = signal(8);
  ttlMinutes = signal(30);
  /**
   * Held in memory only. Putting it in localStorage would outlive the tab and
   * quietly re-unlock the screen on a shared machine, which is the one thing
   * the lock exists to stop.
   */
  private token = signal<string | null>(null);
  password = '';
  passwordAgain = '';

  draftBody = '';
  draftNote = '';

  unlocked(): boolean {
    return this.token() !== null;
  }

  dirty(): boolean {
    const d = this.editing();
    return !!d && this.draftBody !== d.body;
  }

  canSetPassword(): boolean {
    return (
      this.password.trim().length >= this.minLength() &&
      this.password === this.passwordAgain
    );
  }

  ngOnInit(): void {
    this.api.promptGate().subscribe({
      next: (g) => {
        this.gateConfigured.set(g.configured);
        this.minLength.set(g.min_password_length);
        this.ttlMinutes.set(Math.round(g.ttl_seconds / 60));
      },
      error: (err) => this.error.set(apiError(err, 'Could not read the lock state.')),
    });
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.api.listPrompts().subscribe({
      next: (rows) => {
        this.rows.set(rows);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(apiError(err, 'Could not load the prompts.'));
        this.loading.set(false);
      },
    });
  }

  setPassword(): void {
    if (!this.canSetPassword()) return;
    this.busy.set(true);
    this.error.set(null);
    this.api.setPromptPassword({ password: this.password }).subscribe({
      next: (r) => {
        this.token.set(r.token);
        this.gateConfigured.set(true);
        this.password = '';
        this.passwordAgain = '';
        this.busy.set(false);
      },
      error: (err) => {
        this.error.set(apiError(err, 'Could not set the password.'));
        this.busy.set(false);
      },
    });
  }

  unlock(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api.unlockPrompts(this.password).subscribe({
      next: (r) => {
        this.token.set(r.token);
        this.password = '';
        this.busy.set(false);
      },
      error: (err) => {
        this.error.set(apiError(err, 'Could not unlock.'));
        this.busy.set(false);
      },
    });
  }

  lock(): void {
    this.token.set(null);
  }

  open(scenario: string): void {
    this.error.set(null);
    this.api.readPrompt(scenario).subscribe({
      next: (d) => {
        this.editing.set(d);
        this.draftBody = d.body;
        this.draftNote = '';
        this.loadHistory(scenario);
      },
      error: (err) => this.error.set(apiError(err, 'Could not open that stage.')),
    });
  }

  private loadHistory(scenario: string): void {
    this.api.promptHistory(scenario).subscribe({
      next: (v) => this.versions.set(v),
      // A missing history is not a reason to refuse the editor — the text is
      // already on screen and editable.
      error: () => this.versions.set([]),
    });
  }

  close(): void {
    this.editing.set(null);
    this.versions.set([]);
    this.draftBody = '';
    this.draftNote = '';
    this.load();
  }

  revert(): void {
    const d = this.editing();
    if (d) this.draftBody = d.body;
  }

  save(): void {
    const d = this.editing();
    const token = this.token();
    if (!d || !token || !this.draftBody.trim()) return;
    this.busy.set(true);
    this.error.set(null);
    this.api
      .savePrompt(d.scenario, { body: this.draftBody, note: this.draftNote || null }, token)
      .subscribe({
        next: (fresh) => this.afterWrite(fresh),
        error: (err) => this.afterWriteFailed(err, 'Could not save.'),
      });
  }

  reset(): void {
    const d = this.editing();
    const token = this.token();
    if (!d || !token) return;
    this.busy.set(true);
    this.error.set(null);
    this.api.resetPrompt(d.scenario, token).subscribe({
      next: (fresh) => this.afterWrite(fresh),
      error: (err) => this.afterWriteFailed(err, 'Could not reset.'),
    });
  }

  restore(version: number): void {
    const d = this.editing();
    const token = this.token();
    if (!d || !token) return;
    this.busy.set(true);
    this.error.set(null);
    this.api.restorePrompt(d.scenario, version, token).subscribe({
      next: (fresh) => this.afterWrite(fresh),
      error: (err) => this.afterWriteFailed(err, 'Could not restore that version.'),
    });
  }

  private afterWrite(fresh: PromptDetail): void {
    this.editing.set(fresh);
    this.draftBody = fresh.body;
    this.draftNote = '';
    this.busy.set(false);
    this.loadHistory(fresh.scenario);
  }

  private afterWriteFailed(err: unknown, fallback: string): void {
    this.error.set(apiError(err, fallback));
    this.busy.set(false);
    // A 401 means the unlock lapsed while the screen sat open. Dropping the
    // token puts the lock back up rather than leaving buttons that look live
    // and fail on every press.
    if ((err as { status?: number })?.status === 401) this.token.set(null);
  }
}
