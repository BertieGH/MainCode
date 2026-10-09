import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Output, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApolloBuild, ApolloBuildIn, ListsService } from '../core/lists.service';
import { IconComponent } from '../shared/icon.component';
import { apiError } from '../shared/api-error';

/**
 * Build a list from the Apollo contacts this account already owns.
 *
 * **Nothing here spends a credit.** `contacts/search` reads people already
 * paid for — 356,830 on this account, 250,354 with a verified email — and
 * reading them is free however often. That is why the preview recounts on
 * every change rather than hiding behind a button: a free count should be
 * shown, not rationed.
 *
 * It is a separate route from the Suggested tab on purpose. A suggestion is a
 * proposal to spend a credit; these people are already bought, so proposing
 * them for reveal would be theatre. They arrive complete — email, title,
 * LinkedIn — and the list is reachable the moment it exists.
 */
@Component({
  selector: 'app-apollo-builder',
  standalone: true,
  imports: [CommonModule, FormsModule, IconComponent],
  template: `
    <div class="card">
      <div class="sec-head">
        <div style="flex:1;min-width:0;">
          <h3>Build from your Apollo contacts</h3>
          <p class="row-sub">
            People this account has already paid for. Nothing is written, and nothing is
            charged, until you press Create.
          </p>
        </div>
        <span class="badge badge-good">0 credits</span>
      </div>

      <div class="grid">
        <div class="f">
          <label for="ab-size">Company size</label>
          <div class="chips" id="ab-size">
            <button type="button" class="chip" *ngFor="let b of bands"
                    [class.on]="draft.size_bands.includes(b)" (click)="toggleBand(b)">{{ b }}</button>
          </div>
          <!-- Said out loud because we cannot check it: contacts/search does
               not return the employee count on the row. -->
          <p class="row-sub hint">Apollo's own band. It is not on the contact row, so it
            cannot be re-checked here.</p>
        </div>

        <div class="f">
          <label for="ab-persona">Personas · from the ICP</label>
          <div class="chips" id="ab-persona">
            <button type="button" class="chip" *ngFor="let p of personas"
                    [class.on]="draft.personas.includes(p)" (click)="togglePersona(p)">{{ p }}</button>
          </div>
          <p class="row-sub hint">
            A company must field every persona picked, or it is skipped — a list quietly
            missing the persona it was built for looks complete and is not.
          </p>
        </div>

        <div class="f wide">
          <label for="ab-industry">Industry</label>
          <div class="chips" id="ab-industry">
            <button type="button" class="chip" *ngFor="let i of shownIndustries()"
                    [class.on]="draft.industries.includes(i)" (click)="toggleIndustry(i)">
              {{ shortIndustry(i) }}
            </button>
            <button type="button" class="chip more"
                    *ngIf="industries().length > 8"
                    (click)="showAllIndustries.set(!showAllIndustries())">
              {{ showAllIndustries() ? 'fewer' : '+ ' + (industries().length - 8) + ' more' }}
            </button>
          </div>
          <p class="row-sub hint">
            None selected means every industry. Ordered by what this account actually holds —
            IT services is 43,896 of them, and an alphabetical list would bury it.
          </p>
        </div>

        <div class="f">
          <label for="ab-per">Contacts per company</label>
          <input id="ab-per" class="field short" type="number" min="1" max="5"
                 [(ngModel)]="draft.per_company" (ngModelChange)="recount()">
          <p class="row-sub hint">
            One of each persona first; any slot beyond that goes to the next most senior.
          </p>
        </div>

        <div class="f">
          <label for="ab-limit">How many contacts</label>
          <input id="ab-limit" class="field short" type="number" min="1" max="500"
                 [(ngModel)]="draft.limit" (ngModelChange)="recount()">
          <p class="row-sub hint" *ngIf="result() as r">
            <ng-container *ngIf="r.funnel?.available as avail">
              {{ avail }} available on these filters<span *ngIf="avail < draft.limit">
                — asking for more will give you {{ avail }}</span>.
            </ng-container>
          </p>
        </div>

        <div class="f">
          <label for="ab-verified">Email</label>
          <label class="check" for="ab-verified">
            <input id="ab-verified" type="checkbox" [(ngModel)]="draft.verified_only"
                   (ngModelChange)="recount()">
            verified only
          </label>
          <p class="row-sub hint">Only <span class="mono">verified</span> passes the send gate,
            so anything else is a contact nobody may write to.</p>
        </div>

        <div class="f">
          <label for="ab-label">New list name</label>
          <!-- A real value, not a placeholder: it tracks the filters until
               the moment it is typed in, and then it is yours. -->
          <input id="ab-label" class="field" type="text" [(ngModel)]="label"
                 (ngModelChange)="labelTyped()" placeholder="Name this list">
        </div>
      </div>

      <!-- the funnel — free, so it is always on screen -->
      <div class="funnel" *ngIf="shown() as r">
        <ng-container *ngIf="r.ran && r.funnel as f">
          <div class="fr" *ngFor="let step of steps(deep()?.funnel || f)">
            <span class="what">{{ step.label }}</span>
            <span class="bar"><span class="fill" [style.width.%]="step.pct"></span></span>
            <span class="n mono">{{ step.n | number }}</span>
          </div>
          <div class="fr final">
            <span class="what">Companies with every persona</span>
            <span class="bar"><span class="fill"
                  [style.width.%]="deep() ? pct(deep()!.funnel.usable_companies, deep()!.funnel.companies) : 0"></span></span>
            <span class="n mono">
              {{ deep() ? (deep()!.funnel.usable_companies | number) : '—' }}
            </span>
          </div>
          <p class="row-sub" style="margin:10px 0 0;">
            {{ deep()?.note || r.note }}
          </p>
        </ng-container>
      </div>
      <p class="row-sub counting" *ngIf="counting() || checking()">
        <span class="spin" aria-hidden="true"></span>
        {{ checking()
           ? 'Reading the pages to count whole companies — free, but about a minute…'
           : 'Counting — free, no credits…' }}
      </p>
      <p class="row-sub err" *ngIf="error() || refusal()">{{ error() || refusal() }}</p>

      <div class="acts">
        <button class="btn btn-primary" (click)="build()"
                [disabled]="!canBuild() || !!working()">
          <app-icon *ngIf="!working()" name="check" [size]="13" />
          {{ working() === 'build' ? 'Building…' : 'Create the list' }}
        </button>
        <!-- The slow count, asked for rather than imposed. The coarse funnel
             above is four queries; this one reads the pages behind them. -->
        <button class="btn" (click)="check()" [disabled]="!!working() || checking() || counting()">
          {{ checking() ? 'Checking…' : deep() ? 'Check again' : 'Check availability' }}
        </button>
        <button class="btn" (click)="cancelled.emit()">Cancel</button>
        <span class="row-sub" *ngIf="canBuild()">
          up to {{ willTake() }} contacts · 0 credits
        </span>
      </div>

      <!-- Preview rows carry no name and no address: the question is whether
           this is the right shape of list, which needs neither. -->
      <details class="peek" *ngIf="deep()?.sample?.length">
        <summary>Show the first {{ deep()!.sample.length }}</summary>
        <div class="table-wrap">
          <table class="data">
            <thead><tr><th>Company</th><th>Domain</th><th>Title</th><th>Persona</th></tr></thead>
            <tbody>
              <tr *ngFor="let s of deep()!.sample">
                <td>{{ s.company }}</td>
                <td class="mono row-sub">{{ s.domain }}</td>
                <td>{{ s.title }}</td>
                <td>
                  <span class="badge"
                        [ngClass]="s.persona === 'technical buyer' ? 'badge-warn' : 'badge-accent'">
                    {{ s.persona }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
    </div>
  `,
  styles: [
    `
      .sec-head { display: flex; gap: 14px; align-items: center; padding-bottom: 12px;
                  border-bottom: 1px solid var(--line); margin-bottom: 16px; }
      .sec-head h3 { font-size: 1rem; margin: 0 0 2px; }
      .sec-head .badge { flex: none; }
      .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
              gap: 18px 26px; }
      .f.wide { grid-column: 1 / -1; }
      .chip.more { background: none; border-style: dashed; color: var(--muted); }
      .f > label { display: block; font-size: .68rem; letter-spacing: .07em; font-weight: 600;
                   text-transform: uppercase; color: var(--faint); margin-bottom: 7px; }
      .hint { margin: 7px 0 0; max-width: 46ch; }
      .chips { display: flex; flex-wrap: wrap; gap: 6px; }
      .chip { font: inherit; font-size: .78rem; padding: 5px 11px; border-radius: 20px;
              cursor: pointer; background: var(--surface-2); border: 1px solid var(--line);
              color: var(--text); }
      .chip.on { background: var(--accent-soft); border-color: transparent; color: var(--accent);
                 font-weight: 500; }
      .field.short { max-width: 9ch; }
      .check { display: flex; align-items: center; gap: 8px; font-size: .84rem; cursor: pointer; }
      .funnel { background: var(--surface-2); border-radius: 10px; padding: 14px 16px;
                margin-top: 18px; }
      .fr { display: flex; align-items: center; gap: 12px; padding: 5px 0; font-size: .82rem; }
      .fr .what { min-width: 24ch; }
      .fr .bar { flex: 1; height: 6px; border-radius: 3px; background: var(--line);
                 overflow: hidden; }
      .fr .fill { height: 100%; background: var(--accent); transition: width .3s ease; }
      .fr .n { min-width: 8ch; text-align: right; font-size: .78rem; }
      .fr.final { border-top: 1px solid var(--line); margin-top: 6px; padding-top: 10px;
                  font-weight: 600; }
      .acts { display: flex; gap: 10px; align-items: center; margin-top: 18px; flex-wrap: wrap; }
      .counting { margin-top: 12px; display: flex; align-items: center; gap: 8px; }
      .spin { width: 11px; height: 11px; border-radius: 50%; border: 2px solid var(--line);
              border-top-color: var(--accent); animation: ab-spin .8s linear infinite; }
      @keyframes ab-spin { to { transform: rotate(360deg); } }
      @media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
      .err { color: var(--critical); margin-top: 12px; }
      .peek { margin-top: 16px; }
      .peek > summary { cursor: pointer; font-size: .82rem; margin-bottom: 10px; }
    `,
  ],
})
export class ApolloBuilderComponent {
  private api = inject(ListsService);

  @Output() built = new EventEmitter<string>();
  @Output() cancelled = new EventEmitter<void>();

  readonly bands = ['1-10', '11-50', '51-200', '201-500', '501-1000', '1001+'];
  readonly personas = ['economic buyer', 'technical buyer'];

  label = '';
  /** Once the name has been typed in, the suggestion stops overwriting it.
   *  A field that rewrites itself under the cursor is worse than no help. */
  private labelEdited = false;
  industries = signal<string[]>([]);
  showAllIndustries = signal(false);
  draft: ApolloBuildIn = {
    size_bands: ['51-200'],
    industries: [],
    personas: ['economic buyer', 'technical buyer'],
    verified_only: true,
    per_company: 2,
    limit: 100,
  };

  result = signal<ApolloBuild | null>(null);
  /** The deep read's answer, kept apart from the coarse funnel: it goes stale
   *  the moment a filter changes, and showing a stale pair count beside fresh
   *  coarse numbers would be worse than showing none. */
  deep = signal<ApolloBuild | null>(null);
  counting = signal(false);
  checking = signal(false);
  working = signal<'build' | null>(null);
  error = signal<string | null>(null);

  private timer: ReturnType<typeof setTimeout> | null = null;

  ngOnInit(): void {
    this.suggestLabel();
    this.recount();
    this.api.apolloIndustries().subscribe({
      next: (rows) => this.industries.set(rows),
      // A missing list is not worth an error on the screen: the filter is
      // optional and everything else still works without it.
      error: () => this.industries.set([]),
    });
  }

  labelTyped(): void {
    this.labelEdited = true;
  }

  /** A name made of the filters, so the common case is press-and-go.
   *  "Apollo · 51–200 · IT services · both personas" says what is in the list
   *  without anybody writing it down. */
  private suggestLabel(): void {
    if (this.labelEdited) return;
    const bits = ['Apollo'];
    if (this.draft.size_bands.length) bits.push(this.draft.size_bands.join(', '));
    if (this.draft.industries.length) {
      bits.push(
        this.draft.industries.length > 2
          ? `${this.draft.industries.length} industries`
          : this.draft.industries.map((i) => this.shortIndustry(i)).join(', '),
      );
    }
    bits.push(
      this.draft.personas.length === 2
        ? 'both personas'
        : this.draft.personas[0] ?? 'any persona',
    );
    this.label = bits.join(' · ');
  }

  /** "information technology & services" is too long for a list name. */
  shortIndustry(name: string): string {
    return name.replace('information technology & services', 'IT services')
      .replace('nonprofit organization management', 'nonprofits')
      .replace('transportation/trucking/railroad', 'transport');
  }

  toggleIndustry(name: string): void {
    this.draft.industries = this.draft.industries.includes(name)
      ? this.draft.industries.filter((x) => x !== name)
      : [...this.draft.industries, name];
    this.recount();
  }

  /** The first eight carry nearly all of this account's volume; the rest are
   *  behind a toggle so the card is not a wall of thirty-eight chips. */
  shownIndustries(): string[] {
    const all = this.industries();
    if (this.showAllIndustries()) return all;
    const top = all.slice(0, 8);
    // Anything chosen stays visible even when it is further down the list.
    return [...top, ...this.draft.industries.filter((i) => !top.includes(i))];
  }

  toggleBand(b: string): void {
    this.draft.size_bands = this.draft.size_bands.includes(b)
      ? this.draft.size_bands.filter((x) => x !== b)
      : [...this.draft.size_bands, b];
    this.recount();
  }

  togglePersona(p: string): void {
    const next = this.draft.personas.includes(p)
      ? this.draft.personas.filter((x) => x !== p)
      : [...this.draft.personas, p];
    // Asking for nobody is not a filter, it is an empty list. Keep the last one.
    if (next.length) {
      this.draft.personas = next;
      this.recount();
    }
  }

  /** Recount, debounced — typing in a number field fires per keystroke, and
   *  each count is four queries plus up to forty pages against Apollo. Free,
   *  but not instant, and a count for "1" on the way to "100" is wasted. */
  recount(): void {
    this.suggestLabel();
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.count(), 450);
  }

  private count(): void {
    this.counting.set(true);
    this.error.set(null);
    // Any change invalidates the pair count: it was read against the old
    // filters and nothing about it is still true.
    this.deep.set(null);
    this.api.previewFromApollo(this.draft).subscribe({
      next: (r) => {
        this.counting.set(false);
        this.result.set(r);
      },
      error: (err) => {
        this.counting.set(false);
        this.error.set(apiError(err, 'Could not read the saved contacts.'));
      },
    });
  }

  /** The slow half, on request. Measured at sixty-four seconds against forty
   *  pages, now scaled to the ask — thirteen pages for a hundred contacts. */
  check(): void {
    this.checking.set(true);
    this.error.set(null);
    this.api.previewFromApollo(this.draft, true).subscribe({
      next: (r) => {
        this.checking.set(false);
        this.deep.set(r);
      },
      error: (err) => {
        this.checking.set(false);
        this.error.set(apiError(err, 'Could not check availability.'));
      },
    });
  }

  steps(f: ApolloBuild['funnel']): { label: string; n: number; pct: number }[] {
    const top = f.saved_total || 1;
    return [
      { label: 'All saved contacts', n: f.saved_total, pct: 100 },
      { label: 'Verified email', n: f.verified, pct: this.pct(f.verified, top) },
      { label: 'Persona titles', n: f.titled, pct: this.pct(f.titled, top) },
      { label: 'Company size band', n: f.in_band, pct: this.pct(f.in_band, top) },
      // Only once something has been read. A "Read this pass 0" row before
      // the deep check reads as a failure rather than as a step not taken.
      ...(f.read
        ? [{ label: 'Read this pass', n: f.read, pct: this.pct(f.read, top) }]
        : []),
    ];
  }

  pct(n: number, of: number): number {
    return of ? Math.max(1, Math.round((n / of) * 100)) : 0;
  }

  /** What Create will actually take — the ask, or everything there is. */
  willTake(): number {
    const d = this.deep();
    return d ? Math.min(this.draft.limit, d.funnel?.available ?? 0) : this.draft.limit;
  }

  /** Buildable without a deep check: Create reads the pages itself, and
   *  forcing the slow count first would make the common path take twice as
   *  long for an answer the build already produces.
   *
   *  **Either count will do.** This looked only at the fast one, so a
   *  transient failure there — Apollo's rate limit, most often — disabled
   *  Create while a *successful* deep read sat on the screen beside it. The
   *  deep read is the better evidence that a build will work, and it was
   *  being ignored because the cheaper call had since failed.
   */
  canBuild(): boolean {
    return !!this.label.trim() && (!!this.result()?.ran || !!this.deep()?.ran);
  }

  /** Whichever answer is current, preferring the deep one — it has every
   *  number the fast one has, and the pair count as well. */
  shown(): ApolloBuild | null {
    const d = this.deep();
    return d?.ran ? d : this.result();
  }

  /** A refusal from either call. Shown on its own line rather than only
   *  inside the funnel, which disappears when the count it belongs to fails
   *  — so the screen went blank and said nothing at all. */
  refusal(): string | null {
    const r = this.result();
    const d = this.deep();
    if (d && !d.ran) return d.blocked ?? null;
    if (r && !r.ran && !d?.ran) return r.blocked ?? null;
    return null;
  }

  build(): void {
    this.working.set('build');
    this.error.set(null);
    this.api.buildFromApollo(this.label.trim(), this.draft).subscribe({
      next: (r) => {
        this.working.set(null);
        if (!r.ran || !r.list_id) {
          this.error.set(r.blocked ?? 'Nothing was created.');
          return;
        }
        this.built.emit(r.list_id);
      },
      error: (err) => {
        this.working.set(null);
        this.error.set(apiError(err, 'Could not build the list.'));
      },
    });
  }
}
