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
import { AppSettings, ExtractionProfile } from '../../models/interfaces';
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

- date: YYYY-MM-DD. Use the announcement date if stated, otherwise today.

ONLY return {{"is_funding": false}} when the article is genuinely not about a
company raising investment capital — e.g. product launches, acquisitions, hires,
opinion pieces, earnings reports, or new VC fund-vehicle launches (where a VC
firm raises a fund, not a startup raising from VCs). If there is ANY funding
announcement in the article, extract it.

Article title: {title}
Article text: {text}

Return ONLY the JSON object — no markdown fences, no explanation, no preamble.`;

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
}
