import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../../environments/environment';

interface ColumnDef {
  key: string;
  label: string;
  sortable: boolean;
  sortField?: string;
  visible: boolean;
}

@Component({
  selector: 'app-signals',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="signals-page">
      <div class="action-bar">
        <button class="btn-secondary" (click)="analyzeAll()" [disabled]="analyzingAll">
          {{ analyzingAll ? 'Analyzing...' : 'AI Analyze All' }}
        </button>
        <button class="btn-icon" (click)="showSettingsModal = true" title="AI Settings">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/></svg>
        </button>
        <button class="btn-primary" (click)="reprocess()" [disabled]="reprocessing">
          {{ reprocessing ? 'Processing...' : 'Reprocess All Signals' }}
        </button>
        <div class="action-spacer"></div>
        <button class="btn-sm" [class.active]="viewMode === 'table'" (click)="viewMode = 'table'">Table</button>
        <button class="btn-sm" [class.active]="viewMode === 'card'" (click)="viewMode = 'card'">Cards</button>
        <div class="column-picker-wrapper">
          <button class="btn-icon" (click)="toggleColumnPicker($event)" title="Show/Hide Columns">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z"/></svg>
          </button>
          <div class="column-picker" *ngIf="showColumnPicker" (click)="$event.stopPropagation()">
            <div class="picker-header">Show/Hide Columns</div>
            <label *ngFor="let col of columns" class="picker-item">
              <input type="checkbox" [(ngModel)]="col.visible" />
              {{ col.label }}
            </label>
          </div>
        </div>
        <button class="btn-secondary" (click)="exportCsv()">Export CSV</button>
      </div>

      <!-- Stats Cards -->
      <div class="stats-row" *ngIf="stats">
        <div class="stat-card">
          <div class="stat-value">{{ stats.totalSignals }}</div>
          <div class="stat-label">Total Signals</div>
        </div>
        <div class="stat-card matched">
          <div class="stat-value">{{ stats.matchedSignals }}</div>
          <div class="stat-label">Matched</div>
        </div>
        <div class="stat-card unmatched">
          <div class="stat-value">{{ stats.unmatchedSignals }}</div>
          <div class="stat-label">Unmatched</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ stats.totalProspects }}</div>
          <div class="stat-label">Prospects Created</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ stats.activeKeywordRules }}</div>
          <div class="stat-label">Active Keywords</div>
        </div>
        <div class="stat-card ai-analyzed">
          <div class="stat-value">{{ stats.aiAnalyzed || 0 }}</div>
          <div class="stat-label">AI Analyzed</div>
        </div>
      </div>

      <!-- Filters -->
      <div class="filter-bar">
        <select [(ngModel)]="filterPlatform" (ngModelChange)="loadSignals()">
          <option value="">All Platforms</option>
          <option value="Reddit">Reddit</option>
          <option value="LinkedIn">LinkedIn</option>
          <option value="Facebook">Facebook</option>
          <option value="Nextdoor">Nextdoor</option>
          <option value="X">X</option>
        </select>
        <select [(ngModel)]="filterMatched" (ngModelChange)="loadSignals()">
          <option value="">All Signals</option>
          <option value="true">Matched Only</option>
          <option value="false">Unmatched Only</option>
        </select>
        <select [(ngModel)]="filterAnalyzed" (ngModelChange)="loadSignals()">
          <option value="">All (AI)</option>
          <option value="true">AI Analyzed</option>
          <option value="false">Not Analyzed</option>
        </select>
        <span class="result-count">Showing {{ signals.length }} of {{ total }} signals</span>
      </div>

      <!-- Success/Info Message -->
      <div *ngIf="infoMessage" class="info-message">{{ infoMessage }}</div>

      <!-- Signals Table -->
      <div class="table-card" *ngIf="viewMode === 'table'">
        <table>
          <thead>
            <tr>
              <th *ngIf="isVisible('id')" class="sortable-th" (click)="toggleSort('id')" style="width:40px">
                # <span class="sort-icon">{{ getSortIcon('id') }}</span>
              </th>
              <th *ngIf="isVisible('author')" class="sortable-th" (click)="toggleSort('author')">
                Author <span class="sort-icon">{{ getSortIcon('author') }}</span>
              </th>
              <th *ngIf="isVisible('platform')" class="sortable-th" (click)="toggleSort('platform')">
                Platform <span class="sort-icon">{{ getSortIcon('platform') }}</span>
              </th>
              <th *ngIf="isVisible('postContent')">Post Content</th>
              <th *ngIf="isVisible('postDate')" class="sortable-th" (click)="toggleSort('postDate')">
                Post Date <span class="sort-icon">{{ getSortIcon('postDate') }}</span>
              </th>
              <th *ngIf="isVisible('detectedAt')" class="sortable-th" (click)="toggleSort('detectedAt')">
                Detected <span class="sort-icon">{{ getSortIcon('detectedAt') }}</span>
              </th>
              <th *ngIf="isVisible('intentScore')" class="sortable-th" (click)="toggleSort('intentScore')">
                Intent Score <span class="sort-icon">{{ getSortIcon('intentScore') }}</span>
              </th>
              <th *ngIf="isVisible('category')" class="sortable-th" (click)="toggleSort('category')">
                Category <span class="sort-icon">{{ getSortIcon('category') }}</span>
              </th>
              <th *ngIf="isVisible('sentiment')" class="sortable-th" (click)="toggleSort('sentiment')">
                Sentiment <span class="sort-icon">{{ getSortIcon('sentiment') }}</span>
              </th>
              <th *ngIf="isVisible('aiSummary')">AI Summary</th>
              <th *ngIf="isVisible('matches')">Matches</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let signal of signals" [class.matched-row]="signal.matchCount > 0">
              <td *ngIf="isVisible('id')">{{ signal.id }}</td>
              <td *ngIf="isVisible('author')">
                <a *ngIf="signal.authorProfileUrl" [href]="signal.authorProfileUrl" target="_blank" class="author-link">
                  {{ signal.authorName }}
                </a>
                <span *ngIf="!signal.authorProfileUrl">{{ signal.authorName }}</span>
              </td>
              <td *ngIf="isVisible('platform')"><span class="platform-badge" [class]="'platform-' + signal.platform.toLowerCase()">{{ signal.platform }}</span></td>
              <td *ngIf="isVisible('postContent')" class="content-cell">
                <div class="content-preview">
                  <span class="content-meta-line">{{ getContentMeta(signal.fullContent) }}</span>
                  <span class="content-body-line">{{ getContentBody(signal.fullContent) }}</span>
                </div>
                <div class="content-tooltip">{{ signal.fullContent }}</div>
              </td>
              <td *ngIf="isVisible('postDate')">{{ signal.postDate ? (signal.postDate | date:'short') : '—' }}</td>
              <td *ngIf="isVisible('detectedAt')">{{ signal.detectedAt | date:'short' }}</td>
              <td *ngIf="isVisible('intentScore')">
                <span *ngIf="signal.intentScore !== null" class="intent-badge" [class]="getIntentClass(signal.intentScore)">
                  {{ signal.intentScore }}
                </span>
                <span *ngIf="signal.intentScore === null" class="intent-badge pending">—</span>
              </td>
              <td *ngIf="isVisible('category')">
                <span *ngIf="signal.intentCategory" class="category-tag">{{ signal.intentCategory }}</span>
              </td>
              <td *ngIf="isVisible('sentiment')">
                <span *ngIf="signal.sentiment" class="sentiment-tag" [class]="'sentiment-' + signal.sentiment?.toLowerCase()">
                  {{ signal.sentiment }}
                </span>
              </td>
              <td *ngIf="isVisible('aiSummary')" class="summary-cell">
                <small *ngIf="signal.aiSummary">{{ signal.aiSummary }}</small>
              </td>
              <td *ngIf="isVisible('matches')">
                <span *ngIf="signal.matchCount > 0" class="match-badge matched">{{ signal.matchCount }} match{{ signal.matchCount > 1 ? 'es' : '' }}</span>
                <span *ngIf="signal.matchCount === 0" class="match-badge none">No match</span>
                <div *ngIf="signal.matches?.length > 0" class="match-details">
                  <small *ngFor="let m of signal.matches">
                    "{{ m.matchedText }}" ({{ m.matchScore | number:'1.0-0' }}%)
                  </small>
                </div>
              </td>
              <td class="actions-cell">
                <button class="btn-sm btn-ai" (click)="analyzeSingle(signal)" [disabled]="signal.analyzing" title="AI Analyze">
                  {{ signal.analyzing ? '...' : 'Analyze' }}
                </button>
                <button class="btn-sm" (click)="openContentModal(signal)">View</button>
                <a *ngIf="signal.postUrl" [href]="signal.postUrl" target="_blank" class="btn-sm btn-link">Link</a>
              </td>
            </tr>
          </tbody>
          <tbody *ngIf="signals.length === 0">
            <tr><td [attr.colspan]="visibleColumnCount + 1" class="empty">No signals found. Run a sync to scrape posts.</td></tr>
          </tbody>
        </table>
      </div>

      <!-- Signals Card View -->
      <div *ngIf="viewMode === 'card'" class="cards-grid">
        <div *ngFor="let signal of signals" class="signal-card" [class.matched-card]="signal.matchCount > 0" (click)="openContentModal(signal)">
          <div class="card-top-row">
            <div>
              <strong class="card-author">{{ signal.authorName || 'Unknown' }}</strong>
              <span class="platform-badge" [class]="'platform-' + signal.platform.toLowerCase()">{{ signal.platform }}</span>
            </div>
            <span *ngIf="signal.intentScore !== null" class="intent-badge" [class]="getIntentClass(signal.intentScore)">{{ signal.intentScore }}</span>
            <span *ngIf="signal.intentScore === null" class="intent-badge pending">—</span>
          </div>
          <div class="card-badges">
            <span *ngIf="signal.intentCategory" class="category-tag">{{ signal.intentCategory }}</span>
            <span *ngIf="signal.sentiment" class="sentiment-tag" [class]="'sentiment-' + signal.sentiment?.toLowerCase()">{{ signal.sentiment }}</span>
            <span *ngIf="signal.matchCount > 0" class="match-badge matched">{{ signal.matchCount }} match{{ signal.matchCount > 1 ? 'es' : '' }}</span>
          </div>
          <p class="card-snippet">{{ signal.fullContent | slice:0:150 }}{{ signal.fullContent?.length > 150 ? '...' : '' }}</p>
          <div class="card-footer">
            <small class="card-date">{{ signal.postDate ? (signal.postDate | date:'mediumDate') : (signal.detectedAt | date:'mediumDate') }}</small>
            <div class="card-actions">
              <button class="btn-sm btn-ai" (click)="analyzeSingle(signal); $event.stopPropagation()" [disabled]="signal.analyzing">
                {{ signal.analyzing ? '...' : 'Analyze' }}
              </button>
              <a *ngIf="signal.postUrl" [href]="signal.postUrl" target="_blank" class="btn-sm btn-link" (click)="$event.stopPropagation()">Link</a>
            </div>
          </div>
        </div>
        <div *ngIf="signals.length === 0" class="empty">No signals found. Run a sync to scrape posts.</div>
      </div>

      <!-- Pagination -->
      <div class="pagination" *ngIf="total > pageSize">
        <button class="btn-sm" (click)="prevPage()" [disabled]="page <= 1">Previous</button>
        <span>Page {{ page }} of {{ totalPages }}</span>
        <button class="btn-sm" (click)="nextPage()" [disabled]="page >= totalPages">Next</button>
      </div>
    </div>

    <!-- Full Content Modal -->
    <div class="modal-overlay" *ngIf="contentModalSignal" (click)="contentModalSignal = null">
      <div class="modal modal-wide" (click)="$event.stopPropagation()">
        <div class="modal-header">
          <h3>
            Signal #{{ contentModalSignal.id }}
            <span class="platform-badge" [class]="'platform-' + contentModalSignal.platform.toLowerCase()" style="margin-left:8px">{{ contentModalSignal.platform }}</span>
            <span *ngIf="contentModalSignal.authorName" style="font-weight:400;font-size:0.85rem;color:#6b7280;margin-left:8px">by {{ contentModalSignal.authorName }}</span>
          </h3>
          <button class="btn-close" (click)="contentModalSignal = null">&times;</button>
        </div>
        <div class="modal-body">
          <div class="full-content-text">{{ contentModalSignal.fullContent }}</div>
          <div class="content-meta" *ngIf="contentModalSignal.postDate || contentModalSignal.postUrl">
            <span *ngIf="contentModalSignal.postDate">Posted: {{ contentModalSignal.postDate | date:'medium' }}</span>
            <a *ngIf="contentModalSignal.postUrl" [href]="contentModalSignal.postUrl" target="_blank" class="btn-sm btn-link" style="margin-left:1rem">View Original Post</a>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-sm" (click)="contentModalSignal = null">Close</button>
        </div>
      </div>
    </div>

    <!-- AI Settings Modal -->
    <div class="modal-overlay" *ngIf="showSettingsModal" (click)="showSettingsModal = false">
      <div class="modal" (click)="$event.stopPropagation()">
        <div class="modal-header">
          <h3>AI Analysis Settings</h3>
          <button class="btn-close" (click)="showSettingsModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>AI Provider</label>
            <select [(ngModel)]="settingsForm.aiProvider" (ngModelChange)="onProviderChange()">
              <option value="Local">Local (Free - Rule-based)</option>
              <option value="Claude">Claude (Anthropic API)</option>
              <option value="OpenAI">OpenAI</option>
              <option value="Google">Google AI (Gemini)</option>
            </select>
          </div>
          <div class="form-group" *ngIf="settingsForm.aiProvider !== 'Local'">
            <label>API Key</label>
            <input type="password" [(ngModel)]="settingsForm.apiKey"
                   [placeholder]="aiSettings?.hasApiKey ? '(key saved — enter new to update)' : 'Enter API key'" />
          </div>
          <div class="form-group" *ngIf="settingsForm.aiProvider !== 'Local'">
            <label>Model</label>
            <input type="text" [(ngModel)]="settingsForm.aiModel"
                   [placeholder]="settingsForm.aiProvider === 'Claude' ? 'claude-sonnet-4-6' : settingsForm.aiProvider === 'Google' ? 'gemini-2.0-flash' : 'gpt-4o-mini'" />
          </div>
          <div *ngIf="settingsMessage" class="settings-message" [class.error]="settingsError">{{ settingsMessage }}</div>
        </div>
        <div class="modal-footer">
          <button class="btn-sm" (click)="showSettingsModal = false">Cancel</button>
          <button class="btn-primary" (click)="saveSettings()" [disabled]="savingSettings">
            {{ savingSettings ? 'Saving...' : 'Save Settings' }}
          </button>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .signals-page { padding: 1.5rem; }
    .action-bar { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
    .action-spacer { flex: 1; }
    .stats-row { display: flex; gap: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
    .stat-card { background: white; border-radius: 8px; padding: 1rem 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; flex: 1; min-width: 120px; }
    .stat-card.matched { border-left: 4px solid #059669; }
    .stat-card.unmatched { border-left: 4px solid #d97706; }
    .stat-card.ai-analyzed { border-left: 4px solid #7c3aed; }
    .stat-value { font-size: 1.75rem; font-weight: 700; color: #1a1f36; }
    .stat-label { font-size: 0.75rem; text-transform: uppercase; color: #6b7280; letter-spacing: 0.05em; margin-top: 0.25rem; }
    .filter-bar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 1rem; }
    .filter-bar select { padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px; }
    .result-count { font-size: 0.875rem; color: #6b7280; margin-left: auto; }
    .info-message { background: #d1fae5; color: #065f46; padding: 0.75rem 1rem; border-radius: 8px; margin-bottom: 1rem; }
    .table-card { background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 0.6rem 0.75rem; text-align: left; border-bottom: 1px solid #e5e7eb; font-size: 0.85rem; }
    th { font-weight: 600; color: #374151; background: #f9fafb; position: sticky; top: 0; }
    .sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
    .sortable-th:hover { background: #eef2ff; color: #2563eb; }
    .sort-icon { font-size: 0.7rem; margin-left: 2px; color: #9ca3af; }
    .matched-row { background: #f0fdf4; }
    .author-link { color: #2563eb; text-decoration: none; }
    .author-link:hover { text-decoration: underline; }
    .platform-badge { padding: 0.15rem 0.5rem; border-radius: 12px; font-size: 0.7rem; font-weight: 600; color: white; }
    .platform-reddit { background: #ff4500; }
    .platform-linkedin { background: #0077b5; }
    .platform-facebook { background: #1877f2; }
    .platform-nextdoor { background: #8ed500; color: #333; }
    .platform-x { background: #000; }
    .content-cell { max-width: 380px; position: relative; }
    .content-preview { word-break: break-word; font-size: 0.8rem; color: #374151; line-height: 1.4; cursor: default; }
    .content-meta-line { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 0.7rem; color: #6b7280; font-weight: 500; margin-bottom: 2px; }
    .content-body-line { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; font-size: 0.8rem; color: #374151; line-height: 1.4; }
    .content-tooltip { display: none; position: absolute; left: 0; top: 100%; z-index: 999; background: #ffffff; color: #1f2937; padding: 1rem 1.25rem; border-radius: 8px; border: 1px solid #e5e7eb; box-shadow: 0 8px 30px rgba(0,0,0,0.15); white-space: pre-wrap; word-break: break-word; font-size: 0.85rem; line-height: 1.6; width: 500px; max-height: 400px; overflow-y: auto; }
    .content-cell:hover .content-tooltip { display: block; }
    .summary-cell { max-width: 200px; }
    .summary-cell small { color: #6b7280; font-size: 0.75rem; line-height: 1.3; display: block; }
    .intent-badge { display: inline-block; padding: 0.2rem 0.5rem; border-radius: 12px; font-size: 0.75rem; font-weight: 700; min-width: 32px; text-align: center; }
    .intent-high { background: #dc2626; color: white; }
    .intent-medium { background: #f59e0b; color: white; }
    .intent-low { background: #6b7280; color: white; }
    .intent-badge.pending { background: #e5e7eb; color: #9ca3af; }
    .category-tag { padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.7rem; font-weight: 600; background: #ede9fe; color: #6d28d9; }
    .sentiment-tag { padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.7rem; font-weight: 600; }
    .sentiment-urgent { background: #fef2f2; color: #dc2626; }
    .sentiment-negative { background: #fef3c7; color: #92400e; }
    .sentiment-positive { background: #d1fae5; color: #065f46; }
    .sentiment-neutral { background: #f3f4f6; color: #6b7280; }
    .match-badge { padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.7rem; font-weight: 600; }
    .match-badge.matched { background: #d1fae5; color: #065f46; }
    .match-badge.none { background: #fef3c7; color: #92400e; }
    .match-details { margin-top: 0.25rem; }
    .match-details small { display: block; color: #059669; font-size: 0.7rem; }
    .actions-cell { white-space: nowrap; }
    .empty { text-align: center; color: #9ca3af; padding: 2rem; }
    .pagination { display: flex; justify-content: center; align-items: center; gap: 1rem; padding: 1rem; }
    .btn-primary { padding: 0.5rem 1rem; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; }
    .btn-primary:hover { background: #1d4ed8; }
    .btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
    .btn-secondary { padding: 0.5rem 1rem; background: #7c3aed; color: white; border: none; border-radius: 4px; cursor: pointer; }
    .btn-secondary:hover { background: #6d28d9; }
    .btn-secondary:disabled { opacity: 0.6; cursor: not-allowed; }
    .btn-sm { padding: 0.25rem 0.5rem; font-size: 0.75rem; border: 1px solid #d1d5db; border-radius: 4px; cursor: pointer; background: white; }
    .btn-sm:hover { background: #f3f4f6; }
    .btn-sm:disabled { opacity: 0.5; }
    .btn-link { color: #2563eb; border-color: #2563eb; text-decoration: none; }
    .btn-ai { color: #7c3aed; border-color: #7c3aed; }
    .btn-ai:hover { background: #f5f3ff; }
    .btn-icon { background: none; border: 1px solid #d1d5db; border-radius: 4px; padding: 0.4rem; cursor: pointer; display: flex; align-items: center; color: #6b7280; }
    .btn-icon:hover { background: #f3f4f6; color: #374151; }

    /* Column Picker */
    .column-picker-wrapper { position: relative; }
    .column-picker {
      position: absolute; top: 100%; right: 0; margin-top: 4px; z-index: 100;
      background: white; border: 1px solid #e5e7eb; border-radius: 8px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.15); min-width: 200px; padding: 0.5rem 0;
    }
    .picker-header { padding: 0.5rem 1rem; font-weight: 600; font-size: 0.8rem; color: #374151; border-bottom: 1px solid #e5e7eb; }
    .picker-item {
      display: flex; align-items: center; gap: 0.5rem; padding: 0.4rem 1rem;
      font-size: 0.8rem; color: #374151; cursor: pointer;
    }
    .picker-item:hover { background: #f3f4f6; }
    .picker-item input[type="checkbox"] { accent-color: #2563eb; }

    /* Modal */
    .modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; }
    .modal { background: white; border-radius: 12px; width: 480px; max-width: 90vw; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }
    .modal-header { display: flex; justify-content: space-between; align-items: center; padding: 1rem 1.5rem; border-bottom: 1px solid #e5e7eb; }
    .modal-header h3 { margin: 0; font-size: 1.1rem; }
    .btn-close { background: none; border: none; font-size: 1.5rem; cursor: pointer; color: #6b7280; }
    .modal-body { padding: 1.5rem; }
    .form-group { margin-bottom: 1rem; }
    .form-group label { display: block; font-size: 0.85rem; font-weight: 600; color: #374151; margin-bottom: 0.3rem; }
    .form-group select, .form-group input { width: 100%; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px; font-size: 0.9rem; box-sizing: border-box; }
    .modal-footer { display: flex; justify-content: flex-end; gap: 0.5rem; padding: 1rem 1.5rem; border-top: 1px solid #e5e7eb; }
    .settings-message { padding: 0.5rem; border-radius: 4px; font-size: 0.85rem; background: #d1fae5; color: #065f46; margin-top: 0.5rem; }
    .settings-message.error { background: #fef2f2; color: #dc2626; }

    /* View Toggle */
    .btn-sm.active { background: #2563eb; color: white; border-color: #2563eb; }

    /* Card View */
    .cards-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1rem; }
    .signal-card { background: white; border-radius: 8px; padding: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); cursor: pointer; transition: box-shadow 0.2s; }
    .signal-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.15); }
    .signal-card.matched-card { border-left: 3px solid #059669; }
    .card-top-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem; }
    .card-author { display: block; font-size: 0.9rem; margin-bottom: 0.2rem; }
    .card-badges { display: flex; gap: 0.4rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
    .card-snippet { font-size: 0.8rem; color: #6b7280; margin: 0 0 0.75rem; line-height: 1.4; }
    .card-footer { display: flex; justify-content: space-between; align-items: center; }
    .card-date { color: #9ca3af; font-size: 0.75rem; }
    .card-actions { display: flex; gap: 0.25rem; }

    /* Content Modal */
    .modal-wide { width: 700px; max-width: 90vw; }
    .full-content-text { white-space: pre-wrap; word-break: break-word; font-size: 0.9rem; color: #1f2937; line-height: 1.6; max-height: 60vh; overflow-y: auto; padding: 0.5rem; background: #f9fafb; border-radius: 6px; border: 1px solid #e5e7eb; }
    .content-meta { margin-top: 1rem; font-size: 0.8rem; color: #6b7280; display: flex; align-items: center; }
  `],
  host: {
    '(document:click)': 'onDocumentClick($event)'
  }
})
export class SignalsComponent implements OnInit {
  signals: any[] = [];
  stats: any = null;
  total = 0;
  page = 1;
  pageSize = 50;
  viewMode: 'table' | 'card' = 'table';
  filterPlatform = '';
  filterMatched = '';
  filterAnalyzed = '';
  contentModalSignal: any = null;
  reprocessing = false;
  analyzingAll = false;
  infoMessage = '';

  // Sorting
  sortBy = 'detectedAt';
  sortDir: 'asc' | 'desc' = 'desc';

  // Column visibility
  showColumnPicker = false;
  columns: ColumnDef[] = [
    { key: 'id', label: '#', sortable: true, sortField: 'id', visible: true },
    { key: 'author', label: 'Author', sortable: true, sortField: 'author', visible: true },
    { key: 'platform', label: 'Platform', sortable: true, sortField: 'platform', visible: true },
    { key: 'postContent', label: 'Post Content', sortable: false, visible: true },
    { key: 'postDate', label: 'Post Date', sortable: true, sortField: 'postDate', visible: true },
    { key: 'detectedAt', label: 'Detected', sortable: true, sortField: 'detectedAt', visible: true },
    { key: 'intentScore', label: 'Intent Score', sortable: true, sortField: 'intentScore', visible: true },
    { key: 'category', label: 'Category', sortable: true, sortField: 'category', visible: true },
    { key: 'sentiment', label: 'Sentiment', sortable: true, sortField: 'sentiment', visible: true },
    { key: 'aiSummary', label: 'AI Summary', sortable: false, visible: true },
    { key: 'matches', label: 'Matches', sortable: false, visible: true },
  ];

  // AI Settings modal
  showSettingsModal = false;
  aiSettings: any = null;
  settingsForm = { aiProvider: 'Local', apiKey: '', aiModel: '' };
  savingSettings = false;
  settingsMessage = '';
  settingsError = false;

  private apiUrl = environment.apiUrl;

  constructor(private http: HttpClient) {}

  ngOnInit(): void {
    this.loadStats();
    this.loadSignals();
    this.loadAiSettings();
  }

  get totalPages(): number {
    return Math.ceil(this.total / this.pageSize);
  }

  get visibleColumnCount(): number {
    return this.columns.filter(c => c.visible).length;
  }

  isVisible(key: string): boolean {
    return this.columns.find(c => c.key === key)?.visible ?? true;
  }

  getIntentClass(score: number): string {
    if (score >= 60) return 'intent-high';
    if (score >= 30) return 'intent-medium';
    return 'intent-low';
  }

  toggleSort(field: string): void {
    if (this.sortBy === field) {
      this.sortDir = this.sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      this.sortBy = field;
      this.sortDir = 'desc';
    }
    this.page = 1;
    this.loadSignals();
  }

  getSortIcon(field: string): string {
    if (this.sortBy !== field) return '';
    return this.sortDir === 'asc' ? '\u25B2' : '\u25BC';
  }

  toggleColumnPicker(event: Event): void {
    event.stopPropagation();
    this.showColumnPicker = !this.showColumnPicker;
  }

  onDocumentClick(event: Event): void {
    if (this.showColumnPicker) {
      this.showColumnPicker = false;
    }
  }

  loadStats(): void {
    this.http.get<any>(`${this.apiUrl}/signals/stats`).subscribe(s => this.stats = s);
  }

  loadSignals(): void {
    let url = `${this.apiUrl}/signals?page=${this.page}&pageSize=${this.pageSize}`;
    url += `&sortBy=${this.sortBy}&sortDir=${this.sortDir}`;
    if (this.filterPlatform) url += `&platform=${this.filterPlatform}`;
    if (this.filterMatched) url += `&matched=${this.filterMatched}`;
    if (this.filterAnalyzed) url += `&analyzed=${this.filterAnalyzed}`;

    this.http.get<any>(url).subscribe(res => {
      this.signals = res.data;
      this.total = res.total;
    });
  }

  loadAiSettings(): void {
    this.http.get<any>(`${this.apiUrl}/signals/ai-settings`).subscribe(s => {
      this.aiSettings = s;
      this.settingsForm.aiProvider = s.aiProvider;
      this.settingsForm.aiModel = s.aiModel || '';
    });
  }

  reprocess(): void {
    this.reprocessing = true;
    this.http.post<any>(`${this.apiUrl}/signals/reprocess`, {}).subscribe({
      next: (res) => {
        this.infoMessage = `${res.message} — ${res.keywordMatches} keyword matches, ${res.prospects} prospects`;
        this.reprocessing = false;
        this.loadStats();
        this.loadSignals();
        setTimeout(() => this.infoMessage = '', 8000);
      },
      error: () => {
        this.reprocessing = false;
        alert('Reprocessing failed');
      }
    });
  }

  analyzeSingle(signal: any): void {
    signal.analyzing = true;
    this.http.post<any>(`${this.apiUrl}/signals/${signal.id}/analyze`, {}).subscribe({
      next: (res) => {
        signal.intentScore = res.intentScore;
        signal.intentCategory = res.intentCategory;
        signal.sentiment = res.sentiment;
        signal.aiSummary = res.aiSummary;
        signal.aiProvider = res.aiProvider;
        signal.analyzedAt = res.analyzedAt;
        signal.analyzing = false;
        this.loadStats();
      },
      error: (err) => {
        signal.analyzing = false;
        alert(err.error?.error || 'Analysis failed. Check AI settings.');
      }
    });
  }

  analyzeAll(): void {
    this.analyzingAll = true;
    this.http.post<any>(`${this.apiUrl}/signals/analyze-all`, {}).subscribe({
      next: (res) => {
        this.infoMessage = `${res.message} (provider: ${res.provider})`;
        this.analyzingAll = false;
        this.loadStats();
        this.loadSignals();
        setTimeout(() => this.infoMessage = '', 8000);
      },
      error: (err) => {
        this.analyzingAll = false;
        alert(err.error?.error || 'Bulk analysis failed. Check AI settings.');
      }
    });
  }

  onProviderChange(): void {
    this.settingsForm.apiKey = '';
    this.settingsForm.aiModel = '';
    this.settingsMessage = '';
  }

  saveSettings(): void {
    this.savingSettings = true;
    this.settingsMessage = '';
    this.settingsError = false;

    const body: any = {
      aiProvider: this.settingsForm.aiProvider,
      aiModel: this.settingsForm.aiModel || null
    };
    if (this.settingsForm.apiKey) {
      body.apiKey = this.settingsForm.apiKey;
    }

    this.http.put<any>(`${this.apiUrl}/signals/ai-settings`, body).subscribe({
      next: (res) => {
        this.aiSettings = res;
        this.settingsMessage = 'Settings saved successfully';
        this.settingsError = false;
        this.savingSettings = false;
        this.settingsForm.apiKey = '';
      },
      error: () => {
        this.settingsMessage = 'Failed to save settings';
        this.settingsError = true;
        this.savingSettings = false;
      }
    });
  }

  /**
   * Collapse the header lines (initial, name, location) into one meta line.
   * Nextdoor: "L\nLinda Whitehouse\nPleasanton, CA · 1 Mar\n..." → "L · Linda Whitehouse · Pleasanton, CA · 1 Mar"
   * Reddit/other: just show the first line as meta.
   */
  getContentMeta(content: string): string {
    if (!content) return '';
    const lines = content.split('\n').filter(l => l.trim());
    if (lines.length < 2) return '';

    // Detect Nextdoor header: single-char initial, then name, then location line with "·"
    const headerLines: string[] = [];
    let bodyStart = 0;

    for (let i = 0; i < Math.min(lines.length, 5); i++) {
      const line = lines[i].trim();
      // Single char initial
      if (i === 0 && line.length <= 2) { headerLines.push(line); bodyStart = i + 1; continue; }
      // Name line (short, has space or period, no middle dot)
      if (headerLines.length > 0 && headerLines.length <= 1 && line.length <= 40 && !line.includes('·') && (line.includes(' ') || line.includes('.'))) {
        headerLines.push(line); bodyStart = i + 1; continue;
      }
      // Location line (contains ·)
      if (line.includes('·') && i <= 3) { headerLines.push(line); bodyStart = i + 1; break; }
      break;
    }

    if (headerLines.length === 0) {
      // Non-Nextdoor: use first line as meta
      return lines[0].trim();
    }

    return headerLines.join(' · ');
  }

  getContentBody(content: string): string {
    if (!content) return '';
    const lines = content.split('\n').filter(l => l.trim());
    if (lines.length < 2) return content.trim();

    // Skip header lines (same logic as getContentMeta)
    let bodyStart = 0;
    for (let i = 0; i < Math.min(lines.length, 5); i++) {
      const line = lines[i].trim();
      if (i === 0 && line.length <= 2) { bodyStart = i + 1; continue; }
      if (bodyStart > 0 && bodyStart === i && line.length <= 40 && !line.includes('·') && (line.includes(' ') || line.includes('.'))) {
        bodyStart = i + 1; continue;
      }
      if (line.includes('·') && i <= 3) { bodyStart = i + 1; break; }
      break;
    }

    const bodyLines = lines.slice(bodyStart).map(l => l.trim()).filter(l => l);
    return bodyLines.join(' ').trim() || content.trim();
  }

  exportCsv(): void {
    const headers = ['ID', 'Author', 'Platform', 'Post Date', 'Detected', 'Intent Score', 'Category', 'Sentiment', 'AI Summary', 'Matches', 'Post URL', 'Post Content'];
    const rows = this.signals.map(s => [
      s.id,
      s.authorName || '',
      s.platform || '',
      s.postDate || '',
      s.detectedAt || '',
      s.intentScore ?? '',
      s.intentCategory || '',
      s.sentiment || '',
      s.aiSummary || '',
      s.matchCount || 0,
      s.postUrl || '',
      (s.fullContent || '').replace(/\n/g, ' ')
    ]);
    this.downloadCsv(headers, rows, 'signals.csv');
  }

  private downloadCsv(headers: string[], rows: any[][], filename: string): void {
    const escape = (val: any) => {
      const str = String(val ?? '');
      return str.includes(',') || str.includes('"') || str.includes('\n') ? '"' + str.replace(/"/g, '""') + '"' : str;
    };
    const csv = [headers.map(escape).join(','), ...rows.map(r => r.map(escape).join(','))].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
  }

  openContentModal(signal: any): void {
    this.contentModalSignal = signal;
  }

  prevPage(): void {
    if (this.page > 1) { this.page--; this.loadSignals(); }
  }

  nextPage(): void {
    if (this.page < this.totalPages) { this.page++; this.loadSignals(); }
  }
}
