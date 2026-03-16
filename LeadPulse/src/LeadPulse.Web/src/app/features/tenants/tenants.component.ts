import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TenantService } from '../../core/services/tenant.service';
import { Tenant, CreateTenantRequest, SubscriptionPlan } from '../../core/models/tenant.model';

@Component({
  selector: 'app-tenants',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="tenants-page">
      <div class="page-header">
        <h2>Tenant Administration</h2>
        <div class="actions">
          <button class="btn-secondary" (click)="migrateAll()">Migrate All</button>
          <button class="btn-primary" (click)="showCreateForm = !showCreateForm">Create Tenant</button>
        </div>
      </div>

      <!-- Create Tenant Form -->
      <div *ngIf="showCreateForm" class="form-card">
        <h3>New Tenant</h3>
        <div class="form-grid">
          <div class="form-group">
            <label>Name</label>
            <input [(ngModel)]="newTenant.name" name="name" (ngModelChange)="generateSlug()">
          </div>
          <div class="form-group">
            <label>Slug</label>
            <input [(ngModel)]="newTenant.slug" name="slug">
          </div>
          <div class="form-group">
            <label>Industry</label>
            <input [(ngModel)]="newTenant.industry" name="industry">
          </div>
          <div class="form-group">
            <label>Plan</label>
            <select [(ngModel)]="newTenant.planId" name="planId">
              <option [ngValue]="0" disabled>Select a plan</option>
              <option *ngFor="let plan of plans" [ngValue]="plan.id">{{ plan.name }} - \${{ plan.priceMonthly }}/mo</option>
            </select>
          </div>
          <div class="form-group">
            <label>Billing Email</label>
            <input type="email" [(ngModel)]="newTenant.billingEmail" name="billingEmail">
          </div>
        </div>
        <div class="form-actions">
          <button class="btn-secondary" (click)="showCreateForm = false">Cancel</button>
          <button class="btn-primary" (click)="create()">Create</button>
        </div>
        <div *ngIf="formError" class="error">{{ formError }}</div>
      </div>

      <!-- Plan Update Modal -->
      <div *ngIf="editingPlanTenantId !== null" class="modal-overlay" (click)="editingPlanTenantId = null">
        <div class="modal-card" (click)="$event.stopPropagation()">
          <h3>Change Plan</h3>
          <div class="form-group">
            <label>Select New Plan</label>
            <select [(ngModel)]="selectedPlanId" name="selectedPlan">
              <option *ngFor="let plan of plans" [ngValue]="plan.id">
                {{ plan.name }} - \${{ plan.priceMonthly }}/mo ({{ plan.maxUsers }} users)
              </option>
            </select>
          </div>
          <div class="form-actions">
            <button class="btn-secondary" (click)="editingPlanTenantId = null">Cancel</button>
            <button class="btn-primary" (click)="updatePlan(editingPlanTenantId!)">Update Plan</button>
          </div>
        </div>
      </div>

      <!-- Success Message -->
      <div *ngIf="successMessage" class="success-message">{{ successMessage }}</div>

      <!-- Created Credentials -->
      <div *ngIf="createdCredentials" class="credentials-card">
        <h3>Tenant Login Credentials</h3>
        <p>Save these credentials — the password cannot be retrieved later.</p>
        <div class="credential-row"><strong>Tenant ID:</strong> <code>{{ createdCredentials.tenantId }}</code></div>
        <div class="credential-row"><strong>Email:</strong> <code>{{ createdCredentials.email }}</code></div>
        <div class="credential-row"><strong>Password:</strong> <code>{{ createdCredentials.password }}</code></div>
        <p class="credential-note">The user will be asked to change their password on first login.</p>
        <button class="btn-secondary" (click)="createdCredentials = null">Dismiss</button>
      </div>

      <!-- Tenants Table -->
      <div class="table-card">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Slug</th>
              <th>Industry</th>
              <th>Plan</th>
              <th>Status</th>
              <th>Billing Email</th>
              <th>Database</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let tenant of tenants">
              <td>{{ tenant.name }}</td>
              <td><code>{{ tenant.slug }}</code></td>
              <td>{{ tenant.industry }}</td>
              <td>{{ tenant.planName }}</td>
              <td><span class="status-badge" [ngClass]="statusClass(tenant.status)">{{ tenant.status }}</span></td>
              <td>{{ tenant.billingEmail }}</td>
              <td><code>{{ tenant.databaseName || '—' }}</code></td>
              <td>{{ tenant.createdAt | date:'mediumDate' }}</td>
              <td class="actions-cell">
                <button class="btn-sm" (click)="editingPlanTenantId = tenant.id; selectedPlanId = tenant.planId">Edit Plan</button>
                <button *ngIf="tenant.status === 'Active'" class="btn-sm btn-warn" (click)="suspend(tenant.id)">Suspend</button>
                <button *ngIf="tenant.status === 'Suspended'" class="btn-sm btn-success" (click)="reactivate(tenant.id)">Reactivate</button>
                <button *ngIf="tenant.status === 'Active'" class="btn-sm btn-impersonate" (click)="impersonate(tenant.id)">Impersonate</button>
                <button class="btn-sm btn-danger" (click)="deleteTenant(tenant.id)">Delete</button>
              </td>
            </tr>
          </tbody>
          <tbody *ngIf="tenants.length === 0">
            <tr><td colspan="9" class="empty">No tenants found.</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
  styles: [`
    .tenants-page { padding: 1.5rem; }
    .page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; }
    .page-header h2 { margin: 0; }
    .actions { display: flex; gap: 0.5rem; }
    .form-card, .table-card { background: white; border-radius: 8px; padding: 1.5rem; margin-bottom: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    .form-group { margin-bottom: 0.75rem; }
    .form-group label { display: block; font-weight: 500; margin-bottom: 0.25rem; color: #374151; font-size: 0.875rem; }
    input, select { width: 100%; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px; box-sizing: border-box; }
    .form-actions { display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1rem; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #e5e7eb; }
    th { font-weight: 600; color: #374151; font-size: 0.875rem; }
    code { background: #f3f4f6; padding: 0.125rem 0.375rem; border-radius: 3px; font-size: 0.8rem; }
    .status-badge { padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
    .status-active { background: #d1fae5; color: #065f46; }
    .status-suspended { background: #fef3c7; color: #92400e; }
    .status-pendingsetup { background: #dbeafe; color: #1d4ed8; }
    .status-deleted { background: #fee2e2; color: #991b1b; }
    .actions-cell { display: flex; gap: 0.25rem; flex-wrap: wrap; }
    .btn-primary { padding: 0.5rem 1rem; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; }
    .btn-primary:hover { background: #1d4ed8; }
    .btn-secondary { padding: 0.5rem 1rem; background: white; color: #374151; border: 1px solid #d1d5db; border-radius: 4px; cursor: pointer; }
    .btn-secondary:hover { background: #f9fafb; }
    .btn-sm { padding: 0.25rem 0.5rem; font-size: 0.75rem; border: 1px solid #d1d5db; border-radius: 4px; cursor: pointer; background: white; }
    .btn-sm:hover { background: #f3f4f6; }
    .btn-warn { color: #d97706; border-color: #d97706; }
    .btn-success { color: #059669; border-color: #059669; }
    .btn-impersonate { color: #7c3aed; border-color: #7c3aed; }
    .btn-danger { color: #dc2626; border-color: #dc2626; }
    .error { color: #ef4444; margin-top: 0.5rem; font-size: 0.875rem; }
    .empty { text-align: center; color: #9ca3af; padding: 2rem; }
    h3 { margin: 0 0 1rem; color: #1a1f36; }
    .success-message { background: #d1fae5; color: #065f46; padding: 0.75rem 1rem; border-radius: 8px; margin-bottom: 1rem; font-size: 0.875rem; }
    .modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000; }
    .modal-card { background: white; border-radius: 8px; padding: 1.5rem; width: 480px; max-width: 90vw; box-shadow: 0 4px 16px rgba(0,0,0,0.2); }
    .credentials-card { background: #eff6ff; border: 2px solid #2563eb; border-radius: 8px; padding: 1.5rem; margin-bottom: 1rem; }
    .credentials-card h3 { margin: 0 0 0.5rem; color: #1d4ed8; }
    .credentials-card p { margin: 0 0 0.75rem; font-size: 0.875rem; color: #374151; }
    .credential-row { margin-bottom: 0.5rem; font-size: 0.925rem; }
    .credential-row code { background: white; padding: 0.2rem 0.5rem; border-radius: 3px; font-size: 0.9rem; user-select: all; }
    .credential-note { color: #6b7280; font-style: italic; font-size: 0.8rem; }
  `]
})
export class TenantsComponent implements OnInit {
  tenants: Tenant[] = [];
  plans: SubscriptionPlan[] = [];
  showCreateForm = false;
  newTenant: CreateTenantRequest = { name: '', slug: '', industry: '', planId: 0, billingEmail: '' };
  editingPlanTenantId: number | null = null;
  selectedPlanId = 0;
  formError = '';
  successMessage = '';
  createdCredentials: { tenantId: number; email: string; password: string } | null = null;

  constructor(private tenantService: TenantService) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.tenantService.getAll().subscribe(t => this.tenants = t);
    this.tenantService.getPlans().subscribe(p => this.plans = p);
  }

  generateSlug(): void {
    this.newTenant.slug = this.newTenant.name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '');
  }

  create(): void {
    this.formError = '';
    if (!this.newTenant.name.trim()) { this.formError = 'Name is required'; return; }
    if (!this.newTenant.slug.trim()) { this.formError = 'Slug is required'; return; }
    if (!this.newTenant.planId) { this.formError = 'Please select a plan'; return; }

    const slug = this.newTenant.slug;
    this.tenantService.create(this.newTenant).subscribe({
      next: (tenant) => {
        this.showCreateForm = false;
        this.newTenant = { name: '', slug: '', industry: '', planId: 0, billingEmail: '' };
        this.createdCredentials = {
          tenantId: tenant.id,
          email: `admin@${slug}.leadpulse.com`,
          password: 'ChangeMe123!'
        };
        this.successMessage = 'Tenant created successfully!';
        this.load();
      },
      error: (err) => {
        if (err.error?.errors) {
          const msgs = Object.values(err.error.errors).flat();
          this.formError = msgs.join('. ');
        } else {
          this.formError = err.error?.error || err.error?.title || 'Failed to create tenant';
        }
      }
    });
  }

  updatePlan(id: number): void {
    this.tenantService.updatePlan(id, this.selectedPlanId).subscribe({
      next: () => {
        this.editingPlanTenantId = null;
        this.load();
      },
      error: (err) => alert(err.error?.error || 'Failed to update plan')
    });
  }

  suspend(id: number): void {
    this.tenantService.suspend(id).subscribe(() => this.load());
  }

  reactivate(id: number): void {
    this.tenantService.reactivate(id).subscribe(() => this.load());
  }

  deleteTenant(id: number): void {
    if (!confirm('Are you sure you want to delete this tenant? This action cannot be undone.')) return;
    this.tenantService.delete(id).subscribe(() => this.load());
  }

  impersonate(id: number): void {
    this.tenantService.impersonate(id).subscribe({
      next: (res) => {
        localStorage.setItem('impersonate_token', res.token);
        localStorage.setItem('impersonate_tenantId', res.tenantId.toString());
        localStorage.setItem('impersonate_tenantName', res.tenantName);
        this.successMessage = `Now impersonating tenant: ${res.tenantName}`;
        setTimeout(() => this.successMessage = '', 5000);
      },
      error: (err) => alert(err.error?.error || 'Failed to impersonate tenant')
    });
  }

  migrateAll(): void {
    if (!confirm('Run database migrations for all tenants?')) return;
    this.tenantService.migrateAll().subscribe({
      next: () => {
        this.successMessage = 'All tenant databases migrated successfully.';
        setTimeout(() => this.successMessage = '', 5000);
      },
      error: (err) => alert(err.error?.error || 'Migration failed')
    });
  }

  statusClass(status: string): string {
    const key = status.toLowerCase().replace(/\s+/g, '');
    return `status-${key}`;
  }
}
