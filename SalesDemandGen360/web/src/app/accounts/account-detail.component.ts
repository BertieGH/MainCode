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
import { RowAction } from '../shared/table-view';
import { Contact, ListsService } from '../core/lists.service';

type Tab = 'contacts' | 'profile' | 'signals' | 'coverage' | 'qualification' | 'outreach';

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
        <div style="display:flex;align-items:center;gap:16px;flex:none;">
          <div *ngIf="d.qualification as q" class="score">
            <span class="badge" [ngClass]="bandClass(q.priority_band)">{{ q.priority_band }}</span>
            <strong>{{ q.priority_score }}</strong>
            <span class="row-sub">config v{{ q.scoring_config_version }}</span>
          </div>
          <!-- Research from here, not only from the list. A rep reading one
               company's signals and finding them thin should not have to go
               back to the list to ask for more. Same endpoint and the same
               reuse window: inside it this costs nothing, which is why
               "Research" is safe to offer and "Rerun" is the one that spends. -->
          <div style="display:flex;gap:8px;">
            <button class="btn" (click)="research()" [disabled]="researching()">
              <app-icon name="refresh" [size]="13" />
              {{ researching() === 'company' ? 'Researching…' : 'Research' }}
            </button>
            <button class="btn" (click)="research(true)" *ngIf="d.coverage.length"
                    [disabled]="researching()"
                    title="Ignore the reuse window and buy every planned family again">
              {{ researching() === 'rerun' ? 'Re-researching…' : 'Rerun' }}
            </button>
          </div>
        </div>
      </div>

      <p class="row-sub" style="margin:-8px 0 14px;" *ngIf="researchNote()">{{ researchNote() }}</p>

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
                        [selectable]="true"
                        [rowActions]="contactActions"
                        [busyKey]="researching() === 'contacts' ? 'research' : null"
                        busyText="Researching…"
                        (bulk)="researchPeople($any($event).rows)"
                        (rowAction)="researchPeople([$any($event).row])"
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
      <!-- profile — what the company and its people *are*, as against what has
           just happened to them. Stored on account.profile and contact.profile
           since the profile stage was built, read by the context builder and
           so by qualification, strategy and drafting, and until now shown
           nowhere: the one reader who could not see it was the rep. -->
      <ng-container *ngIf="tab() === 'profile'">
        <p class="row-sub" style="max-width:74ch;margin-bottom:14px;">
          Standing descriptions. Unlike a signal these carry no expiry — nothing in them says
          <em>now</em> — so they are never set aside for being old. Strategy and drafting read
          this, which is why the source text is kept whole alongside the summary.
        </p>

        <!-- the company -->
        <div class="card prof" *ngIf="d.profile as p; else noCompanyProfile">
          <div class="prof-head">
            <div style="flex:1;min-width:0;">
              <h3>What they are</h3>
              <p class="row-sub">{{ d.account_name }}</p>
            </div>
            <span class="badge badge-good">researched</span>
          </div>

          <p class="prof-lead" *ngIf="p.what_they_do">{{ p.what_they_do }}</p>

          <dl class="facts" *ngIf="p.size || p.founded || p.ownership || p.locations?.length">
            <div class="fact" *ngIf="p.size"><dt>Size</dt><dd>{{ p.size }}</dd></div>
            <div class="fact" *ngIf="p.founded"><dt>Founded</dt><dd>{{ p.founded }}</dd></div>
            <div class="fact" *ngIf="p.ownership"><dt>Ownership</dt><dd>{{ p.ownership }}</dd></div>
            <div class="fact" *ngIf="p.locations?.length">
              <dt>Locations</dt><dd>{{ p.locations!.join(' · ') }}</dd>
            </div>
          </dl>

          <!-- first of the lists, and tinted. It is the field most often
               missing and most often needed: it is what makes a pitch sound
               written for them rather than at them. -->
          <div class="pgroup" *ngIf="p.target_customers?.length">
            <h4>Who they sell to</h4>
            <div class="chips">
              <span class="chip accent" *ngFor="let x of p.target_customers">{{ x }}</span>
            </div>
          </div>

          <div class="pgroup" *ngIf="p.services?.length">
            <h4>Lines of business</h4>
            <div class="chips"><span class="chip" *ngFor="let x of p.services">{{ x }}</span></div>
          </div>

          <div class="pgroup" *ngIf="p.industries_served?.length">
            <h4>Industries served</h4>
            <div class="chips">
              <span class="chip" *ngFor="let x of p.industries_served">{{ x }}</span>
            </div>
          </div>

          <div class="pgroup" *ngIf="p.current_focus?.length">
            <h4>What they are pushing</h4>
            <p class="pwhy">The closest thing here to a signal, and still not one: it has no date.</p>
            <ul class="focus"><li *ngFor="let x of p.current_focus">{{ x }}</li></ul>
          </div>

          <ng-container
            *ngTemplateOutlet="verbatim; context: { v: p.verbatim, k: 'company' }"></ng-container>
          <ng-container *ngTemplateOutlet="srcs; context: { s: p.sources }"></ng-container>
        </div>

        <ng-template #noCompanyProfile>
          <div class="card prof">
            <div class="prof-head">
              <div style="flex:1;min-width:0;"><h3>What they are</h3></div>
              <span class="badge badge-neutral">not researched</span>
            </div>
            <p class="row-sub" style="max-width:66ch;">
              No profile for {{ d.account_name }} yet. Qualification, strategy and drafting are
              reading this company's signals with no standing description of the business behind
              them. It is written by the profile stage on the next research run.
            </p>
          </div>
        </ng-template>

        <!-- the people. Same shape, because they answer the same question
             about a different subject, and a rep moving between them should
             not have to relearn the layout. -->
        <h3 class="sec-title" *ngIf="d.contact_profiles.length">
          The people here
          <span class="row-sub">
            {{ d.contact_profiles.length }} of {{ contacts().length || d.contact_profiles.length }}
            described
          </span>
        </h3>

        <div class="card prof" *ngFor="let cp of d.contact_profiles">
          <div class="prof-head">
            <div style="flex:1;min-width:0;">
              <h3>{{ cp.contact_name }}</h3>
              <p class="row-sub">{{ cp.title || 'title not recorded' }}</p>
            </div>
            <span class="badge badge-good">researched</span>
          </div>

          <p class="prof-lead" *ngIf="cp.profile.summary">{{ cp.profile.summary }}</p>

          <dl class="facts" *ngIf="cp.profile.tenure || cp.profile.decision_scope">
            <div class="fact" *ngIf="cp.profile.tenure">
              <dt>Tenure</dt><dd>{{ cp.profile.tenure }}</dd>
            </div>
            <div class="fact" *ngIf="cp.profile.decision_scope">
              <dt>Decides</dt><dd>{{ cp.profile.decision_scope }}</dd>
            </div>
          </dl>

          <!-- tinted, for the same reason target_customers is on the company:
               it is the part that decides whether a pitch is addressed to the
               right person at all. -->
          <div class="pgroup" *ngIf="cp.profile.responsibilities?.length">
            <h4>What they own</h4>
            <div class="chips">
              <span class="chip accent" *ngFor="let x of cp.profile.responsibilities">{{ x }}</span>
            </div>
          </div>

          <div class="pgroup" *ngIf="cp.profile.focus_areas?.length">
            <h4>What they write and speak about</h4>
            <p class="pwhy">The nearest thing here to a hook, and still not a signal — no date.</p>
            <div class="chips">
              <span class="chip" *ngFor="let x of cp.profile.focus_areas">{{ x }}</span>
            </div>
          </div>

          <div class="pgroup" *ngIf="cp.profile.background?.length">
            <h4>Before this</h4>
            <ul class="focus"><li *ngFor="let x of cp.profile.background">{{ x }}</li></ul>
          </div>

          <ng-container
            *ngTemplateOutlet="verbatim;
                               context: { v: cp.profile.verbatim, k: cp.contact_id }"></ng-container>
          <ng-container *ngTemplateOutlet="srcs; context: { s: cp.profile.sources }"></ng-container>
        </div>

        <p class="row-sub empty" *ngIf="!d.contact_profiles.length && contacts().length">
          None of the {{ contacts().length }} people here has a profile yet. A contact profile is
          written when research runs for that person, not for the company.
        </p>

        <!-- The uncut source text, behind the same disclosure a signal's
             citations use, because it answers the same question: says who? -->
        <ng-template #verbatim let-v="v" let-k="k">
          <div class="pgroup" *ngIf="v?.length">
            <h4>In their own words</h4>
            <button class="btn cite" (click)="toggle('prof-' + k)"
                    [attr.aria-expanded]="open().has('prof-' + k)">
              <app-icon name="eye" [size]="13" />
              {{ open().has('prof-' + k) ? 'Hide' : 'Show' }} {{ v.length }} passage(s)
            </button>
            <div class="evidence" *ngIf="open().has('prof-' + k)">
              <div class="ev" *ngFor="let q of v">
                <p style="margin:0 0 6px;">“{{ q.text }}”</p>
                <a *ngIf="q.url" [href]="q.url" target="_blank" rel="noopener"
                   class="row-sub">{{ q.url }}</a>
                <span class="row-sub" *ngIf="!q.url && q.source">{{ q.source }}</span>
              </div>
            </div>
          </div>
        </ng-template>

        <!-- Not evidence rows: a profile is not a claim that needs citing the
             way a signal is. But a rep asking "says who?" deserves an answer,
             and a stale profile needs somewhere to be re-read. -->
        <ng-template #srcs let-s="s">
          <p class="row-sub psrc" *ngIf="s?.length">
            Read from
            <ng-container *ngFor="let u of hosts(s); let last = last">
              <a [href]="u.href" target="_blank" rel="noopener">{{ u.label }}</a><span
                *ngIf="!last">, </span>
            </ng-container>. Replaced whole when research runs again.
          </p>
        </ng-template>
      </ng-container>

      <ng-container *ngIf="tab() === 'signals'">
        <p class="row-sub" style="max-width:70ch;margin-bottom:14px;">
          Every signal cites the evidence it rests on. A signal whose citation could not be resolved
          was dropped before it reached here, not shown with a caveat.
        </p>
        <!-- Two sections, not one mixed list. "Something changed at this
             business" and "something changed for this person" are different
             questions a rep works through for different reasons, and a scope
             badge on each card made the reader do the sorting. -->
        <h3 class="sec-title" *ngIf="companySignals(d.signals).length">
          Company signals
          <span class="row-sub">{{ companySignals(d.signals).length }} extracted</span>
        </h3>
        <ng-container *ngFor="let s of companySignals(d.signals)">
          <ng-container *ngTemplateOutlet="sigCard; context: { s: s }"></ng-container>
        </ng-container>

        <h3 class="sec-title" *ngIf="contactSignals(d.signals).length">
          Contact signals
          <span class="row-sub">{{ contactSignals(d.signals).length }} extracted</span>
        </h3>
        <ng-container *ngFor="let s of contactSignals(d.signals)">
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
                <!-- Neither the registry key nor a scope badge. The key was
                     the first thing a rep read and is the one label written
                     for us rather than for them: contact_profile sat here
                     looking like the person's profile, which is a different
                     object on its own tab with no expiry. The scope now comes
                     from the section heading. Both are still reachable — the
                     key on hover, for registry work. -->
                <span class="badge badge-neutral" *ngIf="s.is_hypothesis">
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
            <strong style="display:block;margin:8px 0 4px;"
                    [title]="'signal type: ' + s.signal_type">{{ s.summary }}</strong>
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

      /* --- profile ---
         display is declared, not inherited: a global '.slot' turned another
         screen's cards into flex rows once, and these are stacks. */
      .prof { display: block; margin-bottom: 14px; }
      .prof-head { display: flex; gap: 14px; align-items: center;
                   padding-bottom: 12px; border-bottom: 1px solid var(--line);
                   margin-bottom: 16px; }
      .prof-head h3 { font-size: 1rem; margin: 0 0 2px; }
      .prof-head .badge { flex: none; }
      /* The largest thing on the card: every list below is detail under it. */
      .prof-lead { font-family: 'Fraunces', Georgia, serif; font-size: 1.08rem;
                   line-height: 1.45; margin: 0 0 4px; }
      /* A list, not chips: each is one labelled value, not a member of a set. */
      .facts { display: flex; flex-wrap: wrap; gap: 26px; margin: 18px 0 4px;
               padding-top: 16px; border-top: 1px solid var(--line); }
      .facts dt, .pgroup h4 { font-size: .68rem; letter-spacing: .07em; font-weight: 600;
                              text-transform: uppercase; color: var(--faint); margin: 0 0 8px; }
      .facts dt { margin-bottom: 3px; }
      .facts dd { margin: 0; }
      .facts dd, .focus li { font-size: .88rem; }
      .pgroup { margin-top: 20px; }
      .pwhy { font-size: .74rem; color: var(--faint); margin: -4px 0 8px; max-width: 64ch; }
      .chips { display: flex; flex-wrap: wrap; gap: 6px; }
      .chip { font-size: .78rem; padding: 4px 11px; border-radius: 20px;
              background: var(--surface-2); border: 1px solid var(--line); }
      .chip.accent { background: var(--accent-soft); border-color: transparent;
                     color: var(--accent); }
      /* Arrows, not chips: these are sentences, and a chip that wraps to three
         lines is a paragraph wearing a pill. */
      .focus { margin: 0; padding: 0; list-style: none; }
      .focus li { position: relative; padding-left: 18px; margin-bottom: 6px; max-width: 78ch; }
      .focus li::before { content: "\\2192"; position: absolute; left: 0; color: var(--accent); }
      /* Passages reuse .evidence/.ev from the citation disclosure above. Same
         shape, same job — a quote and the link that reopens it — so a second
         set of rules would only let the two drift apart. */
      .psrc { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--line); }
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
    // Second, not first. Contacts keeps the lead for the reason above; this is
    // the standing context for everything after it, so it sits before the
    // dated things rather than among them.
    { key: 'profile', label: 'Profile' },
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

  /** Which research request is in flight, so two cannot overlap. */
  researching = signal<'company' | 'rerun' | 'contacts' | null>(null);
  researchNote = signal<string | null>(null);

  /**
   * "Research this person" on the contacts table.
   *
   * Narrows research to the named people: nobody else at the company is looked
   * into, and their own reuse window is ignored, because naming somebody is an
   * explicit ask to look now. The company's families are still planned and the
   * window handles those — a person's news means little with no company behind
   * it.
   */
  readonly contactActions: RowAction[] = [
    {
      key: 'research',
      label: 'Research this person',
      // A suppressed contact is somebody we have been told to leave alone, and
      // the server refuses them anyway — offering it would be a button that
      // reports "nothing was researched".
      can: (r) => !r.do_not_contact,
      why: 'marked do-not-contact',
      row: true,
      bulk: true,
    },
  ];

  research(force = false): void {
    this.researching.set(force ? 'rerun' : 'company');
    this.researchNote.set(null);
    this.lists.researchAccount(this.accountId, { force }).subscribe({
      next: (r) => this.afterResearch(r),
      error: (err) => this.researchFailed(err),
    });
  }

  researchPeople(rows: { id: string }[]): void {
    const ids = (rows ?? []).map((r) => r.id).filter(Boolean);
    if (!ids.length) return;
    this.researching.set('contacts');
    this.researchNote.set(null);
    this.lists.researchAccount(this.accountId, { contactIds: ids }).subscribe({
      next: (r) => this.afterResearch(r, ids.length),
      error: (err) => this.researchFailed(err),
    });
  }

  /** Report what the run did, then reload — every tab is downstream of it. */
  private afterResearch(r: any, people = 0): void {
    this.researching.set(null);
    if (!r?.ran || r?.blocked) {
      this.researchNote.set(r?.blocked ?? 'Research could not run.');
      return;
    }
    const bits: string[] = [];
    if (people) bits.push(`${people} ${people === 1 ? 'person' : 'people'}`);
    if (r.reused) bits.push('reused recent research — nothing bought');
    if (r.evidence_stored) bits.push(`${r.evidence_stored} evidence`);
    if (r.signals_stored) bits.push(`${r.signals_stored} new signal(s)`);
    if (r.signals_duplicate) bits.push(`${r.signals_duplicate} already known`);
    if (r.skipped_unresolved) bits.push('skipped — identity not confirmed');
    this.researchNote.set(bits.length ? bits.join(' · ') : 'Nothing new was found.');
    this.api.intelligence(this.accountId).subscribe({
      next: (d) => this.data.set(d),
      error: () => undefined,
    });
    this.loadContacts();
  }

  private researchFailed(err: unknown): void {
    this.researching.set(null);
    // The account is on several lists whose ICPs may ask for different things.
    // The server refuses to guess; say which they are rather than showing a
    // bare 409, so the rep knows what the choice actually is.
    const body = (
      err as { error?: { error?: string; message?: string; lists?: { label: string }[] } }
    )?.error;
    if (body?.error === 'which_list') {
      const names = (body.lists ?? []).map((l) => l.label).join(', ');
      this.researchNote.set(`${body.message} Lists: ${names}.`);
      return;
    }
    this.researchNote.set(apiError(err, 'Could not research this account.'));
  }

  /** Source URLs as one link per host, the full URL kept in the href.
   *
   *  Shortening to the host is what makes a row of sources read rather than
   *  wrap — but two pages on one site then render the same word twice, which
   *  Champion Risk did: "championrisk.com, championrisk.com, insurancejournal.com"
   *  looks like a bug whatever the hrefs say. One link per host, first URL
   *  wins, so the label is always distinct and still opens something real.
   */
  hosts(urls: string[] | undefined): { href: string; label: string }[] {
    const seen = new Map<string, string>();
    for (const url of urls ?? []) {
      let label = url;
      try {
        label = new URL(url).hostname.replace(/^www\./, '');
      } catch {
        /* not a URL — show it as given rather than dropping a source */
      }
      if (!seen.has(label)) seen.set(label, url);
    }
    return [...seen].map(([label, href]) => ({ href, label }));
  }

  countFor(tab: Tab, d: Intelligence): number | string {
    if (tab === 'contacts') return this.contacts().length;
    // The company profile is not a count, so the tab shows how many *people*
    // are described. A dash rather than 0 when none are: "0 profiles" reads as
    // a measurement, and nothing here has been measured.
    if (tab === 'profile') return d.contact_profiles.length || '—';
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
  /** The live signals about the company itself. */
  companySignals(signals: SignalRow[]): SignalRow[] {
    return this.live(signals).filter((s) => s.scope === 'company');
  }

  /**
   * The live signals about a person here.
   *
   * Split from the company's rather than mixed and badged, because they answer
   * different questions — "something changed at this business" against
   * "something changed for this person" — and a rep works through them for
   * different reasons. Once they are in named sections the per-card scope
   * badge is saying what the heading above it already said.
   */
  contactSignals(signals: SignalRow[]): SignalRow[] {
    return this.live(signals).filter((s) => s.scope !== 'company');
  }

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
