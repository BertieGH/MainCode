import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatSelectModule } from '@angular/material/select';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSortModule, Sort } from '@angular/material/sort';
import { MatDialogModule, MatDialog } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { SelectionModel } from '@angular/cdk/collections';
import { interval, Subscription, switchMap } from 'rxjs';
import { Signal, ProspectList } from '../../models/interfaces';
import { ApiService } from '../../services/api.service';
import { InfoDialogComponent } from '../../components/info-dialog/info-dialog.component';
import { SIGNAL_LOG_WORKFLOW } from '../../components/info-dialog/workflows';
import { downloadCsv } from '../../utils/csv-export';
import { ResizableColumnDirective } from '../../directives/resizable-column.directive';
import { ColumnWidthsService } from '../../services/column-widths.service';

@Component({
  selector: 'app-signal-log',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    MatCardModule, MatTableModule, MatCheckboxModule, MatSelectModule,
    MatFormFieldModule, MatInputModule, MatButtonModule, MatIconModule,
    MatChipsModule, MatExpansionModule, MatPaginatorModule, MatProgressBarModule, MatSortModule, MatDialogModule, MatSnackBarModule,
    MatTooltipModule,
    ResizableColumnDirective
  ],
  templateUrl: './signal-log.component.html',
  styleUrl: './signal-log.component.scss'
})
export class SignalLogComponent implements OnInit, OnDestroy {
  signals: Signal[] = [];
  filteredSignals: Signal[] = [];
  selection = new SelectionModel<Signal>(true, []);
  prospectLists: ProspectList[] = [];
  loading = false;

  displayedColumns = ['select', 'companyName', 'industry', 'fundingRound', 'amount', 'location', 'date', 'source', 'actions'];

  industries = ['All', 'AI', 'Fintech', 'SaaS', 'Cybersecurity', 'HealthTech', 'EdTech', 'CleanTech', 'Other'];
  fundingRounds = ['All', 'Pre-Seed', 'Seed', 'Series A', 'Series B', 'Series C', 'Series D', 'Growth', 'Other'];

  filterIndustry = 'All';
  filterRound = 'All';
  filterAmountMin = '';
  filterAmountMax = '';
  filterLocation = '';
  filterDateFrom = '';
  filterDateTo = '';
  /** Free-text quick-filter over company / industry / source title. Client-side. */
  filterQuery = '';
  /** Country code from `countryOptions`. Client-side substring match against `location`. */
  filterCountry = '';
  selectedListId = '';
  newListName = '';
  showNewListInput = false;

  /** Country options + heuristic substring patterns matched against the
   * signal's `location` field (signals don't carry an explicit country column). */
  countryOptions: { code: string; label: string; flag?: string; matchers?: string[] }[] = [
    { code: '',   label: 'All countries' },
    { code: 'US', label: 'United States', flag: '🇺🇸',
      matchers: ['usa', 'united states', ', us', ' u.s.', 'america',
                 'new york', 'san francisco', 'boston', 'seattle', 'austin', 'los angeles', 'chicago'] },
    { code: 'GB', label: 'United Kingdom', flag: '🇬🇧',
      matchers: ['uk', 'united kingdom', 'britain', 'england', 'london', 'manchester', 'edinburgh'] },
    { code: 'IN', label: 'India', flag: '🇮🇳',
      matchers: ['india', ', in ', 'mumbai', 'bangalore', 'bengaluru', 'delhi', 'hyderabad', 'chennai', 'pune'] },
    { code: 'CA', label: 'Canada', flag: '🇨🇦',
      matchers: ['canada', 'toronto', 'vancouver', 'montreal', 'ottawa'] },
    { code: 'DE', label: 'Germany', flag: '🇩🇪',
      matchers: ['germany', 'berlin', 'munich', 'münchen', 'hamburg', 'frankfurt'] },
    { code: 'FR', label: 'France', flag: '🇫🇷',
      matchers: ['france', 'paris', 'lyon', 'marseille'] },
    { code: 'IL', label: 'Israel', flag: '🇮🇱',
      matchers: ['israel', 'tel aviv', 'jerusalem', 'haifa'] },
    { code: 'SG', label: 'Singapore', flag: '🇸🇬', matchers: ['singapore'] },
    { code: 'AU', label: 'Australia', flag: '🇦🇺',
      matchers: ['australia', 'sydney', 'melbourne', 'brisbane'] },
    { code: 'NL', label: 'Netherlands', flag: '🇳🇱',
      matchers: ['netherlands', 'amsterdam', 'rotterdam', 'the hague'] },
    { code: 'OTHER', label: 'Other / unknown' },
  ];

  /** Live progress for the location-backfill background job. Same pattern as
   * the country backfill on News Log: 1.5s polling until terminal status. */
  backfillRun: {
    runId: string;
    status: 'running' | 'done' | 'warning' | 'error';
    total: number;
    processed: number;
    updated: number;
    stillUnknown: number;
    scopeMsg: string;
  } | null = null;
  private backfillPollSub?: Subscription;

  get backfilling(): boolean {
    return this.backfillRun?.status === 'running';
  }

  get backfillProgressPct(): number {
    const r = this.backfillRun;
    if (!r || !r.total) return 0;
    return Math.min(100, Math.round((r.processed / r.total) * 100));
  }

  /** Pagination state (client-side; backend returns up to 2000 in one go).
   * `displaySignals` slices `filteredSignals` for the visible page, while the
   * stat cards / "Selected" count / CSV export still use the full filtered set. */
  pageIndex = 0;
  pageSize = 25;
  pageSizeOptions = [10, 25, 50, 100, 200];

  get displaySignals(): Signal[] {
    const start = this.pageIndex * this.pageSize;
    return this.filteredSignals.slice(start, start + this.pageSize);
  }

  onPage(e: PageEvent) {
    this.pageIndex = e.pageIndex;
    this.pageSize = e.pageSize;
  }

  private _resetPage() { this.pageIndex = 0; }

  /** Expansion-panel state for the filter section (matches News Log behavior). */
  filtersPanelOpen = false;

  /** Count of filters currently narrowing the signals list. Shown in the
   * collapsed panel header so the user knows what's hidden. */
  get activeFilterCount(): number {
    let n = 0;
    if (this.filterIndustry && this.filterIndustry !== 'All') n++;
    if (this.filterRound && this.filterRound !== 'All') n++;
    if (this.filterAmountMin !== '' && this.filterAmountMin != null) n++;
    if (this.filterAmountMax !== '' && this.filterAmountMax != null) n++;
    if (this.filterLocation) n++;
    if (this.filterDateFrom) n++;
    if (this.filterDateTo) n++;
    if (this.filterQuery.trim()) n++;
    if (this.filterCountry) n++;
    return n;
  }

  columnWidths: Record<string, number> = {};

  constructor(
    private snackBar: MatSnackBar,
    private api: ApiService,
    private dialog: MatDialog,
    private widthsSvc: ColumnWidthsService,
  ) {
    this.columnWidths = this.widthsSvc.load('signal-log');
  }

  onColumnResized(col: string, w: number) {
    this.columnWidths = { ...this.columnWidths, [col]: w };
    this.widthsSvc.save('signal-log', this.columnWidths);
  }

  openInfo() {
    this.dialog.open(InfoDialogComponent, { data: SIGNAL_LOG_WORKFLOW, width: '880px', maxWidth: '95vw' });
  }

  ngOnInit() {
    this.loadSignals();
    this.loadLists();
  }

  loadSignals() {
    this.loading = true;
    const filters: any = {};
    if (this.filterIndustry !== 'All') filters.industry = this.filterIndustry;
    if (this.filterRound !== 'All') filters.funding_round = this.filterRound;
    if (this.filterAmountMin) filters.amount_min = +this.filterAmountMin * 1000000;
    if (this.filterAmountMax) filters.amount_max = +this.filterAmountMax * 1000000;
    if (this.filterLocation) filters.location = this.filterLocation;
    if (this.filterDateFrom) filters.date_from = this.filterDateFrom;
    if (this.filterDateTo) filters.date_to = this.filterDateTo;

    this.api.getSignals(filters).subscribe({
      next: (data) => {
        this.signals = data;
        this.applyClientFilters();
        this._resetPage();
        this.loading = false;
      },
      error: () => {
        this.loading = false;
        this.snackBar.open('Failed to load signals', 'OK', { duration: 3000 });
      }
    });
  }

  /** Re-derive `filteredSignals` from `signals` (the backend result) by applying
   * the client-side text-search and country filters. Called whenever those
   * change and after every backend reload. */
  applyClientFilters() {
    this._resetPage();
    const q = this.filterQuery.trim().toLowerCase();
    const matchers = this.countryMatchers();
    const wantUnknownCountry = this.filterCountry === 'OTHER';
    const knownCountryMatchers = this.countryOptions
      .filter(o => o.code && o.code !== 'OTHER')
      .flatMap(o => o.matchers || []);

    this.filteredSignals = this.signals.filter(s => {
      if (q) {
        const haystack = `${s.companyName ?? ''} ${s.industry ?? ''} ${s.sourceTitle ?? ''}`.toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      if (this.filterCountry) {
        const loc = (s.location ?? '').toLowerCase();
        if (wantUnknownCountry) {
          // "Other / unknown": location doesn't match any known country pattern
          if (knownCountryMatchers.some(m => loc.includes(m))) return false;
        } else {
          if (!matchers.length || !matchers.some(m => loc.includes(m))) return false;
        }
      }
      return true;
    });
  }

  private countryMatchers(): string[] {
    if (!this.filterCountry) return [];
    return this.countryOptions.find(o => o.code === this.filterCountry)?.matchers ?? [];
  }

  loadLists() {
    this.api.getProspectLists().subscribe({
      next: (data) => this.prospectLists = data,
    });
  }

  applyFilters() {
    this.loadSignals();
  }

  /** Kick off a background location-backfill job. Mirrors backfillCountries
   * on News Log. If signals are selected, only those are processed; otherwise
   * up to 100 most-recent empty-location rows are picked. */
  backfillLocations() {
    if (this.backfilling) return;
    const ids = this.selection.selected.map(s => s.id);
    const opts = ids.length > 0 ? { signalIds: ids } : { limit: 100 };
    const scopeMsg = ids.length > 0
      ? `${ids.length} selected signal${ids.length === 1 ? '' : 's'}`
      : 'up to 100 empty-location signals';
    this.api.backfillSignalLocations(opts).subscribe({
      next: (res) => {
        if (!res.runId || res.status === 'noop' || res.total === 0) {
          this.snackBar.open('No signals to backfill — none have empty location.', 'OK', { duration: 3000 });
          return;
        }
        this.backfillRun = {
          runId: res.runId,
          status: 'running',
          total: res.total,
          processed: 0,
          updated: 0,
          stillUnknown: 0,
          scopeMsg,
        };
        this._startBackfillPoll(res.runId);
      },
      error: (err) => {
        const msg = err?.error?.detail || 'Location backfill failed to start';
        this.snackBar.open(msg, 'OK', { duration: 4000 });
      }
    });
  }

  private _startBackfillPoll(runId: string) {
    this.backfillPollSub?.unsubscribe();
    this.backfillPollSub = interval(1500)
      .pipe(switchMap(() => this.api.getSignalBackfillRun(runId)))
      .subscribe({
        next: (run) => {
          if (!this.backfillRun || this.backfillRun.runId !== runId) return;
          this.backfillRun = {
            ...this.backfillRun,
            status: run.status as any,
            total: run.total,
            processed: run.processed,
            updated: run.updated,
            stillUnknown: run.stillUnknown,
          };
          if (run.status !== 'running') {
            this._finishBackfill(run.status, run.message);
          }
        },
        error: () => {
          this._finishBackfill('error', 'Lost connection while polling backfill progress.');
        }
      });
  }

  private _finishBackfill(status: string, message: string | null) {
    this.backfillPollSub?.unsubscribe();
    this.backfillPollSub = undefined;
    const r = this.backfillRun;
    if (!r) return;
    const headline = status === 'done'
      ? `Location backfill (${r.scopeMsg}): updated ${r.updated}/${r.total}, still unknown ${r.stillUnknown}` + (message ? ` — ${message}` : '')
      : `Location backfill ${status} after ${r.processed}/${r.total} — ${message || 'see API logs'}`;
    this.snackBar.open(headline, 'OK', { duration: 6000 });
    this.backfillRun = null;
    this.loadSignals();
  }

  ngOnDestroy() {
    this.backfillPollSub?.unsubscribe();
  }

  clearFilters() {
    this.filterIndustry = 'All';
    this.filterRound = 'All';
    this.filterAmountMin = '';
    this.filterAmountMax = '';
    this.filterLocation = '';
    this.filterDateFrom = '';
    this.filterDateTo = '';
    this.filterQuery = '';
    this.filterCountry = '';
    this.loadSignals();
  }

  isAllSelected() {
    return this.selection.selected.length === this.filteredSignals.length;
  }

  toggleAllRows() {
    this.isAllSelected() ? this.selection.clear() : this.filteredSignals.forEach(row => this.selection.select(row));
  }

  formatAmount(amount: number): string {
    if (amount >= 1000000000) return '$' + (amount / 1000000000).toFixed(1) + 'B';
    if (amount >= 1000000) return '$' + (amount / 1000000).toFixed(0) + 'M';
    if (amount >= 1000) return '$' + (amount / 1000).toFixed(0) + 'K';
    return '$' + amount;
  }

  sortData(sort: Sort) {
    this._resetPage();
    const data = [...this.filteredSignals];
    if (!sort.active || sort.direction === '') {
      this.filteredSignals = data;
      return;
    }
    this.filteredSignals = data.sort((a, b) => {
      const isAsc = sort.direction === 'asc';
      switch (sort.active) {
        case 'companyName': return compare(a.companyName, b.companyName, isAsc);
        case 'industry': return compare(a.industry, b.industry, isAsc);
        case 'fundingRound': return compare(a.fundingRound, b.fundingRound, isAsc);
        case 'amount': return compare(a.amount, b.amount, isAsc);
        case 'date': return compare(a.date, b.date, isAsc);
        case 'location': return compareWithEmptyLast(a.location, b.location, isAsc);
        case 'sourceTitle': return compareWithEmptyLast(a.sourceTitle, b.sourceTitle, isAsc);
        default: return 0;
      }
    });
  }

  getTotalFunding(): number {
    return this.filteredSignals.reduce((sum, s) => sum + s.amount, 0);
  }

  getUniqueIndustries(): number {
    return new Set(this.filteredSignals.map(s => s.industry)).size;
  }

  exportCsv() {
    downloadCsv('signals', [
      { header: 'Company', value: s => s.companyName },
      { header: 'Industry', value: s => s.industry },
      { header: 'Funding Round', value: s => s.fundingRound },
      { header: 'Amount (USD)', value: s => s.amount },
      { header: 'Location', value: s => s.location },
      { header: 'Date', value: s => s.date },
      { header: 'Source Title', value: s => s.sourceTitle },
      { header: 'Source URL', value: s => s.sourceUrl },
    ], this.filteredSignals);
  }

  addToList() {
    if (this.selection.selected.length === 0) return;
    const signalIds = this.selection.selected.map(s => s.id);

    if (this.showNewListInput && this.newListName.trim()) {
      // Create new list first, then add signals
      this.api.createProspectList(this.newListName, '').subscribe({
        next: (list) => {
          this.api.addSignalsToList(list.id, signalIds).subscribe({
            next: (res) => {
              this.snackBar.open(this._addResultMessage(res, list.name), 'View', { duration: 4500 });
              this.selection.clear();
              this.showNewListInput = false;
              this.newListName = '';
              this.loadLists();
            },
            error: () => this.snackBar.open('Failed to add signals', 'OK', { duration: 3000 })
          });
        },
        error: () => this.snackBar.open('Failed to create list', 'OK', { duration: 3000 })
      });
    } else if (this.selectedListId) {
      this.api.addSignalsToList(this.selectedListId, signalIds).subscribe({
        next: (res) => {
          const listName = this.prospectLists.find(l => l.id === this.selectedListId)?.name || '';
          this.snackBar.open(this._addResultMessage(res, listName), 'View', { duration: 4500 });
          this.selection.clear();
        },
        error: () => this.snackBar.open('Failed to add signals', 'OK', { duration: 3000 })
      });
    }
  }

  private _addResultMessage(res: { added: any[]; skipped: any[] }, listName: string): string {
    const added = res.added?.length ?? 0;
    const skipped = res.skipped ?? [];
    if (skipped.length === 0) {
      return `Added ${added} companies to "${listName}"`;
    }
    const dupSignal = skipped.filter(s => s.reason === 'dup_signal').length;
    const dupCompany = skipped.filter(s => s.reason === 'dup_company_in_list').length;
    const dupBatch = skipped.filter(s => s.reason === 'dup_company_in_batch').length;
    const parts: string[] = [];
    if (dupCompany) parts.push(`${dupCompany} already on list`);
    if (dupSignal) parts.push(`${dupSignal} same signal`);
    if (dupBatch) parts.push(`${dupBatch} duplicate in selection`);
    return `Added ${added} to "${listName}" — skipped ${skipped.length} (${parts.join(', ')})`;
  }

  deleteSignal(signal: Signal, event?: MouseEvent) {
    event?.stopPropagation();
    if (!confirm(`Delete signal "${signal.companyName}"?`)) return;
    this.api.deleteSignal(signal.id).subscribe({
      next: () => {
        this.signals = this.signals.filter(s => s.id !== signal.id);
        this.applyFilters();
        this.selection.deselect(signal);
        this.snackBar.open(`Deleted "${signal.companyName}"`, 'OK', { duration: 2500 });
      },
      error: () => this.snackBar.open('Failed to delete signal', 'OK', { duration: 3000 })
    });
  }

  deleteSelected() {
    const ids = this.selection.selected.map(s => s.id);
    if (!ids.length) return;
    if (!confirm(`Delete ${ids.length} selected signal${ids.length === 1 ? '' : 's'}?`)) return;
    this.api.bulkDeleteSignals(ids).subscribe({
      next: (res) => {
        const deletedSet = new Set(ids);
        this.signals = this.signals.filter(s => !deletedSet.has(s.id));
        this.selection.clear();
        this.applyFilters();
        this.snackBar.open(`Deleted ${res.deleted} signal${res.deleted === 1 ? '' : 's'}`, 'OK', { duration: 2500 });
      },
      error: () => this.snackBar.open('Bulk delete failed', 'OK', { duration: 3000 })
    });
  }
}

function compare(a: string | number, b: string | number, isAsc: boolean): number {
  return (a < b ? -1 : 1) * (isAsc ? 1 : -1);
}

/** Sort empty / null strings to the bottom regardless of asc/desc — useful
 * for Location and Source where a lot of rows can be blank and shouldn't
 * dominate either end of the order. */
function compareWithEmptyLast(a: string | null | undefined, b: string | null | undefined, isAsc: boolean): number {
  const x = (a || '').trim();
  const y = (b || '').trim();
  if (!x && !y) return 0;
  if (!x) return 1;
  if (!y) return -1;
  return x.localeCompare(y) * (isAsc ? 1 : -1);
}
