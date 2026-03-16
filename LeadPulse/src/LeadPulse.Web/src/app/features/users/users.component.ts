import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { UserService } from '../../core/services/user.service';
import { UserResponse, CreateUserRequest, InviteUserRequest, PermissionsMatrix } from '../../core/models/user.model';

@Component({
  selector: 'app-users',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="users-page">
      <div class="page-header">
        <h2>User Management</h2>
        <div class="actions">
          <button class="btn-secondary" (click)="showInviteForm = !showInviteForm">Invite User</button>
          <button class="btn-primary" (click)="showCreateForm = !showCreateForm">Add User</button>
        </div>
      </div>

      <!-- Invite Form -->
      <div *ngIf="showInviteForm" class="form-card">
        <h3>Invite User</h3>
        <div class="form-row">
          <div class="form-group">
            <label>Email</label>
            <input type="email" [(ngModel)]="inviteRequest.email" name="inviteEmail">
          </div>
          <div class="form-group">
            <label>Role</label>
            <select [(ngModel)]="inviteRequest.role" name="inviteRole">
              <option value="TenantAdmin">Tenant Admin</option>
              <option value="Agent">Agent</option>
              <option value="Viewer">Viewer</option>
            </select>
          </div>
          <button class="btn-primary" (click)="invite()">Send Invitation</button>
        </div>
      </div>

      <!-- Create User Form -->
      <div *ngIf="showCreateForm" class="form-card">
        <h3>{{ editingUser ? 'Edit User' : 'Create User' }}</h3>
        <div class="form-grid">
          <div class="form-group">
            <label>First Name</label>
            <input [(ngModel)]="createRequest.firstName" name="firstName">
          </div>
          <div class="form-group">
            <label>Last Name</label>
            <input [(ngModel)]="createRequest.lastName" name="lastName">
          </div>
          <div class="form-group">
            <label>Email</label>
            <input type="email" [(ngModel)]="createRequest.email" name="email" [disabled]="!!editingUser">
          </div>
          <div class="form-group" *ngIf="!editingUser">
            <label>Password</label>
            <input type="password" [(ngModel)]="createRequest.password" name="password">
          </div>
          <div class="form-group">
            <label>Phone</label>
            <input [(ngModel)]="createRequest.phone" name="phone">
          </div>
          <div class="form-group">
            <label>Role</label>
            <select [(ngModel)]="createRequest.role" name="role">
              <option value="TenantAdmin">Tenant Admin</option>
              <option value="Agent">Agent</option>
              <option value="Viewer">Viewer</option>
            </select>
          </div>
        </div>
        <div *ngIf="permissionsMatrix" class="permissions-section">
          <h4>Permission Overrides</h4>
          <div class="permissions-grid">
            <label *ngFor="let p of permissionsMatrix.permissions" class="checkbox-label">
              <input type="checkbox" [checked]="isPermissionGranted(p)"
                (change)="togglePermission(p, $event)">
              {{ formatPermission(p) }}
            </label>
          </div>
        </div>
        <div class="form-actions">
          <button class="btn-secondary" (click)="cancelForm()">Cancel</button>
          <button class="btn-primary" (click)="editingUser ? updateUser() : createUser()">
            {{ editingUser ? 'Update' : 'Create' }}
          </button>
        </div>
        <div *ngIf="formError" class="error">{{ formError }}</div>
      </div>

      <!-- Users Table -->
      <div class="table-card">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Role</th>
              <th>MFA</th>
              <th>Status</th>
              <th>Last Login</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let user of users">
              <td>{{ user.firstName }} {{ user.lastName }}</td>
              <td>{{ user.email }}</td>
              <td><span class="badge" [class]="'badge-' + user.role.toLowerCase()">{{ user.role }}</span></td>
              <td>{{ user.mfaEnabled ? 'Enabled' : 'Off' }}</td>
              <td><span class="status" [class]="'status-' + user.status.toLowerCase()">{{ user.status }}</span></td>
              <td>{{ user.lastLoginAt ? (user.lastLoginAt | date:'short') : 'Never' }}</td>
              <td class="actions-cell">
                <button class="btn-sm" (click)="editUser(user)">Edit</button>
                <button *ngIf="user.status === 'Active'" class="btn-sm btn-warn" (click)="disableUser(user.id)">Disable</button>
                <button *ngIf="user.status === 'Disabled'" class="btn-sm btn-success" (click)="enableUser(user.id)">Enable</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pending Invitations -->
      <div class="table-card" *ngIf="invitations.length > 0">
        <h3>Pending Invitations</h3>
        <table>
          <thead>
            <tr><th>Email</th><th>Role</th><th>Invited By</th><th>Status</th><th>Expires</th></tr>
          </thead>
          <tbody>
            <tr *ngFor="let inv of invitations">
              <td>{{ inv.email }}</td>
              <td>{{ inv.role }}</td>
              <td>{{ inv.invitedBy }}</td>
              <td><span class="status" [class]="'status-' + inv.status.toLowerCase()">{{ inv.status }}</span></td>
              <td>{{ inv.expiresAt | date:'short' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Permissions Matrix -->
      <div class="table-card" *ngIf="permissionsMatrix">
        <h3>Role Permissions Matrix</h3>
        <table class="matrix-table">
          <thead>
            <tr>
              <th>Permission</th>
              <th *ngFor="let role of ['SuperAdmin', 'TenantAdmin', 'Agent', 'Viewer']">{{ role }}</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let p of permissionsMatrix.permissions">
              <td>{{ formatPermission(p) }}</td>
              <td *ngFor="let role of ['SuperAdmin', 'TenantAdmin', 'Agent', 'Viewer']" class="center">
                {{ permissionsMatrix.matrix[role]?.includes(p) ? '✓' : '—' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
  styles: [`
    .users-page { padding: 1.5rem; }
    .page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; }
    .page-header h2 { margin: 0; }
    .actions { display: flex; gap: 0.5rem; }
    .form-card, .table-card { background: white; border-radius: 8px; padding: 1.5rem; margin-bottom: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .form-row { display: flex; gap: 1rem; align-items: end; }
    .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    .form-group { margin-bottom: 0.75rem; }
    .form-group label { display: block; font-weight: 500; margin-bottom: 0.25rem; color: #374151; font-size: 0.875rem; }
    input, select { width: 100%; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px; box-sizing: border-box; }
    .permissions-section { margin-top: 1rem; }
    .permissions-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.5rem; }
    .checkbox-label { display: flex; align-items: center; gap: 0.5rem; font-size: 0.875rem; }
    .form-actions { display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1rem; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #e5e7eb; }
    th { font-weight: 600; color: #374151; font-size: 0.875rem; }
    .badge { padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
    .badge-tenantadmin { background: #dbeafe; color: #1d4ed8; }
    .badge-agent { background: #d1fae5; color: #065f46; }
    .badge-viewer { background: #e5e7eb; color: #374151; }
    .status { font-size: 0.875rem; }
    .status-active { color: #059669; }
    .status-disabled { color: #dc2626; }
    .status-pending { color: #d97706; }
    .status-expired { color: #6b7280; }
    .center { text-align: center; }
    .actions-cell { display: flex; gap: 0.25rem; }
    .btn-primary { padding: 0.5rem 1rem; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; }
    .btn-secondary { padding: 0.5rem 1rem; background: white; color: #374151; border: 1px solid #d1d5db; border-radius: 4px; cursor: pointer; }
    .btn-sm { padding: 0.25rem 0.5rem; font-size: 0.75rem; border: 1px solid #d1d5db; border-radius: 4px; cursor: pointer; background: white; }
    .btn-warn { color: #dc2626; border-color: #dc2626; }
    .btn-success { color: #059669; border-color: #059669; }
    .error { color: #ef4444; margin-top: 0.5rem; font-size: 0.875rem; }
    .matrix-table td, .matrix-table th { font-size: 0.8rem; }
    h3 { margin: 0 0 1rem; color: #1a1f36; }
    h4 { margin: 0 0 0.5rem; color: #374151; font-size: 0.875rem; }
  `]
})
export class UsersComponent implements OnInit {
  users: UserResponse[] = [];
  invitations: any[] = [];
  permissionsMatrix: PermissionsMatrix | null = null;

  showCreateForm = false;
  showInviteForm = false;
  editingUser: UserResponse | null = null;
  formError = '';

  createRequest: CreateUserRequest = this.emptyCreateRequest();
  inviteRequest: InviteUserRequest = { email: '', role: 'Agent' };
  permissionOverrides: Record<string, boolean> = {};

  constructor(private userService: UserService) {}

  ngOnInit(): void {
    this.loadUsers();
    this.loadInvitations();
    this.loadPermissionsMatrix();
  }

  loadUsers(): void {
    this.userService.getAll().subscribe(users => this.users = users);
  }

  loadInvitations(): void {
    this.userService.getInvitations().subscribe(inv => this.invitations = inv);
  }

  loadPermissionsMatrix(): void {
    this.userService.getPermissionsMatrix().subscribe(m => this.permissionsMatrix = m);
  }

  createUser(): void {
    this.formError = '';
    this.createRequest.permissions = Object.keys(this.permissionOverrides).length > 0
      ? this.permissionOverrides : undefined;

    this.userService.create(this.createRequest).subscribe({
      next: () => { this.cancelForm(); this.loadUsers(); },
      error: (err) => this.formError = err.error?.error || 'Failed to create user'
    });
  }

  editUser(user: UserResponse): void {
    this.editingUser = user;
    this.createRequest = {
      firstName: user.firstName,
      lastName: user.lastName,
      email: user.email,
      password: '',
      phone: user.phone,
      role: user.role
    };
    this.permissionOverrides = user.permissions ? { ...user.permissions } : {};
    this.showCreateForm = true;
  }

  updateUser(): void {
    if (!this.editingUser) return;
    this.formError = '';

    this.userService.update(this.editingUser.id, {
      firstName: this.createRequest.firstName,
      lastName: this.createRequest.lastName,
      phone: this.createRequest.phone,
      role: this.createRequest.role,
      permissions: Object.keys(this.permissionOverrides).length > 0 ? this.permissionOverrides : undefined
    }).subscribe({
      next: () => { this.cancelForm(); this.loadUsers(); },
      error: (err) => this.formError = err.error?.error || 'Failed to update user'
    });
  }

  disableUser(id: number): void {
    this.userService.disable(id).subscribe(() => this.loadUsers());
  }

  enableUser(id: number): void {
    this.userService.enable(id).subscribe(() => this.loadUsers());
  }

  invite(): void {
    this.userService.invite(this.inviteRequest).subscribe({
      next: () => { this.showInviteForm = false; this.inviteRequest = { email: '', role: 'Agent' }; this.loadInvitations(); },
      error: (err) => alert(err.error?.error || 'Failed to send invitation')
    });
  }

  cancelForm(): void {
    this.showCreateForm = false;
    this.editingUser = null;
    this.createRequest = this.emptyCreateRequest();
    this.permissionOverrides = {};
    this.formError = '';
  }

  isPermissionGranted(permission: string): boolean {
    if (this.permissionOverrides[permission] !== undefined) return this.permissionOverrides[permission];
    const defaults = this.permissionsMatrix?.matrix[this.createRequest.role] || [];
    return defaults.includes(permission);
  }

  togglePermission(permission: string, event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    const defaults = this.permissionsMatrix?.matrix[this.createRequest.role] || [];
    const isDefault = defaults.includes(permission);
    if (checked === isDefault) {
      delete this.permissionOverrides[permission];
    } else {
      this.permissionOverrides[permission] = checked;
    }
  }

  formatPermission(p: string): string {
    return p.replace(/([A-Z])/g, ' $1').trim();
  }

  private emptyCreateRequest(): CreateUserRequest {
    return { firstName: '', lastName: '', email: '', password: '', role: 'Agent' };
  }
}
