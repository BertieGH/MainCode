import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ConfigService, WritingSample } from '../core/config.service';
import { IconComponent } from '../shared/icon.component';
import { apiError } from '../shared/api-error';

/**
 * The house voice, by example rather than by instruction.
 *
 * These go into the third cached prompt block. Describing a tone in adjectives
 * produces copy that matches the adjectives; showing three messages that
 * actually landed produces copy that sounds like them.
 */
@Component({
  selector: 'app-writing-samples',
  standalone: true,
  imports: [CommonModule, FormsModule, IconComponent],
  template: `
    <div class="sec-head">
      <div style="display:flex;align-items:center;gap:8px;">
        <h2 style="font-size:1.15rem;">Writing samples</h2>
        <button class="act-btn" (click)="help.set(!help())"
                [attr.aria-expanded]="help()" aria-controls="ws-help"
                [attr.aria-label]="help() ? 'Hide help' : 'About writing samples'"
                title="How these are used">
          <app-icon name="info" [size]="15" />
        </button>
      </div>
      <button class="btn btn-primary" style="padding:6px 12px;font-size:.78rem;"
              (click)="adding.set(!adding())"
              aria-label="Add a writing sample" title="Add a writing sample">
        <app-icon name="plus" [size]="13" />Add Sample
      </button>
    </div>
    <p id="ws-help" class="row-sub" *ngIf="help()" style="max-width:70ch;margin-bottom:18px;">
      Voice is taught by example, not description. Cadence drafting gets these as a
      <strong>voice reference only</strong> — tone, length, rhythm — and is told never to reuse a
      sample's phrases, greeting, sign-off or ask; the ask comes from the strategy. Each step sees
      only its own channel's samples, so write LinkedIn samples the way a LinkedIn message reads.
      The <strong>notes</strong> go with each sample: say <em>why</em> it works — that is the part a
      model can generalise from. Samples starting <code>[demo]</code> are ignored, and sales prep
      does not use samples at all. A handful of real messages that landed beats any amount of
      "friendly but professional".
    </p>
    <div *ngIf="!help()" style="margin-bottom:14px;"></div>

    <div class="card" *ngIf="error()" style="border-color:var(--critical);margin-bottom:18px;">
      <strong style="color:var(--critical);">{{ error() }}</strong>
    </div>

    <div class="card" *ngIf="adding()" style="margin-bottom:18px;max-width:780px;">
      <div class="form-grid">
        <label>Channel
          <select class="field" [(ngModel)]="draft.channel">
            <option value="email">email</option>
            <option value="linkedin">linkedin</option>
          </select>
        </label>
        <label>Subject
          <input class="field" [(ngModel)]="draft.subject" placeholder="Quick one about your QA load">
          <span class="row-sub">Email only. Leave blank for LinkedIn.</span>
        </label>
        <label style="grid-column:1/-1;">Body
          <textarea class="field" rows="5" [(ngModel)]="draft.body"
                    placeholder="Saw you're hiring six backend engineers…"></textarea>
        </label>
        <label style="grid-column:1/-1;">Why it works
          <input class="field" [(ngModel)]="draft.notes"
                 placeholder="Short, specific, no adjectives. Opens on their fact, not ours.">
          <span class="row-sub">The most useful field here — it is what generalises.</span>
        </label>
        <div style="grid-column:1/-1;display:flex;gap:10px;align-items:center;">
          <button class="btn btn-primary" (click)="save()" [disabled]="!draft.body.trim()">
            <app-icon name="check" [size]="13" />Add sample
          </button>
          <button class="btn" (click)="adding.set(false)">Cancel</button>
          <span class="row-sub" [style.color]="!draft.body.trim() ? 'var(--warn)' : ''">
            {{ draft.body.trim() ? 'Ready.' : 'A sample needs a body — it is the example.' }}
          </span>
        </div>
      </div>
    </div>

    <div class="sample-grid">
      <div class="card sample" *ngFor="let s of samples()">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">
          <span class="badge" [ngClass]="s.channel === 'email' ? 'badge-accent' : 'badge-warn'">
            {{ s.channel }}
          </span>
          <div style="display:flex;align-items:center;gap:6px;">
            <span class="badge" [ngClass]="s.is_active ? 'badge-good' : 'badge-neutral'">
              {{ s.is_active ? 'in use' : 'inactive' }}
            </span>
            <button class="act-btn" (click)="toggle(s)"
                    [attr.aria-label]="(s.is_active ? 'Deactivate' : 'Reactivate') + ' this sample'"
                    [title]="s.is_active
                      ? 'Take out of the prompt — keeps the sample'
                      : 'Put back into the prompt'">
              <app-icon [name]="s.is_active ? 'pause' : 'play'" [size]="14" />
            </button>

            <!-- Unconditional, unlike services and proof points: nothing stores
                 a reference to a sample, only its text, so removing one leaves
                 no dangling citation. -->
            <button *ngIf="confirming() !== s.id" class="act-btn danger"
                    (click)="confirming.set(s.id)"
                    aria-label="Delete this sample" title="Delete this sample">
              <app-icon name="trash" [size]="14" />
            </button>
            <ng-container *ngIf="confirming() === s.id">
              <button class="act-btn danger" (click)="remove(s)"
                      aria-label="Confirm delete" title="Yes, delete it">
                <app-icon name="check" [size]="14" />
              </button>
              <button class="act-btn" (click)="confirming.set(null)"
                      aria-label="Keep it" title="Keep it">
                <app-icon name="x" [size]="14" />
              </button>
            </ng-container>
          </div>
        </div>
        <p class="row-sub" *ngIf="confirming() === s.id" style="margin:8px 0 0;color:var(--warn);">
          Delete for good?
        </p>
        <strong *ngIf="s.subject" style="display:block;margin:10px 0 4px;font-size:.9rem;">
          {{ s.subject }}
        </strong>
        <p style="white-space:pre-wrap;margin:8px 0 0;font-size:.86rem;">{{ s.body }}</p>
        <p class="row-sub" *ngIf="s.notes" style="margin-top:10px;border-top:1px solid var(--line);padding-top:8px;">
          {{ s.notes }}
        </p>
      </div>
    </div>

    <p class="row-sub" *ngIf="!loading() && samples().length === 0"
       style="text-align:center;padding:26px;">
      No writing samples yet. Add two or three real messages that worked.
    </p>
  `,
  styles: [
    `
      .sec-head { display: flex; justify-content: space-between; align-items: center;
                  gap: 16px; margin-bottom: 4px; }
      .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
      .form-grid label { display: flex; flex-direction: column; gap: 5px; font-size: .84rem; }
      .sample-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                     gap: 14px; }
      .sample { display: flex; flex-direction: column; }
      @media (max-width: 720px) { .form-grid { grid-template-columns: 1fr; } }
    `,
  ],
})
export class WritingSamplesComponent implements OnInit {
  private api = inject(ConfigService);

  samples = signal<WritingSample[]>([]);
  loading = signal(true);
  error = signal<string | null>(null);
  adding = signal(false);
  help = signal(false);
  confirming = signal<string | null>(null);

  draft = { channel: 'email', subject: '', body: '', notes: '' };

  ngOnInit(): void {
    this.load();
  }

  save(): void {
    this.api
      .createWritingSample({
        channel: this.draft.channel,
        // An empty subject is absent, not blank — a LinkedIn sample has none.
        subject: this.draft.subject.trim() || null,
        body: this.draft.body,
        notes: this.draft.notes.trim() || null,
      })
      .subscribe({
        next: () => {
          this.draft = { channel: 'email', subject: '', body: '', notes: '' };
          this.adding.set(false);
          this.load();
        },
        error: (err) => this.error.set(apiError(err, 'Could not add the sample.')),
      });
  }

  toggle(s: WritingSample): void {
    this.api.setWritingSampleActive(s.id, !s.is_active).subscribe({
      next: (updated) =>
        this.samples.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r))),
      error: (err) => this.error.set(apiError(err, 'Could not change the sample.')),
    });
  }

  remove(s: WritingSample): void {
    this.api.deleteWritingSample(s.id).subscribe({
      next: () => {
        this.samples.update((rows) => rows.filter((r) => r.id !== s.id));
        this.confirming.set(null);
      },
      error: (err) => {
        this.error.set(apiError(err, 'Could not delete the sample.'));
        this.confirming.set(null);
      },
    });
  }

  private load(): void {
    this.loading.set(true);
    this.api.writingSamples().subscribe({
      next: (s) => {
        this.samples.set(s);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(apiError(err, 'Could not load writing samples.'));
      },
    });
  }
}
