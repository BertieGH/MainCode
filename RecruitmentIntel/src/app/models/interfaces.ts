export interface Signal {
  id: string;
  companyName: string;
  industry: string;
  fundingRound: string;
  amount: number;
  location: string;
  date: string;
  sourceUrl: string;
  sourceTitle: string;
  createdAt: string;
}

export interface ProspectList {
  id: string;
  name: string;
  description: string;
  companyCount: number;
  enrichedCount: number;
  jobsCrawledCount: number;
  totalJobs: number;
  createdAt: string;
  updatedAt: string;
}

export interface Prospect {
  id: string;
  listId: string;
  signalId: string;
  companyName: string;
  industry: string;
  fundingRound: string;
  amount: number;
  location: string;
  website: string | null;
  linkedinUrl: string | null;
  careersUrl: string | null;
  enrichmentStatus: 'pending' | 'done' | 'failed' | 'not_started';
  enrichmentStrategy: string | null;
  enrichmentError: string | null;
  jobCrawlStatus: 'pending' | 'done' | 'empty' | 'failed' | 'not_started';
  jobCrawlStrategy: string | null;
  jobCrawlRawCount: number;
  jobCrawlError: string | null;
  jobCount: number;
  createdAt: string;
}

export interface SkippedSignal {
  signalId: string;
  companyName: string;
  reason: 'dup_signal' | 'dup_company_in_list' | 'dup_company_in_batch';
}

export interface AddSignalsResult {
  added: Prospect[];
  skipped: SkippedSignal[];
}

export interface Job {
  id: string;
  prospectId: string;
  listId: string;
  companyName: string;
  title: string;
  department: string;
  seniority: string;
  jobType: string;
  location: string;
  url: string;
  skills: string[];
  matchTarget: string | null;
  discoveredAt: string;
  linkedinUrl?: string | null;
  website?: string | null;
}

export interface FeedSource {
  id: string;
  name: string;
  url: string;
  feedType: string;
  keywords: string[];
  isActive: boolean;
  lastFetched: string | null;
}

export interface Article {
  id: string;
  ingestionRunId: string | null;
  feedSourceId: string | null;
  feedName: string;
  url: string;
  title: string;
  summary: string | null;
  published: string | null;
  verdict: 'funding' | 'not_funding' | 'keyword_filtered' | 'parse_failed' | 'validation_failed' | 'quota_exceeded' | 'service_unavailable' | 'error' | 'pending';
  llmResponse: string | null;
  signalId: string | null;
  keywordHits: { [keyword: string]: number };
  country: string;
  createdAt: string;
}

export interface VerdictCount {
  verdict: string;
  count: number;
}

export interface IngestionRunFeed {
  feed: string;
  articles: number;
  newArticles?: number;
  newSignals: number;
}

export interface IngestionRun {
  id: string;
  startedAt: string;
  finishedAt: string | null;
  status: 'running' | 'ok' | 'warning' | 'error';
  totalNewSignals: number;
  totalSkipped: number;
  feedResults: IngestionRunFeed[];
  message: string | null;
  trigger: 'manual' | 'scheduled';
}

export interface ExtractionProfile {
  id: string;
  name: string;
  extractionPrompt: string;
  scrapeKeywords: string[];
  createdAt: string;
  updatedAt: string;
}

export interface AppSettings {
  llmProvider: 'gemini' | 'ollama';
  geminiApiKey: string;
  geminiModel: string;
  geminiPaidApiKey: string;
  geminiTier: 'free' | 'paid';
  ollamaHost: string;
  ollamaModel: string;
  fetchIntervalHours: number;
  articlesPerFeedLimit: number;
  autoExtractOnIngest: boolean;
  globalScrapeKeywords: string[];
  extractionPrompt: string;
  llmArticleCharBudget: number;
  careerPatterns: string[];
  fallbackGoogle: boolean;
  fallbackLinkedin: boolean;
  atsDetection: string[];
  jobTargetTitles: string[];
  jobMaxListingPages: number;
  jobMaxSubcategoryPages: number;
  jobExtractPrompt: string;
  jobMatchPrompt: string;
  jobClassifyPrompt: string;
}

export interface JobPromptProfile {
  id: string;
  name: string;
  extractPrompt: string;
  matchPrompt: string;
  classifyPrompt: string;
  createdAt: string;
  updatedAt: string;
}
