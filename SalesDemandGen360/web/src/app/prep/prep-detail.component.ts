import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import {
  Freshness,
  Prep,
  PrepDimension,
  PrepService,
  ageLabel,
  ageTone,
  freshnessOf,
} from '../core/prep.service';
import { apiError } from '../shared/api-error';

/**
 * One contact's prep brief.
 *
 * **Everything on this screen is labelled with what kind of claim it is.** The
 * more personalised a brief reads, the easier it is to mistake a plausible
 * story for a finding, so a fact read from a source, our reading of that fact,
 * a hypothesis to test, and a thing nobody established are visually distinct
 * throughout rather than disclaimed once at the bottom.
 *
 * The generated half — objective, opening, questions, objections — is not here
 * yet; the stage that writes it comes next. What is here is everything the
 * database already knows, which is more than the account screen shows and
 * enough to prepare from.
 */
@Component({
  selector: 'app-prep-detail',
  standalone: true,
  imports: [CommonModule, RouterLink],
  template: `
    <p class="err" *ngIf="error()">{{ error() }}</p>
    <p class="muted" *ngIf="loading()">Loading…</p>

    <ng-container *ngIf="prep() as p">
      <div class="crumb">
        <a routerLink="/prep">Sales Prep</a> /
        <a [routerLink]="['/accounts', p.account_id]">{{ p.account_name }}</a> /
        {{ p.contact_name }}
      </div>

      <div class="head">
        <div>
          <h2>{{ p.contact_name }}</h2>
          <div class="row-sub">
            <span *ngIf="p.title">{{ p.title }} · </span>{{ p.account_name }}
            <span class="chip" *ngIf="p.persona_role">{{ p.persona_role }}</span>
            <span class="ep ep-inf" *ngIf="p.persona_basis.startsWith('inferred')">inference</span>
            <span class="ep ep-fact" *ngIf="p.persona_basis.startsWith('recorded')">fact</span>
            <span class="ep ep-unk" *ngIf="p.persona_basis.startsWith('not established')">unknown</span>
            <span class="muted"> {{ p.persona_basis }}</span>
          </div>
          <div class="row-sub danger" *ngIf="p.do_not_contact">
            Do not contact{{ p.do_not_contact_reason ? ' — ' + p.do_not_contact_reason : '' }}
          </div>
        </div>
        <div class="modebadge">
          <span class="badge" [ngClass]="p.mode === 'pre_engagement' ? 'badge-neutral' : 'badge-accent'">
            {{ p.mode === 'pre_engagement' ? 'pre-engagement' : 'engagement-aware' }}
          </span>
          <div class="row-sub">decided from what was actually sent</div>
        </div>
      </div>

      <div class="ep-key">
        <span><span class="ep ep-fact">fact</span> read from a source</span>
        <span><span class="ep ep-inf">inference</span> our reading of a fact</span>
        <span><span class="ep ep-hyp">hypothesis</span> to test on the call</span>
        <span><span class="ep ep-unk">unknown</span> not established</span>
      </div>

      <!-- 1 · three freshnesses -->
      <div class="seclabel">Freshness — three questions, not one</div>
      <div class="fresh">
        <div class="f" *ngFor="let f of p.freshness" [ngClass]="'tone-' + tone(f)">
          <h4>{{ label(f.kind) }}</h4>
          <div class="v">{{ age(f.days) }}</div>
          <p>{{ f.detail }}</p>
        </div>
      </div>

      <!-- 2 · the ladder -->
      <div class="seclabel">What has actually happened</div>
      <div class="card">
        <p class="lede">{{ p.engagement.detail }}</p>
        <div class="rungs">
          <span
            class="rung"
            *ngFor="let r of rungs"
            [class.on]="(p.engagement.counts[r] || 0) > 0"
            [class.blind]="p.engagement.unobservable.includes(r)">
            {{ r }}
            <em *ngIf="(p.engagement.counts[r] || 0) > 0">{{ p.engagement.counts[r] }}</em>
            <em class="q" *ngIf="p.engagement.unobservable.includes(r)">?</em>
          </span>
        </div>
        <p class="note" *ngFor="let u of p.engagement.unobservable">
          <strong>{{ u }}</strong>
          — {{ p.engagement.unobservable_why[u] || 'not observable until outreach events arrive.' }}
        </p>
      </div>

      <!-- 3 · why now -->
      <div class="seclabel" *ngIf="p.thread">Why this account, why now</div>
      <div class="card" *ngIf="p.thread as t">
        <dl class="kv">
          <div>
            <dt>Trigger <span class="ep" [ngClass]="t.without_live_trigger ? 'ep-unk' : 'ep-fact'">
              {{ t.without_live_trigger ? 'no live trigger' : 'fact' }}</span></dt>
            <dd>{{ t.trigger_summary }}</dd>
          </div>
          <div>
            <dt>Hypothesis to test <span class="ep ep-hyp">hypothesis</span></dt>
            <dd>{{ t.problem_hypothesis }}</dd>
          </div>
          <div>
            <dt>How we would help <span class="ep ep-fact">approved positioning</span></dt>
            <dd>{{ t.positioning }}</dd>
          </div>
          <div>
            <dt>The ask</dt>
            <dd>{{ t.cta }}</dd>
          </div>
        </dl>
        <p class="note" *ngIf="t.strategy_confidence !== null">
          Strategy confidence {{ t.strategy_confidence }} — how well this approach fits the
          context. Not whether the problem is real, and not how reliable the evidence is.
        </p>
        <p class="note" *ngIf="t.avoid_list.length">
          Avoid: {{ t.avoid_list.join(', ') }}
        </p>
      </div>

      <!-- 4 · qualification unpacked -->
      <div class="seclabel">Qualification — six dimensions, not one number</div>
      <div class="card" *ngIf="p.qualification as q">
        <div class="scorehead">
          <div>
            <span class="score">{{ q.priority_score }}</span>
            <span class="badge badge-neutral">{{ q.priority_band }}</span>
          </div>
          <span class="chip">scoring_config v{{ q.scoring_config_version }} · arithmetic, not a model</span>
        </div>

        <div class="dim" *ngFor="let d of q.dimensions">
          <span class="nm">{{ d.dimension }}</span>
          <span class="bar">
            <i [style.width.%]="barWidth(d)" [class.zero]="d.score === 0"></i>
          </span>
          <span class="sc">{{ d.score }}</span>
          <span class="bs">
            <span class="badge" [ngClass]="basisTone(d)">{{ basisLabel(d) }}</span>
          </span>
          <span class="why">{{ d.reason }}</span>
        </div>

        <p class="note" *ngIf="q.assessed_average !== null && q.unassessed.length">
          <strong>The headline is not a verdict on the account.</strong>
          {{ q.unassessed.join(' and ') }}
          {{ q.unassessed.length === 1 ? 'was' : 'were' }} scored with nothing to go on —
          an absence, not a low score. Across the {{ q.dimensions.length - q.unassessed.length }}
          dimensions that could be assessed, this account averages
          <strong>{{ q.assessed_average }}</strong>, against a headline of {{ q.priority_score }}.
        </p>
        <p class="note">
          MAN: money <strong>{{ q.man['money'] || 'unknown' }}</strong> ·
          authority <strong>{{ q.man['authority'] || 'unknown' }}</strong> ·
          need <strong>{{ q.man['need'] || 'unknown' }}</strong>
        </p>
      </div>

      <!-- 5 · evidence -->
      <div class="seclabel">Intelligence supporting this brief · {{ p.signals.length }} live</div>
      <div class="empty" *ngIf="!p.signals.length">
        No live signal. A brief here would argue from no trigger at all.
      </div>
      <details class="ev" *ngFor="let s of p.signals">
        <summary>
          <span>
            <strong>{{ s.summary }}</strong>
            <span class="row-sub">{{ s.signal_type }} · {{ s.observed_at }} · {{ age(s.age_days) }} old</span>
          </span>
          <span class="tags">
            <span class="badge badge-good">evidence {{ s.evidence_confidence }}</span>
            <span class="badge badge-neutral">{{ s.strength }}</span>
            <span class="ep ep-hyp" *ngIf="s.is_hypothesis">hypothesis</span>
          </span>
        </summary>
        <div class="evbody">
          <dl class="kv tight">
            <div *ngIf="s.business_implication">
              <dt>What it may mean <span class="ep ep-inf">inference</span></dt>
              <dd>{{ s.business_implication }}</dd>
            </div>
            <div *ngIf="s.sources.length">
              <dt>Sources</dt>
              <dd>{{ s.sources.join(' · ') }}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{{ s.lifecycle_state }}<span *ngIf="s.expires_at"> · expires {{ s.expires_at }}</span></dd>
            </div>
          </dl>
        </div>
      </details>

      <!-- 6 · proof -->
      <div class="seclabel">What we can credibly offer · {{ p.proof.length }} approved</div>
      <div class="empty" *ngIf="!p.proof.length">
        No approved proof point. Describe the capability and claim no result —
        no proof is better than unsupported proof.
      </div>
      <div class="card" *ngIf="p.proof.length">
        <div class="proof" *ngFor="let pp of p.proof">
          <div>
            <strong>{{ pp.title }}</strong>
            <span class="chip">{{ pp.kind }}</span>
            <span class="badge badge-warn" *ngIf="!pp.has_metric">no measured outcome</span>
          </div>
          <p class="row-sub">{{ pp.body }}</p>
          <p class="note" *ngIf="!pp.has_metric">
            Nothing measured is attached, so this may describe what we do and must not
            claim a result.
          </p>
        </div>
      </div>

      <!-- the generated half -->
      <div class="seclabel">The call game plan</div>

      <div class="empty" *ngIf="!p.brief">
        <strong>Not generated yet.</strong>
        The objective, the openings, the questions and the objections are written on
        demand — one contact at a time, never in advance, because a brief written today
        for a call in a fortnight argues from a picture that predates the conversation.
        <div style="margin-top:12px">
          <button class="btn btn-primary" (click)="generate(p)" [disabled]="busy()">
            {{ busy() ? 'Writing…' : 'Generate the brief' }}
          </button>
        </div>
      </div>
      <p class="err" *ngIf="genError()">{{ genError() }}</p>

      <ng-container *ngIf="p.brief as b">
        <div class="stale" *ngIf="p.brief_is_stale">
          <div>
            <strong>Written before the latest facts.</strong>
            Something has changed since this was generated — a signal, a send, or a
            reply. It is not wrong, it is older than what is above it.
          </div>
          <button class="btn btn-sm" (click)="generate(p)" [disabled]="busy()">
            {{ busy() ? 'Writing…' : 'Regenerate' }}
          </button>
        </div>

        <div class="hero">
          <div class="seclabel" style="margin-top:0">What to find out — one thing</div>
          <p class="obj">{{ b.what_to_find_out }}</p>
          <p class="row-sub" *ngIf="b.what_not_to_attempt">
            Not this call: {{ b.what_not_to_attempt }}
          </p>
          <p class="note" *ngIf="b.problem_is_unproven">
            <span class="ep ep-hyp">hypothesis</span> {{ b.problem_is_unproven }}
          </p>

          <ng-container *ngIf="b.openings.length">
            <div class="seclabel">Opening — pick one, say it out loud first</div>
            <div class="optpick">
              <button
                *ngFor="let o of b.openings; let i = index"
                [attr.aria-pressed]="i === opening()"
                (click)="opening.set(i)">
                {{ o.label }}
              </button>
            </div>
            <div class="open-line">{{ b.openings[opening()].words }}</div>
            <p class="row-sub">
              <strong>Use when:</strong> {{ b.openings[opening()].use_when }}
            </p>
            <p class="row-sub">
              <strong>Why it works:</strong> {{ b.openings[opening()].why_it_works }}
            </p>
          </ng-container>

          <ng-container *ngIf="b.listen_for.length">
            <div class="seclabel">Listen for — findings, not expected answers</div>
            <div class="chips">
              <span class="chip" *ngFor="let l of b.listen_for">{{ l }}</span>
            </div>
          </ng-container>

          <ng-container *ngIf="b.next_steps.length">
            <div class="seclabel">Next step — conditional on what you hear</div>
            <div class="step2" *ngFor="let n of b.next_steps">
              <strong>{{ n.condition }}</strong>
              <span>{{ n.action }}</span>
            </div>
          </ng-container>
        </div>

        <div class="seclabel">What we know, suspect, and must not assume</div>
        <div class="know">
          <div *ngIf="b.what_we_know.length">
            <h4><span class="ep ep-fact">fact</span> What we know</h4>
            <ul><li *ngFor="let x of b.what_we_know">{{ x }}</li></ul>
          </div>
          <div *ngIf="b.what_we_suspect.length">
            <h4><span class="ep ep-hyp">hypothesis</span> What we suspect</h4>
            <ul><li *ngFor="let x of b.what_we_suspect">{{ x }}</li></ul>
          </div>
          <div *ngIf="b.what_we_do_not_know.length">
            <h4><span class="ep ep-unk">unknown</span> What we do not know</h4>
            <ul><li *ngFor="let x of b.what_we_do_not_know">{{ x }}</li></ul>
          </div>
          <div class="trap" *ngIf="b.do_not_assume.length">
            <h4>Do not assume</h4>
            <ul><li *ngFor="let x of b.do_not_assume">{{ x }}</li></ul>
          </div>
        </div>

        <div class="seclabel" *ngIf="b.discovery_questions.length">
          Questions — ranked, with what each one changes
        </div>
        <div class="q" *ngFor="let q of b.discovery_questions; let i = index">
          <div class="qn">
            <p class="ask">{{ q.question }}</p>
            <span class="badge badge-accent">{{ i + 1 }}</span>
          </div>
          <dl>
            <dt>Listening for</dt><dd>{{ q.listening_for }}</dd>
            <dt>Changes</dt><dd>{{ q.changes }}</dd>
          </dl>
          <div class="branch" *ngIf="q.branches.length">
            <div *ngFor="let br of q.branches">{{ br }}</div>
          </div>
        </div>

        <ng-container *ngIf="b.objections.length">
          <div class="seclabel">Objections</div>
          <div class="table-wrap">
            <table class="data">
              <thead>
                <tr><th>Objection</th><th>Type</th><th>Response</th><th>Follow-up</th></tr>
              </thead>
              <tbody>
                <tr *ngFor="let o of b.objections">
                  <td>{{ o.objection }}</td>
                  <td>
                    <span
                      class="badge"
                      [ngClass]="o.kind === 'observed' ? 'badge-accent' : 'badge-neutral'">
                      {{ o.kind }}
                    </span>
                  </td>
                  <td>{{ o.pre_empt }}</td>
                  <td class="muted">{{ o.follow_up }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="note">
            Anticipated is kept apart from observed so you never defend against a concern
            nobody raised.
          </p>
        </ng-container>

        <ng-container *ngIf="b.already_said.length || b.their_replies.length">
          <div class="seclabel">What we already said, and what came back</div>
          <div class="card">
            <ul><li *ngFor="let s of b.already_said">{{ s }}</li></ul>
            <blockquote *ngFor="let r of b.their_replies">{{ r }}</blockquote>
          </div>
        </ng-container>

        <div class="seclabel">After the call</div>
        <div class="card">
          <p class="row-sub" style="margin-top:0">
            The hypothesis verdict is the measure worth watching. Hypotheses that keep
            being rejected mean the interpretation or the account selection is wrong —
            not the writing.
          </p>
          <div class="verdict">
            <div>
              <div class="seclabel" style="margin-top:0">Did the hypothesis hold?</div>
              <button
                class="btn btn-sm"
                *ngFor="let v of verdicts"
                [class.btn-primary]="p.hypothesis_verdict === v.key"
                (click)="record(p, { hypothesis_verdict: v.key })">
                {{ v.label }}
              </button>
            </div>
            <div>
              <div class="seclabel" style="margin-top:0">Outcome</div>
              <button
                class="btn btn-sm"
                *ngFor="let o of outcomes"
                [class.btn-primary]="p.outcome === o.key"
                (click)="record(p, { outcome: o.key })">
                {{ o.label }}
              </button>
            </div>
          </div>
        </div>
      </ng-container>

      <div class="exports">
        <button class="btn" disabled>Export .pptx</button>
        <button class="btn" disabled>Export .docx</button>
        <button class="btn" disabled>Export .pdf</button>
        <span class="row-sub">Enabled once a brief exists.</span>
      </div>
    </ng-container>
  `,
  styles: [
    `
      .crumb { font-size: 0.78rem; color: var(--muted); margin-bottom: 10px; }
      .crumb a { color: var(--accent); text-decoration: none; }
      .head { display: flex; justify-content: space-between; align-items: flex-start;
              gap: 20px; margin-bottom: 18px; flex-wrap: wrap; }
      .head h2 { font-size: 1.25rem; margin-bottom: 5px; }
      .modebadge { text-align: right; }
      .fresh { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
      @media (max-width: 760px) { .fresh { grid-template-columns: 1fr; } }
      .fresh .f { border: 1px solid var(--border); border-radius: 11px;
                  padding: 13px 15px; background: var(--surface); }
      .fresh .f.tone-warn { border-color: var(--warn); }
      .fresh .f.tone-critical { border-color: var(--critical); }
      .fresh .f h4 { margin: 0 0 6px; font-size: 0.72rem;
                     font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.05em;
                     text-transform: uppercase; color: var(--faint); font-weight: 500; }
      .fresh .f .v { font-size: 1.02rem; font-weight: 600; }
      .fresh .f p { margin: 5px 0 0; font-size: 0.76rem; color: var(--muted); }
      .lede { margin: 0 0 14px; font-size: 0.9rem; }
      .rungs { display: flex; gap: 7px; flex-wrap: wrap; margin-bottom: 12px; }
      .rung { font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem;
              border: 1px solid var(--border); border-radius: 999px;
              padding: 4px 11px; color: var(--muted); }
      .rung.on { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }
      .rung.blind { border-style: dashed; }
      .rung em { font-style: normal; font-weight: 600; margin-left: 5px; }
      .rung em.q { color: var(--faint); }
      .kv { margin: 0; display: grid; gap: 13px; }
      .kv.tight { gap: 8px; }
      .kv dt { font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem;
               letter-spacing: 0.05em; text-transform: uppercase; color: var(--faint);
               margin-bottom: 4px; display: flex; gap: 8px; align-items: center; }
      .kv dd { margin: 0; font-size: 0.86rem; line-height: 1.5; }
      .scorehead { display: flex; justify-content: space-between; align-items: center;
                   gap: 14px; margin-bottom: 14px; flex-wrap: wrap; }
      .score { font-size: 1.5rem; font-weight: 600;
               font-family: 'IBM Plex Mono', monospace; margin-right: 8px; }
      .dim { display: flex; align-items: center; gap: 11px; padding: 9px 0;
             border-bottom: 1px solid var(--border); flex-wrap: wrap; }
      .dim:last-of-type { border-bottom: none; }
      .dim .nm { width: 108px; flex: 0 0 auto; font-size: 0.82rem;
                 font-weight: 500; text-transform: capitalize; }
      .dim .bar { flex: 1; height: 7px; background: var(--mono-bg);
                  border-radius: 999px; overflow: hidden; min-width: 60px; }
      .dim .bar i { display: block; height: 100%; border-radius: 999px; background: var(--accent); }
      .dim .bar i.zero { background: var(--critical); }
      .dim .sc { width: 44px; flex: 0 0 auto; text-align: right;
                 font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; }
      .dim .bs { width: 124px; flex: 0 0 auto; }
      .dim .why { flex: 0 0 100%; font-size: 0.76rem; color: var(--muted); }
      @media (min-width: 761px) { .dim .why { padding-left: 119px; } }
      .ev { border: 1px solid var(--border); border-radius: 11px;
            margin-bottom: 10px; overflow: hidden; background: var(--surface); }
      .ev summary { padding: 12px 15px; cursor: pointer; display: flex;
                    gap: 10px; align-items: center; justify-content: space-between;
                    flex-wrap: wrap; }
      .ev .tags { display: flex; gap: 6px; flex-wrap: wrap; }
      .ev .evbody { padding: 0 15px 15px; }
      .proof { padding: 11px 0; border-bottom: 1px solid var(--border); }
      .proof:last-child { border-bottom: none; }
      .proof p { margin: 5px 0 0; }
      .exports { display: flex; gap: 8px; flex-wrap: wrap;
                 align-items: center; margin: 26px 0 0; }
      .danger { color: var(--critical); }
      .err { color: var(--critical); }
    `,
  ],
})
export class PrepDetailComponent implements OnInit {
  private api = inject(PrepService);
  private route = inject(ActivatedRoute);

  prep = signal<Prep | null>(null);
  loading = signal(true);
  error = signal<string | null>(null);
  busy = signal(false);
  genError = signal<string | null>(null);
  /** Which opening the rep has picked. Their choice, not the model's. */
  opening = signal(0);

  readonly age = ageLabel;

  readonly verdicts = [
    { key: 'confirmed', label: 'Confirmed' },
    { key: 'rejected', label: 'Rejected' },
    { key: 'partly', label: 'Partly' },
    { key: 'not_discussed', label: "Didn't come up" },
  ];
  readonly outcomes = [
    { key: 'meeting_booked', label: 'Meeting booked' },
    { key: 'follow_up', label: 'Follow-up' },
    { key: 'no_need_now', label: 'No need now' },
    { key: 'not_interested', label: 'Not interested' },
  ];

  generate(p: Prep): void {
    this.busy.set(true);
    this.genError.set(null);
    this.api.generate(p.contact_id).subscribe({
      next: () => {
        // Re-read rather than patching the brief in: generating also moves
        // the staleness flag and the stored mode, and a half-updated screen
        // is how a stale brief starts looking fresh.
        this.api.forContact(p.contact_id).subscribe({
          next: (fresh) => {
            this.prep.set(fresh);
            this.opening.set(0);
            this.busy.set(false);
          },
          error: () => this.busy.set(false),
        });
      },
      error: (err) => {
        this.genError.set(apiError(err, 'Could not write the brief.'));
        this.busy.set(false);
      },
    });
  }

  record(p: Prep, body: { hypothesis_verdict?: string; outcome?: string }): void {
    if (!p.brief_id) return;
    this.api.verdict(p.brief_id, body).subscribe({
      next: () => this.prep.set({ ...p, ...body }),
      error: (err) => this.genError.set(apiError(err, 'Could not record that.')),
    });
  }
  /** `delivered` is shown although it is never counted — see the service. */
  readonly rungs = ['drafted', 'approved', 'sent', 'delivered', 'replied'];

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (!id) {
      this.error.set('No contact in the URL.');
      this.loading.set(false);
      return;
    }
    this.api.forContact(id).subscribe({
      next: (p) => {
        this.prep.set(p);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(apiError(err, 'Could not load this brief.'));
        this.loading.set(false);
      },
    });
  }

  label(kind: Freshness['kind']): string {
    return kind === 'research'
      ? 'Last looked'
      : kind === 'signals'
        ? 'Newest signal'
        : 'Engagement';
  }

  tone(f: Freshness): string {
    return ageTone(f.kind, f.days);
  }

  /** A zero still needs a sliver, or the row reads as a missing bar. */
  barWidth(d: PrepDimension): number {
    return d.score === 0 ? 2 : Math.max(2, Math.min(100, d.score));
  }

  basisLabel(d: PrepDimension): string {
    if (d.basis === 'no_evidence') return 'nothing to compare';
    if (d.basis === 'outreach') return 'from outreach';
    if (d.basis === 'contacts') return 'from contacts';
    if (d.basis === 'evidence') {
      return d.evidence_count === 1 ? '1 evidence row' : d.evidence_count + ' evidence rows';
    }
    return d.basis;
  }

  basisTone(d: PrepDimension): string {
    if (d.basis === 'evidence') return 'badge-good';
    if (d.basis === 'contacts') return 'badge-accent';
    return d.basis === 'no_evidence' ? 'badge-critical' : 'badge-warn';
  }
}
