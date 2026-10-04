import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ConfigService, SalesRules } from '../core/config.service';
import { apiError } from '../shared/api-error';

/**
 * Sales rules — the versioned-singleton pattern, made visible.
 *
 * The save button says "Save as new version" rather than "Save" on purpose.
 * The system never mutates a config row: a qualification computed against
 * version 4 has to stay explainable after version 5 exists.
 */
@Component({
  selector: 'app-sales-rules',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <h2 style="font-size:1.15rem;margin-bottom:4px;">Sales rules</h2>
    <p class="row-sub" style="margin-bottom:22px;max-width:70ch;">
      Read by qualification, strategy, outreach, and execution. Saving creates a new
      version and deactivates the previous one — nothing is edited in place.
    </p>

    <div *ngIf="error()" class="card" style="border-color:var(--critical);margin-bottom:18px;">
      <strong style="color:var(--critical);">{{ error() }}</strong>
      <p class="row-sub" style="margin:6px 0 0;">
        If no active rules exist yet, saving this form creates version 1.
      </p>
    </div>

    <div class="card" style="max-width:720px;">
      <div class="grid">
        <label>Priority threshold
          <input class="field" type="number" [(ngModel)]="form.priority_threshold" min="0" max="100">
          <span class="row-sub">Minimum Opportunity Priority to reach Strategy</span>
        </label>

        <label>Persona weight threshold
          <input class="field" type="number" [(ngModel)]="form.persona_weight_threshold" min="0" max="100">
          <span class="row-sub">Minimum weight for a thread to activate</span>
        </label>

        <label>Max concurrent threads
          <input class="field" type="number" [(ngModel)]="form.max_concurrent_threads" min="1" max="10">
          <span class="row-sub">Per account, across every campaign</span>
        </label>

        <label>Thread start offset (days)
          <input class="field" type="number" [(ngModel)]="form.thread_start_offset_days" min="0" max="30">
          <span class="row-sub">Stagger between threads on one account</span>
        </label>

        <label>Sample rate
          <input class="field" type="number" [(ngModel)]="form.sample_rate" min="0.05" max="1" step="0.05">
          <span class="row-sub">
            Proportion of clean threads read before the batch is accepted.
            Starts high for a new service and persona combination.
          </span>
        </label>
      </div>

      <div style="display:flex;gap:10px;align-items:center;margin-top:20px;
                  padding-top:16px;border-top:1px solid var(--border);">
        <button class="btn btn-primary" (click)="save()" [disabled]="saving()">
          {{ saving() ? 'Saving…' : 'Save as new version' }}
        </button>
        <span class="row-sub" *ngIf="current() as c">
          Currently on version {{ c.version }} · saving creates version {{ c.version + 1 }}
        </span>
        <span class="badge badge-good" *ngIf="saved()">Saved</span>
      </div>
    </div>
  `,
  styles: [
    `
      .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
      label { display: flex; flex-direction: column; gap: 6px; font-size: .84rem; }
      @media (max-width: 720px) { .grid { grid-template-columns: 1fr; } }
    `,
  ],
})
export class SalesRulesComponent implements OnInit {
  private api = inject(ConfigService);

  current = signal<SalesRules | null>(null);
  saving = signal(false);
  saved = signal(false);
  error = signal<string | null>(null);

  form = {
    priority_threshold: 65,
    persona_weight_threshold: 50,
    max_concurrent_threads: 2,
    thread_start_offset_days: 3,
    sample_rate: 0.4,
    signal_ttl_days: {} as Record<string, number>,
    no_go: {},
    compliance: {},
  };

  ngOnInit(): void {
    this.api.getSalesRules().subscribe({
      next: (r) => {
        this.current.set(r);
        this.form = {
          priority_threshold: r.priority_threshold,
          persona_weight_threshold: r.persona_weight_threshold,
          max_concurrent_threads: r.max_concurrent_threads,
          thread_start_offset_days: r.thread_start_offset_days,
          sample_rate: r.sample_rate,
          signal_ttl_days: r.signal_ttl_days ?? {},
          no_go: r.no_go ?? {},
          compliance: r.compliance ?? {},
        };
      },
      error: (err) =>
        this.error.set(apiError(err, 'No active sales rules found.')),
    });
  }

  save(): void {
    this.saving.set(true);
    this.saved.set(false);
    this.error.set(null);
    this.api.saveSalesRules(this.form).subscribe({
      next: (r) => {
        this.current.set(r);
        this.saving.set(false);
        this.saved.set(true);
      },
      error: (err) => {
        this.saving.set(false);
        this.error.set(apiError(err, 'Save failed.'));
      },
    });
  }
}
