import { CommonModule } from '@angular/common';
import {
  Component, EventEmitter, Input, OnInit, Output, inject, signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  ConfigService, IcpSourcePerformance, ResearchSource, SignalType,
} from '../core/config.service';
import { IconComponent } from '../shared/icon.component';

/**
 * The ICP, as factors rather than as JSON.
 *
 * It was a JSON textarea, which asked somebody defining a sales territory to
 * also balance brackets. Worse, it made the *vocabulary* invisible: nothing on
 * screen said that `industries` was a thing you could set, so the only way to
 * discover a factor was to already know it.
 *
 * The design problem is that `org_profile.icp` is deliberately free-form —
 * "keys are free-form; they are read as facts about who to target" — and a
 * form over free-form data destroys whatever it does not understand. So the
 * editor is built around **preservation** rather than a schema:
 *
 * * factors it knows get a proper control, with suggestions, so the common
 *   ones are discoverable and spelled consistently;
 * * a key it does not know, or a value whose *shape* it cannot represent — a
 *   nested object, a number — is carried through untouched and listed as
 *   read-only, so nothing silently disappears from a prompt;
 * * the raw JSON stays available behind a toggle, so nothing becomes
 *   uneditable and the escape hatch is never a rewrite of this component.
 *
 * The preservation rule is not a nicety. This block is the first cached
 * section of every prompt the system sends, and a key quietly dropped on save
 * changes what every stage is told without appearing in any diff a person
 * reads.
 */

type FactorKind = 'chips' | 'range' | 'text' | 'personas' | 'sources' | 'choice';

/**
 * The buying roles a persona can carry. The same closed set as
 * `contact.buying_role_valid` — the ICP uses it rather than inventing a
 * parallel one (`docs/11`).
 */
export const BUYING_ROLES: { key: string; label: string }[] = [
  { key: 'economic_buyer', label: 'Economic buyer' },
  { key: 'technical_buyer', label: 'Technical buyer' },
  { key: 'champion', label: 'Champion' },
  { key: 'influencer', label: 'Influencer' },
  { key: 'blocker', label: 'Blocker' },
];

/** A buying role plus the titles that fill it. */
export interface Persona {
  buying_role: string;
  titles: string[];
}

/** The two signal scopes, as they are set on the Signal types screen. */
const SCOPES: { key: 'company' | 'contact'; label: string; hint: string }[] = [
  {
    key: 'company',
    label: 'Company signals',
    hint: 'About the organisation — found once and shared by every list that works the account.',
  },
  {
    key: 'contact',
    label: 'Contact signals',
    hint: "About a person — researched only for this ICP's buyer personas.",
  },
];

/** One selectable headcount band. `max: null` is the open-ended top band. */
interface Band {
  label: string;
  min: number;
  max: number | null;
}

interface Factor {
  key: string;
  label: string;
  kind: FactorKind;
  hint: string;
  /** Offered as a datalist. Never a closed set — typing anything is allowed. */
  suggestions?: string[];
  /**
   * Draw the options from configuration instead, and accept nothing else.
   *
   * The exception to this editor's free-text rule, and it earns the exception:
   * a value here that is not a registered signal type cannot ever become a
   * signal. `extraction._reject_reason` drops anything whose type is unknown or
   * inactive, so a hand-typed trigger is not an instruction to look harder — it
   * is research the system pays for and then discards, with only a log line to
   * show for it. Typing freely here can only express a wish.
   */
  optionsFrom?: 'signal-types';
  /** For `choice`: the closed set, each with the words that explain it. */
  options?: { key: string; label: string; hint: string }[];
}

/**
 * The factors worth naming on screen.
 *
 * Suggestions, not a schema: the list exists so the common vocabulary is
 * discoverable and spelled the same way twice, which matters when a model is
 * reading it. Anything else can still be added through the JSON view.
 */
const FACTORS: Factor[] = [
  {
    // First, because it decides how everything below it is argued — and
    // because it is the one factor the prompts branch on rather than read.
    key: 'track',
    label: 'Buyer track',
    kind: 'choice',
    hint:
      'Which buyer this list is for. Strategy and drafting change register ' +
      'on it: a CIO measured on nothing going wrong does not read the ' +
      'argument written for a CTO measured on what ships.',
    options: [
      {
        key: 'enterprise',
        label: 'Enterprise IT',
        hint:
          'A non-technology business running internal IT — the argument is ' +
          'risk, continuity and the cost of carrying what is fragile.',
      },
      {
        key: 'tech_company',
        label: 'Technology company',
        hint:
          'An ISV, SaaS or IT product company — software is what it sells, ' +
          'and the argument is bandwidth and time to market.',
      },
    ],
  },
  {
    key: 'industries',
    label: 'Industries',
    kind: 'chips',
    hint: 'Sectors worth approaching. Leave empty for no industry constraint.',
    suggestions: [
      'SaaS', 'Fintech', 'Logistics', 'Healthcare', 'E-commerce',
      'Manufacturing', 'EdTech', 'Insurance', 'Real estate', 'Media',
      'Travel', 'Gaming', 'Telecom', 'Energy',
    ],
  },
  {
    key: 'regions',
    label: 'Regions',
    kind: 'chips',
    hint: 'Where the company is, not where its customers are.',
    suggestions: ['US', 'UK', 'EU', 'IN', 'APAC', 'MENA', 'LATAM', 'Canada', 'Australia'],
  },
  {
    key: 'employees',
    label: 'Company size',
    kind: 'range',
    hint:
      'Headcount. Pick a band, or several adjoining ones to widen the span — ' +
      'click an end to trim it. Stored as a single range, because that is how ' +
      'it is read.',
  },
  {
    key: 'personas',
    label: 'Buyer personas',
    kind: 'personas',
    hint:
      'Who to reach: a buying role, and the titles that fill it. Titles are what ' +
      'imports and enrichment match on; the role is what strategy reasons with. ' +
      'Enrichment and research refuse an ICP that names nobody.',
  },
  {
    key: 'signals_that_matter',
    label: 'Signals that matter',
    kind: 'chips',
    hint:
      'Which triggers make an account worth approaching now, split the way the ' +
      'Signal types screen scopes them. A trigger with no type behind it can never ' +
      'be recorded, so define the type first and it appears here.',
    optionsFrom: 'signal-types',
  },
  {
    // Stores the *exclusions*. The places themselves are derived from the
    // signals above, because each signal type already names where its fact
    // lives and a second list could only ever contradict the first.
    key: 'sources_excluded',
    label: 'Where to look',
    kind: 'sources',
    hint:
      'Derived from the signals above — each one names where its fact lives. The same ' +
      'set runs for every account on the lists this ICP is worked for, which is what makes ' +
      'two accounts ' +
      'comparable: "nothing found at Apex" is then a fact about Apex rather than about ' +
      'what somebody decided to look for that day. Untick one to stop paying for it here ' +
      'without removing it from the signal type.',
  },
  {
    key: 'business_model',
    label: 'Business model',
    kind: 'chips',
    hint: 'How they make money — it changes who feels the problem.',
    suggestions: [
      'B2B SaaS', 'B2C', 'Marketplace', 'Enterprise software',
      'Services', 'Hardware', 'Platform',
    ],
  },
  {
    key: 'tech_stack',
    label: 'Tech stack',
    kind: 'chips',
    hint: 'Only where it changes the pitch. A long list here narrows nothing.',
    suggestions: [
      'AWS', 'Azure', 'GCP', 'Kubernetes', 'React', 'Angular',
      '.NET', 'Java', 'Python', 'Node.js', 'Salesforce', 'Snowflake',
    ],
  },
  {
    key: 'exclusions',
    label: 'Do not target',
    kind: 'chips',
    hint: 'Sectors or situations to stay out of. Read as a hard constraint.',
    suggestions: ['Government', 'Defence', 'Gambling', 'Tobacco', 'Existing customers'],
  },
  {
    key: 'notes',
    label: 'Anything else',
    kind: 'text',
    hint: 'One or two lines a model should know about who to target.',
  },
];

const KNOWN = new Set(FACTORS.map((f) => f.key));

@Component({
  selector: 'app-icp-editor',
  standalone: true,
  imports: [CommonModule, FormsModule, IconComponent],
  template: `
    <div class="icp">
      <div class="fac" *ngFor="let f of factors">
        <div class="lbl">
          <strong>{{ f.label }}</strong>
          <span class="row-sub">{{ f.hint }}</span>
        </div>

        <!-- buyer personas: a role, and the titles that fill it -->
        <div *ngIf="f.kind === 'personas'" class="personas">
          <div class="persona" *ngFor="let p of personas; let i = index">
            <select class="field role" [ngModel]="p.buying_role"
                    (ngModelChange)="setPersonaRole(i, $event)"
                    [attr.aria-label]="'Buying role for persona ' + (i + 1)">
              <option *ngFor="let r of buyingRoles" [value]="r.key">{{ r.label }}</option>
            </select>
            <div class="chips">
              <span class="chip" *ngFor="let t of p.titles">
                {{ t }}
                <button type="button" class="x" (click)="removePersonaTitle(i, t)"
                        [attr.aria-label]="'Remove ' + t">×</button>
              </span>
              <input class="field title-in" [(ngModel)]="personaEntry[i]"
                     (keydown.enter)="addPersonaTitle(i); $event.preventDefault()"
                     [attr.aria-label]="'Add a title to persona ' + (i + 1)"
                     placeholder="add a title, press Enter">
            </div>
            <button type="button" class="act-btn" (click)="removePersona(i)"
                    [attr.aria-label]="'Remove persona ' + (i + 1)" title="Remove this persona">×</button>
          </div>
          <p class="row-sub none" *ngIf="!personas.length">
            None yet — nobody would be enriched or researched for this ICP.
          </p>
          <div>
            <button type="button" class="btn" (click)="addPersona()">+ Add buyer persona</button>
            <span class="row-sub" *ngIf="personas.length" style="margin-left:8px;">
              A persona with no titles is not saved.
            </span>
          </div>
        </div>

        <!-- signals that matter: two groups, by the scope each type carries on
             the Signal types screen. Stored as one list, because scope belongs
             to the type — a second copy here could only ever disagree with it. -->
        <div *ngIf="f.kind === 'chips' && f.optionsFrom" class="chips-wrap">
          <div class="scope-group" *ngFor="let g of scopes">
            <div class="scope-h"><strong>{{ g.label }}</strong>
              <span class="row-sub">{{ g.hint }}</span></div>
            <div class="chips">
              <span class="chip" *ngFor="let v of chipsInScope(f, g.key)">
                {{ v }}
                <button type="button" class="x" (click)="removeChip(f.key, v)"
                        [attr.aria-label]="'Remove ' + v">×</button>
              </span>
              <span class="row-sub none" *ngIf="!chipsInScope(f, g.key).length">none</span>
            </div>
            <div class="addrow">
              <select class="field" [(ngModel)]="scopeEntry[g.key]"
                      [attr.aria-label]="'Add a ' + g.key + ' signal'"
                      [disabled]="!unusedInScope(f, g.key).length">
                <option value="">{{ scopePlaceholder(f, g.key) }}</option>
                <option *ngFor="let s of unusedInScope(f, g.key)" [value]="s">{{ s }}</option>
              </select>
              <button type="button" class="btn"
                      (click)="addChipFor(f.key, scopeEntry[g.key] || ''); scopeEntry[g.key] = ''"
                      [disabled]="!scopeEntry[g.key]">Add</button>
            </div>
          </div>
          <div class="chips" *ngIf="orphanCount(f)">
            <span class="chip orphan" *ngFor="let v of orphans(f)" [attr.title]="orphanReason">
              {{ v }}
              <button type="button" class="x" (click)="removeChip(f.key, v)"
                      [attr.aria-label]="'Remove ' + v">×</button>
            </span>
          </div>
          <p class="row-sub orphan-note" *ngIf="orphanCount(f) as n">
            {{ n }} of these {{ n === 1 ? 'names a trigger' : 'name triggers' }}
            with no signal type behind {{ n === 1 ? 'it' : 'them' }}. Nothing can
            record {{ n === 1 ? 'it' : 'them' }} — define the type under Signal
            types, or remove {{ n === 1 ? 'it' : 'them' }} here.
          </p>
        </div>

        <!-- chips -->
        <div *ngIf="f.kind === 'chips' && !f.optionsFrom" class="chips-wrap">
          <div class="chips">
            <span class="chip" *ngFor="let v of chips[f.key]"
                  [class.orphan]="isOrphan(f, v)"
                  [attr.title]="isOrphan(f, v) ? orphanReason : null">
              {{ v }}
              <button type="button" class="x" (click)="removeChip(f.key, v)"
                      [attr.aria-label]="'Remove ' + v">×</button>
            </span>
            <span class="row-sub none" *ngIf="!chips[f.key]?.length">any</span>
          </div>

          <!-- A closed set, so a picker rather than a text box. Typing here
               could only ever name a trigger nothing can record. -->
          <div class="addrow" *ngIf="f.optionsFrom; else freeText">
            <select class="field" [(ngModel)]="entry[f.key]"
                    [attr.aria-label]="'Add to ' + f.label"
                    [disabled]="!unusedSuggestions(f).length">
              <option value="">
                {{ optionsPlaceholder(f) }}
              </option>
              <option *ngFor="let s of unusedSuggestions(f)" [value]="s">{{ s }}</option>
            </select>
            <button type="button" class="btn" (click)="addChip(f.key)"
                    [disabled]="!entry[f.key]">Add</button>
          </div>

          <ng-template #freeText>
            <div class="addrow">
              <input class="field" [attr.list]="listId(f.key)"
                     [(ngModel)]="entry[f.key]"
                     (keydown.enter)="addChip(f.key); $event.preventDefault()"
                     [attr.aria-label]="'Add to ' + f.label"
                     placeholder="type and press Enter">
              <datalist [id]="listId(f.key)">
                <option *ngFor="let s of unusedSuggestions(f)" [value]="s"></option>
              </datalist>
              <button type="button" class="btn" (click)="addChip(f.key)"
                      [disabled]="!entry[f.key]?.trim()">Add</button>
            </div>
          </ng-template>

          <p class="row-sub orphan-note" *ngIf="orphanCount(f) as n">
            {{ n }} of these {{ n === 1 ? 'names a trigger' : 'name triggers' }}
            with no signal type behind {{ n === 1 ? 'it' : 'them' }}. Nothing can
            record {{ n === 1 ? 'it' : 'them' }} — define the type under Signal
            types, or remove {{ n === 1 ? 'it' : 'them' }} here.
          </p>
        </div>

        <!-- where to look -->
        <!-- Derived, not chosen. Each signal type names where its fact lives,
             so an ICP picking sources as well was a second answer to a settled
             question — and the planner let it win, which is how a source three
             types claimed never ran while one nothing claimed ran anyway. The
             ticks here *subtract*. -->
        <!-- Read-only, on purpose. Sources are derived from the signals above,
             so there is nothing to choose here — and whether a place earns its
             keep differs by ICP, which only its own numbers can answer. This
             replaced a tick that switched a source off: a knob was a blunt
             answer to a question nobody had the evidence for. The capability
             survives in the API for when the evidence says to use it. -->
        <div *ngIf="f.kind === 'sources'" class="chips-wrap">
          <div class="sec-head" style="margin-bottom:8px;">
            <span class="row-sub">
              <ng-container *ngIf="derivedSources().length; else noSignals">
                <strong>{{ derivedSources().length }}</strong>
                place{{ derivedSources().length === 1 ? '' : 's' }} read per account
                <span *ngIf="extraSearches()"> · {{ extraSearches() }} extra
                  search{{ extraSearches() === 1 ? '' : 'es' }} from exceptions</span>
                <em *ngIf="!signalsChosen()" style="display:block;font-style:normal;">
                  No signals chosen above, so this is every active type — research would
                  read all of these. Choose signals to narrow it.
                </em>
              </ng-container>
              <ng-template #noSignals>
                Choose signals above and the places they are found appear here.
              </ng-template>
            </span>
          </div>

          <details class="src" *ngFor="let src of derivedSources()">
            <summary>
              <span class="src-name">{{ src.label }}</span>
              <span class="row-sub src-fig" *ngIf="perfFor(src.key) as p">
                <ng-container *ngIf="p.accounts; else unread">
                  {{ p.evidence }} passage{{ p.evidence === 1 ? '' : 's' }} ·
                  {{ p.accounts }} account{{ p.accounts === 1 ? '' : 's' }} ·
                  {{ p.empty }} empty<span *ngIf="p.failed"> · {{ p.failed }} failed</span>
                </ng-container>
                <ng-template #unread>not read yet</ng-template>
              </span>
              <span class="badge badge-warn" *ngIf="src.status !== 'active'">{{ src.status }}</span>
              <span class="badge badge-neutral" *ngIf="isExcluded(src.key)">off for this ICP</span>
            </summary>
            <div class="src-body">
              <p class="row-sub" style="margin:0 0 6px;">{{ src.description }}</p>
              <p class="row-sub" style="margin:0;">
                Read because <strong>{{ sourceReason(src.key) || 'a signal above names it' }}</strong>.
              </p>
              <p class="row-sub" *ngIf="perfFor(src.key) as p" style="margin:6px 0 0;">
                <ng-container *ngIf="p.accounts; else nothingYet">
                  Read at {{ p.accounts }} account{{ p.accounts === 1 ? '' : 's' }} on this
                  ICP's lists: {{ p.ran }} returned something, {{ p.empty }} looked and found
                  nothing<span *ngIf="p.failed">, {{ p.failed }} failed</span>.
                  <span *ngIf="!p.evidence && p.ran + p.empty >= 5">
                    Tried enough to judge and produced nothing — worth dropping the signal that
                    expects it, or changing what that signal looks for.
                  </span>
                </ng-container>
                <ng-template #nothingYet>
                  Nothing read here yet for this ICP. The numbers appear once its lists are
                  researched, and they are what says whether this place is worth the call.
                </ng-template>
              </p>
            </div>
          </details>
        </div>

        <!-- range -->
        <div *ngIf="f.kind === 'range'" class="range">
          <input class="field narrow" type="number" min="0" [(ngModel)]="rangeMin"
                 (ngModelChange)="emit()" aria-label="Minimum headcount" placeholder="min">
          <span class="row-sub">to</span>
          <input class="field narrow" type="number" min="0" [(ngModel)]="rangeMax"
                 (ngModelChange)="emit()" aria-label="Maximum headcount" placeholder="max">
          <button type="button" class="btn" *ngFor="let p of presets"
                  [class.on]="isPreset(p)" [attr.aria-pressed]="isPreset(p)"
                  (click)="applyPreset(p)">{{ p.label }}</button>
          <span class="row-sub none" *ngIf="rangeMin === null && rangeMax === null">any</span>
        </div>

        <!-- free text -->
        <div *ngIf="f.kind === 'text'">
          <textarea class="field" rows="2" [(ngModel)]="texts[f.key]" (ngModelChange)="emit()"
                    [attr.aria-label]="f.label"></textarea>
        </div>

        <!-- One value from a closed set. Radios rather than a select: there
             are two, both need their explanation read, and a dropdown hides
             the one not chosen. -->
        <div *ngIf="f.kind === 'choice'" class="choices">
          <label class="choice" *ngFor="let o of f.options || []"
                 [class.choice-on]="texts[f.key] === o.key">
            <input type="radio" [name]="f.key" [value]="o.key"
                   [checked]="texts[f.key] === o.key"
                   (change)="pickChoice(f.key, o.key)">
            <span>
              <strong>{{ o.label }}</strong>
              <em class="row-sub" style="display:block;font-style:normal;">{{ o.hint }}</em>
            </span>
          </label>
          <!-- Its own row under the options, now that they sit side by side —
               flex-wrap would otherwise tuck it in as a third column. -->
          <button class="linkish" *ngIf="texts[f.key]" style="flex:0 0 100%;text-align:left;"
                  (click)="pickChoice(f.key, '')">
            Clear — neither
          </button>
        </div>
      </div>

      <!-- Anything this form cannot represent. Shown rather than hidden,
           because it is still going into every prompt. -->
      <div class="fac passthrough" *ngIf="passthroughKeys().length">
        <div class="lbl">
          <strong>Other factors</strong>
          <span class="row-sub">
            Set outside this form, and kept exactly as they are. Edit them in the JSON view.
          </span>
        </div>
        <div>
          <div class="pass" *ngFor="let k of passthroughKeys()">
            <code>{{ k }}</code>
            <span class="row-sub">{{ preview(k) }}</span>
          </div>
        </div>
      </div>

      <div class="rawbar">
        <button type="button" class="btn" (click)="toggleRaw()">
          {{ showRaw() ? 'Hide JSON' : 'Edit as JSON' }}
        </button>
        <span class="row-sub" *ngIf="!showRaw()">
          Keys are free-form. The JSON view is the escape hatch for anything the
          fields above cannot express.
        </span>
        <span class="row-sub bad" *ngIf="rawError()">{{ rawError() }}</span>
      </div>

      <div *ngIf="showRaw()" style="grid-column:1/-1;">
        <textarea class="field mono" rows="10" [(ngModel)]="raw"
                  (ngModelChange)="onRawEdit()" aria-label="ICP as JSON"></textarea>
      </div>
    </div>
  `,
  styles: [
    `
      .icp { display: flex; flex-direction: column; gap: 16px; }
      .fac { display: grid; grid-template-columns: 210px 1fr; gap: 14px;
             align-items: start; }
      /* Side by side. With two mutually exclusive options a column reads as a
         list to work through; a row reads as the choice it is, and the two
         descriptions can be compared without scanning past one to reach the
         other. Wraps back to a column when there is no width for it. */
      /* A source reads as a row you can open, not a box you tick. The summary
         carries the figure that decides whether it is earning its place; the
         body carries why it is read at all. */
      .src { border: 1px solid var(--line); border-radius: 6px; margin-bottom: 6px; }
      .src > summary { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;
                       padding: 7px 10px; cursor: pointer; font-size: .86rem; }
      .src > summary::marker { color: var(--muted, #888); }
      .src[open] > summary { border-bottom: 1px solid var(--line); }
      .src-name { font-weight: 600; }
      .src-fig { margin-left: auto; font-variant-numeric: tabular-nums; }
      .src-body { padding: 9px 10px; }
      .choices { display: flex; flex-wrap: wrap; gap: 8px; }
      .choice { display: flex; gap: 8px; align-items: flex-start; cursor: pointer;
                border: 1px solid var(--line); border-radius: 8px; padding: 9px 11px;
                flex: 1 1 26ch; min-width: 26ch; max-width: 52ch; }
      .choice-on { border-color: var(--accent); background: var(--surface-2, #f6f7f6); }
      .choice input { margin-top: 3px; }
      .linkish { background: none; border: 0; padding: 0; cursor: pointer; font: inherit;
                 font-size: .8rem; color: var(--accent); text-decoration: underline;
                 align-self: flex-start; }
      .lbl { display: flex; flex-direction: column; gap: 2px; }
      .lbl strong { font-size: .84rem; }
      .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px;
               min-height: 22px; align-items: center; }
      .chip { display: inline-flex; align-items: center; gap: 5px;
              padding: 2px 6px 2px 9px; border-radius: 12px; font-size: .78rem;
              border: 1px solid var(--line); background: rgba(127,127,127,.08); }
      .chip .x { border: 0; background: none; cursor: pointer; font-size: .95rem;
                 line-height: 1; padding: 0 2px; color: inherit; opacity: .6; }
      .chip .x:hover { opacity: 1; }
      .none { opacity: .6; }
      .addrow { display: flex; gap: 8px; }
      .addrow .field { max-width: 260px; }
      .range { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
      .range .narrow { max-width: 90px; }
      /* A value no signal type backs. Struck through rather than hidden:
         removing it silently would change what every prompt is told without
         appearing in any diff a person reads. */
      .chip.orphan { border-color: var(--critical); color: var(--critical);
                     text-decoration: line-through; }
      .personas { display: flex; flex-direction: column; gap: 8px; }
      .persona { display: grid; grid-template-columns: 170px 1fr auto; gap: 10px;
                 align-items: start; }
      .persona .role { max-width: 170px; }
      .persona .chips { margin: 0; }
      .persona .title-in { max-width: 200px; padding: 3px 8px; font-size: .8rem; }
      .scope-group + .scope-group { margin-top: 12px; }
      .scope-h { display: flex; flex-direction: column; gap: 1px; margin-bottom: 4px; }
      .scope-h strong { font-size: .8rem; }
      .orphan-note { margin-top: 6px; color: var(--critical); max-width: 60ch; }
      .range .btn { padding: 2px 9px; font-size: .74rem; }
      /* Which bands are in the span. Border as well as colour: a fill alone
         reads as a hover state, and several lit at once has to look chosen. */
      .range .btn.on { border-color: var(--accent); color: var(--accent);
                       background: var(--accent-soft); font-weight: 600; }
      .passthrough .pass { display: flex; gap: 10px; align-items: baseline;
                           margin-bottom: 4px; }
      .rawbar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
                padding-top: 12px; border-top: 1px solid var(--line); }
      .bad { color: var(--critical); }
      textarea.mono { font-family: 'IBM Plex Mono', monospace; font-size: .8rem; }
      @media (max-width: 720px) { .fac { grid-template-columns: 1fr; } }
    `,
  ],
})
export class IcpEditorComponent implements OnInit {
  private api = inject(ConfigService);
  readonly factors = FACTORS;
  /**
   * The selectable headcount bands.
   *
   * `label` and bounds are separate because the two are not the same thing:
   * the top band reads `>1000` but is stored as `1000+`, the open-ended form
   * `parseBand` already understands and that anyone's existing ICP may hold.
   * Showing the stored form would be the easier code and the worse label.
   *
   * The boundaries touch rather than gap — 50 ends one band and starts the
   * next. That is how these are quoted in practice ("50 to 100 people"), and a
   * gap would leave a company of exactly 50 in no band at all.
   */
  readonly presets: Band[] = [
    { label: '1-50', min: 1, max: 50 },
    { label: '50-100', min: 50, max: 100 },
    { label: '100-200', min: 100, max: 200 },
    { label: '200-500', min: 200, max: 500 },
    { label: '500-1000', min: 500, max: 1000 },
    { label: '>1000', min: 1000, max: null },
  ];

  readonly buyingRoles = BUYING_ROLES;
  readonly scopes = SCOPES;

  /** Buyer personas, in the order they were written. */
  personas: Persona[] = [];
  /** The in-progress title in each persona's input. */
  personaEntry: string[] = [];
  /** The in-progress choice in each signal-scope picker. Starts at '' so the
   *  prompt option is selected — an undefined value matches no option and
   *  leaves the picker blank. */
  scopeEntry: Record<string, string> = { company: '', contact: '' };

  /** Chip lists, by factor key. */
  chips: Record<string, string[]> = {};
  /** The in-progress entry in each chip input. */
  entry: Record<string, string> = {};
  texts: Record<string, string> = {};
  rangeMin: number | null = null;
  rangeMax: number | null = null;

  /** Everything the form cannot represent, carried through untouched. */
  private passthrough: Record<string, unknown> = {};

  raw = '{}';
  showRaw = signal(false);
  rawError = signal<string | null>(null);

  @Input() set value(icp: Record<string, unknown> | null | undefined) {
    this.hydrate(icp ?? {});
  }

  @Output() valueChange = new EventEmitter<Record<string, unknown>>();

  /**
   * The profile being edited, when there is one.
   *
   * Absent while creating: the assembly call reads the ICP's saved signals and
   * industries, and there is nothing to read until it exists.
   */
  @Input() profileId: string | null = null;

  allSources = signal<ResearchSource[]>([]);
  /** Measured per ICP, because whether a place earns its keep differs by
   *  book — and only its own numbers can say so. */
  performance = signal<IcpSourcePerformance[]>([]);
  signalTypes = signal<SignalType[]>([]);

  /**
   * Set a single-choice factor, or clear it.
   *
   * Cleared to `''`, which `emit()` already drops the way it drops an empty
   * text field — so "neither" leaves the key absent rather than present and
   * empty. The prompts read a missing track as "not established" and fall back
   * to arguing from the evidence; a key holding `""` would be a third state
   * nothing is written to handle.
   */
  pickChoice(key: string, value: string): void {
    this.texts[key] = value;
    this.emit();
  }

  /**
   * Every place the chosen signals say their facts live.
   *
   * The ICP no longer holds a source list of its own. It held one, it took
   * precedence over this, and the two could describe different worlds: a
   * source three types claimed never ran because the ICP omitted it, while one
   * nothing claimed ran anyway. Derived, that is unrepresentable.
   */
  /** Whether this ICP has narrowed research at all.
   *
   * Distinguished from "chose nothing yet" because the planner does not treat
   * them the same: an empty `signals_that_matter` means *every* active type,
   * not none, so a new ICP derives every source and the list reads as a choice
   * nobody made.
   */
  signalsChosen(): boolean {
    return (this.chips['signals_that_matter'] ?? []).length > 0;
  }

  derivedSources(): ResearchSource[] {
    const wanted = new Set(this.chips['signals_that_matter'] ?? []);
    const keys = new Set<string>();
    for (const t of this.signalTypes()) {
      if (t.status !== 'active') continue;
      if (wanted.size && !wanted.has(t.key)) continue;
      // `?? []` because this runs on every change-detection pass, and a row
      // that arrives without the field would otherwise throw inside the
      // template rather than simply contributing nothing.
      for (const key of t.produced_by ?? []) keys.add(key);
    }
    return this.allSources().filter((s) => keys.has(s.key));
  }

  /** Derived, less what has been switched off — what actually gets read. */
  readSources(): ResearchSource[] {
    return this.derivedSources().filter((s) => !this.isExcluded(s.key));
  }

  isExcluded(key: string): boolean {
    return (this.chips['sources_excluded'] ?? []).includes(key);
  }

  /** What this source has returned for this ICP, once anything has been read. */
  perfFor(key: string): IcpSourcePerformance | null {
    return this.performance().find((p) => p.key === key) ?? null;
  }

  /**
   * What each source costs beyond the sweeps: the exceptions.
   *
   * Counted here rather than only on the Signal types screen because this is
   * where the whole per-account bill is decided, and a number a rep never sees
   * is a number that only grows.
   */
  extraSearches(): number {
    const wanted = new Set(this.chips['signals_that_matter'] ?? []);
    const keys = new Set<string>();
    for (const t of this.signalTypes()) {
      if (t.status !== 'active' || !t.search_instruction) continue;
      if (wanted.size && !wanted.has(t.key)) continue;
      keys.add(t.search_group ? `group:${t.search_group}` : `type:${t.key}`);
    }
    return keys.size;
  }

  /** Why this place is in the list: the types that said their fact lives there. */
  sourceReason(key: string): string {
    const naming = this.signalTypes()
      .filter((t) => t.status === 'active' && t.produced_by.includes(key))
      .map((t) => t.key);
    return naming.length ? `expected by ${naming.join(', ')}` : '';
  }

  /**
   * Active signal type keys, once they have actually arrived.
   *
   * `null` until then, and the distinction is load-bearing: with an empty array
   * every stored value would look like an orphan, so a failed request would
   * accuse a correct ICP of being broken. Null means "not known yet" and
   * nothing is judged.
   */
  signalTypeKeys = signal<string[] | null>(null);
  /** Each active type's scope, as set on the Signal types screen. */
  signalTypeScopes = signal<Record<string, string>>({});
  /** Set when the list could not be fetched, so the note can say which. */
  signalTypesFailed = signal(false);

  readonly orphanReason =
    'No signal type by this name is active, so nothing can ever record it.';

  ngOnInit(): void {
    // Active only. A paused or deprecated type is rejected by the extraction
    // guard exactly like an unknown one, so offering it would repeat the trap
    // this picker exists to close.
    this.api.signalTypes().subscribe({
      next: (types) => {
        const active = types.filter((t) => t.status === 'active');
        this.signalTypeScopes.set(Object.fromEntries(active.map((t) => [t.key, t.scope])));
        this.signalTypeKeys.set(active.map((t) => t.key));
        // The whole rows too: "where to look" needs each type's sources and
        // its exception instruction, neither of which a key list can carry.
        this.signalTypes.set(types);
      },
      error: () => this.signalTypesFailed.set(true),
    });
    this.api.researchSources().subscribe({
      // Paused rows are kept: a signal may still name one, and the panel says
      // so rather than leaving a place a reader can see in the registry but
      // not here.
      next: (rows) => this.allSources.set(rows),
      error: () => undefined,
    });
    if (this.profileId) {
      this.api.icpSourcePerformance(this.profileId).subscribe({
        // Silent on failure. It is a panel of numbers beside an editor that
        // must keep working without them.
        next: (rows) => this.performance.set(rows),
        error: () => undefined,
      });
    }
  }

  /** A known type's scope. A type that arrives without one reads as company. */
  private scopeOf(key: string): string {
    return this.signalTypeScopes()[key] ?? 'company';
  }

  /** The chosen signals of one scope. Orphans belong to neither and are shown apart. */
  chipsInScope(f: Factor, scope: string): string[] {
    return (this.chips[f.key] ?? []).filter(
      (v) => !this.isOrphan(f, v) && this.scopeOf(v) === scope,
    );
  }

  /** Active types of one scope not yet chosen. */
  unusedInScope(f: Factor, scope: string): string[] {
    return this.unusedSuggestions(f).filter((k) => this.scopeOf(k) === scope);
  }

  scopePlaceholder(f: Factor, scope: string): string {
    if (this.signalTypesFailed()) return 'could not load signal types';
    if (this.signalTypeKeys() === null) return 'loading…';
    const any = (this.signalTypeKeys() ?? []).some((k) => this.scopeOf(k) === scope);
    if (!any) return `no ${scope} signal types yet`;
    if (!this.unusedInScope(f, scope).length) return `every ${scope} signal type is listed`;
    return `choose a ${scope} signal…`;
  }

  orphans(f: Factor): string[] {
    return (this.chips[f.key] ?? []).filter((v) => this.isOrphan(f, v));
  }

  addPersona(): void {
    const used = new Set(this.personas.map((p) => p.buying_role));
    const role = BUYING_ROLES.find((r) => !used.has(r.key))?.key ?? BUYING_ROLES[0].key;
    this.personas = [...this.personas, { buying_role: role, titles: [] }];
    this.personaEntry = [...this.personaEntry, ''];
    this.emit();
  }

  removePersona(i: number): void {
    this.personas = this.personas.filter((_, j) => j !== i);
    this.personaEntry = this.personaEntry.filter((_, j) => j !== i);
    this.emit();
  }

  setPersonaRole(i: number, role: string): void {
    this.personas = this.personas.map((p, j) => (j === i ? { ...p, buying_role: role } : p));
    this.emit();
  }

  addPersonaTitle(i: number): void {
    this.addPersonaTitleFor(i, this.personaEntry[i] ?? '');
  }

  /** The same add, given the title directly. Used by the input and by tests. */
  addPersonaTitleFor(i: number, raw: string): void {
    const value = raw.trim();
    const persona = this.personas[i];
    if (!value || !persona) return;
    // Case-insensitive for the same reason chips are: "CTO" and "cto" are one title.
    if (!persona.titles.some((t) => t.toLowerCase() === value.toLowerCase())) {
      this.personas = this.personas.map((p, j) =>
        j === i ? { ...p, titles: [...p.titles, value] } : p,
      );
    }
    this.personaEntry[i] = '';
    this.emit();
  }

  removePersonaTitle(i: number, title: string): void {
    this.personas = this.personas.map((p, j) =>
      j === i ? { ...p, titles: p.titles.filter((t) => t !== title) } : p,
    );
    this.emit();
  }

  listId(key: string): string {
    return `icp-${key}`;
  }

  /** The options for a factor: configuration where it has some, else its own. */
  private options(f: Factor): string[] | null {
    if (f.optionsFrom !== 'signal-types') return f.suggestions ?? [];
    return this.signalTypeKeys();
  }

  /** Suggestions not already chosen — offering a duplicate is noise. */
  unusedSuggestions(f: Factor): string[] {
    const chosen = new Set(this.chips[f.key] ?? []);
    return (this.options(f) ?? []).filter((s) => !chosen.has(s));
  }

  /** What the empty first option should say, which depends on why it is empty. */
  optionsPlaceholder(f: Factor): string {
    if (this.signalTypesFailed()) return 'could not load signal types';
    if (this.signalTypeKeys() === null) return 'loading…';
    if (!this.unusedSuggestions(f).length) return 'every signal type is already listed';
    return 'choose a signal type…';
  }

  /** A stored value that no active signal type backs. */
  isOrphan(f: Factor, value: string): boolean {
    if (f.optionsFrom !== 'signal-types') return false;
    const known = this.signalTypeKeys();
    // Not known yet, or never arrived: judge nothing.
    if (known === null) return false;
    return !known.includes(value);
  }

  orphanCount(f: Factor): number {
    return (this.chips[f.key] ?? []).filter((v) => this.isOrphan(f, v)).length;
  }

  addChip(key: string): void {
    this.addChipFor(key, this.entry[key] ?? '');
  }

  /** The same add, given the value directly. Used by the input and by tests. */
  addChipFor(key: string, raw: string): void {
    const value = raw.trim();
    if (!value) return;
    const list = this.chips[key] ?? [];
    // Case-insensitive, because "SaaS" and "saas" reaching a prompt as two
    // separate facts is the spelling problem this editor exists to stop.
    if (!list.some((v) => v.toLowerCase() === value.toLowerCase())) {
      this.chips[key] = [...list, value];
    }
    this.entry[key] = '';
    this.emit();
  }

  removeChip(key: string, value: string): void {
    this.chips[key] = (this.chips[key] ?? []).filter((v) => v !== value);
    this.emit();
  }

  /** Is this band inside the range currently held? */
  isPreset(p: Band): boolean {
    if (this.rangeMin === null && this.rangeMax === null) return false;
    const low = this.rangeMin ?? 0;
    if (p.min < low) return false;
    // A range with no upper bound covers every band above its floor, including
    // the open-ended top band; a bounded range cannot cover that top band at
    // all, however high it reaches.
    if (this.rangeMax === null) return true;
    return p.max !== null && p.max <= this.rangeMax;
  }

  /**
   * Select bands, several at a time, as one span.
   *
   * The ICP stores a **single** min–max, so a selection is always contiguous —
   * `50-100` plus `500-1000` necessarily includes everything between them, and
   * there is no way to express "these two but not the middle". Rather than
   * pretend otherwise with checkboxes that cannot mean what they look like,
   * clicking extends or trims one span:
   *
   * * nothing selected — start at this band;
   * * the only selected band — clear back to "any";
   * * either end of the selection — trim that end;
   * * beyond the selection — extend out to reach it;
   * * inside the selection — collapse to this band alone, so an interior click
   *   does something rather than nothing.
   */
  applyPreset(p: Band): void {
    const i = this.presets.indexOf(p);
    const selected = this.presets
      .map((band, index) => (this.isPreset(band) ? index : -1))
      .filter((index) => index >= 0);

    let lo: number;
    let hi: number;
    if (!selected.length) {
      lo = hi = i;
    } else {
      const first = selected[0];
      const last = selected[selected.length - 1];
      if (first === last && i === first) {
        this.rangeMin = null;
        this.rangeMax = null;
        this.emit();
        return;
      }
      if (i === first) [lo, hi] = [first + 1, last];
      else if (i === last) [lo, hi] = [first, last - 1];
      else if (i < first) [lo, hi] = [i, last];
      else if (i > last) [lo, hi] = [first, i];
      else [lo, hi] = [i, i];
    }

    this.rangeMin = this.presets[lo].min;
    this.rangeMax = this.presets[hi].max;
    this.emit();
  }

  passthroughKeys(): string[] {
    return Object.keys(this.passthrough).sort();
  }

  preview(key: string): string {
    const text = JSON.stringify(this.passthrough[key]);
    return text.length > 80 ? `${text.slice(0, 80)}…` : text;
  }

  toggleRaw(): void {
    const next = !this.showRaw();
    if (next) this.raw = JSON.stringify(this.compose(), null, 2);
    this.showRaw.set(next);
    this.rawError.set(null);
  }

  /**
   * Editing the JSON re-hydrates the fields.
   *
   * Kept in step deliberately: two editors over one value that disagree is
   * worse than one bad editor, because whichever saves last silently wins.
   */
  onRawEdit(): void {
    let parsed: unknown;
    try {
      parsed = JSON.parse(this.raw || '{}');
    } catch (e) {
      this.rawError.set(`Not valid JSON — ${(e as Error).message}`);
      return;
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      this.rawError.set('The ICP must be a JSON object.');
      return;
    }
    this.rawError.set(null);
    this.hydrate(parsed as Record<string, unknown>, { keepRaw: true });
    this.valueChange.emit(this.compose());
  }

  emit(): void {
    const composed = this.compose();
    if (this.showRaw()) this.raw = JSON.stringify(composed, null, 2);
    this.valueChange.emit(composed);
  }

  /** Split an incoming ICP into fields this form owns and the rest. */
  private hydrate(icp: Record<string, unknown>, options: { keepRaw?: boolean } = {}): void {
    this.chips = {};
    this.texts = {};
    this.passthrough = {};
    this.personas = [];
    this.personaEntry = [];
    this.rangeMin = null;
    this.rangeMax = null;

    for (const [key, value] of Object.entries(icp)) {
      const factor = KNOWN.has(key) ? FACTORS.find((f) => f.key === key)! : null;

      // Only the `{buying_role, titles}` form is owned here. An older
      // definition's bare strings are still read by enrichment, so they are
      // carried through untouched rather than coerced into a role nobody chose.
      if (factor?.kind === 'personas' && isPersonaArray(value)) {
        this.personas = value.map((p) => ({ buying_role: p.buying_role, titles: [...p.titles] }));
        this.personaEntry = this.personas.map(() => '');
        continue;
      }

      // `sources` is a list of registry keys, stored and carried exactly like
      // a chips factor — it differs only in how it is chosen on screen.
      if ((factor?.kind === 'chips' || factor?.kind === 'sources') && isStringArray(value)) {
        this.chips[key] = [...value];
        continue;
      }
      if (factor?.kind === 'text' && typeof value === 'string') {
        this.texts[key] = value;
        continue;
      }
      if (factor?.kind === 'choice' && typeof value === 'string') {
        // A value outside the closed set falls through to passthrough rather
        // than being shown as selected — the form would otherwise display
        // "enterprize" as if it were one of the two, which is the confusion
        // the server-side validator exists to prevent.
        if ((factor.options || []).some((o) => o.key === value)) {
          this.texts[key] = value;
          continue;
        }
      }
      if (factor?.kind === 'range' && typeof value === 'string') {
        const band = parseBand(value);
        if (band) {
          this.rangeMin = band.min;
          this.rangeMax = band.max;
          continue;
        }
      }
      // A known key whose value is the wrong shape lands here too — coercing
      // it would quietly rewrite what a prompt says, and the JSON view can
      // still reach it.
      this.passthrough[key] = value;
    }

    if (!options.keepRaw) this.raw = JSON.stringify(icp, null, 2);
  }

  /** Rebuild the ICP. Empty factors are omitted, not written as blanks. */
  private compose(): Record<string, unknown> {
    const out: Record<string, unknown> = { ...this.passthrough };

    for (const factor of FACTORS) {
      if (factor.kind === 'chips' || factor.kind === 'sources') {
        const list = this.chips[factor.key] ?? [];
        // An empty array and an absent key read differently to a model: one
        // says "no industries qualify", the other says "industry is not a
        // constraint". Absent is what an empty control means.
        if (list.length) out[factor.key] = list;
      } else if (factor.kind === 'text' || factor.kind === 'choice') {
        // A cleared choice leaves the key absent, not present and empty. The
        // prompts read a missing track as "not established"; `""` would be a
        // third state nothing handles.
        const text = (this.texts[factor.key] ?? '').trim();
        if (text) out[factor.key] = text;
      } else if (factor.kind === 'range') {
        const band = formatBand(this.rangeMin, this.rangeMax);
        if (band) out[factor.key] = band;
      } else if (factor.kind === 'personas') {
        // A role with no titles matches nothing a CSV carries, so it is not
        // written; an empty section is omitted rather than saved as [].
        const rows = this.personas
          .filter((p) => p.titles.length)
          .map((p) => ({ buying_role: p.buying_role, titles: [...p.titles] }));
        if (rows.length) out[factor.key] = rows;
      }
    }
    return out;
  }
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === 'string');
}

const ROLE_KEYS = new Set(BUYING_ROLES.map((r) => r.key));

function isPersonaArray(value: unknown): value is Persona[] {
  return (
    Array.isArray(value) &&
    value.every(
      (p) =>
        typeof p === 'object' &&
        p !== null &&
        ROLE_KEYS.has((p as Persona).buying_role) &&
        isStringArray((p as Persona).titles),
    )
  );
}

/** `"50-500"` and `"5000+"` are both bands somebody may already have stored. */
function parseBand(value: string): { min: number | null; max: number | null } | null {
  const range = /^\s*(\d+)\s*-\s*(\d+)\s*$/.exec(value);
  if (range) return { min: Number(range[1]), max: Number(range[2]) };
  const open = /^\s*(\d+)\s*\+\s*$/.exec(value);
  if (open) return { min: Number(open[1]), max: null };
  return null;
}

function formatBand(min: number | null, max: number | null): string | null {
  const low = min === null || Number.isNaN(min) ? null : min;
  const high = max === null || Number.isNaN(max) ? null : max;
  if (low === null && high === null) return null;
  if (low !== null && high !== null) return `${low}-${high}`;
  if (low !== null) return `${low}+`;
  return `0-${high}`;
}
