import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ConfigService, ResearchSource, SignalType } from '../core/config.service';
import { ListsService } from '../core/lists.service';
import { IconComponent } from '../shared/icon.component';
import { SourceRegistryComponent } from './source-registry.component';
import { forkJoin } from 'rxjs';

import { apiError } from '../shared/api-error';

type Scope = 'company' | 'contact';

/**
 * Whether two source lists say the same thing.
 *
 * Set comparison, not element-wise: `produced_by` is a set of keys and the
 * order it arrives in is the registry's, not a choice. Comparing by index
 * would call every reordering a change and patch rows nobody edited.
 */
function sameKeys(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const held = new Set(b);
  return a.every((k) => held.has(k));
}

/**
 * Signal type registry, split by scope.
 *
 * Two registries rather than one table with a scope column, because they answer
 * different questions: a company signal explains *why now*, a contact signal
 * explains *why you*. They are also tuned independently.
 *
 * Each has its own Add button that fixes the scope, so a contact type cannot be
 * created and accidentally filed as a company one — the mistake is not
 * available rather than merely discouraged.
 */
@Component({
  selector: 'app-signal-types',
  standalone: true,
  imports: [CommonModule, FormsModule, IconComponent, SourceRegistryComponent],
  template: `
    <!-- Reference material, not a per-visit read: folded behind the icon so the
         registry itself is the first thing on screen. -->
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
      <h2 style="font-size:1.15rem;">Signal types</h2>
      <button class="act-btn" (click)="help.set(!help())"
              [attr.aria-expanded]="help()"
              aria-controls="signal-types-help"
              [attr.aria-label]="help() ? 'Hide help about signal types' : 'About signal types'"
              [title]="help() ? 'Hide help' : 'What this screen is for, and how weight works'">
        <app-icon name="info" [size]="15" />
      </button>
    </div>
    <p id="signal-types-help" class="row-sub" *ngIf="help()"
       style="margin-bottom:22px;max-width:70ch;">
      What the system is allowed to conclude, and how heavily each conclusion counts.
      The extraction prompt is built from the active rows below, so adding one changes
      behaviour without a deploy. Every signal carries dated, sourced evidence regardless of scope.
      <br><strong>Weight is a multiplier, not a share.</strong> ×1.00 is the baseline; ×1.50 makes a
      signal count half again as much. They are independent and do not need to add up to anything —
      adding a new type does not dilute the existing ones. The six qualification
      <em>dimensions</em> are the opposite: those are a distribution and must total 100.
    </p>
    <div *ngIf="!help()" style="margin-bottom:18px;"></div>

    <div *ngIf="error()" class="card" style="border-color:var(--critical);margin-bottom:18px;">
      <strong style="color:var(--critical);">{{ error() }}</strong>
    </div>

    <div class="plan-line">
      <span class="row-sub">
        <strong>{{ sourcesNamed() }}</strong> source{{ sourcesNamed() === 1 ? '' : 's' }} named
        between {{ activeTypes() }} active type{{ activeTypes() === 1 ? '' : 's' }}
        <span *ngIf="searchCount()"> · {{ searchCount() }} extra
          search{{ searchCount() === 1 ? '' : 'es' }}</span>
        <span *ngIf="neverRuns()"> · {{ neverRuns() }} untargeted</span>
        — what actually runs is set per ICP.
      </span>
      <button class="btn" (click)="suggest()" [class.busy]="suggesting()"
              [disabled]="suggesting()"
              title="Ask which types read the same sources and could share one search">
        {{ suggesting() ? 'Asking…' : 'Suggest groupings' }}
      </button>
    </div>

    <!-- Proposals, never applied on their own: a grouping changes what every
         later search asks for. -->
    <div class="card" *ngIf="suggestions() as s" style="margin-bottom:18px;">
      <div class="sec-head" style="margin-bottom:6px;">
        <strong style="font-size:.9rem;">Suggested groupings</strong>
        <button class="act-btn" (click)="suggestions.set(null)" aria-label="Dismiss suggestions"
                title="Dismiss">
          <app-icon name="x" [size]="15" />
        </button>
      </div>
      <p class="row-sub" *ngIf="!s.groups.length" style="margin:0;">
        Nothing worth grouping — each of these reads sources of its own.
      </p>
      <div class="prop" *ngFor="let p of s.groups">
        <div>
          <strong>{{ p.label }}</strong>
          <span class="row-sub"> · {{ p.type_keys.join(' · ') }}</span>
          <div class="row-sub">{{ p.why }}</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;white-space:nowrap;">
          <span class="row-sub">{{ p.type_keys.length }} → 1</span>
          <button class="btn" (click)="applyGroup(p)" [disabled]="applying() === p.label">
            {{ applying() === p.label ? 'Applying…' : 'Apply' }}
          </button>
        </div>
      </div>
      <p class="row-sub" *ngIf="s.ungrouped.length" style="margin:10px 0 0;">
        Left alone: {{ s.ungrouped.join(', ') }}
      </p>
    </div>

    <ng-container *ngFor="let g of groups">
      <div class="sec-head">
        <div style="display:flex;align-items:baseline;gap:10px;">
          <span class="badge" [ngClass]="g.scope === 'company' ? 'badge-accent' : 'badge-warn'">
            {{ g.title }}
          </span>
          <h3 style="font-size:.98rem;">{{ g.heading }}</h3>
        </div>
        <button class="btn btn-primary" style="padding:6px 12px;font-size:.78rem;"
                (click)="startAdd(g.scope)"
                [attr.aria-label]="'Add ' + g.scope + ' signal type'"
                [title]="'Add a new ' + g.scope + ' signal type'">
          <app-icon name="plus" [size]="13" />Add Signal
        </button>
      </div>
      <p class="row-sub" style="margin-bottom:12px;">{{ g.blurb }}</p>

      <!-- scope is fixed by which button opened this form -->
      <div class="card" *ngIf="adding() === g.scope" style="margin-bottom:14px;">
        <div class="form-grid">
          <label>Key
            <input class="field" [(ngModel)]="draft.key" placeholder="budget_cycle">
            <span class="row-sub">Lowercase snake_case. Goes into the output schema and never changes.</span>
          </label>
          <label>Label
            <input class="field" [(ngModel)]="draft.label" placeholder="Budget cycle disclosed">
          </label>
          <label style="grid-column:1/-1;">Description
            <textarea class="field" rows="2" [(ngModel)]="draft.description"
                      placeholder="A stated or strongly implied budget window."></textarea>
            <span class="row-sub">Goes into the extraction prompt, so write it as an instruction.</span>
          </label>
          <div style="grid-column:1/-1;">
            <div class="sec-head" style="margin-bottom:4px;">
              <strong style="font-size:.84rem;">Found in</strong>
              <button class="btn" (click)="askSources(g.scope)"
                      [class.busy]="asking()" [disabled]="asking() || !draft.label.trim()"
                      title="Ask where this kind of fact usually appears">
                {{ asking() ? 'Asking…' : 'Suggest sources' }}
              </button>
            </div>
            <span class="row-sub" style="display:block;margin-bottom:8px;">
              Where this fact usually appears. Everything a source returns is read against every
              signal type, so this decides what gets <strong>opened</strong>, not what gets found
              in it — two or three is usually right, and naming every source costs a read per
              account and says nothing.
            </span>
            <div class="fam-grid">
              <label class="fam" *ngFor="let f of sourcesFor(g.scope)"
                     [class.fam-on]="draft.produced_by.includes(f.key)"
                     [class.fam-suggested]="suggested().has(f.key)"
                     [title]="f.description">
                <input type="checkbox"
                       [checked]="draft.produced_by.includes(f.key)"
                       (change)="toggleFamily(f.key)">
                <span>
                  {{ f.label }}
                  <!-- Marked, not filtered. Every source stays listed so a rep
                       can pick one the model did not think of, and the mark
                       says which were its idea rather than theirs. -->
                  <em *ngIf="suggested().has(f.key)" class="row-sub"
                      style="display:block;font-style:normal;color:var(--accent);">
                    suggested
                  </em>
                  <em *ngIf="f.support_only" class="row-sub" style="display:block;font-style:normal;">
                    supports only — cannot create a signal alone
                  </em>
                  <!-- Shown rather than hidden. A type may already claim it,
                       and hiding it left the chip on the row with no checkbox
                       to untick. -->
                  <em *ngIf="f.status !== 'active'" class="row-sub"
                      style="display:block;font-style:normal;">
                    {{ f.status }} — can be claimed, but will not run until resumed
                  </em>
                </span>
              </label>
            </div>
            <p class="row-sub" *ngIf="sourcesOutOfScope(g.scope).length" style="margin:6px 0 0;">
              {{ sourcesFor(g.scope).length }} of
              {{ sourcesFor(g.scope).length + sourcesOutOfScope(g.scope).length }} sources —
              {{ sourcesOutOfScope(g.scope).join(', ') }}
              {{ sourcesOutOfScope(g.scope).length === 1 ? 'reads' : 'read' }} the other scope
              and {{ sourcesOutOfScope(g.scope).length === 1 ? 'is' : 'are' }} not offered here.
            </p>
            <p class="row-sub" *ngIf="suggestWhy()" style="margin:8px 0 0;">
              {{ suggestWhy() }}
            </p>
            <p class="row-sub" *ngIf="newSources().length" style="margin:6px 0 0;color:var(--warn);">
              Also suggested, but not in the registry:
              {{ newSources().join(', ') }} — add {{ newSources().length === 1 ? 'it' : 'them' }}
              under <strong>Research</strong> first if you want {{ newSources().length === 1 ? 'it' : 'them' }} read.
            </p>
          </div>
          <label>Default TTL (days)
            <input class="field" type="number" [(ngModel)]="draft.default_ttl_days" min="1">
          </label>
          <label>Weight
            <input class="field" type="number" [(ngModel)]="draft.weight" min="0" max="5" step="0.05">
            <span class="row-sub">Multiplier, not a share. 1.00 = baseline. Need not total anything.</span>
          </label>
          <label>Kind
            <select class="field" [(ngModel)]="draft.kind">
              <option value="event">One-off event — a dated fact</option>
              <option value="theme">Ongoing theme — one live reading</option>
            </select>
            <span class="row-sub">
              An event is kept per occurrence: two funding rounds are two signals. A theme keeps one
              live signal that moves forward when a newer reading arrives — what a company keeps
              publishing about is one theme, not a signal per post.
            </span>
          </label>
          <details style="grid-column:1/-1;">
            <summary class="row-sub" style="cursor:pointer;margin-bottom:8px;">
              A search of its own — only if the sources above would miss it
            </summary>
            <span class="row-sub" style="display:block;margin-bottom:8px;">
              An <strong>extra</strong> search, run alongside the sources rather than instead of
              them. Worth its cost only when a sweep of the ordinary places reliably misses this —
              an unusual phrasing, a filing found only by name. Most types need nothing here,
              because every source that gets read is interpreted against every type anyway.
            </span>
            <label style="display:block;margin-bottom:10px;">What to look for
              <textarea class="field" rows="2" [(ngModel)]="draft.search_instruction"
                        placeholder="Public mention of a budget cycle, planning window or fiscal year end."></textarea>
            </label>
            <label style="display:block;">Runs with
              <input class="field" [(ngModel)]="draft.search_group" list="search-groups"
                     placeholder="blank = its own search">
              <datalist id="search-groups">
                <option *ngFor="let name of groupNames()" [value]="name"></option>
              </datalist>
              <span class="row-sub">
                Types sharing a label share one extra search instead of paying for one each.
              </span>
            </label>
          </details>
          <div style="grid-column:1/-1;display:flex;gap:10px;align-items:center;">
            <button class="btn btn-primary" (click)="save()" [disabled]="!canSave() || saving()">
              <app-icon name="check" [size]="13" />
              {{ saving() ? 'Adding…' : 'Add ' + g.scope + ' type' }}
            </button>
            <button class="btn" (click)="cancel()">Cancel</button>
            <!-- A disabled button with no reason is a dead end. Say what is missing. -->
            <span class="row-sub" [style.color]="blocker() ? 'var(--warn)' : ''">
              <ng-container *ngIf="blocker(); else scopeNote">{{ blocker() }}</ng-container>
              <ng-template #scopeNote>
                Scope is fixed to <strong>{{ g.scope }}</strong> by the button you used.
              </ng-template>
            </span>
          </div>
        </div>
      </div>

      <div class="table-wrap" style="margin-bottom:30px;">
        <table class="data">
          <thead>
            <tr>
              <th>Type</th><th>Found in</th><th>Extra search</th>
              <th title="How long it stays a hook">TTL</th>
              <th title="How long the fact stays worth reading. Research and extraction
                         both refuse anything older. Blank means three times the TTL.">
                Durability
              </th>
              <th>Weight</th><th>Kind</th><th>Status</th><th class="actcol">Actions</th>
            </tr>
          </thead>
          <tbody>
            <!-- The loop wraps both rows: a row and its editor are one unit,
                 and the editor needs the same row object. -->
            <ng-container *ngFor="let t of byScope(g.scope)">
            <tr [style.opacity]="t.status === 'deprecated' ? 0.55 : 1">
              <td>
                <!-- The key is in the output schema and in every stored
                     signal's signal_type column; the server has no route to
                     change it. Shown, never offered as a field. -->
                <code [title]="editing() === t.key ? 'The key cannot change — it is in the output schema and in every signal already stored' : ''">{{ t.key }}</code>
                <div class="row-sub" *ngIf="editing() !== t.key">{{ t.label }}</div>
                <input *ngIf="editing() === t.key" class="field cell-input wide"
                       [(ngModel)]="edit.label" placeholder="label"
                       [attr.aria-label]="'Label for ' + t.key">
              </td>
              <td class="row-sub looks">
                <!-- While editing, the badges track the checkboxes below, so
                     ticking a source shows what the row will say. -->
                <span class="badge badge-neutral"
                      *ngFor="let k of (editing() === t.key ? edit.produced_by : t.produced_by)"
                      style="margin-right:4px;" [title]="briefFor(k)">{{ k }}</span>
                <span *ngIf="!(editing() === t.key ? edit.produced_by : t.produced_by).length"
                      title="Nothing targets it, so it is found only when some other sweep happens to turn it up">
                  untargeted
                </span>
              </td>
              <td class="row-sub looks">
                <ng-container *ngIf="editing() !== t.key">
                  <span *ngIf="t.search_instruction">
                    {{ t.search_instruction }}
                    <span class="badge badge-accent" *ngIf="t.search_group"
                          [title]="'Shares this search with every type in the group'">
                      with {{ t.search_group }}
                    </span>
                  </span>
                  <span *ngIf="!t.search_instruction">—</span>
                </ng-container>
                <ng-container *ngIf="editing() === t.key">
                  <textarea class="field cell-input" rows="2"
                            [(ngModel)]="edit.search_instruction"
                            [attr.aria-label]="'Extra search for ' + t.key"></textarea>
                  <input class="field cell-input" [(ngModel)]="edit.search_group"
                         list="search-groups" placeholder="runs with…"
                         [attr.aria-label]="'Runs with, ' + t.key">
                </ng-container>
              </td>
              <td class="mono" data-col="ttl">
                <ng-container *ngIf="editing() !== t.key">{{ t.default_ttl_days }}d</ng-container>
                <input *ngIf="editing() === t.key" class="field cell-input" type="number"
                       min="1" max="3650" [(ngModel)]="edit.default_ttl_days"
                       [attr.aria-label]="'TTL days for ' + t.key">
              </td>
              <td class="mono" data-col="durability">
                <!-- The number only. A "×3" marker beside it read as a
                     multiplier to apply — 900d ×3 as 2700 days — when it meant
                     the 900 was already 300×3. The derivation belongs in the
                     tooltip, not next to the figure it would be mistaken for. -->
                <ng-container *ngIf="editing() !== t.key">
                  <span [title]="durabilityWhy(t)">{{ t.durability_effective_days }}d</span>
                </ng-container>
                <input *ngIf="editing() === t.key" class="field cell-input" type="number"
                       min="0" max="7300" [(ngModel)]="edit.durability_days"
                       [attr.placeholder]="(t.default_ttl_days * 3) + ' (default)'"
                       [attr.aria-label]="'Durability days for ' + t.key">
              </td>
              <td class="mono" data-col="weight">
                <ng-container *ngIf="editing() !== t.key">×{{ t.weight | number: '1.2-2' }}</ng-container>
                <input *ngIf="editing() === t.key" class="field cell-input" type="number"
                       min="0" max="5" step="0.05" [(ngModel)]="edit.weight"
                       [attr.aria-label]="'Weight for ' + t.key">
              </td>
              <td class="row-sub">
                <ng-container *ngIf="editing() !== t.key">{{ t.kind === 'theme' ? 'theme' : 'event' }}</ng-container>
                <select *ngIf="editing() === t.key" class="field cell-input" [(ngModel)]="edit.kind"
                        [attr.aria-label]="'Kind for ' + t.key">
                  <option value="event">event</option>
                  <option value="theme">theme</option>
                </select>
              </td>
              <td>
                <span class="badge"
                      [class.badge-good]="t.status === 'active'"
                      [class.badge-warn]="t.status === 'paused'"
                      [class.badge-neutral]="t.status === 'deprecated'"
                      [title]="t.status === 'paused' && t.paused_at
                        ? ('Paused ' + (t.paused_at | date:'MMM d, y'))
                        : ''">{{ t.status }}</span>
                <!-- Active and still unable to fire. The ICP's "signals that
                     matter" is what extraction is restricted to, so a type it
                     does not name produces nothing however well it is set up.
                     Eight of fifteen were in that state and the only clue was
                     a zero in the Signals column. -->
                <span class="badge badge-warn" *ngIf="t.extractable === false"
                      title="No active ICP lists this under “signals that matter”, and
                             extraction is restricted to that list — so this type cannot
                             produce a signal. Add it under Org profile.">
                  not extractable
                </span>
              </td>
              <td class="actcol">
                <!-- Icon-only, so each carries its own accessible name and a
                     hover label saying what the action actually does. -->
                <ng-container *ngIf="editing() === t.key">
                  <button class="act-btn" (click)="saveEdit(t)"
                          aria-label="Save changes" title="Save changes">
                    <app-icon name="check" [size]="15" />
                  </button>
                  <button class="act-btn" (click)="cancelEdit()"
                          aria-label="Cancel editing" title="Cancel">
                    <app-icon name="x" [size]="15" />
                  </button>
                </ng-container>

                <button *ngIf="editing() !== t.key && t.status !== 'deprecated'" class="act-btn"
                        (click)="startEdit(t)"
                        [attr.aria-label]="'Edit ' + t.key"
                        [title]="'Edit ' + t.key + ' — everything but the key and scope. Scoring changes affect future qualifications only'">
                  <app-icon name="edit" [size]="15" />
                </button>

                <button *ngIf="editing() !== t.key && t.status === 'active'" class="act-btn"
                        (click)="pause(t)"
                        [attr.aria-label]="'Pause ' + t.key"
                        [title]="'Pause ' + t.key + ' — stops extraction, reversible'">
                  <app-icon name="pause" [size]="15" />
                </button>

                <button *ngIf="editing() !== t.key && t.status === 'paused'" class="act-btn"
                        (click)="resume(t)"
                        [attr.aria-label]="'Resume ' + t.key"
                        [title]="'Resume ' + t.key + ' — extraction starts again on the next run'">
                  <app-icon name="play" [size]="15" />
                </button>

                <!-- Deprecate only makes sense for something with history. A
                     type that never fired is deleted outright below. -->
                <button *ngIf="editing() !== t.key && t.status !== 'deprecated' && t.signal_count"
                        class="act-btn danger" (click)="deprecate(t)"
                        [attr.aria-label]="'Deprecate ' + t.key"
                        [title]="'Deprecate ' + t.key + ' — permanent. Its ' + t.signal_count +
                                 ' signal(s) keep their evidence'">
                  <app-icon name="trash" [size]="15" />
                </button>

                <ng-container *ngIf="editing() !== t.key && !t.signal_count">
                  <button *ngIf="confirming() !== t.key" class="act-btn danger"
                          (click)="askDelete(t)"
                          [attr.aria-label]="'Delete ' + t.key"
                          [title]="'Delete ' + t.key + ' — it has never produced a signal, so nothing cites it'">
                    <app-icon name="trash" [size]="15" />
                  </button>
                  <ng-container *ngIf="confirming() === t.key">
                    <span class="row-sub" style="margin-right:6px;">Delete for good?</span>
                    <button class="act-btn danger" (click)="confirmDelete(t)"
                            [attr.aria-label]="'Confirm delete ' + t.key" title="Yes, delete it">
                      <app-icon name="check" [size]="15" />
                    </button>
                    <button class="act-btn" (click)="confirming.set(null)"
                            aria-label="Keep it" title="Keep it">
                      <app-icon name="x" [size]="15" />
                    </button>
                  </ng-container>
                </ng-container>

                <span *ngIf="t.status === 'deprecated' && t.signal_count" class="row-sub"
                      [title]="'Deprecated ' + (t.deprecated_at | date:'MMM d, y')">
                  retired
                </span>
              </td>
            </tr>

            <!-- The two fields that cannot live in a column. Description is
                 prose that goes into a prompt, and the source list is a grid
                 of a dozen checkboxes; squeezing either into a cell is how
                 they ended up uneditable in the first place. -->
            <tr *ngIf="editing() === t.key" class="edit-extra">
              <td [attr.colspan]="9">
                <div class="extra-grid">
                  <label>Description
                    <textarea class="field" rows="3" [(ngModel)]="edit.description"
                              [attr.aria-label]="'Description for ' + t.key"></textarea>
                    <span class="row-sub">
                      Goes into the extraction prompt, so write it as an instruction. Editing it
                      changes what every later run reads out of the same evidence.
                    </span>
                  </label>
                  <div>
                    <strong style="font-size:.84rem;display:block;margin-bottom:4px;">Found in</strong>
                    <span class="row-sub" style="display:block;margin-bottom:8px;">
                      What research <strong>opens</strong>, not what is found in it — every source
                      is read against every type. Two or three is usually right.
                    </span>
                    <div class="fam-grid">
                      <label class="fam" *ngFor="let f of sourcesFor(g.scope)"
                             [class.fam-on]="edit.produced_by.includes(f.key)"
                             [title]="f.description">
                        <input type="checkbox"
                               [checked]="edit.produced_by.includes(f.key)"
                               (change)="toggleEditFamily(f.key)">
                        <span>
                          {{ f.label }}
                          <em *ngIf="f.support_only" class="row-sub"
                              style="display:block;font-style:normal;">
                            supports only — cannot create a signal alone
                          </em>
                          <em *ngIf="f.status !== 'active'" class="row-sub"
                              style="display:block;font-style:normal;">
                            {{ f.status }} — can be claimed, but will not run until resumed
                          </em>
                        </span>
                      </label>
                    </div>
                  </div>
                </div>
              </td>
            </tr>
            </ng-container>

            <tr *ngIf="!loading() && byScope(g.scope).length === 0">
              <td colspan="9" class="row-sub" style="text-align:center;padding:22px;">
                No {{ g.scope }} signal types yet.
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </ng-container>

    <p class="row-sub" style="max-width:70ch;">
      <strong>Retire by deprecating once a type has produced something.</strong> A deprecated
      type stops being extracted and leaves the pickers, but its existing signals still render,
      keep their evidence, and stay available to Learning — a qualification decided partly on it
      still has to be able to explain itself. A type that has never produced a signal has no such
      history, so it can be deleted outright: a typo should not become a permanent tombstone.
    </p>

    <!-- Where research looks, beside the types that claim it. The two are
         edited together: a type names the sources its fact usually lives in,
         and a source nothing claims is one nobody reads. -->
    <app-source-registry
      [sources]="sources"
      [types]="types"
      [trialAccounts]="trialAccounts"
      [reuseWindow]="reuseDays()"
      [reuseVersion]="reuseVersion()"
      (changed)="reload()" />
  `,
  styles: [
    `
      .sec-head { display: flex; justify-content: space-between; align-items: center;
                  gap: 16px; margin-bottom: 4px; }
      .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
      .plan-line { display: flex; align-items: center; justify-content: space-between;
                   gap: 16px; margin: 0 0 16px; flex-wrap: wrap; }
      .prop { display: flex; align-items: flex-start; justify-content: space-between;
              gap: 16px; padding: 9px 0; border-top: 1px dashed var(--line); }
      .prop:first-of-type { border-top: 0; }
      td.looks { white-space: normal; max-width: 280px; }
      .form-grid label { display: flex; flex-direction: column; gap: 5px; font-size: .84rem; }
      .fam-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
                  gap: 8px; }
      .form-grid .fam { flex-direction: row; align-items: flex-start; gap: 8px;
                        font-size: .84rem; border: 1px solid var(--line);
                        border-radius: 7px; padding: 8px 10px; cursor: pointer; }
      .form-grid .fam input { margin-top: 2px; flex: none; }
      .fam-on { border-color: var(--accent); background: var(--accent-soft, transparent); }
      /* A dashed edge for "the model proposed this", distinct from the solid
         edge of "this is ticked". The two are independent: a suggestion can be
         unticked, and anything else can be ticked without being suggested. */
      .fam-suggested { border-style: dashed; border-color: var(--accent); }
      .cell-input { width: 82px; padding: 4px 7px; font-size: .8rem;
                    font-family: 'IBM Plex Mono', monospace; }
      /* The label is prose, not a figure — it gets room and the body font. */
      .cell-input.wide { width: 100%; min-width: 140px; font-family: inherit; margin-top: 4px; }
      .edit-extra > td { background: var(--surface-2, #f6f7f6); padding: 14px 12px 16px; }
      .extra-grid { display: grid; grid-template-columns: minmax(240px, 1fr) 1.4fr; gap: 18px;
                    align-items: start; }
      .extra-grid textarea { width: 100%; }
      @media (max-width: 900px) { .extra-grid { grid-template-columns: 1fr; } }
      @media (max-width: 720px) { .form-grid { grid-template-columns: 1fr; } }
    `,
  ],
})
export class SignalTypesComponent implements OnInit {
  private api = inject(ConfigService);
  private lists = inject(ListsService);

  types = signal<SignalType[]>([]);
  loading = signal(true);
  saving = signal(false);
  error = signal<string | null>(null);
  adding = signal<Scope | null>(null);
  /** Collapsed by default — the registry is what you come here for. */
  help = signal(false);
  editing = signal<string | null>(null);
  confirming = signal<string | null>(null);
  edit = {
    label: '',
    description: '',
    produced_by: [] as string[],
    weight: 1.0,
    default_ttl_days: 90,
    /** Null is "use the default", not "zero days". */
    durability_days: null as number | null,
    search_instruction: '',
    search_group: '',
    kind: 'event' as 'event' | 'theme',
  };
  suggesting = signal(false);
  applying = signal<string | null>(null);
  suggestions = signal<{
    groups: { label: string; type_keys: string[]; why: string }[];
    ungrouped: string[];
  } | null>(null);

  sources = signal<ResearchSource[]>([]);
  asking = signal(false);
  suggestWhy = signal('');
  /** Places the model named that the registry does not have. Shown, not added. */
  newSources = signal<string[]>([]);
  /**
   * Which sources the last suggestion proposed.
   *
   * Separate from the ticks, and the picker still lists **every** source: a
   * suggestion is a starting point about an unfamiliar registry, not a filter.
   * Showing only what was suggested would hide the source a rep knows is right,
   * and ticking without marking leaves them unable to tell their own choices
   * from the model's — or to judge how good its last answer was.
   */
  suggested = signal<Set<string>>(new Set());
  draft = {
    key: '',
    label: '',
    description: '',
    default_ttl_days: 90,
    weight: 1.0,
    produced_by: [] as string[],
    search_instruction: '',
    search_group: '',
    kind: 'event' as 'event' | 'theme',
  };

  groups = [
    {
      scope: 'company' as const,
      title: 'Company',
      heading: 'Company signal types',
      blurb: 'Evidence about the organisation. Drives qualification and answers why now.',
    },
    {
      scope: 'contact' as const,
      title: 'Contact',
      heading: 'Contact signal types',
      blurb:
        'Evidence about a person. Answers why you, and decides which persona leads — ' +
        'evidence about someone beats a guess from their title.',
    },
  ];

  ngOnInit(): void {
    this.load();
    this.api.researchSources().subscribe({
      // Paused ones are kept. They used to be filtered out here, which left a
      // picker shorter than the registry for no stated reason — and a type
      // already claiming a paused source showed the chip with no checkbox to
      // untick. `ats_boards` is paused and three types name it. Deprecated
      // rows are excluded by the endpoint, which is the right place: those are
      // gone, these are off.
      next: (f) => this.sources.set(f),
      // A missing registry must not silently render an empty picker that looks
      // like "no sources apply".
      error: () => this.error.set('Could not load research sources.'),
    });
  }

  sourcesFor(scope: Scope): ResearchSource[] {
    return this.sources().filter((f) => f.scopes.includes(scope));
  }

  /**
   * The ones this scope cannot use, named rather than merely absent.
   *
   * A picker showing eight of nine with no explanation makes a reader count
   * and wonder what is missing. `enrichment` looks up people, so it never
   * appears for a company signal; the ATS and filing sources are the mirror
   * image. Saying which turns a silent gap into a stated rule.
   */
  sourcesOutOfScope(scope: Scope): string[] {
    return this.sources()
      .filter((f) => !f.scopes.includes(scope))
      .map((f) => f.label)
      .sort();
  }

  briefFor(key: string): string {
    return this.sources().find((f) => f.key === key)?.description ?? key;
  }

  /**
   * Ask where this type would be found, and fill the boxes with the answer.
   *
   * Sent from the form rather than after saving, because the question is most
   * useful while the description is still being typed. Nothing is saved: the
   * rep accepts it by pressing Add, the same as anything else they typed.
   */
  askSources(scope: Scope): void {
    this.asking.set(true);
    this.suggestWhy.set('');
    this.newSources.set([]);
    this.api
      .suggestSourcesForType({
        key: this.draft.key.trim(),
        label: this.draft.label.trim(),
        scope,
        description: this.draft.description.trim() || null,
      })
      .subscribe({
        next: (r) => {
          this.asking.set(false);
          this.draft.produced_by = r.sources;
          // Recorded separately from the ticks so the two stay distinguishable.
          // The suggestion is a proposal about an unfamiliar registry; ticking
          // without saying which were the model's idea leaves a rep unable to
          // tell their own choices from its, and unable to judge it next time.
          this.suggested.set(new Set(r.sources));
          // Only offered into an empty box. Overwriting words a rep typed
          // would be the model editing them rather than helping.
          if (r.search_instruction && !this.draft.search_instruction.trim()) {
            this.draft.search_instruction = r.search_instruction;
          }
          this.suggestWhy.set(r.why);
          this.newSources.set(r.new_sources.map((n) => n.label || n.key));
        },
        error: (err) => {
          this.asking.set(false);
          this.error.set(apiError(err, 'Could not ask where this is found.'));
        },
      });
  }

  toggleFamily(key: string): void {
    const on = this.draft.produced_by;
    this.draft.produced_by = on.includes(key)
      ? on.filter((k) => k !== key)
      : [...on, key];
  }

  toggleEditFamily(key: string): void {
    const on = this.edit.produced_by;
    this.edit.produced_by = on.includes(key)
      ? on.filter((k) => k !== key)
      : [...on, key];
  }

  /**
   * What the durability figure means, for the tooltip.
   *
   * The derivation used to sit beside the number as "×3" and was read as a
   * multiplier still to apply — 900d ×3 as 2700 days, when the 900 *was*
   * 300×3. It says the same thing here without standing next to the figure it
   * would be mistaken for.
   */
  durabilityWhy(t: SignalType): string {
    const base =
      'How long a fact of this type stays worth reading. Research and extraction both refuse ' +
      'anything older.';
    return t.durability_days === null
      ? `${base} The default: three times the ${t.default_ttl_days}-day TTL.`
      : `${base} Set for this type, rather than the default of ${t.default_ttl_days * 3} days.`;
  }

  /** Why Add is disabled, or null when it is not. */
  blocker(): string | null {
    if (!this.draft.key.trim()) return 'Give it a key — lowercase snake_case, e.g. budget_cycle.';
    if (!/^[a-z][a-z0-9_]*$/.test(this.draft.key)) {
      return 'Key must be lowercase snake_case, starting with a letter.';
    }
    if (this.draft.key.length < 2) return 'Key needs at least two characters.';
    if (!this.draft.label.trim()) return 'Give it a label — the human-readable name.';

    // Mirrors the server rule so the reason arrives before the round trip.
    const chosen = this.draft.produced_by;
    if (chosen.length && chosen.every((k) => this.sourceOf(k)?.support_only)) {
      return 'Those sources can support a signal but never create one, so this type would never fire.';
    }
    return null;
  }

  private sourceOf(key: string): ResearchSource | undefined {
    return this.sources().find((f) => f.key === key);
  }

  byScope(scope: Scope): SignalType[] {
    return this.types().filter((t) => t.scope === scope);
  }

  startAdd(scope: Scope): void {
    this.adding.set(this.adding() === scope ? null : scope);
    this.error.set(null);
  }

  cancel(): void {
    this.adding.set(null);
    this.reset();
  }

  canSave(): boolean {
    return this.blocker() === null;
  }

  save(): void {
    const scope = this.adding();
    if (!scope || !this.canSave()) return;

    this.saving.set(true);
    this.api
      .createSignalType({ ...this.draft, scope })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.adding.set(null);
          this.reset();
          this.load();
        },
        error: (err) => {
          this.saving.set(false);
          this.error.set(apiError(err, 'Could not add the signal type.'));
        },
      });
  }

  startEdit(t: SignalType): void {
    this.editing.set(t.key);
    this.edit = {
      label: t.label,
      description: t.description ?? '',
      // Copied, not referenced. `toggleEditFamily` would otherwise mutate the
      // loaded row in place, and cancelling would leave the edit applied to
      // the screen with nothing sent to the server.
      produced_by: [...t.produced_by],
      weight: t.weight,
      default_ttl_days: t.default_ttl_days,
      // Left empty when it is the default, so the box shows the placeholder
      // rather than pinning the derived number as if someone had chosen it.
      durability_days: t.durability_days ?? null,
      search_instruction: t.search_instruction ?? '',
      search_group: t.search_group ?? '',
      kind: t.kind ?? 'event',
    };
  }

  cancelEdit(): void {
    this.editing.set(null);
  }

  saveEdit(t: SignalType): void {
    const changes: {
      label?: string;
      description?: string | null;
      produced_by?: string[];
      weight?: number;
      default_ttl_days?: number;
      durability_days?: number;
      search_instruction?: string | null;
      search_group?: string | null;
      kind?: 'event' | 'theme';
    } = {};
    const label = this.edit.label.trim();
    // An empty label is not an edit. The server requires one, and sending a
    // blank would turn a slip of the keyboard into a 422 on a row the rep
    // only meant to retune.
    if (label && label !== t.label) changes.label = label;
    const description = this.edit.description.trim();
    if (description !== (t.description ?? '')) changes.description = description || null;
    // Order is not meaning here — two lists with the same keys are the same
    // answer — so compare as sets, or reordering the registry would patch
    // every row the rep opened.
    if (!sameKeys(this.edit.produced_by, t.produced_by)) {
      changes.produced_by = [...this.edit.produced_by];
    }
    // An instruction is a prompt fragment: changing it changes what every
    // later search asks for, which is why it is edited deliberately here
    // rather than inferred from anything.
    const instruction = this.edit.search_instruction.trim();
    if (instruction !== (t.search_instruction ?? '')) {
      changes.search_instruction = instruction || null;
    }
    const group = this.edit.search_group.trim();
    if (group !== (t.search_group ?? '')) changes.search_group = group || null;
    if (this.edit.weight !== t.weight) changes.weight = this.edit.weight;
    if (this.edit.kind !== (t.kind ?? 'event')) changes.kind = this.edit.kind;
    if (this.edit.default_ttl_days !== t.default_ttl_days) {
      changes.default_ttl_days = this.edit.default_ttl_days;
    }
    // Emptying the box means "back to the default", and the server spells that
    // `0` — null cannot carry it, because in a patch null already means "leave
    // this field alone".
    const durable = this.edit.durability_days;
    const wanted = durable === null || durable === undefined ? null : Number(durable);
    if (wanted !== (t.durability_days ?? null)) {
      changes.durability_days = wanted ?? 0;
    }
    // No diff means no request — a PATCH with nothing in it is a 400 server-side.
    if (Object.keys(changes).length === 0) {
      this.editing.set(null);
      return;
    }
    this.api.updateSignalType(t.key, changes).subscribe({
      next: (updated) => {
        this.types.update((rows) => rows.map((r) => (r.key === updated.key ? updated : r)));
        this.editing.set(null);
      },
      error: (err) => this.error.set(apiError(err, 'Could not save.')),
    });
  }

  pause(t: SignalType): void {
    this.apply(this.api.pauseSignalType(t.key));
  }

  resume(t: SignalType): void {
    this.apply(this.api.resumeSignalType(t.key));
  }

  private apply(call: import('rxjs').Observable<SignalType>): void {
    call.subscribe({
      next: (updated) =>
        this.types.update((rows) => rows.map((r) => (r.key === updated.key ? updated : r))),
      error: (err) => this.error.set(apiError(err, 'Action failed.')),
    });
  }

  deprecate(t: SignalType): void {
    this.apply(this.api.deprecateSignalType(t.key));
  }

  askDelete(t: SignalType): void {
    this.confirming.set(t.key);
    this.error.set(null);
  }

  /** Permitted only while nothing cites the type — the server is the authority. */
  confirmDelete(t: SignalType): void {
    this.api.deleteSignalType(t.key).subscribe({
      next: () => {
        this.types.update((rows) => rows.filter((r) => r.key !== t.key));
        this.confirming.set(null);
      },
      error: (err) => {
        // A signal can land between render and click. The row stays.
        this.error.set(apiError(err, 'Could not delete.'));
        this.confirming.set(null);
      },
    });
  }

  private reset(): void {
    this.draft = {
      key: '', label: '', description: '', default_ttl_days: 90, weight: 1.0, produced_by: [],
      search_instruction: '', search_group: '', kind: 'event',
    };
    // The marks belong to the draft that was asked about. Left behind, they
    // would claim the model proposed something for a type it never saw.
    this.suggested.set(new Set());
    this.suggestWhy.set('');
    this.newSources.set([]);
  }

  /** Group labels already in use, for the picker. */
  groupNames(): string[] {
    const names = this.types()
      .filter((t) => t.status !== 'deprecated' && t.search_group)
      .map((t) => t.search_group as string);
    return [...new Set(names)].sort();
  }

  activeTypes(): number {
    return this.types().filter((t) => t.status === 'active').length;
  }

  /** Distinct sources these types name between them. */
  sourcesNamed(): number {
    const keys = new Set<string>();
    for (const t of this.types()) {
      if (t.status !== 'active') continue;
      for (const key of t.produced_by) keys.add(key);
    }
    return keys.size;
  }

  /**
   * Extra searches the exceptions cost, per account, on top of the sources.
   *
   * Counted separately from the sources because they are a different kind of
   * spend: a source is read once whatever asked for it, while each of these is
   * a call bought for one conclusion. Grouped ones share a call.
   */
  searchCount(): number {
    const keys = new Set<string>();
    for (const t of this.types()) {
      if (t.status !== 'active' || !t.search_instruction) continue;
      keys.add(t.search_group ? `group:${t.search_group}` : `type:${t.key}`);
    }
    return keys.size;
  }

  /**
   * Active types no source is asked to turn up.
   *
   * Not "never runs" any more, and the difference matters: every document a
   * source returns is read against every type, so an untargeted type is less
   * likely to be found rather than impossible. Reps act on warnings, so the
   * warning has to mean what it says.
   */
  neverRuns(): number {
    return this.types().filter(
      (t) => t.status === 'active' && !t.produced_by.length,
    ).length;
  }

  suggest(): void {
    this.suggesting.set(true);
    this.api.suggestSignalTypeGroups().subscribe({
      next: (result) => {
        this.suggesting.set(false);
        this.suggestions.set(result);
      },
      error: (err) => {
        this.suggesting.set(false);
        this.error.set(apiError(err, 'Could not ask for groupings.'));
      },
    });
  }

  /** Apply one proposal: label every type in it, then reload. */
  applyGroup(proposal: { label: string; type_keys: string[] }): void {
    this.applying.set(proposal.label);
    const calls = proposal.type_keys.map((key) =>
      this.api.updateSignalType(key, { search_group: proposal.label } as never),
    );
    forkJoin(calls).subscribe({
      next: () => {
        this.applying.set(null);
        this.suggestions.update((s) =>
          s ? { ...s, groups: s.groups.filter((g) => g.label !== proposal.label) } : s,
        );
        this.load();
      },
      error: (err) => {
        this.applying.set(null);
        // Some may have landed before the failure, so reload rather than
        // assuming the batch was all-or-nothing.
        this.load();
        this.error.set(apiError(err, 'Could not apply that grouping.'));
      },
    });
  }

  /** Re-read after the embedded registry changes something. The parent owns
   *  the data, so it owns the refresh. */
  /** Accounts for the registry's Try button, and the stored reuse window.
   *  Loaded here because the child does no I/O of its own — see its note. */
  trialAccounts = signal<{ id: string; name: string; domain: string | null }[]>([]);
  reuseDays = signal(30);
  reuseVersion = signal(0);

  reload(): void {
    this.load();
  }

  private load(): void {
    this.lists.accounts({ field: 'name', direction: 'asc' }).subscribe({
      next: (rows) =>
        this.trialAccounts.set(
          rows
            .filter((a) => (a.domain || '').trim())
            .slice(0, 40)
            .map((a) => ({ id: a.id, name: a.name, domain: a.domain ?? null })),
        ),
      error: () => undefined,
    });
    this.api.researchSettings().subscribe({
      next: (s) => {
        this.reuseDays.set(s.freshness_days);
        this.reuseVersion.set(s.version);
      },
      error: () => undefined,
    });
    this.loading.set(true);
    this.api.signalTypes(undefined, true).subscribe({
      next: (rows) => {
        this.types.set(rows);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(apiError(err, 'The API is not reachable.'));
        this.loading.set(false);
      },
    });
  }
}
