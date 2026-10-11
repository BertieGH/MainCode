import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';

import {
  Freshness,
  Prep,
  PrepDimension,
  PrepSignal,
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
  imports: [CommonModule, FormsModule, RouterLink],
  template: `
    <p class="err" *ngIf="error()">{{ error() }}</p>
    <p class="muted" *ngIf="loading()">Loading…</p>

    <ng-container *ngIf="prep() as p">
      <div class="crumb">
        <a routerLink="/prep">Sales Prep</a> /
        <a [routerLink]="['/accounts', p.account_id]">{{ p.account_name }}</a> /
        {{ p.contact_name }}
      </div>

      <!--
        One panel, read in a glance before the call: who, how current, and how
        far anything has got. It replaces a header, a four-item legend and two
        full-width sections. The legend went because the tags explain
        themselves and now carry their meaning on hover, and a permanent key
        for four words was the most valuable space on the screen spent on the
        least.
      -->
      <div class="status">
        <div class="status-top">
          <div>
            <h2>{{ p.contact_name }}</h2>
            <div class="row-sub">
              <span *ngIf="p.title">{{ p.title }} · </span>{{ p.account_name }}
              <span class="chip" *ngIf="p.persona_role" [title]="p.persona_basis">
                {{ p.persona_role }}
              </span>
              <span class="ep ep-inf" *ngIf="p.persona_basis.startsWith('inferred')"
                    [title]="EP.inference + ' — ' + p.persona_basis">inferred</span>
              <span class="ep ep-fact" *ngIf="p.persona_basis.startsWith('recorded')"
                    [title]="EP.fact + ' — ' + p.persona_basis">recorded</span>
              <span class="ep ep-unk" *ngIf="p.persona_basis.startsWith('not established')"
                    [title]="EP.unknown + ' — ' + p.persona_basis">no persona</span>
            </div>
            <div class="row-sub danger" *ngIf="p.do_not_contact">
              Do not contact{{ p.do_not_contact_reason ? ' — ' + p.do_not_contact_reason : '' }}
            </div>
          </div>
          <span
            class="badge"
            [ngClass]="p.mode === 'pre_engagement' ? 'badge-neutral' : 'badge-accent'"
            [title]="p.mode === 'pre_engagement'
              ? 'Nothing has been sent, so there is no conversation to be aware of. Decided from the record, not chosen.'
              : 'They have replied. The brief is written around the conversation so far. Decided from the record, not chosen.'">
            {{ p.mode === 'pre_engagement' ? 'pre-engagement' : 'engagement-aware' }}
          </span>
        </div>

        <div class="status-bar">
          <!-- Three ages, because they answer different questions: when we
               last looked, how old what we found is, and whether anyone has
               ever been contacted. The detail is on hover. -->
          <div class="stat" *ngFor="let f of p.freshness"
               [ngClass]="'tone-' + tone(f)" [title]="f.detail">
            <span class="k">{{ label(f.kind) }}</span>
            <span class="v">{{ age(f.days) }}</span>
          </div>

          <div class="stat ladder" [title]="p.engagement.detail">
            <span class="k">Progress</span>
            <span class="rungs">
              <span
                class="rung"
                *ngFor="let r of rungs"
                [class.on]="(p.engagement.counts[r] || 0) > 0"
                [class.blind]="p.engagement.unobservable.includes(r)"
                [title]="rungTitle(p, r)">
                {{ r }}<em *ngIf="(p.engagement.counts[r] || 0) > 0">{{ p.engagement.counts[r] }}</em
                ><em class="q" *ngIf="p.engagement.unobservable.includes(r)">?</em>
              </span>
            </span>
          </div>
        </div>
      </div>

      <!--
        Two columns: the act, and what it rests on. The page used to run
        evidence-first with the plan at the bottom — the order it was built
        in, not the order it is read in. A rep opening this ninety seconds
        before a call wants the plan; the research is what they check when
        something in the plan surprises them.
      -->
      <div class="tabs" role="tablist">
        <button
          class="tab"
          role="tab"
          *ngFor="let t of tabs"
          [attr.aria-selected]="tab() === t.key"
          (click)="tab.set(t.key)">
          {{ t.label }}
        </button>
      </div>

      <section *ngIf="tab() === 'brief'">
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

          <div class="split">
            <div class="col-main">
              <div class="hero">
                <div class="seclabel" style="margin-top:0">What to find out — one thing</div>
                <p class="obj">{{ b.what_to_find_out }}</p>
                <p class="row-sub" *ngIf="b.what_not_to_attempt">
                  Not this call: {{ b.what_not_to_attempt }}
                </p>
                <p class="note" *ngIf="b.problem_is_unproven">
                  <span class="ep ep-hyp" [title]="EP.hypothesis">hypothesis</span> {{ b.problem_is_unproven }}
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

            </div>

            <aside class="col-side">
              <!-- 3 · why now -->
              <div class="seclabel" *ngIf="p.thread">Why this account, why now</div>
              <div class="card" *ngIf="p.thread as t">
                <dl class="kv">
                  <div>
                    <dt>Trigger <span class="ep" [ngClass]="t.without_live_trigger ? 'ep-unk' : 'ep-fact'"
                      [title]="t.without_live_trigger ? EP.unknown : EP.fact">
                      {{ t.without_live_trigger ? 'no live trigger' : 'fact' }}</span></dt>
                    <dd>{{ t.trigger_summary }}</dd>
                  </div>
                  <div>
                    <dt>Hypothesis to test <span class="ep ep-hyp" [title]="EP.hypothesis">hypothesis</span></dt>
                    <dd>{{ t.problem_hypothesis }}</dd>
                  </div>
                  <div>
                    <dt>How we would help <span class="ep ep-fact" [title]="EP.approved">approved positioning</span></dt>
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
              <div class="seclabel">What we know, suspect, and must not assume</div>
              <div class="know">
                <div *ngIf="b.what_we_know.length">
                  <h4><span class="ep ep-fact" [title]="EP.fact">fact</span> What we know</h4>
                  <ul><li *ngFor="let x of b.what_we_know">{{ x }}</li></ul>
                </div>
                <div *ngIf="b.what_we_suspect.length">
                  <h4><span class="ep ep-hyp" [title]="EP.hypothesis">hypothesis</span> What we suspect</h4>
                  <ul><li *ngFor="let x of b.what_we_suspect">{{ x }}</li></ul>
                </div>
                <div *ngIf="b.what_we_do_not_know.length">
                  <h4><span class="ep ep-unk" [title]="EP.unknown">unknown</span> What we do not know</h4>
                  <ul><li *ngFor="let x of b.what_we_do_not_know">{{ x }}</li></ul>
                </div>
                <div class="trap" *ngIf="b.do_not_assume.length">
                  <h4>Do not assume</h4>
                  <ul><li *ngFor="let x of b.do_not_assume">{{ x }}</li></ul>
                </div>
              </div>

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

            </aside>
          </div>
        </ng-container>
      </section>

      <section *ngIf="tab() === 'evidence'">
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
        <details class="ev" *ngFor="let s of p.signals; trackBy: bySignalId">
          <summary>
            <span>
              <strong>{{ s.summary }}</strong>
              <span class="row-sub">{{ s.signal_type }} · {{ s.observed_at }} · {{ age(s.age_days) }} old</span>
            </span>
            <span class="tags">
              <span class="badge badge-good">evidence {{ s.evidence_confidence }}</span>
              <span class="badge badge-neutral">{{ s.strength }}</span>
              <span class="ep ep-hyp" *ngIf="s.is_hypothesis" [title]="EP.hypothesis">hypothesis</span>
            </span>
          </summary>
          <div class="evbody">
            <dl class="kv tight">
              <div>
                <dt>Observed <span class="ep ep-fact" [title]="EP.fact">fact</span></dt>
                <dd>{{ s.summary }}</dd>
              </div>
              <div *ngFor="let e of s.evidence">
                <dt>Source</dt>
                <dd>
                  <a *ngIf="e.source_url" class="link" [href]="e.source_url"
                     target="_blank" rel="noopener">{{ e.source_name || 'source' }}</a>
                  <span *ngIf="!e.source_url">{{ e.source_name || 'source' }}</span>
                  <!-- Two dates, deliberately. When it happened, and when we
                       read it: a nine-month-old post read this morning is
                       fresh research into a stale fact. -->
                  <span class="muted" *ngIf="e.observed_at"> · dated {{ e.observed_at }}</span>
                  <span class="muted" *ngIf="e.retrieved_at">
                    · retrieved {{ e.retrieved_at | date: 'd MMM y' }}</span>
                  <span class="muted" *ngIf="e.reliability != null">
                    · reliability {{ e.reliability }}</span>
                  <blockquote>{{ e.excerpt }}</blockquote>
                </dd>
              </div>
              <div *ngIf="s.business_implication">
                <dt>Interpretation <span class="ep ep-inf" [title]="EP.inference">inference</span></dt>
                <dd>{{ s.business_implication }}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>
                  <span class="badge"
                        [ngClass]="s.lifecycle_state === 'discovered' ? 'badge-good' : 'badge-neutral'">
                    {{ s.lifecycle_state }}
                  </span>
                  <span class="muted" *ngIf="s.expires_in_days != null">
                    · expires in {{ s.expires_in_days }} days</span>
                </dd>
              </div>
            </dl>

            <!--
              The loop closing. Every other verdict here is the model's own;
              a rep who reads the passage and says it is outdated knows
              something no evaluator does. Kept apart from "inaccurate" on
              purpose: one says the refresh cadence is wrong, the other that
              the reading is, and they send you to different code.
            -->
            <div class="marks">
              <span class="row-sub">Rep verdict:</span>
              <button
                class="btn btn-sm"
                *ngFor="let v of signalVerdicts"
                [class.btn-primary]="s.rep_verdict === v"
                [disabled]="judging() === s.id"
                (click)="judge(p, s, v)">
                {{ v.replace('_', ' ') }}
              </button>
              <span class="row-sub" *ngIf="s.rep_verdict">· recorded</span>
            </div>
          </div>
        </details>

        <!-- 6 · proof -->
      </section>

      <section *ngIf="tab() === 'generate'">
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

        <!--
          Three steps in the order they are worth doing: make the picture
          current, add what only the rep knows, then write the brief. Each one
          states what it will do and what it costs before it is bought.
        -->
        <div class="seclabel">Before you generate</div>
        <div class="steps">
          <div class="step">
            <span class="n2">step 1</span>
            <h3>Refresh what we know</h3>
            <p *ngIf="p.last_run">
              Last run {{ age(lastRunDays(p)) }} · {{ p.last_run.planned }} families
              planned, {{ p.last_run.ran }} returned, {{ p.last_run.empty }} empty,
              {{ p.last_run.failed }} failed · {{ p.last_run.evidence }} passages.
            </p>
            <p *ngIf="!p.last_run">No research run has finished for this account.</p>
            <button class="btn" (click)="refresh(p)" [disabled]="busy() || refreshing()">
              {{ refreshing() ? 'Researching…' : 'Refresh · ~$0.09' }}
            </button>
            <p class="row-sub" *ngIf="p.list_ids.length > 1">
              On {{ p.list_ids.length }} lists — the route will ask which one's ICPs
              decide what to look for rather than pick.
            </p>
            <p class="note">
              Adds evidence and never overwrites it. A refresh does not revalidate
              older signals: the oldest here stays
              {{ age(oldestSignalDays(p)) }} old whatever this run finds.
            </p>
          </div>

          <div class="step">
            <span class="n2">step 2</span>
            <h3>Add what you know</h3>
            <p>
              Whatever surfaced when the call was booked — a post, a line from a
              profile, something you were told. Stored as evidence attributed to
              where you saw it, and treated as data, never as instructions.
            </p>
            <textarea
              class="field"
              rows="3"
              placeholder="Paste what you saw — at least a sentence"
              [(ngModel)]="intelText"></textarea>
            <input
              class="field"
              style="margin-top:6px"
              placeholder="Link it was seen at (optional)"
              [(ngModel)]="intelUrl" />
            <button
              class="btn"
              style="margin-top:8px"
              (click)="addIntel(p)"
              [disabled]="intelText.trim().length < 10 || savingIntel()">
              {{ savingIntel() ? 'Saving…' : 'Add intel' }}
            </button>
            <p class="row-sub" *ngIf="intelSaved()">Saved against this contact.</p>
            <p class="note">
              Filed under {{ p.contact_name }}. There is no field for whether this is
              something they said, something you observed or a hunch — it is all
              stored as evidence with its source, so write the distinction into the
              text if it matters.
            </p>
          </div>

          <div class="step">
            <span class="n2">step 3</span>
            <h3>Generate</h3>
            <p>
              Stamped with what it was written from — research age, signal count,
              what had been sent — so a hypothesis that turns out wrong can be read
              back against what was known at the time.
            </p>
            <button class="btn btn-primary" (click)="generate(p)" [disabled]="busy()">
              {{ busy() ? 'Writing…' : p.brief ? 'Generate a new brief' : 'Generate brief' }}
            </button>
            <p class="note">
              Mode is decided from the engagement ladder, not chosen:
              <strong>{{ p.mode === 'pre_engagement' ? 'nothing sent, so pre-engagement' : 'they have replied, so engagement-aware' }}</strong>.
              Regenerating adds a brief; it never replaces one.
            </p>
          </div>
        </div>

        <p class="err" *ngIf="genError()">{{ genError() }}</p>

        <!--
          Stated as the plan it is. Today a regeneration rewrites the whole
          brief, and a table implying otherwise would be the screen lying
          about its own behaviour — the one thing this design exists not to do.
        -->
        <div class="seclabel">What each event should invalidate — not yet built</div>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr><th>Event</th><th>What should be rebuilt</th><th>What should be left</th></tr>
            </thead>
            <tbody>
              <tr *ngFor="let r of invalidation">
                <td>{{ r.event }}</td>
                <td>{{ r.rebuild }}</td>
                <td class="muted">{{ r.keep }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="note">
          Today every regeneration rewrites everything, which costs a call and
          discards rep corrections along with the rest. Selective regeneration is
          the next thing worth building here.
        </p>

        <div class="empty" *ngIf="!p.brief">
          <strong>No brief yet.</strong>
          Generate one from the brief tab.
        </div>

        <ng-container *ngIf="p.brief as b">
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
      </section>

    </ng-container>
  `,
  styles: [
    `
      .crumb { font-size: 0.78rem; color: var(--muted); margin-bottom: 10px; }
      .crumb a { color: var(--accent); text-decoration: none; }
      /* One panel: who, how current, how far. Read before the call, not
         studied — every detail that used to be a paragraph is on hover. */
      .status { background: var(--surface); border: 1px solid var(--border);
                border-radius: 12px; box-shadow: var(--shadow);
                padding: 16px 18px 0; margin-bottom: 24px; }
      .status-top { display: flex; justify-content: space-between;
                    align-items: flex-start; gap: 16px; flex-wrap: wrap; }
      .status-top h2 { font-size: 1.22rem; margin-bottom: 4px; }
      .status-bar { display: flex; flex-wrap: wrap; gap: 0;
                    margin: 14px -18px 0; border-top: 1px solid var(--border); }
      .stat { flex: 1 1 auto; min-width: 128px; padding: 10px 18px;
              border-right: 1px solid var(--border); cursor: help; }
      .stat:last-child { border-right: none; }
      .stat .k { display: block; font-family: 'IBM Plex Mono', monospace;
                 font-size: 0.62rem; letter-spacing: 0.05em; text-transform: uppercase;
                 color: var(--faint); margin-bottom: 3px; }
      .stat .v { font-size: 0.95rem; font-weight: 600; }
      /* The tone is carried on a left edge rather than a whole border: four
         boxed cards in a row read as four warnings. */
      .stat.tone-warn { box-shadow: inset 3px 0 0 var(--warn); }
      .stat.tone-critical { box-shadow: inset 3px 0 0 var(--critical); }
      .stat.ladder { flex: 2 1 320px; }
      .rungs { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 2px; }
      .rung { font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem;
              border: 1px solid var(--border); border-radius: 999px;
              padding: 2px 8px; color: var(--muted); cursor: help; }
      .rung.on { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }
      .rung.blind { border-style: dashed; color: var(--faint); }
      .rung em { font-style: normal; font-weight: 600; margin-left: 4px; }
      .rung em.q { color: var(--faint); }
      .ep { cursor: help; }
      /* The act, and what it rests on. The side column is narrower because
         it is scanned rather than read, and it collapses under the plan on a
         narrow screen rather than above it — the plan is the reason the
         screen exists. */
      /* A sidebar of full-size cards competes with the plan it supports. */
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

  /**
   * Three questions, three tabs: what do I do on this call, what is that
   * based on, and is this brief still current. One long scroll made a rep
   * page past the research to reach the plan and then page back to check it.
   *
   * The status panel stays above all three, because how old the picture is
   * matters whichever one you are reading.
   */
  tab = signal<'brief' | 'evidence' | 'generate'>('brief');
  readonly tabs = [
    { key: 'brief' as const, label: 'The brief' },
    { key: 'evidence' as const, label: 'Evidence & qualification' },
    { key: 'generate' as const, label: 'Generate & feedback' },
  ];

  readonly age = ageLabel;

  /**
   * What each tag means, on hover.
   *
   * These used to sit in a permanent four-item legend across the top of the
   * screen — the most valuable space on the page, spent on four words that
   * explain themselves. The meaning now travels with each tag instead, which
   * is also where someone actually wonders about it.
   */
  readonly EP = {
    fact: 'Fact — read from a source we hold',
    inference: 'Inference — our reading of a fact, not established',
    hypothesis: 'Hypothesis — to test on the call, not to assert',
    unknown: 'Unknown — nothing we hold establishes this',
    approved: 'Approved positioning — cleared for a rep to say',
  };

  /** A rung's tooltip: what it means here, and why it may be unknowable. */
  rungTitle(p: Prep, rung: string): string {
    const why = p.engagement.unobservable_why[rung];
    if (why) return why;
    if (p.engagement.unobservable.includes(rung)) {
      return 'Not observable until outreach events arrive — a zero here means we cannot see it.';
    }
    const n = p.engagement.counts[rung] || 0;
    return n ? `${n} ${rung}` : `Nothing ${rung} yet`;
  }

  judging = signal<string | null>(null);
  readonly signalVerdicts = [
    'accurate',
    'inaccurate',
    'outdated',
    'irrelevant',
    'needs_verification',
  ];

  judge(p: Prep, s: PrepSignal, verdict: string): void {
    this.judging.set(s.id);
    this.api.judgeSignal(s.id, verdict).subscribe({
      next: () => {
        // Patch in place rather than re-reading: a verdict changes one
        // chip, and re-reading the screen would throw away everything else
        // on it. The loop needs `trackBy` for this to hold — without it
        // Angular rebuilds every row and the card the rep was reading
        // closes under them, which is what the first version did.
        this.prep.set({
          ...p,
          signals: p.signals.map((x) =>
            x.id === s.id ? { ...x, rep_verdict: verdict } : x,
          ),
        });
        this.judging.set(null);
      },
      error: (err) => {
        this.genError.set(apiError(err, 'Could not record that verdict.'));
        this.judging.set(null);
      },
    });
  }

  /** Identity, so a changed verdict does not rebuild the row and close it. */
  bySignalId(_i: number, s: PrepSignal): string {
    return s.id;
  }

  refreshing = signal(false);
  savingIntel = signal(false);
  intelSaved = signal(false);
  intelText = '';
  intelUrl = '';

  /**
   * What a regeneration *should* cost, against what it costs today.
   *
   * Shown as the plan it is rather than as behaviour: a table describing
   * selective invalidation on a screen that regenerates wholesale would be
   * the interface lying about itself, which is the one thing this design
   * exists not to do.
   */
  readonly invalidation = [
    {
      event: 'A new relevant signal',
      rebuild: 'Why-now, the hypotheses it touches, the strategy',
      keep: 'Verified company facts',
    },
    {
      event: 'The prospect replies',
      rebuild: 'Mode flips; what to find out, the openings, the objections',
      keep: 'Signals and evidence',
    },
    { event: 'A meeting is booked', rebuild: 'A meeting-specific brief', keep: 'Qualification' },
    {
      event: 'A call transcript arrives',
      rebuild: 'Facts, objections, commitments, next steps',
      keep: 'Firmographics',
    },
    {
      event: 'The rep corrects an inference',
      rebuild: 'Everything that depended on it',
      keep: 'The evidence it came from',
    },
    {
      event: 'A signal expires',
      rebuild: 'Removed from active recommendations',
      keep: 'The evidence row — never deleted',
    },
  ];

  /** Days since the last finished run, for the step-1 line. */
  lastRunDays(p: Prep): number | null {
    if (!p.last_run?.at) return null;
    const ms = Date.now() - new Date(p.last_run.at).getTime();
    return Math.max(0, Math.floor(ms / 86400000));
  }

  /** The oldest live signal, which a refresh does not make younger. */
  oldestSignalDays(p: Prep): number | null {
    const ages = p.signals.map((s) => s.age_days).filter((d): d is number => d !== null);
    return ages.length ? Math.max(...ages) : null;
  }

  refresh(p: Prep): void {
    this.refreshing.set(true);
    this.genError.set(null);
    const one = p.list_ids.length === 1 ? p.list_ids[0] : undefined;
    this.api.refresh(p.account_id, one).subscribe({
      next: () => this.reload(p.contact_id, () => this.refreshing.set(false)),
      error: (err) => {
        this.genError.set(apiError(err, 'Could not refresh research.'));
        this.refreshing.set(false);
      },
    });
  }

  addIntel(p: Prep): void {
    this.savingIntel.set(true);
    this.genError.set(null);
    this.api
      .addIntel(p.account_id, {
        text: this.intelText.trim(),
        url: this.intelUrl.trim() || null,
        contact_id: p.contact_id,
      })
      .subscribe({
        next: () => {
          this.intelText = '';
          this.intelUrl = '';
          this.intelSaved.set(true);
          this.reload(p.contact_id, () => this.savingIntel.set(false));
        },
        error: (err) => {
          this.genError.set(apiError(err, 'Could not save that.'));
          this.savingIntel.set(false);
        },
      });
  }

  /** Re-read the whole screen. Anything that adds evidence moves the
   *  freshness panel and the staleness flag as well as its own section. */
  private reload(contactId: string, done: () => void): void {
    this.api.forContact(contactId).subscribe({
      next: (fresh) => {
        this.prep.set(fresh);
        done();
      },
      error: () => done(),
    });
  }

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
