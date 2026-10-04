import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import {
  CoverageRow,
  Intelligence,
  MatrixCell,
  PipelineService,
  SignalRow,
} from '../core/pipeline.service';
import { NO_SORT, SortState, SortableDirective } from '../shared/sortable';
import { sortRows } from '../shared/client-sort';
import { IconComponent } from '../shared/icon.component';
import { apiError } from '../shared/api-error';
import { CONTACT_COLUMNS } from '../shared/contact-columns';
import { DataTableComponent } from '../shared/data-table.component';
import { Contact, ListsService } from '../core/lists.service';

type Tab = 'contacts' | 'signals' | 'coverage' | 'qualification' | 'outreach';

/** Reads a dimension's basis. A free function so the template stays readable. */
function basis_is(dim: { basis: string }, value: string): boolean {
  return dim.basis === value;
}

/**
 * One account, in pipeline order: what was found, what was looked for, what it
 * came to, and who we decided to talk to.
 *
 * Every claim on this screen is expandable to its citation. That is the point
 * of the whole system — a rep who cannot check a claim stops believing all of
 * them, including the true ones.
 */
@Component({
  selector: 'app-account-detail',
  standalone: true,
  imports: [CommonModule, RouterLink, IconComponent, SortableDirective, DataTableComponent],
  template: `
    <a routerLink="/lists" class="back"><app-icon name="back" [size]="14" />All lists</a>

    <div *ngIf="error()" class="card" style="border-color:var(--critical);margin:14px 0;">
      <strong style="color:var(--critical);">{{ error() }}</strong>
    </div>

    <ng-container *ngIf="data() as d">
      <div class="head">
        <div>
          <h2>{{ d.account_name }}</h2>
          <p class="row-sub">
            {{ d.domain ?? 'no domain' }}
            <span *ngIf="d.context_version"> · context v{{ d.context_version }}</span>
          </p>
        </div>
        <div *ngIf="d.qualification as q" class="score">
          <span class="badge" [ngClass]="bandClass(q.priority_band)">{{ q.priority_band }}</span>
          <strong>{{ q.priority_score }}</strong>
          <span class="row-sub">config v{{ q.scoring_config_version }}</span>
        </div>
      </div>

      <div class="tabs">
        <button *ngFor="let t of tabs" class="tab" [class.on]="tab() === t.key"
                (click)="tab.set(t.key)" [attr.aria-current]="tab() === t.key">
          {{ t.label }}
          <span class="count">{{ countFor(t.key, d) }}</span>
        </button>
      </div>

      <!-- contacts -->
      <ng-container *ngIf="tab() === 'contacts'">
        <p class="row-sub" style="max-width:70ch;margin-bottom:12px;">
          Everyone known here, and how reachable they are. <strong>Only
          <code>verified</code> may be written to</strong> — a provider's own
          guess arrives as <code>risky</code> and is shown as such rather than
          quietly counted as an address.
        </p>

        <p class="row-sub" *ngIf="!contacts().length && !loadingContacts()">
          No contacts at this account yet. They arrive from a contact-grain
          import, or from enrichment on a list this account belongs to.
        </p>

        <app-data-table *ngIf="contacts().length"
                        table="contacts"
                        noun="contacts"
                        emptyText="No contacts at this account yet."
                        [columns]="contactColumns"
                        [data]="contacts()"
                        [sort]="contactSort()"
                        (sortChange)="onContactSort($event)"
                        [cell]="contactCell">
        </app-data-table>

        <ng-template #contactCell let-row let-column="column" let-value="value">
          <ng-container [ngSwitch]="column.key">
            <span *ngSwitchCase="'email_status'" class="badge"
                  [ngClass]="emailBadge(value)">{{ value }}</span>
            <a *ngSwitchCase="'linkedin_url'" class="link" [href]="row.linkedin_url"
               target="_blank" rel="noopener">
              {{ row.linkedin_url ? 'profile' : '—' }}
            </a>
            <ng-container *ngSwitchDefault>{{ value }}</ng-container>
          </ng-container>
        </ng-template>
      </ng-container>

      <!-- signals -->
      <ng-container *ngIf="tab() === 'signals'">
        <p class="row-sub" style="max-width:70ch;margin-bottom:14px;">
          Every signal cites the evidence it rests on. A signal whose citation could not be resolved
          was dropped before it reached here, not shown with a caveat.
        </p>
        <ng-container *ngFor="let s of live(d.signals)">
          <ng-container *ngTemplateOutlet="sigCard; context: { s: s }"></ng-container>
        </ng-container>

        <p class="row-sub empty" *ngIf="!live(d.signals).length && background(d.signals).length">
          Nothing live. Everything found here has aged out of being a reason to reach out —
          it is below, as background.
        </p>

        <!-- Expired and superseded, apart from the live ones. A 2021
             appointment beside a current one, with only a date between them,
             reads as news. These are true and no longer a reason to call. -->
        <details class="bg-group" *ngIf="background(d.signals).length" [open]="showBackground()"
                 (toggle)="showBackground.set($any($event.target).open)">
          <summary>
            Background — no longer a trigger ({{ background(d.signals).length }})
            <span class="row-sub">
              Still true. Past its durability as a hook, so it is not cited in outreach.
            </span>
          </summary>
          <ng-container *ngFor="let s of background(d.signals)">
            <ng-container *ngTemplateOutlet="sigCard; context: { s: s }"></ng-container>
          </ng-container>
        </details>

        <p class="row-sub empty" *ngIf="!d.signals.length">
          No signals yet. Research has not run for this account.
        </p>

        <!-- One card, both groups. Two copies drifted apart the last time a
             badge was added to only one of them. -->
        <ng-template #sigCard let-s="s">
          <div class="card sig" [class.sig-bg]="!isLive(s)">
            <div class="sig-head">
              <div>
                <code>{{ s.signal_type }}</code>
                <span class="badge" [ngClass]="s.scope === 'company' ? 'badge-accent' : 'badge-warn'"
                      style="margin-left:8px;">{{ s.scope }}</span>
                <span class="badge badge-neutral" *ngIf="s.is_hypothesis" style="margin-left:6px;">
                  hypothesis
                </span>
                <span class="badge" [ngClass]="isLive(s) ? 'badge-good' : 'badge-neutral'"
                      style="margin-left:6px;" [title]="stateWhy(s)">
                  {{ stateLabel(s) }}
                </span>
              </div>
              <span class="row-sub mono">
                {{ s.strength }} · {{ (s.confidence * 100).toFixed(0) }}%
              </span>
            </div>
            <strong style="display:block;margin:8px 0 4px;">{{ s.summary }}</strong>
            <p class="row-sub" *ngIf="s.business_implication">{{ s.business_implication }}</p>
            <p class="row-sub">
              Observed {{ s.observed_at | date: 'MMM d, y' }}
              <span *ngIf="s.expires_at">
                · {{ expired(s) ? 'expired' : 'expires' }}
                {{ s.expires_at | date: 'MMM d, y' }}
              </span>
              <span *ngIf="s.contact_name"> · about {{ s.contact_name }}</span>
            </p>

            <button class="btn cite" (click)="toggle(s.id)"
                    [attr.aria-expanded]="open().has(s.id)">
              <app-icon name="eye" [size]="13" />
              {{ open().has(s.id) ? 'Hide' : 'Show' }} {{ s.evidence.length }} citation(s)
            </button>
            <div *ngIf="open().has(s.id)" class="evidence">
              <div *ngFor="let e of s.evidence" class="ev">
                <div class="row-sub">
                  <span class="badge badge-neutral">{{ e.source_type }}</span>
                  {{ e.source_name ?? 'unknown source' }}
                  <span *ngIf="e.observed_at"> · {{ e.observed_at | date: 'MMM d, y' }}</span>
                  <span class="badge badge-warn" *ngIf="e.raw_status === 'purged'"
                        style="margin-left:6px;">snapshot purged</span>
                </div>
                <p style="margin:6px 0;">“{{ e.excerpt }}”</p>
                <a *ngIf="e.source_url" [href]="e.source_url" target="_blank" rel="noopener"
                   class="row-sub">{{ e.source_url }}</a>
              </div>
            </div>
          </div>
        </ng-template>
      </ng-container>

      <!-- coverage -->
      <ng-container *ngIf="tab() === 'coverage'">
        <p class="row-sub" style="max-width:70ch;margin-bottom:14px;">
          What research looked for, and what it found. <strong>Empty is an answer</strong> — there
          is nothing there. <strong>Failed means we do not know</strong>, and the two are shown
          differently on purpose: a rep who reads a broken provider as a quiet market walks away
          from a live prospect.
        </p>
        <!-- The company first, then one table per person the contact pass
             looked into for the ICP's contact signals. -->
        <ng-container *ngFor="let g of coverageGroups(d); trackBy: trackGroup">
        <h4 class="cov-group" *ngIf="g.label">
          {{ g.label }}<span class="row-sub" *ngIf="g.title"> · {{ g.title }}</span>
        </h4>
        <div class="table-wrap">
          <table class="data coverage">
            <thead>
              <tr><th>Family</th><th>Result</th><th>Evidence</th><th>Researched</th><th>Detail</th></tr>
            </thead>
            <tbody>
              <ng-container *ngFor="let c of g.rows; trackBy: trackRow">
                <tr [class.openable]="canOpen(c)" (click)="canOpen(c) && toggle(covKey(c))">
                  <td>
                    <button *ngIf="canOpen(c); else plainFamily" type="button" class="fam"
                            [attr.aria-expanded]="open().has(covKey(c))"
                            [attr.aria-label]="'Show what ' + c.family + ' found and searched for'
                              + (c.contact_name ? ' about ' + c.contact_name : '')"
                            (click)="$event.stopPropagation(); toggle(covKey(c))">
                      <span class="chev" [class.down]="open().has(covKey(c))"
                            aria-hidden="true">›</span>
                      <code>{{ c.family }}</code>
                    </button>
                    <ng-template #plainFamily><code class="fam-plain">{{ c.family }}</code></ng-template>
                  </td>
                  <td>
                    <span class="badge" [ngClass]="coverageClass(c.status)">{{ c.status }}</span>
                  </td>
                  <td class="mono">{{ c.evidence_count }}</td>
                  <td class="row-sub">{{ c.researched_at ? (c.researched_at | date: 'd MMM y') : '—' }}</td>
                  <td class="row-sub">{{ coverageDetail(c) }}</td>
                </tr>
                <tr *ngIf="open().has(covKey(c))" class="drill">
                  <td colspan="5">
                    <div *ngIf="c.evidence.length" class="drill-block">
                      <div class="drill-h">Found · {{ c.evidence.length }}</div>
                      <ng-container *ngFor="let e of c.evidence">
                        <ng-container *ngTemplateOutlet="evItem; context: { $implicit: e }"></ng-container>
                      </ng-container>
                    </div>
                    <p *ngIf="c.evidence_count > c.evidence.length" class="row-sub drill-block">
                      {{ c.evidence_count - c.evidence.length }} passage(s) from this family were
                      stored before passages recorded which family found them — they are listed
                      under the table.
                    </p>
                    <div *ngIf="c.not_found.length" class="drill-block">
                      <div class="drill-h">Searched, not established · {{ c.not_found.length }}</div>
                      <ul class="searched">
                        <li *ngFor="let q of c.not_found">{{ q }}</li>
                      </ul>
                    </div>
                  </td>
                </tr>
              </ng-container>
            </tbody>
          </table>
        </div>
        </ng-container>
        <p class="row-sub empty" *ngIf="!d.coverage.length">No research run recorded.</p>

        <!-- LinkedIn is the one place research may not read. What a rep saw
             there comes in pasted and attributed, and becomes signals on the
             next Re-read & score like any other passage. -->
        <div class="card paste">
          <div class="drill-h">Add what you saw on LinkedIn</div>
          <p class="row-sub" style="margin:2px 0 8px;">
            Research never opens LinkedIn. Paste a post or a profile line you read there — it is kept
            as evidence you entered, dated from the post's link when there is one, and read into
            signals on the next <em>Re-read &amp; score</em>.
          </p>
          <textarea class="field" rows="3" aria-label="Pasted text"
                    placeholder="Paste the post or profile text…"
                    [value]="pasteText()" (input)="pasteText.set($any($event.target).value)"></textarea>
          <div class="paste-row">
            <input class="field" aria-label="Link to the post" placeholder="Link to the post (optional)"
                   [value]="pasteUrl()" (input)="pasteUrl.set($any($event.target).value)">
            <select class="field" aria-label="Who it is about"
                    [value]="pasteContact()" (change)="pasteContact.set($any($event.target).value)">
              <option value="">About the company</option>
              <option *ngFor="let c of contacts()" [value]="c.id">About {{ c.full_name }}</option>
            </select>
            <input class="field" type="date" aria-label="When it was posted (optional)"
                   title="When it was posted — leave empty if the link says"
                   [value]="pasteDate()" (input)="pasteDate.set($any($event.target).value)">
            <button class="btn btn-primary" (click)="paste()" [class.busy]="pasting()"
                    [disabled]="pasting() || pasteText().trim().length < 10">
              {{ pasting() ? 'Saving…' : 'Add as evidence' }}
            </button>
          </div>
          <p class="row-sub" *ngIf="pasteNote()" style="margin:8px 0 0;">{{ pasteNote() }}</p>
          <p class="row-sub" *ngIf="pasteError()" style="margin:8px 0 0;color:var(--critical);">
            {{ pasteError() }}
          </p>
        </div>

        <div *ngIf="d.unattributed_evidence.length" class="card unattributed">
          <div class="drill-h">From this run, family not recorded · {{ d.unattributed_evidence.length }}</div>
          <p class="row-sub" style="margin:2px 0 6px;">
            Stored before passages kept which family found them. Listed here rather than guessed
            into a family.
          </p>
          <ng-container *ngFor="let e of d.unattributed_evidence">
            <ng-container *ngTemplateOutlet="evItem; context: { $implicit: e }"></ng-container>
          </ng-container>
        </div>
      </ng-container>

      <!-- One passage: where it came from, when the fact was true, the quote,
           and a link that re-opens the page. Excerpts are retrieved text, so
           they are only ever interpolated, never bound as HTML. -->
      <ng-template #evItem let-e>
        <div class="ev">
          <div class="row-sub">
            <span class="badge badge-neutral">{{ e.source_type }}</span>
            {{ e.source_name ?? hostOf(e.source_url) ?? 'unknown source' }}
            <span *ngIf="e.observed_at"> · {{ e.observed_at | date: 'MMM d, y' }}</span>
            <span *ngIf="e.reliability != null"> · reliability {{ e.reliability | number: '1.1-1' }}</span>
          </div>
          <p style="margin:6px 0;">“{{ e.excerpt }}”</p>
          <a *ngIf="e.source_url" [href]="e.source_url" target="_blank" rel="noopener noreferrer"
             class="row-sub src">{{ e.title || e.source_url }}</a>
        </div>
      </ng-template>

      <!-- qualification -->
      <ng-container *ngIf="tab() === 'qualification'">
        <ng-container *ngIf="d.qualification as q; else noQual">
          <div class="table-wrap" *ngIf="q.by_icp?.length" style="margin-bottom:10px;">
            <table class="data">
              <thead><tr><th>ICP</th><th>Score</th><th>Band</th><th>Fit</th><th>Buyer</th></tr></thead>
              <tbody>
                <tr *ngFor="let s of q.by_icp">
                  <td>{{ s.icp_name }} <span class="row-sub">v{{ s.icp_version }}</span></td>
                  <td class="mono">{{ s.priority_score | number: '1.0-0' }}</td>
                  <td>{{ s.priority_band }}</td>
                  <td class="mono">{{ s.fit }}</td>
                  <td class="mono">{{ s.buyer }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="row-sub" *ngIf="q.by_icp?.length" style="max-width:70ch;margin-bottom:14px;">
            One assessment, read for each ICP: fit and buyer are recomputed, the rest carry over. A campaign
            shows the score for its own ICP.
          </p>
          <p class="row-sub" style="max-width:70ch;margin-bottom:14px;">
            Fit, buyer and engagement are computed from the account, its contacts and its
            outreach; opportunity, commercial and intent are judged against cited evidence on a
            five-step scale, and kept as they were when nothing has changed. The roll-up is deterministic
            arithmetic over scoring config v{{ q.scoring_config_version }} — no model was asked
            for the number, which is why re-scoring the whole book after a weight change is free.
          </p>
          <div class="card dim" *ngFor="let dim of q.dimensions">
            <div class="dim-head">
              <strong>{{ dim.dimension }}</strong>
              <span class="mono">{{ dim.score }}</span>
            </div>
            <p class="row-sub" style="margin:6px 0;">{{ dim.reason }}</p>
            <span class="badge" [ngClass]="basisBadge(dim.basis)">
              {{ basisLabel(dim) }}
            </span>
          </div>
          <!-- The reading of the signals, kept apart from the six scores: one is
               a judgement, the other is what a rep would say out loud. -->
          <ng-container *ngIf="d.context_narrative as n">
            <h3 class="sec-title">What the signals say</h3>
            <div class="card">
              <p style="margin:0 0 8px;" *ngIf="n.summary">{{ n.summary }}</p>
              <p class="row-sub" *ngIf="n.what_changed"><strong>Changed:</strong> {{ n.what_changed }}</p>
              <div class="theme" *ngFor="let t of n.themes ?? []">
                <strong>{{ t.label }}</strong>
                <span class="badge badge-neutral" *ngIf="t.weight === 'primary'">primary</span>
                <p class="row-sub" style="margin:2px 0 0;">{{ t.reading }}</p>
              </div>
              <ng-container *ngIf="(n.unknowns ?? []).length">
                <div class="drill-h" style="margin-top:12px;">Still unknown</div>
                <div class="theme" *ngFor="let u of n.unknowns ?? []">
                  <strong>{{ u.question }}</strong>
                  <p class="row-sub" style="margin:2px 0 0;">
                    {{ u.why_it_matters }}
                    <span *ngIf="u.would_be_answered_by"> · would be answered by
                      <code>{{ u.would_be_answered_by }}</code></span>
                  </p>
                </div>
              </ng-container>
            </div>
          </ng-container>

          <div class="card" *ngIf="q.man" style="margin-top:14px;">
            <strong style="font-size:.9rem;">MAN view</strong>
            <p class="row-sub" style="margin:6px 0 0;">
              Money {{ q.man['money'] }} · Authority {{ q.man['authority'] }} ·
              Need {{ q.man['need'] }}
              <br>Derived from commercial, buyer and opportunity — a lens on the six, not a
              separate judgement.
            </p>
          </div>
        </ng-container>
        <ng-template #noQual>
          <p class="row-sub empty">Not qualified yet.</p>
        </ng-template>
      </ng-container>

      <!-- outreach: strategy and cadence drafts belong to each campaign -->
      <ng-container *ngIf="tab() === 'outreach'">
        <p class="row-sub" style="max-width:70ch;margin-bottom:12px;">
          Strategy and cadence drafts belong to each campaign — the same person is argued for differently
          for another service or ICP. Open a campaign to build or edit them.
        </p>
        <div class="card" *ngFor="let o of d.outreach" style="margin-bottom:12px;">
          <div class="sig-head">
            <div>
              <a [routerLink]="['/campaigns', o.campaign_id]" style="color:var(--accent);text-decoration:none;">
                <strong>Outreach — {{ o.label }}</strong>
              </a>
              <div class="row-sub">for {{ o.service_code ?? '—' }} · ICP {{ o.icp_name ?? '—' }} · {{ o.status }}</div>
            </div>
            <span class="badge badge-neutral" *ngIf="o.priority_band">
              {{ o.priority_band }} {{ o.priority_score | number: '1.0-0' }}
            </span>
          </div>
          <div class="table-wrap" style="margin-top:8px;">
            <table class="data">
              <thead><tr><th>Person</th><th>Strategy</th><th>Cadence drafts</th></tr></thead>
              <tbody>
                <tr *ngFor="let p of o.people">
                  <td>
                    {{ p.full_name }}
                    <div class="row-sub" *ngIf="p.problem_hypothesis">{{ p.problem_hypothesis }}</div>
                  </td>
                  <td>{{ p.strategy }}</td>
                  <td>{{ p.drafts }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <p class="row-sub empty" *ngIf="!d.outreach.length">Nobody from this company is in a campaign yet.</p>
      </ng-container>
    </ng-container>
  `,
  styles: [
    `
      .back { display: inline-flex; align-items: center; gap: 5px; color: var(--accent);
              text-decoration: none; font-size: .84rem; margin-bottom: 14px; }
      .head { display: flex; justify-content: space-between; align-items: flex-start;
              gap: 20px; margin-bottom: 18px; }
      .head h2 { font-size: 1.15rem; margin-bottom: 2px; }
      .score { display: flex; align-items: baseline; gap: 8px; }
      .score strong { font-size: 1.5rem; }
      .tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); margin-bottom: 18px; }
      .tab { background: none; border: 0; padding: 9px 14px; cursor: pointer;
             font-size: .86rem; color: var(--text-dim); border-bottom: 2px solid transparent; }
      .tab.on { color: var(--text); border-bottom-color: var(--accent); font-weight: 500; }
      .count { display: inline-block; margin-left: 6px; font-size: .74rem;
               font-family: 'IBM Plex Mono', monospace; opacity: .7; }
      .sig, .dim, .thread { margin-bottom: 12px; }
      .sig-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
      /* Receded, not hidden: still readable, visibly not one of the live ones.
         Opacity alone would take the evidence excerpts down with it, and those
         are the reason to open a background card at all. */
      .sig-bg { border-style: dashed; background: none; }
      .sig-bg strong { font-weight: 500; }
      .bg-group { margin-top: 18px; border-top: 1px solid var(--line); padding-top: 14px; }
      .bg-group > summary { cursor: pointer; font-size: .86rem; font-weight: 500;
                            margin-bottom: 12px; }
      .bg-group > summary .row-sub { display: block; font-weight: 400; margin-top: 3px; }
      .dim-head { display: flex; justify-content: space-between; align-items: baseline; }
      .dim-head .mono { font-size: 1.05rem; }
      .cite { margin-top: 10px; padding: 5px 10px; font-size: .78rem; }
      .evidence { margin-top: 10px; border-top: 1px solid var(--line); padding-top: 10px; }
      .ev { padding: 8px 0; border-bottom: 1px dashed var(--line); font-size: .84rem; }
      .ev:last-child { border-bottom: 0; }
      .empty { text-align: center; padding: 30px; }
      .coverage tr.openable { cursor: pointer; }
      .coverage tr.openable:hover td { background: var(--surface-2, #f6f7f6); }
      .fam { background: none; border: 0; padding: 0; cursor: pointer; font: inherit;
             color: inherit; display: inline-flex; align-items: center; gap: 6px; }
      .fam-plain { margin-left: 14px; }
      .chev { display: inline-block; width: 8px; color: var(--text-dim);
              transition: transform .15s ease; }
      .chev.down { transform: rotate(90deg); }
      tr.drill td { background: var(--surface-2, #f6f7f6); padding: 10px 18px 14px 32px; }
      .drill-block + .drill-block { margin-top: 12px; }
      .drill-h { font-size: .72rem; text-transform: uppercase; letter-spacing: .06em;
                 color: var(--text-dim); margin-bottom: 2px; }
      .searched { margin: 4px 0 0; padding-left: 18px; font-size: .84rem; }
      .searched li { margin: 2px 0; }
      .src { overflow-wrap: anywhere; }
      .unattributed { margin-top: 14px; }
      .cov-group { font-size: .88rem; margin: 18px 0 6px; }
      .sec-title { font-size: .95rem; margin: 22px 0 8px; }
      .theme { padding: 8px 0; border-top: 1px dashed var(--line); }
      .theme:first-of-type { border-top: 0; }
      .paste { margin-top: 18px; }
      .paste textarea { width: 100%; }
      .paste-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
      .paste-row .field { flex: 1 1 180px; }
      @media (prefers-reduced-motion: reduce) { .chev { transition: none; } }
    `,
  ],
})
export class AccountDetailComponent implements OnInit {
  private api = inject(PipelineService);

  /**
   * The matrix is small and diagnostic, so it gets sorting and no filter
   * panel — three controls above a ten-row table costs more height than it
   * saves. Sorting by weight is the one thing worth doing to it: the question
   * this table answers is "who ranked where, and why not the others".
   */
  sort = signal<SortState>(NO_SORT);

  private readonly cellAccessors: Record<string, (c: MatrixCell) => unknown> = {
    contact: (c) => c.contact_name,
    service: (c) => c.service_code,
    weight: (c) => c.weight,
  };

  matrix(strategy: { matrix: MatrixCell[] }): MatrixCell[] {
    return sortRows(strategy.matrix, this.sort(), this.cellAccessors);
  }

  onSort(state: SortState): void {
    this.sort.set(state);
  }
  private route = inject(ActivatedRoute);

  readonly tabs: { key: Tab; label: string }[] = [
    // First, deliberately. Everything below it is about the company; this is
    // the people, and "who would we actually write to" is the question a rep
    // opens an account to answer.
    { key: 'contacts', label: 'Contacts' },
    { key: 'signals', label: 'Signals' },
    { key: 'coverage', label: 'Research coverage' },
    { key: 'qualification', label: 'Qualification' },
    { key: 'outreach', label: 'Outreach' },
  ];

  private lists = inject(ListsService);

  readonly contactColumns = CONTACT_COLUMNS;
  contacts = signal<Contact[]>([]);
  loadingContacts = signal(false);
  contactSort = signal<SortState>(NO_SORT);

  /** Green only for `verified`. A `risky` address is a provider's own guess
   *  and must not read as ready to send to. */
  emailBadge(status: string): Record<string, boolean> {
    return {
      'badge-good': status === 'verified',
      'badge-warn': status === 'risky',
      'badge-critical': status === 'invalid',
      'badge-neutral': status === 'unverified' || !status,
    };
  }

  onContactSort(state: SortState): void {
    this.contactSort.set(state);
    this.loadContacts();
  }

  private loadContacts(): void {
    const id = this.accountId;
    if (!id) return;
    this.loadingContacts.set(true);
    this.lists.accountContacts(id, this.contactSort()).subscribe({
      next: (rows) => {
        this.contacts.set(rows);
        this.loadingContacts.set(false);
      },
      error: () => this.loadingContacts.set(false),
    });
  }

  data = signal<Intelligence | null>(null);

  pasteText = signal('');
  pasteUrl = signal('');
  pasteContact = signal('');
  pasteDate = signal('');
  pasting = signal(false);
  pasteNote = signal<string | null>(null);
  pasteError = signal<string | null>(null);
  // The first tab in the strip, and the question a rep opens an account to
  // answer: who would we actually write to. Leaving the default on Signals
  // meant the new tab was first in the list and never the one you landed on.
  tab = signal<Tab>('contacts');
  open = signal<Set<string>>(new Set());
  /**
   * Collapsed by default — the clutter is the whole complaint. Held in a signal
   * rather than left to the `<details>` element so it survives a tab switch,
   * which destroys the element and would otherwise re-close it.
   */
  showBackground = signal(false);
  error = signal<string | null>(null);

  /** Held so the contacts tab can reload without re-reading the route. */
  accountId = '';

  ngOnInit(): void {
    this.accountId = this.route.snapshot.paramMap.get('id') ?? '';
    this.api.intelligence(this.accountId).subscribe({
      next: (d) => this.data.set(d),
      error: (err) => this.error.set(apiError(err, 'Could not load this account.')),
    });
    // Loaded up front rather than on tab click: the count in the tab strip is
    // part of how a rep decides which tab to open.
    this.loadContacts();
  }

  paste(): void {
    const text = this.pasteText().trim();
    if (text.length < 10) return;
    this.pasting.set(true);
    this.pasteNote.set(null);
    this.pasteError.set(null);
    this.api
      .pasteEvidence(this.accountId, {
        text,
        url: this.pasteUrl().trim() || null,
        contact_id: this.pasteContact() || null,
        observed_at: this.pasteDate() || null,
      })
      .subscribe({
        next: (r) => {
          this.pasting.set(false);
          this.pasteText.set('');
          this.pasteUrl.set('');
          this.pasteDate.set('');
          // Say where the date came from: a date decoded from a link is not
          // one somebody typed, and an undated passage is not dated today.
          const when = r.evidence.observed_at
            ? ` · dated ${r.evidence.observed_at}${r.dated_from === 'post link' ? ' from the post link' : ''}`
            : ' · undated';
          this.pasteNote.set(`Saved as evidence${when}. It becomes signals on the next Re-read & score.`);
        },
        error: (err) => {
          this.pasting.set(false);
          this.pasteError.set(apiError(err, 'Could not save that.'));
        },
      });
  }

  countFor(tab: Tab, d: Intelligence): number | string {
    if (tab === 'contacts') return this.contacts().length;
    if (tab === 'signals') return d.signals.length;
    if (tab === 'coverage') return d.coverage.length;
    if (tab === 'qualification') return d.qualification ? d.qualification.priority_score : '—';
    return d.outreach.length;
  }

  toggle(id: string): void {
    this.open.update((set) => {
      const next = new Set(set);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  expired(s: SignalRow): boolean {
    return !!s.expires_at && new Date(s.expires_at) < new Date();
  }

  /**
   * Live means the same thing here as everywhere else: `context.live_signals`
   * filters on `expires_at`, and `drafting` additionally refuses a superseded
   * citation. Both conditions, or the screen would call something live that
   * outreach will not use — which is the harder bug to spot, because the only
   * symptom is a signal a rep expected to see quoted and never did.
   */
  isLive(s: SignalRow): boolean {
    return !this.expired(s) && !s.superseded_by;
  }

  live(signals: SignalRow[]): SignalRow[] {
    return signals.filter((s) => this.isLive(s));
  }

  /** Expired or superseded. True, and not a reason to reach out. */
  background(signals: SignalRow[]): SignalRow[] {
    return signals.filter((s) => !this.isLive(s));
  }

  stateLabel(s: SignalRow): string {
    if (s.superseded_by) return 'superseded';
    if (this.expired(s)) return 'expired';
    return s.lifecycle_state;
  }

  stateWhy(s: SignalRow): string {
    if (s.superseded_by) return 'A newer reading of this ongoing theme replaced it.';
    if (this.expired(s)) {
      return 'Past its TTL, so it is no longer a hook. Kept because it is still true.';
    }
    return `Lifecycle state: ${s.lifecycle_state}.`;
  }

  /**
   * Four bases, four different facts. `unsupported` is deliberately not
   * `no_evidence`: one says nothing happened at this account, the other says
   * the model claimed something and could not back it. `firmographics` is fit
   * computed from the account's size, industry and country against the ICP —
   * nothing cited, because nothing needed citing.
   */
  basisBadge(basis: string): string {
    if (basis === 'evidence') return 'badge-good';
    if (basis === 'firmographics' || basis === 'contacts' || basis === 'outreach') {
      return 'badge-accent';
    }
    if (basis === 'unsupported') return 'badge-critical';
    return 'badge-neutral';
  }

  basisLabel(dim: { basis: string; evidence_ids: string[] }): string {
    if (basis_is(dim, 'evidence')) return `${dim.evidence_ids.length} citation(s)`;
    if (basis_is(dim, 'unsupported')) return 'citation did not resolve — scored 0';
    if (basis_is(dim, 'firmographics')) return 'computed from account details vs the ICP';
    if (basis_is(dim, 'contacts')) return 'computed from contacts vs the ICP personas';
    if (basis_is(dim, 'outreach')) return 'computed from outreach history';
    return 'declared absence — scored 0';
  }

  bandClass(band: string): string {
    return band === 'high' ? 'badge-good' : band === 'medium' ? 'badge-accent' : 'badge-neutral';
  }

  /**
   * The company first, then one group per person the contact pass looked into.
   * With only the company, no heading — it would label the obvious.
   */
  coverageGroups(d: Intelligence): {
    key: string; label: string | null; title: string | null; rows: CoverageRow[];
  }[] {
    const groups = new Map<string, {
      key: string; label: string | null; title: string | null; rows: CoverageRow[];
    }>();
    for (const c of d.coverage) {
      const key = c.contact_id ?? 'company';
      if (!groups.has(key)) {
        groups.set(key, {
          key,
          label: c.contact_id ? (c.contact_name ?? 'Contact') : 'Company',
          title: c.contact_id ? c.contact_title : null,
          rows: [],
        });
      }
      groups.get(key)!.rows.push(c);
    }
    const out = [...groups.values()];
    if (out.length === 1 && out[0].key === 'company') out[0].label = null;
    return out;
  }

  /** One key per family per person, so opening a row opens only that one. */
  covKey(c: CoverageRow): string {
    return `cov:${c.contact_id ?? 'company'}:${c.family}`;
  }

  /** Stable identity, so a change-detection pass reuses rows instead of rebuilding them. */
  readonly trackGroup = (_: number, g: { key: string }) => g.key;
  readonly trackRow = (_: number, c: CoverageRow) => this.covKey(c);

  /** Openable when there is something behind the row to show. */
  canOpen(c: CoverageRow): boolean {
    return c.evidence.length > 0 || c.not_found.length > 0;
  }

  /** The reason a family failed or was skipped wins; otherwise say what the
   *  search amounted to, so `empty` never reads as "did not look". */
  coverageDetail(c: CoverageRow): string {
    if (c.detail) return c.detail;
    const n = c.not_found.length;
    // Remarks about the shape of what came back lead, because they describe a
    // family that *worked*. A sweep that found thirty entries and kept ten
    // used to read "1 not established", which says close to the opposite.
    const notes = (c.notes ?? []).join(' · ');
    if (c.status === 'ran') {
      if (notes) return notes;
      return n ? `${n} not established` : '—';
    }
    if (c.status === 'empty') {
      if (n) return `searched ${n} thing(s) — nothing found`;
      return notes || 'nothing found';
    }
    return notes || '—';
  }

  hostOf(url: string | null): string | null {
    if (!url) return null;
    try {
      return new URL(url).hostname.replace(/^www\./, '');
    } catch {
      return null;
    }
  }

  coverageClass(status: string): string {
    // `failed` is deliberately the loud one — it is the state a rep would
    // otherwise mistake for "nothing there".
    if (status === 'ran') return 'badge-good';
    if (status === 'failed') return 'badge-warn';
    return 'badge-neutral';
  }

  threadClass(status: string): string {
    if (status === 'active_primary') return 'badge-good';
    if (status === 'active_secondary') return 'badge-accent';
    if (status === 'queued') return 'badge-warn';
    return 'badge-neutral';
  }
}
