import { Component, OnInit, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { StrategyService } from '../../core/services/strategy.service';
import { GeoService } from '../../core/services/geo.service';
import { StrategyResponse, CreateStrategyRequest, DailyListResponse } from '../../core/models/strategy.model';

interface ColumnDef {
  key: string;
  label: string;
  visible: boolean;
}

@Component({
  selector: 'app-daily-list',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="daily-page">
      <div class="page-header">
        <h2>Daily Prospect List</h2>
        <div class="tab-bar">
          <button class="tab-btn" [class.active]="activeTab === 'list'" (click)="activeTab = 'list'">Daily List</button>
          <button class="tab-btn" [class.active]="activeTab === 'strategies'" (click)="activeTab = 'strategies'">Strategies</button>
        </div>
      </div>

      <!-- ==================== DAILY LIST TAB ==================== -->
      <div *ngIf="activeTab === 'list'">
        <div class="top-bar">
          <select [(ngModel)]="selectedStrategyId" (change)="onStrategyChange()" name="strategy">
            <option [ngValue]="undefined">-- Select Strategy --</option>
            <option *ngFor="let s of strategies" [ngValue]="s.id">
              {{ s.name }} {{ s.isActive ? '' : '(Inactive)' }}
            </option>
          </select>
          <button class="btn-primary" [disabled]="!selectedStrategyId || generating" (click)="generateList()">
            {{ generating ? 'Generating...' : 'Generate Today\\'s List' }}
          </button>
        </div>

        <!-- Strategy Tune Panel -->
        <div *ngIf="selectedStrategy" class="tune-panel">
          <div class="tune-header" (click)="showTuning = !showTuning">
            <div class="tune-summary">
              <strong>{{ selectedStrategy.name }}</strong>
              <span class="tune-tag">Score &ge; {{ selectedStrategy.minScore }}</span>
              <span *ngIf="selectedStrategy.minUrgency" class="tune-tag">{{ selectedStrategy.minUrgency }}+</span>
              <span *ngIf="selectedStrategy.targetCategories?.length" class="tune-tag">{{ selectedStrategy.targetCategories!.join(', ') }}</span>
              <span class="tune-tag">Max {{ selectedStrategy.maxDailyProspects }}/day</span>
              <span *ngIf="selectedStrategy.targetStates?.length" class="tune-tag">States: {{ selectedStrategy.targetStates!.join(', ') }}</span>
              <span class="tune-tag">{{ selectedStrategy.targetZipCodes?.length ? selectedStrategy.targetZipCodes!.length + ' zips' : 'All Zip Codes' }}</span>
            </div>
            <button class="btn-sm btn-tune">{{ showTuning ? 'Close' : 'Tune Strategy' }}</button>
          </div>

          <div *ngIf="showTuning" class="tune-body">
            <ng-container *ngTemplateOutlet="strategyFormTpl; context: { $implicit: tuneForm, cats: tuneCategoriesText, zips: tuneZipsText, states: tuneSelectedStates, showStates: showTuneStates, counties: tuneCounties, selectedCounty: tuneSelectedCounty, loadingCounties: tuneLoadingCounties, loadingZips: loadingTuneZips, countyZipCount: tuneCountyZipCount, mode: 'tune' }"></ng-container>
            <div class="tune-actions">
              <label class="toggle-label">
                <input type="checkbox" [(ngModel)]="tuneIsActive" name="tuneActive"> Active
              </label>
              <div class="tune-btns">
                <button class="btn-sm" (click)="resetTuneForm()">Reset</button>
                <button class="btn-primary btn-save" (click)="saveTune()" [disabled]="savingTune">
                  {{ savingTune ? 'Saving...' : 'Save & Apply' }}
                </button>
              </div>
            </div>
            <div *ngIf="tuneMessage" class="tune-message" [class.error]="tuneError">{{ tuneMessage }}</div>
          </div>
        </div>

        <div *ngIf="message" class="message" [class.error]="isError">{{ message }}</div>

        <!-- Daily List Table -->
        <div *ngIf="dailyList" class="list-card">
          <div class="list-header">
            <div>
              <h3>{{ dailyList.strategyName }}</h3>
              <div style="display:flex;align-items:center;gap:.5rem">
                <span class="sub-text">Generated: {{ dailyList.generatedDate | date:'mediumDate' }} — {{ dailyList.prospectCount }} prospects</span>
                <button class="btn-sm" [class.active]="listViewMode === 'table'" (click)="listViewMode = 'table'">Table</button>
                <button class="btn-sm" [class.active]="listViewMode === 'card'" (click)="listViewMode = 'card'">Cards</button>
                <button class="btn-sm btn-export" (click)="exportCsv()">Export CSV</button>
                <div class="column-picker-wrapper">
                  <button class="btn-icon" title="Show/Hide Columns" (click)="toggleColumnPicker($event)">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z"/></svg>
                  </button>
                  <div *ngIf="showColumnPicker" class="column-picker" (click)="$event.stopPropagation()">
                    <div class="picker-header">Show / Hide Columns</div>
                    <label *ngFor="let col of columns" class="picker-item">
                      <input type="checkbox" [(ngModel)]="col.visible" [name]="'col_' + col.key">
                      {{ col.label }}
                    </label>
                  </div>
                </div>
              </div>
            </div>
            <div class="list-stats">
              <span class="stat-pill new">{{ countByStatus('New') }} New</span>
              <span class="stat-pill viewed">{{ countByStatus('Viewed') }} Viewed</span>
              <span class="stat-pill contacted">{{ countByStatus('Contacted') }} Contacted</span>
              <span class="stat-pill converted">{{ countByStatus('Converted') }} Converted</span>
              <span class="stat-pill dismissed">{{ countByStatus('Dismissed') }} Dismissed</span>
            </div>
          </div>

          <div class="filter-bar">
            <select [(ngModel)]="filterStatus" name="filterStatus">
              <option value="">All Statuses</option>
              <option value="New">New</option><option value="Viewed">Viewed</option>
              <option value="Contacted">Contacted</option><option value="Converted">Converted</option>
              <option value="Dismissed">Dismissed</option>
            </select>
            <select [(ngModel)]="filterUrgency" name="filterUrgency">
              <option value="">All Urgency</option>
              <option value="Hot">Hot</option><option value="Warm">Warm</option><option value="Cool">Cool</option>
            </select>
            <select [(ngModel)]="filterCategory" name="filterCategory">
              <option value="">All Categories</option>
              <option value="Auto">Auto</option><option value="Home">Home</option>
              <option value="Life">Life</option><option value="Health">Health</option>
              <option value="Commercial">Commercial</option>
            </select>
            <select [(ngModel)]="filterPlatform" name="filterPlatform">
              <option value="">All Platforms</option>
              <option value="Reddit">Reddit</option><option value="Nextdoor">Nextdoor</option>
              <option value="LinkedIn">LinkedIn</option><option value="Facebook">Facebook</option>
            </select>
          </div>

          <table *ngIf="dailyList.items.length > 0 && listViewMode === 'table'">
            <thead>
              <tr>
                <th *ngIf="isVisible('name')" class="sortable-th" (click)="toggleSort('name')">Name <span class="sort-icon">{{ getSortIcon('name') }}</span></th>
                <th *ngIf="isVisible('score')" class="sortable-th" (click)="toggleSort('score')">Score <span class="sort-icon">{{ getSortIcon('score') }}</span></th>
                <th *ngIf="isVisible('intentScore')" class="sortable-th" (click)="toggleSort('intentScore')">Intent <span class="sort-icon">{{ getSortIcon('intentScore') }}</span></th>
                <th *ngIf="isVisible('urgency')" class="sortable-th" (click)="toggleSort('urgency')">Urgency <span class="sort-icon">{{ getSortIcon('urgency') }}</span></th>
                <th *ngIf="isVisible('category')" class="sortable-th" (click)="toggleSort('category')">Category <span class="sort-icon">{{ getSortIcon('category') }}</span></th>
                <th *ngIf="isVisible('platform')" class="sortable-th" (click)="toggleSort('platform')">Platform <span class="sort-icon">{{ getSortIcon('platform') }}</span></th>
                <th *ngIf="isVisible('signal')">Signal</th>
                <th *ngIf="isVisible('status')" class="sortable-th" (click)="toggleSort('status')">Status <span class="sort-icon">{{ getSortIcon('status') }}</span></th>
                <th *ngIf="isVisible('city')" class="sortable-th" (click)="toggleSort('city')">City <span class="sort-icon">{{ getSortIcon('city') }}</span></th>
                <th *ngIf="isVisible('state')" class="sortable-th" (click)="toggleSort('state')">State <span class="sort-icon">{{ getSortIcon('state') }}</span></th>
                <th *ngIf="isVisible('zip')">Zip</th>
                <th *ngIf="isVisible('email')">Email</th>
                <th *ngIf="isVisible('phone')">Phone</th>
                <th *ngIf="isVisible('company')">Company</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr *ngFor="let item of filteredItems" [class]="'row-' + item.status.toLowerCase()">
                <td *ngIf="isVisible('name')"><strong>{{ item.prospect.name }}</strong></td>
                <td *ngIf="isVisible('score')"><span class="score">{{ item.prospect.compositeScore }}</span></td>
                <td *ngIf="isVisible('intentScore')"><span *ngIf="item.prospect.intentScore !== null" class="intent-score" [class]="intentClass(item.prospect.intentScore!)">{{ item.prospect.intentScore }}</span><span *ngIf="item.prospect.intentScore === null" class="no-intent">—</span></td>
                <td *ngIf="isVisible('urgency')"><span class="urgency-badge" [class]="'urgency-' + item.prospect.urgency.toLowerCase()">{{ item.prospect.urgency }}</span></td>
                <td *ngIf="isVisible('category')">{{ item.prospect.category || '—' }}</td>
                <td *ngIf="isVisible('platform')"><span class="platform-tag" [class]="'plat-' + (item.prospect.platform || '').toLowerCase()">{{ item.prospect.platform || '—' }}</span></td>
                <td *ngIf="isVisible('signal')" class="signal-cell" [title]="item.prospect.signalSnippet || ''">{{ item.prospect.signalSnippet ? (item.prospect.signalSnippet.length > 80 ? item.prospect.signalSnippet.substring(0, 80) + '...' : item.prospect.signalSnippet) : '—' }}</td>
                <td *ngIf="isVisible('status')"><span class="status-badge" [class]="'status-' + item.status.toLowerCase()">{{ item.status }}</span></td>
                <td *ngIf="isVisible('city')">{{ item.prospect.city || '—' }}</td>
                <td *ngIf="isVisible('state')">{{ item.prospect.state || '—' }}</td>
                <td *ngIf="isVisible('zip')">{{ item.prospect.zip || '—' }}</td>
                <td *ngIf="isVisible('email')">{{ item.prospect.email || '—' }}</td>
                <td *ngIf="isVisible('phone')">{{ item.prospect.phone || '—' }}</td>
                <td *ngIf="isVisible('company')">{{ item.prospect.company || '—' }}</td>
                <td class="actions-cell">
                  <a *ngIf="item.prospect.postUrl" [href]="item.prospect.postUrl" target="_blank" class="btn-sm btn-link">Link</a>
                  <button *ngIf="item.status === 'New'" class="btn-sm" (click)="updateStatus(item.id, 'Viewed')">Mark Viewed</button>
                  <button *ngIf="item.status === 'Viewed'" class="btn-sm btn-accent" (click)="updateStatus(item.id, 'Contacted')">Contacted</button>
                  <button *ngIf="item.status === 'Contacted'" class="btn-sm btn-success" (click)="updateStatus(item.id, 'Converted')">Converted</button>
                  <button *ngIf="item.status !== 'Dismissed' && item.status !== 'Converted'" class="btn-sm btn-danger" (click)="updateStatus(item.id, 'Dismissed')">Dismiss</button>
                </td>
              </tr>
            </tbody>
          </table>

          <!-- Card View -->
          <div *ngIf="filteredItems.length > 0 && listViewMode === 'card'" class="dl-cards-grid">
            <div *ngFor="let item of filteredItems" class="dl-card" [class]="'dl-card-' + item.status.toLowerCase()">
              <div class="dl-card-top">
                <div>
                  <strong>{{ item.prospect.name }}</strong>
                  <span class="platform-tag" [class]="'plat-' + (item.prospect.platform || '').toLowerCase()">{{ item.prospect.platform }}</span>
                </div>
                <div style="display:flex;gap:.3rem;align-items:center">
                  <span class="score">{{ item.prospect.compositeScore }}</span>
                  <span *ngIf="item.prospect.intentScore !== null" class="intent-score" [class]="intentClass(item.prospect.intentScore!)" title="Intent Score">{{ item.prospect.intentScore }}</span>
                </div>
              </div>
              <div class="dl-card-badges">
                <span class="urgency-badge" [class]="'urgency-' + item.prospect.urgency.toLowerCase()">{{ item.prospect.urgency }}</span>
                <span *ngIf="item.prospect.category" class="cat-badge">{{ item.prospect.category }}</span>
                <span class="status-badge" [class]="'status-' + item.status.toLowerCase()">{{ item.status }}</span>
              </div>
              <div *ngIf="item.prospect.city || item.prospect.state" class="dl-card-location">
                {{ item.prospect.city }}{{ item.prospect.city && item.prospect.state ? ', ' : '' }}{{ item.prospect.state }}
              </div>
              <p class="dl-card-snippet" *ngIf="item.prospect.signalSnippet">{{ item.prospect.signalSnippet | slice:0:120 }}...</p>
              <div class="dl-card-footer">
                <div class="dl-card-contact">
                  <small *ngIf="item.prospect.phone">{{ item.prospect.phone }}</small>
                  <small *ngIf="item.prospect.email">{{ item.prospect.email }}</small>
                </div>
                <div class="dl-card-actions">
                  <a *ngIf="item.prospect.postUrl" [href]="item.prospect.postUrl" target="_blank" class="btn-sm btn-link">Link</a>
                  <button *ngIf="item.status === 'New'" class="btn-sm" (click)="updateStatus(item.id, 'Viewed')">Viewed</button>
                  <button *ngIf="item.status === 'Viewed'" class="btn-sm btn-accent" (click)="updateStatus(item.id, 'Contacted')">Contacted</button>
                  <button *ngIf="item.status === 'Contacted'" class="btn-sm btn-success" (click)="updateStatus(item.id, 'Converted')">Converted</button>
                  <button *ngIf="item.status !== 'Dismissed' && item.status !== 'Converted'" class="btn-sm btn-danger" (click)="updateStatus(item.id, 'Dismissed')">Dismiss</button>
                </div>
              </div>
            </div>
          </div>

          <p *ngIf="dailyList.items.length === 0" class="empty-text">No prospects matched this strategy's filters.</p>
        </div>

        <div *ngIf="!dailyList && !message" class="empty-state">
          <p *ngIf="!selectedStrategyId">Select a strategy above, then generate your daily call list.</p>
          <p *ngIf="selectedStrategyId">No list generated for today yet. Tune the strategy if needed, then click "Generate Today's List".</p>
        </div>
      </div>

      <!-- ==================== STRATEGIES TAB ==================== -->
      <div *ngIf="activeTab === 'strategies'">
        <div class="top-bar">
          <div class="strat-view-toggle">
            <button class="btn-sm" [class.active]="stratViewMode === 'card'" (click)="stratViewMode = 'card'">Cards</button>
            <button class="btn-sm" [class.active]="stratViewMode === 'list'" (click)="stratViewMode = 'list'">List</button>
          </div>
          <button class="btn-primary" (click)="showNewForm = !showNewForm">{{ showNewForm ? 'Cancel' : '+ New Strategy' }}</button>
        </div>

        <!-- New Strategy Form -->
        <div *ngIf="showNewForm" class="form-card">
          <h4 style="margin:0 0 .75rem">New Strategy</h4>
          <ng-container *ngTemplateOutlet="strategyFormTpl; context: { $implicit: newForm, cats: newCategoriesText, zips: newZipsText, states: newSelectedStates, showStates: showNewStates, counties: newCounties, selectedCounty: newSelectedCounty, loadingCounties: newLoadingCounties, loadingZips: loadingNewZips, countyZipCount: newCountyZipCount, mode: 'new' }"></ng-container>
          <div class="tune-actions">
            <span></span>
            <div class="tune-btns">
              <button class="btn-sm" (click)="showNewForm = false">Cancel</button>
              <button class="btn-primary btn-save" (click)="createStrategy()" [disabled]="creatingStrategy">
                {{ creatingStrategy ? 'Creating...' : 'Create Strategy' }}
              </button>
            </div>
          </div>
          <div *ngIf="newFormError" class="tune-message error">{{ newFormError }}</div>
        </div>

        <!-- Card View -->
        <div *ngIf="stratViewMode === 'card'" class="strategies-grid">
          <div *ngFor="let s of strategies" class="strategy-card" [class.inactive]="!s.isActive">
            <div class="card-top">
              <h4>{{ s.name }}</h4>
              <span class="strat-status" [class.active]="s.isActive">{{ s.isActive ? 'Active' : 'Inactive' }}</span>
            </div>
            <div class="card-details">
              <div><strong>Min Score:</strong> {{ s.minScore }}</div>
              <div><strong>Max Daily:</strong> {{ s.maxDailyProspects }}</div>
              <div *ngIf="s.targetCategories?.length"><strong>Categories:</strong> {{ s.targetCategories!.join(', ') }}</div>
              <div *ngIf="s.minUrgency"><strong>Min Urgency:</strong> {{ s.minUrgency }}</div>
              <div *ngIf="s.targetStates?.length"><strong>States:</strong> {{ s.targetStates!.join(', ') }}</div>
              <div *ngIf="s.targetZipCodes?.length"><strong>Zip Codes:</strong> {{ s.targetZipCodes!.length }} zips</div>
            </div>
            <div class="card-actions">
              <button class="btn-sm" (click)="selectAndTune(s)">Edit</button>
              <button class="btn-sm btn-accent" (click)="selectAndGenerate(s)">Generate List</button>
              <button class="btn-sm btn-danger" (click)="deleteStrategy(s)">Delete</button>
            </div>
          </div>
        </div>

        <!-- List View -->
        <div *ngIf="stratViewMode === 'list'" class="table-card">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Min Score</th>
                <th>Max Daily</th>
                <th>Categories</th>
                <th>States</th>
                <th>Urgency</th>
                <th>Zip Codes</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr *ngFor="let s of strategies" [class.inactive-row]="!s.isActive">
                <td><strong>{{ s.name }}</strong></td>
                <td><span class="strat-status" [class.active]="s.isActive">{{ s.isActive ? 'Active' : 'Inactive' }}</span></td>
                <td>{{ s.minScore }}</td>
                <td>{{ s.maxDailyProspects }}</td>
                <td>{{ s.targetCategories?.join(', ') || '—' }}</td>
                <td>{{ s.targetStates?.join(', ') || 'All' }}</td>
                <td>{{ s.minUrgency || 'Any' }}</td>
                <td>{{ s.targetZipCodes?.length ? s.targetZipCodes!.length + ' zips' : 'All' }}</td>
                <td class="actions-cell">
                  <button class="btn-sm" (click)="selectAndTune(s)">Edit</button>
                  <button class="btn-sm btn-accent" (click)="selectAndGenerate(s)">Generate</button>
                  <button class="btn-sm btn-danger" (click)="deleteStrategy(s)">Delete</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p *ngIf="strategies.length === 0 && !showNewForm" class="empty-text">No strategies configured yet. Click "+ New Strategy" to create one.</p>
      </div>
    </div>

    <!-- Shared strategy form template -->
    <ng-template #strategyFormTpl let-form let-cats="cats" let-zips="zips" let-states="states" let-showStates="showStates" let-counties="counties" let-selectedCounty="selectedCounty" let-loadingCounties="loadingCounties" let-loadingZips="loadingZips" let-countyZipCount="countyZipCount" let-mode="mode">
      <div class="tune-grid">
        <div class="form-group">
          <label>Strategy Name</label>
          <input [(ngModel)]="form.name" [name]="mode + 'Name'">
        </div>
        <div class="form-group">
          <label>Min Score (0-100)</label>
          <input type="number" [(ngModel)]="form.minScore" [name]="mode + 'Score'" min="0" max="100">
        </div>
        <div class="form-group">
          <label>Categories (comma-separated)</label>
          <input [(ngModel)]="mode === 'tune' ? tuneCategoriesText : newCategoriesText" [name]="mode + 'Cats'" placeholder="Home, Auto, Life">
        </div>
        <div class="form-group">
          <label>Min Urgency</label>
          <select [(ngModel)]="form.minUrgency" [name]="mode + 'Urg'">
            <option [ngValue]="undefined">Any</option>
            <option value="Cool">Cool</option>
            <option value="Warm">Warm</option>
            <option value="Hot">Hot</option>
          </select>
        </div>
        <div class="form-group">
          <label>States</label>
          <div class="state-picker">
            <button class="btn-sm state-toggle" type="button" (click)="mode === 'tune' ? showTuneStates = !showTuneStates : showNewStates = !showNewStates; $event.stopPropagation()">
              {{ states.length ? states.length + ' states selected' : 'All States (default)' }}
            </button>
            <div *ngIf="mode === 'tune' ? showTuneStates : showNewStates" class="state-dropdown">
              <div class="state-actions">
                <button class="btn-sm" (click)="mode === 'tune' ? tuneSelectAllStates() : newSelectAllStates()">All</button>
                <button class="btn-sm" (click)="mode === 'tune' ? tuneClearStates() : newClearStates()">None</button>
              </div>
              <div class="state-list">
                <label *ngFor="let st of usStates" class="state-item">
                  <input type="checkbox" [checked]="states.includes(st.code)" (change)="mode === 'tune' ? tuneToggleState(st.code) : newToggleState(st.code)">
                  {{ st.code }} - {{ st.name }}
                </label>
              </div>
            </div>
          </div>
        </div>
        <div class="form-group" *ngIf="states.length === 1">
          <label>County (auto-add zip codes)</label>
          <div class="county-picker">
            <select [(ngModel)]="mode === 'tune' ? tuneSelectedCounty : newSelectedCounty" (ngModelChange)="mode === 'tune' ? onTuneCountyChange() : onNewCountyChange()" [name]="mode + 'County'">
              <option value="">-- Select County --</option>
              <option *ngFor="let c of counties" [value]="c">{{ c }}</option>
            </select>
            <button *ngIf="selectedCounty" class="btn-sm btn-add-zips" (click)="mode === 'tune' ? addTuneCountyZips() : addNewCountyZips()" [disabled]="loadingZips">
              {{ loadingZips ? 'Loading...' : 'Add Zips' }}
            </button>
          </div>
          <small *ngIf="counties.length === 0 && loadingCounties" class="hint">Loading counties...</small>
          <small *ngIf="countyZipCount" class="hint success">Added {{ countyZipCount }} zip codes</small>
        </div>
        <div class="form-group" *ngIf="states.length > 1">
          <label>County</label>
          <small class="hint">Select a single state to pick a county</small>
        </div>
        <div class="form-group">
          <label>Zip Codes (comma-separated)</label>
          <input [(ngModel)]="mode === 'tune' ? tuneZipsText : newZipsText" [name]="mode + 'Zips'" [placeholder]="states.length ? 'Leave empty for all zips in selected states' : 'All Zip Codes (default)'">
          <small *ngIf="(mode === 'tune' ? tuneZipsText : newZipsText)" class="hint">{{ countZips(mode === 'tune' ? tuneZipsText : newZipsText) }} zip codes</small>
        </div>
        <div class="form-group">
          <label>Max Daily Prospects</label>
          <input type="number" [(ngModel)]="form.maxDailyProspects" [name]="mode + 'Max'" min="1" max="500">
        </div>
      </div>
    </ng-template>
  `,
  styles: [`
    .daily-page{padding:1.5rem}
    .page-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem}
    .page-header h2{margin:0}
    .tab-bar{display:flex;gap:0}
    .tab-btn{padding:.5rem 1.25rem;border:1px solid #d1d5db;background:#fff;cursor:pointer;font-weight:500;font-size:.875rem;color:#6b7280}
    .tab-btn:first-child{border-radius:6px 0 0 6px}
    .tab-btn:last-child{border-radius:0 6px 6px 0;border-left:none}
    .tab-btn.active{background:#2563eb;color:#fff;border-color:#2563eb}
    .top-bar{display:flex;gap:.5rem;align-items:center;margin-bottom:1rem}
    .top-bar select{padding:.5rem;border:1px solid #d1d5db;border-radius:4px;min-width:280px}
    .strat-view-toggle{display:flex;gap:0}
    .strat-view-toggle .btn-sm{border-radius:0}
    .strat-view-toggle .btn-sm:first-child{border-radius:4px 0 0 4px}
    .strat-view-toggle .btn-sm:last-child{border-radius:0 4px 4px 0;border-left:none}
    .strat-view-toggle .btn-sm.active{background:#2563eb;color:#fff;border-color:#2563eb}

    .btn-primary{padding:.5rem 1rem;background:#2563eb;color:#fff;border:none;border-radius:4px;cursor:pointer}
    .btn-primary:hover{background:#1d4ed8}
    .btn-primary:disabled{opacity:.5;cursor:not-allowed}

    /* Tune Panel */
    .tune-panel{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-bottom:1rem;overflow:hidden}
    .tune-header{display:flex;justify-content:space-between;align-items:center;padding:.75rem 1rem;cursor:pointer;border-bottom:1px solid #f3f4f6}
    .tune-header:hover{background:#fafbfc}
    .tune-summary{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;font-size:.85rem}
    .tune-summary strong{color:#1a1f36;font-size:.9rem}
    .tune-tag{padding:.15rem .5rem;border-radius:10px;font-size:.7rem;font-weight:600;background:#eff6ff;color:#1d4ed8}
    .btn-tune{color:#7c3aed;border-color:#7c3aed;font-weight:600}
    .tune-body{padding:1rem 1.25rem;border-top:1px solid #e5e7eb;background:#fafbfc}
    .tune-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:.75rem}
    .tune-actions{display:flex;justify-content:space-between;align-items:center;margin-top:.75rem}
    .tune-btns{display:flex;gap:.5rem}
    .btn-save{padding:.4rem .75rem;font-size:.85rem}
    .toggle-label{display:flex;align-items:center;gap:.4rem;font-size:.85rem;font-weight:500;color:#374151;cursor:pointer}
    .toggle-label input{accent-color:#2563eb}
    .tune-message{padding:.5rem;border-radius:4px;font-size:.8rem;background:#d1fae5;color:#065f46;margin-top:.5rem}
    .tune-message.error{background:#fee2e2;color:#991b1b}

    /* Form */
    .form-card{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1);padding:1.25rem;margin-bottom:1rem}
    .form-group label{display:block;font-weight:500;margin-bottom:.2rem;color:#374151;font-size:.8rem}
    .form-group input,.form-group select{width:100%;padding:.45rem;border:1px solid #d1d5db;border-radius:4px;box-sizing:border-box;font-size:.85rem}

    .message{padding:.75rem 1rem;border-radius:6px;margin-bottom:1rem;background:#d1fae5;color:#065f46;font-size:.875rem}
    .message.error{background:#fee2e2;color:#991b1b}
    .list-card{background:#fff;border-radius:8px;padding:1.5rem;box-shadow:0 1px 3px rgba(0,0,0,.1)}
    .list-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1rem;flex-wrap:wrap;gap:.5rem}
    .list-header h3{margin:0}
    .sub-text{font-size:.8rem;color:#6b7280}
    .list-stats{display:flex;gap:.4rem;flex-wrap:wrap}
    .stat-pill{padding:.15rem .5rem;border-radius:10px;font-size:.7rem;font-weight:600}
    .stat-pill.new{background:#dbeafe;color:#1d4ed8}
    .stat-pill.viewed{background:#fef3c7;color:#92400e}
    .stat-pill.contacted{background:#d1fae5;color:#065f46}
    .stat-pill.converted{background:#ecfdf5;color:#047857}
    .stat-pill.dismissed{background:#e5e7eb;color:#6b7280}

    table{width:100%;border-collapse:collapse}
    th,td{padding:.5rem;text-align:left;border-bottom:1px solid #e5e7eb;font-size:.85rem}
    th{font-weight:600;color:#374151}
    .row-dismissed,.inactive-row{opacity:.5}
    .row-converted{background:#f0fdf4}
    .score{font-weight:700;color:#2563eb}
    .intent-score{font-weight:700;padding:.2rem .5rem;border-radius:4px;font-size:.8rem}
    .intent-high{background:#ede9fe;color:#5b21b6}
    .intent-med{background:#fef3c7;color:#92400e}
    .intent-low{background:#f3f4f6;color:#6b7280}
    .no-intent{color:#d1d5db}
    .urgency-badge,.status-badge{padding:.15rem .4rem;border-radius:10px;font-size:.7rem;font-weight:600}
    .urgency-hot,.urgency-critical{background:#fee2e2;color:#991b1b}
    .urgency-warm,.urgency-medium{background:#fef3c7;color:#92400e}
    .urgency-cool,.urgency-low{background:#dbeafe;color:#1d4ed8}
    .status-new{background:#dbeafe;color:#1d4ed8}
    .status-viewed{background:#fef3c7;color:#92400e}
    .status-contacted,.status-converted{background:#d1fae5;color:#065f46}
    .status-dismissed{background:#e5e7eb;color:#6b7280}
    .platform-tag{padding:.1rem .4rem;border-radius:4px;font-size:.7rem;font-weight:600}
    .plat-reddit{background:#fff1f0;color:#ff4500}
    .plat-nextdoor{background:#f0fce9;color:#4d7c0f}
    .plat-linkedin{background:#eff6ff;color:#0077b5}
    .plat-facebook{background:#eff6ff;color:#1877f2}
    .signal-cell{max-width:200px;font-size:.8rem;color:#6b7280;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .actions-cell{display:flex;gap:.25rem;flex-wrap:nowrap}
    .empty-state,.empty-text{color:#6b7280;text-align:center;padding:2rem;background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1)}
    .btn-sm{padding:.3rem .6rem;font-size:.75rem;border:1px solid #d1d5db;border-radius:4px;cursor:pointer;background:#fff}
    .btn-sm:hover{background:#f3f4f6}
    .btn-accent{color:#2563eb;border-color:#2563eb}
    .btn-success{color:#059669;border-color:#059669}
    .btn-danger{color:#dc2626;border-color:#dc2626}
    .btn-link{color:#2563eb;border-color:#2563eb;text-decoration:none}

    /* Strategy Cards */
    .strategies-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:1rem}
    .strategy-card{background:#fff;border-radius:8px;padding:1.25rem;box-shadow:0 1px 3px rgba(0,0,0,.1)}
    .strategy-card.inactive{opacity:.5}
    .card-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:.75rem}
    .card-top h4{margin:0}
    .strat-status{font-size:.75rem;font-weight:600;color:#6b7280}
    .strat-status.active{color:#059669}
    .card-details{font-size:.85rem;display:grid;gap:.25rem;margin-bottom:.75rem}
    .card-actions{display:flex;gap:.5rem}

    /* State Picker */
    .state-picker{position:relative}
    .state-toggle{width:100%;text-align:left;padding:.45rem;font-size:.85rem}
    .state-dropdown{position:absolute;top:100%;left:0;right:0;background:#fff;border:1px solid #d1d5db;border-radius:4px;box-shadow:0 4px 12px rgba(0,0,0,.15);z-index:100;max-height:250px;display:flex;flex-direction:column}
    .state-actions{display:flex;gap:.25rem;padding:.4rem;border-bottom:1px solid #e5e7eb}
    .state-list{overflow-y:auto;padding:.25rem}
    .state-item{display:flex;align-items:center;gap:.4rem;padding:.2rem .4rem;font-size:.8rem;cursor:pointer}
    .state-item:hover{background:#f3f4f6;border-radius:3px}
    .state-item input{accent-color:#2563eb}

    /* County Picker */
    .county-picker{display:flex;gap:.4rem;align-items:center}
    .county-picker select{flex:1;padding:.45rem;border:1px solid #d1d5db;border-radius:4px;font-size:.85rem}
    .btn-add-zips{color:#059669;border-color:#059669;white-space:nowrap}
    .hint{display:block;font-size:.7rem;color:#6b7280;margin-top:.2rem}
    .hint.success{color:#059669}

    /* Column Picker */
    .column-picker-wrapper{position:relative;display:inline-block}
    .column-picker{position:absolute;top:100%;right:0;background:#fff;border:1px solid #d1d5db;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,.15);z-index:100;min-width:180px;padding:.5rem 0}
    .picker-header{padding:.4rem .75rem;font-weight:600;font-size:.8rem;color:#374151;border-bottom:1px solid #e5e7eb}
    .picker-item{display:flex;align-items:center;gap:.5rem;padding:.3rem .75rem;font-size:.8rem;cursor:pointer}
    .picker-item:hover{background:#f3f4f6}
    .picker-item input{accent-color:#2563eb}
    .btn-icon{padding:.4rem;border:1px solid #d1d5db;border-radius:4px;cursor:pointer;background:#fff;display:flex;align-items:center;justify-content:center}
    .btn-icon:hover{background:#f3f4f6}
    .btn-sm.active{background:#2563eb;color:#fff;border-color:#2563eb}
    .dl-cards-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:.75rem;margin-top:.5rem}
    .dl-card{background:#fff;border-radius:8px;padding:.75rem 1rem;box-shadow:0 1px 3px rgba(0,0,0,.1);border-left:3px solid transparent}
    .dl-card-new{border-left-color:#2563eb}.dl-card-viewed{border-left-color:#f59e0b}.dl-card-contacted,.dl-card-converted{border-left-color:#059669}.dl-card-dismissed{border-left-color:#9ca3af}
    .dl-card-top{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.3rem}
    .dl-card-badges{display:flex;gap:.3rem;flex-wrap:wrap;margin-bottom:.3rem}
    .dl-card-location{font-size:.72rem;color:#6b7280;margin-bottom:.3rem}
    .dl-card-snippet{font-size:.78rem;color:#6b7280;margin:0 0 .5rem;line-height:1.3}
    .dl-card-footer{display:flex;justify-content:space-between;align-items:center}
    .dl-card-contact small{font-size:.7rem;color:#6b7280;display:block}
    .dl-card-actions{display:flex;gap:.25rem}
    .sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
    .sortable-th:hover{background:#eef2ff;color:#2563eb}
    .sort-icon{font-size:.7rem;margin-left:2px;color:#9ca3af}
    .filter-bar{display:flex;gap:.5rem;align-items:center;margin-bottom:.75rem;flex-wrap:wrap}
    .filter-bar select{padding:.35rem .5rem;border:1px solid #d1d5db;border-radius:4px;font-size:.8rem}
  `]
})
export class DailyListComponent implements OnInit {
  activeTab: 'list' | 'strategies' = 'list';
  stratViewMode: 'card' | 'list' = 'card';

  strategies: StrategyResponse[] = [];
  selectedStrategyId?: number;
  selectedStrategy: StrategyResponse | null = null;
  dailyList: DailyListResponse | null = null;
  generating = false;
  message = '';
  isError = false;

  listViewMode: 'table' | 'card' = 'table';

  // Column picker
  showColumnPicker = false;
  columns: ColumnDef[] = [
    { key: 'name', label: 'Name', visible: true },
    { key: 'score', label: 'Score', visible: true },
    { key: 'intentScore', label: 'Intent', visible: true },
    { key: 'urgency', label: 'Urgency', visible: true },
    { key: 'category', label: 'Category', visible: true },
    { key: 'platform', label: 'Platform', visible: true },
    { key: 'signal', label: 'Signal', visible: true },
    { key: 'status', label: 'Status', visible: true },
    { key: 'city', label: 'City', visible: false },
    { key: 'state', label: 'State', visible: false },
    { key: 'zip', label: 'Zip', visible: false },
    { key: 'email', label: 'Email', visible: false },
    { key: 'phone', label: 'Phone', visible: false },
    { key: 'company', label: 'Company', visible: false },
  ];

  // Sorting
  sortBy: string = 'score';
  sortDir: 'asc' | 'desc' = 'desc';

  // Filters
  filterStatus: string = '';
  filterUrgency: string = '';
  filterCategory: string = '';
  filterPlatform: string = '';

  // Tune strategy
  showTuning = false;
  tuneForm: CreateStrategyRequest = { name: '', minScore: 50, maxDailyProspects: 10 };
  tuneCategoriesText = '';
  tuneZipsText = '';
  tuneIsActive = true;
  savingTune = false;
  tuneMessage = '';
  tuneError = false;

  // Tune states & counties
  showTuneStates = false;
  tuneSelectedStates: string[] = [];
  tuneCounties: string[] = [];
  tuneSelectedCounty = '';
  tuneLoadingCounties = false;
  loadingTuneZips = false;
  tuneCountyZipCount = 0;

  // New strategy
  showNewForm = false;
  newForm: CreateStrategyRequest = { name: '', minScore: 50, maxDailyProspects: 10 };
  newCategoriesText = '';
  newZipsText = '';
  newSelectedStates: string[] = [];
  showNewStates = false;
  newCounties: string[] = [];
  newSelectedCounty = '';
  newLoadingCounties = false;
  loadingNewZips = false;
  newCountyZipCount = 0;
  creatingStrategy = false;
  newFormError = '';

  usStates = [
    {code:'AL',name:'Alabama'},{code:'AK',name:'Alaska'},{code:'AZ',name:'Arizona'},{code:'AR',name:'Arkansas'},
    {code:'CA',name:'California'},{code:'CO',name:'Colorado'},{code:'CT',name:'Connecticut'},{code:'DE',name:'Delaware'},
    {code:'FL',name:'Florida'},{code:'GA',name:'Georgia'},{code:'HI',name:'Hawaii'},{code:'ID',name:'Idaho'},
    {code:'IL',name:'Illinois'},{code:'IN',name:'Indiana'},{code:'IA',name:'Iowa'},{code:'KS',name:'Kansas'},
    {code:'KY',name:'Kentucky'},{code:'LA',name:'Louisiana'},{code:'ME',name:'Maine'},{code:'MD',name:'Maryland'},
    {code:'MA',name:'Massachusetts'},{code:'MI',name:'Michigan'},{code:'MN',name:'Minnesota'},{code:'MS',name:'Mississippi'},
    {code:'MO',name:'Missouri'},{code:'MT',name:'Montana'},{code:'NE',name:'Nebraska'},{code:'NV',name:'Nevada'},
    {code:'NH',name:'New Hampshire'},{code:'NJ',name:'New Jersey'},{code:'NM',name:'New Mexico'},{code:'NY',name:'New York'},
    {code:'NC',name:'North Carolina'},{code:'ND',name:'North Dakota'},{code:'OH',name:'Ohio'},{code:'OK',name:'Oklahoma'},
    {code:'OR',name:'Oregon'},{code:'PA',name:'Pennsylvania'},{code:'RI',name:'Rhode Island'},{code:'SC',name:'South Carolina'},
    {code:'SD',name:'South Dakota'},{code:'TN',name:'Tennessee'},{code:'TX',name:'Texas'},{code:'UT',name:'Utah'},
    {code:'VT',name:'Vermont'},{code:'VA',name:'Virginia'},{code:'WA',name:'Washington'},{code:'WV',name:'West Virginia'},
    {code:'WI',name:'Wisconsin'},{code:'WY',name:'Wyoming'},{code:'DC',name:'District of Columbia'}
  ];

  constructor(private strategyService: StrategyService, private geoService: GeoService) {}

  ngOnInit(): void {
    this.loadStrategies();
  }

  loadStrategies(): void {
    this.strategyService.getAll().subscribe(s => {
      this.strategies = s;
      if (!this.selectedStrategyId && s.length > 0) {
        const active = s.find(st => st.isActive);
        if (active) {
          this.selectedStrategyId = active.id;
          this.onStrategyChange();
        }
      }
    });
  }

  onStrategyChange(): void {
    this.selectedStrategy = this.strategies.find(s => s.id === this.selectedStrategyId) || null;
    this.message = '';
    this.showTuning = false;
    this.tuneMessage = '';
    if (this.selectedStrategy) {
      this.populateTuneForm(this.selectedStrategy);
    }
    this.loadList();
  }

  populateTuneForm(s: StrategyResponse): void {
    this.tuneForm = {
      name: s.name,
      minScore: s.minScore,
      maxDailyProspects: s.maxDailyProspects,
      minUrgency: s.minUrgency || undefined
    };
    this.tuneCategoriesText = s.targetCategories?.join(', ') || '';
    this.tuneSelectedStates = s.targetStates ? [...s.targetStates] : [];
    this.tuneZipsText = s.targetZipCodes?.join(', ') || '';
    this.tuneIsActive = s.isActive;
  }

  resetTuneForm(): void {
    if (this.selectedStrategy) {
      this.populateTuneForm(this.selectedStrategy);
      this.tuneMessage = '';
    }
  }

  saveTune(): void {
    if (!this.selectedStrategy) return;
    this.savingTune = true;
    this.tuneMessage = '';
    this.tuneError = false;

    const payload: any = {
      ...this.tuneForm,
      isActive: this.tuneIsActive,
      targetCategories: this.tuneCategoriesText ? this.tuneCategoriesText.split(',').map(s => s.trim()).filter(s => s) : null,
      targetStates: this.tuneSelectedStates.length ? this.tuneSelectedStates : null,
      targetZipCodes: this.tuneZipsText ? this.tuneZipsText.split(',').map(s => s.trim()).filter(s => s) : null
    };

    this.strategyService.update(this.selectedStrategy.id, payload).subscribe({
      next: (updated) => {
        this.savingTune = false;
        this.tuneMessage = 'Strategy saved. Generate a new list to apply changes.';
        this.tuneError = false;
        const idx = this.strategies.findIndex(s => s.id === updated.id);
        if (idx >= 0) this.strategies[idx] = updated;
        this.selectedStrategy = updated;
      },
      error: (err) => {
        this.savingTune = false;
        this.tuneMessage = err.error?.error || 'Failed to save strategy';
        this.tuneError = true;
      }
    });
  }

  createStrategy(): void {
    this.creatingStrategy = true;
    this.newFormError = '';

    const payload: CreateStrategyRequest = {
      ...this.newForm,
      targetCategories: this.newCategoriesText ? this.newCategoriesText.split(',').map(s => s.trim()).filter(s => s) : undefined,
      targetStates: this.newSelectedStates.length ? this.newSelectedStates : undefined,
      targetZipCodes: this.newZipsText ? this.newZipsText.split(',').map(s => s.trim()).filter(s => s) : undefined
    };

    this.strategyService.create(payload).subscribe({
      next: (created) => {
        this.creatingStrategy = false;
        this.showNewForm = false;
        this.strategies.push(created);
        this.selectedStrategyId = created.id;
        this.onStrategyChange();
        this.activeTab = 'list';
        this.newForm = { name: '', minScore: 50, maxDailyProspects: 10 };
        this.newCategoriesText = '';
        this.newZipsText = '';
        this.newSelectedStates = [];
        this.message = `Strategy "${created.name}" created. Generate a list now.`;
        this.isError = false;
      },
      error: (err) => {
        this.creatingStrategy = false;
        this.newFormError = err.error?.error || 'Failed to create strategy';
      }
    });
  }

  deleteStrategy(s: StrategyResponse): void {
    if (confirm('Delete strategy "' + s.name + '"?')) {
      this.strategyService.delete(s.id).subscribe(() => {
        this.strategies = this.strategies.filter(st => st.id !== s.id);
        if (this.selectedStrategyId === s.id) {
          this.selectedStrategyId = undefined;
          this.selectedStrategy = null;
          this.dailyList = null;
        }
      });
    }
  }

  selectAndTune(s: StrategyResponse): void {
    this.selectedStrategyId = s.id;
    this.onStrategyChange();
    this.showTuning = true;
    this.activeTab = 'list';
  }

  selectAndGenerate(s: StrategyResponse): void {
    this.selectedStrategyId = s.id;
    this.onStrategyChange();
    this.activeTab = 'list';
    this.generateList();
  }

  loadList(): void {
    if (!this.selectedStrategyId) {
      this.dailyList = null;
      return;
    }
    this.strategyService.getTodayList(this.selectedStrategyId).subscribe({
      next: (res) => {
        this.dailyList = res.items ? res : null;
      },
      error: () => this.dailyList = null
    });
  }

  generateList(): void {
    if (!this.selectedStrategyId) return;
    this.generating = true;
    this.message = '';
    this.strategyService.generateDailyList(this.selectedStrategyId).subscribe({
      next: () => {
        this.generating = false;
        this.message = 'Daily list generated successfully.';
        this.isError = false;
        this.loadList();
      },
      error: (err) => {
        this.generating = false;
        this.message = err.error?.error || 'Failed to generate daily list';
        this.isError = true;
      }
    });
  }

  countByStatus(status: string): number {
    if (!this.dailyList?.items) return 0;
    return this.dailyList.items.filter(i => i.status === status).length;
  }

  // Tune state methods
  tuneToggleState(code: string): void {
    const idx = this.tuneSelectedStates.indexOf(code);
    if (idx >= 0) this.tuneSelectedStates.splice(idx, 1);
    else this.tuneSelectedStates.push(code);
    this.loadTuneCounties();
  }
  tuneSelectAllStates(): void {
    this.tuneSelectedStates = this.usStates.map(s => s.code);
    this.tuneCounties = [];
    this.tuneSelectedCounty = '';
  }
  tuneClearStates(): void {
    this.tuneSelectedStates = [];
    this.tuneCounties = [];
    this.tuneSelectedCounty = '';
  }

  private loadTuneCounties(): void {
    this.tuneSelectedCounty = '';
    this.tuneCountyZipCount = 0;
    if (this.tuneSelectedStates.length === 1) {
      this.tuneLoadingCounties = true;
      this.geoService.getCounties(this.tuneSelectedStates[0]).subscribe(counties => {
        this.tuneCounties = counties;
        this.tuneLoadingCounties = false;
      });
    } else {
      this.tuneCounties = [];
    }
  }

  onTuneCountyChange(): void {
    this.tuneCountyZipCount = 0;
  }

  addTuneCountyZips(): void {
    if (!this.tuneSelectedCounty || this.tuneSelectedStates.length !== 1) return;
    this.loadingTuneZips = true;
    this.tuneCountyZipCount = 0;
    this.geoService.getZipsForCounty(this.tuneSelectedStates[0], this.tuneSelectedCounty).subscribe(zips => {
      this.loadingTuneZips = false;
      if (zips.length > 0) {
        const existing = this.tuneZipsText ? this.tuneZipsText.split(',').map(z => z.trim()).filter(z => z) : [];
        const merged = [...new Set([...existing, ...zips])].sort();
        this.tuneZipsText = merged.join(', ');
        this.tuneCountyZipCount = zips.length;
      }
    });
  }

  // New state methods
  newToggleState(code: string): void {
    const idx = this.newSelectedStates.indexOf(code);
    if (idx >= 0) this.newSelectedStates.splice(idx, 1);
    else this.newSelectedStates.push(code);
    this.loadNewCounties();
  }
  newSelectAllStates(): void {
    this.newSelectedStates = this.usStates.map(s => s.code);
    this.newCounties = [];
    this.newSelectedCounty = '';
  }
  newClearStates(): void {
    this.newSelectedStates = [];
    this.newCounties = [];
    this.newSelectedCounty = '';
  }

  private loadNewCounties(): void {
    this.newSelectedCounty = '';
    this.newCountyZipCount = 0;
    if (this.newSelectedStates.length === 1) {
      this.newLoadingCounties = true;
      this.geoService.getCounties(this.newSelectedStates[0]).subscribe(counties => {
        this.newCounties = counties;
        this.newLoadingCounties = false;
      });
    } else {
      this.newCounties = [];
    }
  }

  onNewCountyChange(): void {
    this.newCountyZipCount = 0;
  }

  addNewCountyZips(): void {
    if (!this.newSelectedCounty || this.newSelectedStates.length !== 1) return;
    this.loadingNewZips = true;
    this.newCountyZipCount = 0;
    this.geoService.getZipsForCounty(this.newSelectedStates[0], this.newSelectedCounty).subscribe(zips => {
      this.loadingNewZips = false;
      if (zips.length > 0) {
        const existing = this.newZipsText ? this.newZipsText.split(',').map(z => z.trim()).filter(z => z) : [];
        const merged = [...new Set([...existing, ...zips])].sort();
        this.newZipsText = merged.join(', ');
        this.newCountyZipCount = zips.length;
      }
    });
  }

  countZips(text: string): number {
    return text ? text.split(',').map(z => z.trim()).filter(z => z).length : 0;
  }

  updateStatus(itemId: number, status: string): void {
    this.strategyService.updateItemStatus(itemId, status).subscribe(() => this.loadList());
  }

  // Column picker
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

  // Sorting
  toggleSort(field: string): void {
    if (this.sortBy === field) {
      this.sortDir = this.sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      this.sortBy = field;
      this.sortDir = 'asc';
    }
    this.sortItems();
  }

  getSortIcon(field: string): string {
    if (this.sortBy !== field) return '\u2195';
    return this.sortDir === 'asc' ? '\u25B2' : '\u25BC';
  }

  sortItems(): void {
    if (!this.dailyList || !this.dailyList.items) return;
    const dir = this.sortDir === 'asc' ? 1 : -1;
    const field = this.sortBy;
    this.dailyList.items.sort(function(a: any, b: any) {
      let valA: any;
      let valB: any;
      if (field === 'name') { valA = a.prospect.name || ''; valB = b.prospect.name || ''; }
      else if (field === 'score') { valA = a.prospect.compositeScore || 0; valB = b.prospect.compositeScore || 0; }
      else if (field === 'intentScore') { valA = a.prospect.intentScore || 0; valB = b.prospect.intentScore || 0; }
      else if (field === 'urgency') { valA = a.prospect.urgency || ''; valB = b.prospect.urgency || ''; }
      else if (field === 'category') { valA = a.prospect.category || ''; valB = b.prospect.category || ''; }
      else if (field === 'platform') { valA = a.prospect.platform || ''; valB = b.prospect.platform || ''; }
      else if (field === 'status') { valA = a.status || ''; valB = b.status || ''; }
      else if (field === 'city') { valA = a.prospect.city || ''; valB = b.prospect.city || ''; }
      else if (field === 'state') { valA = a.prospect.state || ''; valB = b.prospect.state || ''; }
      else { valA = ''; valB = ''; }
      if (typeof valA === 'string') { valA = valA.toLowerCase(); valB = (valB as string).toLowerCase(); }
      if (valA < valB) return -1 * dir;
      if (valA > valB) return 1 * dir;
      return 0;
    });
  }

  // Filtered + sorted items
  get filteredItems(): any[] {
    if (!this.dailyList || !this.dailyList.items) return [];
    const status = this.filterStatus;
    const urgency = this.filterUrgency;
    const category = this.filterCategory;
    const platform = this.filterPlatform;
    let items = this.dailyList.items;
    if (status) {
      items = items.filter(function(i: any) { return i.status === status; });
    }
    if (urgency) {
      items = items.filter(function(i: any) { return i.prospect.urgency === urgency; });
    }
    if (category) {
      items = items.filter(function(i: any) { return i.prospect.category === category; });
    }
    if (platform) {
      items = items.filter(function(i: any) { return i.prospect.platform === platform; });
    }
    return items;
  }

  intentClass(score: number): string {
    if (score >= 60) return 'intent-score intent-high';
    if (score >= 30) return 'intent-score intent-med';
    return 'intent-score intent-low';
  }

  exportCsv(): void {
    const items = this.filteredItems;
    if (!items.length) return;
    const headers = ['Name', 'Score', 'Intent Score', 'Urgency', 'Category', 'Platform', 'Status', 'City', 'State', 'Zip', 'Email', 'Phone', 'Company', 'Post URL', 'Signal Snippet'];
    const rows = items.map((i: any) => [
      i.prospect.name || '',
      i.prospect.compositeScore ?? '',
      i.prospect.intentScore ?? '',
      i.prospect.urgency || '',
      i.prospect.category || '',
      i.prospect.platform || '',
      i.status || '',
      i.prospect.city || '',
      i.prospect.state || '',
      i.prospect.zip || '',
      i.prospect.email || '',
      i.prospect.phone || '',
      i.prospect.company || '',
      i.prospect.postUrl || '',
      (i.prospect.signalSnippet || '').replace(/\n/g, ' ')
    ]);
    const escape = (val: any) => {
      const str = String(val ?? '');
      return str.includes(',') || str.includes('"') || str.includes('\n') ? '"' + str.replace(/"/g, '""') + '"' : str;
    };
    const csv = [headers.map(escape).join(','), ...rows.map((r: any[]) => r.map(escape).join(','))].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'daily-list.csv'; a.click();
    URL.revokeObjectURL(url);
  }
}
