import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable, map } from 'rxjs';
import { Signal, ProspectList, Prospect, Job, FeedSource, AppSettings, IngestionRun, Article, VerdictCount, ExtractionProfile, JobPromptProfile, AddSignalsResult } from '../models/interfaces';

const BASE = 'http://localhost:8002/api';

/** Convert snake_case keys to camelCase */
function toCamel(obj: any): any {
  if (Array.isArray(obj)) return obj.map(toCamel);
  if (obj !== null && typeof obj === 'object') {
    return Object.keys(obj).reduce((acc: any, key) => {
      const camel = key.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
      acc[camel] = toCamel(obj[key]);
      return acc;
    }, {});
  }
  return obj;
}

/** Convert camelCase keys to snake_case */
function toSnake(obj: any): any {
  if (Array.isArray(obj)) return obj.map(toSnake);
  if (obj !== null && typeof obj === 'object') {
    return Object.keys(obj).reduce((acc: any, key) => {
      const snake = key.replace(/[A-Z]/g, c => '_' + c.toLowerCase());
      acc[snake] = toSnake(obj[key]);
      return acc;
    }, {});
  }
  return obj;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  constructor(private http: HttpClient) {}

  // --- Signals ---
  getSignals(filters?: any): Observable<Signal[]> {
    // Fetch the full filtered set (up to backend ceiling 2000) and paginate
    // client-side. Matches the News Log pattern.
    let params = new HttpParams().set('limit', '2000');
    if (filters) {
      Object.entries(filters).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== '' && v !== 'All') {
          params = params.set(k, String(v));
        }
      });
    }
    return this.http.get<any[]>(`${BASE}/signals`, { params }).pipe(map(toCamel));
  }

  getSignalStats(): Observable<any> {
    return this.http.get<any>(`${BASE}/signals/stats/summary`).pipe(map(toCamel));
  }

  triggerIngest(): Observable<any> {
    return this.http.post<any>(`${BASE}/signals/ingest`, {}).pipe(map(toCamel));
  }

  deleteSignal(id: string): Observable<any> {
    return this.http.delete(`${BASE}/signals/${id}`);
  }

  bulkDeleteSignals(ids: string[]): Observable<{ deleted: number }> {
    return this.http.post<{ deleted: number }>(`${BASE}/signals/bulk-delete`, { ids });
  }

  getIngestionRuns(limit = 10): Observable<IngestionRun[]> {
    return this.http.get<any[]>(`${BASE}/ingestion-runs`, { params: { limit } }).pipe(map(toCamel));
  }

  getArticles(filters?: {
    runId?: string; feedId?: string; verdict?: string;
    keyword?: string[]; keywordMode?: 'any' | 'all';
    q?: string; dateFrom?: string; dateTo?: string;
    country?: string;
    limit?: number; offset?: number;
  }): Observable<Article[]> {
    let params = new HttpParams();
    if (filters?.runId) params = params.set('run_id', filters.runId);
    if (filters?.feedId) params = params.set('feed_id', filters.feedId);
    if (filters?.verdict && filters.verdict !== 'All') params = params.set('verdict', filters.verdict);
    if (filters?.keyword && filters.keyword.length) {
      for (const k of filters.keyword) params = params.append('keyword', k);
    }
    if (filters?.keywordMode) params = params.set('keyword_mode', filters.keywordMode);
    if (filters?.q) params = params.set('q', filters.q);
    if (filters?.dateFrom) params = params.set('date_from', filters.dateFrom);
    if (filters?.dateTo) params = params.set('date_to', filters.dateTo);
    if (filters?.country) params = params.set('country', filters.country);
    if (filters?.limit !== undefined) params = params.set('limit', String(filters.limit));
    if (filters?.offset !== undefined) params = params.set('offset', String(filters.offset));
    return this.http.get<any[]>(`${BASE}/articles`, { params }).pipe(map(toCamel));
  }

  rescoreArticleKeywords(): Observable<{ status: string; updated: number; total: number }> {
    return this.http.post<any>(`${BASE}/articles/rescore-keywords`, {}).pipe(map(toCamel));
  }

  backfillArticleCountries(opts: { limit?: number; articleIds?: string[] } = {}): Observable<{ runId: string | null; status: string; total: number }> {
    const body: any = {};
    if (opts.articleIds && opts.articleIds.length) body.article_ids = opts.articleIds;
    else body.limit = opts.limit ?? 100;
    return this.http.post<any>(`${BASE}/articles/backfill-countries`, body).pipe(map(toCamel));
  }

  getBackfillRun(runId: string): Observable<{
    id: string; kind: string; startedAt: string; finishedAt: string | null;
    status: string; total: number; processed: number; updated: number;
    stillUnknown: number; viaLocation: number; viaLlm: number;
    message: string | null; trigger: string;
  }> {
    return this.http.get<any>(`${BASE}/articles/backfill-runs/${runId}`).pipe(map(toCamel));
  }

  dedupeArticles(dryRun: boolean): Observable<{ groupsWithDupes: number; kept: number; deleted: number; dryRun: boolean }> {
    return this.http.post<any>(`${BASE}/articles/dedupe`, { dry_run: dryRun }).pipe(map(toCamel));
  }

  getVerdictSummary(runId?: string): Observable<VerdictCount[]> {
    let params = new HttpParams();
    if (runId) params = params.set('run_id', runId);
    return this.http.get<any[]>(`${BASE}/articles/verdict-summary`, { params });
  }

  deleteArticle(id: string): Observable<any> {
    return this.http.delete(`${BASE}/articles/${id}`);
  }

  deleteArticlesBatch(ids: string[]): Observable<any> {
    return this.http.post<any>(`${BASE}/articles/delete-batch`, { article_ids: ids });
  }

  extractArticles(opts: { ids?: string[]; allPending?: boolean; force?: boolean }): Observable<{ runId: string | null; status: string; total: number }> {
    const body: any = {};
    if (opts.ids) body.article_ids = opts.ids;
    if (opts.allPending) body.all_pending = true;
    if (opts.force) body.force = true;
    return this.http.post<any>(`${BASE}/articles/extract`, body).pipe(map(toCamel));
  }

  backfillSignalLocations(opts: { limit?: number; signalIds?: string[] } = {}): Observable<{ runId: string | null; status: string; total: number }> {
    const body: any = {};
    if (opts.signalIds && opts.signalIds.length) body.signal_ids = opts.signalIds;
    else body.limit = opts.limit ?? 100;
    return this.http.post<any>(`${BASE}/signals/backfill-locations`, body).pipe(map(toCamel));
  }

  getSignalBackfillRun(runId: string): Observable<{
    id: string; kind: string; startedAt: string; finishedAt: string | null;
    status: string; total: number; processed: number; updated: number;
    stillUnknown: number; viaLocation: number; viaLlm: number;
    message: string | null; trigger: string;
  }> {
    return this.http.get<any>(`${BASE}/signals/backfill-runs/${runId}`).pipe(map(toCamel));
  }

  getExtractionRun(runId: string): Observable<{
    id: string; status: string; total: number; processed: number;
    funding: number; notFunding: number; parseFailed: number; validationFailed: number;
    serviceUnavailable: number; error: number;
    message: string | null; startedAt: string; finishedAt: string | null; force: boolean;
  }> {
    return this.http.get<any>(`${BASE}/articles/extract-runs/${runId}`).pipe(map(toCamel));
  }

  // --- Prospect Lists ---
  getProspectLists(): Observable<ProspectList[]> {
    return this.http.get<any[]>(`${BASE}/prospect-lists`).pipe(map(toCamel));
  }

  createProspectList(name: string, description: string): Observable<ProspectList> {
    return this.http.post<any>(`${BASE}/prospect-lists`, { name, description }).pipe(map(toCamel));
  }

  deleteProspectList(id: string): Observable<any> {
    return this.http.delete(`${BASE}/prospect-lists/${id}`);
  }

  getProspectList(id: string): Observable<ProspectList> {
    return this.http.get<any>(`${BASE}/prospect-lists/${id}`).pipe(map(toCamel));
  }

  // --- Prospects ---
  getProspects(listId: string): Observable<Prospect[]> {
    return this.http.get<any[]>(`${BASE}/prospect-lists/${listId}/prospects`).pipe(map(toCamel));
  }

  addSignalsToList(listId: string, signalIds: string[]): Observable<AddSignalsResult> {
    return this.http.post<any>(`${BASE}/prospect-lists/${listId}/add`, { signal_ids: signalIds }).pipe(map(toCamel));
  }

  removeProspect(listId: string, prospectId: string): Observable<any> {
    return this.http.delete(`${BASE}/prospect-lists/${listId}/prospects/${prospectId}`);
  }

  // --- Enrichment ---
  enrichList(listId: string, force = false, prospectIds?: string[]): Observable<any> {
    // Endpoint now takes a JSON body { force, prospect_ids? }. Empty array
    // omitted so the backend treats it as "whole list".
    const body: any = { force };
    if (prospectIds && prospectIds.length) body.prospect_ids = prospectIds;
    return this.http.post<any>(`${BASE}/prospect-lists/${listId}/enrich`, body);
  }

  enrichProspect(prospectId: string): Observable<any> {
    return this.http.post<any>(`${BASE}/prospects/${prospectId}/enrich`, {}).pipe(map(toCamel));
  }

  // --- Job Crawl ---
  crawlJobsForList(listId: string, force = false, prospectIds?: string[]): Observable<any> {
    const body: any = { force };
    if (prospectIds && prospectIds.length) body.prospect_ids = prospectIds;
    return this.http.post<any>(`${BASE}/prospect-lists/${listId}/crawl-jobs`, body);
  }

  crawlJobsForProspect(prospectId: string, force = false): Observable<any> {
    const params = force ? new HttpParams().set('force', 'true') : undefined;
    return this.http.post<any>(`${BASE}/prospects/${prospectId}/crawl-jobs`, {}, { params }).pipe(map(toCamel));
  }

  // --- Outreach ---
  getOutreach(listId: string, filters?: any): Observable<Job[]> {
    let params = new HttpParams();
    if (filters) {
      Object.entries(filters).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== '' && v !== 'All') {
          params = params.set(k, String(v));
        }
      });
    }
    return this.http.get<any[]>(`${BASE}/outreach/${listId}`, { params }).pipe(map(toCamel));
  }

  getOutreachSummary(listId: string): Observable<{ department: string; count: number }[]> {
    return this.http.get<any[]>(`${BASE}/outreach/${listId}/summary`);
  }

  exportOutreachCsv(listId: string, filters?: any): string {
    let params = '';
    if (filters) {
      const parts = Object.entries(filters)
        .filter(([_, v]) => v !== undefined && v !== null && v !== '' && v !== 'All')
        .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
      if (parts.length) params = '?' + parts.join('&');
    }
    return `${BASE}/outreach/${listId}/export${params}`;
  }

  // --- Feeds ---
  getFeeds(): Observable<FeedSource[]> {
    return this.http.get<any[]>(`${BASE}/feeds`).pipe(map(toCamel));
  }

  createFeed(data: any): Observable<FeedSource> {
    return this.http.post<any>(`${BASE}/feeds`, toSnake(data)).pipe(map(toCamel));
  }

  updateFeed(id: string, data: any): Observable<FeedSource> {
    return this.http.put<any>(`${BASE}/feeds/${id}`, toSnake(data)).pipe(map(toCamel));
  }

  deleteFeed(id: string): Observable<any> {
    return this.http.delete(`${BASE}/feeds/${id}`);
  }

  addSuggestedFeeds(): Observable<FeedSource[]> {
    return this.http.post<any[]>(`${BASE}/feeds/suggested/add-all`, {}).pipe(map(toCamel));
  }

  // --- Settings ---
  getSettings(): Observable<AppSettings> {
    return this.http.get<any>(`${BASE}/settings`).pipe(map(toCamel));
  }

  updateSettings(data: Partial<AppSettings>): Observable<AppSettings> {
    return this.http.put<any>(`${BASE}/settings`, toSnake(data)).pipe(map(toCamel));
  }

  testConnection(): Observable<any> {
    return this.http.post<any>(`${BASE}/settings/test-connection`, {});
  }

  // --- Extraction Profiles ---
  getExtractionProfiles(): Observable<ExtractionProfile[]> {
    return this.http.get<any[]>(`${BASE}/extraction-profiles`).pipe(map(toCamel));
  }

  createExtractionProfile(data: { name: string; extractionPrompt: string; scrapeKeywords: string[] }): Observable<ExtractionProfile> {
    return this.http.post<any>(`${BASE}/extraction-profiles`, toSnake(data)).pipe(map(toCamel));
  }

  updateExtractionProfile(id: string, data: Partial<{ name: string; extractionPrompt: string; scrapeKeywords: string[] }>): Observable<ExtractionProfile> {
    return this.http.put<any>(`${BASE}/extraction-profiles/${id}`, toSnake(data)).pipe(map(toCamel));
  }

  deleteExtractionProfile(id: string): Observable<any> {
    return this.http.delete(`${BASE}/extraction-profiles/${id}`);
  }

  // --- Job Prompt Profiles ---
  getJobPromptProfiles(): Observable<JobPromptProfile[]> {
    return this.http.get<any[]>(`${BASE}/job-prompt-profiles`).pipe(map(toCamel));
  }

  createJobPromptProfile(data: { name: string; extractPrompt: string; matchPrompt: string; classifyPrompt: string }): Observable<JobPromptProfile> {
    return this.http.post<any>(`${BASE}/job-prompt-profiles`, toSnake(data)).pipe(map(toCamel));
  }

  updateJobPromptProfile(id: string, data: Partial<{ name: string; extractPrompt: string; matchPrompt: string; classifyPrompt: string }>): Observable<JobPromptProfile> {
    return this.http.put<any>(`${BASE}/job-prompt-profiles/${id}`, toSnake(data)).pipe(map(toCamel));
  }

  deleteJobPromptProfile(id: string): Observable<any> {
    return this.http.delete(`${BASE}/job-prompt-profiles/${id}`);
  }
}
