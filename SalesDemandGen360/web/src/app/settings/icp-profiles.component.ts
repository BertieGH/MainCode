import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ConfigService, IcpProfile, Service } from '../core/config.service';
import { FilterPanelComponent } from '../shared/filter-panel.component';
import { IconComponent } from '../shared/icon.component';
import { sortRows } from '../shared/client-sort';
import { NO_SORT, SortState, SortableDirective } from '../shared/sortable';
import { IcpEditorComponent } from './icp-editor.component';
import { apiError } from '../shared/api-error';

/**
 * ICP profiles — who you sell to, named once and shared.
 *
 * Its own screen rather than a section under a service, because an ICP belongs
 * to *several* services. Edited under one of them, a change would silently move
 * the targeting of the others, and nothing on screen would say so.
 *
 * Two rules the UI has to make visible rather than merely obey:
 *
 * **A profile with no definition targets nobody.** It can be linked to a
 * service and still be empty, which passes a naive "has an ICP?" check and then
 * hands enrichment no personas at all. Shown as `empty`, not as a version.
 *
 * **Saving makes a new version.** Runs already finished keep pointing at the
 * version they read, so "why were these contacts chosen?" survives an edit.
 */
@Component({
  selector: 'app-icp-profiles',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    IconComponent,
    IcpEditorComponent,
    FilterPanelComponent,
    SortableDirective,
  ],
  template: `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
      <h2 style="font-size:1.15rem;">ICP profiles</h2>
      <button class="act-btn" (click)="help.set(!help())"
              [attr.aria-expanded]="help()" aria-controls="icp-help"
              aria-label="About ICP profiles" title="What these control">
        <app-icon name="info" [size]="15" />
      </button>
    </div>
    <p class="row-sub" id="icp-help" *ngIf="help()" style="max-width:78ch;margin-bottom:14px;">
      An ICP describes a kind of buyer: the industries and regions worth
      approaching, the size of company, and the <strong>buyer personas</strong> to
      reach. Each ICP picks the products/services it is for; a service needs no
      ICP of its own. An account list is worked for one or more ICPs — and their
      personas decide who is worth paying a provider to find, and who research
      looks into.
      Saving writes a <strong>new version</strong>; runs that already happened
      keep pointing at the version they used.
    </p>

    <!-- Who is selling. Two fields, so a screen of their own would be mostly
         empty — and they read better next to who you sell *to*, since the two
         together are exactly what the org block and catalogue block of every
         prompt are assembled from. -->
    <div class="card" style="margin-bottom:18px;">
      <h3 style="font-size:.98rem;margin-bottom:2px;">Your company</h3>
      <p class="row-sub" style="max-width:70ch;margin-bottom:10px;">
        Who is doing the selling. Every research and outreach prompt carries this,
        so the model knows whose offer it is writing.
      </p>
      <div class="newrow">
        <label class="fl">
          <span class="row-sub">Name</span>
          <input class="field" [(ngModel)]="orgName" style="min-width:220px;">
        </label>
        <label class="fl" style="flex:1;min-width:260px;">
          <span class="row-sub">What you do</span>
          <input class="field" [(ngModel)]="orgDesc"
                 placeholder="Engineering partner for product teams…">
        </label>
      </div>
      <div style="display:flex;gap:10px;align-items:center;margin-top:10px;">
        <button class="btn btn-primary" (click)="saveOrg()"
                [disabled]="savingOrg() || !orgName.trim() || !orgDirty()">
          <app-icon name="check" [size]="13" />
          {{ savingOrg() ? 'Saving…' : 'Save company' }}
        </button>
        <span class="row-sub" *ngIf="!orgDirty()">No changes.</span>
      </div>
    </div>

    <div class="sec-head">
      <h3 style="font-size:.98rem;">{{ profiles().length }} profile{{ profiles().length === 1 ? '' : 's' }}</h3>
      <button class="btn btn-primary" (click)="startNew()"
              style="padding:6px 12px;font-size:.78rem;"
              [disabled]="!services().length"
              [title]="services().length
                ? 'Add an ICP'
                : 'Add a product/service first — an ICP has to be for something'">
        <app-icon name="plus" [size]="13" /> Add ICP
      </button>
    </div>

    <app-filter-panel key="icp-profiles" noun="profiles"
                      [activeCount]="activeFilters()" [summary]="filterSummary()"
                      [showing]="visible().length" [total]="profiles().length"
                      (cleared)="clearFilters()">
      <label class="fl">
        <span class="row-sub">Name</span>
        <input class="field" [(ngModel)]="qName" (ngModelChange)="page.set(0)"
               placeholder="contains…">
      </label>
      <label class="fl">
        <span class="row-sub">Product/service</span>
        <select class="field" [(ngModel)]="qService" (ngModelChange)="page.set(0)">
          <option value="">any</option>
          <option *ngFor="let s of services()" [value]="s.code">{{ s.code }}</option>
        </select>
      </label>
      <label class="fl">
        <span class="row-sub">Defined</span>
        <select class="field" [(ngModel)]="qDefined" (ngModelChange)="page.set(0)">
          <option value="">any</option>
          <option value="yes">has a definition</option>
          <option value="no">empty</option>
        </select>
      </label>
    </app-filter-panel>

    <p class="row-sub err" *ngIf="error()">{{ error() }}</p>

    <div class="table-wrap">
      <table class="data">
        <thead>
          <tr>
            <th appSortable="name" [state]="sort()" (sortChange)="onSort($event)">Name</th>
            <th>Products/services</th>
            <th appSortable="version" [state]="sort()" (sortChange)="onSort($event)">Version</th>
            <th appSortable="list_count" [state]="sort()" (sortChange)="onSort($event)">Lists</th>
            <th class="actcol">Actions</th>
          </tr>
        </thead>
        <tbody>
          <ng-container *ngFor="let p of visible()">
            <tr>
              <td>
                <strong>{{ p.name }}</strong>
                <div class="row-sub" *ngIf="p.description">{{ p.description }}</div>
              </td>
              <td class="row-sub">{{ p.service_codes.join(', ') || '—' }}</td>
              <td class="mono">
                <span *ngIf="p.definition; else empty">v{{ p.version }}</span>
                <ng-template #empty>
                  <span class="missing"
                        title="No definition yet, so this profile targets nobody and
                               enrichment for it is refused.">empty</span>
                </ng-template>
              </td>
              <td class="mono">{{ p.list_count }}</td>
              <td class="actcol">
                <button class="act-btn" (click)="edit(p)"
                        [attr.aria-label]="'Edit ' + p.name">
                  <app-icon name="edit" [size]="14" />
                </button>
                <button class="act-btn" (click)="remove(p)"
                        [disabled]="p.list_count > 0"
                        [title]="p.list_count
                          ? 'Used by ' + p.list_count + ' account list(s) — deleting would
                             make their enrichment unexplainable'
                          : 'Delete this ICP'"
                        [attr.aria-label]="'Delete ' + p.name">
                  <app-icon name="trash" [size]="14" />
                </button>
              </td>
            </tr>

            <tr *ngIf="editing() === p.id">
              <td colspan="5" style="background:var(--mono-bg);">
                <label class="fl" style="margin-bottom:10px;">
                  <span class="row-sub">Product/services to sell</span>
                  <span class="svc-picks">
                    <label *ngFor="let s of services()" class="pick">
                      <input type="checkbox" [checked]="picked.has(s.code)"
                             (change)="togglePick(s.code)">
                      <code>{{ s.code }}</code>
                    </label>
                  </span>
                </label>
                <p class="row-sub missing" *ngIf="!picked.size">
                  Pick at least one product/service — an ICP that is for nothing
                  would never be read by anything.
                </p>

                <app-icp-editor [value]="draft" [profileId]="p.id" (valueChange)="draft = $event" />

                <div style="display:flex;gap:10px;align-items:center;margin-top:12px;">
                  <button class="btn btn-primary" (click)="save(p)"
                          [disabled]="saving() || !picked.size">
                    <app-icon name="check" [size]="13" />
                    {{ saving() ? 'Saving…' : 'Save as new version' }}
                  </button>
                  <button class="btn" (click)="editing.set(null)">Cancel</button>
                </div>
              </td>
            </tr>
          </ng-container>

          <tr *ngIf="creating()">
            <td colspan="5" style="background:var(--mono-bg);">
              <div class="newrow">
                <label class="fl">
                  <span class="row-sub">Name</span>
                  <input class="field" [(ngModel)]="newName" placeholder="Mid-market SaaS">
                </label>
                <label class="fl" style="flex:1;">
                  <span class="row-sub">Description</span>
                  <input class="field" [(ngModel)]="newDesc" placeholder="optional">
                </label>
              </div>
              <label class="fl" style="margin:10px 0;">
                <span class="row-sub">Product/services to sell</span>
                <span class="svc-picks">
                  <label *ngFor="let s of services()" class="pick">
                    <input type="checkbox" [checked]="picked.has(s.code)"
                           (change)="togglePick(s.code)">
                    <code>{{ s.code }}</code>
                  </label>
                </span>
              </label>
              <app-icp-editor [value]="draft" (valueChange)="draft = $event" />
              <div style="display:flex;gap:10px;align-items:center;margin-top:12px;">
                <button class="btn btn-primary" (click)="create()"
                        [disabled]="saving() || !newName.trim() || !picked.size">
                  <app-icon name="check" [size]="13" />
                  {{ saving() ? 'Creating…' : 'Create ICP' }}
                </button>
                <button class="btn" (click)="creating.set(false)">Cancel</button>
              </div>
            </td>
          </tr>

          <tr *ngIf="!loading() && !profiles().length && !creating()">
            <td colspan="5" class="row-sub" style="text-align:center;padding:22px;">
              No ICPs yet. Nothing can be enriched or researched until an ICP names
              its buyer personas.
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  `,
  styles: [
    `
      .sec-head { display:flex; align-items:center; justify-content:space-between;
                  margin: 16px 0 8px; }
      .fl { display:flex; flex-direction:column; gap:4px; }
      .newrow { display:flex; gap:12px; flex-wrap:wrap; }
      .svc-picks { display:flex; gap:14px; flex-wrap:wrap; padding-top:2px; }
      .pick { display:flex; align-items:center; gap:5px; font-size:.8rem; }
      .missing { color: var(--critical); }
      .err { color: var(--critical); margin: 8px 0; }
      .chip.link { text-decoration:none; }
    `,
  ],
})
export class IcpProfilesComponent implements OnInit {
  private api = inject(ConfigService);

  profiles = signal<IcpProfile[]>([]);
  services = signal<Service[]>([]);
  loading = signal(true);
  error = signal<string | null>(null);
  help = signal(false);
  saving = signal(false);
  savingOrg = signal(false);

  orgName = '';
  orgDesc = '';
  /** What was loaded, so "no changes" is a fact rather than a guess. */
  private orgLoaded = { name: '', description: '' };

  orgDirty(): boolean {
    return (
      this.orgName !== this.orgLoaded.name ||
      this.orgDesc !== this.orgLoaded.description
    );
  }

  editing = signal<string | null>(null);
  creating = signal(false);
  page = signal(0);

  /** The editor binds to this; replaced wholesale when a row is opened. */
  draft: Record<string, unknown> = {};
  /** Service codes ticked in the open editor. A Set, so order never matters. */
  picked = new Set<string>();
  newName = '';
  newDesc = '';

  /**
   * How each sortable column reads its value.
   *
   * `version` deliberately reads `null` for an undefined profile rather than
   * 0: blanks sort last in both directions, so the profiles nobody has written
   * stay at the bottom instead of pretending to be the oldest version.
   */
  private accessors = {
    name: (p: IcpProfile) => p.name,
    version: (p: IcpProfile) => (p.definition ? p.version : null),
    list_count: (p: IcpProfile) => p.list_count,
  };

  qName = '';
  qService = '';
  qDefined = '';
  sort = signal<SortState>(NO_SORT);

  ngOnInit(): void {
    this.load();
    this.api.services().subscribe({
      next: (rows) => this.services.set(rows.filter((s) => s.is_active)),
      error: () => undefined,
    });
    this.api.getOrgProfile().subscribe({
      next: (p) => {
        this.orgName = p.name ?? '';
        this.orgDesc = p.description ?? '';
        this.orgLoaded = { name: this.orgName, description: this.orgDesc };
      },
      error: () => undefined,
    });
  }

  private load(): void {
    this.loading.set(true);
    this.api.icpProfiles().subscribe({
      next: (rows) => {
        this.profiles.set(rows);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Could not load ICP profiles.');
        this.loading.set(false);
      },
    });
  }

  onSort(state: SortState): void {
    this.sort.set(state);
  }

  activeFilters(): number {
    return [this.qName, this.qService, this.qDefined].filter((v) => v !== '').length;
  }

  /** What the collapsed panel says it is hiding. */
  filterSummary(): string {
    const bits: string[] = [];
    if (this.qName.trim()) bits.push(`name contains "${this.qName.trim()}"`);
    if (this.qService) bits.push(`sells ${this.qService}`);
    if (this.qDefined) bits.push(this.qDefined === 'yes' ? 'defined' : 'empty');
    return bits.join(' · ');
  }

  clearFilters(): void {
    this.qName = '';
    this.qService = '';
    this.qDefined = '';
  }

  visible(): IcpProfile[] {
    const name = this.qName.trim().toLowerCase();
    const rows = this.profiles().filter(
      (p) =>
        (!name || p.name.toLowerCase().includes(name)) &&
        (!this.qService || p.service_codes.includes(this.qService)) &&
        (!this.qDefined ||
          (this.qDefined === 'yes' ? p.definition !== null : p.definition === null)),
    );
    return sortRows(rows, this.sort(), this.accessors);
  }

  togglePick(code: string): void {
    if (this.picked.has(code)) this.picked.delete(code);
    else this.picked.add(code);
  }

  startNew(): void {
    this.editing.set(null);
    this.draft = {};
    this.picked = new Set<string>();
    this.newName = '';
    this.newDesc = '';
    this.error.set(null);
    this.creating.set(true);
  }

  edit(p: IcpProfile): void {
    this.creating.set(false);
    // A copy, so cancelling leaves the stored definition untouched.
    this.draft = structuredClone(p.definition ?? {});
    this.picked = new Set(p.service_codes);
    this.error.set(null);
    this.editing.set(p.id);
  }

  save(p: IcpProfile): void {
    this.saving.set(true);
    this.error.set(null);
    const codes = [...this.picked];
    const linksChanged =
      codes.length !== p.service_codes.length ||
      codes.some((c) => !p.service_codes.includes(c));

    this.api.saveIcpDefinition(p.id, this.draft).subscribe({
      next: () => {
        if (!linksChanged) return this.done();
        // Links second, and only when they actually changed — replacing them
        // with the same set would be a pointless write on every save.
        this.api.setIcpServices(p.id, codes).subscribe({
          next: () => this.done(),
          error: (e) => this.failed(e, 'Could not update the linked services.'),
        });
      },
      error: (e) => this.failed(e, 'Could not save the ICP.'),
    });
  }

  create(): void {
    this.saving.set(true);
    this.error.set(null);
    this.api
      .createIcpProfile({
        name: this.newName.trim(),
        description: this.newDesc.trim() || null,
        definition: this.draft,
        service_codes: [...this.picked],
      })
      .subscribe({
        next: () => {
          this.creating.set(false);
          this.done();
        },
        error: (e) => this.failed(e, 'Could not create the ICP.'),
      });
  }

  remove(p: IcpProfile): void {
    this.error.set(null);
    this.api.deleteIcpProfile(p.id).subscribe({
      next: () => this.load(),
      // The server refuses when a list uses it, and says which — so its
      // message is shown rather than replaced with a generic one.
      error: (e) => this.error.set(apiError(e, 'Could not delete this ICP.')),
    });
  }

  saveOrg(): void {
    this.savingOrg.set(true);
    this.error.set(null);
    // A new version, like every other config write here: the org description
    // is part of the prompt, so a run has to stay explainable against the one
    // it used.
    this.api
      .saveOrgProfile({ name: this.orgName.trim(), description: this.orgDesc.trim() })
      .subscribe({
        next: (p) => {
          this.orgLoaded = { name: p.name ?? '', description: p.description ?? '' };
          this.savingOrg.set(false);
        },
        error: (e) => {
          this.savingOrg.set(false);
          this.error.set(
            (e as { error?: { detail?: string } })?.error?.detail ??
              'Could not save the company profile.',
          );
        },
      });
  }

  private done(): void {
    this.saving.set(false);
    this.editing.set(null);
    this.load();
  }

  private failed(e: unknown, fallback: string): void {
    this.saving.set(false);
    const detail = (e as { error?: { detail?: string } })?.error?.detail;
    this.error.set(detail ?? fallback);
  }
}
