import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { KeywordService } from '../../core/services/keyword.service';
import { KeywordRuleResponse, CreateKeywordRuleRequest } from '../../core/models/keyword.model';

@Component({
  selector: 'app-keywords',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="keywords-page">
      <div class="page-header">
        <h2>Keyword Rules</h2>
        <div class="actions">
          <select [(ngModel)]="filterCategory" (change)="loadKeywords()" name="filterCat" class="filter-select">
            <option value="">All Categories</option>
            <option value="Home">Home</option>
            <option value="Auto">Auto</option>
            <option value="Life">Life</option>
            <option value="Health">Health</option>
            <option value="Commercial">Commercial</option>
          </select>
          <button class="btn-secondary" (click)="exportCsv()">Export CSV</button>
          <button class="btn-primary" (click)="showForm = !showForm">Add Keyword</button>
        </div>
      </div>

      <!-- Add/Edit Form -->
      <div *ngIf="showForm" class="form-card">
        <h3>{{ editingRule ? 'Edit' : 'Add' }} Keyword Rule</h3>
        <div class="form-grid">
          <div class="form-group">
            <label>Keyword / Pattern</label>
            <input [(ngModel)]="formData.keyword" name="keyword" placeholder="e.g. home insurance">
          </div>
          <div class="form-group">
            <label>Match Type</label>
            <select [(ngModel)]="formData.matchType" name="matchType">
              <option value="Exact">Exact</option>
              <option value="Contains">Contains</option>
              <option value="Similar">Similar / Fuzzy</option>
              <option value="Regex">Regex</option>
              <option value="Semantic">Semantic (AI)</option>
            </select>
          </div>
          <div class="form-group">
            <label>Category</label>
            <select [(ngModel)]="formData.category" name="category">
              <option [ngValue]="undefined">Any</option>
              <option value="Home">Home</option>
              <option value="Auto">Auto</option>
              <option value="Life">Life</option>
              <option value="Health">Health</option>
              <option value="Commercial">Commercial</option>
            </select>
          </div>
          <div class="form-group">
            <label>Score Boost</label>
            <input type="number" [(ngModel)]="formData.scoreBoost" name="boost" min="1" max="50">
          </div>
          <div class="form-group" *ngIf="formData.matchType === 'Similar'">
            <label>Similarity Threshold (%)</label>
            <input type="number" [(ngModel)]="formData.similarityThreshold" name="threshold" min="50" max="100">
          </div>
          <div class="form-group">
            <label>Synonyms (comma-separated)</label>
            <input [(ngModel)]="synonymsText" name="synonyms" placeholder="auto insurance, vehicle coverage">
          </div>
          <div class="form-group">
            <label>Negative Keywords (comma-separated)</label>
            <input [(ngModel)]="negativesText" name="negatives" placeholder="spam, selling">
          </div>
          <div class="form-group">
            <label>Platforms</label>
            <div class="checkbox-row">
              <label class="checkbox-label">
                <input type="checkbox" [checked]="selectedPlatforms.length === 0"
                  (change)="selectAllPlatforms()"> All
              </label>
              <label *ngFor="let p of allPlatforms" class="checkbox-label">
                <input type="checkbox" [checked]="selectedPlatforms.includes(p)"
                  (change)="togglePlatform(p, $event)"> {{ p }}
              </label>
            </div>
          </div>
        </div>
        <div class="form-actions">
          <button class="btn-secondary" (click)="cancelForm()">Cancel</button>
          <button class="btn-primary" (click)="saveRule()">{{ editingRule ? 'Update' : 'Create' }}</button>
        </div>
        <div *ngIf="formError" class="error">{{ formError }}</div>
      </div>

      <!-- Keywords Table -->
      <div class="table-card">
        <table>
          <thead>
            <tr>
              <th>Keyword</th>
              <th>Match Type</th>
              <th>Category</th>
              <th>Boost</th>
              <th>Hits (30d)</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let rule of keywords" [class.inactive]="!rule.isActive">
              <td>
                <strong>{{ rule.keyword }}</strong>
                <div *ngIf="rule.synonyms?.length" class="sub-text">
                  Synonyms: {{ rule.synonyms!.join(', ') }}
                </div>
              </td>
              <td><span class="badge" [class]="'badge-' + rule.matchType.toLowerCase()">{{ rule.matchType }}</span></td>
              <td>{{ rule.category || 'Any' }}</td>
              <td>+{{ rule.scoreBoost }}</td>
              <td>{{ rule.hitCount30d }}</td>
              <td>
                <span class="status" [class.status-active]="rule.isActive" [class.status-disabled]="!rule.isActive">
                  {{ rule.isActive ? 'Active' : 'Disabled' }}
                </span>
              </td>
              <td class="actions-cell">
                <button class="btn-sm" (click)="editRule(rule)">Edit</button>
                <button class="btn-sm" (click)="toggleRule(rule)">{{ rule.isActive ? 'Disable' : 'Enable' }}</button>
                <button class="btn-sm btn-danger" (click)="deleteRule(rule)">Delete</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p *ngIf="keywords.length === 0" class="empty-text">No keyword rules configured yet.</p>
      </div>
    </div>
  `,
  styles: [`
    .keywords-page { padding: 1.5rem; }
    .page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; }
    .page-header h2 { margin: 0; }
    .actions { display: flex; gap: 0.5rem; align-items: center; }
    .filter-select { padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px; }
    .form-card, .table-card { background: white; border-radius: 8px; padding: 1.5rem; margin-bottom: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    .form-group { margin-bottom: 0.5rem; }
    .form-group label { display: block; font-weight: 500; margin-bottom: 0.25rem; color: #374151; font-size: 0.875rem; }
    input, select { width: 100%; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px; box-sizing: border-box; }
    .checkbox-row { display: flex; gap: 1rem; }
    .checkbox-label { display: flex; align-items: center; gap: 0.25rem; font-size: 0.875rem; }
    .form-actions { display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1rem; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #e5e7eb; }
    th { font-weight: 600; color: #374151; font-size: 0.875rem; }
    .sub-text { font-size: 0.75rem; color: #6b7280; margin-top: 0.2rem; }
    .badge { padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.7rem; font-weight: 600; }
    .badge-exact { background: #dbeafe; color: #1d4ed8; }
    .badge-contains { background: #d1fae5; color: #065f46; }
    .badge-similar { background: #fef3c7; color: #92400e; }
    .badge-regex { background: #ede9fe; color: #5b21b6; }
    .badge-semantic { background: #fce7f3; color: #9d174d; }
    .status { font-size: 0.875rem; }
    .status-active { color: #059669; }
    .status-disabled { color: #6b7280; }
    .inactive { opacity: 0.6; }
    .actions-cell { display: flex; gap: 0.25rem; }
    .empty-text { color: #6b7280; text-align: center; padding: 2rem; }
    .btn-primary { padding: 0.5rem 1rem; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; }
    .btn-secondary { padding: 0.5rem 1rem; background: white; color: #374151; border: 1px solid #d1d5db; border-radius: 4px; cursor: pointer; }
    .btn-sm { padding: 0.25rem 0.5rem; font-size: 0.75rem; border: 1px solid #d1d5db; border-radius: 4px; cursor: pointer; background: white; }
    .btn-danger { color: #dc2626; border-color: #dc2626; }
    .error { color: #ef4444; margin-top: 0.5rem; font-size: 0.875rem; }
    h3 { margin: 0 0 1rem; color: #1a1f36; }
  `]
})
export class KeywordsComponent implements OnInit {
  keywords: KeywordRuleResponse[] = [];
  showForm = false;
  editingRule: KeywordRuleResponse | null = null;
  formError = '';
  filterCategory = '';

  formData: CreateKeywordRuleRequest = this.emptyForm();
  synonymsText = '';
  negativesText = '';
  selectedPlatforms: string[] = [];
  allPlatforms = ['Reddit', 'LinkedIn', 'Facebook', 'Nextdoor', 'X'];

  constructor(private keywordService: KeywordService) {}

  ngOnInit(): void {
    this.loadKeywords();
  }

  loadKeywords(): void {
    this.keywordService.getAll(this.filterCategory || undefined).subscribe(k => this.keywords = k);
  }

  saveRule(): void {
    this.formError = '';
    this.formData.synonyms = this.synonymsText ? this.synonymsText.split(',').map(s => s.trim()).filter(s => s) : undefined;
    this.formData.negativeKeywords = this.negativesText ? this.negativesText.split(',').map(s => s.trim()).filter(s => s) : undefined;
    this.formData.platforms = this.selectedPlatforms.length > 0 ? this.selectedPlatforms : undefined;

    if (this.editingRule) {
      this.keywordService.update(this.editingRule.id, { ...this.formData, isActive: this.editingRule.isActive }).subscribe({
        next: () => { this.cancelForm(); this.loadKeywords(); },
        error: (err) => this.formError = err.error?.error || 'Failed to update'
      });
    } else {
      this.keywordService.create(this.formData).subscribe({
        next: () => { this.cancelForm(); this.loadKeywords(); },
        error: (err) => this.formError = err.error?.error || 'Failed to create'
      });
    }
  }

  editRule(rule: KeywordRuleResponse): void {
    this.editingRule = rule;
    this.formData = {
      keyword: rule.keyword,
      matchType: rule.matchType,
      category: rule.category || undefined,
      scoreBoost: rule.scoreBoost,
      similarityThreshold: rule.similarityThreshold
    };
    this.synonymsText = rule.synonyms?.join(', ') || '';
    this.negativesText = rule.negativeKeywords?.join(', ') || '';
    this.selectedPlatforms = rule.platforms ? [...rule.platforms] : [];
    this.showForm = true;
  }

  toggleRule(rule: KeywordRuleResponse): void {
    this.keywordService.toggle(rule.id).subscribe(() => this.loadKeywords());
  }

  deleteRule(rule: KeywordRuleResponse): void {
    if (confirm(`Delete keyword rule "${rule.keyword}"?`)) {
      this.keywordService.delete(rule.id).subscribe(() => this.loadKeywords());
    }
  }

  exportCsv(): void {
    this.keywordService.exportCsv().subscribe(blob => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'keywords.csv';
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  selectAllPlatforms(): void {
    this.selectedPlatforms = [];
  }

  togglePlatform(platform: string, event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    if (checked) {
      this.selectedPlatforms.push(platform);
    } else {
      this.selectedPlatforms = this.selectedPlatforms.filter(p => p !== platform);
    }
  }

  cancelForm(): void {
    this.showForm = false;
    this.editingRule = null;
    this.formData = this.emptyForm();
    this.synonymsText = '';
    this.negativesText = '';
    this.selectedPlatforms = [];
    this.formError = '';
  }

  private emptyForm(): CreateKeywordRuleRequest {
    return { keyword: '', matchType: 'Contains', scoreBoost: 10, similarityThreshold: 75 };
  }
}
