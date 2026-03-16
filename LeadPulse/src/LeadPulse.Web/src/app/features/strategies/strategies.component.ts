import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { StrategyService } from '../../core/services/strategy.service';
import { StrategyResponse, CreateStrategyRequest } from '../../core/models/strategy.model';

@Component({
  selector: 'app-strategies',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="strategies-page">
      <div class="page-header">
        <h2>Strategies</h2>
        <button class="btn-primary" (click)="showForm = !showForm">New Strategy</button>
      </div>

      <div *ngIf="showForm" class="form-card">
        <h3>{{ editing ? 'Edit' : 'Create' }} Strategy</h3>
        <div class="form-grid">
          <div class="form-group">
            <label>Name</label>
            <input [(ngModel)]="formData.name" name="name" placeholder="e.g. Texas Home Insurance Leads">
          </div>
          <div class="form-group">
            <label>Min Score</label>
            <input type="number" [(ngModel)]="formData.minScore" name="minScore" min="0" max="100">
          </div>
          <div class="form-group">
            <label>Categories (comma-separated)</label>
            <input [(ngModel)]="categoriesText" name="categories" placeholder="Home, Auto">
          </div>
          <div class="form-group">
            <label>Min Urgency</label>
            <select [(ngModel)]="formData.minUrgency" name="minUrg">
              <option [ngValue]="undefined">Any</option>
              <option value="Cool">Cool</option>
              <option value="Warm">Warm</option>
              <option value="Hot">Hot</option>
            </select>
          </div>
          <div class="form-group">
            <label>Zip Codes (comma-separated)</label>
            <input [(ngModel)]="zipsText" name="zips" placeholder="75024, 75025">
          </div>
          <div class="form-group">
            <label>Max Daily Prospects</label>
            <input type="number" [(ngModel)]="formData.maxDailyProspects" name="maxDaily" min="1" max="100">
          </div>
        </div>
        <div class="form-actions">
          <button class="btn-secondary" (click)="cancelForm()">Cancel</button>
          <button class="btn-primary" (click)="save()">{{ editing ? 'Update' : 'Create' }}</button>
        </div>
        <div *ngIf="formError" class="error">{{ formError }}</div>
      </div>

      <div class="strategies-grid">
        <div *ngFor="let s of strategies" class="strategy-card" [class.inactive]="!s.isActive">
          <div class="card-header">
            <h4>{{ s.name }}</h4>
            <span class="status" [class.active]="s.isActive">{{ s.isActive ? 'Active' : 'Inactive' }}</span>
          </div>
          <div class="card-details">
            <div><strong>Min Score:</strong> {{ s.minScore }}</div>
            <div><strong>Max Daily:</strong> {{ s.maxDailyProspects }}</div>
            <div *ngIf="s.targetCategories"><strong>Categories:</strong> {{ s.targetCategories!.join(', ') }}</div>
            <div *ngIf="s.minUrgency"><strong>Min Urgency:</strong> {{ s.minUrgency }}</div>
            <div *ngIf="s.targetZipCodes"><strong>Zip Codes:</strong> {{ s.targetZipCodes!.join(', ') }}</div>
          </div>
          <div class="card-actions">
            <button class="btn-sm" (click)="edit(s)">Edit</button>
            <button class="btn-sm btn-accent" (click)="generate(s)">Generate List</button>
            <button class="btn-sm btn-danger" (click)="deleteStrategy(s)">Delete</button>
          </div>
        </div>
      </div>

      <p *ngIf="strategies.length === 0 && !showForm" class="empty-text">No strategies configured yet.</p>
    </div>
  `,
  styles: [`
    .strategies-page { padding: 1.5rem; }
    .page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; }
    .page-header h2 { margin: 0; }
    .form-card { background: white; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    .form-group label { display: block; font-weight: 500; margin-bottom: 0.25rem; color: #374151; font-size: 0.875rem; }
    input, select { width: 100%; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px; box-sizing: border-box; }
    .form-actions { display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1rem; }
    .strategies-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 1rem; }
    .strategy-card { background: white; border-radius: 8px; padding: 1.25rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .strategy-card.inactive { opacity: 0.6; }
    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; }
    .card-header h4 { margin: 0; }
    .status { font-size: 0.75rem; font-weight: 600; }
    .status.active { color: #059669; }
    .card-details { font-size: 0.875rem; display: grid; gap: 0.25rem; margin-bottom: 0.75rem; }
    .card-actions { display: flex; gap: 0.5rem; }
    .empty-text { color: #6b7280; text-align: center; padding: 2rem; }
    .btn-primary { padding: 0.5rem 1rem; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; }
    .btn-secondary { padding: 0.5rem 1rem; background: white; color: #374151; border: 1px solid #d1d5db; border-radius: 4px; cursor: pointer; }
    .btn-sm { padding: 0.3rem 0.6rem; font-size: 0.75rem; border: 1px solid #d1d5db; border-radius: 4px; cursor: pointer; background: white; }
    .btn-accent { color: #2563eb; border-color: #2563eb; }
    .btn-danger { color: #dc2626; border-color: #dc2626; }
    .error { color: #ef4444; margin-top: 0.5rem; font-size: 0.875rem; }
    h3 { margin: 0 0 1rem; color: #1a1f36; }
  `]
})
export class StrategiesComponent implements OnInit {
  strategies: StrategyResponse[] = [];
  showForm = false;
  editing: StrategyResponse | null = null;
  formError = '';
  formData: CreateStrategyRequest = this.emptyForm();
  categoriesText = '';
  zipsText = '';

  constructor(private strategyService: StrategyService) {}

  ngOnInit(): void { this.load(); }

  load(): void { this.strategyService.getAll().subscribe(s => this.strategies = s); }

  save(): void {
    this.formError = '';
    this.formData.targetCategories = this.categoriesText ? this.categoriesText.split(',').map(s => s.trim()).filter(s => s) : undefined;
    this.formData.targetZipCodes = this.zipsText ? this.zipsText.split(',').map(s => s.trim()).filter(s => s) : undefined;

    if (this.editing) {
      this.strategyService.update(this.editing.id, { ...this.formData, isActive: this.editing.isActive }).subscribe({
        next: () => { this.cancelForm(); this.load(); },
        error: err => this.formError = err.error?.error || 'Failed'
      });
    } else {
      this.strategyService.create(this.formData).subscribe({
        next: () => { this.cancelForm(); this.load(); },
        error: err => this.formError = err.error?.error || 'Failed'
      });
    }
  }

  edit(s: StrategyResponse): void {
    this.editing = s;
    this.formData = { name: s.name, minScore: s.minScore, maxDailyProspects: s.maxDailyProspects, minUrgency: s.minUrgency || undefined };
    this.categoriesText = s.targetCategories?.join(', ') || '';
    this.zipsText = s.targetZipCodes?.join(', ') || '';
    this.showForm = true;
  }

  generate(s: StrategyResponse): void {
    this.strategyService.generateDailyList(s.id).subscribe({
      next: () => alert('Daily list generated!'),
      error: err => alert(err.error?.error || 'Failed to generate')
    });
  }

  deleteStrategy(s: StrategyResponse): void {
    if (confirm(`Delete strategy "${s.name}"?`)) {
      this.strategyService.delete(s.id).subscribe(() => this.load());
    }
  }

  cancelForm(): void {
    this.showForm = false; this.editing = null; this.formData = this.emptyForm();
    this.categoriesText = ''; this.zipsText = ''; this.formError = '';
  }

  private emptyForm(): CreateStrategyRequest {
    return { name: '', minScore: 50, maxDailyProspects: 10 };
  }
}
