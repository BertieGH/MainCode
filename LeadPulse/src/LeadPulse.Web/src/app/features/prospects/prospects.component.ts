import { Component, OnInit, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ProspectService } from '../../core/services/prospect.service';
import { ProspectResponse, ProspectFilter } from '../../core/models/prospect.model';

interface ColumnDef {
  key: string;
  label: string;
  visible: boolean;
}

@Component({
  selector: 'app-prospects',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="prospects-page">
      <div class="page-header">
        <h2>Prospects</h2>
        <div class="actions">
          <button class="btn-sm" [class.active]="viewMode === 'table'" (click)="viewMode = 'table'">Table</button>
          <button class="btn-sm" [class.active]="viewMode === 'card'" (click)="viewMode = 'card'">Cards</button>
          <div class="column-picker-wrapper">
            <button class="btn-icon" title="Show/Hide Columns" (click)="toggleColumnPicker($event)">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z"/></svg>
            </button>
            <div class="column-picker" *ngIf="showColumnPicker" (click)="$event.stopPropagation()">
              <div class="picker-header">Show/Hide Columns</div>
              <label *ngFor="let col of columns" class="picker-item">
                <input type="checkbox" [(ngModel)]="col.visible" [name]="'col_' + col.key" />
                {{ col.label }}
              </label>
            </div>
          </div>
          <button class="btn-secondary" (click)="exportCsv()">Export CSV</button>
        </div>
      </div>

      <!-- Filters -->
      <div class="filter-bar">
        <select [(ngModel)]="filter.category" (change)="loadProspects()" name="cat">
          <option value="">All Categories</option>
          <option *ngFor="let c of categories" [value]="c">{{ c }}</option>
        </select>
        <select [(ngModel)]="filter.urgency" (change)="loadProspects()" name="urg">
          <option value="">All Urgency</option>
          <option value="Hot">Hot</option>
          <option value="Warm">Warm</option>
          <option value="Cool">Cool</option>
        </select>
        <select [(ngModel)]="filter.platform" (change)="loadProspects()" name="plat">
          <option value="">All Platforms</option>
          <option value="LinkedIn">LinkedIn</option>
          <option value="Facebook">Facebook</option>
          <option value="Nextdoor">Nextdoor</option>
          <option value="X">X</option>
        </select>
        <select [(ngModel)]="filter.status" (change)="loadProspects()" name="stat">
          <option value="">All Status</option>
          <option value="New">New</option>
          <option value="Viewed">Viewed</option>
          <option value="Contacted">Contacted</option>
          <option value="Converted">Converted</option>
          <option value="Dismissed">Dismissed</option>
        </select>
      </div>

      <!-- Table View -->
      <div *ngIf="viewMode === 'table'" class="table-card">
        <table>
          <thead>
            <tr>
              <th *ngIf="isVisible('name')" class="sortable-th" (click)="toggleSort('name')">Name <span class="sort-icon">{{ getSortIcon('name') }}</span></th>
              <th *ngIf="isVisible('score')" class="sortable-th" (click)="toggleSort('score')">Score <span class="sort-icon">{{ getSortIcon('score') }}</span></th>
              <th *ngIf="isVisible('intentScore')" class="sortable-th" (click)="toggleSort('intentScore')">Intent <span class="sort-icon">{{ getSortIcon('intentScore') }}</span></th>
              <th *ngIf="isVisible('urgency')" class="sortable-th" (click)="toggleSort('urgency')">Urgency <span class="sort-icon">{{ getSortIcon('urgency') }}</span></th>
              <th *ngIf="isVisible('category')" class="sortable-th" (click)="toggleSort('category')">Category <span class="sort-icon">{{ getSortIcon('category') }}</span></th>
              <th *ngIf="isVisible('platform')" class="sortable-th" (click)="toggleSort('platform')">Platform <span class="sort-icon">{{ getSortIcon('platform') }}</span></th>
              <th *ngIf="isVisible('location')">Location</th>
              <th *ngIf="isVisible('status')" class="sortable-th" (click)="toggleSort('status')">Status <span class="sort-icon">{{ getSortIcon('status') }}</span></th>
              <th *ngIf="isVisible('company')">Company</th>
              <th *ngIf="isVisible('email')">Email</th>
              <th *ngIf="isVisible('phone')">Phone</th>
              <th *ngIf="isVisible('enrichment')">Enrichment</th>
              <th *ngIf="isVisible('createdAt')" class="sortable-th" (click)="toggleSort('createdAt')">Created <span class="sort-icon">{{ getSortIcon('createdAt') }}</span></th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let p of prospects">
              <td *ngIf="isVisible('name')"><strong>{{ p.name }}</strong><div class="sub-text" *ngIf="p.company">{{ p.company }}</div></td>
              <td *ngIf="isVisible('score')"><span class="score" [class]="scoreClass(p.compositeScore)">{{ p.compositeScore }}</span></td>
              <td *ngIf="isVisible('intentScore')"><span *ngIf="p.intentScore !== null" class="intent-score" [class]="intentClass(p.intentScore!)">{{ p.intentScore }}</span><span *ngIf="p.intentScore === null" class="no-intent">—</span></td>
              <td *ngIf="isVisible('urgency')"><span class="urgency-badge" [class]="'urgency-' + p.urgency.toLowerCase()">{{ p.urgency }}</span></td>
              <td *ngIf="isVisible('category')">{{ p.category || '—' }}</td>
              <td *ngIf="isVisible('platform')">{{ p.platform || '—' }}</td>
              <td *ngIf="isVisible('location')">{{ formatLocation(p.city, p.state) }}</td>
              <td *ngIf="isVisible('status')"><span class="status-badge" [class]="'status-' + p.status.toLowerCase()">{{ p.status }}</span></td>
              <td *ngIf="isVisible('company')">{{ p.company || '—' }}</td>
              <td *ngIf="isVisible('email')">{{ p.email || '—' }}</td>
              <td *ngIf="isVisible('phone')">{{ p.phone || '—' }}</td>
              <td *ngIf="isVisible('enrichment')">{{ p.enrichmentStatus || '—' }}</td>
              <td *ngIf="isVisible('createdAt')">{{ p.createdAt | date:'short' }}</td>
              <td class="actions-cell">
                <button class="btn-sm" (click)="selectProspect(p)">View</button>
                <a *ngIf="p.postUrl" [href]="p.postUrl" target="_blank" class="btn-sm btn-link">Link</a>
                <button *ngIf="p.status !== 'Dismissed'" class="btn-sm btn-danger" (click)="dismiss(p)">Dismiss</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Card View -->
      <div *ngIf="viewMode === 'card'" class="cards-grid">
        <div *ngFor="let p of prospects" class="prospect-card" (click)="selectProspect(p)">
          <div class="card-header">
            <div>
              <strong>{{ p.name }}</strong>
              <div class="sub-text">{{ p.company || p.platform }}</div>
            </div>
            <div class="card-scores">
              <span class="score" [class]="scoreClass(p.compositeScore)">{{ p.compositeScore }}</span>
              <span *ngIf="p.intentScore !== null" class="intent-score" [class]="intentClass(p.intentScore!)" title="Intent Score">{{ p.intentScore }}</span>
            </div>
          </div>
          <div class="card-badges">
            <span class="urgency-badge" [class]="'urgency-' + p.urgency.toLowerCase()">{{ p.urgency }}</span>
            <span *ngIf="p.category" class="cat-badge">{{ p.category }}</span>
          </div>
          <p class="snippet" *ngIf="p.signalSnippet">{{ p.signalSnippet | slice:0:120 }}...</p>
        </div>
      </div>

      <!-- Pagination -->
      <div class="pagination" *ngIf="totalPages > 1">
        <button class="btn-sm" [disabled]="filter.page === 1" (click)="goPage(filter.page! - 1)">Prev</button>
        <span>Page {{ filter.page }} of {{ totalPages }}</span>
        <button class="btn-sm" [disabled]="filter.page === totalPages" (click)="goPage(filter.page! + 1)">Next</button>
      </div>

      <!-- Detail Panel -->
      <div *ngIf="selectedProspect" class="modal-overlay" (click)="selectedProspect = null">
        <div class="modal" (click)="$event.stopPropagation()">
          <h3>{{ selectedProspect.name }}</h3>
          <div class="detail-grid">
            <div><strong>Score:</strong> {{ selectedProspect.compositeScore }}</div>
            <div><strong>Intent:</strong> {{ selectedProspect.intentScore !== null ? selectedProspect.intentScore : '—' }}</div>
            <div><strong>Urgency:</strong> {{ selectedProspect.urgency }}</div>
            <div><strong>Sentiment:</strong> {{ selectedProspect.sentiment || '—' }}</div>
            <div><strong>Category:</strong> {{ selectedProspect.category || '—' }}</div>
            <div><strong>Platform:</strong> {{ selectedProspect.platform || '—' }}</div>
            <div><strong>Phone:</strong> {{ selectedProspect.phone || '—' }}</div>
            <div><strong>Email:</strong> {{ selectedProspect.email || '—' }}</div>
            <div><strong>Company:</strong> {{ selectedProspect.company || '—' }}</div>
            <div><strong>Location:</strong> {{ formatLocation(selectedProspect.city, selectedProspect.state, selectedProspect.zip) }}</div>
            <div><strong>Status:</strong> {{ selectedProspect.status }}</div>
            <div><strong>Enrichment:</strong> {{ selectedProspect.enrichmentStatus }}</div>
          </div>
          <div *ngIf="selectedProspect.signalSnippet" class="signal-box">
            <strong>Signal:</strong>
            <p>{{ selectedProspect.signalSnippet }}</p>
          </div>
          <div class="form-actions">
            <button class="btn-secondary" (click)="selectedProspect = null">Close</button>
            <button *ngIf="selectedProspect.status === 'New'" class="btn-primary" (click)="markViewed()">Mark Viewed</button>
            <button *ngIf="selectedProspect.status === 'Viewed'" class="btn-primary" (click)="markContacted()">Mark Contacted</button>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .prospects-page { padding: 1.5rem; }
    .page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
    .page-header h2 { margin: 0; }
    .actions { display: flex; gap: 0.5rem; align-items: center; }
    .filter-bar { display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }
    .filter-bar select { padding: 0.4rem; border: 1px solid #d1d5db; border-radius: 4px; font-size: 0.875rem; }
    .table-card { background: white; border-radius: 8px; padding: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 0.6rem; text-align: left; border-bottom: 1px solid #e5e7eb; font-size: 0.875rem; }
    th { font-weight: 600; color: #374151; }
    .sub-text { font-size: 0.75rem; color: #6b7280; }
    .score { font-weight: 700; padding: 0.2rem 0.5rem; border-radius: 4px; }
    .score-high { background: #d1fae5; color: #065f46; }
    .score-med { background: #fef3c7; color: #92400e; }
    .score-low { background: #e5e7eb; color: #374151; }
    .intent-score { font-weight: 700; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.8rem; }
    .intent-high { background: #ede9fe; color: #5b21b6; }
    .intent-med { background: #fef3c7; color: #92400e; }
    .intent-low { background: #f3f4f6; color: #6b7280; }
    .no-intent { color: #d1d5db; }
    .card-scores { display: flex; gap: 0.3rem; align-items: center; }
    .urgency-badge { padding: 0.15rem 0.4rem; border-radius: 10px; font-size: 0.7rem; font-weight: 600; }
    .urgency-hot { background: #fee2e2; color: #991b1b; }
    .urgency-warm { background: #fef3c7; color: #92400e; }
    .urgency-cool { background: #dbeafe; color: #1d4ed8; }
    .status-badge { padding: 0.15rem 0.4rem; border-radius: 10px; font-size: 0.7rem; font-weight: 600; }
    .status-new { background: #dbeafe; color: #1d4ed8; }
    .status-viewed { background: #fef3c7; color: #92400e; }
    .status-contacted { background: #d1fae5; color: #065f46; }
    .status-converted { background: #d1fae5; color: #065f46; }
    .status-dismissed { background: #e5e7eb; color: #6b7280; }
    .cat-badge { padding: 0.15rem 0.4rem; border-radius: 10px; font-size: 0.7rem; background: #ede9fe; color: #5b21b6; }
    .cards-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1rem; }
    .prospect-card { background: white; border-radius: 8px; padding: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); cursor: pointer; }
    .prospect-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.15); }
    .card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem; }
    .card-badges { display: flex; gap: 0.5rem; margin-bottom: 0.5rem; }
    .snippet { font-size: 0.8rem; color: #6b7280; margin: 0; }
    .pagination { display: flex; align-items: center; gap: 1rem; justify-content: center; margin-top: 1rem; }
    .actions-cell { display: flex; gap: 0.25rem; }
    .modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; }
    .modal { background: white; border-radius: 8px; padding: 1.5rem; width: 560px; max-height: 80vh; overflow-y: auto; }
    .modal h3 { margin: 0 0 1rem; }
    .detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; margin-bottom: 1rem; font-size: 0.875rem; }
    .signal-box { background: #f9fafb; padding: 0.75rem; border-radius: 4px; margin-bottom: 1rem; font-size: 0.875rem; }
    .signal-box p { margin: 0.25rem 0 0; color: #374151; }
    .form-actions { display: flex; gap: 0.5rem; justify-content: flex-end; }
    .btn-primary { padding: 0.5rem 1rem; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; }
    .btn-secondary { padding: 0.5rem 1rem; background: white; color: #374151; border: 1px solid #d1d5db; border-radius: 4px; cursor: pointer; }
    .btn-sm { padding: 0.3rem 0.6rem; font-size: 0.75rem; border: 1px solid #d1d5db; border-radius: 4px; cursor: pointer; background: white; }
    .btn-sm.active { background: #2563eb; color: white; border-color: #2563eb; }
    .btn-danger { color: #dc2626; border-color: #dc2626; }
    .btn-link { color: #2563eb; border-color: #2563eb; text-decoration: none; }
    /* Column Picker */
    .column-picker-wrapper{position:relative;display:inline-block}
    .column-picker{position:absolute;top:100%;right:0;background:#fff;border:1px solid #d1d5db;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,.15);z-index:100;min-width:180px;padding:.5rem 0}
    .picker-header{padding:.4rem .75rem;font-weight:600;font-size:.8rem;color:#374151;border-bottom:1px solid #e5e7eb}
    .picker-item{display:flex;align-items:center;gap:.5rem;padding:.3rem .75rem;font-size:.8rem;cursor:pointer}
    .picker-item:hover{background:#f3f4f6}
    .picker-item input{accent-color:#2563eb}
    .btn-icon{padding:.4rem;border:1px solid #d1d5db;border-radius:4px;cursor:pointer;background:#fff;display:flex;align-items:center;justify-content:center}
    .btn-icon:hover{background:#f3f4f6}
    .sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
    .sortable-th:hover{background:#eef2ff;color:#2563eb}
    .sort-icon{font-size:.7rem;margin-left:2px;color:#9ca3af}
  `]
})
export class ProspectsComponent implements OnInit {
  prospects: ProspectResponse[] = [];
  selectedProspect: ProspectResponse | null = null;
  viewMode: 'table' | 'card' = 'table';
  totalPages = 0;
  categories = ['Home', 'Auto', 'Life', 'Health', 'Commercial'];
  showColumnPicker = false;

  columns: ColumnDef[] = [
    { key: 'name', label: 'Name', visible: true },
    { key: 'score', label: 'Score', visible: true },
    { key: 'intentScore', label: 'Intent Score', visible: true },
    { key: 'urgency', label: 'Urgency', visible: true },
    { key: 'category', label: 'Category', visible: true },
    { key: 'platform', label: 'Platform', visible: true },
    { key: 'location', label: 'Location', visible: true },
    { key: 'status', label: 'Status', visible: true },
    { key: 'company', label: 'Company', visible: false },
    { key: 'email', label: 'Email', visible: false },
    { key: 'phone', label: 'Phone', visible: false },
    { key: 'enrichment', label: 'Enrichment', visible: false },
    { key: 'createdAt', label: 'Created At', visible: false },
  ];

  private sortFieldMap: Record<string, string> = {
    name: 'name',
    score: 'score',
    intentScore: 'intentscore',
    urgency: 'urgency',
    category: 'category',
    platform: 'platform',
    status: 'status',
    createdAt: 'date',
  };

  filter: ProspectFilter = { sortBy: 'score', sortDesc: true, page: 1, pageSize: 20 };

  constructor(private prospectService: ProspectService) {}

  ngOnInit(): void { this.loadProspects(); }

  loadProspects(): void {
    this.prospectService.getAll(this.filter).subscribe(res => {
      this.prospects = res.items;
      this.totalPages = res.totalPages;
    });
  }

  goPage(page: number): void { this.filter.page = page; this.loadProspects(); }

  selectProspect(p: ProspectResponse): void { this.selectedProspect = p; }

  dismiss(p: ProspectResponse): void {
    this.prospectService.dismiss(p.id).subscribe(() => this.loadProspects());
  }

  markViewed(): void {
    if (!this.selectedProspect) return;
    this.prospectService.updateStatus(this.selectedProspect.id, 'Viewed').subscribe(updated => {
      this.selectedProspect = updated;
      this.loadProspects();
    });
  }

  markContacted(): void {
    if (!this.selectedProspect) return;
    this.prospectService.updateStatus(this.selectedProspect.id, 'Contacted').subscribe(updated => {
      this.selectedProspect = updated;
      this.loadProspects();
    });
  }

  exportCsv(): void {
    this.prospectService.exportCsv(this.filter).subscribe(blob => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'prospects.csv'; a.click();
      URL.revokeObjectURL(url);
    });
  }

  formatLocation(...parts: (string | null | undefined)[]): string {
    const filtered = parts.filter(p => p);
    return filtered.length > 0 ? filtered.join(', ') : '—';
  }

  scoreClass(score: number): string {
    if (score >= 70) return 'score score-high';
    if (score >= 40) return 'score score-med';
    return 'score score-low';
  }

  intentClass(score: number): string {
    if (score >= 60) return 'intent-score intent-high';
    if (score >= 30) return 'intent-score intent-med';
    return 'intent-score intent-low';
  }

  // Column Picker
  toggleColumnPicker($event: Event): void {
    $event.stopPropagation();
    this.showColumnPicker = !this.showColumnPicker;
  }

  @HostListener('document:click')
  onDocumentClick(): void {
    this.showColumnPicker = false;
  }

  isVisible(key: string): boolean {
    const col = this.columns.find(function(c) { return c.key === key; });
    return col ? col.visible : false;
  }

  get visibleColumnCount(): number {
    return this.columns.filter(function(c) { return c.visible; }).length;
  }

  // Sortable Headers
  toggleSort(field: string): void {
    const apiField = this.sortFieldMap[field] || field;
    if (this.filter.sortBy === apiField) {
      this.filter.sortDesc = !this.filter.sortDesc;
    } else {
      this.filter.sortBy = apiField;
      this.filter.sortDesc = true;
    }
    this.loadProspects();
  }

  getSortIcon(field: string): string {
    const apiField = this.sortFieldMap[field] || field;
    if (this.filter.sortBy !== apiField) return '\u2195';
    return this.filter.sortDesc ? '\u25BC' : '\u25B2';
  }
}
