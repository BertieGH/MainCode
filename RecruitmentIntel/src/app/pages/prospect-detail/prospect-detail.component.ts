import { ChangeDetectorRef, Component, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatTable, MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatMenuModule } from '@angular/material/menu';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { SelectionModel } from '@angular/cdk/collections';
import { Prospect, ProspectList } from '../../models/interfaces';
import { ApiService } from '../../services/api.service';
import { downloadCsv } from '../../utils/csv-export';
import { ResizableColumnDirective } from '../../directives/resizable-column.directive';
import { ColumnWidthsService } from '../../services/column-widths.service';

@Component({
  selector: 'app-prospect-detail',
  standalone: true,
  imports: [
    CommonModule, FormsModule, RouterLink,
    MatCardModule, MatCheckboxModule, MatTableModule, MatButtonModule, MatIconModule,
    MatChipsModule, MatPaginatorModule, MatProgressBarModule, MatProgressSpinnerModule,
    MatTooltipModule, MatMenuModule, MatSnackBarModule,
    ResizableColumnDirective
  ],
  templateUrl: './prospect-detail.component.html',
  styleUrl: './prospect-detail.component.scss'
})
export class ProspectDetailComponent implements OnInit, OnDestroy {
  listId = '';
  list: ProspectList | undefined;
  prospects: Prospect[] = [];
  displayedColumns = ['select', 'companyName', 'industry', 'fundingRound', 'amount', 'website', 'linkedin', 'jobCount', 'actions'];

  /** Multi-select for bulk actions. Operates on the FULL filtered set, not just
   * the visible page (so "Select all" via the master checkbox picks all 318
   * even when only 25 are on screen). */
  selection = new SelectionModel<Prospect>(true, []);

  /** Client-side pagination state — same pattern as Signal Log. */
  pageIndex = 0;
  pageSize = 25;
  pageSizeOptions = [10, 25, 50, 100, 200];

  get displayProspects(): Prospect[] {
    const start = this.pageIndex * this.pageSize;
    return this.prospects.slice(start, start + this.pageSize);
  }

  onPage(e: PageEvent) {
    this.pageIndex = e.pageIndex;
    this.pageSize = e.pageSize;
  }

  /** True when every visible row on the current page is selected. */
  isAllVisibleSelected(): boolean {
    const visible = this.displayProspects;
    return visible.length > 0 && visible.every(p => this.selection.isSelected(p));
  }

  /** Toggle the master "select all visible" checkbox. */
  toggleAllVisible() {
    const visible = this.displayProspects;
    if (this.isAllVisibleSelected()) {
      visible.forEach(p => this.selection.deselect(p));
    } else {
      visible.forEach(p => this.selection.select(p));
    }
  }

  clearSelection() { this.selection.clear(); }

  private _resetPage() { this.pageIndex = 0; }

  private pollHandle: ReturnType<typeof setInterval> | null = null;
  private pollStart = 0;
  private readonly POLL_MS = 2000;
  private readonly POLL_MAX_MS = 10 * 60 * 1000;
  /** Wall-clock of last successful prospects refresh — bound into the live indicator. */
  lastPollAt: number | null = null;
  /** Cheap 1Hz tick so the "refreshed Xs ago" badge updates between polls. */
  private uiTickHandle: ReturnType<typeof setInterval> | null = null;
  uiTick = 0;

  /** Direct handle to the MatTable so we can call renderRows() after mutating
   * the prospects array — Material Table doesn't auto re-render when only the
   * array contents change, even if we replace the array reference. */
  @ViewChild(MatTable) prospectTable?: MatTable<Prospect>;

  /** Stable identity for change-detection diffing. */
  trackByProspect = (_: number, p: Prospect) => p.id;
  /** Snapshot of (id → enrichmentStatus|jobCrawlStatus) used to detect transitions
   * between polls so we can surface snackbars when a row settles. */
  private prevStatuses: Map<string, { e?: string; c?: string }> = new Map();

  columnWidths: Record<string, number> = {};

  constructor(
    private route: ActivatedRoute,
    private snackBar: MatSnackBar,
    private api: ApiService,
    private cdr: ChangeDetectorRef,
    private widthsSvc: ColumnWidthsService,
  ) {
    this.listId = this.route.snapshot.paramMap.get('id') || '';
    this.columnWidths = this.widthsSvc.load('prospect-detail');
  }

  onColumnResized(col: string, w: number) {
    this.columnWidths = { ...this.columnWidths, [col]: w };
    this.widthsSvc.save('prospect-detail', this.columnWidths);
  }

  ngOnInit() {
    this.loadList();
    this.loadProspects();
    // 1Hz tick keeps the "refreshed Xs ago" badge live without forcing a full poll.
    this.uiTickHandle = setInterval(() => { this.uiTick++; }, 1000);
  }

  ngOnDestroy() {
    this.stopPolling();
    if (this.uiTickHandle) { clearInterval(this.uiTickHandle); this.uiTickHandle = null; }
  }

  loadList() {
    if (!this.listId) return;
    this.api.getProspectList(this.listId).subscribe({
      next: (data) => this.list = data,
      error: () => this.snackBar.open('Failed to load list', 'OK', { duration: 3000 })
    });
  }

  loadProspects() {
    if (!this.listId) return;
    this.api.getProspects(this.listId).subscribe({
      next: (data) => {
        this._applyProspects(data);
        // Drop selection entries for prospects no longer in the list (e.g.
        // after a remove). Keep the rest so a partial reload doesn't clobber.
        const present = new Set(data.map(p => p.id));
        this.selection.selected
          .filter(p => !present.has(p.id))
          .forEach(p => this.selection.deselect(p));
        // First load resets to page 1; subsequent polls keep the user where
        // they were. Caller distinguishes via .anyPending() heuristic — when
        // there's no pending work, this is most likely a user-initiated
        // refresh so we reset; otherwise it's a poll mid-run.
        if (!this.anyPending()) this._resetPage();
        if (this.anyPending()) this.startPolling();
        else this.stopPolling();
      },
      error: () => this.snackBar.open('Failed to load prospects', 'OK', { duration: 3000 })
    });
  }

  /** Replace the prospects array, emit snackbars for any row that just
   * transitioned out of `pending`, and record the refresh time. */
  private _applyProspects(data: Prospect[]) {
    const transitions: string[] = [];
    for (const p of data) {
      const prev = this.prevStatuses.get(p.id);
      if (prev) {
        if (prev.e === 'pending' && p.enrichmentStatus !== 'pending') {
          transitions.push(`${p.companyName}: enrichment ${p.enrichmentStatus}`);
        }
        if (prev.c === 'pending' && p.jobCrawlStatus !== 'pending') {
          transitions.push(`${p.companyName}: job crawl ${p.jobCrawlStatus}`);
        }
      }
      this.prevStatuses.set(p.id, { e: p.enrichmentStatus, c: p.jobCrawlStatus });
    }
    this.prospects = [...data];  // new ref so OnPush + plain-array diffs notice
    this.lastPollAt = Date.now();
    // MatTable with `[dataSource]="prospects"` (a plain array) doesn't re-render
    // automatically when the underlying contents change — even a fresh array
    // reference isn't always enough. Tell it explicitly.
    if (this.prospectTable) this.prospectTable.renderRows();
    this.cdr.markForCheck();
    if (transitions.length > 0) {
      this.snackBar.open(transitions.join(' · '), 'OK', { duration: 4500 });
    }
  }

  /** Seconds since the last successful poll/refresh — used by the live indicator. */
  secondsSinceRefresh(): number | null {
    return this.lastPollAt ? Math.floor((Date.now() - this.lastPollAt) / 1000) : null;
  }

  anyPending(): boolean {
    return this.prospects.some(p =>
      p.enrichmentStatus === 'pending' || p.jobCrawlStatus === 'pending'
    );
  }

  isRowPending(p: Prospect): boolean {
    return p.enrichmentStatus === 'pending' || p.jobCrawlStatus === 'pending';
  }

  private startPolling() {
    if (this.pollHandle) return;
    this.pollStart = Date.now();
    this.pollHandle = setInterval(() => {
      if (Date.now() - this.pollStart > this.POLL_MAX_MS) {
        this.stopPolling();
        this.snackBar.open(
          'Polling timed out after 10 min — click Refresh to check status manually.',
          'OK', { duration: 5000 }
        );
        return;
      }
      this.api.getProspects(this.listId).subscribe({
        next: (data) => {
          this._applyProspects(data);
          if (!this.anyPending()) this.stopPolling();
        },
        // Network blip → keep polling, don't kill the timer.
      });
    }, this.POLL_MS);
  }

  private stopPolling() {
    if (this.pollHandle) {
      clearInterval(this.pollHandle);
      this.pollHandle = null;
    }
  }

  get enrichedCount(): number { return this.prospects.filter(p => p.enrichmentStatus === 'done').length; }
  get pendingCount(): number { return this.prospects.filter(p => p.enrichmentStatus === 'pending').length; }
  get failedCount(): number { return this.prospects.filter(p => p.enrichmentStatus === 'failed').length; }
  get crawledCount(): number { return this.prospects.filter(p => p.jobCrawlStatus === 'done').length; }
  get emptyCount(): number { return this.prospects.filter(p => p.jobCrawlStatus === 'empty').length; }
  get totalJobs(): number { return this.prospects.reduce((sum, p) => sum + p.jobCount, 0); }
  get enrichPercent(): number { return this.prospects.length > 0 ? (this.enrichedCount / this.prospects.length) * 100 : 0; }
  get crawlPercent(): number { return this.prospects.length > 0 ? (this.crawledCount / this.prospects.length) * 100 : 0; }

  formatAmount(amount: number): string {
    if (amount >= 1000000000) return '$' + (amount / 1000000000).toFixed(1) + 'B';
    if (amount >= 1000000) return '$' + (amount / 1000000).toFixed(0) + 'M';
    return '$' + amount;
  }

  enrichAll(force = false) {
    if (force && !confirm(`Re-enrich every prospect (${this.prospects.length} rows), including ones already 'done'? This is useful after changing LLM provider or model settings.`)) {
      return;
    }
    this.snackBar.open(
      force ? 'Re-enriching all prospects…' : 'Enrichment started for pending prospects…',
      '', { duration: 2000 }
    );
    this.startPolling();
    this.api.enrichList(this.listId, force).subscribe({
      next: () => {
        this.snackBar.open('Enrichment queued — watch the progress bar', 'OK', { duration: 3000 });
        this.loadProspects();
      },
      error: () => this.snackBar.open('Failed to queue enrichment', 'OK', { duration: 3000 })
    });
  }

  crawlAll(force = false) {
    if (force && !confirm(`Re-crawl jobs for every enriched prospect (deletes prior Job rows and cached careers URLs first)? Use this after changing LLM / crawl settings.`)) {
      return;
    }
    this.snackBar.open(
      force ? 'Re-crawling jobs for all enriched prospects…' : 'Job crawl started for enriched prospects…',
      '', { duration: 2000 }
    );
    this.startPolling();
    this.api.crawlJobsForList(this.listId, force).subscribe({
      next: () => {
        this.snackBar.open('Job crawl queued — watch the progress bar', 'OK', { duration: 3000 });
        this.loadProspects();
      },
      error: () => this.snackBar.open('Failed to queue job crawl', 'OK', { duration: 3000 })
    });
  }

  // ----- Bulk actions on selected prospects -----

  enrichSelected(force = false) {
    const ids = this.selection.selected.map(p => p.id);
    if (!ids.length) return;
    if (force && !confirm(`Re-enrich ${ids.length} selected prospect(s), including ones already 'done'?`)) return;
    this.startPolling();
    this.api.enrichList(this.listId, force, ids).subscribe({
      next: (res: any) => {
        this.snackBar.open(
          `Enrich queued for ${ids.length} prospect${ids.length === 1 ? '' : 's'} (${res?.mode || 'inproc'}) — watch progress`,
          'OK', { duration: 3500 }
        );
        this.loadProspects();
      },
      error: () => this.snackBar.open('Failed to queue enrichment', 'OK', { duration: 3000 })
    });
  }

  crawlSelected(force = false) {
    const ids = this.selection.selected.map(p => p.id);
    if (!ids.length) return;
    // Backend filters to enrichment_status=done; warn if user picked rows that won't be processed.
    const eligible = this.selection.selected.filter(p => p.enrichmentStatus === 'done').length;
    if (eligible === 0) {
      this.snackBar.open('None of the selected prospects are enriched yet — enrich first.', 'OK', { duration: 4000 });
      return;
    }
    if (eligible < ids.length) {
      if (!confirm(`${ids.length - eligible} of ${ids.length} selected aren't enriched yet and will be skipped. Continue with the ${eligible} enriched?`)) return;
    }
    if (force && !confirm(`Re-crawl jobs for ${eligible} selected prospect(s)? Existing Job rows + cached careers URLs are wiped first.`)) return;
    this.startPolling();
    this.api.crawlJobsForList(this.listId, force, ids).subscribe({
      next: (res: any) => {
        this.snackBar.open(
          `Job crawl queued for ${eligible} prospect${eligible === 1 ? '' : 's'} (${res?.mode || 'inproc'})`,
          'OK', { duration: 3500 }
        );
        this.loadProspects();
      },
      error: () => this.snackBar.open('Failed to queue job crawl', 'OK', { duration: 3000 })
    });
  }

  /** True when at least one selected row is `enrichment_status=done` (i.e.
   * crawlable). Drives the [disabled] state of "Crawl Selected". */
  hasEnrichedSelected(): boolean {
    return this.selection.selected.some(p => p.enrichmentStatus === 'done');
  }

  enrichOne(prospect: Prospect) {
    this.snackBar.open(`Enriching ${prospect.companyName}…`, '', { duration: 1500 });
    // Optimistic: mark row pending so spinner shows immediately
    const idx = this.prospects.findIndex(p => p.id === prospect.id);
    if (idx > -1) {
      this.prospects[idx] = { ...this.prospects[idx], enrichmentStatus: 'pending' };
      this.prospects = [...this.prospects];
      this.prospectTable?.renderRows();
    }
    this.prevStatuses.set(prospect.id, { e: 'pending', c: this.prospects[idx]?.jobCrawlStatus });
    this.startPolling();
    this.api.enrichProspect(prospect.id).subscribe({
      next: (updated) => {
        if (idx > -1) {
          this.prospects[idx] = {
            ...this.prospects[idx],
            website: updated.website,
            linkedinUrl: updated.linkedinUrl,
            enrichmentStatus: updated.enrichmentStatus,
            enrichmentStrategy: updated.enrichmentStrategy,
            enrichmentError: updated.enrichmentError,
          };
          this.prospects = [...this.prospects];
          this.prospectTable?.renderRows();
          this.prevStatuses.set(prospect.id, { e: updated.enrichmentStatus, c: updated.jobCrawlStatus });
        }
        this.lastPollAt = Date.now();
        this.snackBar.open(`${prospect.companyName} enrichment ${updated.enrichmentStatus}`, 'OK', { duration: 2500 });
        if (!this.anyPending()) this.stopPolling();
      },
      // The single-prospect enrich endpoint is sync — a long LLM call can drop the
      // HTTP response (timeout, reload, network blip) even though the backend keeps
      // working and writes the final row. Don't mark anything failed; keep polling
      // — the row will settle to its real status once the backend commits.
      error: () => {
        this.snackBar.open(
          `${prospect.companyName}: response dropped — still polling, will update when ready.`,
          'OK', { duration: 4000 }
        );
      }
    });
  }

  crawlOne(prospect: Prospect, force = false) {
    this.snackBar.open(
      force ? `Re-crawling ${prospect.companyName}…` : `Crawling jobs for ${prospect.companyName}…`,
      '', { duration: 1500 }
    );
    const idx = this.prospects.findIndex(p => p.id === prospect.id);
    if (idx > -1) {
      this.prospects[idx] = { ...this.prospects[idx], jobCrawlStatus: 'pending' };
      this.prospects = [...this.prospects];
      this.prospectTable?.renderRows();
    }
    this.prevStatuses.set(prospect.id, { e: this.prospects[idx]?.enrichmentStatus, c: 'pending' });
    this.startPolling();
    this.api.crawlJobsForProspect(prospect.id, force).subscribe({
      next: (res) => {
        if (idx > -1) {
          this.prospects[idx] = {
            ...this.prospects[idx],
            careersUrl: res.careersUrl,
            jobCrawlStatus: res.jobCrawlStatus,
            jobCrawlStrategy: res.jobCrawlStrategy,
            jobCrawlRawCount: res.jobCrawlRawCount ?? 0,
            jobCrawlError: res.jobCrawlError,
            jobCount: res.jobsFound ?? this.prospects[idx].jobCount,
          };
          this.prospects = [...this.prospects];
          this.prospectTable?.renderRows();
          this.prevStatuses.set(prospect.id, { e: this.prospects[idx].enrichmentStatus, c: res.jobCrawlStatus });
        }
        this.lastPollAt = Date.now();
        const msg = res.jobCrawlStatus === 'empty'
          ? `${prospect.companyName}: careers page found but 0 listings`
          : `${prospect.companyName}: found ${res.jobsFound ?? 0} jobs`;
        this.snackBar.open(msg, 'OK', { duration: 3500 });
        if (!this.anyPending()) this.stopPolling();
      },
      // Long crawls (Playwright + LLM) can drop the response — keep polling.
      error: () => {
        this.snackBar.open(
          `${prospect.companyName}: response dropped — still polling, will update when ready.`,
          'OK', { duration: 4000 }
        );
      }
    });
  }

  exportCsv() {
    const slug = (this.list?.name || 'prospects').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    // When the user has rows selected, export ONLY those — otherwise export
    // the whole list (prior behavior).
    const rows = this.selection.selected.length > 0 ? this.selection.selected : this.prospects;
    downloadCsv(`prospects-${slug}`, [
      { header: 'Company', value: p => p.companyName },
      { header: 'Industry', value: p => p.industry },
      { header: 'Funding Round', value: p => p.fundingRound },
      { header: 'Amount (USD)', value: p => p.amount },
      { header: 'Website', value: p => p.website },
      { header: 'LinkedIn', value: p => p.linkedinUrl },
      { header: 'Enrichment Status', value: p => p.enrichmentStatus },
      { header: 'Enrichment Strategy', value: p => p.enrichmentStrategy },
      { header: 'Job Crawl Status', value: p => p.jobCrawlStatus },
      { header: 'Job Crawl Strategy', value: p => p.jobCrawlStrategy },
      { header: 'Careers URL', value: p => p.careersUrl },
      { header: 'Jobs Found', value: p => p.jobCount },
      { header: 'Raw Listings', value: p => p.jobCrawlRawCount },
    ], rows);
  }

  removeProspect(prospect: Prospect) {
    this.api.removeProspect(this.listId, prospect.id).subscribe({
      next: () => this.prospects = this.prospects.filter(p => p.id !== prospect.id),
      error: () => this.snackBar.open('Failed to remove prospect', 'OK', { duration: 3000 })
    });
  }

  getStatusIcon(status: string): string {
    switch (status) {
      case 'done': return 'check_circle';
      case 'pending': return 'hourglass_empty';
      case 'failed': return 'error';
      case 'empty': return 'inbox';
      default: return 'radio_button_unchecked';
    }
  }

  getStatusColor(status: string): string {
    switch (status) {
      case 'done': return '#4caf50';
      case 'pending': return '#2196f3';
      case 'failed': return '#f44336';
      case 'empty': return '#ff9800';
      default: return '#ccc';
    }
  }

  enrichmentTooltip(p: Prospect): string {
    const parts: string[] = [p.enrichmentStatus];
    if (p.enrichmentStrategy) parts.push(`via ${p.enrichmentStrategy}`);
    if (p.enrichmentError) parts.push(p.enrichmentError);
    return parts.join(' — ');
  }

  crawlTooltip(p: Prospect): string {
    const parts: string[] = [p.jobCrawlStatus];
    if (p.jobCrawlStrategy) parts.push(`via ${p.jobCrawlStrategy}`);
    if (p.jobCrawlRawCount) parts.push(`raw: ${p.jobCrawlRawCount} scraped`);
    if (p.jobCrawlError) parts.push(p.jobCrawlError);
    return parts.join(' — ');
  }
}
