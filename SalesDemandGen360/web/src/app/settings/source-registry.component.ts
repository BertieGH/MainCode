import { CommonModule } from '@angular/common';
import {
  Component, EventEmitter, Input, Output, inject, signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ConfigService, ResearchSource, SignalType, SourceTrial } from '../core/config.service';
import { IconComponent } from '../shared/icon.component';
import { apiError } from '../shared/api-error';
import { ResearchModeService } from './../shared/research-mode.service';

/**
 * The source registry: where research looks, and how often it looks again.
 *
 * It lived on a screen called "Sources & weights", beside two multiplier
 * tables that answer a different question — how much what is found is worth.
 * Sources belong next to the signal types that claim them, because the two
 * are edited together: a type names the sources its fact usually lives in,
 * and a source nothing claims is one nobody reads.
 *
 * Sources used to be a closed set in code, because a source the agents do not
 * run is indistinguishable from one that ran and found nothing. They are a
 * registry now — the key is still checked before a signal type may claim it,
 * the registry is just something a person can add to.
 *
 * What goes beside each one is the part that stops the list rotting: how often
 * it was read lately and what it produced. A registry only ever grows, and
 * without those two numbers on the same screen a source added in March is
 * still costing a read per account in December and nobody knows.
 */
@Component({
  selector: 'app-source-registry',
  standalone: true,
  imports: [CommonModule, FormsModule, IconComponent],
  template: `
    <div class="card" style="margin-bottom:22px;">
      <h3 style="font-size:.98rem;margin-bottom:2px;">Reuse window</h3>
      <p class="row-sub" style="max-width:72ch;margin-bottom:10px;">
        Research younger than this is reused rather than paid for again. <em>Run research</em>
        skips any family already answered for an account inside the window — so a second list
        working the same company pays only for what is new. <em>Rerun research</em> on an account
        list ignores it. A family that failed is never reused. Saving writes a new version.
      </p>
      <!-- Beside the reuse window because they are the same kind of fact —
           how research spends — and saved together because the endpoint
           writes a whole new version rather than patching one. -->
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
        <label style="display:flex;align-items:center;gap:8px;">
          <span class="row-sub">Research depth by default</span>
          <select class="field" style="width:130px;" [(ngModel)]="defaultTier"
                  aria-label="Default research depth for the installation">
            <option value="light">Light</option>
            <option value="standard">Standard</option>
            <option value="deep">Deep</option>
          </select>
        </label>
        <label style="display:flex;align-items:center;gap:8px;">
          <span class="row-sub">Reuse results younger than</span>
          <input class="field" type="number" min="1" max="365" step="1" style="width:90px;"
                 [(ngModel)]="reuseDays" aria-label="Reuse window in days">
          <span class="row-sub">days</span>
        </label>
        <button class="btn btn-primary" (click)="saveReuse()" [class.busy]="savingReuse()"
                [disabled]="savingReuse() || !reuseValid()
                            || (reuseDays === reuseSaved && defaultTier === tierSaved)">
          <app-icon *ngIf="!savingReuse()" name="check" [size]="13" />
          {{ savingReuse() ? 'Saving…' : 'Save' }}
        </button>
        <span class="row-sub" *ngIf="!reuseValid()" style="color:var(--critical);">
          Between 1 and 365 days.
        </span>
        <span class="row-sub"
              *ngIf="reuseValid() && reuseDays === reuseSaved && defaultTier === tierSaved">
          {{ reuseVersion ? 'Version ' + reuseVersion : 'Default' }} ·
          {{ reuseSaved }} days · {{ tierSaved }}.
          A list can still say otherwise, and any run can.
        </span>
      </div>
    </div>

    <!-- industry multipliers: rows are the ICP's industries -->

    <!-- the source registry -->
    <div class="sec-head" style="margin:28px 0 4px;">
      <h3 style="font-size:.98rem;">Sources</h3>
      <button class="btn" (click)="adding.set(!adding())">
        {{ adding() ? 'Cancel' : '+ Add a source' }}
      </button>
    </div>
    <p class="row-sub" style="margin-bottom:12px;max-width:76ch;">
      Where research looks. A signal type names the ones its fact usually lives in; an ICP decides
      which actually run for its lists. Everything a source returns is read against every signal
      type, so naming one here narrows what gets <em>opened</em>, never what gets found in it.
    </p>

    <!-- adding one: a search, always. A feed reader or a paid waterfall needs
         code behind it, and a row claiming one with nothing behind it is the
         silent coverage gap this registry exists to prevent. -->
    <div class="card" *ngIf="adding()" style="margin-bottom:16px;">
      <div class="form-grid">
        <label>Key
          <input class="field" [(ngModel)]="draft.key" placeholder="trade_press">
          <span class="row-sub">Lowercase and underscores. Permanent — coverage is filed under it.</span>
        </label>
        <label>Name
          <input class="field" [(ngModel)]="draft.label" placeholder="Trade press">
        </label>
        <label style="grid-column:1/-1;">What lives there
          <textarea class="field" rows="2" [(ngModel)]="draft.description"
                    placeholder="Sector publications, their newsletters and award lists."></textarea>
          <span class="row-sub">
            This is the brief a search runs. Describe the <em>place</em>, not a conclusion — what
            to conclude is every signal type's job, on everything this returns.
          </span>
        </label>
        <label>Reads about
          <select class="field" [(ngModel)]="draft.scope">
            <option value="company">companies</option>
            <option value="contact">people</option>
            <option value="both">both</option>
          </select>
        </label>
        <label>Re-read after
          <input class="field" type="number" min="1" max="3650" [(ngModel)]="draft.reuse_days"
                 placeholder="blank = the window above">
          <span class="row-sub">News is worth a week, filings a quarter.</span>
        </label>
        <label style="grid-column:1/-1;display:flex;align-items:center;gap:8px;flex-direction:row;">
          <input type="checkbox" [(ngModel)]="draft.support_only">
          <span class="row-sub">
            Can corroborate a signal but never create one on its own — like reviews, where a single
            complaint is noise and a repeated theme is evidence.
          </span>
        </label>
      </div>
      <!-- Try it before you store it. A source costs a read per account from
           the moment it is saved, and the old way of finding out whether it
           earns that was 26 attempts across the book. -->
      <div style="border-top:1px solid var(--line);margin-top:14px;padding-top:12px;">
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
          <strong style="font-size:.9rem;">Try it first</strong>
          <span class="row-sub" style="flex:1;min-width:30ch;">
            Runs the real search against the accounts you pick and shows what came back.
            Nothing is stored — but the model calls are real, so keep the sample small.
          </span>
        </div>

        <label style="display:block;margin-top:10px;">Try against
          <select class="field" multiple size="5" [(ngModel)]="trialAccountIds"
                  style="min-height:auto;">
            <option *ngFor="let a of trialAccounts()" [value]="a.id">
              {{ a.name }}{{ a.domain ? ' — ' + a.domain : '' }}
            </option>
          </select>
          <span class="row-sub">
            Pick two or three, and pick <em>different kinds</em> — a source that works for a
            technology company often returns nothing for a small broker, and that is the
            thing worth knowing before you save it.
          </span>
        </label>

        <!-- A/B. Both wordings run against the same accounts in the same call:
             two separate runs are not a comparison, because the same request
             can return a sound answer once and nothing the next time. -->
        <label style="display:block;margin-top:10px;">
          <span style="display:flex;align-items:center;gap:8px;">
            <input type="checkbox" [(ngModel)]="abTest">
            <span>Compare a second wording (A/B)</span>
          </span>
          <textarea class="field" rows="2" *ngIf="abTest" [(ngModel)]="descriptionB"
                    placeholder="The same place, described differently."></textarea>
          <span class="row-sub" *ngIf="abTest">
            Both run against the same accounts on the same day, so a difference is down to the
            words rather than to the weather. Halves the accounts, to keep the cost the same.
          </span>
        </label>

        <div style="display:flex;gap:10px;align-items:center;margin-top:10px;flex-wrap:wrap;">
          <button class="btn" (click)="tryIt()"
                  [disabled]="trying() || !draftValid() || !trialAccountIds.length
                              || (abTest && !descriptionB.trim())">
            {{ trying() ? 'Running…' : (abTest ? 'Run A/B' : 'Try it') }}
          </button>
          <button class="btn" *ngIf="trial()?.prompt" (click)="showLogic.set(!showLogic())">
            {{ showLogic() ? 'Hide the search logic' : 'Show the search logic' }}
          </button>
          <span class="row-sub" *ngIf="!trialAccountIds.length">Pick at least one account.</span>
          <span class="row-sub" *ngIf="trialError()" style="color:var(--danger);">
            {{ trialError() }}
          </span>
        </div>

        <!-- The logic, exactly as sent. Built by the same function the real call
             uses, so what is shown here cannot drift from what runs. -->
        <div class="card" *ngIf="showLogic() && trial() as t" style="margin-top:10px;">
          <p class="row-sub" style="margin:0 0 8px;">
            This is what was sent, verbatim — copy it into any model to argue with it. The
            instructions are the <strong>company_research</strong> template, editable under
            Settings → Prompts; the brief above is the <code>source.read_for</code> line in the
            payload.
          </p>
          <strong style="font-size:.85rem;">Instructions</strong>
          <pre class="pre-wrap">{{ t.prompt }}</pre>
          <strong style="font-size:.85rem;">Payload for {{ firstTrialName() }}</strong>
          <pre class="pre-wrap">{{ t.payload | json }}</pre>
        </div>

        <div class="card" *ngIf="trial() as t" style="margin-top:12px;background:var(--bg-subtle);">
          <div style="display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;">
            <strong style="font-size:.9rem;"
                    [style.color]="t.found ? 'var(--ok)' : 'var(--danger)'">
              {{ t.found ? 'Worth storing' : 'Do not store this yet' }}
            </strong>
            <span class="row-sub">{{ t.verdict }}</span>
          </div>
          <p class="row-sub" style="margin:6px 0 10px;">
            {{ t.input_tokens + t.output_tokens }} tokens across {{ t.accounts }} account(s).
          </p>

          <div *ngFor="let a of t.trials" style="margin-bottom:10px;">
            <div style="font-size:.88rem;font-weight:600;">
              <span *ngIf="t.variant_b" class="pill">{{ a.variant }}</span>
              {{ a.account_name }}
              <span class="row-sub" style="font-weight:400;">
                — {{ a.error ? 'failed' : a.found.length + ' found' }} · {{ a.duration_ms }}ms
              </span>
            </div>
            <p class="row-sub" *ngIf="a.error" style="color:var(--danger);">{{ a.error }}</p>
            <!-- What this account could not be searched by. An account with no
                 website finds nothing for every source, so saying so here stops
                 somebody rewriting a brief that was never the problem. -->
            <p class="row-sub" *ngIf="a.missing.length" style="margin:2px 0 0;">
              this account has no {{ a.missing.join(', no ') }} — a source needing one of those
              would find nothing here whatever the brief says
            </p>
            <ul style="margin:4px 0 0;padding-left:18px;">
              <li *ngFor="let f of a.found" class="row-sub" style="margin-bottom:3px;">
                <span style="font-variant-numeric:tabular-nums;">
                  {{ a.found.length ? (f.observed_at || 'undated') : '' }}
                </span>
                — {{ f.title || f.excerpt }}
                <a *ngIf="f.source_url" [href]="f.source_url" target="_blank"
                   rel="noopener noreferrer">open</a>
              </li>
            </ul>
            <!-- What it searched and could not establish. "We looked and there
                 is nothing" is a fact about the account; the same answer at
                 every account is a fact about the source. -->
            <p class="row-sub" *ngIf="!a.found.length && a.not_found.length"
               style="margin:2px 0 0;">
              looked for: {{ a.not_found.join('; ') }}
            </p>
          </div>
        </div>
      </div>

      <div style="display:flex;gap:10px;align-items:center;margin-top:12px;">
        <button class="btn btn-primary" (click)="addSource()"
                [disabled]="savingSource() || !draftValid()">
          {{ savingSource() ? 'Adding…' : 'Add source' }}
        </button>
        <span class="row-sub" *ngIf="!draftValid()">A key, a name and a brief are needed.</span>
        <span class="row-sub" *ngIf="trial() && !trial()!.found">
          Trialled and found nothing — change the brief and try again rather than storing it.
        </span>
      </div>
    </div>

    <div class="table-wrap">
      <table class="data">
        <thead>
          <tr>
            <th>Source</th><th>Reads</th>
            <th class="tier-col"
                title="How much an account must be worth before this is bought for it">
              Bought at
            </th>
            <th class="brief-col">What lives there</th>
            <th class="claim-col">Claimed by</th><th>Lately</th>
            <th class="actcol">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let f of sources()" [class.retired-row]="f.status !== 'active'">
            <td>
              <code>{{ f.key }}</code>
              <div class="row-sub" *ngIf="editing() !== f.key">{{ f.label }}</div>
              <input *ngIf="editing() === f.key" class="field cell-input" [(ngModel)]="edit.label"
                     [attr.aria-label]="'Name for ' + f.key">
              <div class="row-sub" *ngIf="f.builtin" title="Shipped with the product">built in</div>
              <div class="row-sub" *ngIf="f.status !== 'active'" style="color:var(--warn);">
                {{ f.status }}
              </div>
              <!-- Beside the status, not in a tooltip: this is read by someone
                   about to turn the source back on, and the reason is the
                   whole input to that decision. -->
              <details class="why" *ngIf="f.status !== 'active' && f.status_reason">
                <summary class="row-sub">why</summary>
                <p class="row-sub">{{ f.status_reason }}</p>
              </details>
            </td>
            <td>
              <span class="badge" *ngFor="let s of f.scopes"
                    [ngClass]="s === 'company' ? 'badge-accent' : 'badge-warn'"
                    style="margin-right:4px;">{{ s }}</span>
              <div class="row-sub" *ngIf="f.kind !== 'search'">{{ kindWord(f.kind) }}</div>
            </td>
            <!-- Saved on change rather than behind the row's edit mode: a
                 tier is the one field somebody comes here to change after
                 reading the two columns to its right, and making them open an
                 editor first puts the decision a click away from its own
                 evidence. -->
            <td class="tier-col">
              <select class="field tier-pick" [ngModel]="f.tier"
                      (ngModelChange)="setTier(f, $event)"
                      [disabled]="f.kind !== 'search' && f.kind !== 'fetch'"
                      [attr.aria-label]="'Tier for ' + f.key">
                <option value="light">Light</option>
                <option value="standard">Standard</option>
                <option value="deep">Deep</option>
              </select>
              <!-- A free source costs no search, so its tier decides only
                   whether a cheap run still reads it — never what it saves.
                   Said here so nobody demotes one expecting a saving. -->
              <div class="row-sub" *ngIf="f.kind === 'fetch'">costs no search</div>
            </td>
            <td class="row-sub brief">
              <ng-container *ngIf="editing() !== f.key">{{ f.description }}</ng-container>
              <textarea *ngIf="editing() === f.key" class="field cell-input" rows="2"
                        [(ngModel)]="edit.description"
                        [attr.aria-label]="'What lives in ' + f.key"></textarea>
              <div *ngIf="f.support_only" style="color:var(--warn);margin-top:3px;">
                Supports a signal but never creates one on its own.
              </div>
            </td>
            <td class="row-sub mono claim-col">{{ feedsFor(f.key) || '— nothing yet' }}</td>
            <td class="row-sub">
              <ng-container *ngIf="f.attempts">
                {{ f.attempts }} read{{ f.attempts === 1 ? '' : 's' }} ·
                {{ f.evidence }} passage{{ f.evidence === 1 ? '' : 's' }}
                <div *ngIf="f.dead_weight" style="color:var(--warn);">
                  nothing found in any of them
                </div>
              </ng-container>
              <span *ngIf="!f.attempts">not read yet</span>
            </td>
            <td class="actcol">
              <ng-container *ngIf="editing() !== f.key">
                <button class="act-btn" (click)="startEdit(f)" title="Edit"
                        [attr.aria-label]="'Edit ' + f.key">
                  <app-icon name="edit" [size]="15" />
                </button>
                <button class="act-btn" *ngIf="f.status === 'active'" (click)="setStatus(f, 'paused')"
                        title="Stop reading this, reversibly"
                        [attr.aria-label]="'Pause ' + f.key">
                  <app-icon name="pause" [size]="15" />
                </button>
                <button class="act-btn" *ngIf="f.status === 'paused'" (click)="setStatus(f, 'active')"
                        title="Read it again" [attr.aria-label]="'Resume ' + f.key">
                  <app-icon name="play" [size]="15" />
                </button>
              </ng-container>
              <ng-container *ngIf="editing() === f.key">
                <button class="act-btn" (click)="saveEdit(f)" title="Save"
                        [attr.aria-label]="'Save ' + f.key">
                  <app-icon name="check" [size]="15" />
                </button>
                <button class="act-btn" (click)="editing.set(null)" title="Cancel"
                        [attr.aria-label]="'Cancel editing ' + f.key">
                  <app-icon name="x" [size]="15" />
                </button>
              </ng-container>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="row-sub" style="margin-top:10px;max-width:76ch;">
      A source is retired rather than deleted: its key is written into every coverage row that
      records reading it, and a report that cannot resolve one prints a bare key where a name
      should be.
    </p>
  `,
  styles: [
    `
      .sec-head { display: flex; justify-content: space-between; align-items: center;
                  gap: 16px; margin-bottom: 4px; }
      /* The search logic, shown verbatim so it can be copied into a model and
         argued with. Scrolls rather than stretching the page: the research
         template runs to a few hundred lines. */
      .pre-wrap { white-space: pre-wrap; word-break: break-word; margin: 4px 0 12px;
                  font-size: .78rem; font-family: 'IBM Plex Mono', monospace;
                  max-height: 280px; overflow: auto; padding: 8px;
                  background: var(--bg-subtle); border: 1px solid var(--line);
                  border-radius: 4px; }
      .pill { display: inline-block; min-width: 1.4em; text-align: center;
              padding: 0 5px; margin-right: 4px; border-radius: 3px;
              background: var(--bg-subtle); border: 1px solid var(--line);
              font-family: 'IBM Plex Mono', monospace; font-size: .72rem; }
      .cell { width: 74px; padding: 4px 7px; font-size: .8rem;
              font-family: 'IBM Plex Mono', monospace; text-align: right; }
      .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
      .form-grid label { display: flex; flex-direction: column; gap: 4px; font-size: .84rem; }
      /* The brief is the column people read; the claim is a list of keys
         they scan. Before this the claim took 751px of a 1200px table and
         squeezed the brief into 217, because a run of comma-separated keys
         has no wrap opportunity a browser will take by itself. */
      td.brief, th.brief-col { white-space: normal; width: 42%; min-width: 260px; }
      .tier-col { width: 118px; }
      .tier-pick { width: 100%; font-size: 0.78rem; padding: 4px 6px; }
      td.claim-col, th.claim-col { white-space: normal; width: 22%;
                                   overflow-wrap: anywhere; }
      .retired-row { opacity: .6; }
      .why > summary { cursor: pointer; color: var(--accent); }
      .why p { margin: 4px 0 0; max-width: 48ch; }
      .cell-input { width: 100%; padding: 4px 7px; font-size: .8rem; }
    `,
  ],
})
export class SourceRegistryComponent {
  private api = inject(ConfigService);
  // Every screen shows the inherited depth somewhere, so a save here makes
  // all of them stale at once.
  private mode = inject(ResearchModeService);

  /**
   * Both lists come from the parent, which already holds them.
   *
   * Fetching them here as well meant two requests for the same rows on every
   * load of a screen that renders them once — and the parent's own spec
   * caught it, because `expectOne` found two. A child that re-reads what it
   * was embedded beside is a duplicate, not an encapsulation.
   */
  @Input({ required: true }) sources = signal<ResearchSource[]>([]);
  @Input({ required: true }) types = signal<SignalType[]>([]);
  /** Something was added, edited or retired — the parent owns the reload. */
  @Output() changed = new EventEmitter<void>();
  /** Offered to the Try button. The parent fetches them. */
  @Input() trialAccounts = signal<{ id: string; name: string; domain: string | null }[]>([]);
  /** The stored reuse window, so the field opens on the saved value. */
  @Input() set reuseWindow(value: number) {
    this.reuseDays = this.reuseSaved = value;
  }
  @Input() reuseVersion = 0;
  @Input() set appTier(value: 'light' | 'standard' | 'deep' | undefined) {
    if (value) this.defaultTier = this.tierSaved = value;
  }

  /** The reuse window as edited, and as last saved. */
  reuseDays = 30;
  /** The installation's default depth, and what is saved for it. */
  defaultTier: 'light' | 'standard' | 'deep' = 'standard';
  tierSaved: 'light' | 'standard' | 'deep' = 'standard';
  reuseSaved = 30;
  savingReuse = signal(false);

  adding = signal(false);
  savingSource = signal(false);
  editing = signal<string | null>(null);
  edit = { label: '', description: '' };
  draft = {
    key: '',
    label: '',
    description: '',
    scope: 'company' as 'company' | 'contact' | 'both',
    reuse_days: null as number | null,
    support_only: false,
  };

  trialAccountIds: string[] = [];
  trying = signal(false);
  trial = signal<SourceTrial | null>(null);
  trialError = signal<string | null>(null);
  showLogic = signal(false);
  abTest = false;
  descriptionB = '';

  loading = signal(true);
  savingSourceError = signal<string | null>(null);
  error = signal<string | null>(null);

  /** Whose payload the logic panel is showing — it is captured once, from the
   *  first account tried, because the instructions are identical for all of
   *  them and only the account block differs. */
  firstTrialName(): string {
    return this.trial()?.trials[0]?.account_name ?? 'this account';
  }
  draftValid(): boolean {
    return (
      /^[a-z][a-z0-9_]*$/.test(this.draft.key.trim()) &&
      this.draft.label.trim().length > 0 &&
      this.draft.description.trim().length > 0
    );
  }

  /** Why a source has no coverage of its own, in words rather than a code. */
  kindWord(kind: string): string {
    if (kind === 'fetch') return 'read directly, no search';
    if (kind === 'provider') return 'a metered provider — never auto-run';
    if (kind === 'manual') return 'entered by a rep';
    return '';
  }

  addSource(): void {
    this.savingSource.set(true);
    const scopes =
      this.draft.scope === 'both' ? ['company', 'contact'] : [this.draft.scope];
    this.api
      .createResearchSource({
        key: this.draft.key.trim(),
        label: this.draft.label.trim(),
        description: this.draft.description.trim(),
        scopes,
        support_only: this.draft.support_only,
        reuse_days: this.draft.reuse_days ? Number(this.draft.reuse_days) : null,
      })
      .subscribe({
        next: () => {
          this.savingSource.set(false);
          this.adding.set(false);
          this.draft = {
            key: '', label: '', description: '', scope: 'company',
            reuse_days: null, support_only: false,
          };
          this.changed.emit();
        },
        error: (err) => {
          this.savingSource.set(false);
          this.error.set(apiError(err, 'Could not add that source.'));
        },
      });
  }

  startEdit(row: ResearchSource): void {
    this.editing.set(row.key);
    this.edit = { label: row.label, description: row.description };
  }

  saveEdit(row: ResearchSource): void {
    const changes: { label?: string; description?: string } = {};
    if (this.edit.label.trim() !== row.label) changes.label = this.edit.label.trim();
    if (this.edit.description.trim() !== row.description) {
      // The brief is what a search is told to read for, so editing it changes
      // what every later read of this source returns.
      changes.description = this.edit.description.trim();
    }
    if (!Object.keys(changes).length) {
      this.editing.set(null);
      return;
    }
    this.api.updateResearchSource(row.key, changes).subscribe({
      next: () => {
        this.editing.set(null);
        this.changed.emit();
      },
      error: (err) => {
        this.editing.set(null);
        this.error.set(apiError(err, 'Could not save that source.'));
      },
    });
  }

  /**
   * Pause or resume. Never a delete: the key is written into every coverage
   * row that recorded reading it.
   */
  /**
   * Saved on change, not behind the row editor.
   *
   * A tier is the one field somebody comes here to change after reading the
   * two columns beside it — what the source is claimed by, and what it has
   * actually produced. Putting it behind an edit button would move the
   * decision one click away from its own evidence.
   */
  setTier(row: ResearchSource, tier: string): void {
    if (tier === row.tier) return;
    this.api.updateResearchSource(row.key, { tier }).subscribe({
      next: () => this.changed.emit(),
      error: (err) => {
        this.error.set(apiError(err, 'Could not change that source.'));
        // Reload anyway, or the select keeps showing a tier the server
        // refused — the screen would disagree with what research will buy.
        this.changed.emit();
      },
    });
  }

  setStatus(row: ResearchSource, status: string): void {
    this.api.updateResearchSource(row.key, { status }).subscribe({
      next: () => this.changed.emit(),
      error: (err) => this.error.set(apiError(err, 'Could not change that source.')),
    });
  }

  feedsFor(family: string): string {
    return this.types()
      .filter((t) => t.status === 'active' && t.produced_by.includes(family))
      .map((t) => t.key)
      .join(', ');
  }

  /** The scopes the draft claims, in the shape the API wants. */
  private draftScopes(): ('company' | 'contact')[] {
    return this.draft.scope === 'both' ? ['company', 'contact'] : [this.draft.scope];
  }

  tryIt(): void {
    this.trying.set(true);
    this.trialError.set(null);
    this.trial.set(null);
    this.api
      .tryResearchSource({
        key: this.draft.key.trim(),
        label: this.draft.label.trim(),
        description: this.draft.description.trim(),
        scopes: this.draftScopes(),
        // Only a search is creatable on this screen, so only a search is
        // trialled. A fetch or a provider needs code behind it.
        kind: 'search',
        account_ids: this.trialAccountIds,
        description_b: this.abTest && this.descriptionB.trim() ? this.descriptionB.trim() : null,
      })
      .subscribe({
        next: (t) => {
          this.trial.set(t);
          this.trying.set(false);
        },
        error: (e) => {
          this.trialError.set(apiError(e, 'Could not run the trial.'));
          this.trying.set(false);
        },
      });
  }

  reuseValid(): boolean {
    const n = Number(this.reuseDays);
    return Number.isInteger(n) && n >= 1 && n <= 365;
  }

  saveReuse(): void {
    this.savingReuse.set(true);
    this.api.saveResearchSettings(Number(this.reuseDays), this.defaultTier).subscribe({
      next: (s) => {
        this.savingReuse.set(false);
        this.reuseDays = this.reuseSaved = s.freshness_days;
        this.defaultTier = this.tierSaved = s.default_tier;
        this.reuseVersion = s.version;
        // Every screen shows the inherited depth, so they are all stale
        // now. Told rather than re-fetched: the service deliberately makes
        // no request of its own, and the response is already in hand.
        this.mode.setAppDefault(s.default_tier);
      },
      error: (err) => {
        this.savingReuse.set(false);
        this.error.set(apiError(err, 'Could not save the reuse window.'));
      },
    });
  }

  /**
   * **No I/O here, deliberately.** Everything this renders comes down as an
   * input from the screen that embeds it.
   *
   * It used to load its own sources, types, accounts and settings. That meant
   * two requests for the same rows on one page — and, worse, every spec of
   * every parent suddenly had to know about requests the child made, which
   * broke sixty-eight of them at once. A child embedded in a screen that
   * already holds the data should render it, not re-read it. Writes still
   * happen here; they are the user's actions, not the page loading.
   */
}
