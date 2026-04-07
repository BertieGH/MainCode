import { Component, OnInit, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ProspectService } from '../../core/services/prospect.service';
import { ProspectResponse, ProspectFilter, ProspectFullDataResponse, SignalDto, LinkedInPostDto } from '../../core/models/prospect.model';

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
      <!-- Action Bar -->
      <div class="action-bar">
        <button class="btn btn-primary" (click)="reprocess()" [disabled]="reprocessing">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
          {{ reprocessing ? 'Reprocessing...' : 'Reprocess All' }}
        </button>
        <button class="btn btn-purple" (click)="analyzeAll()" [disabled]="analyzingAll">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
          {{ analyzingAll ? 'Analyzing...' : 'AI Analyze All' }}
        </button>
        <button class="btn btn-ghost" (click)="showSettings = true" title="AI Analysis Settings">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        </button>

        <div class="bar-divider"></div>

        <!-- Filters -->
        <input type="text" class="search-input" placeholder="Search name..." [(ngModel)]="searchText" (input)="onSearch()" name="search" />
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
          <option value="Nextdoor">Nextdoor</option>
          <option value="Facebook">Facebook</option>
          <option value="LinkedIn">LinkedIn</option>
        </select>
        <select [(ngModel)]="filter.status" (change)="loadProspects()" name="stat">
          <option value="">All Status</option>
          <option value="New">New</option>
          <option value="Viewed">Viewed</option>
          <option value="Contacted">Contacted</option>
          <option value="Converted">Converted</option>
          <option value="Dismissed">Dismissed</option>
        </select>

        <div class="bar-spacer"></div>

        <div class="view-toggle">
          <button class="view-btn" [class.active]="viewMode === 'table'" (click)="viewMode = 'table'">Table</button>
          <button class="view-btn" [class.active]="viewMode === 'card'" (click)="viewMode = 'card'">Cards</button>
        </div>
        <div class="column-picker-wrapper">
          <button class="btn-icon" title="Columns" (click)="toggleColumnPicker($event)">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z"/></svg>
          </button>
          <div class="column-picker" *ngIf="showColumnPicker" (click)="$event.stopPropagation()">
            <div class="picker-header">Show/Hide Columns</div>
            <label *ngFor="let col of columns" class="picker-item">
              <input type="checkbox" [(ngModel)]="col.visible" [name]="'col_' + col.key" (ngModelChange)="saveColumnSettings()" />
              {{ col.label }}
            </label>
          </div>
        </div>
        <button class="btn btn-ghost btn-sm" (click)="exportCsv()">Export CSV</button>
      </div>

      <!-- Stats Strip -->
      <div class="stats-strip">
        <span>Total: <strong>{{ totalCount }}</strong></span>
        <span>AI Analyzed: <strong>{{ stats.analyzed }}</strong> / {{ stats.total }}</span>
        <span class="stat-hot">Hot: <strong>{{ stats.hot }}</strong></span>
        <span class="stat-warm">Warm: <strong>{{ stats.warm }}</strong></span>
        <span>New: <strong>{{ stats.newCount }}</strong></span>
        <span>Contacted: <strong>{{ stats.contacted }}</strong></span>
      </div>

      <!-- Info Message -->
      <div *ngIf="infoMessage" class="info-msg" [class.error]="infoError">
        <svg *ngIf="!infoError" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
        {{ infoMessage }}
        <span class="info-close" (click)="infoMessage = ''">&times;</span>
      </div>

      <!-- Table View -->
      <div *ngIf="viewMode === 'table'" class="table-wrap">
        <table>
          <thead>
            <tr>
              <th *ngIf="isVisible('name')" class="sortable-th" (click)="toggleSort('name')">Name <span class="sort-icon">{{ getSortIcon('name') }}</span></th>
              <th *ngIf="isVisible('score')" class="sortable-th" (click)="toggleSort('score')">Match <span class="sort-icon">{{ getSortIcon('score') }}</span></th>
              <th *ngIf="isVisible('intentScore')" class="sortable-th" (click)="toggleSort('intentScore')">Intent <span class="sort-icon">{{ getSortIcon('intentScore') }}</span></th>
              <th *ngIf="isVisible('intentCategory')" class="sortable-th" (click)="toggleSort('intentCategory')">Category <span class="sort-icon">{{ getSortIcon('intentCategory') }}</span></th>
              <th *ngIf="isVisible('sentiment')" class="sortable-th" (click)="toggleSort('sentiment')">Sentiment <span class="sort-icon">{{ getSortIcon('sentiment') }}</span></th>
              <th *ngIf="isVisible('aiSummary')">AI Summary</th>
              <th *ngIf="isVisible('urgency')" class="sortable-th" (click)="toggleSort('urgency')">Urgency <span class="sort-icon">{{ getSortIcon('urgency') }}</span></th>
              <th *ngIf="isVisible('platform')" class="sortable-th" (click)="toggleSort('platform')">Platform <span class="sort-icon">{{ getSortIcon('platform') }}</span></th>
              <th *ngIf="isVisible('location')" class="sortable-th" (click)="toggleSort('location')">Location <span class="sort-icon">{{ getSortIcon('location') }}</span></th>
              <th *ngIf="isVisible('postDate')" class="sortable-th" (click)="toggleSort('postDate')">Post Date <span class="sort-icon">{{ getSortIcon('postDate') }}</span></th>
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
              <td *ngIf="isVisible('intentScore')"><span *ngIf="p.intentScore !== null" class="intent-badge" [class]="intentClass(p.intentScore!)">{{ p.intentScore }}</span><span *ngIf="p.intentScore === null" class="no-data">&mdash;</span></td>
              <td *ngIf="isVisible('intentCategory')"><span *ngIf="p.intentCategory" class="category-tag">{{ p.intentCategory }}</span><span *ngIf="!p.intentCategory" class="no-data">&mdash;</span></td>
              <td *ngIf="isVisible('sentiment')"><span *ngIf="p.sentiment" class="sentiment-tag" [class]="'sentiment-' + p.sentiment.toLowerCase()">{{ p.sentiment }}</span><span *ngIf="!p.sentiment" class="no-data">&mdash;</span></td>
              <td *ngIf="isVisible('aiSummary')" class="ai-summary-cell"><span *ngIf="p.aiSummary" class="ai-summary-text" [title]="p.aiSummary">{{ truncate(p.aiSummary, 80) }}</span><span *ngIf="!p.aiSummary" class="no-data">&mdash;</span></td>
              <td *ngIf="isVisible('urgency')"><span class="urgency-badge" [class]="'urgency-' + p.urgency.toLowerCase()">{{ p.urgency }}</span></td>
              <td *ngIf="isVisible('platform')"><span class="platform-tag" [class]="'plat-' + (p.platform || '').toLowerCase()">{{ p.platform || '—' }}</span></td>
              <td *ngIf="isVisible('location')">{{ formatLocation(p.city, p.state) }}</td>
              <td *ngIf="isVisible('postDate')" style="white-space:nowrap">{{ p.postDate ? (p.postDate | date:'shortDate') : '—' }}</td>
              <td *ngIf="isVisible('status')"><span class="status-badge" [class]="'status-' + p.status.toLowerCase()">{{ p.status }}</span></td>
              <td *ngIf="isVisible('company')">{{ p.company || '—' }}</td>
              <td *ngIf="isVisible('email')">{{ p.email || '—' }}</td>
              <td *ngIf="isVisible('phone')">{{ p.phone || '—' }}</td>
              <td *ngIf="isVisible('enrichment')">{{ p.enrichmentStatus || '—' }}</td>
              <td *ngIf="isVisible('createdAt')">{{ p.createdAt | date:'short' }}</td>
              <td>
                <div class="actions-cell">
                  <!-- Analyze -->
                  <button class="icon-btn" [class.done]="p.analyzedAt !== null" (click)="analyzeProspect(p)" [disabled]="analyzingIds.has(p.id) || p.analyzedAt !== null" [title]="p.analyzedAt ? 'AI Analyzed' : 'Analyze'">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
                    <span *ngIf="p.analyzedAt" class="tick">&#10003;</span>
                    <span *ngIf="analyzingIds.has(p.id)" class="spinner"></span>
                  </button>
                  <!-- Lookup Contact -->
                  <button class="icon-btn" [class.done]="p.enrichmentStatus === 'Verified'" (click)="lookupContact(p)" [disabled]="lookingUpIds.has(p.id)" [title]="p.enrichmentStatus === 'Verified' ? 'Re-lookup Contact' : 'Lookup Contact'">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.79 19.79 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
                    <span *ngIf="p.enrichmentStatus === 'Verified'" class="tick">&#10003;</span>
                    <span *ngIf="lookingUpIds.has(p.id)" class="spinner"></span>
                  </button>
                  <!-- LinkedIn Search / Open -->
                  <button *ngIf="!p.linkedInUrl" class="icon-btn icon-linkedin" (click)="searchLinkedIn(p)" [disabled]="searchingLinkedIn[p.id]" title="Find LinkedIn">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z"/></svg>
                    <span *ngIf="searchingLinkedIn[p.id]" class="spinner"></span>
                  </button>
                  <a *ngIf="p.linkedInUrl" [href]="p.linkedInUrl" target="_blank" class="icon-btn icon-linkedin done" title="View LinkedIn Profile">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z"/></svg>
                    <span class="tick">&#10003;</span>
                  </a>
                  <!-- Scrub Profile -->
                  <button class="icon-btn" [class.done]="!!p.linkedInScrapedAt" (click)="scrubProfileFromTable(p)" [disabled]="scrubbingProfileIds.has(p.id) || !p.linkedInUrl" [title]="p.linkedInScrapedAt ? 'Profile Scraped' : (p.linkedInUrl ? 'Scrub Profile' : 'Find LinkedIn first')">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                    <span *ngIf="p.linkedInScrapedAt" class="tick">&#10003;</span>
                    <span *ngIf="scrubbingProfileIds.has(p.id)" class="spinner"></span>
                  </button>
                  <!-- Scrub Posts -->
                  <button class="icon-btn" [class.done]="p.linkedInScrapedAt && scrubbedPostsIds.has(p.id)" (click)="scrubPostsFromTable(p)" [disabled]="scrubbingPostsIds.has(p.id) || !p.linkedInUrl" [title]="p.linkedInUrl ? 'Scrub LinkedIn Posts' : 'Find LinkedIn first'">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
                    <span *ngIf="scrubbedPostsIds.has(p.id)" class="tick">&#10003;</span>
                    <span *ngIf="scrubbingPostsIds.has(p.id)" class="spinner"></span>
                  </button>
                  <!-- Post Link -->
                  <a *ngIf="p.postUrl" [href]="p.postUrl" target="_blank" class="icon-btn icon-link-out" title="View Original Post">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                  </a>
                  <!-- Data -->
                  <button class="icon-btn icon-data" (click)="openDataModal(p)" title="View All Data" [disabled]="loadingFullData === p.id">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
                    <span *ngIf="loadingFullData === p.id" class="spinner"></span>
                  </button>
                  <!-- View Detail -->
                  <button class="icon-btn" (click)="selectProspect(p)" title="View Details">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                  </button>
                  <!-- Status -->
                  <select class="status-select" [ngModel]="p.status" (ngModelChange)="changeStatus(p, $event)" [name]="'pstatus_' + p.id">
                    <option value="New">New</option>
                    <option value="Viewed">Viewed</option>
                    <option value="Contacted">Contacted</option>
                    <option value="Converted">Converted</option>
                    <option value="Dismissed">Dismissed</option>
                  </select>
                </div>
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
              <span *ngIf="p.intentScore !== null" class="intent-badge" [class]="intentClass(p.intentScore!)" title="Intent Score">{{ p.intentScore }}</span>
            </div>
          </div>
          <div class="card-badges">
            <span class="urgency-badge" [class]="'urgency-' + p.urgency.toLowerCase()">{{ p.urgency }}</span>
            <span *ngIf="p.intentCategory" class="category-tag">{{ p.intentCategory }}</span>
            <span *ngIf="p.sentiment" class="sentiment-tag" [class]="'sentiment-' + p.sentiment.toLowerCase()">{{ p.sentiment }}</span>
          </div>
          <div *ngIf="p.city || p.state" class="card-location">{{ formatLocation(p.city, p.state) }}</div>
          <small *ngIf="p.postDate" class="card-date">{{ p.postDate | date:'mediumDate' }}</small>
          <p class="snippet" *ngIf="p.signalSnippet">{{ p.signalSnippet | slice:0:120 }}...</p>
        </div>
      </div>

      <!-- Pagination -->
      <div class="pagination" *ngIf="totalPages > 1">
        <button class="btn-sm" [disabled]="filter.page === 1" (click)="goPage(filter.page! - 1)">Prev</button>
        <span>Page {{ filter.page }} of {{ totalPages }} ({{ totalCount }} prospects)</span>
        <button class="btn-sm" [disabled]="filter.page === totalPages" (click)="goPage(filter.page! + 1)">Next</button>
      </div>

      <!-- LinkedIn Picker Modal -->
      <div *ngIf="linkedInCandidates.length > 0" class="modal-overlay" (click)="linkedInCandidates = []">
        <div class="modal" (click)="$event.stopPropagation()" style="max-width:500px">
          <div class="modal-header"><h3>Select LinkedIn Profile</h3><span class="modal-close" (click)="linkedInCandidates = []">&times;</span></div>
          <p style="color:#6b7280;font-size:.85rem;margin:0 0 .75rem">Choose the correct profile for <strong>{{ linkedInPickerName }}</strong></p>
          <div *ngFor="let c of linkedInCandidates" class="li-candidate" (click)="pickLinkedIn(c.url)">
            <div class="li-candidate-name">{{ c.name }}</div>
            <div class="li-candidate-headline">{{ c.headline }}</div>
            <div class="li-candidate-snippet">{{ c.snippet }}</div>
            <div class="li-candidate-url">{{ c.url }}</div>
          </div>
          <div style="margin-top:1rem;text-align:right"><button class="btn-sm" (click)="linkedInCandidates = []">Cancel</button></div>
        </div>
      </div>

      <!-- Detail Modal -->
      <div *ngIf="selectedProspect" class="modal-overlay" (click)="closeDetail()">
        <div class="modal" (click)="$event.stopPropagation()">
          <h3>{{ selectedProspect.name }}</h3>
          <div class="detail-grid">
            <div><strong>Match:</strong> {{ selectedProspect.compositeScore }}</div>
            <div><strong>Intent:</strong> {{ selectedProspect.intentScore !== null ? selectedProspect.intentScore : '—' }}</div>
            <div><strong>Category:</strong> {{ selectedProspect.intentCategory || selectedProspect.category || '—' }}</div>
            <div><strong>Sentiment:</strong> {{ selectedProspect.sentiment || '—' }}</div>
            <div><strong>Urgency:</strong> {{ selectedProspect.urgency }}</div>
            <div><strong>Platform:</strong> {{ selectedProspect.platform || '—' }}</div>
            <div><strong>Phone:</strong> {{ selectedProspect.phone || '—' }}</div>
            <div><strong>Email:</strong> {{ selectedProspect.email || '—' }}</div>
            <div><strong>Company:</strong> {{ selectedProspect.company || '—' }}</div>
            <div><strong>Location:</strong> {{ formatLocation(selectedProspect.city, selectedProspect.state, selectedProspect.zip) }}</div>
            <div><strong>Status:</strong> {{ selectedProspect.status }}</div>
            <div><strong>Post Date:</strong> {{ selectedProspect.postDate ? (selectedProspect.postDate | date:'mediumDate') : '—' }}</div>
          </div>
          <div *ngIf="selectedProspect.aiSummary" class="ai-box">
            <strong>AI Summary</strong> <small class="ai-provider">{{ selectedProspect.aiProvider }} &middot; {{ selectedProspect.analyzedAt | date:'short' }}</small>
            <p>{{ selectedProspect.aiSummary }}</p>
          </div>
          <div *ngIf="selectedProspect.signalSnippet" class="signal-box">
            <strong>Signal Snippet:</strong>
            <p>{{ selectedProspect.signalSnippet }}</p>
          </div>

          <!-- LinkedIn Profile Section -->
          <div *ngIf="selectedProspect.linkedInUrl" class="linkedin-section">
            <div class="linkedin-header">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="#0a66c2"><path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z"/></svg>
              <strong>LinkedIn Profile</strong>
              <a [href]="selectedProspect.linkedInUrl" target="_blank" class="linkedin-url">{{ selectedProspect.linkedInUrl }}</a>
            </div>

            <div *ngIf="selectedProspect.linkedInScrapedAt" class="li-profile-data">
              <div class="li-profile-type">
                <span class="li-type-badge" [class]="'li-type-' + (selectedProspect.linkedInType || 'individual').toLowerCase()">{{ selectedProspect.linkedInType || 'Individual' }}</span>
                <small class="li-scraped-at">Scraped {{ selectedProspect.linkedInScrapedAt | date:'short' }}</small>
              </div>
              <div *ngIf="selectedProspect.linkedInHeadline" class="li-headline">{{ selectedProspect.linkedInHeadline }}</div>
              <div *ngIf="selectedProspect.linkedInAbout" class="li-about">
                <strong>About:</strong>
                <p>{{ selectedProspect.linkedInAbout }}</p>
              </div>
              <div *ngIf="selectedProspect.linkedInContactInfo" class="li-contact">
                <strong>Contact Info:</strong>
                <pre class="li-contact-json">{{ formatContactInfo(selectedProspect.linkedInContactInfo) }}</pre>
              </div>
            </div>

            <div class="li-actions">
              <button class="btn btn-linkedin-scrub" (click)="scrubProfile(selectedProspect!)" [disabled]="scrubbingProfile">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                {{ scrubbingProfile ? 'Scrubbing Profile...' : (selectedProspect.linkedInScrapedAt ? 'Re-scrub Profile' : 'Scrub Profile') }}
              </button>
              <button class="btn btn-linkedin-posts" (click)="scrubPosts(selectedProspect!)" [disabled]="scrubbingPosts">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
                {{ scrubbingPosts ? 'Scrubbing Posts...' : 'Scrub Posts' }}
              </button>
            </div>

            <!-- LinkedIn Posts -->
            <div *ngIf="linkedInPosts.length > 0" class="li-posts">
              <strong>LinkedIn Posts ({{ linkedInPosts.length }})</strong>
              <div *ngFor="let post of linkedInPosts" class="li-post-item">
                <div class="li-post-content">{{ truncate(post.content, 200) }}</div>
                <div class="li-post-meta">
                  <span *ngIf="post.postDate">{{ post.postDate | date:'mediumDate' }}</span>
                  <span *ngIf="post.likes">{{ post.likes }} likes</span>
                  <span *ngIf="post.comments">{{ post.comments }} comments</span>
                </div>
              </div>
            </div>
          </div>

          <div class="form-actions">
            <button class="btn btn-ghost" (click)="closeDetail()">Close</button>
            <select class="status-select" [ngModel]="selectedProspect.status" (ngModelChange)="changeStatus(selectedProspect!, $event)" [name]="'detailStatus'">
              <option value="New">New</option>
              <option value="Viewed">Viewed</option>
              <option value="Contacted">Contacted</option>
              <option value="Converted">Converted</option>
              <option value="Dismissed">Dismissed</option>
            </select>
          </div>
        </div>
      </div>

      <!-- AI Settings Modal -->
      <div *ngIf="showSettings" class="modal-overlay" (click)="showSettings = false">
        <div class="modal" (click)="$event.stopPropagation()" style="width:480px">
          <h3>AI Analysis Settings</h3>
          <p class="help-text">Configure the AI provider used for intent analysis on prospects.</p>
          <div class="settings-form">
            <div class="form-group">
              <label>AI Provider</label>
              <select [(ngModel)]="settingsForm.aiProvider" (ngModelChange)="onProviderChange()" name="aiProv">
                <option value="Local">Local (Free - Rule-based)</option>
                <option value="Claude">Claude (Anthropic)</option>
                <option value="OpenAI">OpenAI</option>
                <option value="Google">Google AI (Gemini)</option>
              </select>
            </div>
            <div class="form-group" *ngIf="settingsForm.aiProvider !== 'Local'">
              <label>API Key
                <span *ngIf="aiSettings?.hasApiKey" class="key-ok">&#10003; Stored</span>
                <span *ngIf="aiSettings && !aiSettings.hasApiKey" class="key-missing">&#10007; Not set</span>
              </label>
              <input type="password" [(ngModel)]="settingsForm.apiKey" name="aiKey"
                     [placeholder]="aiSettings?.hasApiKey ? '(key saved — enter new to update)' : 'Enter API key'" />
            </div>
            <div class="form-group" *ngIf="settingsForm.aiProvider !== 'Local'">
              <label>Model</label>
              <select [(ngModel)]="settingsForm.aiModel" name="aiModel">
                <ng-container *ngIf="settingsForm.aiProvider === 'Claude'">
                  <option value="claude-sonnet-4-6">Claude Sonnet 4.6</option>
                  <option value="claude-haiku-4-5-20251001">Claude Haiku 4.5</option>
                  <option value="claude-opus-4-6">Claude Opus 4.6</option>
                </ng-container>
                <ng-container *ngIf="settingsForm.aiProvider === 'OpenAI'">
                  <option value="gpt-4o-mini">GPT-4o Mini</option>
                  <option value="gpt-4o">GPT-4o</option>
                  <option value="gpt-4-turbo">GPT-4 Turbo</option>
                </ng-container>
                <ng-container *ngIf="settingsForm.aiProvider === 'Google'">
                  <option value="gemini-2.0-flash">Gemini 2.0 Flash</option>
                  <option value="gemini-3.1-flash-lite-preview">Gemini 3.1 Flash Lite</option>
                  <option value="gemini-2.5-flash-preview-05-20">Gemini 2.5 Flash</option>
                  <option value="gemini-2.5-pro-preview-05-06">Gemini 2.5 Pro</option>
                </ng-container>
              </select>
            </div>
          </div>
          <div *ngIf="settingsMsg" class="settings-msg" [class.error]="settingsError">{{ settingsMsg }}</div>
          <div class="form-actions">
            <button class="btn btn-ghost" (click)="showSettings = false">Close</button>
            <button *ngIf="settingsForm.aiProvider !== 'Local'" class="btn btn-ghost" (click)="testAiKey()" [disabled]="testingAi">{{ testingAi ? 'Testing...' : 'Test Key' }}</button>
            <button class="btn btn-primary" (click)="saveAiSettings()" [disabled]="savingSettings">{{ savingSettings ? 'Saving...' : 'Save' }}</button>
          </div>
        </div>
      </div>
      <!-- Full Data Modal -->
      <div *ngIf="fullData" class="modal-overlay" (click)="closeDataModal()">
        <div class="data-modal" (click)="$event.stopPropagation()">
          <div class="data-modal-header">
            <h3>{{ fullData.prospect.name }} — All Data</h3>
            <span class="modal-close" (click)="closeDataModal()">&times;</span>
          </div>

          <div class="data-modal-body">
            <!-- Row 1: Prospect Info + Contact Data -->
            <div class="data-row-2col">
              <div class="data-section">
                <div class="data-section-title">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                  Prospect Info
                </div>
                <div class="data-fields">
                  <div class="data-field"><span class="data-label">Name</span><span class="data-value">{{ fullData.prospect.name }}</span></div>
                  <div class="data-field"><span class="data-label">Company</span><span class="data-value">{{ fullData.prospect.company || '—' }}</span></div>
                  <div class="data-field"><span class="data-label">Location</span><span class="data-value">{{ formatLocation(fullData.prospect.city, fullData.prospect.state, fullData.prospect.zip) }}</span></div>
                  <div class="data-field"><span class="data-label">Platform</span><span class="data-value"><span class="platform-tag" [class]="'plat-' + (fullData.prospect.platform || '').toLowerCase()">{{ fullData.prospect.platform || '—' }}</span></span></div>
                  <div class="data-field"><span class="data-label">Score</span><span class="data-value"><span class="score" [class]="scoreClass(fullData.prospect.compositeScore)">{{ fullData.prospect.compositeScore }}</span></span></div>
                  <div class="data-field"><span class="data-label">Urgency</span><span class="data-value"><span class="urgency-badge" [class]="'urgency-' + fullData.prospect.urgency.toLowerCase()">{{ fullData.prospect.urgency }}</span></span></div>
                  <div class="data-field"><span class="data-label">Status</span><span class="data-value"><span class="status-badge" [class]="'status-' + fullData.prospect.status.toLowerCase()">{{ fullData.prospect.status }}</span></span></div>
                  <div class="data-field"><span class="data-label">Created</span><span class="data-value">{{ fullData.prospect.createdAt | date:'medium' }}</span></div>
                </div>
              </div>
              <div class="data-section">
                <div class="data-section-title">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.79 19.79 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
                  Contact Data
                  <span *ngIf="fullData.prospect.enrichmentStatus === 'Verified'" class="section-badge done-badge">Verified</span>
                  <span *ngIf="fullData.prospect.enrichmentStatus !== 'Verified'" class="section-badge pending-badge">{{ fullData.prospect.enrichmentStatus }}</span>
                </div>
                <div class="data-fields">
                  <div class="data-field"><span class="data-label">Phone</span><span class="data-value">{{ fullData.prospect.phone || '—' }}</span></div>
                  <div class="data-field"><span class="data-label">Email</span><span class="data-value">{{ fullData.prospect.email || '—' }}</span></div>
                  <div class="data-field"><span class="data-label">Address</span><span class="data-value">{{ fullData.prospect.address || '—' }}</span></div>
                </div>
                <div class="data-empty-action">
                  <button class="btn btn-sm btn-ghost" (click)="lookupContactFromData()" [disabled]="lookingUpIds.has(fullData.prospect.id)">
                    {{ lookingUpIds.has(fullData.prospect.id) ? 'Looking up...' : (fullData.prospect.enrichmentStatus === 'Verified' ? 'Re-lookup Contact' : 'Lookup Contact') }}
                  </button>
                </div>
              </div>
            </div>

            <!-- AI Analysis -->
            <div class="data-section">
              <div class="data-section-title">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
                AI Analysis
                <span *ngIf="fullData.prospect.analyzedAt" class="section-badge done-badge">Analyzed</span>
                <span *ngIf="!fullData.prospect.analyzedAt" class="section-badge pending-badge">Not Analyzed</span>
              </div>
              <div *ngIf="fullData.prospect.analyzedAt" class="data-fields">
                <div class="data-field"><span class="data-label">Intent</span><span class="data-value"><span *ngIf="fullData.prospect.intentScore !== null" class="intent-badge" [class]="intentClass(fullData.prospect.intentScore!)">{{ fullData.prospect.intentScore }}</span><span *ngIf="fullData.prospect.intentScore === null">—</span></span></div>
                <div class="data-field"><span class="data-label">Category</span><span class="data-value"><span *ngIf="fullData.prospect.intentCategory" class="category-tag">{{ fullData.prospect.intentCategory }}</span><span *ngIf="!fullData.prospect.intentCategory">—</span></span></div>
                <div class="data-field"><span class="data-label">Sentiment</span><span class="data-value"><span *ngIf="fullData.prospect.sentiment" class="sentiment-tag" [class]="'sentiment-' + fullData.prospect.sentiment.toLowerCase()">{{ fullData.prospect.sentiment }}</span><span *ngIf="!fullData.prospect.sentiment">—</span></span></div>
                <div class="data-field"><span class="data-label">Provider</span><span class="data-value">{{ fullData.prospect.aiProvider || '—' }}</span></div>
              </div>
              <div *ngIf="fullData.prospect.aiSummary" class="ai-summary-box">{{ fullData.prospect.aiSummary }}</div>
              <div *ngIf="!fullData.prospect.analyzedAt" class="data-empty-action">
                <button class="btn btn-sm btn-purple" (click)="analyzeFromData()" [disabled]="analyzingIds.has(fullData.prospect.id)">
                  {{ analyzingIds.has(fullData.prospect.id) ? 'Analyzing...' : 'Run AI Analysis' }}
                </button>
              </div>
            </div>

            <!-- Signals / Original Posts -->
            <div class="data-section">
              <div class="data-section-title">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                Source Signals ({{ fullData.signals.length }})
              </div>
              <div *ngIf="fullData.signals.length === 0" class="data-empty">No signals linked to this prospect.</div>
              <div *ngFor="let s of fullData.signals" class="signal-card">
                <div class="signal-card-header">
                  <span class="platform-tag" [class]="'plat-' + s.platform.toLowerCase()">{{ s.platform }}</span>
                  <span *ngIf="s.authorName" class="signal-author">{{ s.authorName }}</span>
                  <span class="signal-date">{{ s.postDate ? (s.postDate | date:'mediumDate') : (s.detectedAt | date:'mediumDate') }}</span>
                </div>
                <div class="signal-card-content">{{ s.postContent }}</div>
                <div *ngIf="s.intentScore !== null" class="signal-card-ai">
                  <span class="intent-badge" [class]="intentClass(s.intentScore!)">Intent: {{ s.intentScore }}</span>
                  <span *ngIf="s.intentCategory" class="category-tag">{{ s.intentCategory }}</span>
                  <span *ngIf="s.sentiment" class="sentiment-tag" [class]="'sentiment-' + s.sentiment.toLowerCase()">{{ s.sentiment }}</span>
                </div>
                <div *ngIf="s.aiSummary" class="signal-card-summary">{{ s.aiSummary }}</div>
                <a *ngIf="s.postUrl" [href]="s.postUrl" target="_blank" class="signal-card-link">View Original Post &rarr;</a>
              </div>
            </div>

            <!-- LinkedIn Profile -->
            <div class="data-section">
              <div class="data-section-title">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="#0a66c2"><path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z"/></svg>
                LinkedIn Profile
                <span *ngIf="fullData.prospect.linkedInScrapedAt" class="section-badge done-badge">Scraped</span>
                <span *ngIf="fullData.prospect.linkedInUrl && !fullData.prospect.linkedInScrapedAt" class="section-badge pending-badge">URL Found</span>
                <span *ngIf="!fullData.prospect.linkedInUrl" class="section-badge pending-badge">Not Found</span>
              </div>
              <div *ngIf="fullData.prospect.linkedInScrapedAt" class="li-data-card">
                <div class="li-data-header">
                  <span class="li-type-badge" [class]="'li-type-' + (fullData.prospect.linkedInType || 'individual').toLowerCase()">{{ fullData.prospect.linkedInType || 'Individual' }}</span>
                  <small class="li-scraped-at">Scraped {{ fullData.prospect.linkedInScrapedAt | date:'medium' }}</small>
                </div>
                <div *ngIf="fullData.prospect.linkedInHeadline" class="li-data-headline">{{ fullData.prospect.linkedInHeadline }}</div>
                <div *ngIf="fullData.prospect.linkedInAbout" class="li-data-about">
                  <strong>About</strong>
                  <p>{{ fullData.prospect.linkedInAbout }}</p>
                </div>
                <div *ngIf="fullData.prospect.linkedInContactInfo" class="li-data-contact">
                  <strong>Contact Info</strong>
                  <pre>{{ formatContactInfo(fullData.prospect.linkedInContactInfo) }}</pre>
                </div>
                <a *ngIf="fullData.prospect.linkedInUrl" [href]="fullData.prospect.linkedInUrl" target="_blank" class="signal-card-link">View on LinkedIn &rarr;</a>
              </div>
              <div *ngIf="!fullData.prospect.linkedInUrl" class="data-empty-action">
                <span class="data-empty-text">No LinkedIn profile linked yet.</span>
              </div>
              <div *ngIf="fullData.prospect.linkedInUrl && !fullData.prospect.linkedInScrapedAt" class="data-empty-action">
                <span class="data-empty-text">Profile URL saved but not scraped.</span>
                <button class="btn btn-sm btn-ghost" (click)="scrubProfileFromData()" [disabled]="scrubbingProfileIds.has(fullData.prospect.id)">Scrub Profile</button>
              </div>
            </div>

            <!-- LinkedIn Posts -->
            <div class="data-section">
              <div class="data-section-title">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
                LinkedIn Posts ({{ fullData.linkedInPosts.length }})
              </div>
              <div *ngIf="fullData.linkedInPosts.length === 0 && fullData.prospect.linkedInUrl" class="data-empty-action">
                <span class="data-empty-text">No posts scraped yet.</span>
                <button class="btn btn-sm btn-ghost" (click)="scrubPostsFromData()" [disabled]="scrubbingPostsIds.has(fullData.prospect.id)">Scrub Posts</button>
              </div>
              <div *ngIf="fullData.linkedInPosts.length === 0 && !fullData.prospect.linkedInUrl" class="data-empty">No LinkedIn URL — search for a LinkedIn profile first.</div>
              <div *ngFor="let post of fullData.linkedInPosts; let i = index" class="li-post-card" [class.hidden-post]="i >= 3 && !showAllPosts">
                <div class="li-post-card-content">{{ post.content }}</div>
                <div class="li-post-card-meta">
                  <span *ngIf="post.postDate">{{ post.postDate | date:'mediumDate' }}</span>
                  <span *ngIf="post.likes" class="meta-engagement">{{ post.likes }} likes</span>
                  <span *ngIf="post.comments" class="meta-engagement">{{ post.comments }} comments</span>
                </div>
              </div>
              <button *ngIf="fullData.linkedInPosts.length > 3 && !showAllPosts" class="btn btn-sm btn-ghost show-all-btn" (click)="showAllPosts = true">Show all {{ fullData.linkedInPosts.length }} posts</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .prospects-page{padding:1.25rem}

    /* Action Bar */
    .action-bar{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;margin-bottom:.75rem;background:#fff;padding:.65rem 1rem;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
    .bar-divider{width:1px;height:24px;background:#e2e8f0;margin:0 .15rem}
    .bar-spacer{flex:1}
    .search-input{padding:.35rem .5rem;border:1px solid #cbd5e1;border-radius:4px;font-size:.8rem;width:130px}
    .action-bar select{padding:.35rem .5rem;border:1px solid #cbd5e1;border-radius:4px;font-size:.8rem;background:#fff}

    /* Buttons */
    .btn{padding:.42rem .7rem;border:none;border-radius:5px;cursor:pointer;font-size:.8rem;font-weight:500;display:inline-flex;align-items:center;gap:4px}
    .btn-primary{background:#2563eb;color:#fff}
    .btn-primary:hover{background:#1d4ed8}
    .btn-primary:disabled{opacity:.5;cursor:not-allowed}
    .btn-purple{background:#7c3aed;color:#fff}
    .btn-purple:hover{background:#6d28d9}
    .btn-purple:disabled{opacity:.5;cursor:not-allowed}
    .btn-ghost{background:#f8fafc;color:#475569;border:1px solid #cbd5e1}
    .btn-ghost:hover{background:#e2e8f0}
    .btn-sm{padding:.28rem .5rem;font-size:.75rem;border:1px solid #cbd5e1;border-radius:4px;cursor:pointer;background:#fff}
    .btn-sm:disabled{opacity:.4;cursor:not-allowed}

    /* View Toggle */
    .view-toggle{display:flex;border:1px solid #e2e8f0;border-radius:5px;overflow:hidden}
    .view-btn{padding:.32rem .55rem;background:#fff;border:none;cursor:pointer;font-size:.78rem;color:#64748b}
    .view-btn.active{background:#2563eb;color:#fff}

    /* Stats Strip */
    .stats-strip{display:flex;gap:1.25rem;padding:.45rem 1rem;background:#fff;border-radius:6px;margin-bottom:.65rem;box-shadow:0 1px 2px rgba(0,0,0,.05);font-size:.78rem;color:#64748b;flex-wrap:wrap}
    .stats-strip strong{color:#1e293b}
    .stat-hot strong{color:#dc2626}
    .stat-warm strong{color:#d97706}

    /* Info Message */
    .info-msg{padding:.55rem 1rem;background:#ecfdf5;border:1px solid #a7f3d0;border-radius:6px;color:#065f46;font-size:.8rem;margin-bottom:.65rem;display:flex;align-items:center;gap:.5rem}
    .info-msg.error{background:#fef2f2;border-color:#fecaca;color:#991b1b}
    .info-close{cursor:pointer;margin-left:auto;font-weight:bold;font-size:1.1rem}

    /* Table */
    .table-wrap{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08);overflow-x:auto}
    table{width:100%;border-collapse:collapse}
    th{background:#f8fafc;text-align:left;padding:.5rem .6rem;font-size:.72rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.3px;border-bottom:2px solid #e2e8f0;white-space:nowrap}
    td{padding:.45rem .6rem;border-bottom:1px solid #f1f5f9;font-size:.8rem;vertical-align:middle}
    tr:hover{background:#f8fafc}
    .sub-text{font-size:.7rem;color:#94a3b8}
    .no-data{color:#cbd5e1}

    /* Badges */
    .score{font-weight:700;padding:1px 8px;border-radius:10px;font-size:.78rem}
    .score-high{background:#d1fae5;color:#065f46}
    .score-med{background:#fef3c7;color:#92400e}
    .score-low{background:#f1f5f9;color:#64748b}
    .intent-badge{font-weight:600;padding:1px 8px;border-radius:10px;font-size:.78rem}
    .intent-high{background:#ede9fe;color:#6d28d9}
    .intent-med{background:#fef3c7;color:#92400e}
    .intent-low{background:#f1f5f9;color:#64748b}
    .category-tag{display:inline-block;padding:2px 8px;background:#f5f3ff;color:#7c3aed;border-radius:10px;font-size:.72rem;font-weight:500}
    .sentiment-tag{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.72rem;font-weight:500}
    .ai-summary-cell{max-width:250px}
    .ai-summary-text{font-size:.75rem;color:#475569;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;cursor:help}
    .sentiment-urgent{background:#fef2f2;color:#dc2626}
    .sentiment-negative{background:#fff7ed;color:#c2410c}
    .sentiment-positive{background:#ecfdf5;color:#059669}
    .sentiment-neutral{background:#f1f5f9;color:#64748b}
    .urgency-badge{padding:2px 8px;border-radius:10px;font-size:.72rem;font-weight:600}
    .urgency-hot{background:#fef2f2;color:#dc2626}
    .urgency-warm{background:#fef3c7;color:#92400e}
    .urgency-cool{background:#dbeafe;color:#1d4ed8}
    .platform-tag{padding:2px 8px;border-radius:10px;font-size:.72rem;font-weight:500}
    .plat-nextdoor{background:#ecfdf5;color:#059669}
    .plat-facebook{background:#eff6ff;color:#2563eb}
    .plat-linkedin{background:#eef2ff;color:#4f46e5}
    .status-badge{padding:2px 8px;border-radius:10px;font-size:.72rem;font-weight:600}
    .status-new{background:#dbeafe;color:#1d4ed8}
    .status-viewed{background:#fef3c7;color:#92400e}
    .status-contacted{background:#d1fae5;color:#065f46}
    .status-converted{background:#d1fae5;color:#065f46}
    .status-dismissed{background:#e5e7eb;color:#6b7280}

    /* Actions */
    .actions-cell{display:flex;gap:.25rem;align-items:center;white-space:nowrap}
    .btn-analyze{background:#f5f3ff;color:#7c3aed;border:1px solid #ddd6fe}
    .btn-analyze:hover{background:#ede9fe}
    .btn-view{color:#2563eb;border-color:#bfdbfe}
    .btn-view:hover{background:#eff6ff}
    .btn-link{color:#2563eb;border-color:#bfdbfe;text-decoration:none}
    .btn-linkedin{color:#0a66c2;border-color:#0a66c2;font-weight:600;display:inline-flex;align-items:center;gap:3px}
    .btn-linkedin:hover{background:#e8f4fd}
    .btn-linkedin:disabled{opacity:.5;cursor:not-allowed}
    .btn-linkedin-link{color:#fff;background:#0a66c2;border-color:#0a66c2;font-weight:600;display:inline-flex;align-items:center;gap:3px;text-decoration:none}
    .btn-linkedin-link:hover{background:#004182}
    .btn-linkedin-link svg{fill:#fff}
    .li-candidate{padding:.75rem;border:1px solid #e5e7eb;border-radius:8px;margin-bottom:.5rem;cursor:pointer;transition:all .15s}
    .li-candidate:hover{border-color:#0a66c2;background:#f0f7ff}
    .li-candidate-name{font-weight:600;color:#1a1f36}
    .li-candidate-headline{font-size:.8rem;color:#0a66c2;margin-top:2px}
    .li-candidate-snippet{font-size:.75rem;color:#6b7280;margin-top:4px;line-height:1.3}
    .li-candidate-url{font-size:.7rem;color:#9ca3af;margin-top:4px;word-break:break-all}
    .status-select{padding:.22rem .3rem;font-size:.72rem;border:1px solid #e2e8f0;border-radius:4px;background:#fff}

    /* Cards */
    .cards-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:.75rem}
    .prospect-card{background:#fff;border-radius:8px;padding:.85rem;box-shadow:0 1px 3px rgba(0,0,0,.08);cursor:pointer}
    .prospect-card:hover{box-shadow:0 2px 8px rgba(0,0,0,.13)}
    .card-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.4rem}
    .card-scores{display:flex;gap:.3rem;align-items:center}
    .card-badges{display:flex;gap:.4rem;margin-bottom:.3rem;flex-wrap:wrap}
    .card-location{font-size:.72rem;color:#6b7280}
    .card-date{font-size:.72rem;color:#9ca3af;display:block;margin-bottom:.2rem}
    .snippet{font-size:.78rem;color:#6b7280;margin:0}

    /* Pagination */
    .pagination{display:flex;align-items:center;gap:1rem;justify-content:center;margin-top:.75rem;font-size:.82rem}

    /* Modal */
    .modal-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:1000}
    .modal{background:#fff;border-radius:8px;padding:1.25rem;width:560px;max-height:80vh;overflow-y:auto}
    .modal h3{margin:0 0 .75rem}
    .detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:.4rem;margin-bottom:.75rem;font-size:.82rem}
    .ai-box{background:#f5f3ff;padding:.65rem;border-radius:6px;margin-bottom:.75rem;font-size:.82rem}
    .ai-box p{margin:.25rem 0 0;color:#374151}
    .ai-provider{font-size:.7rem;color:#9ca3af;margin-left:.5rem}
    .signal-box{background:#f9fafb;padding:.65rem;border-radius:6px;margin-bottom:.75rem;font-size:.82rem}
    .signal-box p{margin:.25rem 0 0;color:#374151}
    .form-actions{display:flex;gap:.5rem;justify-content:flex-end}

    /* Settings Modal */
    .help-text{font-size:.8rem;color:#64748b;margin-bottom:.75rem}
    .settings-form{display:flex;flex-direction:column;gap:.65rem;margin-bottom:.75rem}
    .form-group{display:flex;flex-direction:column;gap:.25rem}
    .form-group label{font-size:.8rem;font-weight:600;color:#374151;display:flex;align-items:center;gap:.4rem}
    .form-group select,.form-group input{padding:.4rem .5rem;border:1px solid #cbd5e1;border-radius:4px;font-size:.82rem}
    .key-ok{font-size:.72rem;color:#16a34a;font-weight:500}
    .key-missing{font-size:.72rem;color:#ef4444;font-weight:500}
    .settings-msg{padding:.4rem .75rem;border-radius:4px;font-size:.8rem;margin-bottom:.5rem;background:#ecfdf5;color:#065f46;border:1px solid #a7f3d0}
    .settings-msg.error{background:#fef2f2;color:#991b1b;border-color:#fecaca}

    /* Column Picker */
    .column-picker-wrapper{position:relative;display:inline-block}
    .column-picker{position:absolute;top:100%;right:0;background:#fff;border:1px solid #d1d5db;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,.15);z-index:100;min-width:180px;padding:.5rem 0}
    .picker-header{padding:.4rem .75rem;font-weight:600;font-size:.78rem;color:#374151;border-bottom:1px solid #e5e7eb}
    .picker-item{display:flex;align-items:center;gap:.5rem;padding:.3rem .75rem;font-size:.78rem;cursor:pointer}
    .picker-item:hover{background:#f3f4f6}
    .picker-item input{accent-color:#2563eb}
    .btn-icon{padding:.35rem;border:1px solid #cbd5e1;border-radius:4px;cursor:pointer;background:#fff;display:flex;align-items:center}
    .btn-icon:hover{background:#f3f4f6}

    .sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
    .sortable-th:hover{background:#eef2ff;color:#2563eb}
    .sort-icon{font-size:.65rem;margin-left:2px;color:#9ca3af}

    /* LinkedIn Section */
    .linkedin-section{background:#f0f7ff;padding:.85rem;border-radius:8px;margin-bottom:.75rem;border:1px solid #bfdbfe}
    .linkedin-header{display:flex;align-items:center;gap:.5rem;margin-bottom:.5rem}
    .linkedin-url{font-size:.72rem;color:#0a66c2;text-decoration:none;margin-left:auto;word-break:break-all}
    .linkedin-url:hover{text-decoration:underline}
    .li-profile-data{margin-bottom:.65rem}
    .li-profile-type{display:flex;align-items:center;gap:.5rem;margin-bottom:.4rem}
    .li-type-badge{padding:2px 8px;border-radius:10px;font-size:.72rem;font-weight:600}
    .li-type-individual{background:#ede9fe;color:#6d28d9}
    .li-type-company{background:#dbeafe;color:#1d4ed8}
    .li-scraped-at{font-size:.7rem;color:#9ca3af}
    .li-headline{font-size:.82rem;color:#374151;margin-bottom:.4rem;font-style:italic}
    .li-about{font-size:.8rem;margin-bottom:.4rem}
    .li-about p{margin:.25rem 0 0;color:#475569;line-height:1.4;white-space:pre-wrap}
    .li-contact{font-size:.8rem}
    .li-contact-json{font-size:.72rem;background:#fff;padding:.4rem;border-radius:4px;margin:.25rem 0 0;white-space:pre-wrap;word-break:break-all;border:1px solid #e2e8f0}
    .li-actions{display:flex;gap:.5rem;margin-bottom:.65rem}
    .btn-linkedin-scrub{background:#0a66c2;color:#fff;display:inline-flex;align-items:center;gap:4px}
    .btn-linkedin-scrub:hover{background:#004182}
    .btn-linkedin-scrub:disabled{opacity:.5;cursor:not-allowed}
    .btn-linkedin-posts{background:#7c3aed;color:#fff;display:inline-flex;align-items:center;gap:4px}
    .btn-linkedin-posts:hover{background:#6d28d9}
    .btn-linkedin-posts:disabled{opacity:.5;cursor:not-allowed}
    .li-posts{margin-top:.5rem}
    .li-posts > strong{font-size:.82rem;display:block;margin-bottom:.4rem}
    .li-post-item{background:#fff;padding:.5rem;border-radius:6px;margin-bottom:.35rem;border:1px solid #e5e7eb}
    .li-post-content{font-size:.78rem;color:#374151;line-height:1.4}
    .li-post-meta{display:flex;gap:.75rem;margin-top:.3rem;font-size:.7rem;color:#9ca3af}
    .modal-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:.75rem}
    .modal-close{cursor:pointer;font-size:1.3rem;color:#9ca3af}
    .modal-close:hover{color:#374151}

    /* Icon Buttons */
    .icon-btn{position:relative;width:30px;height:30px;display:inline-flex;align-items:center;justify-content:center;border:1px solid #d1d5db;border-radius:6px;background:#fff;cursor:pointer;color:#6b7280;transition:all .15s}
    .icon-btn:hover{background:#f3f4f6;border-color:#9ca3af;color:#374151}
    .icon-btn:disabled{opacity:.4;cursor:not-allowed}
    .icon-btn.done{border-color:#86efac;background:#f0fdf4;color:#16a34a}
    .icon-btn.done:hover{background:#dcfce7}
    .icon-btn .tick{position:absolute;top:-4px;right:-4px;width:14px;height:14px;background:#16a34a;color:#fff;border-radius:50%;font-size:9px;display:flex;align-items:center;justify-content:center;font-weight:700;line-height:1}
    .icon-btn .spinner{position:absolute;top:-4px;right:-4px;width:14px;height:14px;border:2px solid #d1d5db;border-top-color:#2563eb;border-radius:50%;animation:spin .6s linear infinite}
    @keyframes spin{to{transform:rotate(360deg)}}
    .icon-btn.icon-linkedin{color:#0a66c2;border-color:#bfdbfe}
    .icon-btn.icon-linkedin.done{border-color:#0a66c2;background:#eff6ff}
    .icon-btn.icon-linkedin.done svg{fill:#0a66c2}
    .icon-btn.icon-data{color:#7c3aed;border-color:#ddd6fe}
    .icon-btn.icon-data:hover{background:#f5f3ff;border-color:#7c3aed}
    .icon-btn.icon-link-out{color:#2563eb;border-color:#bfdbfe;text-decoration:none}
    .icon-btn.icon-link-out:hover{background:#eff6ff}

    /* Full Data Modal */
    .data-modal{background:#fff;border-radius:12px;width:820px;max-width:95vw;max-height:90vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,.2)}
    .data-modal-header{display:flex;justify-content:space-between;align-items:center;padding:1rem 1.25rem;border-bottom:1px solid #e5e7eb}
    .data-modal-header h3{margin:0;font-size:1.05rem;color:#1e293b}
    .data-modal-body{padding:1rem 1.25rem;overflow-y:auto;display:flex;flex-direction:column;gap:.85rem}
    .data-row-2col{display:grid;grid-template-columns:1fr 1fr;gap:.85rem}
    .data-section{background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:.85rem}
    .data-section-title{display:flex;align-items:center;gap:.4rem;font-weight:600;font-size:.82rem;color:#374151;margin-bottom:.6rem;padding-bottom:.4rem;border-bottom:1px solid #e5e7eb}
    .section-badge{padding:1px 6px;border-radius:10px;font-size:.65rem;font-weight:600;margin-left:auto}
    .done-badge{background:#d1fae5;color:#065f46}
    .pending-badge{background:#fef3c7;color:#92400e}
    .data-fields{display:grid;grid-template-columns:1fr 1fr;gap:.3rem .75rem}
    .data-field{display:flex;gap:.4rem;font-size:.8rem;align-items:center}
    .data-label{color:#6b7280;font-weight:500;white-space:nowrap;min-width:60px}
    .data-value{color:#1e293b}
    .data-empty{font-size:.8rem;color:#9ca3af;font-style:italic;padding:.25rem 0}
    .data-empty-action{display:flex;align-items:center;gap:.5rem;margin-top:.4rem}
    .data-empty-text{font-size:.78rem;color:#9ca3af;font-style:italic}
    .ai-summary-box{background:#ede9fe;border-radius:6px;padding:.5rem .65rem;font-size:.8rem;color:#374151;line-height:1.5;margin-top:.4rem}

    /* Signal Cards */
    .signal-card{background:#fff;border:1px solid #e5e7eb;border-radius:6px;padding:.65rem;margin-bottom:.4rem}
    .signal-card-header{display:flex;align-items:center;gap:.5rem;margin-bottom:.35rem}
    .signal-author{font-weight:600;font-size:.8rem;color:#374151}
    .signal-date{font-size:.72rem;color:#9ca3af;margin-left:auto}
    .signal-card-content{font-size:.82rem;color:#374151;line-height:1.5;white-space:pre-wrap;word-break:break-word}
    .signal-card-ai{display:flex;gap:.4rem;margin-top:.4rem;flex-wrap:wrap}
    .signal-card-summary{font-size:.78rem;color:#6b7280;margin-top:.3rem;font-style:italic}
    .signal-card-link{font-size:.75rem;color:#2563eb;text-decoration:none;display:inline-block;margin-top:.35rem}
    .signal-card-link:hover{text-decoration:underline}

    /* LinkedIn Data in Modal */
    .li-data-card{background:#fff;border:1px solid #bfdbfe;border-radius:6px;padding:.65rem}
    .li-data-header{display:flex;align-items:center;gap:.5rem;margin-bottom:.4rem}
    .li-data-headline{font-size:.85rem;color:#374151;font-style:italic;margin-bottom:.4rem}
    .li-data-about{font-size:.8rem;margin-bottom:.4rem}
    .li-data-about p{margin:.2rem 0 0;color:#475569;line-height:1.5;white-space:pre-wrap}
    .li-data-contact{font-size:.8rem}
    .li-data-contact pre{background:#f8fafc;padding:.4rem;border-radius:4px;margin:.2rem 0 0;font-size:.72rem;white-space:pre-wrap;word-break:break-all;border:1px solid #e2e8f0}

    /* LinkedIn Posts in Modal */
    .li-post-card{background:#fff;border:1px solid #e5e7eb;border-radius:6px;padding:.6rem;margin-bottom:.35rem}
    .li-post-card.hidden-post{display:none}
    .li-post-card-content{font-size:.8rem;color:#374151;line-height:1.5;white-space:pre-wrap;word-break:break-word}
    .li-post-card-meta{display:flex;gap:.75rem;margin-top:.3rem;font-size:.72rem;color:#9ca3af}
    .meta-engagement{font-weight:500}
    .show-all-btn{width:100%;text-align:center;margin-top:.25rem}

    @media (max-width:700px){
      .data-row-2col{grid-template-columns:1fr}
      .data-modal{width:98vw}
    }
  `]
})
export class ProspectsComponent implements OnInit {
  prospects: ProspectResponse[] = [];
  selectedProspect: ProspectResponse | null = null;
  viewMode: 'table' | 'card' = 'table';
  totalPages = 0;
  totalCount = 0;
  categories = ['Home', 'Auto', 'Life', 'Health', 'Commercial'];
  showColumnPicker = false;
  searchText = '';

  // Action states
  reprocessing = false;
  analyzingAll = false;
  analyzingIds = new Set<number>();
  searchingLinkedIn: Record<number, boolean> = {};
  linkedInCandidates: any[] = [];
  linkedInPickerName = '';
  linkedInPickerProspect: ProspectResponse | null = null;
  scrubbingProfile = false;
  scrubbingPosts = false;
  scrubbingProfileIds = new Set<number>();
  scrubbingPostsIds = new Set<number>();
  scrubbedPostsIds = new Set<number>();
  lookingUpIds = new Set<number>();
  linkedInPosts: any[] = [];
  infoMessage = '';
  infoError = false;

  // Full Data Modal
  fullData: ProspectFullDataResponse | null = null;
  loadingFullData: number | null = null;
  showAllPosts = false;

  // Stats
  stats = { total: 0, analyzed: 0, hot: 0, warm: 0, newCount: 0, contacted: 0 };

  // AI Settings
  showSettings = false;
  aiSettings: any = null;
  settingsForm = { aiProvider: 'Local', apiKey: '', aiModel: '' };
  savingSettings = false;
  testingAi = false;
  settingsMsg = '';
  settingsError = false;


  columns: ColumnDef[] = [
    { key: 'name', label: 'Name', visible: true },
    { key: 'score', label: 'Match', visible: true },
    { key: 'intentScore', label: 'Intent', visible: false },
    { key: 'intentCategory', label: 'Category', visible: true },
    { key: 'sentiment', label: 'Sentiment', visible: true },
    { key: 'aiSummary', label: 'AI Summary', visible: true },
    { key: 'urgency', label: 'Urgency', visible: false },
    { key: 'platform', label: 'Platform', visible: false },
    { key: 'location', label: 'Location', visible: true },
    { key: 'postDate', label: 'Post Date', visible: true },
    { key: 'status', label: 'Status', visible: true },
    { key: 'company', label: 'Company', visible: false },
    { key: 'email', label: 'Email', visible: false },
    { key: 'phone', label: 'Phone', visible: false },
    { key: 'enrichment', label: 'Enrichment', visible: false },
    { key: 'createdAt', label: 'Created At', visible: false },
  ];

  private sortFieldMap: Record<string, string> = {
    name: 'name', score: 'score', intentScore: 'intentscore',
    intentCategory: 'intentcategory', sentiment: 'sentiment',
    urgency: 'urgency', category: 'category', platform: 'platform',
    location: 'city', status: 'status', createdAt: 'date', postDate: 'postdate',
  };

  filter: ProspectFilter = { sortBy: 'score', sortDesc: true, page: 1, pageSize: 20 };

  constructor(private prospectService: ProspectService) {}

  private readonly COLUMNS_STORAGE_KEY = 'prospects_columnVisibility_v2';

  ngOnInit(): void {
    this.loadColumnSettings();
    this.loadProspects();
    this.loadAiSettings();
  }

  loadProspects(): void {
    this.prospectService.getAll(this.filter).subscribe(res => {
      this.prospects = res.items;
      this.totalPages = res.totalPages;
      this.totalCount = res.totalCount;
      this.updateStats();
    });
  }

  updateStats(): void {
    this.stats.total = this.totalCount;
    this.stats.analyzed = this.prospects.filter(p => p.analyzedAt !== null).length;
    this.stats.hot = this.prospects.filter(p => p.urgency === 'Hot').length;
    this.stats.warm = this.prospects.filter(p => p.urgency === 'Warm').length;
    this.stats.newCount = this.prospects.filter(p => p.status === 'New').length;
    this.stats.contacted = this.prospects.filter(p => p.status === 'Contacted').length;
  }

  onSearch(): void {
    this.filter.search = this.searchText || undefined;
    this.filter.page = 1;
    this.loadProspects();
  }

  goPage(page: number): void { this.filter.page = page; this.loadProspects(); }

  changeStatus(p: ProspectResponse, newStatus: string): void {
    this.prospectService.updateStatus(p.id, newStatus).subscribe(updated => {
      if (this.selectedProspect?.id === p.id) this.selectedProspect = updated;
      this.loadProspects();
    });
  }

  // === Actions ===

  reprocess(): void {
    this.reprocessing = true;
    this.infoMessage = '';
    this.prospectService.reprocess().subscribe({
      next: (res) => {
        this.reprocessing = false;
        this.infoError = false;
        this.infoMessage = `${res.message} — ${res.prospects} prospects, ${res.keywordMatches} keyword matches`;
        this.loadProspects();
      },
      error: () => {
        this.reprocessing = false;
        this.infoError = true;
        this.infoMessage = 'Reprocessing failed';
      }
    });
  }

  analyzeAll(): void {
    this.analyzingAll = true;
    this.infoMessage = '';
    this.prospectService.analyzeAll().subscribe({
      next: (res) => {
        this.analyzingAll = false;
        this.infoError = false;
        this.infoMessage = `${res.message} (${res.provider})`;
        this.loadProspects();
      },
      error: (err) => {
        this.analyzingAll = false;
        this.infoError = true;
        this.infoMessage = err.error?.error || 'AI analysis failed';
      }
    });
  }

  analyzeProspect(p: ProspectResponse): void {
    this.analyzingIds.add(p.id);
    this.prospectService.analyzeProspect(p.id).subscribe({
      next: (res) => {
        this.analyzingIds.delete(p.id);
        if (res.prospect) {
          Object.assign(p, res.prospect);
        }
      },
      error: (err) => {
        this.analyzingIds.delete(p.id);
        this.infoError = true;
        this.infoMessage = err.error?.error || 'Analysis failed';
      }
    });
  }

  // === LinkedIn Search ===

  searchLinkedIn(p: ProspectResponse): void {
    this.searchingLinkedIn[p.id] = true;
    this.prospectService.searchLinkedIn(p.id).subscribe({
      next: (res: any) => {
        this.searchingLinkedIn[p.id] = false;
        if (res.alreadyHasUrl) {
          p.linkedInUrl = res.linkedInUrl;
          return;
        }
        if (!res.success) {
          this.infoError = true;
          this.infoMessage = res.error || 'LinkedIn search failed';
          return;
        }
        this.linkedInCandidates = res.candidates;
        this.linkedInPickerName = p.name;
        this.linkedInPickerProspect = p;
      },
      error: () => {
        this.searchingLinkedIn[p.id] = false;
        this.infoError = true;
        this.infoMessage = 'LinkedIn search failed';
      }
    });
  }

  pickLinkedIn(url: string): void {
    const p = this.linkedInPickerProspect;
    if (!p) return;
    this.prospectService.saveLinkedIn(p.id, url).subscribe({
      next: (res: any) => {
        if (res.success && res.prospect) {
          Object.assign(p, res.prospect);
        } else {
          p.linkedInUrl = url;
        }
        this.linkedInCandidates = [];
        this.linkedInPickerProspect = null;
      },
      error: () => {
        p.linkedInUrl = url;
        this.linkedInCandidates = [];
        this.linkedInPickerProspect = null;
      }
    });
  }

  // === LinkedIn Scrub ===

  scrubProfile(p: ProspectResponse): void {
    this.scrubbingProfile = true;
    this.prospectService.scrubLinkedInProfile(p.id).subscribe({
      next: (res: any) => {
        this.scrubbingProfile = false;
        if (res.success) {
          // Update the prospect with new LinkedIn data
          p.linkedInType = res.profile.linkedInType;
          p.linkedInHeadline = res.profile.linkedInHeadline;
          p.linkedInAbout = res.profile.linkedInAbout;
          p.linkedInContactInfo = res.profile.linkedInContactInfo;
          p.linkedInPhotoUrl = res.profile.linkedInPhotoUrl;
          p.linkedInScrapedAt = res.profile.linkedInScrapedAt;
          this.infoError = false;
          this.infoMessage = 'LinkedIn profile scraped successfully';
        } else {
          this.infoError = true;
          this.infoMessage = res.error || 'Profile scrub failed';
        }
      },
      error: (err) => {
        this.scrubbingProfile = false;
        this.infoError = true;
        this.infoMessage = err.error?.error || 'Profile scrub failed';
      }
    });
  }

  scrubPosts(p: ProspectResponse): void {
    this.scrubbingPosts = true;
    this.prospectService.scrubLinkedInPosts(p.id).subscribe({
      next: (res: any) => {
        this.scrubbingPosts = false;
        if (res.success) {
          this.linkedInPosts = res.posts || [];
          this.infoError = false;
          this.infoMessage = `Scraped ${res.postsCount} LinkedIn posts`;
        } else {
          this.infoError = true;
          this.infoMessage = res.error || 'Posts scrub failed';
        }
      },
      error: (err) => {
        this.scrubbingPosts = false;
        this.infoError = true;
        this.infoMessage = err.error?.error || 'Posts scrub failed';
      }
    });
  }

  closeDetail(): void {
    this.selectedProspect = null;
    this.linkedInPosts = [];
  }

  selectProspect(p: ProspectResponse): void {
    this.selectedProspect = p;
    this.linkedInPosts = [];
    // Load existing LinkedIn posts if profile has been scraped
    if (p.linkedInScrapedAt) {
      this.prospectService.getLinkedInPosts(p.id).subscribe({
        next: (posts) => this.linkedInPosts = posts,
        error: () => {}
      });
    }
  }

  formatContactInfo(json: string | null): string {
    if (!json) return '';
    try {
      const obj = JSON.parse(json);
      return Object.entries(obj)
        .filter(([, v]) => v && v !== '' && v !== null)
        .map(([k, v]) => `${k}: ${v}`)
        .join('\n') || 'No contact info available';
    } catch {
      return json;
    }
  }

  // === AI Settings ===

  loadAiSettings(): void {
    this.prospectService.getAiSettings().subscribe(s => {
      this.aiSettings = s;
      this.settingsForm.aiProvider = s.aiProvider;
      this.settingsForm.aiModel = s.aiModel || '';
    });
  }

  onProviderChange(): void {
    this.settingsForm.apiKey = '';
    this.settingsMsg = '';
    const defaults: Record<string, string> = {
      'Claude': 'claude-sonnet-4-6',
      'OpenAI': 'gpt-4o-mini',
      'Google': 'gemini-2.0-flash'
    };
    this.settingsForm.aiModel = defaults[this.settingsForm.aiProvider] || '';
  }

  saveAiSettings(): void {
    this.savingSettings = true;
    this.settingsMsg = '';
    const body: any = { aiProvider: this.settingsForm.aiProvider, aiModel: this.settingsForm.aiModel || null };
    if (this.settingsForm.apiKey) body.apiKey = this.settingsForm.apiKey;
    this.prospectService.updateAiSettings(body).subscribe({
      next: (res) => {
        this.aiSettings = res;
        this.settingsMsg = 'AI settings saved';
        this.settingsError = false;
        this.savingSettings = false;
        this.settingsForm.apiKey = '';
      },
      error: () => {
        this.settingsMsg = 'Failed to save';
        this.settingsError = true;
        this.savingSettings = false;
      }
    });
  }

  testAiKey(): void {
    this.testingAi = true;
    this.settingsMsg = '';
    this.prospectService.testAiKey().subscribe({
      next: (res) => {
        this.testingAi = false;
        this.settingsMsg = res.success ? res.message : res.error;
        this.settingsError = !res.success;
      },
      error: () => {
        this.testingAi = false;
        this.settingsMsg = 'Test failed';
        this.settingsError = true;
      }
    });
  }

  // === Full Data Modal ===

  openDataModal(p: ProspectResponse): void {
    this.loadingFullData = p.id;
    this.showAllPosts = false;
    this.prospectService.getFullData(p.id).subscribe({
      next: (data) => {
        this.fullData = data;
        this.loadingFullData = null;
      },
      error: () => {
        this.loadingFullData = null;
        this.infoError = true;
        this.infoMessage = 'Failed to load prospect data';
      }
    });
  }

  closeDataModal(): void {
    this.fullData = null;
    this.showAllPosts = false;
  }

  // === Table-level actions ===

  lookupContact(p: ProspectResponse): void {
    this.lookingUpIds.add(p.id);
    this.prospectService.lookupContact(p.id).subscribe({
      next: (res: any) => {
        this.lookingUpIds.delete(p.id);
        if (res.success && res.prospect) {
          Object.assign(p, res.prospect);
          this.infoError = false;
          this.infoMessage = `Contact found via ${res.provider}`;
        } else {
          this.infoError = true;
          this.infoMessage = res.error || 'Contact lookup failed';
        }
      },
      error: (err) => {
        this.lookingUpIds.delete(p.id);
        this.infoError = true;
        this.infoMessage = err.error?.error || 'Contact lookup failed';
      }
    });
  }

  scrubProfileFromTable(p: ProspectResponse): void {
    this.scrubbingProfileIds.add(p.id);
    this.prospectService.scrubLinkedInProfile(p.id).subscribe({
      next: (res: any) => {
        this.scrubbingProfileIds.delete(p.id);
        if (res.success) {
          p.linkedInType = res.profile.linkedInType;
          p.linkedInHeadline = res.profile.linkedInHeadline;
          p.linkedInAbout = res.profile.linkedInAbout;
          p.linkedInContactInfo = res.profile.linkedInContactInfo;
          p.linkedInPhotoUrl = res.profile.linkedInPhotoUrl;
          p.linkedInScrapedAt = res.profile.linkedInScrapedAt;
          this.infoError = false;
          this.infoMessage = 'LinkedIn profile scraped';
        } else {
          this.infoError = true;
          this.infoMessage = res.error || 'Profile scrub failed';
        }
      },
      error: (err) => {
        this.scrubbingProfileIds.delete(p.id);
        this.infoError = true;
        this.infoMessage = err.error?.error || 'Profile scrub failed';
      }
    });
  }

  scrubPostsFromTable(p: ProspectResponse): void {
    this.scrubbingPostsIds.add(p.id);
    this.prospectService.scrubLinkedInPosts(p.id).subscribe({
      next: (res: any) => {
        this.scrubbingPostsIds.delete(p.id);
        if (res.success) {
          this.scrubbedPostsIds.add(p.id);
          this.infoError = false;
          this.infoMessage = `Scraped ${res.postsCount} LinkedIn posts for ${p.name}`;
        } else {
          this.infoError = true;
          this.infoMessage = res.error || 'Posts scrub failed';
        }
      },
      error: (err) => {
        this.scrubbingPostsIds.delete(p.id);
        this.infoError = true;
        this.infoMessage = err.error?.error || 'Posts scrub failed';
      }
    });
  }

  // === Data modal actions ===

  lookupContactFromData(): void {
    if (!this.fullData) return;
    const id = this.fullData.prospect.id;
    this.lookingUpIds.add(id);
    this.prospectService.lookupContact(id).subscribe({
      next: (res: any) => {
        this.lookingUpIds.delete(id);
        if (res.success && res.prospect) {
          this.fullData!.prospect = res.prospect;
          const p = this.prospects.find(x => x.id === id);
          if (p) Object.assign(p, res.prospect);
        }
      },
      error: () => this.lookingUpIds.delete(id)
    });
  }

  analyzeFromData(): void {
    if (!this.fullData) return;
    const id = this.fullData.prospect.id;
    this.analyzingIds.add(id);
    this.prospectService.analyzeProspect(id).subscribe({
      next: (res: any) => {
        this.analyzingIds.delete(id);
        if (res.prospect) {
          this.fullData!.prospect = res.prospect;
          const p = this.prospects.find(x => x.id === id);
          if (p) Object.assign(p, res.prospect);
        }
      },
      error: () => this.analyzingIds.delete(id)
    });
  }

  scrubProfileFromData(): void {
    if (!this.fullData) return;
    const id = this.fullData.prospect.id;
    this.scrubbingProfileIds.add(id);
    this.prospectService.scrubLinkedInProfile(id).subscribe({
      next: (res: any) => {
        this.scrubbingProfileIds.delete(id);
        if (res.success) {
          this.fullData!.prospect.linkedInType = res.profile.linkedInType;
          this.fullData!.prospect.linkedInHeadline = res.profile.linkedInHeadline;
          this.fullData!.prospect.linkedInAbout = res.profile.linkedInAbout;
          this.fullData!.prospect.linkedInContactInfo = res.profile.linkedInContactInfo;
          this.fullData!.prospect.linkedInPhotoUrl = res.profile.linkedInPhotoUrl;
          this.fullData!.prospect.linkedInScrapedAt = res.profile.linkedInScrapedAt;
        }
      },
      error: () => this.scrubbingProfileIds.delete(id)
    });
  }

  scrubPostsFromData(): void {
    if (!this.fullData) return;
    const id = this.fullData.prospect.id;
    this.scrubbingPostsIds.add(id);
    this.prospectService.scrubLinkedInPosts(id).subscribe({
      next: (res: any) => {
        this.scrubbingPostsIds.delete(id);
        if (res.success) {
          this.fullData!.linkedInPosts = (res.posts || []).map((p: any) => ({
            id: 0, content: p.content, postUrl: null, postDate: p.postDate, likes: p.likes, comments: p.comments, scrapedAt: new Date().toISOString()
          }));
        }
      },
      error: () => this.scrubbingPostsIds.delete(id)
    });
  }

  // === Utilities ===

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

  truncate(text: string, max: number): string {
    return text.length > max ? text.substring(0, max) + '…' : text;
  }

  scoreClass(score: number): string {
    if (score >= 70) return 'score score-high';
    if (score >= 40) return 'score score-med';
    return 'score score-low';
  }

  intentClass(score: number): string {
    if (score >= 60) return 'intent-badge intent-high';
    if (score >= 30) return 'intent-badge intent-med';
    return 'intent-badge intent-low';
  }

  // Column Picker
  loadColumnSettings(): void {
    try {
      const saved = localStorage.getItem(this.COLUMNS_STORAGE_KEY);
      if (saved) {
        const visibility: Record<string, boolean> = JSON.parse(saved);
        this.columns.forEach(col => {
          if (visibility.hasOwnProperty(col.key)) col.visible = visibility[col.key];
        });
      }
    } catch {}
  }

  saveColumnSettings(): void {
    const visibility: Record<string, boolean> = {};
    this.columns.forEach(col => visibility[col.key] = col.visible);
    localStorage.setItem(this.COLUMNS_STORAGE_KEY, JSON.stringify(visibility));
  }

  toggleColumnPicker($event: Event): void {
    $event.stopPropagation();
    this.showColumnPicker = !this.showColumnPicker;
  }

  @HostListener('document:click')
  onDocumentClick(): void { this.showColumnPicker = false; }

  isVisible(key: string): boolean {
    const col = this.columns.find(c => c.key === key);
    return col ? col.visible : false;
  }

  // Sorting
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
