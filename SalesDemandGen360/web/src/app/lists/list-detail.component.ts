import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import {
  catchError,
  forkJoin,
  map,
  of,
  Observable,
} from 'rxjs';

import { ConfigService, IcpProfile, Service } from '../core/config.service';
import {
  Account,
  AccountList,
  Contact,
  ListsService,
  QueueSummary,
  ResolutionCandidate,
  ResolveReport,
  VerifyReport,
  CompanyCheckReport,
  ContactSuggestion,
  FindReport,
  OpenConflicts,
  asUnsortableField,
  ResearchTier,
} from '../core/lists.service';
import { PipelineService } from '../core/pipeline.service';
import { ACCOUNT_ACTIONS, ACCOUNT_COLUMNS } from '../shared/account-columns';
import { CONTACT_COLUMNS } from '../shared/contact-columns';
import { RowAction } from '../shared/table-view';
import { SUGGESTION_ACTIONS, SUGGESTION_COLUMNS } from '../shared/suggestion-columns';
import { DataTableComponent } from '../shared/data-table.component';
import { IconComponent } from '../shared/icon.component';
import {
  distinct,
  matchesAny,
  matchesText,
  sortRows,
} from '../shared/client-sort';
import { FilterPanelComponent } from '../shared/filter-panel.component';
import { NO_SORT, SortState, SortableDirective } from '../shared/sortable';
import { CsvImportComponent } from './csv-import.component';
import { apiError } from '../shared/api-error';

import { ConfirmService } from '../shared/confirm.service';
import { NotifyService } from '../shared/notify.service';
import { ActivityService } from '../shared/activity.service';
import { RunProgressComponent } from '../shared/run-progress.component';
import { RunItem, SequentialRun } from '../shared/sequential-run';

@Component({
  selector: 'app-list-detail',
  standalone: true,
  imports: [CommonModule, RouterLink, SortableDirective, CsvImportComponent, IconComponent, FormsModule, FilterPanelComponent, DataTableComponent, RunProgressComponent],
  template: `
    <a routerLink="/lists" class="back"><app-icon name="back" [size]="13" />All lists</a>

    <div class="head">
      <div>
        <h2>{{ meta()?.label ?? 'List' }}</h2>
        <p class="row-sub">{{ accounts().length }} accounts · {{ contacts().length }} contacts</p>
      </div>

      <button class="btn btn-primary" (click)="importing.set(!importing())">
        <app-icon [name]="importing() ? 'x' : 'upload'" />
        {{ importing() ? 'Close import' : 'Import CSV' }}
      </button>
    </div>

    <app-csv-import
      *ngIf="importing()"
      [listId]="listId"
      (finished)="onImported()"
      style="display:block;margin-bottom:24px;">
    </app-csv-import>

    <div class="card" *ngIf="error()" style="border-color:var(--critical);margin-bottom:18px;">
      <strong style="color:var(--critical);">{{ error() }}</strong>
    </div>

    <!-- What this list is worked for. Configuration, not an action: set once,
         read by enrichment and research. Collapsed to a summary once set, so the
         table keeps the height; open by default when nothing is chosen yet. -->
    <div class="worked" [class.open]="targetingOpen()">
      <button type="button" class="worked-head" (click)="targetingOpen.set(!targetingOpen())"
              [attr.aria-expanded]="targetingOpen()">
        <span class="chev">›</span>
        <h3>Worked for</h3>
        <span class="row-sub" *ngIf="targetingSet()">{{ targetingSummary() }}</span>
        <span class="row-sub pending" *ngIf="!targetingSet()">
          not set — enrichment needs a service to know who to look for
        </span>
      </button>
      <div class="worked-body" [hidden]="!targetingOpen()">
      <div class="bands">
        <!-- Each column scrolls once its list grows. Wrapping checkboxes read
             fine with three services and become unusable with thirty; a fixed
             height keeps this band the same size whatever the catalogue does. -->
        <div class="band">
          <div class="band-head">
            <span class="lbl">Services</span>
            <input class="field tiny" *ngIf="services().length > 6"
                   [(ngModel)]="serviceFilter" placeholder="filter…"
                   aria-label="Filter services">
          </div>
          <div class="scroll">
            <label *ngFor="let sv of filteredServices()" class="pick">
              <input type="checkbox" [checked]="pickedServices.has(sv.id)"
                     (change)="toggleService(sv.id)">
              <code>{{ sv.code }}</code>
            </label>
            <span class="row-sub" *ngIf="!services().length">
              No active services. Add one before working this list.
            </span>
            <span class="row-sub" *ngIf="services().length && !filteredServices().length">
              Nothing matches that.
            </span>
          </div>
        </div>

        <div class="band">
          <div class="band-head">
            <span class="lbl">ICPs</span>
            <input class="field tiny" *ngIf="reachableIcps().length > 6"
                   [(ngModel)]="icpFilter" placeholder="filter…"
                   aria-label="Filter ICPs">
          </div>
          <div class="scroll">
            <label *ngFor="let p of filteredIcps()" class="pick">
              <input type="checkbox" [checked]="pickedIcps.has(p.id)"
                     (change)="toggleIcp(p.id)">
              {{ p.name }}<span *ngIf="!p.definition" class="warn"> · empty</span>
            </label>
            <span class="row-sub" *ngIf="!reachableIcps().length">
              {{ pickedServices.size
                 ? 'Those services have no ICP yet — enrichment for them is refused.'
                 : 'Choose a service first.' }}
            </span>
            <span class="row-sub" *ngIf="reachableIcps().length && !filteredIcps().length">
              Nothing matches that.
            </span>
          </div>
        </div>
      </div>
        <div class="worked-foot">
          <button class="btn btn-primary" (click)="saveTargeting()" [class.busy]="savingTargeting()"
                  [disabled]="savingTargeting() || !pickedServices.size || !pickedIcps.size">
            {{ savingTargeting() ? 'Saving…' : 'Save targeting' }}
          </button>
          <span class="row-sub">Enrichment and research use this.</span>
        </div>
      </div>
    </div>

    <!-- One place for what the last action did, and for any question an action
         needs answered before it runs (which queue, which service). -->
    <div class="outcomes">
      <p class="row-sub err" *ngIf="targetingError()">{{ targetingError() }}</p>

      <!-- Resolve, enrich and research, while they run: "Researching 3 of 8…",
           what has come back so far, and Cancel. What they came to is a corner
           notice — these used to be report lines here, out of sight once the
           table was scrolled. -->
      <app-run-progress [run]="batch"></app-run-progress>

      <!-- A list becomes a queue, and the queue becomes a campaign later.
           This used to do both at once and ask for a cadence on the way, which
           put the choice of LGM campaign — and with it the schedule — at the
           wrong end of the work: before anyone had looked at who was in it. -->
      <div class="queuepick" *ngIf="pendingPromote() as rows">
        <span>Queue <strong>{{ rows.length }}</strong>
          {{ promoteMode() === 'contacts' ? (rows.length === 1 ? 'person' : 'people') : (rows.length === 1 ? 'account' : 'accounts') }} for</span>
        <select class="field" [(ngModel)]="promoteDraft.service_id" [ngModelOptions]="{standalone:true}"
                (ngModelChange)="promoteDraft.icp_profile_id = ''" aria-label="Service">
          <option value="">service…</option>
          <option *ngFor="let sv of chosenServices()" [value]="sv.id">{{ sv.code }}</option>
        </select>
        <select class="field" [(ngModel)]="promoteDraft.icp_profile_id" [ngModelOptions]="{standalone:true}"
                aria-label="ICP">
          <option value="">ICP…</option>
          <option *ngFor="let i of promoteIcps()" [value]="i.id">{{ i.name }}</option>
        </select>
        <input class="field" [(ngModel)]="promoteDraft.label" [ngModelOptions]="{standalone:true}"
               placeholder="campaign name" aria-label="Campaign name">
        <button class="btn btn-primary" (click)="confirmPromote()" [class.busy]="working() === 'promote'"
                [disabled]="!promoteReady() || !!working()">
          {{ working() === 'promote' ? 'Queueing…' : 'Create queue' }}
        </button>
        <button class="btn" (click)="pendingPromote.set(null)">Cancel</button>
        <span class="row-sub">Opens the queue, where you can still add, drop and review people.
          Promoting it to outreach is where you pick the La Growth Machine campaign — that choice
          carries the cadence and its schedule with it.</span>
      </div>

      <div class="queuepick" *ngIf="pendingSuppress() as rows">
        <span>Mark <strong>{{ rows.length }}</strong> {{ rows.length === 1 ? 'person' : 'people' }} do not contact —</span>
        <input class="field" [(ngModel)]="suppressReason" [ngModelOptions]="{standalone:true}"
               placeholder="why? e.g. asked us to stop" aria-label="Reason">
        <button class="btn btn-primary" (click)="confirmSuppress()"
                [disabled]="!suppressReason.trim()">Mark</button>
        <button class="btn" (click)="pendingSuppress.set(null)">Cancel</button>
        <span class="row-sub">Nothing is deleted — they are skipped by enrichment, research,
          queues and execution from now on.</span>
      </div>

      <div class="queuepick" *ngIf="pendingEnrich() as rows">
        <span>{{ enrichMode() === 'find' ? 'Find contacts at' : 'Enrich contacts at' }} <strong>{{ rows.length }}</strong> account{{ rows.length === 1 ? '' : 's' }} for</span>
        <select class="field" [(ngModel)]="enrichService" [ngModelOptions]="{standalone:true}"
                aria-label="Service to enrich for">
          <option value="">choose a service…</option>
          <option *ngFor="let sv of chosenServices()" [value]="sv.id">{{ sv.code }}</option>
        </select>
        <button class="btn btn-primary" (click)="confirmEnrich()"
                [disabled]="!enrichService || !!working()">{{ enrichMode() === 'find' ? 'Find contacts' : 'Enrich' }}</button>
        <button class="btn" (click)="pendingEnrich.set(null); enrichContacts.set(null)">Cancel</button>
      </div>
      <!-- What the company check could not settle on its own. First, because
           the people search goes by domain. -->
      <div class="fpanel" *ngIf="conflicts().length">
        <div class="fpanel-h">
          <strong>Confirm company details</strong>
          <span class="row-sub">{{ conflictCount() }} to confirm — people are searched by domain, so these come first.</span>
        </div>
        <div class="conf-row" *ngFor="let a of conflicts()">
          <div><strong>{{ a.name }}</strong> <span class="mono row-sub">{{ a.domain }}</span></div>
          <div class="conf-item" *ngFor="let c of a.conflicts">
            <span class="badge badge-warn">{{ fieldLabel(c.field) }}</span>
            <span class="row-sub">{{ c.note }}</span>
            <span class="conf-opts">
              <button class="mini" *ngFor="let o of c.options" [disabled]="settling()"
                      (click)="settle(a, c.field, o.value)">
                Use {{ o.value }} <span class="row-sub">· {{ o.source }}</span>
              </button>
              <button class="mini" [disabled]="settling()" (click)="settle(a, c.field, null)">
                {{ c.current ? 'Keep ' + c.current : 'Leave empty' }}
              </button>
            </span>
          </div>
        </div>
      </div>

      <!-- Which queue. Asked only when Add to queue is used, and only for the
           accounts that can go — the table has already split the selection. -->
      <div class="queuepick" *ngIf="pendingQueue() as rows">
        <span>Add <strong>{{ rows.length }}</strong>
          {{ queueMode() === 'contacts' ? (rows.length === 1 ? 'person' : 'people') : (rows.length === 1 ? 'account' : 'accounts') }} to</span>
        <select class="field" [(ngModel)]="queueChoice" [ngModelOptions]="{standalone:true}"
                aria-label="Queue to add to">
          <option value="">choose a queue…</option>
          <option *ngFor="let q of queueList()" [value]="q.id" [disabled]="!!q.locked_at">
            {{ q.label }}{{ q.locked_at ? ' (locked)' : '' }}
          </option>
        </select>
        <button class="btn btn-primary" (click)="confirmQueue()" [class.busy]="working() === 'queue'"
                [disabled]="!queueChoice || !!working()">
          {{ working() === 'queue' ? 'Adding…' : 'Add' }}
        </button>
        <button class="btn" (click)="pendingQueue.set(null)">Cancel</button>
      </div>
    </div>

    <!-- Accounts and their people, as two views of one list rather than two
         stacked tables. -->
    <div class="tabs" role="tablist">
      <button type="button" class="tab" role="tab" [class.on]="tab() === 'accounts'"
              [attr.aria-selected]="tab() === 'accounts'" (click)="tab.set('accounts')">
        Accounts <span class="count">{{ accounts().length }}</span>
      </button>
      <button type="button" class="tab" role="tab" [class.on]="tab() === 'contacts'"
              [attr.aria-selected]="tab() === 'contacts'" (click)="tab.set('contacts')">
        Contacts <span class="count">{{ contacts().length }}</span>
        <span class="row-sub" *ngIf="contacts().length"> · {{ verifiedCount() }} reachable</span>
      </button>
      <button type="button" class="tab" role="tab" *ngIf="suggestions().length"
              [class.on]="tab() === 'suggestions'" [attr.aria-selected]="tab() === 'suggestions'"
              (click)="tab.set('suggestions')">
        Suggested <span class="count">{{ openSuggestions().length }}</span>
        <span class="row-sub" *ngIf="acceptedCount()"> · {{ acceptedCount() }} accepted</span>
      </button>
    </div>

    <p class="row-sub hint" *ngIf="tab() === 'accounts' && accounts().length">
      Select accounts, then resolve, enrich, research or queue them — the header box selects
      every account shown.
    </p>

    <ng-container *ngIf="tab() === 'accounts'">
    <!-- The accounts, with the columns the reader chose. Replaces a fixed
         nine-column table plus a filter panel that knew about four fields —
         two places to narrow one list, neither of which covered the columns
         somebody had actually turned on. -->
    <app-data-table
      table="accounts"
      noun="accounts"
      emptyText="No accounts on this list yet. Import a CSV to fill it."
      [columns]="accountColumns"
      [data]="accounts()"
      [sort]="sort()"
      (sortChange)="onSort($event)"
      [selectable]="true"
      [rowActions]="accountActions"
      [busyKey]="working()"
      [busyText]="workingText()"
      [scopeLabel]="meta()?.label ?? ''"
      [scope]="listScope"
      (open)="openAccount($event)"
      (bulk)="onBulk($event)"
      (rowAction)="onRowAction($event)"
      [cell]="accountCell">
    </app-data-table>

    <!-- The screen's own scope control. The table never learns what a list is. -->
    <ng-template #listScope>
      <label class="fieldlab">
        List
        <select class="field" [ngModel]="listId" (ngModelChange)="goToList($event)"
                [ngModelOptions]="{standalone:true}" aria-label="Which list to show">
          <option *ngFor="let l of allLists()" [value]="l.id">{{ l.label }}</option>
        </select>
      </label>
    </ng-template>

    <ng-template #accountCell let-row let-column="column" let-value="value">
      <ng-container [ngSwitch]="column.key">
        <a *ngSwitchCase="'name'" class="link" [routerLink]="['/accounts', row.id]">{{ value }}</a>
        <a *ngSwitchCase="'domain'" class="link" [href]="'https://' + row.domain"
           target="_blank" rel="noopener" [class.none]="!row.domain">{{ value }}</a>
        <a *ngSwitchCase="'linkedin_url'" class="link" [href]="row.linkedin_url"
           target="_blank" rel="noopener">{{ value }}</a>
        <!-- Identity, the reason to doubt it, and the means to settle it. The
             table refactor dropped the Accept / Edit / Reject that used to live
             here, which left "check this" accounts with no way forward — every
             resolve button skips them, by design, because they need a person. -->
        <div *ngSwitchCase="'resolution_status'" class="idcell">
          <span class="badge" [ngClass]="identityBadge(row.resolution_status)">{{ value }}</span>
          <span class="row-sub conf" *ngIf="row.resolution_confidence !== null">
            {{ row.resolution_confidence | number: '1.2-2' }}<span *ngIf="row.resolved_by"> · {{ row.resolved_by }}</span>
          </span>
          <div class="row-sub why" *ngIf="row.resolution_note" [title]="row.resolution_note">
            {{ row.resolution_note }}
          </div>

          <span class="btn busy saving-id" *ngIf="saving() === row.id">Saving…</span>
          <div class="idactions" *ngIf="row.resolution_status !== 'resolved' && row.resolution_status !== 'rejected' && saving() !== row.id">
            <button type="button" class="mini" (click)="accept(row)"
                    [disabled]="saving() === row.id || !row.domain"
                    title="Confirm this is the right company. Research is refused until something says yes.">
              Accept
            </button>
            <button type="button" class="mini" (click)="openEdit(row)">Edit</button>
            <button type="button" class="mini danger" (click)="reject(row)"
                    [disabled]="saving() === row.id"
                    title="Not a company we want. Left out of every later stage.">Reject</button>
          </div>
          <div class="idactions" *ngIf="(row.resolution_status === 'resolved' || row.resolution_status === 'rejected') && saving() !== row.id">
            <button type="button" class="mini" (click)="openEdit(row)">Change</button>
          </div>

          <!-- The runners-up, so choosing does not mean searching again. -->
          <details class="cands" *ngIf="(row.resolution_candidates?.length ?? 0) > 1">
            <summary class="row-sub">{{ row.resolution_candidates.length }} candidates</summary>
            <div class="cand" *ngFor="let c of row.resolution_candidates">
              <button type="button" class="mini" (click)="pick(row, c)"
                      [disabled]="saving() === row.id || !c.domain">use</button>
              <code>{{ c.domain || '—' }}</code>
              <span class="row-sub">{{ c.confidence | number: '1.2-2' }}<span *ngIf="c.source"> · {{ c.source }}</span></span>
            </div>
          </details>

          <div class="editrow" *ngIf="editing() === row.id">
            <input class="field tiny" [(ngModel)]="editDomain" [ngModelOptions]="{standalone:true}"
                   placeholder="acme.com" aria-label="Domain">
            <input class="field tiny" [(ngModel)]="editLinkedin" [ngModelOptions]="{standalone:true}"
                   placeholder="linkedin.com/company/…" aria-label="LinkedIn company page">
            <button type="button" class="mini" (click)="saveEdit(row)"
                    [disabled]="saving() === row.id">Save</button>
            <button type="button" class="mini" (click)="editing.set(null)">Cancel</button>
          </div>
        </div>
        <ng-container *ngSwitchCase="'priority_score'">
          <span *ngIf="row.priority_band" class="badge" [ngClass]="bandBadge(row.priority_band)">
            {{ row.priority_band }} {{ row.priority_score }}
          </span>
          <span *ngIf="!row.priority_band" class="row-sub">not qualified</span>
        </ng-container>
        <span *ngSwitchCase="'research_status'" class="badge"
              [ngClass]="pipelineBadge(value)">{{ value }}</span>
        <span *ngSwitchCase="'enrichment_status'" class="badge"
              [ngClass]="pipelineBadge(value)">{{ value }}</span>
        <span *ngSwitchCase="'status'" class="badge"
              [ngClass]="statusBadge(value)">{{ value }}</span>
        <ng-container *ngSwitchDefault>{{ value }}</ng-container>
      </ng-container>
    </ng-template>
    </ng-container>

    <ng-container *ngIf="tab() === 'contacts'">
      <p class="row-sub" *ngIf="!contacts().length && !loadingContacts()">
        No contacts on this list. Enrichment finds addresses for people already
        here — import a file with contact columns, or add them by hand.
      </p>

      <p class="row-sub hint" *ngIf="contacts().length">
        Select people to enrich or re-check their address, research their company, find more
        people there, copy addresses, or add them to a campaign queue — a campaign sends to people,
        and each needs a verified email or a LinkedIn profile.
      </p>
      <app-data-table *ngIf="contacts().length"
                      table="contacts"
                      noun="contacts"
                      emptyText="No contacts on this list yet."
                      [columns]="contactColumns"
                      [data]="contacts()"
                      [sort]="contactSort()"
                      (sortChange)="onContactSort($event)"
                      [selectable]="true"
                      [rowActions]="contactActions"
                      [busyKey]="working() === 'queue' ? 'queue' : null"
                      busyText="Adding…"
                      (bulk)="onContactBulk($event)"
                      (rowAction)="onContactBulk({ action: $event.action, rows: [$event.row], skipped: [] })"
                      (open)="openContact($event)"
                      [cell]="contactCell">
      </app-data-table>

      <ng-template #contactCell let-row let-column="column" let-value="value">
        <ng-container [ngSwitch]="column.key">
          <a *ngSwitchCase="'full_name'" class="link"
             [routerLink]="['/accounts', row.account_id]">{{ value }}</a>
          <span *ngSwitchCase="'email_status'" class="badge"
                [ngClass]="emailBadge(value)">{{ value }}</span>
          <a *ngSwitchCase="'linkedin_url'" class="link" [href]="row.linkedin_url"
             target="_blank" rel="noopener" [class.none]="!row.linkedin_url">
            {{ row.linkedin_url ? 'profile' : '—' }}
          </a>
          <a *ngSwitchCase="'account_name'" class="link"
             [routerLink]="['/accounts', row.account_id]">{{ value }}</a>
          <ng-container *ngSwitchDefault>{{ value }}</ng-container>
        </ng-container>
      </ng-template>
    </ng-container>

    <!-- People Apollo's free search proposed, in the same table as everything
         else: filter to the CTOs, select, accept, reveal. -->
    <ng-container *ngIf="tab() === 'suggestions'">
      <div class="sugg-bar">
        <p class="row-sub">
          Found by Apollo's free search for this list's personas. Select people to accept or
          reject — nothing is revealed, or paid for, until you reveal the accepted ones.
          <em>Apollo has email</em> means Apollo holds an address; you receive it on reveal.
        </p>
        <span class="spacer"></span>
        <span class="row-sub">
          {{ acceptedCount() }} accepted · up to {{ acceptedCount() }} Apollo credit{{ acceptedCount() === 1 ? '' : 's' }}
        </span>
        <button class="btn btn-primary" (click)="reveal()" [class.busy]="working() === 'reveal'"
                [disabled]="!acceptedCount() || !!working()">
          {{ working() === 'reveal' ? 'Revealing…' : 'Reveal all ' + acceptedCount() + ' accepted' }}
        </button>
      </div>

      <app-data-table
        table="suggestions"
        noun="suggestions"
        emptyText="No suggestions yet. Select accounts and use Find contacts (Apollo)."
        [columns]="suggestionColumns"
        [data]="sortedSuggestions()"
        [sort]="suggestionSort()"
        (sortChange)="suggestionSort.set($event)"
        [selectable]="true"
        [rowActions]="suggestionActions"
        [busyKey]="deciding() ? 'accept' : working() === 'reveal' ? 'reveal' : null"
        [busyText]="deciding() ? 'Saving…' : 'Revealing…'"
        [label]="suggestionLabel"
        (open)="openSuggestion($event)"
        (bulk)="onSuggestionBulk($event)"
        (rowAction)="onSuggestionBulk({ action: $event.action, rows: [$event.row], skipped: [] })"
        [cell]="suggestionCell">
      </app-data-table>

      <ng-template #suggestionCell let-row let-column="column" let-value="value">
        <ng-container [ngSwitch]="column.key">
          <a *ngSwitchCase="'account_name'" class="link"
             [routerLink]="['/accounts', row.account_id]">{{ value }}</a>
          <ng-container *ngSwitchCase="'person'">
            {{ row.first_name }} <span class="mono row-sub">{{ row.last_name_hint }}</span>
          </ng-container>
          <span *ngSwitchCase="'status'" class="badge"
                [ngClass]="suggestionBadge(row.status)">{{ value }}</span>
          <ng-container *ngSwitchCase="'linkedin_url'">
            <a *ngIf="row.linkedin_url; else noProfile" class="link" [href]="row.linkedin_url"
               target="_blank" rel="noopener">profile</a>
            <ng-template #noProfile><span class="row-sub">{{ value }}</span></ng-template>
          </ng-container>
          <span *ngSwitchCase="'has_email'" class="badge"
                [ngClass]="row.has_email ? 'badge-good' : 'badge-neutral'">
            {{ row.has_email ? 'has email' : 'no email' }}
          </span>
          <ng-container *ngSwitchDefault>{{ value }}</ng-container>
        </ng-container>
      </ng-template>
    </ng-container>

  `,
  styles: [
    `
      /* A band across the top of the table, not a boxed panel adrift in a
         wide page. */
      .worked { border:1px solid var(--line); border-radius:8px;
                background:var(--card, #fff); padding:12px 14px; margin:12px 0 16px; }
      .worked-head { display:flex; align-items:baseline; gap:10px;
                     margin-bottom:10px; flex-wrap:wrap; }
      .worked-head h3 { font-size:.95rem; margin:0; }
      .worked-head .done { color:var(--muted); }
      /* Two pickers and the actions, across. The actions column is fixed so
         it does not shrink as the other two fill up. */
      .bands { display:grid; grid-template-columns:1fr 1fr; gap:20px;
               align-items:start; }
      @media (max-width: 900px) { .bands { grid-template-columns:1fr 1fr; }
                                  .band.actions { grid-column:1 / -1; } }
      @media (max-width: 620px) { .bands { grid-template-columns:1fr; } }
      .band-head { display:flex; align-items:center; justify-content:space-between;
                   gap:8px; margin-bottom:5px; min-height:22px; }
      .band-head .lbl { font-size:.72rem; text-transform:uppercase;
                        letter-spacing:.04em; color:var(--muted); }
      .field.tiny { padding:2px 6px; font-size:.72rem; max-width:110px; }
      /* Fixed height so the band does not grow with the catalogue. */
      .scroll { display:flex; flex-direction:column; gap:5px; max-height:104px;
                overflow-y:auto; padding-right:4px; }
      .band.actions { display:flex; flex-direction:column; gap:8px; }
      .band.actions .btn { width:100%; justify-content:center; }
      .enrich-row { display:flex; gap:6px; }
      .enrich-row .field { flex:1; min-width:0; }
      .report { margin-top:10px; }
      .worked-head { display:flex; align-items:baseline; gap:10px; width:100%; text-align:left;
                     background:none; border:none; padding:0; cursor:pointer; font:inherit;
                     color:inherit; flex-wrap:wrap; }
      .worked-head h3 { font-size:.95rem; margin:0; }
      .worked-head .chev { display:inline-block; transition:transform .15s; color:var(--muted); }
      .worked.open .worked-head .chev { transform:rotate(90deg); }
      .worked-body { margin-top:12px; }
      .worked-foot { display:flex; gap:10px; align-items:center; margin-top:12px; }
      .pending { color:var(--critical); }
      .outcomes .report, .outcomes .actionmsg { margin:6px 0; }
      .tabs { display:flex; gap:4px; border-bottom:1px solid var(--line); margin:16px 0 8px; }
      .tab { background:none; border:none; border-bottom:2px solid transparent; padding:7px 12px;
             font:inherit; font-size:.86rem; cursor:pointer; color:var(--muted); margin-bottom:-1px; }
      .tab.on { color:inherit; border-bottom-color:var(--accent); font-weight:600; }
      .tab .count { font-size:.74rem; background:var(--line); border-radius:9px; padding:0 6px;
                    margin-left:3px; font-weight:400; }
      .hint { margin:4px 0 6px; }
      .idcell { white-space: normal; }
      .idcell .conf { margin-left: 6px; }
      .idcell .why { max-width: 32ch; margin-top: 2px; overflow: hidden;
                     text-overflow: ellipsis; white-space: nowrap; }
      .idactions { display: flex; gap: 4px; margin-top: 5px; flex-wrap: wrap; }
      .mini { font-size: .7rem; padding: 1px 7px; border: 1px solid var(--line);
              border-radius: 4px; background: transparent; cursor: pointer; }
      .mini:disabled { opacity: .4; cursor: default; }
      .mini.danger { color: var(--critical); border-color: var(--critical); }
      .saving-id { display: inline-flex; margin-top: 5px; font-size: .7rem; padding: 1px 7px;
                   cursor: default; }
      .cands { margin-top: 5px; }
      .cand { display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap;
              padding: 3px 0; border-top: 1px dashed var(--line); }
      .editrow { display: flex; gap: 4px; margin-top: 5px; flex-wrap: wrap; }
      .editrow .field.tiny { max-width: 150px; }
      .queuepick { display:flex; gap:8px; align-items:center; flex-wrap:wrap;
                   padding:9px 11px; margin:8px 0; border:1px solid var(--line);
                   border-radius:7px; font-size:.83rem; }
      .queuepick .field { max-width:260px; }
      .actionmsg { margin:6px 0 4px; }
      .idcell { min-width: 210px; }
      .idcell .conf { margin-left:6px; }
      .idcell .why { max-width:34ch; margin-top:2px; }
      .idlinks { display:flex; gap:8px; align-items:center; margin-top:3px; }
      .idactions { display:flex; gap:4px; margin-top:5px; }
      .mini { font-size:.7rem; padding:1px 7px; border:1px solid var(--line);
              border-radius:4px; background:transparent; cursor:pointer; }
      .mini:disabled { opacity:.4; cursor:default; }
      .mini.danger { color:var(--critical); border-color:var(--critical); }
      .cands { margin-top:5px; }
      .cand { display:flex; gap:6px; align-items:baseline; flex-wrap:wrap;
              padding:3px 0; border-top:1px dashed var(--line); }
      .editrow { display:flex; gap:4px; margin-top:5px; flex-wrap:wrap; }
      .editrow .field.tiny { max-width:150px; }
      .pick { display:flex; align-items:center; gap:5px; font-size:.8rem; }
      .fl { display:flex; flex-direction:column; gap:4px; }
      .warn { color: var(--critical); }
      .err { color: var(--critical); }
      .f { display: flex; flex-direction: column; gap: 4px; font-size: .78rem; }
      .f .field { min-width: 170px; }
      .f .narrow { min-width: 90px; }
      .f.chk { flex-direction: row; align-items: center; gap: 6px; }
      .back { display: inline-flex; align-items: center; gap: 5px; margin-bottom: 14px;
              color: var(--muted); text-decoration: none; font-size: .82rem; }
      .back:hover { color: var(--text); }
      .head { display: flex; justify-content: space-between; align-items: flex-start;
              gap: 20px; margin-bottom: 22px; }
      .head h2 { font-size: 1.15rem; margin-bottom: 4px; }
      .link { color: var(--accent); text-decoration: none; }
    `,
  ],
})
export class ListDetailComponent implements OnInit {
  private api = inject(ListsService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private confirm = inject(ConfirmService);
  private notify = inject(NotifyService);

  listId = '';
  accounts = signal<Account[]>([]);

  // --- filtering ---
  //
  // Client-side over the loaded rows; sorting stays on the server, which has
  // an allowlist for it. The panel reports "showing N of M" so a filtered view
  // never reads as the whole list.
  query = '';
  industry = '';
  research = '';
  enrichment = '';
  status = '';
  minIcp: number | null = null;
  private revision = signal(0);

  industries = computed(() => distinct(this.accounts(), (a) => a.industry));
  researchStates = computed(() => distinct(this.accounts(), (a) => a.research_status));
  enrichmentStates = computed(() => distinct(this.accounts(), (a) => a.enrichment_status));
  statuses = computed(() => distinct(this.accounts(), (a) => a.status));

  visible = computed(() => {
    this.revision();
    const min = this.minIcp;
    return this.accounts().filter(
      (a) =>
        matchesText(a, this.query, [(r) => r.name, (r) => r.domain ?? '']) &&
        matchesAny(a.industry, this.industry ? [this.industry] : []) &&
        matchesAny(a.research_status, this.research ? [this.research] : []) &&
        matchesAny(a.enrichment_status, this.enrichment ? [this.enrichment] : []) &&
        matchesAny(a.status, this.status ? [this.status] : []) &&
        (min === null || Number.isNaN(min) || (a.icp_match_score ?? -1) >= min),
    );
  });

  activeFilters = computed(() => {
    this.revision();
    return [
      this.query.trim(), this.industry, this.research, this.enrichment, this.status,
      this.minIcp === null || Number.isNaN(this.minIcp) ? '' : 'icp',
    ].filter(Boolean).length;
  });

  filterSummary = computed(() => {
    this.revision();
    const parts: string[] = [];
    if (this.query.trim()) parts.push(`"${this.query.trim()}"`);
    if (this.industry) parts.push(this.industry);
    if (this.research) parts.push(`research ${this.research}`);
    if (this.enrichment) parts.push(`enrichment ${this.enrichment}`);
    if (this.status) parts.push(this.status);
    if (this.minIcp !== null && !Number.isNaN(this.minIcp)) parts.push(`ICP ${this.minIcp}+`);
    return parts.join(' · ');
  });

  /** ngModel writes to a plain field, which no signal is watching. */

  // --- targeting ---------------------------------------------------------
  private config = inject(ConfigService);
  private pipeline = inject(PipelineService);

  services = signal<Service[]>([]);
  icpProfiles = signal<IcpProfile[]>([]);
  pickedServices = new Set<string>();
  pickedIcps = new Set<string>();
  savingTargeting = signal(false);
  enriching = signal(false);
  targetingError = signal<string | null>(null);
  targetingSet = signal(false);
  report = signal<VerifyReport | null>(null);
  enrichService = '';
  resolving = signal(false);
  resolveReport = signal<ResolveReport | null>(null);
  editing = signal<string | null>(null);
  saving = signal<string | null>(null);
  editDomain = '';
  editLinkedin = '';

  readonly accountColumns = ACCOUNT_COLUMNS;
  readonly accountActions = ACCOUNT_ACTIONS;
  allLists = signal<AccountList[]>([]);

  /** Green only for a confirmed identity; `check this` is the one state that
   *  needs a person and must not read as settled. */
  identityBadge(status: string): Record<string, boolean> {
    return {
      'badge-good': status === 'resolved',
      'badge-warn': status === 'needs_review',
      'badge-neutral': status === 'unresolved',
      'badge-critical': status === 'rejected',
    };
  }

  /** Green only for high: the band is a ranking, and medium is not a win. */
  bandBadge(band: string): Record<string, boolean> {
    return {
      'badge-good': band === 'high',
      'badge-accent': band === 'medium',
      'badge-neutral': band === 'low' || !band,
    };
  }

  pipelineBadge(v: string): Record<string, boolean> {
    return {
      'badge-good': v === 'complete',
      'badge-warn': v === 'partial' || v === 'running',
      'badge-critical': v === 'failed',
      'badge-neutral': v === 'not_started' || !v,
    };
  }

  statusBadge(v: string): Record<string, boolean> {
    return {
      'badge-good': v === 'qualified',
      'badge-warn': v === 'researching',
      'badge-critical': v === 'disqualified',
      'badge-neutral': v === 'new',
    };
  }

  openAccount(row: any): void {
    this.router.navigate(['/accounts', row.id]);
  }

  /** Switching list navigates rather than refetching in place, so the URL
   *  stays the thing that says which list you are looking at. */
  goToList(id: string): void {
    if (id && id !== this.listId) this.router.navigate(['/lists', id]);
  }

  /**
   * A bulk action runs on what it can; the component has already split the
   * selection and reported the remainder.
   */
  pendingQueue = signal<any[] | null>(null);
  queueList = signal<QueueSummary[]>([]);
  queueChoice = '';
  /** Which action is running, by its table action key — drives every working state. */
  working = signal<string | null>(null);
  /** Resolve, enrich and research run one account at a time, so progress is real. */
  readonly batch = new SequentialRun();
  private activity = inject(ActivityService);
  /** What the running bulk button reads, e.g. "Researching 3 of 8…". */
  workingText = computed(() => {
    const s = this.batch.state();
    return s ? `${s.verb} ${Math.min(s.done + 1, s.total)} of ${s.total}…` : '';
  });

  /**
   * A bulk action runs on what it can; the table has already split the
   * selection and passes only the eligible rows.
   */
  onBulk(run: { action: { key: string }; rows: any[]; skipped: any[] }): void {
    if (!run.rows.length) return;
    if (this.working()) {
      // One action at a time: two runs over the same accounts would race each
      // other's writes, and the progress line can only describe one of them.
      this.notify.info('Another action is still running — wait for it to finish.');
      return;
    }
    const ids = run.rows.map((r) => r.id);
    switch (run.action.key) {
      case 'resolve':
        void this.resolveIdentities(run.rows);
        return;
      case 'recheck':
        void this.resolveIdentities(run.rows, true);
        return;
      case 'enrich':
        this.askEnrich(run.rows);
        return;
      case 'check_company':
        void this.checkCompanies(run.rows);
        return;
      case 'find_contacts':
        this.askEnrich(run.rows, 'find');
        return;
      case 'research':
        void this.askThenResearch(run.rows);
        return;
      case 'qualify':
        void this.runQualify(run.rows);
        return;
      case 'rerun':
        void this.rerunResearch(run.rows);
        return;
      case 'queue':
        this.askQueue(run.rows);
        return;
      case 'promote':
        this.askPromote(run.rows, 'accounts');
        return;
      case 'remove':
        this.removeMembers(ids);
        return;
      case 'accept':
        this.settleMany(run.rows, 'resolved');
        return;
      case 'reject':
        this.settleMany(run.rows, 'rejected');
        return;
    }
  }

  onRowAction(e: { action: { key: string }; row: any }): void {
    this.onBulk({ action: e.action, rows: [e.row], skipped: [] });
  }

  /** Research again, ignoring the reuse window — after asking, since it pays twice. */
  /**
   * The three prices, and what each one buys.
   *
   * **Measured, not estimated.** Per account, from `llm_call` and `serp_call`
   * over the first week of attributed runs. Shown because the whole reason a
   * tier exists is the comparison, and a rep choosing between three numbers
   * they cannot see is choosing blind.
   */
  private readonly TIER_COST: Record<ResearchTier, number> = {
    light: 0.07,
    standard: 0.105,
    deep: 0.245,
  };

  /** Ask which tier, with what each costs for this many accounts. */
  private async askTier(
    rows: RunItem[],
    opts: { title: string; body: string; confirmLabel: string; chosen?: ResearchTier },
  ): Promise<ResearchTier | null> {
    const n = rows.length;
    const price = (tier: ResearchTier) => {
      const total = this.TIER_COST[tier] * n;
      // Two decimals below ten, whole pennies above: "$12.3450" reads as
      // false precision about a figure derived from a published rate.
      return total < 10 ? `~$${total.toFixed(2)}` : `~$${total.toFixed(1)}`;
    };
    const answer = await this.confirm.ask({
      title: opts.title,
      body: opts.body,
      confirmLabel: opts.confirmLabel,
      chosen: opts.chosen ?? 'standard',
      choices: [
        {
          value: 'light',
          label: 'Light',
          cost: price('light'),
          detail:
            'Their site, job boards, the LinkedIn index and trade press. '
            + 'Finds 85% of the signals the full run finds.',
        },
        {
          value: 'standard',
          label: 'Standard',
          cost: price('standard'),
          detail: 'Light, plus company data and funding providers.',
        },
        {
          value: 'deep',
          label: 'Deep',
          cost: price('deep'),
          detail:
            'Everything: licence registers, the conference circuit, and the '
            + 'people at the account.',
        },
      ],
    });
    // `false` is cancel; anything else is the value of the chosen radio.
    return answer ? (answer as ResearchTier) : null;
  }

  private async rerunResearch(
    rows: RunItem[],
    scope: 'both' | 'company' | 'contacts' = 'company',
  ): Promise<void> {
    const n = rows.length;
    const half = scope === 'company' ? "company's" : scope === 'contacts' ? "people's" : '';
    const tier = await this.askTier(rows, {
      title: `Rerun ${half} research for ${n} account${n === 1 ? '' : 's'}?`,
      body:
        `This ignores the reuse window and pays for every ${half || ''} family again — ` +
        'including ones answered in the last few days. Run research reuses those instead.'
        // Said plainly, because the opposite assumption is what cost the money:
        // a rerun used to re-buy both halves whichever one you meant.
        + (scope === 'company'
          ? ' Their people are left alone — research the people separately if you need them again.'
          : ''),
      confirmLabel: 'Rerun research',
    });
    if (tier) await this.runResearch(rows, true, scope, tier);
  }

  /** Pick a tier, then research. The dialog is where the price is said. */
  private async askThenResearch(
    rows: RunItem[],
    scope: 'both' | 'company' | 'contacts' = 'both',
  ): Promise<void> {
    const n = rows.length;
    const tier = await this.askTier(rows, {
      title: `Research ${n} account${n === 1 ? '' : 's'}?`,
      body:
        'Families answered inside the reuse window are skipped, so a second run '
        + 'on the same account usually costs less than this.',
      confirmLabel: 'Research',
    });
    if (tier) await this.runResearch(rows, false, scope, tier);
  }

  /**
   * One account per request, so the screen can say "Researching 3 of 8" and
   * mean it, show what has come back so far, and stop between accounts when
   * asked. The server already researched one account at a time; this only
   * moves the loop to where it can be watched.
   */
  private async runResearch(
    rows: RunItem[],
    force = false,
    scope: 'both' | 'company' | 'contacts' = 'both',
    tier: ResearchTier = 'deep',
  ): Promise<void> {
    this.working.set(force ? 'rerun' : 'research');
    const t = {
      researched: 0, partial: 0, reused: 0, failed: 0, halted: 0, skipped: 0,
      evidence: 0, window: 0, why: '', contacts: 0, noContacts: 0,
      signals: 0, signalsDropped: 0,
    };
    const stop = { reason: '' };
    const summary = () => {
      const bits = [`${t.researched} researched`];
      if (t.partial) bits.push(`${t.partial} partly — some sources failed`);
      if (t.reused) bits.push(`${t.reused} reused`);
      if (t.failed) bits.push(`${t.failed} failed`);
      if (t.halted) bits.push(`${t.halted} halted`);
      if (t.skipped) bits.push(`${t.skipped} skipped — identity not confirmed`);
      if (t.contacts) bits.push(`${t.contacts} contact${t.contacts === 1 ? '' : 's'} researched`);
      if (t.signals) bits.push(`${t.signals} signal${t.signals === 1 ? '' : 's'}`);
      return `${bits.join(' · ')} · ${t.evidence} evidence rows`;
    };
    const out = await this.batch.run<any>({
      verb: force ? 'Re-researching' : 'Researching',
      describe: (_, r: any) =>
        !r.ran || r.blocked
          ? { kind: 'error', text: r.blocked ?? 'could not run' }
          : r.failed
            ? { kind: 'error', text: `failed · ${r.evidence_stored ?? 0} evidence` }
            : r.partial || r.halted || r.skipped_unresolved
              ? { kind: 'warning', text: `${r.partial ? 'partial' : r.halted ? 'halted' : 'not confirmed'} · ${r.evidence_stored ?? 0} evidence · ${r.signals_stored ?? 0} signals` }
              : { kind: 'success', text: r.reused ? 'reused recent research' : `${r.evidence_stored ?? 0} evidence · ${r.signals_stored ?? 0} signals` },
      items: rows,
      call: (id) =>
        this.api.researchAccounts(this.listId, [id], force, this.researchContacts()?.[id], {
          scope,
          tier,
          // A rerun re-sweeps what was asked for. Defaulting this to `both`
          // is the behaviour that re-bought a contact pass on every one of
          // the seven reruns one account had in an afternoon.
          forceScope: scope,
        }),
      onResult: (_, r) => {
        if (!r.ran || r.blocked) {
          // A blocked capability is the same answer for every account.
          stop.reason = r.blocked ?? 'Research could not run.';
          return 'stop';
        }
        t.researched += r.researched ?? 0;
        t.partial += r.partial ?? 0;
        t.reused += r.reused ?? 0;
        t.failed += r.failed ?? 0;
        t.halted += r.halted ?? 0;
        t.skipped += r.skipped_unresolved ?? 0;
        t.evidence += r.evidence_stored ?? 0;
        t.contacts += r.contacts_researched ?? 0;
        t.noContacts += r.no_contacts ?? 0;
        t.signals += r.signals_stored ?? 0;
        t.signalsDropped += r.signals_dropped ?? 0;
        t.window = r.window_days || t.window;
        // The first reason, so a failure says what to fix, not only that it happened.
        const bad = (r.accounts ?? []).find(
          (a: any) => a.outcome === 'failed' || a.outcome === 'halted' || a.outcome === 'partial',
        );
        if (bad && !t.why) t.why = `${bad.name}: ${bad.detail}`;
        return undefined;
      },
      onError: (item, err) => {
        t.failed += 1;
        if (!t.why) t.why = `${item.name}: ${apiError(err, 'the request failed')}`;
        return undefined;
      },
      summary,
    });
    this.working.set(null);
    // Reloaded, not re-filtered: the server wrote each account's research status.
    this.load();

    if (stop.reason) {
      this.notify.error('Research could not run.', stop.reason);
      return;
    }
    const lead = out.cancelled
      ? `Research stopped after ${out.completed} of ${rows.length}: `
      : 'Research: ';
    // **A run that only reused says so first.** It used to open with
    // "0 researched · 0 evidence rows", which is the success message for
    // this case and reads exactly like a button that did nothing — reported
    // as broken, twice. Nothing was bought because nothing needed buying,
    // and the sentence now says that before it says any number.
    const onlyReused = !out.cancelled && t.reused && !t.researched && !t.partial && !t.failed;
    const text = onlyReused
      ? `Already researched in the last ${t.window} days — nothing re-bought`
        + `${t.reused > 1 ? ` for ${t.reused} accounts` : ''}.`
      : `${lead}${summary()}.`
        + (t.reused ? ` Reused means answered within the last ${t.window} days.` : '');
    // The company was still researched; the people need finding first.
    const enrichFirst = t.noContacts
      ? `${t.noContacts} account${t.noContacts === 1 ? ' has' : 's have'} no ICP contact with a `
        + 'verified email — run Enrich contacts, then research again for the people.'
      : null;
    if (t.failed || t.halted || t.partial) {
      const nothing = !t.researched && !t.partial && !t.reused;
      this.notify[nothing ? 'error' : 'warning'](
        text, [t.why, enrichFirst].filter(Boolean).join(' ') || null,
      );
    } else if (out.cancelled || enrichFirst) {
      this.notify.warning(text, enrichFirst);
    } else if (onlyReused) {
      // Named, because a rep who wanted fresh evidence has just been told
      // nothing happened and needs the next move, not an explanation.
      this.notify.success(
        text,
        "Rerun research ignores the window and pays for every family again.",
      );
    } else {
      this.notify.success(text);
    }
  }

  /**
   * Score accounts that already hold signals — one per request, like research,
   * so the screen can report real progress and stop between accounts.
   */
  private async runQualify(rows: RunItem[]): Promise<void> {
    this.working.set('qualify');
    const t = { qualified: 0, skipped: 0, failed: 0, unsupported: 0, signals: 0, why: '' };
    const bands: Record<string, number> = {};
    const stop = { reason: '' };
    const summary = () => {
      const bits = Object.entries(bands).map(([band, n]) => `${n} ${band}`);
      if (t.signals) bits.unshift(`${t.signals} new signal${t.signals === 1 ? '' : 's'}`);
      return (bits.length ? bits.join(' · ') : `${t.qualified} scored`)
        + (t.skipped ? ` · ${t.skipped} skipped` : '')
        + (t.failed ? ` · ${t.failed} failed` : '');
    };
    const out = await this.batch.run<any>({
      verb: 'Re-reading',
      describe: (_, r: any) =>
        !r.ran || r.blocked
          ? { kind: 'error', text: r.blocked ?? 'could not run' }
          : r.failed
            ? { kind: 'error', text: 'scoring failed' }
            : r.skipped
              ? { kind: 'warning', text: 'skipped' }
              : { kind: 'success', text: `scored · ${r.signals_stored ?? 0} signals` },
      items: rows,
      call: (id) => this.api.qualifyAccounts(this.listId, [id]),
      onResult: (_, r) => {
        if (!r.ran || r.blocked) {
          stop.reason = r.blocked ?? 'Qualification could not run.';
          return 'stop';
        }
        t.qualified += r.qualified ?? 0;
        t.signals += r.signals_stored ?? 0;
        t.skipped += r.skipped ?? 0;
        t.failed += r.failed ?? 0;
        for (const [band, n] of Object.entries(r.bands ?? {})) {
          bands[band] = (bands[band] ?? 0) + (n as number);
        }
        for (const a of r.accounts ?? []) {
          t.unsupported += (a.unsupported ?? []).length;
          if (!t.why && a.outcome !== 'qualified') t.why = `${a.name}: ${a.detail}`;
        }
        return undefined;
      },
      onError: (item, err) => {
        t.failed += 1;
        if (!t.why) t.why = `${item.name}: ${apiError(err, 'the request failed')}`;
        return undefined;
      },
      summary,
    });
    this.working.set(null);
    // The server wrote each account's score; the rows have to come back.
    this.load();

    if (stop.reason) {
      this.notify.error('Qualification could not run.', stop.reason);
      return;
    }
    const lead = out.cancelled
      ? `Qualifying stopped after ${out.completed} of ${rows.length}: `
      : 'Qualified: ';
    const detail = [
      t.why,
      t.unsupported
        ? `${t.unsupported} dimension(s) scored 0 — their citations did not resolve.`
        : '',
    ].filter(Boolean).join(' ') || null;
    if (t.failed) this.notify[t.qualified ? 'warning' : 'error'](lead + summary() + '.', detail);
    else if (t.skipped || out.cancelled || t.unsupported) {
      this.notify.warning(lead + summary() + '.', detail);
    } else {
      this.notify.success(lead + summary() + '.');
    }
  }

  private askQueue(rows: any[], mode: 'accounts' | 'contacts' = 'accounts'): void {
    this.queueMode.set(mode);
    this.queueChoice = '';
    this.api.queues().subscribe({
      next: (q) => {
        this.queueList.set(q);
        if (!q.length) {
          this.notify.warning(
            'There are no queues yet.',
            'Create one under Campaign Queues, then add these accounts to it.',
          );
          return;
        }
        this.pendingQueue.set(rows);
      },
      error: (err) =>
        this.notify.error('Could not load the queues.', apiError(err, 'The server did not answer.'), {
          retry: NotifyService.retryable(err) ? () => this.askQueue(rows, mode) : undefined,
        }),
    });
  }

  confirmQueue(): void {
    const rows = this.pendingQueue();
    if (!rows || !this.queueChoice) return;
    const label = this.queueList().find((q) => q.id === this.queueChoice)?.label ?? 'the queue';
    this.working.set('queue');
    const ids = rows.map((r) => r.id);
    const call: Observable<{ added: number; already: number; refused: { reason: string }[] }> =
      this.queueMode() === 'contacts'
        ? this.api.addContactsToQueue(this.queueChoice, ids, this.listId)
        : this.api.addToQueue(this.queueChoice, ids, this.listId);
    call.subscribe({
      next: (r) => {
        this.working.set(null);
        this.pendingQueue.set(null);
        const text = `${r.added} added to ${label}`
          + (r.already ? ` · ${r.already} already there` : '')
          + (r.refused.length ? ` · ${r.refused.length} refused` : '') + '.';
        const reasons = [...new Set(r.refused.map((x) => x.reason))].join('; ') || null;
        if (!r.refused.length) this.notify.success(text);
        else this.notify[r.added ? 'warning' : 'error'](text, reasons);
      },
      error: (err) => {
        this.working.set(null);
        this.notify.error('Could not add to that queue.', apiError(err, 'The server refused.'));
      },
    });
  }

  /** Accounts on this list awaiting a person's decision. */
  reviewCount(): number {
    return this.accounts().filter((a) => a.resolution_status === 'needs_review').length;
  }

  /**
   * Accept or reject a selection's identities in one go. One request per
   * account, because each is a separate decision with its own provenance
   * (`resolved_by = rep`), and one failure must not cost the rest.
   */
  /**
   * Accept or reject a selection's identities. One request per account —
   * each is its own decision with its own provenance — and one failure must
   * not cost the rest.
   */
  private async settleMany(rows: Account[], status: 'resolved' | 'rejected'): Promise<void> {
    if (status === 'rejected') {
      const ok = await this.confirm.ask({
        title: `Reject ${rows.length} account${rows.length === 1 ? '' : 's'}?`,
        body: 'They are left out of every later stage — enrichment, research and queues. '
          + 'You can change an identity back later.',
        confirmLabel: 'Reject',
        danger: true,
      });
      if (!ok) return;
    }
    this.working.set(status === 'resolved' ? 'accept' : 'reject');
    forkJoin(
      rows.map((r) =>
        this.api.setResolution(r.id, { status }).pipe(
          map(() => true),
          catchError(() => of(false)),
        ),
      ),
    ).subscribe((results) => {
      this.working.set(null);
      const done = results.filter(Boolean).length;
      const failed = results.length - done;
      const verb = status === 'resolved' ? 'Accepted' : 'Rejected';
      const text = `${verb} ${done} identit${done === 1 ? 'y' : 'ies'}`
        + (failed ? ` · ${failed} failed` : '') + '.';
      if (!failed) this.notify.success(text);
      else this.notify[done ? 'warning' : 'error'](text);
      this.load();
    });
  }

  /** Membership only. The accounts stay, reachable from every other list they are on. */
  /** Membership only. The accounts stay, reachable from every other list they are on. */
  private async removeMembers(ids: string[]): Promise<void> {
    const name = this.meta()?.label ?? 'this list';
    const ok = await this.confirm.ask({
      title: `Remove ${ids.length} account${ids.length === 1 ? '' : 's'} from ${name}?`,
      body: 'Only their membership of this list. Nothing is deleted: an account on no other '
        + 'list and in no campaign queue goes dormant, with its contacts and research kept.',
      confirmLabel: 'Remove',
      danger: true,
    });
    if (!ok) return;
    this.working.set('remove');
    this.api.removeFromList(this.listId, ids).subscribe({
      next: (r) => {
        this.working.set(null);
        this.notify.success(
          `Removed ${r.removed} from ${name}`
            + (r.not_members ? ` · ${r.not_members} were no longer on it` : '')
            + (r.dormant ? ` · ${r.dormant} now dormant` : '')
            + '. Nothing was deleted.',
        );
        // The server changed, so the rows must come back — `touch()` would
        // only re-filter the ones already on screen.
        this.load();
      },
      error: (err) => {
        this.working.set(null);
        this.notify.error('Could not remove those accounts.', apiError(err, 'The server refused.'));
      },
    });
  }

  readonly contactColumns = CONTACT_COLUMNS;

  /** People go to queues by name — a campaign reaches people, not companies. */
  readonly contactActions: RowAction[] = [
    {
      key: 'enrich',
      label: 'Enrich / re-check',
      can: (c) => !c.do_not_contact && (c.email_status !== 'verified' || !!c.email_recheck),
      why: 'already verified and not due a re-check, or marked do-not-contact',
    },
    {
      key: 'research_person',
      label: 'Research this person',
      can: (c) => !c.do_not_contact,
      why: 'marked do-not-contact',
    },
    // Research and finding people are company-wide work reached from a person:
    // the row a rep is looking at is where they notice it is needed.
    { key: 'research', label: 'Research their company' },
    // The same work with the reuse window ignored. It exists here because a
    // company researched a fortnight ago answers "Research their company"
    // with "0 researched · 1 reused", and the only way to force it used to
    // be leaving the person you were looking at, switching to Accounts and
    // finding their company by name.
    { key: 'rerun_company', label: "Rerun their company's research" },
    { key: 'find_contacts', label: 'Find more people there' },
    {
      key: 'copy_email',
      label: 'Copy email address',
      can: (c) => !!c.email,
      why: 'no address yet',
    },
    {
      key: 'promote',
      label: 'Add to a campaign queue',
      can: (c) =>
        !c.do_not_contact && ((c.email_status === 'verified' && !!c.email) || !!c.linkedin_url),
      why: 'no verified email or LinkedIn profile, or marked do-not-contact',
    },
    {
      key: 'suppress',
      label: 'Mark do not contact',
      can: (c) => !c.do_not_contact,
      why: 'already marked',
    },
    {
      key: 'allow',
      label: 'Allow contact again',
      can: (c) => !!c.do_not_contact,
      why: 'not marked',
    },
    {
      key: 'queue',
      label: 'Add to queue',
      can: (c) =>
        !c.do_not_contact && ((c.email_status === 'verified' && !!c.email) || !!c.linkedin_url),
      why: 'no verified email or LinkedIn profile, or marked do-not-contact',
    },
  ];
  /** Whether the queue picker is adding accounts or people. */
  queueMode = signal<'accounts' | 'contacts'>('accounts');

  /** A person opens their company's page, where their contacts and strategy live. */
  openContact(c: any): void {
    void this.router.navigate(['/accounts', c.account_id]);
  }

  onContactBulk(run: { action: { key: string }; rows: any[]; skipped: any[] }): void {
    if (!run.rows.length) return;
    switch (run.action.key) {
      case 'queue':
        this.askQueue(run.rows, 'contacts');
        return;
      case 'promote':
        this.askPromote(run.rows, 'contacts');
        return;
      case 'enrich':
        this.askEnrichPeople(run.rows);
        return;
      case 'research':
        // The company only. Buying its people as well was invisible on the
        // screen and 40% of the bill.
        void this.askThenResearch(this.companiesOf(run.rows), 'company');
        return;
      case 'rerun_company':
        void this.rerunResearch(this.companiesOf(run.rows), 'company');
        return;
      case 'research_person':
        void this.researchPeople(run.rows);
        return;
      case 'suppress':
        this.pendingSuppress.set(run.rows);
        return;
      case 'allow':
        void this.setSuppression(run.rows, false);
        return;
      case 'find_contacts':
        this.askEnrich(this.companiesOf(run.rows) as any, 'find');
        return;
      case 'copy_email':
        void this.copyEmails(run.rows);
        return;
    }
  }

  // --- straight to a campaign ---------------------------------------------
  //
  // The queue is not skipped, only made for you: it is what records which
  // accounts and people fed the campaign, and promotion locks it forever.
  pendingPromote = signal<any[] | null>(null);
  promoteMode = signal<'accounts' | 'contacts'>('accounts');
  promoteDraft = { label: '', service_id: '', icp_profile_id: '' };

  /** ICPs this list is worked for that the chosen service actually sells to. */
  promoteIcps(): IcpProfile[] {
    const code = this.services().find((s) => s.id === this.promoteDraft.service_id)?.code;
    if (!code) return [];
    return this.icpProfiles().filter(
      (i) => i.service_codes.includes(code) && (!this.pickedIcps.size || this.pickedIcps.has(i.id)),
    );
  }

  promoteReady(): boolean {
    const d = this.promoteDraft;
    return !!(d.label.trim() && d.service_id && d.icp_profile_id);
  }

  private askPromote(rows: any[], mode: 'accounts' | 'contacts'): void {
    const svcs = this.chosenServices();
    if (!svcs.length) {
      this.notify.warning(
        'Choose what this list is worked for first.',
        'A campaign is built for one service and one ICP — strategy and drafting need both.',
      );
      this.targetingOpen.set(true);
      return;
    }
    this.promoteMode.set(mode);
    this.promoteDraft = {
      label: `${this.meta()?.label ?? 'Queue'} — ${new Date().toLocaleDateString()}`,
      service_id: svcs.length === 1 ? svcs[0].id : '',
      icp_profile_id: '',
    };
    this.pendingPromote.set(rows);
  }

  /**
   * Queue, fill, open it — and stop. Promotion to outreach is the queue
   * screen's job, because that is where the LGM campaign is chosen, and with
   * it the cadence and the schedule LGM runs it on.
   *
   * It used to promote in the same breath. That made a half-filled queue into
   * a campaign nobody could unpick, and it asked for a cadence before anyone
   * had seen who was actually in the list.
   */
  confirmPromote(): void {
    const rows = this.pendingPromote();
    if (!rows || !this.promoteReady()) return;
    const d = { ...this.promoteDraft, label: this.promoteDraft.label.trim() };
    const contacts = this.promoteMode() === 'contacts';
    const ids = rows.map((r) => r.id);
    this.working.set('promote');

    this.pipeline
      .createQueue({ label: d.label, service_id: d.service_id, icp_profile_id: d.icp_profile_id })
      .subscribe({
        next: (queue) => {
          const add: Observable<{
            added: number;
            already: number;
            refused: { reason: string }[];
          }> = contacts
            ? this.api.addContactsToQueue(queue.id, ids, this.listId)
            : this.api.addToQueue(queue.id, ids, this.listId);
          add.subscribe({
            next: (r) => {
              if (!r.added) {
                this.working.set(null);
                this.notify.error(
                  'Nobody could be added, so no campaign was created.',
                  [...new Set(r.refused.map((x) => x.reason))].join('; ') || null,
                );
                return;
              }
              this.working.set(null);
              this.pendingPromote.set(null);
              const refused = r.refused.length
                ? ` · ${r.refused.length} left out: ${[...new Set(r.refused.map((x) => x.reason))].join('; ')}`
                : '';
              this.notify.success(
                `${d.label} queued with ${r.added} member(s)${r.already ? ` · ${r.already} already there` : ''}.`,
                `Review them, then promote to outreach and pick the LGM campaign${refused}.`,
              );
              void this.router.navigate(['/queues', queue.id]);
            },
            error: (err) => {
              this.working.set(null);
              this.notify.error('Could not fill the new queue.', this.detail(err, 'The server refused.'));
            },
          });
        },
        error: (err) => {
          this.working.set(null);
          this.notify.error('Could not create the queue.', this.detail(err, 'The server refused.'));
        },
      });
  }

  /** People picked for do-not-contact, waiting on the reason. */
  pendingSuppress = signal<any[] | null>(null);
  suppressReason = '';

  confirmSuppress(): void {
    const rows = this.pendingSuppress();
    if (!rows || !this.suppressReason.trim()) return;
    this.pendingSuppress.set(null);
    void this.setSuppression(rows, true, this.suppressReason.trim());
  }

  /**
   * Mark or unmark, in one call. Not a delete: everything they are cited by
   * stays, and what changes is that later stages refuse them.
   */
  private setSuppression(rows: any[], off: boolean, reason?: string): void {
    const ids = rows.map((c) => c.id);
    this.api.setSuppression(ids, off, reason).subscribe({
      next: (r) => {
        this.suppressReason = '';
        const who = rows.length === 1 ? rows[0].full_name : `${r.updated} people`;
        if (off) {
          this.notify.success(`${who} marked do not contact.`, reason ?? null);
        } else {
          this.notify.success(`${who} can be contacted again.`);
        }
        this.loadContacts();
      },
      error: (e) => this.notify.error('Could not change that.', this.detail(e, 'The server refused.')),
    });
  }

  /**
   * Research the people picked, rather than their whole company.
   *
   * Their company is covered in the same run when it has never been
   * researched — a person's news means little with no company behind it — and
   * skipped when it is inside the reuse window. That is the part worth saying
   * out loud before it runs, because it is where the money goes.
   */
  private async researchPeople(rows: any[]): Promise<void> {
    const byAccount: Record<string, string[]> = {};
    for (const c of rows) (byAccount[c.account_id] ??= []).push(c.id);
    const companies = this.companiesOf(rows);
    const fresh = new Map(this.accounts().map((a) => [a.id, a.research_status]));
    const cold = companies.filter((c) => (fresh.get(c.id) ?? 'not_started') === 'not_started');

    const people = `${rows.length} ${rows.length === 1 ? 'person' : 'people'}`;
    const ok = await this.confirm.ask({
      title: `Research ${people}?`,
      body: cold.length
        ? `${cold.length} of their ${companies.length === 1 ? 'company has' : 'companies have'} never `
          + `been researched (${cold.map((c) => c.name).join(', ')}), so ${cold.length === 1 ? 'it is' : 'they are'} `
          + 'covered in the same run — several AI calls with web search each. Companies researched '
          + 'recently are skipped, and only the people you picked are read.'
        : 'Their companies were researched recently, so only the people you picked are read — one '
          + 'AI call per contact source. Nobody else at their companies is touched.',
      confirmLabel: 'Research',
    });
    if (!ok) return;

    this.researchContacts.set(byAccount);
    await this.runResearch(companies);
    this.researchContacts.set(null);
  }

  /** account id → the people picked at it, when researching named people. */
  researchContacts = signal<Record<string, string[]> | null>(null);

  /** The distinct companies behind the people picked, as the runners take them. */
  private companiesOf(rows: any[]): { id: string; name: string }[] {
    const seen = new Map<string, { id: string; name: string }>();
    for (const c of rows) {
      seen.set(c.account_id, { id: c.account_id, name: c.account_name ?? 'company' });
    }
    return [...seen.values()];
  }

  /**
   * Addresses to the clipboard, newline-separated — a rep pasting into their
   * own mail client is outside the sending path and none of its rules.
   */
  private async copyEmails(rows: any[]): Promise<void> {
    const addresses = rows.map((c) => c.email).filter(Boolean);
    if (!addresses.length) return;
    try {
      await navigator.clipboard.writeText(addresses.join('\n'));
      this.notify.success(
        `Copied ${addresses.length} address${addresses.length === 1 ? '' : 'es'}.`,
        addresses.length === 1 ? addresses[0] : null,
      );
    } catch {
      // A browser that refuses the clipboard is not a failure worth a red
      // notice: show the addresses so they can be copied by hand.
      this.notify.warning('Could not reach the clipboard.', addresses.join(', '));
    }
  }

  /**
   * Enrich exactly the people picked, rather than everyone at their companies.
   *
   * The run is still one call per company — that is how the provider is billed
   * and how progress stays real — but each call carries only the contacts
   * chosen, so picking three people does not spend on the other twenty.
   */
  private askEnrichPeople(rows: any[]): void {
    const byAccount = new Map<string, { id: string; name: string }>();
    const chosen: Record<string, string[]> = {};
    for (const c of rows) {
      byAccount.set(c.account_id, { id: c.account_id, name: c.account_name ?? 'company' });
      (chosen[c.account_id] ??= []).push(c.id);
    }
    this.enrichContacts.set(chosen);
    this.askEnrich([...byAccount.values()] as any);
  }
  contacts = signal<Contact[]>([]);
  loadingContacts = signal(false);
  showContacts = signal(true);
  /** Which view of the list is showing. */
  tab = signal<'accounts' | 'contacts' | 'suggestions'>('accounts');
  /** Targeting band; opened on load when nothing is chosen yet. */
  targetingOpen = signal(false);
  pendingEnrich = signal<Account[] | null>(null);
  /** account id → the contacts picked at it, when enriching named people. */
  enrichContacts = signal<Record<string, string[]> | null>(null);
  contactSort = signal<SortState>(NO_SORT);

  verifiedCount(): number {
    return this.contacts().filter((c) => c.email_status === 'verified').length;
  }

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
    this.loadingContacts.set(true);
    this.api.listContacts(this.listId, this.contactSort()).subscribe({
      next: (rows) => {
        this.contacts.set(rows);
        this.loadingContacts.set(false);
      },
      error: () => this.loadingContacts.set(false),
    });
  }

  serviceFilter = '';
  icpFilter = '';

  /**
   * Filtering is a display concern only — a ticked row that scrolls out of
   * view stays ticked, because the selection lives in the Set rather than in
   * what happens to be rendered.
   */
  /**
   * How sure we are, and how much that number is worth.
   *
   * `needs_review` is deliberately loud. It is not a failure — it is the
   * honest answer when two companies are plausible — but it is the one state
   * that needs a person, and a quiet badge would let it sit unnoticed while
   * everything downstream waits.
   */
  resBadge(a: Account): Record<string, boolean> {
    return {
      'badge-good': a.resolution_status === 'resolved',
      'badge-warn': a.resolution_status === 'needs_review',
      'badge-neutral': a.resolution_status === 'unresolved',
      'badge-critical': a.resolution_status === 'rejected',
    };
  }

  resLabel(a: Account): string {
    return (
      {
        resolved: 'confirmed',
        needs_review: 'check this',
        unresolved: 'not identified',
        rejected: 'rejected',
      }[a.resolution_status] ?? a.resolution_status
    );
  }

  /** Tier 0, one account per request — see `runResearch` for why. */
  private async resolveIdentities(rows: RunItem[], recheck = false): Promise<void> {
    this.working.set('resolve');
    const t = { checked: 0, resolved: 0, review: 0, notFound: 0, unavailable: 0 };
    const stop = { reason: '' };
    const summary = () =>
      `${t.resolved} resolved · ${t.review} need review · ${t.notFound} not found`;
    const out = await this.batch.run<ResolveReport>({
      verb: recheck ? 'Re-checking' : 'Resolving',
      describe: (_, r: any) => {
        const o = r.outcomes?.[0];
        if (!r.ran) return { kind: 'error', text: r.blocked ?? 'could not run' };
        if (!o) return { kind: 'success', text: 'nothing to resolve' };
        const kind = o.outcome === 'resolved' ? 'success' : o.outcome === 'unavailable' ? 'error' : 'warning';
        return { kind, text: `${String(o.outcome).replace('_', ' ')}${o.detail ? ' — ' + o.detail : ''}` };
      },
      items: rows,
      call: (id) => this.api.resolveAccounts(this.listId, 1, [id], recheck),
      onResult: (_, r) => {
        if (!r.ran) {
          stop.reason = r.blocked ?? 'Resolution could not run.';
          return 'stop';
        }
        t.checked += r.checked;
        t.resolved += r.resolved;
        t.review += r.needs_review;
        t.notFound += r.unresolved;
        t.unavailable += r.unavailable;
        return undefined;
      },
      onError: (_, err) => {
        stop.reason = apiError(err, 'Resolution could not run.');
        return 'stop';
      },
      summary,
    });
    this.working.set(null);
    this.enrichContacts.set(null);
    // `load()`, not `touch()`: the server changed, so the rows have to come back.
    this.load();

    if (stop.reason) {
      this.notify.error('Identity resolution stopped.', stop.reason);
      return;
    }
    const lead = out.cancelled ? `Stopped after ${out.completed} of ${rows.length}. ` : '';
    if (!t.checked) {
      // Not an error, and it must not read like one: the resolver touches only
      // unidentified accounts, and everything else is settled or with a person.
      this.notify.info(`${lead}Nothing left to resolve automatically.`);
      return;
    }
    const text = `${lead}Identity: ${t.checked} checked · ${summary()}`
      + (t.unavailable ? ` · ${t.unavailable} unavailable` : '') + '.';
    if (t.review) {
      this.notify.warning(
        text, 'Accept, Edit or Reject the ones marked "check this" in the Identity column.',
      );
    } else {
      this.notify.success(text);
    }
  }

  accept(a: Account): void {
    this.patch(a, { status: 'resolved' });
  }

  reject(a: Account): void {
    this.patch(a, { status: 'rejected' });
  }

  /** Take a runner-up. Accepting it *is* the confirmation, so both travel. */
  pick(a: Account, c: ResolutionCandidate): void {
    this.patch(a, {
      status: 'resolved',
      domain: c.domain,
      linkedin_url: c.linkedin_url,
      industry: c.industry,
      employee_count: c.employee_count,
    });
  }

  openEdit(a: Account): void {
    this.editDomain = a.domain ?? '';
    this.editLinkedin = a.linkedin_url ?? '';
    this.editing.set(a.id);
  }

  /**
   * A typed correction is a decision, so it resolves in the same call.
   * Saving without confirming would leave the account still blocked from
   * research with nothing on screen explaining why.
   */
  saveEdit(a: Account): void {
    this.patch(a, {
      status: 'resolved',
      domain: this.editDomain.trim() || null,
      linkedin_url: this.editLinkedin.trim() || null,
    });
  }

  private patch(a: Account, body: Parameters<ListsService['setResolution']>[1]): void {
    this.saving.set(a.id);
    this.api.setResolution(a.id, body).subscribe({
      next: () => {
        this.saving.set(null);
        this.editing.set(null);
        // `load()`, not `touch()`: the server changed, so the rows have to
        // come back. `touch()` only re-runs the client-side filter, which
        // repaints identical data and reads as the action doing nothing.
        this.load();
      },
      error: (err) => {
        this.saving.set(null);
        // 422 carries the reason — a bare word offered as a domain, or an
        // /in/ URL offered as a company page. It used to land in the
        // targeting band's error line, nowhere near the row that failed.
        this.notify.error(`Could not save ${a.name}'s identity.`, apiError(err, 'The server refused.'), {
          retry: NotifyService.retryable(err) ? () => this.patch(a, body) : undefined,
        });
      },
    });
  }

  filteredServices(): Service[] {
    const q = this.serviceFilter.trim().toLowerCase();
    const rows = this.services();
    return q ? rows.filter((s) => s.code.toLowerCase().includes(q)) : rows;
  }

  filteredIcps(): IcpProfile[] {
    const q = this.icpFilter.trim().toLowerCase();
    const rows = this.reachableIcps();
    return q ? rows.filter((p) => p.name.toLowerCase().includes(q)) : rows;
  }

  /** The chosen services, as rows. */
  /** "EIA · Default" — what the collapsed band says. */
  targetingSummary(): string {
    const svc = this.chosenServices().map((x) => x.code);
    const icp = this.icpProfiles().filter((p) => this.pickedIcps.has(p.id)).map((p) => p.name);
    return [svc.join(', '), icp.join(', ')].filter(Boolean).join(' · ');
  }

  /**
   * Enrich from the selection bar. One targeted service runs straight away;
   * several ask which; none sends the rep to "Worked for". The old screen
   * left an Enrich button greyed until a small dropdown beside it was used,
   * and never said so.
   */
  askEnrich(rows: Account[], mode: 'enrich' | 'find' = 'enrich'): void {
    this.enrichMode.set(mode);
    const svcs = this.chosenServices();
    if (!svcs.length) {
      this.notify.warning(
        'Choose what this list is worked for first.',
        'Enrichment needs a service and an ICP to know who to look for.',
      );
      this.targetingOpen.set(true);
      return;
    }
    if (svcs.length === 1) {
      this.enrichService = svcs[0].id;
      void this.runChosen(rows);
      return;
    }
    this.pendingEnrich.set(rows);
  }

  confirmEnrich(): void {
    const rows = this.pendingEnrich();
    if (!rows || !this.enrichService) return;
    this.pendingEnrich.set(null);
    void this.runChosen(rows);
  }

  private runChosen(rows: RunItem[]): Promise<void> {
    return this.enrichMode() === 'find' ? this.findContacts(rows) : this.enrich(rows);
  }

  // --- search-first enrichment ----------------------------------------------

  /** Whether the service question is asked for enrichment or for finding people. */
  enrichMode = signal<'enrich' | 'find'>('enrich');
  conflicts = signal<OpenConflicts[]>([]);
  suggestions = signal<ContactSuggestion[]>([]);
  settling = signal(false);
  deciding = signal(false);

  openSuggestions = computed(() =>
    this.suggestions().filter((s) => s.status === 'proposed' || s.status === 'accepted'),
  );
  acceptedCount = computed(() => this.suggestions().filter((s) => s.status === 'accepted').length);
  readonly suggestionColumns = SUGGESTION_COLUMNS;
  readonly suggestionActions = SUGGESTION_ACTIONS;
  suggestionSort = signal<SortState>(NO_SORT);
  suggestionLabel = (r: ContactSuggestion): string =>
    [r.first_name, r.last_name_hint].filter(Boolean).join(' ') || 'suggestion';
  /** Sorted in the browser, by the same value each column shows and filters on. */
  sortedSuggestions = computed(() =>
    sortRows(
      this.suggestions(),
      this.suggestionSort(),
      Object.fromEntries(
        SUGGESTION_COLUMNS.map((c) => [c.key, c.value ?? ((r: any) => r[c.key])]),
      ) as Record<string, (r: ContactSuggestion) => any>,
    ),
  );

  conflictCount(): number {
    return this.conflicts().reduce((n, a) => n + a.conflicts.length, 0);
  }

  fieldLabel(field: string): string {
    return ({ domain: 'Domain', linkedin_url: 'LinkedIn page', hq_country: 'Country' } as Record<string, string>)[field] ?? field;
  }

  private loadFindings(): void {
    if (!this.listId) return;
    this.api.companyConflicts(this.listId).subscribe({
      next: (rows) => this.conflicts.set(rows),
      error: () => this.conflicts.set([]),
    });
    // Every status, so the table's Decision filter can show rejected and revealed too.
    this.api.suggestions(this.listId).subscribe({
      next: (rows) => this.suggestions.set(rows),
      error: () => this.suggestions.set([]),
    });
  }

  /** The company check, one account per request. */
  private async checkCompanies(rows: RunItem[]): Promise<void> {
    if (!this.listId) return;
    this.working.set('check');
    const t = { checked: 0, filled: 0, conflicts: 0, credits: 0, noApollo: false, apolloError: '' };
    const stop = { reason: '' };
    const summary = () =>
      `${t.filled} detail${t.filled === 1 ? '' : 's'} filled · ${t.conflicts} to confirm`;
    const out = await this.batch.run<CompanyCheckReport>({
      verb: 'Checking',
      describe: (_, r: any) =>
        r.apollo_error
          ? { kind: 'warning', text: `Apollo: ${r.apollo_error}` }
          : r.conflicts
            ? { kind: 'warning', text: `${r.filled} filled · ${r.conflicts} to confirm` }
            : { kind: 'success', text: `${r.filled} filled` },
      items: rows,
      call: (id) => this.api.checkCompanies(this.listId, [id]),
      onResult: (_, r) => {
        t.checked += r.checked;
        t.filled += r.filled;
        t.conflicts += r.conflicts;
        t.credits += r.apollo_credits;
        t.noApollo = t.noApollo || !r.apollo_available;
        if (r.apollo_error) t.apolloError = r.apollo_error;
        return undefined;
      },
      onError: (_, e) => {
        stop.reason = this.detail(e, 'Could not check these companies.');
        return 'stop';
      },
      summary,
    });
    this.working.set(null);
    this.load();

    if (stop.reason) {
      this.notify.error('Company check stopped.', stop.reason);
      return;
    }
    const lead = out.cancelled ? `Stopped after ${out.completed} of ${rows.length}. ` : '';
    const paid = t.credits ? ` · ${t.credits} Apollo credit${t.credits === 1 ? '' : 's'}` : '';
    const text = `${lead}Checked ${t.checked} compan${t.checked === 1 ? 'y' : 'ies'}: ${summary()}${paid}.`;
    const note = t.apolloError
      ? `Apollo: ${t.apolloError}`
      : t.noApollo
        ? 'No Apollo key is stored — only the websites were read.'
        : null;
    if (t.conflicts || note || out.cancelled) this.notify.warning(text, note);
    else this.notify.success(text);
  }

  /** Apollo's free people search, one account per request. Suggestions only. */
  private async findContacts(rows: RunItem[]): Promise<void> {
    const service = this.enrichService;
    if (!this.listId || !service) return;
    this.working.set('find');
    const t = {
      proposed: 0, refreshed: 0, onList: 0, known: 0, decided: 0, dropped: 0,
      perPersona: 0, personas: [] as string[], skipped: [] as string[],
    };
    const stop = { reason: '' };
    const summary = () =>
      `${t.proposed} new suggestion${t.proposed === 1 ? '' : 's'} · ${t.onList} already on the list`;
    const out = await this.batch.run<FindReport>({
      verb: 'Searching',
      describe: (_, r: any) =>
        !r.ran
          ? { kind: 'error', text: r.blocked ?? 'could not search' }
          : { kind: r.proposed || r.refreshed || r.known ? 'success' : 'warning',
              text: `${r.proposed} new · ${r.refreshed} still waiting · ${r.filtered} filtered` },
      items: rows,
      call: (id) => this.api.findContacts(this.listId, service, [id]),
      onResult: (_, r) => {
        if (!r.ran) {
          stop.reason = r.blocked ?? 'The search could not run.';
          return 'stop';
        }
        t.proposed += r.proposed;
        t.refreshed += r.refreshed;
        t.onList += r.on_list;
        t.known += r.known;
        t.decided += r.already_decided;
        t.dropped += r.dropped ?? 0;
        t.perPersona = r.per_persona;
        t.personas = r.personas;
        t.skipped = r.skipped_personas;
        return undefined;
      },
      onError: (_, e) => {
        // 409 names what is missing (no ICP, no personas); 502 is Apollo failing.
        const detail = (e as { error?: { detail?: { message?: string } } })?.error?.detail;
        stop.reason = detail?.message ?? this.detail(e, 'Could not search for contacts.');
        return 'stop';
      },
      summary,
    });
    this.working.set(null);
    this.load();

    if (stop.reason) {
      this.notify.error('Finding contacts stopped.', stop.reason);
      return;
    }
    const lead = out.cancelled ? `Stopped after ${out.completed} of ${rows.length}. ` : '';
    const extra = [
      t.refreshed ? `${t.refreshed} still waiting for a decision` : '',
      t.known ? `${t.known} already complete` : '',
      t.decided ? `${t.decided} decided before` : '',
      t.dropped ? `${t.dropped} earlier suggestion${t.dropped === 1 ? '' : 's'} no longer kept` : '',
    ].filter(Boolean).join(' · ');
    const who = t.personas.join(', ') || 'the personas';
    const text =
      `${lead}Searched for ${who} (up to ${t.perPersona} each): ${summary()}` +
      `${extra ? ' · ' + extra : ''}. Free — review them in the Suggested tab.`;
    const note = t.skipped.length ? `Not searched, no titles to search on: ${t.skipped.join(', ')}` : null;
    if (t.proposed || t.refreshed) this.tab.set('suggestions');
    if (note || out.cancelled) this.notify.warning(text, note);
    else this.notify.success(text);
  }

  settle(a: OpenConflicts, field: string, value: string | null): void {
    this.settling.set(true);
    this.api.settleConflict(a.account_id, field, value).subscribe({
      next: () => {
        this.settling.set(false);
        this.load();
      },
      error: (err) => {
        this.settling.set(false);
        this.notify.error('Could not save that.', apiError(err, 'The server refused.'));
      },
    });
  }

  /** The table's bulk bar and row menus. It has already split the selection. */
  onSuggestionBulk(run: { action: { key: string }; rows: any[]; skipped: any[] }): void {
    const ids = run.rows.map((r) => r.id);
    if (!ids.length) return;
    switch (run.action.key) {
      case 'accept':
        this.decideIds(ids, 'accepted');
        return;
      case 'reject':
        this.decideIds(ids, 'rejected');
        return;
      case 'undecide':
        this.decideIds(ids, 'proposed');
        return;
      case 'reveal':
        void this.reveal(ids);
        return;
    }
  }

  openSuggestion(row: any): void {
    void this.router.navigate(['/accounts', row.account_id]);
  }

  suggestionBadge(status: string): string {
    return (
      {
        accepted: 'badge-accent',
        revealed: 'badge-good',
        known: 'badge-good',
        not_found: 'badge-warn',
        rejected: 'badge-critical',
      }[status] ?? 'badge-neutral'
    );
  }

  private decideIds(ids: string[], status: ContactSuggestion['status']): void {
    this.deciding.set(true);
    this.api.decideSuggestions(this.listId, ids, status).subscribe({
      next: () => {
        this.deciding.set(false);
        const chosen = new Set(ids);
        this.suggestions.update((rows) => rows.map((r) => (chosen.has(r.id) ? { ...r, status } : r)));
        const verb = { accepted: 'Accepted', rejected: 'Rejected', proposed: 'Moved back to undecided' }[
          status as 'accepted' | 'rejected' | 'proposed'
        ];
        if (verb) this.notify.success(`${verb}: ${ids.length} suggestion${ids.length === 1 ? '' : 's'}.`);
      },
      error: (err) => {
        this.deciding.set(false);
        this.notify.error('Could not record that.', apiError(err, 'The server refused.'));
      },
    });
  }

  /** Paid, so asked first: one credit per accepted person Apollo has data for. */
  async reveal(ids?: string[]): Promise<void> {
    const n = ids?.length ?? this.acceptedCount();
    // One reveal at a time: a second click while one runs would buy the same
    // people again in a parallel request.
    if (!n || this.working()) return;
    const ok = await this.confirm.ask({
      // Says which: the selection, or every accepted suggestion on the list.
      title: ids
        ? `Reveal ${n} selected contact${n === 1 ? '' : 's'}?`
        : `Reveal all ${n} accepted contact${n === 1 ? '' : 's'}?`,
      body:
        `Apollo charges one credit per person it has data for — up to ${n} here. ` +
        'Work email and LinkedIn profile only: no personal emails, no phone numbers.',
      confirmLabel: 'Reveal',
    });
    if (!ok) return;
    this.working.set('reveal');
    this.api.revealSuggestions(this.listId, ids).subscribe({
      next: (r) => {
        this.working.set(null);
        this.load();
        if (!r.ran) {
          this.notify.error('Nothing was revealed.', r.blocked ?? 'Apollo could not be called.');
          return;
        }
        const s = (k: number) => (k === 1 ? '' : 's');
        const text =
          `Revealed ${r.revealed} of ${r.asked}: ${r.created} new contact${s(r.created)} · ` +
          `${r.updated} updated · ${r.verified} verified · ${r.risky} risky · ${r.no_email} without email · ` +
          `${r.linkedin} LinkedIn profile${s(r.linkedin)} · ${r.credits} credit${s(r.credits)}` +
          (r.reused ? ` · ${r.reused} already revealed or saved in Apollo, no credit spent` : '') +
          (r.saved_to_apollo ? ` · ${r.saved_to_apollo} saved to Apollo (label Gen360)` : '') + '.';
        const note = [
          r.stopped ? `Apollo ran out of credits — ${r.asked - r.revealed} still accepted for next time.` : '',
          r.not_found ? `${r.not_found} not found by Apollo` : '',
          r.save_error ? `Not saved to Apollo: ${r.save_error}` : '',
          ...r.notes,
        ]
          .filter(Boolean)
          .join(' · ');
        if (note) this.notify.warning(text, note);
        else this.notify.success(text);
      },
      error: (err) => {
        this.working.set(null);
        const detail = (err as { error?: { detail?: { message?: string } } })?.error?.detail;
        this.notify.error('Reveal failed.', detail?.message ?? apiError(err, 'The server refused.'));
      },
    });
  }

  chosenServices(): Service[] {
    return this.services().filter((s) => this.pickedServices.has(s.id));
  }

  /**
   * ICPs the currently-ticked services sell to.
   *
   * Computed here from each profile's own `service_codes` rather than from the
   * server's `available_icps`, because the picker has to react while somebody
   * is still choosing — before anything is saved. The server recomputes the
   * same rule and refuses a stray ICP on save, so this is a convenience and
   * not the authority.
   */
  reachableIcps(): IcpProfile[] {
    const codes = new Set(this.chosenServices().map((s) => s.code));
    return this.icpProfiles().filter((p) =>
      p.service_codes.some((c: string) => codes.has(c)),
    );
  }

  toggleService(id: string): void {
    if (this.pickedServices.has(id)) this.pickedServices.delete(id);
    else this.pickedServices.add(id);
    // Drop any ICP the remaining services no longer reach, so the selection
    // cannot describe something the server would refuse.
    const reachable = new Set(this.reachableIcps().map((p) => p.id));
    for (const id of [...this.pickedIcps]) {
      if (!reachable.has(id)) this.pickedIcps.delete(id);
    }
    if (this.enrichService && !this.pickedServices.has(this.enrichService)) {
      this.enrichService = '';
    }
  }

  toggleIcp(id: string): void {
    if (this.pickedIcps.has(id)) this.pickedIcps.delete(id);
    else this.pickedIcps.add(id);
  }

  private loadTargeting(listId: string): void {
    this.config.services().subscribe({
      next: (rows) => this.services.set(rows.filter((s) => s.is_active)),
      error: () => undefined,
    });
    this.config.icpProfiles().subscribe({
      next: (rows) => this.icpProfiles.set(rows),
      error: () => undefined,
    });
    this.api.targeting(listId).subscribe({
      next: (t) => {
        this.pickedServices = new Set(t.service_ids);
        this.pickedIcps = new Set(t.icp_profile_ids);
        this.targetingSet.set(t.service_ids.length > 0);
        this.targetingOpen.set(t.service_ids.length === 0);
      },
      error: () => undefined,
    });
  }

  saveTargeting(): void {
    const listId = this.listId;
    if (!listId) return;
    this.savingTargeting.set(true);
    this.targetingError.set(null);
    this.api
      .setTargeting(listId, {
        service_ids: [...this.pickedServices],
        icp_profile_ids: [...this.pickedIcps],
      })
      .subscribe({
        next: () => {
          this.savingTargeting.set(false);
          this.targetingSet.set(true);
          this.notify.success('Targeting saved — enrichment and research use it from now on.');
        },
        error: (e) => {
          this.savingTargeting.set(false);
          this.targetingError.set(this.detail(e, 'Could not save the targeting.'));
        },
      });
  }

  /** Enrichment, one account per request — see `runResearch` for why. */
  private async enrich(rows: RunItem[]): Promise<void> {
    const service = this.enrichService;
    if (!this.listId || !service) return;
    this.working.set('enrich');
    const t = {
      code: '', checked: 0, verified: 0, risky: 0, notFound: 0, unavailable: 0,
      outOfPersona: 0, unknown: 0, linkedinPeople: 0, linkedinCompanies: 0,
      reconfirmed: 0, savedApollo: 0, apolloNote: '',
    };
    const stop = { reason: '' };
    const summary = () => `${t.verified} verified · ${t.risky} risky · ${t.notFound} not found`;
    const out = await this.batch.run<VerifyReport>({
      verb: 'Enriching',
      describe: (_, r: any) =>
        !r.ran
          ? { kind: 'error', text: r.blocked ?? 'could not run' }
          : { kind: r.unavailable || r.not_found || r.risky ? 'warning' : 'success',
              text: `${r.checked} checked · ${r.verified} verified · ${r.risky} risky · ${r.not_found} not found` },
      items: rows,
      call: (id) => this.api.verifyContacts(this.listId, service, [id], this.enrichContacts()?.[id]),
      onResult: (_, r) => {
        if (!r.ran) {
          stop.reason = r.blocked ?? 'Enrichment could not run.';
          return 'stop';
        }
        t.code = r.service_code ?? t.code;
        t.checked += r.checked;
        t.verified += r.verified;
        t.risky += r.risky;
        t.notFound += r.not_found;
        t.unavailable += r.unavailable;
        t.outOfPersona += r.out_of_persona ?? 0;
        t.unknown += r.unknown_persona ?? 0;
        t.linkedinPeople += (r.contact_linkedin_from_provider ?? 0) + (r.contact_linkedin_from_site ?? 0);
        t.linkedinCompanies += (r.company_linkedin_from_provider ?? 0) + (r.company_linkedin_from_site ?? 0);
        t.reconfirmed += r.reconfirmed_free ?? 0;
        t.savedApollo += r.saved_to_apollo ?? 0;
        if (r.apollo_note) t.apolloNote = r.apollo_note;
        return undefined;
      },
      onError: (_, e) => {
        // 409 carries the reason — no ICP, no personas, no credential. Each
        // needs different work, and it would be the same for every account,
        // so the run stops rather than repeating it.
        const detail = (e as { error?: { detail?: { message?: string } } })?.error?.detail;
        stop.reason = detail?.message ?? this.detail(e, 'Could not enrich this list.');
        return 'stop';
      },
      summary,
    });
    this.working.set(null);
    this.enrichContacts.set(null);
    // `load()`, not `touch()`: the server changed, so the rows have to come back.
    this.load();

    if (stop.reason) {
      this.notify.error('Enrichment stopped.', stop.reason);
      return;
    }
    const lead = out.cancelled ? `Stopped after ${out.completed} of ${rows.length}. ` : '';
    // LinkedIn links are said separately: they are filled for contacts the
    // address search found nothing for, and from the company's own site.
    const linked = [
      t.linkedinPeople ? `${t.linkedinPeople} contact LinkedIn profile${t.linkedinPeople === 1 ? '' : 's'} added` : '',
      t.linkedinCompanies ? `${t.linkedinCompanies} company LinkedIn page${t.linkedinCompanies === 1 ? '' : 's'} added` : '',
      t.reconfirmed ? `${t.reconfirmed} re-confirmed from saved Apollo contacts, no credit` : '',
      t.savedApollo ? `${t.savedApollo} saved to Apollo` : '',
    ].filter(Boolean).join(' · ');
    const text = `${lead}${t.code || 'Enrichment'}: ${t.checked} checked · ${summary()}${linked ? ' · ' + linked : ''}.`;
    const skipped = [
      t.outOfPersona ? `${t.outOfPersona} out of persona` : '',
      t.unknown ? `${t.unknown} with nothing to judge on` : '',
      t.unavailable ? `${t.unavailable} unavailable` : '',
      t.apolloNote,
    ].filter(Boolean).join(' · ');
    if (skipped || out.cancelled) this.notify.warning(text, skipped || null);
    else this.notify.success(text);
  }

  private detail(e: unknown, fallback: string): string {
    const d = (e as { error?: { detail?: unknown } })?.error?.detail;
    return typeof d === 'string' ? d : fallback;
  }

  touch(): void {
    this.revision.update((n) => n + 1);
  }

  clearFilters(): void {
    this.query = '';
    this.industry = '';
    this.research = '';
    this.enrichment = '';
    this.status = '';
    this.minIcp = null;
    this.touch();
  }
  sort = signal<SortState>(NO_SORT);
  loading = signal(true);
  error = signal<string | null>(null);
  importing = signal(false);
  meta = signal<AccountList | null>(null);

  ngOnInit(): void {
    this.listId = this.route.snapshot.paramMap.get('id') ?? '';
    // ?import=1 arrives from "Create and import" and from the upload icon on
    // the index, so a newly made list opens on the step that fills it.
    this.importing.set(this.route.snapshot.queryParamMap.get('import') === '1');
    this.api.list(this.listId).subscribe({
      next: (l) => {
        this.meta.set(l);
        this.activity.where.set(`List · ${l.label}`);
      },
    });
    this.loadTargeting(this.listId);
    this.load();
  }

  onSort(next: SortState): void {
    this.sort.set(next);
    this.load();
  }

  onImported(): void {
    this.importing.set(false);
    this.load();
  }

  /** `partial` is amber rather than green: some query families returned nothing,
   *  and treating that as success is how a coverage gap goes unnoticed. */
  pipelineClass(status: string): string {
    return {
      complete: 'badge-good',
      partial: 'badge-warn',
      failed: 'badge-critical',
      running: 'badge-accent',
      not_started: 'badge-neutral',
      skipped: 'badge-neutral',
    }[status] ?? 'badge-neutral';
  }

  private load(): void {
    // The scope picker offers every list; arriving here preselects this one.
    this.api.lists(NO_SORT).subscribe({ next: (l) => this.allLists.set(l) });
    this.loadContacts();
    this.loadFindings();
    this.loading.set(true);
    this.api.listAccounts(this.listId, this.sort()).subscribe({
      next: (rows) => {
        this.accounts.set(rows);
        this.loading.set(false);
        this.error.set(null);
      },
      error: (err) => {
        this.loading.set(false);
        const bad = asUnsortableField(err);
        this.error.set(
          bad
            ? `Cannot sort by "${bad.field}". Allowed: ${bad.allowed.join(', ')}`
            : 'Could not load accounts.',
        );
      },
    });
  }
}
