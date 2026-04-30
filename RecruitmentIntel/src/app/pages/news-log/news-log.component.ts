import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { Subscription, interval, switchMap } from 'rxjs';
import { InfoDialogComponent } from '../../components/info-dialog/info-dialog.component';
import { NEWS_LOG_WORKFLOW } from '../../components/info-dialog/workflows';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { Article, FeedSource, VerdictCount, IngestionRun } from '../../models/interfaces';
import { ApiService } from '../../services/api.service';

type SortBy = 'newest' | 'oldest' | 'hits_desc' | 'hits_asc' | 'title' | 'title_desc' | 'feed' | 'feed_desc' | 'country' | 'country_desc';
type SortColumn = 'title' | 'hits' | 'feed' | 'date' | 'country';
// Per column: [first-click sort, second-click sort]. Hits and date default to
// DESC on first click (most-hits / newest first feel natural); title, feed,
// country default to ASC (A-Z).
const COLUMN_PAIRS: Record<SortColumn, [SortBy, SortBy]> = {
  title:   ['title', 'title_desc'],
  hits:    ['hits_desc', 'hits_asc'],
  feed:    ['feed', 'feed_desc'],
  date:    ['newest', 'oldest'],
  country: ['country', 'country_desc'],
};
const DESC_FIRST_COLUMNS: Set<SortColumn> = new Set(['hits', 'date']);

@Component({
  selector: 'app-news-log',
  standalone: true,
  imports: [
    CommonModule, FormsModule, RouterLink,
    MatCardModule, MatButtonModule, MatIconModule, MatFormFieldModule,
    MatInputModule, MatSelectModule, MatChipsModule, MatTooltipModule,
    MatExpansionModule, MatCheckboxModule, MatPaginatorModule,
    MatProgressSpinnerModule, MatProgressBarModule, MatDialogModule, MatSnackBarModule,
  ],
  templateUrl: './news-log.component.html',
  styleUrl: './news-log.component.scss'
})
export class NewsLogComponent implements OnInit, OnDestroy {
  articles: Article[] = [];
  feeds: FeedSource[] = [];
  runs: IngestionRun[] = [];
  summary: VerdictCount[] = [];
  globalKeywords: string[] = [];

  filterFeedId = '';
  filterVerdict = 'All';
  filterRunId = '';
  filterMinHits: number | null = null;
  filterKeywords: string[] = [];
  filterKeywordMode: 'any' | 'all' = 'any';
  filterQuery = '';
  filterDateFrom = '';
  filterDateTo = '';
  filterCountry = '';
  sortBy: SortBy = 'newest';
  deduping = false;

  /** Live progress for the country backfill background job. `null` when no
   * job has been kicked off this session. The poller updates this every 1.5 s
   * until the run reaches a terminal status. */
  backfillRun: {
    runId: string;
    status: 'running' | 'done' | 'warning' | 'error';
    total: number;
    processed: number;
    updated: number;
    stillUnknown: number;
    viaLocation: number;
    viaLlm: number;
    scopeMsg: string;
  } | null = null;
  private backfillPollSub?: Subscription;

  /** Used by the existing template `[disabled]="backfilling"` bindings. */
  get backfilling(): boolean {
    return this.backfillRun?.status === 'running';
  }

  get backfillProgressPct(): number {
    const r = this.backfillRun;
    if (!r || !r.total) return 0;
    return Math.min(100, Math.round((r.processed / r.total) * 100));
  }

  countryOptions: { code: string; label: string; flag?: string }[] = [
    { code: '',         label: 'All countries' },
    { code: 'US',       label: 'United States', flag: '🇺🇸' },
    { code: 'GB',       label: 'United Kingdom', flag: '🇬🇧' },
    { code: 'IN',       label: 'India', flag: '🇮🇳' },
    { code: 'CA',       label: 'Canada', flag: '🇨🇦' },
    { code: 'DE',       label: 'Germany', flag: '🇩🇪' },
    { code: 'FR',       label: 'France', flag: '🇫🇷' },
    { code: 'IL',       label: 'Israel', flag: '🇮🇱' },
    { code: 'SG',       label: 'Singapore', flag: '🇸🇬' },
    { code: 'AU',       label: 'Australia', flag: '🇦🇺' },
    { code: 'NL',       label: 'Netherlands', flag: '🇳🇱' },
    { code: 'IE',       label: 'Ireland', flag: '🇮🇪' },
    { code: 'Other',    label: 'Other' },
    { code: '(empty)',  label: '(not yet tagged)' },
  ];

  countryFlag(code: string): string {
    const opt = this.countryOptions.find(o => o.code === code);
    return opt?.flag || '';
  }

  /** Parsed publish-date for display + sort. Most RSS feeds give us
   * RFC 2822 ("Wed, 22 Apr 2026 13:18:00 GMT") or ISO; both are JS-Date
   * parseable. Falls back to ingest time when the feed didn't supply one
   * (or when parsing fails). */
  articleDate(a: Article): Date {
    const s = (a as any).published;
    if (s) {
      const t = Date.parse(s);
      if (!isNaN(t)) return new Date(t);
    }
    return new Date(a.createdAt);
  }

  pageIndex = 0;
  pageSize = 25;
  pageSizeOptions = [10, 25, 50, 100, 200];

  ingesting = false;
  recentRuns: IngestionRun[] = [];
  expandedRunId: string | null = null;
  runsPanelOpen = false;
  filtersPanelOpen = false;

  /** Count of filters/searches currently narrowing the result set. Shown in
   * the collapsed filter-panel header so the user knows what's hidden. */
  get activeFilterCount(): number {
    let n = 0;
    if (this.filterVerdict && this.filterVerdict !== 'All') n++;
    if (this.filterFeedId) n++;
    if (this.filterRunId) n++;
    if (this.filterMinHits != null && !Number.isNaN(this.filterMinHits)) n++;
    if (this.filterKeywords.length) n++;
    if (this.filterQuery.trim()) n++;
    if (this.filterDateFrom) n++;
    if (this.filterDateTo) n++;
    if (this.filterCountry) n++;
    if (this.sortBy !== 'newest') n++;
    return n;
  }

  selected = new Set<string>();
  busy = false;

  sortOptions: { value: SortBy; label: string }[] = [
    { value: 'newest', label: 'Newest first' },
    { value: 'oldest', label: 'Oldest first' },
    { value: 'hits_desc', label: 'Most keyword hits' },
    { value: 'hits_asc', label: 'Fewest keyword hits' },
    { value: 'title', label: 'Title A→Z' },
    { value: 'title_desc', label: 'Title Z→A' },
    { value: 'feed', label: 'Feed A→Z' },
    { value: 'feed_desc', label: 'Feed Z→A' },
    { value: 'country', label: 'Country A→Z' },
    { value: 'country_desc', label: 'Country Z→A' },
  ];

  get filteredArticles(): Article[] {
    const min = this.filterMinHits ?? null;
    let list = (min === null || Number.isNaN(min))
      ? this.articles
      : this.articles.filter(a => this.totalKeywordHits(a) >= min);

    const sorted = [...list];
    switch (this.sortBy) {
      case 'newest':     sorted.sort((a, b) => +this.articleDate(b) - +this.articleDate(a)); break;
      case 'oldest':     sorted.sort((a, b) => +this.articleDate(a) - +this.articleDate(b)); break;
      case 'hits_desc':  sorted.sort((a, b) => this.totalKeywordHits(b) - this.totalKeywordHits(a)); break;
      case 'hits_asc':   sorted.sort((a, b) => this.totalKeywordHits(a) - this.totalKeywordHits(b)); break;
      case 'title':      sorted.sort((a, b) => (a.title || '').localeCompare(b.title || '')); break;
      case 'title_desc': sorted.sort((a, b) => (b.title || '').localeCompare(a.title || '')); break;
      case 'feed':       sorted.sort((a, b) => (a.feedName || '').localeCompare(b.feedName || '')); break;
      case 'feed_desc':  sorted.sort((a, b) => (b.feedName || '').localeCompare(a.feedName || '')); break;
      case 'country':
        sorted.sort((a, b) => this._cmpCountry(a.country, b.country, true)); break;
      case 'country_desc':
        sorted.sort((a, b) => this._cmpCountry(a.country, b.country, false)); break;
    }
    return sorted;
  }

  /** Articles paginated for table rendering. The full filtered list is what
   * counts for "X of Y" display, paginator length, and bulk select-all. */
  get displayArticles(): Article[] {
    const all = this.filteredArticles;
    const start = this.pageIndex * this.pageSize;
    return all.slice(start, start + this.pageSize);
  }

  onPage(e: PageEvent) {
    this.pageIndex = e.pageIndex;
    this.pageSize = e.pageSize;
  }

  /** Reset to page 0 whenever a filter changes the result-set length. */
  private _resetPage() { this.pageIndex = 0; }

  applySearch() {
    this._resetPage();
    this.load();
  }

  /** Country compare: empty rows always sink to the bottom regardless of asc/desc
   * so untagged articles don't dominate either end of the sort. */
  private _cmpCountry(a: string | undefined, b: string | undefined, asc: boolean): number {
    const x = (a || '').trim();
    const y = (b || '').trim();
    if (!x && !y) return 0;
    if (!x) return 1;
    if (!y) return -1;
    return asc ? x.localeCompare(y) : y.localeCompare(x);
  }

  /** Click-to-sort cycle for a column header. Same column toggles direction. */
  sortByColumn(column: SortColumn) {
    const [asc, desc] = COLUMN_PAIRS[column];
    this.sortBy = this.sortBy === asc ? desc : asc;
  }

  sortIndicator(column: SortColumn): '' | '▲' | '▼' {
    const [first, second] = COLUMN_PAIRS[column];
    // Columns whose "first" pair entry is descending need their arrow flipped
    // so ▼ means "newest/most-first" and ▲ means "oldest/least-first".
    const descFirst = DESC_FIRST_COLUMNS.has(column);
    if (this.sortBy === first) return descFirst ? '▼' : '▲';
    if (this.sortBy === second) return descFirst ? '▲' : '▼';
    return '';
  }

  verdictOptions = [
    'All',
    'pending',
    'funding',
    'not_funding',
    'keyword_filtered',
    'parse_failed',
    'validation_failed',
    'quota_exceeded',
    'service_unavailable',
    'error',
  ];

  constructor(private api: ApiService, private snackBar: MatSnackBar, private dialog: MatDialog) {}

  openInfo() {
    this.dialog.open(InfoDialogComponent, { data: NEWS_LOG_WORKFLOW, width: '880px', maxWidth: '95vw' });
  }

  ngOnInit() {
    this.api.getFeeds().subscribe({ next: (f) => this.feeds = f });
    this.api.getIngestionRuns(20).subscribe({ next: (r) => this.runs = r });
    this.api.getSettings().subscribe({
      next: (s) => this.globalKeywords = s.globalScrapeKeywords || [],
    });
    this.loadRuns();
    this.load();
  }

  loadRuns() {
    this.api.getIngestionRuns(5).subscribe({
      next: (runs) => this.recentRuns = runs,
    });
  }

  runDurationSeconds(run: IngestionRun): number | null {
    if (!run.finishedAt) return null;
    return Math.max(0, Math.round((+new Date(run.finishedAt) - +new Date(run.startedAt)) / 1000));
  }

  runStatusIcon(status: string): string {
    switch (status) {
      case 'ok': return 'check_circle';
      case 'warning': return 'warning';
      case 'error': return 'error';
      case 'running': return 'hourglass_empty';
      default: return 'help_outline';
    }
  }

  runStatusColor(status: string): string {
    switch (status) {
      case 'ok': return '#4caf50';
      case 'warning': return '#ff9800';
      case 'error': return '#f44336';
      case 'running': return '#1976d2';
      default: return '#999';
    }
  }

  ingestNow() {
    this.ingesting = true;
    this.api.triggerIngest().subscribe({
      next: (res: any) => {
        this.ingesting = false;
        this.loadRuns();
        if (res?.runId) {
          this.expandedRunId = res.runId;
          this.runsPanelOpen = true;
        }
        if (res?.status === 'error') {
          this.snackBar.open(res.message || 'Ingestion failed — see details below', 'OK', { duration: 5000 });
          return;
        }
        if (res?.status === 'warning') {
          this.snackBar.open(res.message || 'Nothing ingested', 'OK', { duration: 4000 });
          return;
        }
        const added = res?.totalNewSignals ?? 0;
        const skipped = res?.totalSkipped ?? 0;
        this.snackBar.open(
          `Ingestion complete — ${added} new signal${added === 1 ? '' : 's'}, ${skipped} skipped`,
          'OK', { duration: 4000 }
        );
        this.load();
      },
      error: () => {
        this.ingesting = false;
        this.snackBar.open('Ingestion request failed', 'OK', { duration: 3000 });
      }
    });
  }

  load() {
    this.api.getArticles({
      runId: this.filterRunId || undefined,
      feedId: this.filterFeedId || undefined,
      verdict: this.filterVerdict,
      keyword: this.filterKeywords.length ? this.filterKeywords : undefined,
      keywordMode: this.filterKeywordMode,
      q: this.filterQuery.trim() || undefined,
      dateFrom: this.filterDateFrom || undefined,
      dateTo: this.filterDateTo || undefined,
      country: this.filterCountry || undefined,
      limit: 500,
    }).subscribe({
      next: (data) => {
        this.articles = data;
        this._resetPage();
        // Drop selections for articles no longer present
        const present = new Set(data.map(a => a.id));
        this.selected = new Set([...this.selected].filter(id => present.has(id)));
      },
      error: () => this.snackBar.open('Failed to load articles', 'OK', { duration: 3000 })
    });
    this.api.getVerdictSummary(this.filterRunId || undefined).subscribe({
      next: (data) => this.summary = data,
    });
  }

  toggleSelected(id: string, checked: boolean) {
    if (checked) this.selected.add(id);
    else this.selected.delete(id);
  }

  isSelected(id: string): boolean { return this.selected.has(id); }

  toggleSelectAll() {
    if (this.allVisibleSelected) {
      this.articles.forEach(a => this.selected.delete(a.id));
    } else {
      this.articles.forEach(a => this.selected.add(a.id));
    }
  }

  get allVisibleSelected(): boolean {
    return this.articles.length > 0 && this.articles.every(a => this.selected.has(a.id));
  }

  get someVisibleSelected(): boolean {
    return !this.allVisibleSelected && this.articles.some(a => this.selected.has(a.id));
  }

  get selectedCount(): number { return this.selected.size; }

  get pendingCount(): number {
    return this.summary.find(s => s.verdict === 'pending')?.count ?? 0;
  }

  extractSelected(force = false) {
    if (this.selected.size === 0) return;
    if (force && !confirm(`Re-extract ${this.selected.size} article(s) — this deletes any existing Signal rows for the same URLs and reruns the LLM with the current prompt. Continue?`)) return;
    this.busy = true;
    this.api.extractArticles({ ids: [...this.selected], force }).subscribe({
      next: (res) => {
        this.busy = false;
        this.snackBar.open(this._extractMessage(res), 'OK', { duration: 5000 });
        this.selected.clear();
        this.load();
      },
      error: () => { this.busy = false; this.snackBar.open('Extraction failed', 'OK', { duration: 3000 }); }
    });
  }

  extractAllPending() {
    this.busy = true;
    this.api.extractArticles({ allPending: true }).subscribe({
      next: (res) => {
        this.busy = false;
        this.snackBar.open(this._extractMessage(res), 'OK', { duration: 5000 });
        this.load();
      },
      error: () => { this.busy = false; this.snackBar.open('Extraction failed', 'OK', { duration: 3000 }); }
    });
  }

  extractOne(article: Article, force = false) {
    this.busy = true;
    this.api.extractArticles({ ids: [article.id], force }).subscribe({
      next: (res) => {
        this.busy = false;
        this.snackBar.open(this._extractMessage(res), 'OK', { duration: 4000 });
        this.load();
      },
      error: () => { this.busy = false; this.snackBar.open('Extraction failed', 'OK', { duration: 3000 }); }
    });
  }

  private _extractMessage(res: any): string {
    if (res?.status === 'warning' && res?.message) return res.message;
    const c = res?.counts || {};
    const parts: string[] = [];
    if (c.funding) parts.push(`${c.funding} signal${c.funding === 1 ? '' : 's'}`);
    if (c.not_funding) parts.push(`${c.not_funding} not-funding`);
    if (c.parse_failed) parts.push(`${c.parse_failed} parse-failed`);
    if (c.validation_failed) parts.push(`${c.validation_failed} validation-failed`);
    if (c.error) parts.push(`${c.error} error`);
    return parts.length ? `Extracted: ${parts.join(', ')}` : 'No articles extracted';
  }

  deleteSelected() {
    if (this.selected.size === 0) return;
    if (!confirm(`Delete ${this.selected.size} selected article${this.selected.size === 1 ? '' : 's'}?`)) return;
    this.busy = true;
    const ids = [...this.selected];
    this.api.deleteArticlesBatch(ids).subscribe({
      next: (res) => {
        this.busy = false;
        this.snackBar.open(`Deleted ${res?.deleted ?? 0} article${(res?.deleted ?? 0) === 1 ? '' : 's'}`, 'OK', { duration: 3000 });
        this.selected.clear();
        this.load();
      },
      error: () => { this.busy = false; this.snackBar.open('Delete failed', 'OK', { duration: 3000 }); }
    });
  }

  deleteOne(article: Article) {
    if (!confirm(`Delete article "${article.title.slice(0, 60)}"?`)) return;
    this.api.deleteArticle(article.id).subscribe({
      next: () => {
        this.articles = this.articles.filter(a => a.id !== article.id);
        this.selected.delete(article.id);
        this.snackBar.open('Article deleted', 'OK', { duration: 2000 });
      },
      error: () => this.snackBar.open('Delete failed', 'OK', { duration: 3000 })
    });
  }

  clearFilters() {
    this.filterFeedId = '';
    this.filterVerdict = 'All';
    this.filterRunId = '';
    this.filterMinHits = null;
    this.filterKeywords = [];
    this.filterKeywordMode = 'any';
    this.filterQuery = '';
    this.filterDateFrom = '';
    this.filterDateTo = '';
    this.filterCountry = '';
    this.sortBy = 'newest';
    this._resetPage();
    this.load();
  }

  backfillCountries() {
    if (this.backfilling) return;
    const ids = Array.from(this.selected);
    const opts = ids.length > 0 ? { articleIds: ids } : { limit: 100 };
    const scopeMsg = ids.length > 0
      ? `${ids.length} selected article${ids.length === 1 ? '' : 's'}`
      : 'up to 100 untagged articles';
    this.api.backfillArticleCountries(opts).subscribe({
      next: (res) => {
        if (!res.runId || res.status === 'noop' || res.total === 0) {
          this.snackBar.open('No articles to process — all targeted rows are already tagged.', 'OK', { duration: 3000 });
          return;
        }
        this.backfillRun = {
          runId: res.runId,
          status: 'running',
          total: res.total,
          processed: 0,
          updated: 0,
          stillUnknown: 0,
          viaLocation: 0,
          viaLlm: 0,
          scopeMsg,
        };
        this._startBackfillPoll(res.runId);
      },
      error: (err) => {
        const msg = err?.error?.detail || 'Country backfill failed to start';
        this.snackBar.open(msg, 'OK', { duration: 4000 });
      }
    });
  }

  private _startBackfillPoll(runId: string) {
    this.backfillPollSub?.unsubscribe();
    this.backfillPollSub = interval(1500)
      .pipe(switchMap(() => this.api.getBackfillRun(runId)))
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
            viaLocation: run.viaLocation,
            viaLlm: run.viaLlm,
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
      ? `Country backfill (${r.scopeMsg}): processed ${r.processed}/${r.total}, updated ${r.updated}, still unknown ${r.stillUnknown}` + (message ? ` — ${message}` : '')
      : `Country backfill ${status} after ${r.processed}/${r.total} — ${message || 'see Recent Runs'}`;
    this.snackBar.open(headline, 'OK', { duration: 6000 });
    this.backfillRun = null;
    this.load();
  }

  ngOnDestroy() {
    this.backfillPollSub?.unsubscribe();
  }

  dedupeArticles() {
    if (this.deduping) return;
    this.deduping = true;
    this.api.dedupeArticles(true).subscribe({
      next: (preview) => {
        if (preview.deleted === 0) {
          this.deduping = false;
          this.snackBar.open('No duplicates found in News Log.', 'OK', { duration: 3000 });
          return;
        }
        const ref = this.snackBar.open(
          `Found ${preview.groupsWithDupes} duplicate group${preview.groupsWithDupes === 1 ? '' : 's'} — would delete ${preview.deleted} row${preview.deleted === 1 ? '' : 's'}.`,
          'Delete',
          { duration: 8000 }
        );
        let confirmed = false;
        ref.onAction().subscribe(() => {
          confirmed = true;
          this.api.dedupeArticles(false).subscribe({
            next: (res) => {
              this.deduping = false;
              this.snackBar.open(`Deduped ${res.deleted} row${res.deleted === 1 ? '' : 's'} across ${res.groupsWithDupes} group${res.groupsWithDupes === 1 ? '' : 's'}.`, 'OK', { duration: 4000 });
              this.load();
            },
            error: (err) => {
              this.deduping = false;
              const msg = err?.error?.detail || 'Dedupe failed';
              this.snackBar.open(msg, 'OK', { duration: 4000 });
            }
          });
        });
        ref.afterDismissed().subscribe(() => {
          if (!confirmed) this.deduping = false;
        });
      },
      error: (err) => {
        this.deduping = false;
        const msg = err?.error?.detail || 'Dedupe preview failed';
        this.snackBar.open(msg, 'OK', { duration: 4000 });
      }
    });
  }

  isKeywordActive(kw: string): boolean {
    return this.filterKeywords.includes(kw);
  }

  toggleKeywordFilter(kw: string) {
    const idx = this.filterKeywords.indexOf(kw);
    if (idx > -1) this.filterKeywords.splice(idx, 1);
    else this.filterKeywords.push(kw);
    this.load();
  }

  setKeywordMode(mode: 'any' | 'all') {
    if (this.filterKeywordMode === mode) return;
    this.filterKeywordMode = mode;
    if (this.filterKeywords.length) this.load();
  }

  rescoreKeywords() {
    this.busy = true;
    this.api.rescoreArticleKeywords().subscribe({
      next: (res) => {
        this.busy = false;
        this.snackBar.open(
          `Rescored ${res.updated} of ${res.total} article(s) against current global keywords`,
          'OK', { duration: 4000 },
        );
        this.load();
      },
      error: () => {
        this.busy = false;
        this.snackBar.open('Rescore failed', 'OK', { duration: 3000 });
      },
    });
  }

  keywordSetStale(a: Article): boolean {
    if (!this.globalKeywords.length) return false;
    const existing = new Set(Object.keys(a.keywordHits || {}).map(k => k.toLowerCase()));
    const expected = this.globalKeywords.map(k => k.toLowerCase());
    return expected.some(k => !existing.has(k));
  }

  feedKeywords(feedId: string | null): string[] {
    if (!feedId) return [];
    return this.feeds.find(f => f.id === feedId)?.keywords ?? [];
  }

  verdictColor(v: string): string {
    switch (v) {
      case 'pending': return '#1976d2';
      case 'funding': return '#4caf50';
      case 'not_funding': return '#9e9e9e';
      case 'keyword_filtered': return '#90a4ae';
      case 'parse_failed': return '#ff9800';
      case 'validation_failed': return '#ff9800';
      case 'quota_exceeded': return '#f44336';
      case 'service_unavailable': return '#e65100';
      case 'error': return '#f44336';
      default: return '#999';
    }
  }

  verdictIcon(v: string): string {
    switch (v) {
      case 'pending': return 'hourglass_empty';
      case 'funding': return 'check_circle';
      case 'not_funding': return 'block';
      case 'keyword_filtered': return 'filter_alt_off';
      case 'parse_failed': return 'broken_image';
      case 'validation_failed': return 'rule';
      case 'quota_exceeded': return 'speed';
      case 'service_unavailable': return 'cloud_off';
      case 'error': return 'error';
      default: return 'help_outline';
    }
  }

  totalKeywordHits(a: Article): number {
    if (!a.keywordHits) return 0;
    return Object.values(a.keywordHits).reduce((acc, n) => acc + (n || 0), 0);
  }

  keywordHitList(a: Article): { keyword: string; count: number }[] {
    if (!a.keywordHits) return [];
    return Object.entries(a.keywordHits)
      .map(([keyword, count]) => ({ keyword, count }))
      .sort((x, y) => y.count - x.count);
  }

  verdictDescription(v: string): string {
    switch (v) {
      case 'pending': return 'Scraped but not yet sent to the LLM. Click Extract to process.';
      case 'funding': return 'LLM extracted a valid funding signal';
      case 'not_funding': return 'LLM determined this article is not about funding';
      case 'keyword_filtered': return 'Skipped — title/summary matched none of the feed\'s keywords';
      case 'parse_failed': return 'LLM response was not valid JSON';
      case 'validation_failed': return 'LLM returned data missing required fields';
      case 'quota_exceeded': return 'Hit LLM quota limit before processing this article';
      case 'service_unavailable': return 'LLM returned 5xx after retries — usually a brief demand spike. Retry later.';
      case 'error': return 'Other extraction error (network, fetch, etc.)';
      default: return v;
    }
  }
}
