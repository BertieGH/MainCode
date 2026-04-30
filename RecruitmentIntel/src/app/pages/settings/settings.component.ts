import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatRadioModule } from '@angular/material/radio';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatDividerModule } from '@angular/material/divider';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { AppSettings, ExtractionProfile, JobPromptProfile } from '../../models/interfaces';
import { ApiService } from '../../services/api.service';

const DEFAULT_FUNDING_KEYWORDS = ['funding', 'raised', 'series', 'seed', 'round', 'investment'];

const DEFAULT_EXTRACTION_PROMPT = `You are extracting structured funding data from a news article.
Read the FULL article carefully — do not stop at the title or first sentence.

Your bias: if the article clearly describes a company raising money, ALWAYS
extract it. Don't reject a real funding story just because one field is uncertain
— partial data is better than no data.

Return ONLY a valid JSON object with these fields:

- company_name: The FULL official name of the company that raised funding, as
  written in the article body. Prefer the long form (e.g. "Anthropic PBC",
  "OpenAI, Inc.", "Stripe, Inc."), not the stock ticker, abbreviation, or bare
  domain. If the article describes a parent/subsidiary relationship, use the
  entity that actually received the funding. If only a short form is given
  (e.g. just "Stripe"), use that — do NOT return is_funding: false for this.

- funding_round: Exactly one of: Pre-Seed, Seed, Series A, Series B, Series C,
  Series D, Growth, Other. Use "Other" if the article mentions funding but the
  round type is unclear (bridge, extension, strategic, debt, etc.).

- amount: The funding amount in USD as a plain integer (e.g. 5000000 for $5M,
  120000000 for $120M). Convert from other currencies if mentioned. Use 0 if
  the article doesn't state an amount — still extract the signal.

- industry: Exactly one of: AI, Fintech, SaaS, Cybersecurity, HealthTech, EdTech,
  CleanTech, Other. Pick the closest match based on the company's product, not the
  investor's focus. Use "Other" if unclear.

- location: The company's HEADQUARTERS as the most specific format available.
  Prefer "City, State/Region, Country" (e.g. "San Francisco, CA, USA",
  "London, England, UK", "Bengaluru, Karnataka, India", "Berlin, Germany").
  Look in the article body for phrases like "based in", "headquartered in",
  "{{city}}-based startup", or a dateline. Do NOT use the investor's location
  or the article publisher's location. If the article doesn't mention a location,
  return an empty string "" — do NOT reject the article for this.

- date: YYYY-MM-DD. The date THIS specific funding round was announced — i.e.
  the news event the article is reporting. Many articles also mention the
  company's PREVIOUS funding rounds for context (e.g. "had previously raised
  $30M Series A in May 2024"); IGNORE those — they are NOT what's being
  announced now.
  Resolution order:
    1. An explicit dateline / "announced today, {{date}}" / press-release date
       at the TOP of the article that refers to THIS round.
    2. The article's published date (provided below as \`published_date\`).
    3. Today's date as a last resort.
  Never return a date older than the article's published date — that's a
  historical mention, not the current announcement.

ONLY return {{"is_funding": false}} when the article is genuinely not about a
company raising investment capital — e.g. product launches, acquisitions, hires,
opinion pieces, earnings reports, or new VC fund-vehicle launches (where a VC
firm raises a fund, not a startup raising from VCs). If there is ANY funding
announcement in the article, extract it.

Article title: {title}
Article published_date (from the RSS feed — usually within ±2 days of the actual
announcement): {published}
Article text: {text}

Return ONLY the JSON object — no markdown fences, no explanation, no preamble.`;

const DEFAULT_JOB_EXTRACT_PROMPT = `You are looking at the page at: {base_url}
Decide whether this page is actually a list of open job positions.
If it's a marketing page, blog post, About page, or just a single job posting, treat it as NOT a job listings page.

Page text:
{page_text}

Return ONLY a JSON object with shape:
{"is_job_listings_page": true|false, "jobs": [{"title": "...", "url": "...", "location": "..."}]}

Rules:
- If is_job_listings_page is false, jobs MUST be [].
- Skip generic CTAs like "Join our team" — only include rows with a specific role title.
- url is the link to the specific job posting if present in the page text; otherwise empty string.
`;

const DEFAULT_JOB_MATCH_PROMPT = `You are filtering job postings to those a recruiter would care about.
Targets (the role families the recruiter is hiring for): {targets_json}
Candidates: {candidates_json}

For each candidate, decide if its title belongs to the SAME ROLE FAMILY as ANY target.

MATCHING examples (same role family):
- "Backend Engineer" → "Software Engineer"  (subtype of software engineering)
- "Staff iOS Developer" → "Software Engineer"  (subtype)
- "Senior Site Reliability Engineer" → "DevOps Engineer"  (same family)
- "Platform Engineer" → "DevOps Engineer"  (same family)
- "ML Engineer" → "AI Engineer"  (same family)

NOT MATCHING examples (different role family — return null):
- "Engineering Manager" → "Software Engineer"  (people-manager, not IC)
- "Solutions Engineer" → "Software Engineer"  (pre-sales, not building product)
- "Sales Engineer" → "Software Engineer"  (sales-side)
- "Account Executive" → any target  (sales, not engineering)
- "Customer Success Manager" → any target  (post-sales)
- "Data Solutions Architect" → "Software Engineer"  (consulting/sales-side)
- "Marketing Manager" → any target  (non-engineering)
- "Recruiter" → any target  (HR)
- "Product Manager" → "Software Engineer"  (PM, not engineer)

Be STRICT: when in doubt, return null. The recruiter only wants individual contributor engineers building product.

Return ONLY a JSON array of objects: [{"i": 0, "match": "Software Engineer"}, {"i": 1, "match": null}, ...]
- "match" MUST be one of the EXACT target strings from the targets list, character-for-character. Or null.
- One entry per candidate.
`;

const DEFAULT_JOB_CLASSIFY_PROMPT = `Classify these job postings. For each job, determine:
- department (one of: Engineering, Product, Design, Sales, Marketing, Operations, HR, Finance, Legal, Data, Other)
- seniority (one of: Intern, Junior, Mid, Senior, Lead, Manager, Director, VP, C-Level, Unknown)
- job_type (one of: Full-time, Part-time, Contract, Internship)
- skills (list of 3-5 key technical skills, empty list if non-technical)

Input jobs:
{jobs_json}

Return ONLY a JSON array with objects containing: title, department, seniority, job_type, skills
No markdown, no explanation.`;

const DEFAULT_SETTINGS: AppSettings = {
  llmProvider: 'gemini',
  geminiApiKey: '',
  geminiModel: 'gemini-2.5-flash',
  geminiPaidApiKey: '',
  geminiTier: 'free',
  ollamaHost: 'http://localhost:11434',
  ollamaModel: 'llama3',
  fetchIntervalHours: 2,
  articlesPerFeedLimit: 20,
  autoExtractOnIngest: false,
  globalScrapeKeywords: [],
  extractionPrompt: '',
  llmArticleCharBudget: 3500,
  careerPatterns: ['/careers', '/jobs', '/join-us', '/open-positions'],
  fallbackGoogle: true,
  fallbackLinkedin: true,
  atsDetection: ['Greenhouse', 'Lever', 'Workable', 'Ashby'],
  jobTargetTitles: [],
  jobMaxListingPages: 4,
  jobMaxSubcategoryPages: 6,
  jobExtractPrompt: '',
  jobMatchPrompt: '',
  jobClassifyPrompt: '',
};

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    MatCardModule, MatButtonModule, MatIconModule, MatFormFieldModule,
    MatInputModule, MatSelectModule, MatRadioModule, MatCheckboxModule,
    MatDividerModule, MatSlideToggleModule, MatSnackBarModule
  ],
  templateUrl: './settings.component.html',
  styleUrl: './settings.component.scss'
})
export class SettingsComponent implements OnInit {
  settings: AppSettings = { ...DEFAULT_SETTINGS };
  showApiKey = false;
  showPaidApiKey = false;

  profiles: ExtractionProfile[] = [];
  selectedProfileId = '';

  jobPromptProfiles: JobPromptProfile[] = [];
  selectedJobPromptId = '';

  geminiModels = [
    'gemini-2.5-flash',
    'gemini-2.5-flash-lite',
    'gemini-2.5-pro',
    'gemini-2.0-flash',
    'gemini-2.0-flash-lite',
  ];
  ollamaModels = ['llama3', 'llama3.1', 'mistral', 'codellama', 'phi3'];
  intervals = [0, 1, 2, 4, 6, 12, 24];

  intervalLabel(h: number): string {
    if (h === 0) return 'Manual (no schedule)';
    return `Every ${h} hour${h > 1 ? 's' : ''}`;
  }
  allAts = ['Greenhouse', 'Lever', 'Workable', 'Ashby', 'SmartRecruiters', 'BambooHR'];

  constructor(private snackBar: MatSnackBar, private api: ApiService) {}

  ngOnInit() {
    this.load();
    this.loadProfiles();
    this.loadJobPromptProfiles();
  }

  loadProfiles() {
    this.api.getExtractionProfiles().subscribe({
      next: (data) => this.profiles = data,
    });
  }

  applyProfile(profileId: string) {
    if (!profileId) return;
    const p = this.profiles.find(x => x.id === profileId);
    if (!p) return;
    this.settings.extractionPrompt = p.extractionPrompt || DEFAULT_EXTRACTION_PROMPT;
    this.settings.globalScrapeKeywords = [...p.scrapeKeywords];
    this.snackBar.open(`Loaded preset "${p.name}" into editor — click Save to apply`, 'OK', { duration: 3000 });
  }

  saveAsNewPreset() {
    const name = (prompt('Name for this preset?') || '').trim();
    if (!name) return;
    this.api.createExtractionProfile({
      name,
      extractionPrompt: this.settings.extractionPrompt || '',
      scrapeKeywords: this.settings.globalScrapeKeywords || [],
    }).subscribe({
      next: (created) => {
        this.profiles = [...this.profiles, created].sort((a, b) => a.name.localeCompare(b.name));
        this.selectedProfileId = created.id;
        this.snackBar.open(`Preset "${created.name}" saved`, 'OK', { duration: 2500 });
      },
      error: (err) => {
        const msg = err?.error?.detail || 'Failed to save preset';
        this.snackBar.open(msg, 'OK', { duration: 4000 });
      }
    });
  }

  updateSelectedPreset() {
    if (!this.selectedProfileId) return;
    this.api.updateExtractionProfile(this.selectedProfileId, {
      extractionPrompt: this.settings.extractionPrompt || '',
      scrapeKeywords: this.settings.globalScrapeKeywords || [],
    }).subscribe({
      next: (updated) => {
        this.profiles = this.profiles.map(p => p.id === updated.id ? updated : p);
        this.snackBar.open(`Preset "${updated.name}" updated`, 'OK', { duration: 2500 });
      },
      error: () => this.snackBar.open('Failed to update preset', 'OK', { duration: 3000 })
    });
  }

  deleteSelectedPreset() {
    if (!this.selectedProfileId) return;
    const p = this.profiles.find(x => x.id === this.selectedProfileId);
    if (!p || !confirm(`Delete preset "${p.name}"?`)) return;
    this.api.deleteExtractionProfile(this.selectedProfileId).subscribe({
      next: () => {
        this.profiles = this.profiles.filter(x => x.id !== this.selectedProfileId);
        this.selectedProfileId = '';
        this.snackBar.open(`Preset "${p.name}" deleted`, 'OK', { duration: 2500 });
      },
      error: () => this.snackBar.open('Failed to delete preset', 'OK', { duration: 3000 })
    });
  }

  load() {
    this.api.getSettings().subscribe({
      next: (data) => {
        this.settings = { ...DEFAULT_SETTINGS, ...data };
        // Show the built-in funding prompt + keywords in the editor when the user hasn't
        // saved custom ones, so they can see/edit them directly instead of seeing empty fields.
        if (!this.settings.extractionPrompt) {
          this.settings.extractionPrompt = DEFAULT_EXTRACTION_PROMPT;
        }
        if (!this.settings.globalScrapeKeywords || this.settings.globalScrapeKeywords.length === 0) {
          this.settings.globalScrapeKeywords = [...DEFAULT_FUNDING_KEYWORDS];
        }
        // Same pattern for the three job prompts: if backend has no override
        // saved, surface the built-in defaults in the editor so the user can
        // see/tweak them instead of staring at empty textareas.
        if (!this.settings.jobExtractPrompt) {
          this.settings.jobExtractPrompt = DEFAULT_JOB_EXTRACT_PROMPT;
        }
        if (!this.settings.jobMatchPrompt) {
          this.settings.jobMatchPrompt = DEFAULT_JOB_MATCH_PROMPT;
        }
        if (!this.settings.jobClassifyPrompt) {
          this.settings.jobClassifyPrompt = DEFAULT_JOB_CLASSIFY_PROMPT;
        }
      },
      error: () => this.snackBar.open('Failed to load settings', 'OK', { duration: 3000 })
    });
  }

  private save(patch: Partial<AppSettings>, successMsg: string) {
    this.api.updateSettings(patch).subscribe({
      next: (data) => {
        this.settings = { ...this.settings, ...data };
        this.snackBar.open(successMsg, 'OK', { duration: 2000 });
      },
      error: () => this.snackBar.open('Failed to save settings', 'OK', { duration: 3000 })
    });
  }

  testConnection() {
    this.snackBar.open(
      `Testing ${this.settings.llmProvider === 'gemini' ? 'Gemini' : 'Ollama'} connection...`,
      '', { duration: 1500 }
    );
    this.api.testConnection().subscribe({
      next: (res) => {
        const ok = res?.status === 'ok';
        this.snackBar.open(
          res?.message || (ok ? 'Connection successful' : 'Connection failed'),
          'OK', { duration: 3000 }
        );
      },
      error: () => this.snackBar.open('Connection test failed', 'OK', { duration: 3000 })
    });
  }

  saveProvider() {
    const patch: Partial<AppSettings> = {
      llmProvider: this.settings.llmProvider,
      geminiModel: this.settings.geminiModel,
      geminiTier: this.settings.geminiTier,
      ollamaHost: this.settings.ollamaHost,
      ollamaModel: this.settings.ollamaModel,
      autoExtractOnIngest: this.settings.autoExtractOnIngest,
    };
    // Only include either API key if the user typed a new one (masked values contain '*')
    if (this.settings.geminiApiKey && !this.settings.geminiApiKey.includes('*')) {
      patch.geminiApiKey = this.settings.geminiApiKey;
    }
    if (this.settings.geminiPaidApiKey && !this.settings.geminiPaidApiKey.includes('*')) {
      patch.geminiPaidApiKey = this.settings.geminiPaidApiKey;
    }
    this.save(patch, 'AI provider settings saved');
  }

  saveIngestion() {
    this.save({
      fetchIntervalHours: this.settings.fetchIntervalHours,
      articlesPerFeedLimit: this.settings.articlesPerFeedLimit,
      llmArticleCharBudget: this.settings.llmArticleCharBudget,
    }, 'Ingestion settings saved');
  }

  saveCrawl() {
    this.save({
      careerPatterns: this.settings.careerPatterns,
      fallbackGoogle: this.settings.fallbackGoogle,
      fallbackLinkedin: this.settings.fallbackLinkedin,
      atsDetection: this.settings.atsDetection,
      jobTargetTitles: this.settings.jobTargetTitles,
      jobMaxListingPages: this.settings.jobMaxListingPages,
      jobMaxSubcategoryPages: this.settings.jobMaxSubcategoryPages,
    }, 'Job crawl strategy saved');
  }

  get jobTargetTitlesCsv(): string {
    return (this.settings.jobTargetTitles || []).join(', ');
  }
  set jobTargetTitlesCsv(val: string) {
    this.settings.jobTargetTitles = val.split(',').map(s => s.trim()).filter(s => s);
  }

  toggleAts(ats: string) {
    const idx = this.settings.atsDetection.indexOf(ats);
    if (idx > -1) {
      this.settings.atsDetection.splice(idx, 1);
    } else {
      this.settings.atsDetection.push(ats);
    }
  }

  isAtsChecked(ats: string): boolean {
    return this.settings.atsDetection.includes(ats);
  }

  get careerPatternsStr(): string {
    return this.settings.careerPatterns.join(', ');
  }

  set careerPatternsStr(val: string) {
    this.settings.careerPatterns = val.split(',').map(s => s.trim()).filter(s => s);
  }

  get globalKeywordsStr(): string {
    return (this.settings.globalScrapeKeywords || []).join(', ');
  }

  set globalKeywordsStr(val: string) {
    this.settings.globalScrapeKeywords = val.split(',').map(s => s.trim()).filter(s => s);
  }

  resetExtractionPrompt() {
    this.settings.extractionPrompt = DEFAULT_EXTRACTION_PROMPT;
  }

  get defaultPromptPreview(): string { return DEFAULT_EXTRACTION_PROMPT; }

  saveIntent() {
    this.save({
      extractionPrompt: this.settings.extractionPrompt,
      globalScrapeKeywords: this.settings.globalScrapeKeywords,
    }, 'Extraction intent saved');
  }

  // --- Job Crawl Prompts ---

  saveJobPrompts() {
    this.save({
      jobExtractPrompt: this.settings.jobExtractPrompt,
      jobMatchPrompt: this.settings.jobMatchPrompt,
      jobClassifyPrompt: this.settings.jobClassifyPrompt,
    }, 'Job crawl prompts saved');
  }

  resetJobExtractPrompt() { this.settings.jobExtractPrompt = DEFAULT_JOB_EXTRACT_PROMPT; }
  resetJobMatchPrompt() { this.settings.jobMatchPrompt = DEFAULT_JOB_MATCH_PROMPT; }
  resetJobClassifyPrompt() { this.settings.jobClassifyPrompt = DEFAULT_JOB_CLASSIFY_PROMPT; }

  loadJobPromptProfiles() {
    this.api.getJobPromptProfiles().subscribe({
      next: (data) => this.jobPromptProfiles = data,
    });
  }

  applyJobPromptProfile(profileId: string) {
    if (!profileId) return;
    const p = this.jobPromptProfiles.find(x => x.id === profileId);
    if (!p) return;
    this.settings.jobExtractPrompt = p.extractPrompt || DEFAULT_JOB_EXTRACT_PROMPT;
    this.settings.jobMatchPrompt = p.matchPrompt || DEFAULT_JOB_MATCH_PROMPT;
    this.settings.jobClassifyPrompt = p.classifyPrompt || DEFAULT_JOB_CLASSIFY_PROMPT;
    this.snackBar.open(`Loaded preset "${p.name}" — click Save to apply`, 'OK', { duration: 3000 });
  }

  saveAsNewJobPromptPreset() {
    const name = (prompt('Name for this job-prompt preset?') || '').trim();
    if (!name) return;
    this.api.createJobPromptProfile({
      name,
      extractPrompt: this.settings.jobExtractPrompt || '',
      matchPrompt: this.settings.jobMatchPrompt || '',
      classifyPrompt: this.settings.jobClassifyPrompt || '',
    }).subscribe({
      next: (created) => {
        this.jobPromptProfiles = [...this.jobPromptProfiles, created]
          .sort((a, b) => a.name.localeCompare(b.name));
        this.selectedJobPromptId = created.id;
        this.snackBar.open(`Preset "${created.name}" saved`, 'OK', { duration: 2500 });
      },
      error: (err) => {
        const msg = err?.error?.detail || 'Failed to save preset';
        this.snackBar.open(msg, 'OK', { duration: 4000 });
      }
    });
  }

  updateSelectedJobPromptPreset() {
    if (!this.selectedJobPromptId) return;
    this.api.updateJobPromptProfile(this.selectedJobPromptId, {
      extractPrompt: this.settings.jobExtractPrompt || '',
      matchPrompt: this.settings.jobMatchPrompt || '',
      classifyPrompt: this.settings.jobClassifyPrompt || '',
    }).subscribe({
      next: (updated) => {
        this.jobPromptProfiles = this.jobPromptProfiles.map(p => p.id === updated.id ? updated : p);
        this.snackBar.open(`Preset "${updated.name}" updated`, 'OK', { duration: 2500 });
      },
      error: () => this.snackBar.open('Failed to update preset', 'OK', { duration: 3000 })
    });
  }

  deleteSelectedJobPromptPreset() {
    if (!this.selectedJobPromptId) return;
    const p = this.jobPromptProfiles.find(x => x.id === this.selectedJobPromptId);
    if (!p || !confirm(`Delete preset "${p.name}"?`)) return;
    this.api.deleteJobPromptProfile(this.selectedJobPromptId).subscribe({
      next: () => {
        this.jobPromptProfiles = this.jobPromptProfiles.filter(x => x.id !== this.selectedJobPromptId);
        this.selectedJobPromptId = '';
        this.snackBar.open(`Preset "${p.name}" deleted`, 'OK', { duration: 2500 });
      },
      error: () => this.snackBar.open('Failed to delete preset', 'OK', { duration: 3000 })
    });
  }
}
