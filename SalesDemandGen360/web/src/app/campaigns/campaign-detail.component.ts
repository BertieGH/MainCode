import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import {
  ApprovalView,
  ArcView,
  CadenceShapeView,
  CampaignActivity,
  CheckPerson,
  PreflightCheck,
  PipelineService,
  PreflightView,
  ThreadCard,
  blockersOf,
} from '../core/pipeline.service';
import {
  distinct,
  matchesAny,
  matchesText,
  sortRows,
} from '../shared/client-sort';
import { FilterPanelComponent } from '../shared/filter-panel.component';
import { NO_SORT, SortState, SortableDirective } from '../shared/sortable';
import { IconComponent } from '../shared/icon.component';
import { apiError } from '../shared/api-error';
import {
  channelDisagrees,
  noSubjectReason,
  sendingChannel,
  slotWire,
} from '../shared/lgm-slot';
import { ConfirmService } from '../shared/confirm.service';
import { NotifyService } from '../shared/notify.service';
import { ReadinessService } from '../shared/readiness.service';
import { CampaignDraftsComponent } from './campaign-drafts.component';
import { CampaignPersonComponent, PersonSection } from './campaign-person.component';
import { CampaignStrategyComponent } from './campaign-strategy.component';

type Tab = 'strategy' | 'drafts' | 'approval' | 'threads' | 'execute' | 'replies';

/**
 * One person in the campaign, whether or not their drafts are saved.
 *
 * `card` is present only for the two approval strata — it is what the arc
 * drawer and the stop action need. Everyone else is here from `waiting`, with
 * the state that says what they are missing.
 */
interface ThreadRow {
  sequence_id: string;
  withdrawn: boolean;
  contact_id: string | null;
  contact_name: string;
  contact_title: string | null;
  account_name: string;
  touch_count: number;
  approved: boolean;
  state: string;
  card: ThreadCard | null;
}

/**
 * Campaign detail — Approval, Threads, Execute.
 *
 * The Approval tab is the gate metric. Two strata, and the split is the whole
 * point: **flagged threads are never sampled**, and the clean stratum is
 * sampled by the server. A rep may redraw as often as they like but cannot
 * choose which threads are in the sample — uniform sampling would let a random
 * 6 of 18 miss all four threads that needed looking at.
 */
@Component({
  selector: 'app-campaign-detail',
  standalone: true,
  imports: [CampaignStrategyComponent, CampaignDraftsComponent, CampaignPersonComponent, CommonModule, FormsModule, RouterLink, IconComponent, FilterPanelComponent, SortableDirective],
  template: `
    <a routerLink="/campaigns" class="back"><app-icon name="back" [size]="14" />All campaigns</a>

    <div class="card" *ngIf="error()" style="border-color:var(--critical);margin:14px 0;">
      <strong style="color:var(--critical);">{{ error() }}</strong>
    </div>

    <h2 style="font-size:1.15rem;margin-bottom:2px;">
      Outreach — {{ approval()?.campaign_label ?? 'campaign' }}
    </h2>
    <p class="row-sub" style="margin-bottom:18px;">
      {{ total() }} thread(s) · {{ approvedCount() }} approved
    </p>

    <div class="tabs">
      <button *ngFor="let t of tabs" class="tab" [class.on]="tab() === t.key"
              (click)="openTab(t.key)" [attr.aria-current]="tab() === t.key">
        {{ t.label }}
        <span class="dot" *ngIf="t.key === 'approval' && pending()"></span>
      </button>
    </div>

    <!-- ============================ APPROVAL ============================ -->
    <ng-container *ngIf="tab() === 'approval'">
      <ng-container *ngIf="approval() as a">
        <!-- An empty campaign is nearly always upstream, not a fault here. Say
             which stage has not run rather than showing a blank approval tab. -->
        <div class="card empty-why" *ngIf="!total()">
          <strong>Nothing saved for approval yet.</strong>
          <span class="row-sub">
            Build each person's strategy, write their cadence drafts, then <em>Save for approval</em> on
            the Cadence drafts tab. Approval reads saved words — the whole campaign is approved from here.
          </span>
          <ul class="why" *ngIf="a.waiting?.length">
            <li class="row-sub" *ngFor="let w of a.waiting">{{ w.name }} — {{ w.state }}</li>
          </ul>
          <ul class="why" *ngIf="a.promotion_notes?.length">
            <li class="row-sub" *ngFor="let n of a.promotion_notes">{{ n }}</li>
          </ul>
          <span class="row-sub" *ngIf="!a.promotion_notes?.length">
            No promotion notes were recorded for this campaign.
          </span>
        </div>

        <div class="card strat-note" *ngIf="total()">
          <strong>Two strata, and the split is the point.</strong>
          <span class="row-sub">
            Threads needing your eyes are <strong>never sampled</strong> — a random 6 of 18 could
            miss all four. The rest are sampled randomly by the server; you can redraw, but not
            choose. Approving the sample accepts the remainder as read on its strength.
          </span>
        </div>

        <p class="row-sub" *ngIf="total() && a.waiting?.length" style="margin:-6px 0 14px;">
          Not saved for approval yet:
          <span *ngFor="let w of a.waiting; let last = last">{{ w.name }} ({{ w.state }}){{ last ? '' : ', ' }}</span>
        </p>

        <!-- flagged -->
        <h3 class="sec" *ngIf="total()">
          Needs your eyes
          <span class="row-sub">{{ a.flagged.length }} — every one read individually</span>
        </h3>
        <div class="card card-flag" *ngFor="let c of a.flagged">
          <div class="card-head">
            <div>
              <strong>{{ c.contact_name }}</strong>
              <span class="row-sub" *ngIf="c.contact_title"> · {{ c.contact_title }}</span>
              <div class="row-sub">{{ c.account_name }}</div>
            </div>
            <span class="badge" [ngClass]="c.approved ? 'badge-good' : 'badge-warn'">
              {{ c.approved ? 'approved' : 'awaiting' }}
            </span>
          </div>
          <p style="margin:8px 0 6px;">{{ c.problem_hypothesis }}</p>
          <p class="row-sub" *ngFor="let r of c.flag_reasons" style="color:var(--warn);">
            {{ r }}
          </p>
          <div class="actions">
            <button class="btn" (click)="openArc(c)">
              <app-icon name="eye" [size]="13" />Review arc
            </button>
            <button class="btn btn-primary" (click)="decide(c, 'approve')"
                    [class.busy]="deciding() === c.sequence_id && decidingKind() === 'approve'"
                    [disabled]="c.approved || !!deciding()">
              <app-icon *ngIf="deciding() !== c.sequence_id" name="check" [size]="13" />
              {{ deciding() === c.sequence_id && decidingKind() === 'approve' ? 'Approving…' : 'Approve' }}
            </button>
            <button class="btn" (click)="rejecting.set(c.sequence_id)" [disabled]="!!deciding()">Reject</button>
          </div>
          <div *ngIf="rejecting() === c.sequence_id" class="reject">
            <select class="field" [(ngModel)]="rejectReason">
              <option value="wrong_persona">wrong persona</option>
              <option value="wrong_signal">wrong signal</option>
              <option value="wrong_problem">wrong problem</option>
              <option value="wrong_solution">wrong solution</option>
              <option value="poor_message">poor message</option>
              <option value="other">other</option>
            </select>
            <button class="btn btn-primary" (click)="decide(c, 'reject')"
                    [class.busy]="deciding() === c.sequence_id && decidingKind() === 'reject'"
                    [disabled]="!!deciding()">
              {{ deciding() === c.sequence_id && decidingKind() === 'reject' ? 'Rejecting…' : 'Confirm reject' }}
            </button>
            <button class="btn" (click)="rejecting.set(null)">Cancel</button>
            <span class="row-sub">A reason is required — the distribution is a gate metric.</span>
          </div>
        </div>
        <p class="row-sub empty" *ngIf="total() && !a.flagged.length">
          Nothing flagged — every thread passed evaluation and has a verified contact.
        </p>

        <!-- clean -->
        <h3 class="sec" *ngIf="total()">
          Clean
          <span class="row-sub">
            {{ a.sample_size }} of {{ a.stratum_size }} drawn at
            {{ (a.sample_rate * 100).toFixed(0) }}%
          </span>
        </h3>

        <div class="card escalated" *ngIf="a.escalated">
          <strong>This batch dropped to individual review.</strong>
          <span class="row-sub">
            Two or more rejections in a sample means the batch itself is not trustworthy. Every
            thread must now be read.
          </span>
        </div>

        <div style="display:flex;gap:10px;align-items:center;margin-bottom:14px;" *ngIf="total()">
          <button class="btn" (click)="redraw()" [class.busy]="working() === 'redraw'"
                  [disabled]="!!working()">
            <app-icon *ngIf="working() !== 'redraw'" name="refresh" [size]="13" />
            {{ working() === 'redraw' ? 'Redrawing…' : 'Redraw sample' }}
          </button>
          <button class="btn btn-primary" (click)="accept()" [class.busy]="working() === 'accept'"
                  [disabled]="!!working() || !a.sample_size || a.escalated || allCleanApproved()">
            <app-icon *ngIf="working() !== 'accept'" name="check" [size]="13" />
            {{ working() === 'accept'
                ? 'Approving…'
                : (allCleanApproved() ? 'Sample accepted' : 'Approve sample and accept the rest') }}
          </button>
          <span class="row-sub" [style.color]="flash() ? 'var(--accent)' : ''">
            {{ flash() ?? 'The draw is server-side — you can re-roll it, never hand-pick it.' }}
          </span>
        </div>

        <div class="table-wrap" *ngIf="total()">
          <table class="data">
            <thead>
              <tr>
                <th>Contact</th><th>Account</th><th>Hypothesis</th>
                <th>Read</th><th class="actcol">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr *ngFor="let c of a.clean" [class.sampled]="c.in_sample">
                <td>
                  <strong>{{ c.contact_name }}</strong>
                  <div class="row-sub" *ngIf="c.contact_title">{{ c.contact_title }}</div>
                </td>
                <td class="row-sub">{{ c.account_name }}</td>
                <td class="row-sub">{{ c.problem_hypothesis }}</td>
                <td>
                  <span class="badge" [ngClass]="c.in_sample ? 'badge-accent' : 'badge-neutral'">
                    {{ c.in_sample ? 'in sample' : 'inherits' }}
                  </span>
                  <div class="row-sub" *ngIf="c.approved" style="margin-top:3px;">
                    approved · {{ c.in_sample ? 'read' : 'unread' }}
                  </div>
                </td>
                <td class="actcol">
                  <button class="act-btn" (click)="openArc(c)"
                          [attr.aria-label]="'Review ' + c.contact_name"
                          [title]="'Review the arc for ' + c.contact_name">
                    <app-icon name="eye" [size]="15" />
                  </button>
                </td>
              </tr>
              <tr *ngIf="!a.clean.length">
                <td colspan="5" class="row-sub" style="text-align:center;padding:22px;">
                  No clean threads.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </ng-container>
    </ng-container>

    <!-- ============================ THREADS ============================= -->
    <ng-container *ngIf="tab() === 'strategy'">
      <app-campaign-strategy [campaignId]="campaignId" [refresh]="refresh()" (changed)="strategyChanged()"
                             (openPerson)="openPerson($event, 'strategy')" />
    </ng-container>

    <ng-container *ngIf="tab() === 'drafts'">
      <app-campaign-drafts [campaignId]="campaignId" [refresh]="refresh()" (changed)="strategyChanged()"
                           (openPerson)="openPerson($event, 'drafts')" />
    </ng-container>

    <app-campaign-person *ngIf="person() as p" [campaignId]="campaignId" [contactId]="p.contact_id"
                         [sequenceId]="p.sequence_id" [section]="p.section"
                         (closed)="person.set(null)" (changed)="personChanged()" />

    <ng-container *ngIf="tab() === 'threads'">
      <app-filter-panel key="campaign-threads" noun="threads"
                      [activeCount]="activeFilters()" [summary]="filterSummary()"
                      [showing]="visibleCards().length" [total]="allThreads().length"
                      (cleared)="clearFilters()">
      <label class="f">Search
        <input class="field" [(ngModel)]="query" (ngModelChange)="touch()"
               placeholder="contact or account">
      </label>
      <label class="f">Approval
        <select class="field" [(ngModel)]="approval2" (ngModelChange)="touch()">
          <option value="">any</option>
          <option value="approved">approved</option>
          <option value="awaiting">awaiting</option>
        </select>
      </label>
      <label class="f">Account
        <select class="field" [(ngModel)]="account" (ngModelChange)="touch()">
          <option value="">any</option>
          <option *ngFor="let v of accounts()" [value]="v">{{ v }}</option>
        </select>
      </label>
    </app-filter-panel>

      <div class="queuepick" *ngIf="withdrawing() as row">
        <span>Take <strong>{{ row.contact_name }}</strong> out of this campaign —</span>
        <input class="field" [(ngModel)]="withdrawReason"
               placeholder="why? e.g. covered by another campaign" aria-label="Reason">
        <button class="btn btn-primary" (click)="confirmWithdraw()"
                [disabled]="!withdrawReason.trim()">Withdraw</button>
        <button class="btn" (click)="withdrawing.set(null)">Cancel</button>
        <span class="row-sub">Nothing is deleted — their drafts and strategy stay, and the row
          stays here greyed with this reason.</span>
      </div>

        <div class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th appSortable="contact" [state]="sort()" (sortChange)="onSort($event)">
                Contact
              </th>
              <th appSortable="account" [state]="sort()" (sortChange)="onSort($event)">
                Account
              </th>
              <th appSortable="touches" [state]="sort()" (sortChange)="onSort($event)">
                Touches
              </th>
              <th appSortable="approved" [state]="sort()" (sortChange)="onSort($event)">
                Status
              </th>
              <th class="actcol">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let c of visibleCards()" [class.withdrawn]="c.withdrawn">
              <td>
                <strong>{{ c.contact_name }}</strong>
                <div class="row-sub" *ngIf="c.contact_title">{{ c.contact_title }}</div>
              </td>
              <td class="row-sub">{{ c.account_name }}</td>
              <td class="mono">{{ c.touch_count }}</td>
              <td>
                <span class="badge"
                      [ngClass]="c.withdrawn ? 'badge-neutral' : (c.approved ? 'badge-good' : 'badge-warn')">
                  {{ c.state }}
                </span>
              </td>
              <td class="actcol">
                <button class="act-btn" (click)="openThread(c)"
                        [attr.aria-label]="'Review ' + c.contact_name"
                        [title]="c.card ? 'Review the arc' : 'Open their cadence drafts'">
                  <app-icon name="eye" [size]="15" />
                </button>
                <button class="act-btn" *ngIf="c.withdrawn" (click)="reinstate(c)"
                        [disabled]="!!working()"
                        [attr.aria-label]="'Put ' + c.contact_name + ' back'"
                        title="Put them back — they will need drafting and approving again">
                  <app-icon name="refresh" [size]="15" />
                </button>
                <button class="act-btn" *ngIf="!c.withdrawn && !enrolled(c)" (click)="askWithdraw(c)"
                        [disabled]="!!working()"
                        [attr.aria-label]="'Withdraw ' + c.contact_name"
                        title="Take them out of this campaign — nothing is deleted">
                  <app-icon name="x" [size]="15" />
                </button>
                <button class="act-btn danger" *ngIf="c.card && !c.withdrawn" (click)="stopOne(c.card)"
                        [disabled]="!!working()"
                        [attr.aria-label]="'Stop ' + c.contact_name"
                        [title]="'Stop this sequence — the only post-enrolment lever'">
                  <app-icon name="pause" [size]="15" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </ng-container>

    <!-- ============================ EXECUTE ============================= -->
    <ng-container *ngIf="tab() === 'execute'">
      <!-- The one step that genuinely needs LGM. Everything before it —
           promoting, drafting, approving — runs without a credential. -->
      <div class="card empty-why" *ngIf="outreachReady() === false">
        <strong>La Growth Machine is not connected, so nothing can be enrolled.</strong>
        <span class="row-sub">
          Execute is refused until it is —
          <a routerLink="/settings/setup" class="link">connect it in API settings</a>.
          Approving the threads above is worth doing first either way: it is the gate that
          cannot be automated, and it is what execute enrols.
        </span>
      </div>

      <div class="card freeze">
        <strong>After execute, the words cannot change.</strong>
        <span class="row-sub">
          LGM reads copy from the lead, not from us. Once written, the only levers are stopping one
          contact's sequence or the whole campaign — editing means stopping and re-enrolling, which
          starts a new sequence from touch 1.
        </span>
      </div>

      <ng-container *ngIf="preflight() as p">
        <div class="table-wrap" style="margin-bottom:16px;">
          <table class="data">
            <thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead>
            <tbody>
              <tr *ngFor="let c of p.checks">
                <td>{{ c.label }}</td>
                <td>
                  <span class="badge" [ngClass]="c.passed ? 'badge-good' : 'badge-warn'">
                    {{ c.passed ? 'pass' : 'blocks' }}
                  </span>
                </td>
                <td class="row-sub">
                  {{ c.detail }}
                  <!-- Who it is about, and the way to fix it. "2 of 4 not
                       approved" without naming the two is a hunt through the
                       campaign; each name opens exactly the screen that can
                       clear this check for that person. -->
                  <div class="whom" *ngIf="!c.passed && c.people.length">
                    <button type="button" class="chip" *ngFor="let who of c.people.slice(0, 6)"
                            (click)="fix(c, who)" [title]="fixHint(c)">
                      {{ who.name }} <span class="go">→ {{ fixLabel(c) }}</span>
                    </button>
                    <!-- Naming six is a shortcut; a hundred is a list, and the
                         list is a screen that already sorts and filters. -->
                    <button type="button" class="chip" (click)="fixAll(c)">
                      <span class="go" *ngIf="c.people.length > 6">+{{ c.people.length - 6 }} more · </span>
                      <span class="go">{{ listLabel(c) }} ({{ c.people.length }})</span>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Offered only when the registered cadence cannot enrol. An LGM
             campaign that is deleted and rebuilt kills its registration; the
             strategy and approved drafts behind it are still good. -->
        <div class="queuepick" *ngIf="!p.passed && cadenceBlocked(p)">
          <span>This campaign's cadence cannot enrol. Move it to</span>
          <select class="field" [(ngModel)]="swapShapeId" aria-label="Replacement cadence">
            <option value="">choose a registered cadence…</option>
            <option *ngFor="let s of swappable()" [value]="s.id">
              {{ s.label }} · {{ s.touch_count }} steps
            </option>
          </select>
          <button class="btn btn-primary" (click)="swapCadence()" [class.busy]="working() === 'swap'"
                  [disabled]="!swapShapeId || !!working()">
            {{ working() === 'swap' ? 'Moving…' : 'Change cadence' }}
          </button>
          <span class="row-sub">
            Keeps the strategy and the drafts, and re-points each touch at the attribute the new
            campaign's step actually reads. Refused if the step counts differ or anything has
            already been written to La Growth Machine.
          </span>
        </div>

        <div style="display:flex;gap:10px;align-items:center;">
          <button class="btn btn-primary" (click)="execute()" [class.busy]="working() === 'execute'"
                  [disabled]="!p.passed || !!working()">
            <app-icon *ngIf="working() !== 'execute'" name="check" [size]="13" />
            {{ working() === 'execute' ? 'Executing…' : 'Execute campaign' }}
          </button>
          <button class="btn" (click)="loadPreflight()" [class.busy]="checking()"
                  [disabled]="!!working() || checking()">
            <app-icon *ngIf="!checking()" name="refresh" [size]="13" />
            {{ checking() ? 'Checking…' : 'Run checks again' }}
          </button>
          <button class="btn danger" (click)="stopAll()" [class.busy]="working() === 'stop'"
                  [disabled]="!!working()">
            {{ working() === 'stop' ? 'Stopping…' : 'Stop campaign' }}
          </button>
          <!-- The way out of a campaign that will not execute. Stopping is for
               one that is sending; a campaign that never sent has nothing to
               stop, and leaving only that button made the dead end look
               permanent. -->
          <button class="btn danger" *ngIf="approval()?.deletable" (click)="deleteCampaign()"
                  [class.busy]="working() === 'delete'" [disabled]="!!working()"
                  title="Delete this campaign and unlock the queue it came from">
            {{ working() === 'delete' ? 'Deleting…' : 'Delete campaign' }}
          </button>
          <span class="row-sub" *ngIf="approval() as a"
                [title]="'This campaign is ' + a.campaign_status">
            <ng-container *ngIf="!a.deletable">
              Nothing to delete — this campaign is {{ a.campaign_status }}, so it is the record of
              what was sent.
            </ng-container>
          </span>
          <span class="row-sub"
                [style.color]="flash() ? 'var(--accent)' : (p.passed ? '' : 'var(--warn)')">
            {{ flash() ?? (p.passed
                ? 'Every check passes' + (checkedAt() ? ' · checked ' + (checkedAt() | date: 'HH:mm:ss') : '') + '.'
                : (p.checks.length - passedCount(p)) + ' check(s) block execution'
                  + (checkedAt() ? ' · checked ' + (checkedAt() | date: 'HH:mm:ss') : '') + '.') }}
          </span>
        </div>
      </ng-container>
    </ng-container>

    <!-- ============================ REPLIES ============================= -->
    <ng-container *ngIf="tab() === 'replies'">
      <p class="row-sub" style="max-width:90ch;margin-bottom:12px;">
        What La Growth Machine has reported for this campaign. Replies arrive on their own where the
        inbox webhook is registered; <strong>Sync now</strong> pulls everything since the last event
        held here, which is the fallback with no public URL and the way to close a gap after one.
        Message text is what a prospect wrote — quoted here, never acted on.
      </p>

      <div style="display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap;">
        <button class="btn btn-primary" (click)="sync()" [class.busy]="working() === 'sync'"
                [disabled]="!!working()">
          <app-icon *ngIf="working() !== 'sync'" name="refresh" [size]="13" />
          {{ working() === 'sync' ? 'Syncing…' : 'Sync now' }}
        </button>
        <span class="row-sub" *ngIf="activity() as a">
          {{ a.sent }} sent · {{ a.received }} received · {{ a.people_replied }} replied
          <span *ngIf="a.last_event_at"> · last {{ a.last_event_at | date: 'd MMM HH:mm' }}</span>
        </span>
      </div>

      <p class="row-sub empty" *ngIf="activity() && !activity()!.events.length">
        Nothing yet. Events appear once the campaign is executing and LGM has something to report.
      </p>

      <div class="table-wrap" *ngIf="activity()?.events?.length">
        <table class="data">
          <thead>
            <tr><th>When</th><th>Who</th><th>What</th><th>Message</th><th>Via</th></tr>
          </thead>
          <tbody>
            <tr *ngFor="let e of activity()!.events">
              <td class="row-sub">{{ e.occurred_at | date: 'd MMM HH:mm' }}</td>
              <td>
                <a *ngIf="e.contact_id" href="" class="link"
                   (click)="$event.preventDefault(); openEventPerson(e)">{{ e.contact_name }}</a>
                <span *ngIf="!e.contact_id" class="row-sub">nobody matched</span>
                <div class="row-sub" *ngIf="e.account_name">{{ e.account_name }}</div>
              </td>
              <td>
                <span class="badge"
                      [ngClass]="e.direction === 'received' ? 'badge-good' : 'badge-neutral'">
                  {{ e.event_type.replace('_', ' ') }}
                </span>
                <div class="row-sub" *ngIf="e.channel">{{ e.channel }}</div>
              </td>
              <td class="row-sub" style="white-space:normal;">{{ e.preview ?? '—' }}</td>
              <td class="row-sub">
                {{ e.received_via }}
                <div *ngIf="e.matched_by">matched by {{ e.matched_by }}</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </ng-container>

    <!-- =========================== ARC DRAWER =========================== -->
    <div class="drawer" *ngIf="arc() as arcView">
      <div class="drawer-head">
        <div>
          <h3 style="font-size:1rem;">{{ arcView.contact_name }}</h3>
          <p class="row-sub">{{ arcView.account_name }} · {{ arcView.status }}</p>
        </div>
        <button class="act-btn" (click)="arc.set(null)" aria-label="Close" title="Close">
          <app-icon name="x" [size]="16" />
        </button>
      </div>

      <!-- Decided here, because this is where the arc is actually read. The
           sample button below still accepts the whole draw in one go; this is
           the same decision, made one person at a time. -->
      <div class="drawer-decide">
        <span class="badge badge-good" *ngIf="arcView.approved">approved</span>
        <!-- Approval reads words. With none written there is nothing to read,
             and the server refuses — so the drawer offers the step that comes
             first instead of a button that cannot work. -->
        <ng-container *ngIf="!arcView.approved && !arcView.touches.length">
          <button class="btn btn-primary" (click)="writeFor(arcView)">Write their drafts</button>
          <span class="row-sub">
            Nothing is drafted for {{ arcView.contact_name }} yet, so there is nothing to approve.
          </span>
        </ng-container>
        <ng-container *ngIf="!arcView.approved && arcView.touches.length">
          <button class="btn btn-primary" (click)="decideArc('approve')"
                  [class.busy]="deciding() === arcView.sequence_id && decidingKind() === 'approve'"
                  [disabled]="!!deciding()">
            <app-icon *ngIf="deciding() !== arcView.sequence_id" name="check" [size]="13" />
            {{ deciding() === arcView.sequence_id && decidingKind() === 'approve' ? 'Approving…' : 'Approve this sequence' }}
          </button>
          <select class="field" [(ngModel)]="rejectReason" aria-label="Reason for rejecting">
            <option value="wrong_persona">wrong persona</option>
            <option value="wrong_signal">wrong signal</option>
            <option value="wrong_problem">wrong problem</option>
            <option value="wrong_solution">wrong solution</option>
            <option value="poor_message">poor message</option>
            <option value="other">other</option>
          </select>
          <button class="btn" (click)="decideArc('reject')"
                  [class.busy]="deciding() === arcView.sequence_id && decidingKind() === 'reject'"
                  [disabled]="!!deciding()">
            {{ deciding() === arcView.sequence_id && decidingKind() === 'reject' ? 'Rejecting…' : 'Reject' }}
          </button>
        </ng-container>
        <span class="row-sub">A rejection needs a reason — the distribution is a gate metric.</span>
      </div>

      <p class="row-sub"><strong>Problem:</strong> {{ arcView.problem_hypothesis }}</p>
      <p class="row-sub"><strong>Trigger:</strong> {{ arcView.trigger_summary }}</p>
      <p class="row-sub"><strong>Positioning:</strong> {{ arcView.positioning }}</p>
      <p class="row-sub" style="margin-bottom:14px;"><strong>Ask:</strong> {{ arcView.cta }}</p>

      <p class="row-sub" style="margin-bottom:10px;">
        One approval covers the whole arc — which is the only way to judge whether touch 5 earns
        its place.
      </p>

      <div class="touch" *ngFor="let t of arcView.touches">
        <div class="touch-head">
          <span class="mono">{{ t.step_no }}{{ t.day_offset === null ? '' : ' · day ' + t.day_offset }}</span><span class="row-sub" *ngIf="t.day_offset === null"> · scheduled in LGM</span>
          <span class="badge badge-neutral">{{ sends(t) }}</span>
          <span class="badge badge-warn" *ngIf="disagrees(t)"
                [title]="'Drafted as ' + t.channel.replace('_', ' ') + ', but LGM sends this step as ' + sends(t)">
            drafted as {{ t.channel.replace('_', ' ') }}
          </span>
          <span class="badge" [ngClass]="dependenceClass(t.signal_dependence)">
            {{ t.signal_dependence }}
          </span>
          <span class="row-sub" *ngIf="t.lgm_position">
            LGM position {{ t.lgm_position }}<span *ngIf="t.lgm_step_name"> · {{ t.lgm_step_name }}</span>
          </span>
        </div>
        <p class="row-sub" *ngIf="t.purpose">{{ t.purpose }}</p>
        <!-- The same slot chips as the person drawer: whoever approves an arc
             should see where each piece of it lands, not just what it says. -->
        <div class="slot" *ngIf="t.subject_allowed || t.subject">
          <span class="slot-id" *ngIf="t.subject_attribute">{{ wire(t.subject_attribute) }}</span>
          <span class="slot-id none" *ngIf="!t.subject_attribute">no subject</span>
          <span class="slot-name">{{ t.subject_attribute_label || noSubject(t) }}</span>
        </div>
        <strong *ngIf="t.subject" style="display:block;margin-top:4px;"
                [class.dead]="!t.subject_allowed">{{ t.subject }}</strong>
        <span class="row-sub" *ngIf="t.subject && !t.subject_allowed">
          will not send — this step has nowhere to put it
        </span>
        <div class="slot" *ngIf="t.lgm_attribute">
          <span class="slot-id">{{ wire(t.lgm_attribute) }}</span>
          <span class="slot-name">{{ t.lgm_attribute_label }}</span>
        </div>
        <p style="white-space:pre-wrap;margin:4px 0 0;font-size:.86rem;">{{ t.body }}</p>
      </div>
    </div>
  `,
  styles: [
    `
      .f { display: flex; flex-direction: column; gap: 4px; font-size: .78rem; }
      .f .field { min-width: 170px; }
      .f .narrow { min-width: 90px; }
      .f.chk { flex-direction: row; align-items: center; gap: 6px; }
      .back { display: inline-flex; align-items: center; gap: 5px; color: var(--accent);
              text-decoration: none; font-size: .84rem; margin-bottom: 14px; }
      .tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); margin-bottom: 18px; }
      .tab { background: none; border: 0; padding: 9px 14px; cursor: pointer; font-size: .86rem;
             color: var(--text-dim); border-bottom: 2px solid transparent; position: relative; }
      .tab.on { color: var(--text); border-bottom-color: var(--accent); font-weight: 500; }
      .dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%;
             background: var(--warn); margin-left: 6px; vertical-align: middle; }
      .sec { font-size: .95rem; margin: 22px 0 10px; display: flex; align-items: baseline; gap: 10px; }
      .card-flag { border-left: 3px solid var(--warn); margin-bottom: 12px; }
      .card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
      .actions { display: flex; gap: 8px; margin-top: 12px; }
      .reject { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
      .reject .field { width: 170px; }
      .strat-note, .freeze { border-color: var(--line); margin-bottom: 18px; }
      .empty-why { border-color: var(--warn); margin-bottom: 18px; }
      .why { margin: 10px 0 0; padding-left: 18px; }
      .freeze { border-color: var(--warn); }
      .escalated { border-color: var(--warn); margin-bottom: 14px; }
      .empty { text-align: center; padding: 24px; }
      tr.sampled { background: var(--accent-soft, rgba(0,0,0,.03)); }
      .drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(560px, 92vw);
                background: var(--surface); border-left: 1px solid var(--line);
                box-shadow: -8px 0 24px rgba(0,0,0,.14); padding: 22px; overflow-y: auto;
                z-index: 40; }
      .drawer-head { display: flex; justify-content: space-between; align-items: flex-start;
                     gap: 12px; margin-bottom: 12px; }
      .touch { border-top: 1px solid var(--line); padding: 12px 0; }
      .touch-head { display: flex; align-items: center; gap: 8px; }
    `,
  ],
})
export class CampaignDetailComponent implements OnInit {
  private api = inject(PipelineService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private confirm = inject(ConfirmService);
  private notify = inject(NotifyService);
  private readiness = inject(ReadinessService);
  /** `false` only once known to be missing — unknown never blocks. */
  outreachReady = computed(() => this.readiness.satisfied('outreach'));

  readonly tabs: { key: Tab; label: string }[] = [
    { key: 'strategy', label: 'Strategy' },
    { key: 'drafts', label: 'Cadence drafts' },
    { key: 'approval', label: 'Approval' },
    { key: 'threads', label: 'Threads' },
    { key: 'execute', label: 'Execute' },
    { key: 'replies', label: 'Replies' },
  ];

  campaignId = '';
  approval = signal<ApprovalView | null>(null);
  preflight = signal<PreflightView | null>(null);
  arc = signal<ArcView | null>(null);
  tab = signal<Tab>('strategy');
  rejecting = signal<string | null>(null);
  /** The campaign-wide action running now: redraw, accept, execute or stop. */
  working = signal<string | null>(null);
  /** The thread a decision is being saved for, and which decision. */
  deciding = signal<string | null>(null);
  decidingKind = signal<'approve' | 'reject' | null>(null);
  /** Load failures only. Action outcomes are corner notices. */
  error = signal<string | null>(null);
  /** Short confirmation rendered *beside the action*, not at the top of the page. */
  flash = signal<string | null>(null);

  rejectReason = 'poor_message';

  /** The person open in the side panel, and which section. */
  person = signal<{ contact_id: string; sequence_id: string; section: PersonSection } | null>(null);
  /** Bumped so the Strategy and Cadence drafts tabs reload after a change in the panel. */
  refresh = signal(0);

  openPerson(p: { contact_id: string; sequence_id: string }, section: PersonSection): void {
    this.person.set({ ...p, section });
  }

  personChanged(): void {
    this.refresh.update((n) => n + 1);
    this.load();
    this.loadPreflight();
  }

  /**
   * Where a blocked check is actually fixed, per person.
   *
   * Approval is read in the arc drawer, because approving without reading is
   * the one thing the gate exists to prevent. Everything else opens that
   * person's panel at the section that can change the answer.
   */
  private static readonly FIX: Record<string, { label: string; hint: string; section?: PersonSection }> = {
    approved: { label: 'read and approve', hint: 'Opens their arc, where you can approve or reject it' },
    strategy: { label: 'build strategy', hint: 'Opens their strategy', section: 'strategy' },
    one_cadence: { label: 'rewrite drafts', hint: 'Opens their cadence drafts', section: 'drafts' },
    content_ready: { label: 'write drafts', hint: 'Opens their cadence drafts', section: 'drafts' },
    attributes: { label: 'shorten the arc', hint: 'Opens their cadence drafts', section: 'drafts' },
    do_not_contact: { label: 'review', hint: 'Opens their strategy and drafts', section: 'strategy' },
    screened: { label: 'review', hint: 'Opens their cadence drafts', section: 'drafts' },
    enrolment_lock: { label: 'review', hint: 'Opens their cadence drafts', section: 'drafts' },
  };

  /**
   * The whole list, filtered to what this check is about.
   *
   * Six names is a shortcut for a small campaign. With a hundred the answer is
   * the screen that already sorts and filters — opened with the filter set, so
   * nobody has to reconstruct what the check just said.
   */
  fixAll(check: PreflightCheck): void {
    if (check.key === 'approved') {
      this.approval2 = 'awaiting';
      this.query = '';
      this.account = '';
      this.touch();
      this.tab.set('threads');
      return;
    }
    const section = CampaignDetailComponent.FIX[check.key]?.section;
    this.tab.set(section === 'strategy' ? 'strategy' : 'drafts');
  }

  listLabel(check: PreflightCheck): string {
    if (check.key === 'approved') return 'open the list, awaiting first';
    const section = CampaignDetailComponent.FIX[check.key]?.section;
    return section === 'strategy' ? 'open Strategy' : 'open Cadence drafts';
  }

  fixLabel(check: PreflightCheck): string {
    return CampaignDetailComponent.FIX[check.key]?.label ?? 'open';
  }

  fixHint(check: PreflightCheck): string {
    return CampaignDetailComponent.FIX[check.key]?.hint ?? 'Opens this person';
  }

  fix(check: PreflightCheck, who: CheckPerson): void {
    const how = CampaignDetailComponent.FIX[check.key];
    if (!how?.section) {
      this.openArc({ sequence_id: who.sequence_id, contact_name: who.name } as ThreadCard);
      return;
    }
    if (!who.contact_id) return;
    this.tab.set(how.section === 'strategy' ? 'strategy' : 'drafts');
    this.openPerson({ contact_id: who.contact_id, sequence_id: who.sequence_id }, how.section);
  }

  activity = signal<CampaignActivity | null>(null);

  /** Opening Execute re-runs the checks; opening Replies re-reads what came back. */
  openTab(key: Tab): void {
    this.tab.set(key);
    this.flash.set(null);
    if (key === 'execute') this.loadPreflight();
    if (key === 'replies') this.loadActivity();
  }

  loadActivity(): void {
    this.api.campaignActivity(this.campaignId).subscribe({
      next: (a) => this.activity.set(a),
      error: () => this.activity.set(null),
    });
  }

  /**
   * Ask LGM what has happened since the last event we hold.
   *
   * Cheap and idempotent: the same message pushed by the webhook and pulled
   * here is one row, because LGM's own message id is what deduplicates it.
   */
  sync(): void {
    this.working.set('sync');
    this.api.syncCampaign(this.campaignId).subscribe({
      next: (r) => {
        this.working.set(null);
        this.loadActivity();
        if (!r.ran) {
          this.notify.warning('Nothing was synced.', r.blocked);
          return;
        }
        const text = `${r.stored} new event(s) · ${r.replies} reply/replies`;
        if (r.unmatched) {
          this.notify.warning(
            text,
            `${r.unmatched} could not be matched to anybody here${r.orphans.length ? ' — leads ' + r.orphans.join(', ') : ''}.`,
          );
        } else {
          this.notify.success(text, r.duplicates ? `${r.duplicates} already held.` : null);
        }
      },
      error: (err) => {
        this.working.set(null);
        this.notify.error('Could not sync with LGM.', apiError(err, 'The server refused.'));
      },
    });
  }

  /** From a reply to the person who sent it. */
  openEventPerson(event: { contact_id: string | null; sequence_id: string | null }): void {
    if (!event.contact_id || !event.sequence_id) return;
    this.tab.set('drafts');
    this.openPerson({ contact_id: event.contact_id, sequence_id: event.sequence_id }, 'drafts');
  }

  /** A strategy was built or the campaign's targets chosen: approval and pre-flight read it. */
  strategyChanged(): void {
    this.load();
    this.loadPreflight();
  }

  ngOnInit(): void {
    this.readiness.refresh();
    this.campaignId = this.route.snapshot.paramMap.get('id') ?? '';
    this.load();
    this.loadPreflight();
  }

  // --- sorting and filtering over every thread in the campaign ---
  //
  // Client-side: the approval payload arrives whole, and the sample draw is
  // server-side precisely so this screen cannot influence it. Sorting a
  // rendered list changes nothing about which threads were drawn.
  sort = signal<SortState>(NO_SORT);

  query = '';
  approval2 = '';
  account = '';
  private revision = signal(0);

  private readonly cardAccessors: Record<string, (c: ThreadRow) => unknown> = {
    contact: (c) => c.contact_name,
    account: (c) => c.account_name,
    touches: (c) => c.touch_count,
    approved: (c) => c.state,
  };

  /**
   * Every person in the campaign, not only those saved for approval.
   *
   * The approval payload holds the two strata; anyone still being drafted is
   * in `waiting`. Filtering the threads list to "awaiting" used to return
   * nothing in exactly the case a rep cared about — the people blocking the
   * gate were the ones the list could not show.
   */
  allThreads = computed((): ThreadRow[] => [
    ...this.allCards().map((c) => ({
      sequence_id: c.sequence_id,
      withdrawn: false,
      contact_id: null,
      contact_name: c.contact_name,
      contact_title: c.contact_title,
      account_name: c.account_name,
      touch_count: c.touch_count,
      approved: c.approved,
      state: c.approved ? 'approved' : 'awaiting your approval',
      card: c,
    })),
    ...(this.approval()?.waiting ?? []).map((w) => ({
      sequence_id: w.sequence_id,
      withdrawn: !!w.withdrawn,
      contact_id: w.contact_id,
      contact_name: w.name,
      contact_title: null,
      account_name: w.account_name,
      touch_count: w.touch_count,
      approved: false,
      state: w.state,
      card: null,
    })),
  ]);

  accounts = computed(() => distinct(this.allThreads(), (c) => c.account_name));

  visibleCards = computed(() => {
    this.revision();
    const rows = this.allThreads().filter((c) => {
      if (
        !matchesText(c, this.query, [
          (r) => r.contact_name,
          (r) => r.contact_title ?? '',
          (r) => r.account_name,
        ])
      ) {
        return false;
      }
      if (this.approval2 === 'approved' && !c.approved) return false;
      if (this.approval2 === 'awaiting' && c.approved) return false;
      return matchesAny(c.account_name, this.account ? [this.account] : []);
    });
    return sortRows(rows, this.sort(), this.cardAccessors);
  });

  activeFilters = computed(() => {
    this.revision();
    return [this.query.trim(), this.approval2, this.account].filter(Boolean).length;
  });

  filterSummary = computed(() => {
    this.revision();
    const parts: string[] = [];
    if (this.query.trim()) parts.push(`"${this.query.trim()}"`);
    if (this.approval2) parts.push(this.approval2);
    if (this.account) parts.push(this.account);
    return parts.join(' · ');
  });

  /** ngModel writes to a plain field, which no signal is watching. */
  touch(): void {
    this.revision.update((n) => n + 1);
  }

  onSort(state: SortState): void {
    this.sort.set(state);
  }

  clearFilters(): void {
    this.query = '';
    this.approval2 = '';
    this.account = '';
    this.touch();
  }

  allCards(): ThreadCard[] {
    const a = this.approval();
    return a ? [...a.flagged, ...a.clean] : [];
  }

  total(): number {
    return this.allCards().length;
  }

  approvedCount(): number {
    return this.allCards().filter((c) => c.approved).length;
  }

  pending(): boolean {
    return this.total() > this.approvedCount();
  }

  passedCount(p: PreflightView): number {
    return p.checks.filter((c) => c.passed).length;
  }

  allCleanApproved(): boolean {
    const clean = this.approval()?.clean ?? [];
    return clean.length > 0 && clean.every((c) => c.approved);
  }

  /** What an action did, in the corner — where it cannot be scrolled past. */
  private say(message: string): void {
    this.notify.success(message);
  }

  dependenceClass(d: string): string {
    // `dated` late in an arc is the failure a rep cannot catch at approval —
    // on day 0 the copy reads perfectly.
    return d === 'dated' ? 'badge-warn' : d === 'implied' ? 'badge-accent' : 'badge-neutral';
  }

  openArc(c: ThreadCard): void {
    this.api.arc(c.sequence_id).subscribe({
      next: (a) => this.arc.set(a),
      error: (err) =>
        this.notify.error(`Could not load ${c.contact_name}'s arc.`, apiError(err, 'The server did not answer.'), {
          retry: NotifyService.retryable(err) ? () => this.openArc(c) : undefined,
        }),
    });
  }

  /**
   * Decide the sequence open in the drawer.
   *
   * The same call the cards make: reading one arc and approving it there is
   * what "read individually" means, and walking back to the row to click the
   * other button is how a rep loses their place in a long sample.
   */
  /** Enrolled or beyond: withdrawal is refused there, stopping is the lever. */
  enrolled(row: ThreadRow): boolean {
    return ['enrolled', 'stopped', 'completed'].some((s) => row.state.startsWith(s));
  }

  /**
   * Take somebody out of this campaign, with a reason.
   *
   * A promoted queue is locked forever, so this is the only way out short of
   * executing around them — and it deletes nothing: the sequence keeps its
   * drafts, the strategy stays, and the row stays visible, greyed, so a
   * campaign cannot quietly lose a person.
   */
  askWithdraw(row: ThreadRow): void {
    this.withdrawReason = '';
    this.withdrawing.set(row);
  }

  /** The person being taken out, while the reason is typed. */
  withdrawing = signal<ThreadRow | null>(null);
  withdrawReason = '';

  confirmWithdraw(): void {
    const row = this.withdrawing();
    const reason = this.withdrawReason.trim();
    if (!row || !reason) return;
    this.withdrawing.set(null);
    this.working.set('withdraw');
    this.api.withdrawFromCampaign(row.sequence_id, reason).subscribe({
      next: () => {
        this.working.set(null);
        this.notify.success(`${row.contact_name} was withdrawn.`, reason);
        this.load();
        this.loadPreflight();
      },
      error: (err) => {
        this.working.set(null);
        this.notify.error(
          `Could not withdraw ${row.contact_name}.`,
          (err as { error?: { detail?: string } })?.error?.detail ?? apiError(err, 'The server refused.'),
        );
      },
    });
  }

  reinstate(row: ThreadRow): void {
    this.working.set('withdraw');
    this.api.reinstateIntoCampaign(row.sequence_id).subscribe({
      next: () => {
        this.working.set(null);
        this.notify.success(`${row.contact_name} is back in the campaign.`,
          'They need drafting and approving again.');
        this.load();
        this.loadPreflight();
      },
      error: (err) => {
        this.working.set(null);
        this.notify.error('Could not put them back.', apiError(err, 'The server refused.'));
      },
    });
  }

  /**
   * Open whatever this row actually needs.
   *
   * A saved arc opens for reading and approving; somebody still being drafted
   * opens at their cadence drafts, which is the step they are waiting on.
   */
  openThread(row: ThreadRow): void {
    if (row.card) {
      this.openArc(row.card);
      return;
    }
    this.tab.set('drafts');
    if (row.contact_id) {
      this.openPerson({ contact_id: row.contact_id, sequence_id: row.sequence_id }, 'drafts');
    }
  }

  /** From an empty arc to the screen that fills it. */
  writeFor(arcView: ArcView): void {
    const contactId = arcView.contact_id;
    this.arc.set(null);
    this.tab.set('drafts');
    if (contactId) {
      this.openPerson({ contact_id: contactId, sequence_id: arcView.sequence_id }, 'drafts');
    }
  }

  decideArc(decision: 'approve' | 'reject'): void {
    const open = this.arc();
    if (!open) return;
    this.decide(
      { sequence_id: open.sequence_id, contact_name: open.contact_name } as ThreadCard,
      decision,
      () => this.api.arc(open.sequence_id).subscribe({ next: (a) => this.arc.set(a) }),
    );
  }

  decide(c: ThreadCard, decision: 'approve' | 'reject', then?: () => void): void {
    this.deciding.set(c.sequence_id);
    this.decidingKind.set(decision);
    this.api
      .decide(c.sequence_id, {
        decision,
        reject_reason: decision === 'reject' ? this.rejectReason : undefined,
      })
      .subscribe({
        next: () => {
          this.deciding.set(null);
          this.decidingKind.set(null);
          this.rejecting.set(null);
          this.notify.success(
            decision === 'approve'
              ? `Approved ${c.contact_name}'s sequence.`
              : `Rejected ${c.contact_name}'s sequence — ${this.rejectReason.replace('_', ' ')}.`,
          );
          this.load();
          this.loadPreflight();
          then?.();
        },
        error: (err) => {
          this.deciding.set(null);
          this.decidingKind.set(null);
          this.notify.error(
            'Could not record the decision.',
            (err as { error?: { detail?: string } })?.error?.detail
              ?? apiError(err, 'The server refused.'),
          );
        },
      });
  }

  redraw(): void {
    this.working.set('redraw');
    this.api.redraw(this.campaignId).subscribe({
      next: (a) => {
        this.approval.set(a);
        this.working.set(null);
        this.say(`Redrawn — ${a.sample_size} of ${a.stratum_size} clean threads.`);
      },
      error: (err) => {
        this.working.set(null);
        // A redraw changes nothing a rep has decided, so retrying is safe.
        this.notify.error('Could not redraw the sample.', apiError(err, 'The server refused.'), {
          retry: NotifyService.retryable(err) ? () => this.redraw() : undefined,
        });
      },
    });
  }

  accept(): void {
    const a = this.approval();
    if (!a) return;
    // Exactly the drawn ids — the server refuses anything else, which is what
    // stops a rep choosing which threads counted as read.
    const decisions: Record<string, string> = {};
    for (const card of a.clean.filter((c) => c.in_sample)) {
      decisions[card.sequence_id] = 'approve';
    }

    this.working.set('accept');
    this.api.acceptSample(this.campaignId, decisions).subscribe({
      next: (r) => {
        this.working.set(null);
        this.say(`${r.sampled} read and approved; ${r.inherited} accepted as inherited.`);
        this.load();
        this.loadPreflight();
      },
      error: (err) => {
        this.working.set(null);
        this.notify.error('Could not accept the sample.', apiError(err, 'The server refused.'));
        this.load();
      },
    });
  }

  /**
   * Asked first: after this the words cannot change and sequences start
   * sending. It was the one irreversible button on the screen with no
   * confirmation at all.
   */
  async execute(): Promise<void> {
    const ok = await this.confirm.ask({
      title: 'Execute this campaign?',
      body:
        'Approved sequences are written into the La Growth Machine audience with their copy. If '
        + 'that campaign is already running they start sending; if it has never been launched, '
        + 'they wait there until you launch it in LGM. After this the words cannot change — the '
        + 'only levers left are stopping one sequence or the whole campaign.',
      confirmLabel: 'Execute campaign',
    });
    if (!ok) return;
    this.working.set('execute');
    this.api.execute(this.campaignId).subscribe({
      next: (r) => {
        this.working.set(null);
        if (r.awaiting_launch) {
          // Said plainly, because "enrolled" alone reads as "sending", and a
          // rep who believes that will wait for replies that cannot come.
          this.notify.success(
            `${r.enrolled.length} sequence(s) written into ${r.audience ? `"${r.audience}"` : 'the LGM audience'}. Nothing is sending yet.`,
            'That campaign has never been launched. Launch it once in La Growth Machine — it '
              + 'starts everyone at step 1 — and replies will come back here.',
          );
        } else {
          this.say(`Enrolled ${r.enrolled.length} sequence(s). Content is now frozen.`);
        }
        this.loadPreflight();
        this.load();
      },
      error: (err) => {
        this.working.set(null);
        this.notify.error('Execution refused.', apiError(err, 'The server refused.'));
        this.loadPreflight();
      },
    });
  }

  async stopOne(c: ThreadCard): Promise<void> {
    const ok = await this.confirm.ask({
      title: `Stop ${c.contact_name}'s sequence?`,
      body:
        'Remaining touches will not send. It cannot be resumed — enrolling again starts a new '
        + 'sequence from touch 1.',
      confirmLabel: 'Stop sequence',
      danger: true,
    });
    if (!ok) return;
    this.working.set('stop-one');
    this.api.stopSequence(c.sequence_id).subscribe({
      next: () => {
        this.working.set(null);
        this.notify.success(`Stopped ${c.contact_name}'s sequence. Remaining touches will not send.`);
        this.load();
      },
      error: (err) => {
        this.working.set(null);
        this.notify.error('Could not stop the sequence.', apiError(err, 'The server refused.'));
      },
    });
  }

  /**
   * Delete a campaign that never sent anything.
   *
   * Stopping is for a campaign in flight; one that cannot execute has nothing
   * to stop, and offering only Stop left a dead end with no way out of it. The
   * server draws the real line — anything written to La Growth Machine, or any
   * execution record, and it refuses with the reason.
   */
  async deleteCampaign(): Promise<void> {
    const label = this.approval()?.campaign_label ?? 'this campaign';
    const ok = await this.confirm.ask({
      title: `Delete ${label}?`,
      body:
        'Nothing has been sent, so there is no record to keep. The strategy and drafts go with it, '
        + 'and the queue it came from unlocks and can be edited again.',
      confirmLabel: 'Delete campaign',
      danger: true,
    });
    if (!ok) return;
    this.working.set('delete');
    this.api.deleteCampaign(this.campaignId).subscribe({
      next: () => {
        this.working.set(null);
        this.notify.success(`${label} deleted.`, 'Its queue is unlocked.');
        void this.router.navigate(['/campaigns']);
      },
      error: (err) => {
        this.working.set(null);
        // The server re-checks: a campaign can start sending between this page
        // rendering and the click, and then it is refused with the reason.
        this.notify.error('That campaign was not deleted.', apiError(err, 'The server refused.'));
        this.load();
      },
    });
  }

  async stopAll(): Promise<void> {
    const ok = await this.confirm.ask({
      title: 'Stop the whole campaign?',
      body: 'Every live sequence stops and no remaining touch will send. This cannot be undone.',
      confirmLabel: 'Stop campaign',
      danger: true,
    });
    if (!ok) return;
    this.working.set('stop');
    this.api.stopCampaign(this.campaignId).subscribe({
      next: (r) => {
        this.working.set(null);
        this.notify.success(`Stopped ${r.stopped} live sequence(s).`);
        this.load();
        this.loadPreflight();
      },
      error: (err) => {
        this.working.set(null);
        this.notify.error('Could not stop the campaign.', apiError(err, 'The server refused.'));
      },
    });
  }

  /**
   * Re-run every check.
   *
   * A snapshot, deliberately: an account can be disqualified, a draft edited
   * or somebody marked do-not-contact between this rendering and the click on
   * Execute — which is why `execute()` runs pre-flight again server-side and
   * refuses on its own answer, not on this one.
   */
  loadPreflight(): void {
    this.checking.set(true);
    this.api.preflight(this.campaignId).subscribe({
      next: (p) => {
        this.preflight.set(p);
        this.checkedAt.set(new Date());
        this.checking.set(false);
      },
      error: () => {
        this.preflight.set(null);
        this.checking.set(false);
      },
    });
  }

  /** When the checks on screen were taken, and whether they are being retaken. */
  checkedAt = signal<Date | null>(null);
  checking = signal(false);

  // --- moving to another cadence -----------------------------------------
  //
  // Only surfaced when the cadence itself is what fails: a campaign deleted
  // and rebuilt in LGM leaves a registration that can no longer enrol, and
  // rebuilding this campaign to escape it would throw away the strategy and
  // every approved draft.
  /** Where each drafted piece lands in LGM — shared with the person drawer. */
  readonly wire = slotWire;
  readonly noSubject = noSubjectReason;
  readonly sends = sendingChannel;
  readonly disagrees = channelDisagrees;

  swapShapeId = '';
  shapes = signal<CadenceShapeView[]>([]);

  cadenceBlocked(p: PreflightView): boolean {
    const cadence = p.checks.find((c) => c.key === 'cadence');
    if (!cadence || cadence.passed) return false;
    if (!this.shapes().length) {
      this.api.cadenceShapes(true).subscribe({ next: (s) => this.shapes.set(s) });
    }
    return true;
  }

  /** Registered cadences that could actually take this campaign. */
  swappable(): CadenceShapeView[] {
    return this.shapes().filter((s) => blockersOf(s).length === 0);
  }

  swapCadence(): void {
    if (!this.swapShapeId) return;
    this.working.set('swap');
    this.api.changeCadence(this.campaignId, this.swapShapeId).subscribe({
      next: (r) => {
        this.working.set(null);
        this.swapShapeId = '';
        this.notify.success(r.detail, 'Strategy and drafts are unchanged. Checks re-run.');
        this.loadPreflight();
        this.load();
      },
      error: (err) => {
        this.working.set(null);
        this.notify.error('The cadence was not changed.', apiError(err, 'The server refused.'));
      },
    });
  }

  private load(): void {
    this.api.approval(this.campaignId).subscribe({
      next: (a) => this.approval.set(a),
      error: (err) => this.error.set(apiError(err, 'Could not load approvals.')),
    });
  }
}
