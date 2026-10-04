import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ConfigService, IcpProfile, ProofPoint, Service } from '../core/config.service';
import { IconComponent } from '../shared/icon.component';
import { apiError } from '../shared/api-error';

/**
 * What CGVAK sells, and the claims it is allowed to make about it.
 *
 * The approval toggle is the point of this screen. Only `is_approved` proof
 * points reach a prompt at all — blocked at generation, not caught at review —
 * so an unapproved claim here is a claim the model has never seen and cannot
 * accidentally put in front of a prospect.
 */
@Component({
  selector: 'app-services',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, IconComponent],
  template: `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;">
      <h2 style="font-size:1.15rem;">Services and proof points</h2>
      <button class="act-btn" (click)="help.set(!help())"
              [attr.aria-expanded]="help()" aria-controls="svc-help"
              [attr.aria-label]="help() ? 'Hide help' : 'About proof point approval'"
              title="Why approval matters here">
        <app-icon name="info" [size]="15" />
      </button>
    </div>
    <p id="svc-help" class="row-sub" *ngIf="help()" style="max-width:70ch;margin-bottom:18px;">
      Only <strong>approved</strong> proof points reach a prompt. The filter is applied when the
      prompt is built, not when a draft is reviewed — so an unapproved claim is one the model has
      never seen and cannot put in front of a prospect by accident. Approving is deliberately a
      separate act from creating: a claim cannot arrive pre-approved in the request that made it.
    </p>

    <div class="card" *ngIf="error()" style="border-color:var(--critical);margin-bottom:18px;">
      <strong style="color:var(--critical);">{{ error() }}</strong>
    </div>

    <!-- services -->
    <div class="sec-head">
      <h3 style="font-size:.98rem;">Service catalog</h3>
      <button class="btn btn-primary" style="padding:6px 12px;font-size:.78rem;"
              (click)="addingService.set(!addingService())"
              aria-label="Add a service" title="Add a service">
        <app-icon name="plus" [size]="13" />Add Service
      </button>
    </div>

    <div class="card" *ngIf="addingService()" style="margin-bottom:14px;">
      <div class="form-grid">
        <label>Code
          <input class="field" [(ngModel)]="svc.code" placeholder="qa_engineering">
          <span class="row-sub">Lowercase snake_case. Referenced by strategy, never changes.</span>
        </label>
        <label>Name
          <input class="field" [(ngModel)]="svc.name" placeholder="QA engineering">
        </label>
        <label style="grid-column:1/-1;">Description
          <textarea class="field" rows="2" [(ngModel)]="svc.description"
                    placeholder="Embedded QA that absorbs a growing engineering team."></textarea>
        </label>
        <label>Positioning angles
          <input class="field" [(ngModel)]="anglesRaw" placeholder="ship faster without a quality cliff">
          <span class="row-sub">Comma separated.</span>
        </label>
        <label>Economic buyer
          <input class="field" [(ngModel)]="svc.economic_buyer" placeholder="CIO / Head of IT">
          <span class="row-sub">Who signs off, broadly. The people to reach are set on an ICP,
            as buyer personas.</span>
        </label>
        <div style="grid-column:1/-1;display:flex;gap:10px;align-items:center;">
          <button class="btn btn-primary" (click)="saveService()" [disabled]="!serviceReady()">
            <app-icon name="check" [size]="13" />Add service
          </button>
          <button class="btn" (click)="addingService.set(false)">Cancel</button>
          <span class="row-sub" [style.color]="serviceBlocker() ? 'var(--warn)' : ''">
            {{ serviceBlocker() ?? 'Both code and name are required.' }}
          </span>
        </div>
      </div>
    </div>

    <div class="table-wrap" style="margin-bottom:30px;">
      <table class="data">
        <thead>
          <tr>
            <th>Code</th><th>Name</th><th>Economic buyer</th><th>ICPs</th><th>Proof points</th>
            <th>Status</th><th class="actcol">Actions</th>
          </tr>
        </thead>
        <tbody>
          <!-- A container, not a repeated row: one service renders two rows —
               itself, and its ICP editor when opened. -->
          <ng-container *ngFor="let s of services()">
          <tr>
            <td><code>{{ s.code }}</code></td>
            <td>
              {{ s.name }}
              <div class="row-sub">{{ s.description }}</div>
            </td>
            <td class="row-sub">{{ s.economic_buyer || '—' }}</td>
            <td>
              <!-- Read-only. Which ICPs a service is for is chosen on the ICP,
                   under "Product/services to sell" — and a service needs none. -->
              <ng-container *ngIf="icpsFor(s.code).length; else noIcp">
                <a class="chip link" *ngFor="let p of icpsFor(s.code)"
                   routerLink="/settings/icp-profiles"
                   [title]="p.definition
                     ? p.name + ' — active v' + p.version
                     : p.name + ' has no definition yet, so it targets nobody'">
                  {{ p.name }}<span *ngIf="!p.definition" class="missing"> · empty</span>
                </a>
              </ng-container>
              <ng-template #noIcp><span class="row-sub">—</span></ng-template>
            </td>
            <td class="mono">
              {{ approvedFor(s.id) }} / {{ countFor(s.id) }}
              <span class="row-sub" *ngIf="countFor(s.id) > approvedFor(s.id)">approved</span>
            </td>
            <td>
              <span class="badge" [ngClass]="s.is_active ? 'badge-good' : 'badge-neutral'">
                {{ s.is_active ? 'active' : 'inactive' }}
              </span>
            </td>
            <td class="actcol">
              <button class="act-btn" (click)="startEdit(s)"
                      [attr.aria-label]="'Edit ' + s.code" [title]="'Edit ' + s.code">
                <app-icon name="edit" [size]="15" />
              </button>
              <button class="act-btn" (click)="toggleService(s)"
                      [attr.aria-label]="(s.is_active ? 'Deactivate ' : 'Reactivate ') + s.code"
                      [title]="s.is_active
                        ? 'Deactivate ' + s.code + ' — stops being weighed, keeps its history'
                        : 'Reactivate ' + s.code">
                <app-icon [name]="s.is_active ? 'pause' : 'play'" [size]="15" />
              </button>

              <!-- Delete only while nothing has committed to it. Once a strategy
                   has weighed the service, the matrix is the record of a decision
                   and must not point at nothing. -->
              <button *ngIf="confirmingService() !== s.code" class="act-btn danger"
                      (click)="confirmingService.set(s.code)"
                      [attr.aria-label]="'Delete ' + s.code"
                      [title]="'Delete ' + s.code + ' — only while nothing references it'">
                <app-icon name="trash" [size]="15" />
              </button>
              <ng-container *ngIf="confirmingService() === s.code">
                <span class="row-sub" style="margin-right:6px;">Delete for good?</span>
                <button class="act-btn danger" (click)="removeService(s)"
                        [attr.aria-label]="'Confirm delete ' + s.code" title="Yes, delete it">
                  <app-icon name="check" [size]="15" />
                </button>
                <button class="act-btn" (click)="confirmingService.set(null)"
                        aria-label="Keep it" title="Keep it">
                  <app-icon name="x" [size]="15" />
                </button>
              </ng-container>
            </td>
          </tr>
          <tr *ngIf="editingCode() === s.code">
            <td colspan="7" style="background:var(--mono-bg);">
              <div class="form-grid">
                <label>Name
                  <input class="field" [(ngModel)]="edit.name">
                </label>
                <label>Economic buyer
                  <input class="field" [(ngModel)]="edit.economic_buyer" placeholder="CIO / Head of IT">
                  <span class="row-sub">Who signs off, broadly.</span>
                </label>
                <label style="grid-column:1/-1;">Description
                  <textarea class="field" rows="2" [(ngModel)]="edit.description"></textarea>
                </label>
                <label style="grid-column:1/-1;">Positioning angles
                  <input class="field" [(ngModel)]="edit.angles">
                  <span class="row-sub">Comma separated.</span>
                </label>
                <div style="grid-column:1/-1;display:flex;gap:10px;align-items:center;">
                  <button class="btn btn-primary" (click)="saveEdit(s)" [class.busy]="savingEdit()"
                          [disabled]="savingEdit() || !edit.name.trim() || !edit.description.trim()">
                    <app-icon *ngIf="!savingEdit()" name="check" [size]="13" />
                    {{ savingEdit() ? 'Saving…' : 'Save' }}
                  </button>
                  <button class="btn" (click)="editingCode.set(null)">Cancel</button>
                  <span class="row-sub">The code {{ s.code }} stays — strategy refers to it.</span>
                </div>
              </div>
            </td>
          </tr>

          </ng-container>

          <tr *ngIf="!loading() && services().length === 0">
            <td colspan="7" class="row-sub" style="text-align:center;padding:22px;">
              No services yet.
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- proof points -->
    <div class="sec-head">
      <h3 style="font-size:.98rem;">Proof points</h3>
      <button class="btn btn-primary" style="padding:6px 12px;font-size:.78rem;"
              (click)="addingProof.set(!addingProof())"
              aria-label="Add a proof point" title="Add a proof point">
        <app-icon name="plus" [size]="13" />Add Proof Point
      </button>
    </div>
    <p class="row-sub" style="margin-bottom:12px;">
      A new proof point starts <strong>unapproved</strong> and stays out of every prompt until
      someone approves it here.
    </p>

    <div class="card" *ngIf="addingProof()" style="margin-bottom:14px;">
      <div class="form-grid">
        <label>Kind
          <select class="field" [(ngModel)]="proof.kind">
            <option value="case_study">case_study</option>
            <option value="metric">metric</option>
            <option value="logo">logo</option>
            <option value="testimonial">testimonial</option>
          </select>
        </label>
        <label>Service
          <select class="field" [(ngModel)]="proof.service_id">
            <option [ngValue]="null">— none —</option>
            <option *ngFor="let s of services()" [ngValue]="s.id">{{ s.name }}</option>
          </select>
        </label>
        <label style="grid-column:1/-1;">Title
          <input class="field" [(ngModel)]="proof.title"
                 placeholder="Retail platform cut regression time 60%">
        </label>
        <label style="grid-column:1/-1;">Body
          <textarea class="field" rows="3" [(ngModel)]="proof.body"
                    placeholder="An 80-engineer retail platform moved regression from 9 days to 3."></textarea>
          <span class="row-sub">This wording can reach a prospect verbatim. Write it as a claim you can defend.</span>
        </label>
        <label>Client industry
          <input class="field" [(ngModel)]="proof.client_industry" placeholder="Retail">
        </label>
        <label>Client size band
          <input class="field" [(ngModel)]="proof.client_size_band" placeholder="200-500">
        </label>
        <div style="grid-column:1/-1;display:flex;gap:10px;align-items:center;">
          <button class="btn btn-primary" (click)="saveProof()" [disabled]="!proofReady()">
            <app-icon name="check" [size]="13" />Add proof point
          </button>
          <button class="btn" (click)="addingProof.set(false)">Cancel</button>
          <span class="row-sub">It will be created unapproved.</span>
        </div>
      </div>
    </div>

    <div class="table-wrap">
      <table class="data">
        <thead>
          <tr><th>Title</th><th>Kind</th><th>Service</th><th>Status</th><th class="actcol">Actions</th></tr>
        </thead>
        <tbody>
          <tr *ngFor="let p of proofPoints()" [style.opacity]="p.is_approved ? 1 : 0.72">
            <td>
              {{ p.title }}
              <div class="row-sub">{{ p.body }}</div>
            </td>
            <td class="row-sub">{{ p.kind }}</td>
            <td class="row-sub">{{ serviceName(p.service_id) }}</td>
            <td>
              <span class="badge" [ngClass]="p.is_approved ? 'badge-good' : 'badge-warn'">
                {{ p.is_approved ? 'approved' : 'not approved' }}
              </span>
            </td>
            <td class="actcol">
              <button *ngIf="!p.is_approved" class="act-btn" (click)="approve(p)"
                      [attr.aria-label]="'Approve ' + p.title"
                      [title]="'Approve ' + p.title + ' — it becomes usable in drafts'">
                <app-icon name="check" [size]="15" />
              </button>

              <!-- Withdraw is what matters when a claim turns out to be wrong:
                   it stops future use immediately without touching the drafts a
                   rep already approved on the strength of it. -->
              <button *ngIf="p.is_approved" class="act-btn" (click)="withdraw(p)"
                      [attr.aria-label]="'Withdraw ' + p.title"
                      [title]="'Withdraw ' + p.title + ' — stops future use; existing drafts keep citing it'">
                <app-icon name="pause" [size]="15" />
              </button>

              <button *ngIf="confirmingProof() !== p.id" class="act-btn danger"
                      (click)="confirmingProof.set(p.id)"
                      [attr.aria-label]="'Delete ' + p.title"
                      [title]="'Delete ' + p.title + ' — refused once a draft quotes it'">
                <app-icon name="trash" [size]="15" />
              </button>
              <ng-container *ngIf="confirmingProof() === p.id">
                <span class="row-sub" style="margin-right:6px;">Delete for good?</span>
                <button class="act-btn danger" (click)="removeProof(p)"
                        [attr.aria-label]="'Confirm delete ' + p.title" title="Yes, delete it">
                  <app-icon name="check" [size]="15" />
                </button>
                <button class="act-btn" (click)="confirmingProof.set(null)"
                        aria-label="Keep it" title="Keep it">
                  <app-icon name="x" [size]="15" />
                </button>
              </ng-container>
            </td>
          </tr>
          <tr *ngIf="!loading() && proofPoints().length === 0">
            <td colspan="5" class="row-sub" style="text-align:center;padding:22px;">
              No proof points yet.
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  `,
  styles: [
    `
      .sec-head { display: flex; justify-content: space-between; align-items: center;
                  gap: 16px; margin-bottom: 4px; }
      .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
      .form-grid label { display: flex; flex-direction: column; gap: 5px; font-size: .84rem; }
      @media (max-width: 720px) { .form-grid { grid-template-columns: 1fr; } }
    `,
  ],
})
export class ServicesComponent implements OnInit {
  /**
   * Every ICP profile, indexed by nothing — the list is short and each row
   * carries the service codes it links to.
   *
   * Held as a signal rather than derived from `services()`: profiles arrive in
   * their own request, and a computed over the services list would never see
   * them.
   */
  icpProfiles = signal<IcpProfile[]>([]);

  /** The profiles this service sells to. */
  icpsFor(code: string): IcpProfile[] {
    return this.icpProfiles().filter((p) => p.service_codes.includes(code));
  }

  private loadIcps(): void {
    this.api.icpProfiles().subscribe({
      next: (rows) => this.icpProfiles.set(rows),
      error: () => undefined,
    });
  }

  private api = inject(ConfigService);

  services = signal<Service[]>([]);
  proofPoints = signal<ProofPoint[]>([]);
  loading = signal(true);
  error = signal<string | null>(null);
  help = signal(false);
  addingService = signal(false);
  addingProof = signal(false);
  confirmingService = signal<string | null>(null);
  confirmingProof = signal<string | null>(null);

  svc = { code: '', name: '', description: '', economic_buyer: '' };
  anglesRaw = '';

  /** The service open for editing, by code — codes never change. */
  editingCode = signal<string | null>(null);
  savingEdit = signal(false);
  edit = { name: '', description: '', economic_buyer: '', angles: '' };
  proof = {
    kind: 'case_study',
    service_id: null as string | null,
    title: '',
    body: '',
    client_industry: '',
    client_size_band: '',
  };

  ngOnInit(): void {
    this.load();
  }

  countFor(serviceId: string): number {
    return this.proofPoints().filter((p) => p.service_id === serviceId).length;
  }

  approvedFor(serviceId: string): number {
    return this.proofPoints().filter((p) => p.service_id === serviceId && p.is_approved).length;
  }

  serviceName(id: string | null): string {
    return this.services().find((s) => s.id === id)?.name ?? '—';
  }

  serviceBlocker(): string | null {
    if (!this.svc.code.trim()) return 'Give it a code — lowercase snake_case.';
    if (!/^[a-z][a-z0-9_]*$/.test(this.svc.code)) return 'Code must be lowercase snake_case.';
    if (!this.svc.name.trim()) return 'Give it a name.';
    if (!this.svc.description.trim()) return 'Give it a description — it goes into the prompt.';
    return null;
  }

  serviceReady(): boolean {
    return this.serviceBlocker() === null;
  }

  proofReady(): boolean {
    return this.proof.title.trim().length > 0 && this.proof.body.trim().length > 0;
  }

  saveService(): void {
    this.api
      .createService({
        ...this.svc,
        economic_buyer: this.svc.economic_buyer.trim() || null,
        positioning_angles: split(this.anglesRaw),
      })
      .subscribe({
        next: () => {
          this.svc = { code: '', name: '', description: '', economic_buyer: '' };
          this.anglesRaw = '';
          this.addingService.set(false);
          this.load();
        },
        error: (err) => this.error.set(apiError(err, 'Could not add the service.')),
      });
  }

  startEdit(s: Service): void {
    this.edit = {
      name: s.name,
      description: s.description,
      economic_buyer: s.economic_buyer ?? '',
      angles: (s.positioning_angles ?? []).join(', '),
    };
    this.error.set(null);
    this.editingCode.set(s.code);
  }

  saveEdit(s: Service): void {
    this.savingEdit.set(true);
    this.api
      .updateService(s.code, {
        name: this.edit.name.trim(),
        description: this.edit.description.trim(),
        economic_buyer: this.edit.economic_buyer.trim() || null,
        positioning_angles: split(this.edit.angles),
      })
      .subscribe({
        next: (updated) => {
          this.savingEdit.set(false);
          this.editingCode.set(null);
          this.services.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
        },
        error: (err) => {
          this.savingEdit.set(false);
          this.error.set(apiError(err, 'Could not save the service.'));
        },
      });
  }

  saveProof(): void {
    this.api.createProofPoint({ ...this.proof }).subscribe({
      next: () => {
        this.proof = {
          kind: 'case_study', service_id: null, title: '', body: '',
          client_industry: '', client_size_band: '',
        };
        this.addingProof.set(false);
        this.load();
      },
      error: (err) => this.error.set(apiError(err, 'Could not add the proof point.')),
    });
  }

  toggleService(s: Service): void {
    this.api.setServiceActive(s.code, !s.is_active).subscribe({
      next: (updated) =>
        this.services.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r))),
      error: (err) => this.error.set(apiError(err, 'Could not change the service.')),
    });
  }

  removeService(s: Service): void {
    this.api.deleteService(s.code).subscribe({
      next: () => {
        this.services.update((rows) => rows.filter((r) => r.id !== s.id));
        this.confirmingService.set(null);
      },
      error: (err) => {
        // The server is the authority: a strategy can reference it between
        // this page rendering and the click.
        this.error.set(apiError(err, 'Could not delete the service.'));
        this.confirmingService.set(null);
      },
    });
  }

  withdraw(p: ProofPoint): void {
    this.api.withdrawProofPoint(p.id).subscribe({
      next: (updated) =>
        this.proofPoints.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r))),
      error: (err) => this.error.set(apiError(err, 'Could not withdraw.')),
    });
  }

  removeProof(p: ProofPoint): void {
    this.api.deleteProofPoint(p.id).subscribe({
      next: () => {
        this.proofPoints.update((rows) => rows.filter((r) => r.id !== p.id));
        this.confirmingProof.set(null);
      },
      error: (err) => {
        this.error.set(apiError(err, 'Could not delete the proof point.'));
        this.confirmingProof.set(null);
      },
    });
  }

  approve(p: ProofPoint): void {
    this.api.approveProofPoint(p.id).subscribe({
      next: (updated) =>
        this.proofPoints.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r))),
      error: (err) => this.error.set(apiError(err, 'Could not approve.')),
    });
  }

  private load(): void {
    this.loading.set(true);
    this.api.services().subscribe({
      next: (s) => {
        this.services.set(s);
        this.loading.set(false);
        this.loadIcps();
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(apiError(err, 'Could not load services.'));
      },
    });
    this.api.proofPoints().subscribe({
      next: (p) => this.proofPoints.set(p),
      error: () => this.proofPoints.set([]),
    });
  }
}

function split(raw: string): string[] {
  return raw
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}
