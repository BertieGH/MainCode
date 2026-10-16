import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AccessService, RoleGrid, RolesView } from '../core/access.service';
import { AuthService, Level, ROLE_LABELS } from '../core/auth.service';
import { apiError } from '../shared/api-error';
import { NotifyService } from '../shared/notify.service';

/**
 * What each role may do (`docs/17`).
 *
 * A level per module — None hides it, View opens it read-only, Edit lets you
 * create and change things there — plus the three actions that cost money or
 * reach a customer. Admin is not in the grid: its column is drawn locked,
 * because no edit here can be allowed to lock admins out of this screen.
 *
 * Saving writes a new version; nothing is edited in place, so who could do
 * what on a past date stays a row rather than a guess.
 */
@Component({
  selector: 'app-roles',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <h2 style="font-size:1.15rem;margin-bottom:4px;">Roles</h2>
    <p class="row-sub" style="max-width:72ch;margin-bottom:18px;">
      What each role can do. <strong>View</strong> opens a screen read-only, <strong>Edit</strong> also lets
      you create and change things there, <strong>None</strong> hides it from the menu. Admin always has
      everything. Saving writes a new version, so you can always see who could do what on a past date.
    </p>

    <div class="card" *ngIf="view() as v; else loading" style="padding:0;overflow-x:auto;">
      <table class="perm">
        <thead>
          <tr>
            <th style="min-width:240px;">Module</th>
            <th>Admin</th>
            <th *ngFor="let r of v.roles">{{ roleLabel(r) }}</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let m of moduleKeys()">
            <td>{{ v.modules[m] }}</td>
            <td class="locked">Edit</td>
            <td *ngFor="let r of v.roles">
              <select class="field lvl" [class.edit]="grid.modules[r][m] === 'edit'" [class.none]="grid.modules[r][m] === 'none'"
                      [(ngModel)]="grid.modules[r][m]" (ngModelChange)="touch()"
                      [attr.aria-label]="roleLabel(r) + ' — ' + v.modules[m]">
                <option *ngFor="let l of v.levels" [value]="l">{{ levelLabel(l) }}</option>
              </select>
            </td>
          </tr>
          <tr *ngFor="let m of adminModuleKeys()">
            <td>{{ v.admin_modules[m] }}</td>
            <td class="locked">Edit</td>
            <td *ngFor="let r of v.roles" class="locked">Admin only</td>
          </tr>
          <tr class="sec"><td [attr.colspan]="2 + v.roles.length">Actions</td></tr>
          <tr *ngFor="let a of actionKeys()">
            <td>{{ v.actions[a] }}<span class="risk" *ngIf="risk[a]"> · {{ risk[a] }}</span></td>
            <td><input type="checkbox" checked disabled aria-label="Admin always"></td>
            <td *ngFor="let r of v.roles">
              <input type="checkbox" [checked]="grid.actions[r].includes(a)" (change)="toggle(r, a)"
                     [attr.aria-label]="roleLabel(r) + ' — ' + v.actions[a]">
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <ng-template #loading><p class="row-sub">Loading…</p></ng-template>

    <div style="display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap;" *ngIf="view() as v">
      <button class="btn btn-primary" (click)="save()" [class.busy]="saving()" [disabled]="!dirty() || saving()">
        {{ saving() ? 'Saving…' : 'Save as new version' }}
      </button>
      <button class="btn" (click)="discard()" [disabled]="!dirty() || saving()">Discard changes</button>
      <span class="row-sub">
        <ng-container *ngIf="v.version; else shipped">
          Current: version {{ v.version }}<ng-container *ngIf="v.saved_by"> · saved by {{ v.saved_by }}</ng-container><ng-container *ngIf="v.saved_at"> on {{ v.saved_at | date: 'mediumDate' }}</ng-container>
        </ng-container>
        <ng-template #shipped>Current: the shipped defaults (never saved)</ng-template>
      </span>
    </div>
  `,
  styles: [`
    table.perm { border-collapse: collapse; width: 100%; font-size: .84rem; }
    .perm th { text-align: left; font-family: 'IBM Plex Mono', monospace; font-size: .62rem; letter-spacing: .08em;
      text-transform: uppercase; color: var(--faint); font-weight: 500; padding: 10px 14px; border-bottom: 1px solid var(--border); }
    .perm td { padding: 8px 14px; border-bottom: 1px solid var(--border); }
    .perm td.locked { color: var(--faint); font-size: .78rem; }
    .perm .sec td { background: var(--surface-2); font-family: 'IBM Plex Mono', monospace; font-size: .62rem;
      letter-spacing: .08em; text-transform: uppercase; color: var(--faint); padding: 7px 14px; }
    .lvl { width: auto; padding: 4px 6px; font-size: .78rem; }
    .lvl.edit { border-color: var(--accent); color: var(--accent); }
    .lvl.none { color: var(--faint); }
    .risk { color: var(--warn); font-size: .72rem; }
  `],
})
export class RolesComponent implements OnInit {
  private api = inject(AccessService);
  private auth = inject(AuthService);
  private notify = inject(NotifyService);

  view = signal<RolesView | null>(null);
  saving = signal(false);
  private revision = signal(0);
  /** The working copy the selects edit; compared with the saved one. */
  grid: RoleGrid = { modules: {}, actions: {} };

  readonly risk: Record<string, string> = {
    approve_send: 'reaches customers',
    paid_research: 'spends budget',
  };

  moduleKeys = computed(() => Object.keys(this.view()?.modules ?? {}));
  adminModuleKeys = computed(() => Object.keys(this.view()?.admin_modules ?? {}));
  actionKeys = computed(() => Object.keys(this.view()?.actions ?? {}));
  dirty = computed(() => {
    this.revision();
    const v = this.view();
    return !!v && JSON.stringify(this.normal(this.grid)) !== JSON.stringify(this.normal(v.grid));
  });

  ngOnInit(): void {
    this.api.roles().subscribe({
      next: (v) => this.adopt(v),
      error: (err) => this.notify.error('Could not load roles.', apiError(err, 'The server refused.')),
    });
  }

  roleLabel(r: string): string {
    return ROLE_LABELS[r as keyof typeof ROLE_LABELS] ?? r;
  }

  levelLabel(l: Level): string {
    return l === 'edit' ? 'Edit' : l === 'view' ? 'View' : 'None';
  }

  /** ngModel writes to a plain object no signal watches. */
  touch(): void {
    this.revision.update((n) => n + 1);
  }

  toggle(role: string, action: string): void {
    const now = this.grid.actions[role];
    this.grid.actions[role] = now.includes(action) ? now.filter((a) => a !== action) : [...now, action];
    this.touch();
  }

  discard(): void {
    const v = this.view();
    if (v) this.adopt(v);
  }

  save(): void {
    this.saving.set(true);
    this.api.saveRoles(this.normal(this.grid)).subscribe({
      next: (v) => {
        this.saving.set(false);
        this.adopt(v);
        // My own rights may have changed with it — re-read them so the menu
        // agrees. (An admin's never do; the reload is cheap and keeps one rule.)
        this.auth.load(true).subscribe();
        this.notify.success(`Saved as version ${v.version}.`, 'It applies to everyone within a few seconds.');
      },
      error: (err) => {
        this.saving.set(false);
        this.notify.error('The roles were not saved.', apiError(err, 'The server refused.'));
      },
    });
  }

  private adopt(v: RolesView): void {
    this.view.set(v);
    this.grid = JSON.parse(JSON.stringify(v.grid));
    this.touch();
  }

  /** Sorted actions, so ticking one off and on again is not a change. */
  private normal(g: RoleGrid): RoleGrid {
    return {
      modules: g.modules,
      actions: Object.fromEntries(Object.entries(g.actions).map(([r, a]) => [r, [...a].sort()])),
    };
  }
}
