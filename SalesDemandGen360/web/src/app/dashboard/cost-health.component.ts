import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { ConfigService, Monitoring } from '../core/config.service';
import { apiError } from '../shared/api-error';

/**
 * What the pipeline spent, and what it got stuck on.
 *
 * Filed under Dashboard rather than Settings: what a run costs is read beside
 * the pipeline it belongs to, not beside the knobs that configure it. The
 * menu says "Cost & health" rather than "API cost" because the stuck-run
 * panel is not a cost: a run that silently never finished is the other half
 * of the same question, and naming only the cheaper half is how a screen
 * ends up with a panel nobody expects to find on it.
 *
 * **This screen exists because a spend cap arrived as a surprise.** Tokens
 * were recorded and cheap; grounding is billed per request, is the larger
 * part of a research bill, and was recorded nowhere — so nothing anywhere
 * could have shown a number climbing toward a limit.
 *
 * Two rules it keeps.
 *
 * **Nothing is estimated.** A cost is computed from a stored price and a
 * counted call, or it is shown as unpriced. A screen that guesses the
 * expensive half is how the gap went unnoticed, and a figure that looks
 * authoritative is the one nobody re-checks.
 *
 * **A stuck run is the headline.** The deadlock that cost a fifty-account run
 * its eighteenth account produced no error, no timeout and no log line — only
 * a run that never finished. It is the first thing on the page, and absent
 * when there is none rather than shown as a reassuring zero in a corner.
 */
@Component({
  selector: 'app-cost-health',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  template: `
    <div class="head">
      <div>
        <h2>Cost &amp; health</h2>
        <p class="sub">
          What the pipeline spent, and what it got stuck on. Every figure here is
          counted from this installation's own ledger.
        </p>
      </div>
      <select class="field" style="width:auto" [(ngModel)]="days" (change)="load()">
        <option [value]="1">Last 24 hours</option>
        <option [value]="7">Last 7 days</option>
        <option [value]="30">Last 30 days</option>
      </select>
    </div>

    <p class="err" *ngIf="error()">{{ error() }}</p>
    <p class="muted" *ngIf="loading()">Loading…</p>

    <ng-container *ngIf="data() as d">
      <!-- Stuck runs first, and only when there are any. A permanent "0 stuck"
           tile is a thing the eye learns to skip. -->
      <div class="alarm" *ngIf="d.stuck.length">
        <div>
          <strong>{{ d.stuck.length }} run{{ d.stuck.length === 1 ? '' : 's' }} open and
            not moving.</strong>
          A run with no finish and no activity is the shape a deadlock takes: searches
          paid for, nothing stored, and nothing timing out.
        </div>
        <table class="data" style="margin-top:12px">
          <thead>
            <tr><th>Account</th><th>Stage</th><th class="num">Open for</th><th></th></tr>
          </thead>
          <tbody>
            <tr *ngFor="let s of d.stuck">
              <td>
                <a class="link" [routerLink]="['/accounts', s.account_id]">
                  {{ s.account_name }}
                </a>
              </td>
              <td class="mono">{{ s.stage }} · {{ s.status }}</td>
              <td class="num">{{ minutes(s.open_seconds) }}</td>
              <td class="muted mono">{{ s.run_id.slice(0, 8) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="seclabel" style="margin-top:0">Spend · last {{ d.window_days }} days</div>
      <div class="tiles">
        <div class="tile">
          <h4>Model tokens</h4>
          <div class="v">{{ money(d.token_cost, d.currency) }}</div>
          <p>{{ big(totalIn(d)) }} in · {{ big(totalOut(d)) }} out</p>
        </div>
        <div class="tile" [class.critb]="!d.grounded_since">
          <h4>Grounded searches</h4>
          <div class="v">{{ money(d.grounding_cost, d.currency) }}</div>
          <p *ngIf="d.grounded_since">
            {{ groundedCalls(d) }} calls, billed per request
          </p>
          <p *ngIf="!d.grounded_since">
            <strong>Not yet measured.</strong> The ledger began recording which calls
            carry the search tool on 10 October; nothing before that can be counted
            truthfully.
          </p>
        </div>
        <div class="tile" [class.warnb]="!d.serp_calls">
          <h4>SERP credits</h4>
          <div class="v">{{ d.serp_credits }}</div>
          <p *ngIf="d.serp_calls">across {{ d.serp_calls }} searches</p>
          <p *ngIf="!d.serp_calls">No search bought in this window.</p>
        </div>
        <div class="tile">
          <h4>Model calls</h4>
          <div class="v">{{ d.calls }}</div>
          <p>
            <span [class.danger]="d.failed_calls > 0">{{ d.failed_calls }} failed</span>
            · {{ d.runs_finished }} runs finished
          </p>
        </div>
      </div>

      <p class="note" *ngIf="d.unpriced_models.length">
        <strong>{{ d.unpriced_models.join(', ') }}</strong>
        {{ d.unpriced_models.length === 1 ? 'has' : 'have' }} no row in the price sheet,
        so {{ d.unpriced_models.length === 1 ? 'its' : 'their' }} calls are counted and
        not costed. The total above is short by exactly that — named rather than folded
        in at zero, which would read as free.
      </p>
      <p class="note" *ngIf="d.price_version">
        Priced from sheet v{{ d.price_version }}. Correct it against an invoice and save
        a new version; the old one stays, so last month still adds up the way it did.
      </p>

      <div class="seclabel">By stage</div>
      <div class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>Stage</th><th>Model</th><th class="num">Calls</th>
              <th class="num">Failed</th><th class="num">In</th><th class="num">Out</th>
              <th class="num">Cache</th><th class="num">Avg</th>
              <th class="num">Grounded</th><th class="num">Cost</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let s of d.stages">
              <td><strong>{{ s.scenario }}</strong></td>
              <td class="mono row-sub">{{ s.model }}</td>
              <td class="num">{{ s.calls }}</td>
              <td class="num" [class.danger]="s.failed > 0">{{ s.failed || '—' }}</td>
              <td class="num">{{ big(s.input_tokens) }}</td>
              <td class="num">{{ big(s.output_tokens) }}</td>
              <td class="num">{{ cache(s) }}</td>
              <td class="num">{{ s.avg_seconds }}s</td>
              <td class="num">{{ s.grounded_calls || '—' }}</td>
              <td class="num">{{ s.cost === null ? 'unpriced' : money(s.cost, d.currency) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <ng-container *ngIf="d.failures.length">
        <div class="seclabel">Families that failed</div>
        <div class="table-wrap">
          <table class="data">
            <thead><tr><th class="num">Rows</th><th>Reason</th></tr></thead>
            <tbody>
              <tr *ngFor="let f of d.failures">
                <td class="num">{{ f.rows }}</td>
                <td class="row-sub">{{ f.reason }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="note">
          Grouped by reason rather than listed per account: thirty-nine rows of one
          refusal is one problem, and a list of thirty-nine is a page nobody reads.
        </p>
      </ng-container>

      <div class="empty" *ngIf="!d.calls">
        Nothing ran in this window.
      </div>
    </ng-container>
  `,
  styles: [
    `
      .head { display: flex; justify-content: space-between; align-items: flex-start;
              gap: 20px; margin-bottom: 20px; flex-wrap: wrap; }
      .head h2 { font-size: 1.15rem; margin-bottom: 4px; }
      .sub { color: var(--muted); font-size: 0.85rem; margin: 0; max-width: 72ch; }
      .tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
      @media (max-width: 880px) { .tiles { grid-template-columns: repeat(2, 1fr); } }
      .tile { border: 1px solid var(--border); border-radius: 11px;
              padding: 13px 15px; background: var(--surface); }
      .tile h4 { font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem;
                 letter-spacing: 0.05em; text-transform: uppercase; color: var(--faint);
                 font-weight: 500; margin: 0 0 5px; }
      .tile .v { font-size: 1.3rem; font-weight: 600;
                 font-family: 'IBM Plex Mono', monospace; }
      .tile p { margin: 4px 0 0; font-size: 0.75rem; color: var(--muted); }
      .tile.warnb { box-shadow: inset 3px 0 0 var(--warn); }
      .tile.critb { box-shadow: inset 3px 0 0 var(--critical); }
      .alarm { background: var(--critical-soft); border: 1px solid var(--critical);
               border-radius: 12px; padding: 14px 16px; margin-bottom: 22px;
               font-size: 0.84rem; }
      table.data td.num, table.data th.num { text-align: right;
               font-family: 'IBM Plex Mono', monospace; }
      .link { color: var(--accent); text-decoration: none; font-weight: 500; }
      .danger { color: var(--critical); }
      .err { color: var(--critical); }
    `,
  ],
})
export class CostHealthComponent implements OnInit {
  private api = inject(ConfigService);

  days = 7;
  data = signal<Monitoring | null>(null);
  loading = signal(true);
  error = signal<string | null>(null);

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.monitoring(Number(this.days)).subscribe({
      next: (d) => {
        this.data.set(d);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(apiError(err, 'Could not load monitoring.'));
        this.loading.set(false);
      },
    });
  }

  /** `null` is "no price stored", which is not "free". */
  money(value: number | null, currency: string): string {
    if (value === null) return 'unpriced';
    const symbol = currency === 'USD' ? '$' : `${currency} `;
    return `${symbol}${value.toFixed(2)}`;
  }

  big(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
    if (n >= 1_000) return `${Math.round(n / 1000)}K`;
    return String(n);
  }

  minutes(seconds: number): string {
    const m = Math.floor(seconds / 60);
    return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`;
  }

  cache(s: { input_tokens: number; cache_read_tokens: number }): string {
    if (!s.input_tokens) return '—';
    return `${Math.round((s.cache_read_tokens / s.input_tokens) * 100)}%`;
  }

  totalIn(d: Monitoring): number {
    return d.stages.reduce((n, s) => n + s.input_tokens, 0);
  }

  totalOut(d: Monitoring): number {
    return d.stages.reduce((n, s) => n + s.output_tokens, 0);
  }

  groundedCalls(d: Monitoring): number {
    return d.stages.reduce((n, s) => n + s.grounded_calls, 0);
  }
}
