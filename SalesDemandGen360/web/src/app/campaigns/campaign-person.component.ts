import { CommonModule } from '@angular/common';
import {
  Component,
  EventEmitter,
  HostListener,
  Input,
  OnChanges,
  Output,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ArcView, DraftVersion, PersonDetail, PipelineService, StrategyAngleView, TouchView } from '../core/pipeline.service';
import { apiError } from '../shared/api-error';
import {
  channelDisagrees,
  noSubjectReason,
  sendingChannel,
  slotWire,
} from '../shared/lgm-slot';
import { ConfirmService } from '../shared/confirm.service';
import { IconComponent } from '../shared/icon.component';
import { NotifyService } from '../shared/notify.service';

export type PersonSection = 'score' | 'strategy' | 'drafts';

const DECISION: Record<string, string> = {
  pursue: 'pursue',
  below_threshold: 'below threshold',
  over_limit: 'over the limit',
  not_reachable: 'not reachable',
};

const ORIGIN: Record<string, string> = {
  arc: 'written by AI',
  regeneration: 'rewritten by AI',
  rep_edit: 'edited by you',
};

/** The message inside a `{detail: {message}}` refusal, or a fallback. */
function refusal(err: unknown, fallback: string): string {
  const detail = (err as { error?: { detail?: { message?: string } | string } })?.error?.detail;
  if (detail && typeof detail === 'object' && detail.message) return detail.message;
  return apiError(err, fallback);
}

/**
 * One person in an outreach campaign — everything about approaching them, in one place.
 *
 * *Qualification* is the company's score read for the campaign's ICP (scored on
 * the company, never here). *Strategy* is the case argued for this person in this
 * campaign. *Cadence drafts* are the words for every touch of their cadence: write
 * them with AI, edit any touch (saved as a new version), then save for approval.
 */
@Component({
  selector: 'app-campaign-person',
  standalone: true,
  imports: [CommonModule, FormsModule, IconComponent],
  template: `
    <div class="pd-backdrop" (click)="closed.emit()"></div>
    <aside class="pd" role="dialog" [attr.aria-label]="detail()?.person?.full_name ?? 'Person'">
      <header class="pd-head">
        <div>
          <h3>{{ detail()?.person?.full_name ?? 'Loading…' }}</h3>
          <p class="row-sub" *ngIf="detail() as d">
            {{ d.person.title ?? '—' }} · {{ d.person.account_name }} · for {{ d.service_code }} · ICP {{ d.icp_name }}
          </p>
        </div>
        <button class="act-btn" (click)="closed.emit()" aria-label="Close" title="Close">
          <app-icon name="x" [size]="16" />
        </button>
      </header>

      <nav class="pd-tabs">
        <button *ngFor="let s of sections" type="button" [class.on]="section === s.key" (click)="section = s.key">
          {{ s.label }}
        </button>
      </nav>

      <p class="row-sub pd-err" *ngIf="failed()">{{ failed() }}</p>

      <!-- qualification: the company's, read for this ICP -->
      <section *ngIf="section === 'score' && detail() as d">
        <ng-container *ngIf="d.score as s; else noScore">
          <div class="pd-score">
            <strong>{{ s.priority_score | number: '1.0-0' }}</strong>
            <span class="badge" [ngClass]="bandClass(s.priority_band)">{{ s.priority_band }}</span>
            <span class="row-sub">for {{ s.icp_name }} v{{ s.icp_version }} · scoring config v{{ s.scoring_config_version }}</span>
          </div>
          <p class="row-sub">
            The company is qualified once; fit and buyer are recomputed for this campaign's ICP and the
            roll-up is arithmetic — no AI call.
          </p>
          <div class="pd-dim" *ngFor="let dim of s.dimensions">
            <div class="pd-dim-h"><strong>{{ dim.dimension }}</strong><span class="mono">{{ dim.score }}</span></div>
            <p class="row-sub">{{ dim.reason }}</p>
          </div>
        </ng-container>
        <ng-template #noScore>
          <p class="row-sub">
            Not qualified yet. Qualify the company from its list — the score is the company's, read here
            for this campaign's ICP.
          </p>
        </ng-template>
      </section>

      <!-- strategy -->
      <section *ngIf="section === 'strategy' && detail() as d">
        <!-- Same bar as the drafts tab, one tab across: state, context, then
             what you can do about it. This tab used to end at "build it on the
             Strategy tab", which named the place and gave you nothing. -->
        <div class="pd-bar">
          <span class="badge" [ngClass]="d.strategy ? 'badge-accent' : 'badge-neutral'">
            {{ d.strategy ? d.strategy.thread_status.replace('_', ' ') : 'no strategy' }}
          </span>
          <span class="row-sub">{{ decision(d.person.default_decision) }} · weight {{ d.person.weight }}</span>
          <span class="spacer"></span>
          <button class="btn" [class.btn-primary]="!d.strategy" (click)="buildStrategy(d)"
                  [class.busy]="busy() === 'strategy'"
                  [disabled]="!!busy() || !canBuild(d)"
                  [title]="whyNotBuild(d) ?? ''">
            {{ busy() === 'strategy' ? 'Building…' : (d.strategy ? 'Rebuild strategy' : 'Build strategy') }}
          </button>
        </div>

        <!-- Overrides are governance, not convenience: they are recorded
             against the campaign and read back at approval. The drawer offers
             exactly what the Strategy tab offers, and no quieter route. -->
        <label class="ovr" *ngIf="needsPursue(d)">
          <input type="checkbox" [(ngModel)]="pursueAnyway"
                 [attr.aria-label]="'Pursue ' + d.person.full_name + ' anyway'">
          pursue anyway — {{ d.person.decision_detail }}
        </label>
        <label class="ovr" *ngIf="needsSignal(d)">
          <input type="checkbox" [(ngModel)]="allowWithoutSignal"
                 [attr.aria-label]="'Build for ' + d.person.full_name + ' without a live signal'">
          allow without a live signal — nothing live to date the copy to
        </label>
        <p class="row-sub" *ngIf="needsPursue(d) || needsSignal(d)">
          Recorded against the campaign and shown again at approval.
        </p>
        <p class="row-sub" *ngIf="withdrawn(d)">
          Withdrawn from this campaign<span *ngIf="d.person.withdraw_reason"> — {{ d.person.withdraw_reason }}</span>.
          Their drafts are kept; reinstate them on the Threads tab to argue a case again.
        </p>
        <p class="row-sub" *ngIf="frozen(d)">
          Frozen at enrolment — La Growth Machine holds the copy. Stop the sequence to change the
          approach.
        </p>

        <p class="row-sub">
          By the sales rules: <strong>{{ decision(d.person.default_decision) }}</strong> — {{ d.person.decision_detail }}
        </p>
        <ng-container *ngIf="d.strategy as st; else noStrategy">
          <p class="pd-flags">
            <span class="badge badge-warn" *ngIf="st.chosen_by_rep">pursued by your choice</span>
            <span class="badge badge-warn" *ngIf="st.without_live_trigger">pitched without a live signal</span>
            <span class="badge badge-neutral">{{ st.thread_status.replace('_', ' ') }} · starts day {{ st.start_offset_days }}</span>
          </p>
          <p class="pd-account" *ngIf="d.account_angle">
            <span class="k">The read on {{ d.person.account_name }}</span> {{ d.account_angle }}
          </p>

          <!-- Ranked ways in (docs/18). The app pitches the top-ranked angle;
               a rep can pitch another. Drafting writes from whichever is
               selected, so picking one re-opens saved drafts. -->
          <h4>Angles <span class="row-sub">ranked — drafting writes from the one being pitched</span></h4>
          <p class="row-sub" *ngIf="whyOrder(d) as why">Why this order: {{ why }}</p>
          <div class="pd-angle" *ngFor="let a of d.angles" [class.on]="a.is_selected">
            <div class="pd-angle-head">
              <span class="badge" [ngClass]="a.is_selected ? 'badge-accent' : 'badge-neutral'">
                {{ a.is_selected ? 'Pitching' : (a.rank === 1 ? 'Recommended' : 'Alternative') }}
              </span>
              <strong>{{ a.angle }}</strong>
              <span class="spacer"></span>
              <span class="row-sub" *ngIf="a.is_selected">
                {{ a.selected_by === 'rep' ? 'picked by a rep' : 'top-ranked, picked automatically' }}
              </span>
              <button class="btn" *ngIf="!a.is_selected" (click)="pickAngle(d, a)"
                      [class.busy]="busy() === 'angle-' + a.id" [disabled]="!!busy() || frozen(d)"
                      [title]="frozen(d) ? 'Frozen at enrolment' : 'Pitch this angle instead'">
                {{ busy() === 'angle-' + a.id ? 'Switching…' : 'Pitch this angle' }}
              </button>
            </div>
            <p class="row-sub">
              #{{ a.rank }}<span *ngIf="a.confidence != null"> · confidence {{ a.confidence }}</span>
              · {{ a.signals_cited }} signal{{ a.signals_cited === 1 ? '' : 's' }} cited
              <span *ngIf="a.proof.length"> · proof: {{ a.proof.join(', ') }}</span>
            </p>
            <ng-container *ngIf="a.is_selected; else brief">
              <h5>Problem <span class="row-sub">(our hypothesis)</span></h5>
              <p>{{ a.problem_hypothesis }}</p>
              <h5>Why now</h5>
              <p>{{ a.why_now }}</p>
              <ul class="pd-signals" *ngIf="d.trigger_signals.length">
                <li *ngFor="let sg of d.trigger_signals" class="row-sub">
                  {{ sg.summary }}<span *ngIf="sg.expires_at"> · live until {{ sg.expires_at | date: 'MMM d, y' }}</span>
                </li>
              </ul>
              <h5>Positioning</h5>
              <p>{{ a.positioning }}</p>
              <h5>Ask</h5>
              <p>{{ a.cta }}</p>
              <p class="row-sub" *ngIf="a.avoid.length">Avoid: {{ a.avoid.join('; ') }}</p>
            </ng-container>
            <ng-template #brief><p class="row-sub">{{ a.problem_hypothesis }}</p></ng-template>
          </div>
          <p class="row-sub" *ngIf="d.versions.length > 1">
            Versions:
            <span *ngFor="let v of d.versions; let last = last">v{{ v.version }} {{ v.status }}{{ v.argued_for_this_person ? '' : ' (not argued for them)' }}{{ last ? '' : ' · ' }}</span>
          </p>
        </ng-container>
        <ng-template #noStrategy>
          <p class="row-sub">
            No strategy yet. One AI call argues the case for everyone from
            {{ d.person.account_name }} in this campaign — the problem, the trigger it is dated to,
            the positioning and the ask.
          </p>
        </ng-template>
      </section>

      <!-- cadence drafts -->
      <section *ngIf="section === 'drafts'">
        <ng-container *ngIf="arc() as a">
          <div class="pd-bar">
            <span class="badge" [ngClass]="stateClass(a.state)">{{ a.state_label }}</span>
            <span class="row-sub" *ngIf="a.cadence_label">
              {{ a.cadence_label }} · {{ a.cadence_touches }} touches over {{ a.cadence_days }} days
            </span>
            <span class="spacer"></span>
            <button class="btn" (click)="write(a)" [class.busy]="busy() === 'write'"
                    [disabled]="!!busy() || editing() !== null || !a.has_strategy || a.state === 'enrolled'">
              {{ a.touches.length ? 'Rewrite with AI' : 'Write drafts' }}
            </button>
            <button class="btn btn-primary" (click)="save(a)" [class.busy]="busy() === 'save'"
                    [disabled]="!!busy() || editing() !== null || a.state !== 'drafted'">
              Save for approval
            </button>
          </div>
          <p class="row-sub" *ngIf="!a.has_strategy">Build this person's strategy first — drafts are written from it.</p>
          <p class="row-sub" *ngIf="a.has_strategy && !a.touches.length">
            Not drafted yet. One AI call writes every touch of the cadence from the strategy.
          </p>
          <p class="row-sub" *ngIf="a.state === 'saved'">Saved for approval. Editing a touch takes it back to drafting.</p>
          <p class="row-sub" *ngIf="a.state === 'approved'">Approved. Editing a touch sends this person back for approval.</p>
          <p class="row-sub" *ngIf="a.state === 'enrolled'">Enrolled — LGM holds the words, so they can no longer change.</p>
          <p class="row-sub" *ngIf="a.attribute_budget">
            {{ a.attributes_used }} of {{ a.attribute_budget }} attributes used on this lead ·
            read from {{ a.cadence_label }}'s templates
          </p>

          <div class="pd-touch" *ngFor="let t of a.touches">
            <div class="pd-touch-h">
              <span class="mono">{{ t.step_no }}{{ t.day_offset === null ? '' : ' · day ' + t.day_offset }}</span><span class="row-sub" *ngIf="t.day_offset === null"> · scheduled in LGM</span>
              <!-- LGM's channel, not the one the model proposed: it is the
                   one that decides what sends. -->
              <span class="badge badge-neutral">{{ sends(t) }}</span>
              <span class="badge badge-warn" *ngIf="disagrees(t)"
                    [title]="'Drafted as ' + t.channel.replace('_', ' ') + ', but LGM sends this step as ' + sends(t)">
                drafted as {{ t.channel.replace('_', ' ') }}
              </span>
              <span class="badge badge-accent" *ngIf="t.generated_as === 'rep_edit'">edited by you</span>
              <span class="row-sub" *ngIf="t.lgm_position">
                LGM position {{ t.lgm_position }}<span *ngIf="t.lgm_step_name"> · {{ t.lgm_step_name }}</span>
              </span>
              <span class="row-sub">v{{ t.version }}</span>
              <span class="spacer"></span>
              <button class="btn btn-sm" *ngIf="editing() !== t.step_no && a.state !== 'enrolled'"
                      (click)="startEdit(t)" [disabled]="editing() !== null || !!busy()">Edit</button>
              <button class="btn btn-sm" (click)="toggleVersions(t.step_no)">
                {{ versionsOf() === t.step_no ? 'Hide versions' : 'Versions' }}
              </button>
            </div>
            <p class="row-sub" *ngIf="t.purpose">{{ t.purpose }}</p>
            <ng-container *ngIf="editing() !== t.step_no">
              <!-- Where each piece of content actually lands. Without this the
                   binding is invisible: a rep cannot tell which attribute a
                   body occupies, nor that a subject they wrote will never
                   appear because the step has nowhere to put it. -->
              <div class="attr-slot" *ngIf="t.subject_allowed || t.subject">
                <span class="slot-id" *ngIf="t.subject_attribute">{{ wire(t.subject_attribute) }}</span>
                <span class="slot-id none" *ngIf="!t.subject_attribute">no subject</span>
                <span class="slot-name">{{ t.subject_attribute_label || noSubject(t) }}</span>
              </div>
              <!-- Shown struck through where it cannot send: the words are
                   still on the draft, and pretending they are a subject line
                   is how an approved arc and the sent message differ. -->
              <strong *ngIf="t.subject" class="pd-subject"
                      [class.dead]="!t.subject_allowed">{{ t.subject }}</strong>
              <span class="row-sub" *ngIf="t.subject && !t.subject_allowed">
                will not send — this step has nowhere to put it
              </span>

              <div class="attr-slot" *ngIf="t.lgm_attribute">
                <span class="slot-id">{{ wire(t.lgm_attribute) }}</span>
                <span class="slot-name">{{ t.lgm_attribute_label }}</span>
              </div>
              <p class="pd-body">{{ t.body }}</p>
            </ng-container>
            <div *ngIf="editing() === t.step_no" class="pd-edit">
              <!-- Offered only where LGM's step template names an attribute
                   for it. Anywhere else the words are not a worse subject,
                   they are a subject nobody would ever see. -->
              <input *ngIf="t.subject_allowed" class="field" [(ngModel)]="draftSubject"
                     [placeholder]="'Subject — written into ' + wire(t.subject_attribute)"
                     aria-label="Subject">
              <p class="row-sub" *ngIf="!t.subject_allowed">
                {{ noSubject(t) }} — a subject written here would not appear. Add a
                <code>{{ placeholder }}</code> to that step's subject in LGM to change that.
              </p>
              <textarea class="field" rows="8" [(ngModel)]="draftBody" aria-label="Body"></textarea>
              <div class="pd-edit-f">
                <button class="btn btn-primary" (click)="saveTouch(t.step_no)" [class.busy]="busy() === 'touch'"
                        [disabled]="!draftBody.trim() || !!busy()">Save touch</button>
                <button class="btn" (click)="editing.set(null)" [disabled]="!!busy()">Cancel</button>
                <span class="row-sub">Saved as a new version — earlier words stay in the history.</span>
              </div>
            </div>
            <div class="pd-versions" *ngIf="versionsOf() === t.step_no">
              <div *ngFor="let v of versions()" class="pd-version">
                <span class="row-sub">
                  v{{ v.version }} · {{ origin(v.generated_as) }}<span *ngIf="v.created_at"> · {{ v.created_at | date: 'MMM d, h:mm a' }}</span>{{ v.is_current ? ' · current' : '' }}
                </span>
                <strong *ngIf="v.subject" class="pd-subject">{{ v.subject }}</strong>
                <p class="pd-body">{{ v.body }}</p>
              </div>
            </div>
          </div>
        </ng-container>
      </section>
    </aside>
  `,
  styles: [`
    .pd-account { background: var(--surface-2); border-radius: 8px; padding: 8px 10px; font-size: .85rem; margin: 6px 0 12px; }
    .k { font-family: 'IBM Plex Mono', monospace; font-size: .6rem; letter-spacing: .08em; text-transform: uppercase; color: var(--faint); margin-right: 6px; }
    .pd-angle { border: 1px solid var(--border); border-radius: 9px; padding: 9px 11px; margin: 8px 0; }
    .pd-angle.on { border-color: var(--accent); background: var(--accent-soft); }
    .pd-angle-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .pd-angle-head .spacer { flex: 1; }
    .pd-angle h5 { font-size: .8rem; margin: 10px 0 2px; }
    .pd-angle p { margin: 2px 0; }
  `],
})
export class CampaignPersonComponent implements OnChanges {
  @Input({ required: true }) campaignId = '';
  @Input({ required: true }) contactId = '';
  @Input({ required: true }) sequenceId = '';
  @Input() section: PersonSection = 'strategy';
  @Output() closed = new EventEmitter<void>();
  /** Drafts were written, edited or saved — the tabs behind reload. */
  @Output() changed = new EventEmitter<void>();

  private api = inject(PipelineService);
  private notify = inject(NotifyService);
  private confirm = inject(ConfirmService);

  readonly sections: { key: PersonSection; label: string }[] = [
    { key: 'score', label: 'Qualification' },
    { key: 'strategy', label: 'Strategy' },
    { key: 'drafts', label: 'Cadence drafts' },
  ];

  detail = signal<PersonDetail | null>(null);
  arc = signal<ArcView | null>(null);
  failed = signal<string | null>(null);
  busy = signal<string | null>(null);
  editing = signal<number | null>(null);
  versionsOf = signal<number | null>(null);
  versions = signal<DraftVersion[]>([]);
  draftSubject = '';
  draftBody = '';

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.editing() === null) this.closed.emit();
  }

  ngOnChanges(): void {
    this.editing.set(null);
    this.versionsOf.set(null);
    this.load();
  }

  load(): void {
    if (!this.campaignId || !this.contactId) return;
    this.api.personDetail(this.campaignId, this.contactId).subscribe({
      next: (d) => this.detail.set(d),
      error: (err) => this.failed.set(apiError(err, 'Could not load this person.')),
    });
    this.loadArc();
  }

  private loadArc(): void {
    this.api.arc(this.sequenceId).subscribe({
      next: (a) => this.arc.set(a),
      error: (err) => this.failed.set(apiError(err, 'Could not load the cadence drafts.')),
    });
  }

  /** Angular would read a literal `{{…}}` in the template as interpolation. */
  readonly placeholder = '{{customAttributeN}}';
  /** LGM's spelling of a slot, and why a step has no subject of ours. */
  readonly wire = slotWire;
  readonly noSubject = noSubjectReason;
  readonly sends = sendingChannel;
  readonly disagrees = channelDisagrees;

  decision(key: string): string {
    return DECISION[key] ?? key;
  }

  /** The model's reason for the order, carried on the top-ranked angle. */
  whyOrder(d: PersonDetail): string | null {
    return d.angles.find((a) => a.rank === 1)?.why_this_order ?? null;
  }

  /** Pitch a different angle. Saved drafts argued the old one and re-open. */
  pickAngle(d: PersonDetail, a: StrategyAngleView): void {
    this.busy.set('angle-' + a.id);
    this.api.selectAngle(this.campaignId, this.contactId, a.id).subscribe({
      next: (r) => {
        this.busy.set(null);
        this.load();
        this.changed.emit();
        this.notify.success(
          `Pitching “${a.angle}” to ${d.person.full_name}.`,
          r.drafts_need_rewriting
            ? 'Their drafts argued the previous angle — rewrite them on the Cadence drafts tab.'
            : 'Drafting will write from this angle.',
        );
      },
      error: (err) => {
        this.busy.set(null);
        this.notify.error('The angle was not changed.', apiError(err, 'The server refused.'));
      },
    });
  }

  // --- building the strategy from here ---------------------------------
  //
  // The same call the Strategy tab makes, scoped to this person's company:
  // one AI call argues for everyone from it in this campaign, so the drawer
  // cannot produce a different answer from the table.
  pursueAnyway = false;
  allowWithoutSignal = false;

  /** Enrolled means LGM holds the copy; the approach is settled. */
  frozen(d: PersonDetail): boolean {
    return ['enrolled', 'executing', 'stopped', 'completed'].some((s) =>
      (d.person.draft_state ?? '').startsWith(s),
    );
  }

  /** Out of this campaign. Not something an override on this tab can undo. */
  withdrawn(d: PersonDetail): boolean {
    return !!d.person.withdrawn;
  }

  needsPursue(d: PersonDetail): boolean {
    return (
      !this.frozen(d) && !this.withdrawn(d) &&
      d.person.default_decision !== 'pursue' && !d.person.chosen_by_rep
    );
  }

  needsSignal(d: PersonDetail): boolean {
    return (
      !this.frozen(d) && !this.withdrawn(d) &&
      d.person.live_signals === 0 && !d.person.without_live_trigger
    );
  }

  /** Why the button is disabled, for its tooltip — never a silent refusal. */
  whyNotBuild(d: PersonDetail): string | null {
    if (this.withdrawn(d)) {
      const why = d.person.withdraw_reason;
      return `Withdrawn from this campaign${why ? ' — ' + why : ''}. Reinstate them on the Threads tab`;
    }
    if (this.frozen(d)) return 'Frozen at enrolment — stop the sequence first';
    if (this.needsPursue(d) && !this.pursueAnyway) {
      return `${d.person.decision_detail} — tick "pursue anyway" to override`;
    }
    if (this.needsSignal(d) && !this.allowWithoutSignal) {
      return 'No live signal to date the copy to — tick "allow without a live signal"';
    }
    return null;
  }

  canBuild(d: PersonDetail): boolean {
    return this.whyNotBuild(d) === null;
  }

  buildStrategy(d: PersonDetail): void {
    if (!this.canBuild(d)) return;
    // No confirmation: whoever opened one person's drawer and pressed this
    // has already chosen them. The cost is said plainly next to the button.
    this.busy.set('strategy');
    this.failed.set(null);
    const contact = [d.person.contact_id];
    this.api
      .buildCampaignStrategy(this.campaignId, {
        account_id: d.person.account_id,
        pursue_anyway: this.needsPursue(d) && this.pursueAnyway ? contact : [],
        allow_without_signal: this.needsSignal(d) && this.allowWithoutSignal ? contact : [],
      })
      .subscribe({
        next: (r) => {
          this.busy.set(null);
          this.pursueAnyway = false;
          this.allowWithoutSignal = false;
          if (!r.built) {
            // Not an error: the rules excluded them, and the reason is the
            // useful part.
            this.notify.warning(
              `No strategy was built for ${d.person.full_name}.`,
              r.note || (r.excluded ?? []).join('; ') || 'The rules left them out.',
            );
          } else {
            this.notify.success(
              `Strategy v${r.version} built for ${(r.pursued ?? []).join(', ') || d.person.full_name}.`,
              'Cadence drafts are written from it.',
            );
          }
          // Stays on this tab: the case that was argued is what you came to
          // read, and drafting from it is the next decision, not this one.
          this.load();
          this.changed.emit();
        },
        error: (err) => {
          this.busy.set(null);
          this.failed.set(refusal(err, 'Could not build the strategy.'));
        },
      });
  }

  origin(key: string): string {
    return ORIGIN[key] ?? key;
  }

  bandClass(band: string): string {
    return band === 'high' ? 'badge-good' : band === 'medium' ? 'badge-accent' : 'badge-neutral';
  }

  stateClass(state: string): string {
    if (state === 'approved' || state === 'enrolled') return 'badge-good';
    if (state === 'saved') return 'badge-accent';
    return 'badge-warn';
  }

  private name(): string {
    return this.detail()?.person.full_name ?? 'this person';
  }

  async write(a: ArcView): Promise<void> {
    if (a.touches.length) {
      const ok = await this.confirm.ask({
        title: `Rewrite ${this.name()}'s cadence with AI?`,
        body:
          'One AI call rewrites every touch from the strategy. Each touch gets a new version — your edits ' +
          'stay in its history. A saved or approved cadence goes back to drafting.',
        confirmLabel: 'Rewrite',
      });
      if (!ok) return;
    }
    this.busy.set('write');
    this.api.writeDrafts(this.sequenceId).subscribe({
      next: (arc) => {
        this.busy.set(null);
        this.arc.set(arc);
        this.notify.success(`Drafted ${arc.touches.length} touches for ${this.name()}.`);
        this.changed.emit();
      },
      error: (err) => {
        this.busy.set(null);
        this.notify.error(`Could not draft ${this.name()}'s cadence.`, refusal(err, 'The server refused.'));
      },
    });
  }

  save(a: ArcView): void {
    this.busy.set('save');
    this.api.saveDrafts(a.sequence_id).subscribe({
      next: (arc) => {
        this.busy.set(null);
        this.arc.set(arc);
        this.notify.success(`Saved ${this.name()}'s cadence for approval.`);
        this.changed.emit();
      },
      error: (err) => {
        this.busy.set(null);
        this.notify.error(`Could not save ${this.name()} for approval.`, refusal(err, 'The server refused.'));
      },
    });
  }

  startEdit(t: TouchView): void {
    this.draftSubject = t.subject ?? '';
    this.draftBody = t.body;
    this.editing.set(t.step_no);
  }

  saveTouch(step: number): void {
    this.busy.set('touch');
    this.api
      .editTouch(this.sequenceId, step, { subject: this.draftSubject.trim() || null, body: this.draftBody })
      .subscribe({
        next: (arc) => {
          this.busy.set(null);
          this.editing.set(null);
          this.arc.set(arc);
          this.notify.success(`Saved touch ${step} for ${this.name()} — save the cadence for approval when ready.`);
          if (this.versionsOf() === step) this.loadVersions(step);
          this.changed.emit();
        },
        error: (err) => {
          this.busy.set(null);
          this.notify.error(`Could not save touch ${step}.`, refusal(err, 'The server refused.'));
        },
      });
  }

  toggleVersions(step: number): void {
    if (this.versionsOf() === step) {
      this.versionsOf.set(null);
      return;
    }
    this.versionsOf.set(step);
    this.loadVersions(step);
  }

  private loadVersions(step: number): void {
    this.versions.set([]);
    this.api.touchVersions(this.sequenceId, step).subscribe({
      next: (v) => this.versions.set(v),
      error: (err) => this.notify.error('Could not load the versions.', apiError(err, 'The server did not answer.')),
    });
  }
}
