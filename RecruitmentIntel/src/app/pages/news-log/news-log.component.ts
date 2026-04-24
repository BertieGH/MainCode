import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { Article, FeedSource, VerdictCount, IngestionRun } from '../../models/interfaces';
import { ApiService } from '../../services/api.service';

type SortBy = 'newest' | 'oldest' | 'hits_desc' | 'hits_asc' | 'title' | 'title_desc' | 'feed' | 'feed_desc';
type SortColumn = 'title' | 'hits' | 'feed';
const COLUMN_PAIRS: Record<SortColumn, [SortBy, SortBy]> = {
  title: ['title', 'title_desc'],
  hits:  ['hits_desc', 'hits_asc'],
  feed:  ['feed', 'feed_desc'],
};

@Component({
  selector: 'app-news-log',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    MatCardModule, MatButtonModule, MatIconModule, MatFormFieldModule,
    MatSelectModule, MatChipsModule, MatTooltipModule, MatExpansionModule,
    MatCheckboxModule, MatSnackBarModule,
  ],
  templateUrl: './news-log.component.html',
  styleUrl: './news-log.component.scss'
})
export class NewsLogComponent implements OnInit {
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
  sortBy: SortBy = 'newest';

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
  ];

  get displayArticles(): Article[] {
    const min = this.filterMinHits ?? null;
    let list = (min === null || Number.isNaN(min))
      ? this.articles
      : this.articles.filter(a => this.totalKeywordHits(a) >= min);

    const sorted = [...list];
    switch (this.sortBy) {
      case 'newest':     sorted.sort((a, b) => +new Date(b.createdAt) - +new Date(a.createdAt)); break;
      case 'oldest':     sorted.sort((a, b) => +new Date(a.createdAt) - +new Date(b.createdAt)); break;
      case 'hits_desc':  sorted.sort((a, b) => this.totalKeywordHits(b) - this.totalKeywordHits(a)); break;
      case 'hits_asc':   sorted.sort((a, b) => this.totalKeywordHits(a) - this.totalKeywordHits(b)); break;
      case 'title':      sorted.sort((a, b) => (a.title || '').localeCompare(b.title || '')); break;
      case 'title_desc': sorted.sort((a, b) => (b.title || '').localeCompare(a.title || '')); break;
      case 'feed':       sorted.sort((a, b) => (a.feedName || '').localeCompare(b.feedName || '')); break;
      case 'feed_desc':  sorted.sort((a, b) => (b.feedName || '').localeCompare(a.feedName || '')); break;
    }
    return sorted;
  }

  /** Click-to-sort cycle for a column header. Same column toggles direction. */
  sortByColumn(column: SortColumn) {
    const [asc, desc] = COLUMN_PAIRS[column];
    this.sortBy = this.sortBy === asc ? desc : asc;
  }

  sortIndicator(column: SortColumn): '' | '▲' | '▼' {
    const [first, second] = COLUMN_PAIRS[column];
    // For 'hits' the "first" entry is descending (most hits first), so flip the arrow.
    if (this.sortBy === first) return column === 'hits' ? '▼' : '▲';
    if (this.sortBy === second) return column === 'hits' ? '▲' : '▼';
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

  constructor(private api: ApiService, private snackBar: MatSnackBar) {}

  ngOnInit() {
    this.api.getFeeds().subscribe({ next: (f) => this.feeds = f });
    this.api.getIngestionRuns(20).subscribe({ next: (r) => this.runs = r });
    this.api.getSettings().subscribe({
      next: (s) => this.globalKeywords = s.globalScrapeKeywords || [],
    });
    this.load();
  }

  load() {
    this.api.getArticles({
      runId: this.filterRunId || undefined,
      feedId: this.filterFeedId || undefined,
      verdict: this.filterVerdict,
      keyword: this.filterKeywords.length ? this.filterKeywords : undefined,
      keywordMode: this.filterKeywordMode,
      limit: 200,
    }).subscribe({
      next: (data) => {
        this.articles = data;
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
    this.sortBy = 'newest';
    this.load();
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
