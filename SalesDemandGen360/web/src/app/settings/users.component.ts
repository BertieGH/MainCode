import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Observable } from 'rxjs';

import { AccessService, AdminUser, generatePassword } from '../core/access.service';
import { AuthService, ROLE_LABELS } from '../core/auth.service';
import { apiError } from '../shared/api-error';
import { sortRows } from '../shared/client-sort';
import { ConfirmService } from '../shared/confirm.service';
import { DataTableComponent } from '../shared/data-table.component';
import { NotifyService } from '../shared/notify.service';
import { NO_SORT, SortState } from '../shared/sortable';
import { ColumnDef, RowAction } from '../shared/table-view';

/**
 * Who can sign in, and as which role (`docs/17`).
 *
 * An admin creates every account and sets its password, then tells the person
 * — the app sends nothing. Someone with history (an approval, an audited
 * action, a role version, an account they created) is deactivated, never
 * deleted: what they did has to stay answerable after they leave. An account
 * with no history — created by mistake — can be deleted outright. The server refuses the two moves that would strand the installation
 * (removing the last admin, changing your own role) with the reason.
 */
@Component({
  selector: 'app-users',
  standalone: true,
  imports: [CommonModule, FormsModule, DataTableComponent],
  template: `
    <h2 style="font-size:1.15rem;margin-bottom:4px;">Users</h2>
    <p class="row-sub" style="max-width:72ch;margin-bottom:18px;">
      Who can sign in, and as which role. An account that has never done anything can be deleted;
      anyone with history is deactivated instead, so the record of who approved and sent what stays intact.
    </p>

    <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap;">
      <span class="row-sub">{{ activeCount() }} active · {{ users().length - activeCount() }} deactivated</span>
      <span style="flex:1;"></span>
      <button class="btn btn-primary" (click)="openCreate()" [disabled]="creating()">+ Create user</button>
    </div>

    <form class="queuepick panel" *ngIf="creating()" (ngSubmit)="create()">
      <div class="grid2">
        <label class="f">Full name<input class="field" name="full_name" [(ngModel)]="draft.full_name" required></label>
        <label class="f">Work email<input class="field" name="email" type="email" [(ngModel)]="draft.email" placeholder="name@cgvak.com" required></label>
        <label class="f">Role
          <select class="field" name="role" [(ngModel)]="draft.role">
            <option *ngFor="let r of roleKeys" [value]="r">{{ roleLabels[r] }}</option>
          </select>
        </label>
        <label class="f">Password
          <span style="display:flex;gap:6px;">
            <input class="field mono" name="password" [(ngModel)]="draft.password" required autocomplete="off">
            <button class="btn" type="button" (click)="draft.password = gen()">Generate</button>
          </span>
        </label>
      </div>
      <p class="row-sub" style="margin:-4px 0 12px;">
        Tell them their email and password yourself — the app sends nothing. At least 10 characters.
      </p>
      <div style="display:flex;gap:10px;">
        <button class="btn btn-primary" type="submit" [class.busy]="saving()"
                [disabled]="saving() || !draft.full_name.trim() || !draft.email.trim() || draft.password.length < 10">
          {{ saving() ? 'Creating…' : 'Create user' }}
        </button>
        <button class="btn" type="button" (click)="creating.set(false)">Cancel</button>
      </div>
    </form>

    <app-data-table
      table="users"
      noun="users"
      emptyText="No users yet."
      [columns]="columns"
      [data]="sorted()"
      [sort]="sort()"
      (sortChange)="sort.set($event)"
      [openable]="false"
      [rowActions]="actions"
      [label]="nameOf"
      (rowAction)="onAction($event.action.key, $any($event.row))"
      [cell]="userCell">
    </app-data-table>
    <p class="row-sub" style="margin-top:10px;">
      At least one active Admin must always remain. Deactivating someone, or setting their password,
      signs them out everywhere at once.
    </p>

    <!-- Change a role. -->
    <form class="queuepick panel" *ngIf="roleFor() as u" (ngSubmit)="saveRole(u)">
      <span>Role for <strong>{{ u.full_name }}</strong></span>
      <select class="field" name="role" [(ngModel)]="nextRole" style="max-width:200px;">
        <option *ngFor="let r of roleKeys" [value]="r">{{ roleLabels[r] }}</option>
      </select>
      <button class="btn btn-primary" type="submit" [disabled]="saving() || nextRole === u.role">Save</button>
      <button class="btn" type="button" (click)="roleFor.set(null)">Cancel</button>
    </form>

    <!-- Set a new password. -->
    <form class="queuepick panel" *ngIf="passwordFor() as u" (ngSubmit)="savePassword(u)">
      <span>New password for <strong>{{ u.full_name }}</strong></span>
      <input class="field mono" name="pw" [(ngModel)]="nextPassword" style="max-width:220px;" autocomplete="off">
      <button class="btn" type="button" (click)="nextPassword = gen()">Generate</button>
      <button class="btn btn-primary" type="submit" [disabled]="saving() || nextPassword.length < 10">Set password</button>
      <button class="btn" type="button" (click)="passwordFor.set(null)">Cancel</button>
      <span class="row-sub">Their old password stops working and they are signed out. Tell them the new one yourself.</span>
    </form>

    <ng-template #userCell let-row let-column="column" let-value="value">
      <ng-container [ngSwitch]="column.key">
        <ng-container *ngSwitchCase="'full_name'">
          {{ row.full_name }}<span class="row-sub" *ngIf="row.id === auth.user()?.id"> (you)</span>
        </ng-container>
        <code *ngSwitchCase="'email'">{{ row.email }}</code>
        <ng-container *ngSwitchCase="'role'">
          <span class="badge" [class.badge-accent]="row.role === 'admin'">{{ row.protected ? 'Super admin' : value }}</span>
        </ng-container>
        <span *ngSwitchCase="'status'" class="badge" [class.badge-good]="row.status === 'active'">{{ value }}</span>
        <ng-container *ngSwitchDefault>{{ value }}</ng-container>
      </ng-container>
    </ng-template>
  `,
  styles: [`
    .panel { margin: 0 0 14px; flex-wrap: wrap; }
    .grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0 14px; width: 100%; }
    .f { display: flex; flex-direction: column; gap: 4px; font-size: .78rem; color: var(--muted); margin-bottom: 12px; }
    form.panel { display: flex; gap: 10px; align-items: center; }
    form.panel:has(.grid2) { display: block; }
  `],
})
export class UsersComponent implements OnInit {
  private api = inject(AccessService);
  readonly auth = inject(AuthService);
  private notify = inject(NotifyService);
  private confirm = inject(ConfirmService);

  readonly roleLabels = ROLE_LABELS;
  readonly roleKeys = Object.keys(ROLE_LABELS) as (keyof typeof ROLE_LABELS)[];
  readonly gen = generatePassword;
  readonly nameOf = (u: AdminUser) => u.full_name;

  users = signal<AdminUser[]>([]);
  sort = signal<SortState>(NO_SORT);
  creating = signal(false);
  saving = signal(false);
  roleFor = signal<AdminUser | null>(null);
  passwordFor = signal<AdminUser | null>(null);
  draft = { full_name: '', email: '', role: 'demandgen', password: '' };
  nextRole = '';
  nextPassword = '';

  activeCount = computed(() => this.users().filter((u) => u.status === 'active').length);
  sorted = computed(() =>
    sortRows(this.users(), this.sort(), {
      full_name: (u) => u.full_name.toLowerCase(),
      email: (u) => u.email,
      role: (u) => u.role,
      status: (u) => u.status,
      last_login_at: (u) => u.last_login_at,
    }),
  );

  readonly columns: ColumnDef[] = [
    { key: 'full_name', label: 'Name', width: 200 },
    { key: 'email', label: 'Email', width: 220 },
    { key: 'role', label: 'Role', width: 130, filter: 'enum', value: (u) => ROLE_LABELS[u.role as keyof typeof ROLE_LABELS] },
    { key: 'status', label: 'Status', width: 130, filter: 'enum', value: (u) => u.status },
    { key: 'history', label: 'History', width: 240, filter: 'none',
      value: (u) => Object.entries(u.history ?? {}).map(([k, n]) => `${k}: ${n}`).join(', ') || 'none — can be deleted' },
    { key: 'last_login_at', label: 'Last sign-in', width: 170, filter: 'none',
      value: (u) => (u.last_login_at ? new Date(u.last_login_at).toLocaleString() : 'never') },
  ];

  /** Yourself excluded from the moves the server refuses for yourself. */
  private notMe = (u: AdminUser) => u.id !== this.auth.user()?.id;

  /** The super admin's account is theirs alone — the server refuses the rest. */
  private open = (u: AdminUser) => !u.protected;

  readonly actions: RowAction[] = [
    { key: 'role', label: 'Change role…', row: true, can: (u) => this.open(u) && this.notMe(u) && u.status === 'active', why: 'not yourself, a deactivated user, or the super admin' },
    { key: 'password', label: 'Set new password…', row: true, can: (u) => (this.open(u) || !this.notMe(u)) && u.status === 'active', why: 'the super admin sets their own' },
    { key: 'deactivate', label: 'Deactivate', row: true, danger: true, can: (u) => this.open(u) && this.notMe(u) && u.status === 'active', why: 'not yourself or the super admin' },
    { key: 'reactivate', label: 'Reactivate', row: true, can: (u) => u.status !== 'active', why: 'already active' },
    {
      key: 'delete', label: 'Delete user', row: true, danger: true,
      can: (u) => this.open(u) && this.notMe(u) && !this.hasHistory(u),
      why: 'has history, or is the super admin',
    },
  ];

  hasHistory(u: AdminUser): boolean {
    return Object.keys(u.history ?? {}).length > 0;
  }

  ngOnInit(): void {
    this.load();
  }

  private load(): void {
    this.api.users().subscribe({
      next: (rows) => this.users.set(rows),
      error: (err) => this.notify.error('Could not load users.', apiError(err, 'The server refused.')),
    });
  }

  openCreate(): void {
    this.draft = { full_name: '', email: '', role: 'demandgen', password: generatePassword() };
    this.creating.set(true);
  }

  create(): void {
    this.saving.set(true);
    const body = { ...this.draft, full_name: this.draft.full_name.trim(), email: this.draft.email.trim() };
    this.api.createUser(body).subscribe({
      next: (u) => {
        this.saving.set(false);
        this.creating.set(false);
        this.load();
        this.notify.success(`${u.full_name} created as ${ROLE_LABELS[u.role]}.`, `They sign in as ${u.email}. Give them the password yourself.`);
      },
      error: (err) => {
        this.saving.set(false);
        this.notify.error('No user was created.', apiError(err, 'The server refused.'));
      },
    });
  }

  async onAction(key: string, u: AdminUser): Promise<void> {
    this.roleFor.set(null);
    this.passwordFor.set(null);
    if (key === 'role') {
      this.nextRole = u.role;
      this.roleFor.set(u);
    } else if (key === 'password') {
      this.nextPassword = generatePassword();
      this.passwordFor.set(u);
    } else if (key === 'deactivate') {
      const ok = await this.confirm.ask({
        title: `Deactivate ${u.full_name}?`,
        body: 'They are signed out everywhere and cannot sign in. Everything they did stays on record. You can reactivate them later.',
        confirmLabel: 'Deactivate',
        danger: true,
      });
      if (ok) this.run(this.api.deactivate(u.id), `${u.full_name} deactivated.`);
    } else if (key === 'reactivate') {
      this.run(this.api.reactivate(u.id), `${u.full_name} can sign in again.`);
    } else if (key === 'delete') {
      const ok = await this.confirm.ask({
        title: `Delete ${u.full_name}?`,
        body: `${u.email} has never done anything the app keeps a record of, so the account is removed outright. This cannot be undone — create it again if you need it.`,
        confirmLabel: 'Delete user',
        danger: true,
      });
      if (ok) this.run(this.api.deleteUser(u.id), `${u.full_name} deleted.`);
    }
  }

  saveRole(u: AdminUser): void {
    this.run(this.api.updateUser(u.id, { role: this.nextRole }), `${u.full_name} is now ${ROLE_LABELS[this.nextRole as keyof typeof ROLE_LABELS]}.`, () => this.roleFor.set(null));
  }

  savePassword(u: AdminUser): void {
    this.run(this.api.setPassword(u.id, this.nextPassword), `New password set for ${u.full_name}.`, () => this.passwordFor.set(null), 'Tell them the new one yourself. They have been signed out.');
  }

  private run(call: Observable<unknown>, done: string, after?: () => void, detail?: string): void {
    this.saving.set(true);
    call.subscribe({
      next: () => {
        this.saving.set(false);
        after?.();
        this.load();
        this.notify.success(done, detail ?? null);
      },
      error: (err) => {
        this.saving.set(false);
        this.notify.error('Not changed.', apiError(err, 'The server refused.'));
      },
    });
  }
}
