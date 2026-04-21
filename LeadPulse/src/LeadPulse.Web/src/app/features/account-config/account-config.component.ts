import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { SocialAccountsComponent } from '../social-accounts/social-accounts.component';
import { environment } from '../../../environments/environment';

@Component({
  selector: 'app-account-config',
  standalone: true,
  imports: [CommonModule, FormsModule, SocialAccountsComponent],
  template: `
    <div class="config-page">
      <div class="tab-row">
        <div class="tab-bar">
          <button class="tab-btn" [class.active]="activeTab === 'social'" (click)="activeTab = 'social'">Social Accounts</button>
          <button class="tab-btn" [class.active]="activeTab === 'ai'" (click)="activeTab = 'ai'">AI Config</button>
          <button class="tab-btn" [class.active]="activeTab === 'contact'" (click)="activeTab = 'contact'">Contact Data Config</button>
        </div>
        <button *ngIf="activeTab === 'social'" class="btn-new-account" (click)="socialToggle = socialToggle + 1">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          New Account
        </button>
        <button *ngIf="activeTab === 'contact'" class="btn-new-account" (click)="showProviderModal()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          New Provider
        </button>
      </div>

      <!-- Social Accounts Tab -->
      <div *ngIf="activeTab === 'social'">
        <app-social-accounts [toggleAdd]="socialToggle"></app-social-accounts>
      </div>

      <!-- AI Config Tab -->
      <div *ngIf="activeTab === 'ai'">
        <div class="config-card">
          <h3>AI Analysis Settings</h3>
          <p class="help-text">Configure the AI provider used for intent analysis on scraped signals. The "Local" option is free and runs rule-based analysis without an API key.</p>

          <div class="form-grid">
            <div class="form-group">
              <label>AI Provider</label>
              <select [(ngModel)]="aiForm.aiProvider" (ngModelChange)="onProviderChange()" name="aiProvider">
                <option value="Local">Local (Free - Rule-based)</option>
                <option value="Claude">Claude (Anthropic API)</option>
                <option value="OpenAI">OpenAI</option>
                <option value="Google">Google AI (Gemini)</option>
              </select>
            </div>
            <div class="form-group" *ngIf="aiForm.aiProvider !== 'Local'">
              <label>API Key
                <span *ngIf="aiSettings?.hasApiKey" class="key-status key-ok" title="API key is stored">
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                  Stored
                </span>
                <span *ngIf="aiSettings && !aiSettings.hasApiKey" class="key-status key-missing" title="No API key stored">
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                  Not set
                </span>
              </label>
              <input type="password" [(ngModel)]="aiForm.apiKey" name="aiKey"
                     [placeholder]="aiSettings?.hasApiKey ? '(key saved — enter new to update)' : 'Enter API key'" />
            </div>
            <div class="form-group" *ngIf="aiForm.aiProvider !== 'Local'">
              <label>Model</label>
              <select [(ngModel)]="aiForm.aiModel" name="aiModel">
                <ng-container *ngIf="aiForm.aiProvider === 'Claude'">
                  <option value="claude-sonnet-4-6">Claude Sonnet 4.6 (Recommended)</option>
                  <option value="claude-haiku-4-5-20251001">Claude Haiku 4.5 (Fast/Cheap)</option>
                  <option value="claude-opus-4-6">Claude Opus 4.6 (Most Capable)</option>
                </ng-container>
                <ng-container *ngIf="aiForm.aiProvider === 'OpenAI'">
                  <option value="gpt-4o-mini">GPT-4o Mini (Recommended)</option>
                  <option value="gpt-4o">GPT-4o</option>
                  <option value="gpt-4-turbo">GPT-4 Turbo</option>
                  <option value="gpt-3.5-turbo">GPT-3.5 Turbo (Cheapest)</option>
                </ng-container>
                <ng-container *ngIf="aiForm.aiProvider === 'Google'">
                  <option value="gemini-2.0-flash">Gemini 2.0 Flash (Recommended)</option>
                  <option value="gemini-3.1-flash-lite-preview">Gemini 3.1 Flash Lite</option>
                  <option value="gemini-2.5-flash-preview-05-20">Gemini 2.5 Flash</option>
                  <option value="gemini-2.5-pro-preview-05-06">Gemini 2.5 Pro</option>
                  <option value="gemini-1.5-flash">Gemini 1.5 Flash (Cheapest)</option>
                </ng-container>
              </select>
            </div>
          </div>

          <div class="info-row" *ngIf="aiSettings">
            <span class="info-label">Current Provider:</span>
            <span class="info-value">{{ aiSettings.aiProvider }}</span>
            <span class="info-label" style="margin-left:1.5rem">API Key:</span>
            <span class="info-value">{{ aiSettings.hasApiKey ? 'Configured' : 'Not set' }}</span>
            <span *ngIf="aiSettings.aiModel" class="info-label" style="margin-left:1.5rem">Model:</span>
            <span *ngIf="aiSettings.aiModel" class="info-value">{{ aiSettings.aiModel }}</span>
            <span *ngIf="aiSettings.updatedAt" class="info-label" style="margin-left:1.5rem">Last Updated:</span>
            <span *ngIf="aiSettings.updatedAt" class="info-value">{{ aiSettings.updatedAt | date:'medium' }}</span>
          </div>

          <div *ngIf="aiMessage" class="msg" [class.error]="aiError">{{ aiMessage }}</div>

          <div class="form-actions">
            <button class="btn-primary" (click)="saveAiSettings()" [disabled]="savingAi">
              {{ savingAi ? 'Saving...' : 'Save AI Settings' }}
            </button>
            <button *ngIf="aiForm.aiProvider !== 'Local'" class="btn-sm btn-test" (click)="testAiKey()" [disabled]="testingAi" style="margin-left:.5rem">
              {{ testingAi ? 'Testing...' : 'Test Key' }}
            </button>
          </div>
        </div>

        <div class="config-card" style="margin-top:1.25rem">
          <h3>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="#0a66c2" style="vertical-align:middle;margin-right:6px"><path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z"/></svg>
            LinkedIn Scraper Settings
          </h3>
          <p class="help-text">Configure the Claude API key used for LinkedIn profile &amp; post scraping. This uses Claude Vision to extract structured data from LinkedIn page screenshots.</p>

          <div class="form-grid">
            <div class="form-group">
              <label>Claude API Key
                <span *ngIf="scraperSettings?.hasApiKey" class="key-status key-ok">
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                  Stored
                </span>
                <span *ngIf="scraperSettings && !scraperSettings.hasApiKey" class="key-status key-missing">
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                  Not set
                </span>
              </label>
              <input type="password" [(ngModel)]="scraperForm.apiKey" name="scraperKey"
                     [placeholder]="scraperSettings?.hasApiKey ? '(key saved — enter new to update)' : 'Enter Claude API key (sk-ant-...)'" />
            </div>
            <div class="form-group">
              <label>Claude Model</label>
              <select [(ngModel)]="scraperForm.aiModel" name="scraperModel">
                <option value="claude-sonnet-4-6">Claude Sonnet 4.6 (Recommended)</option>
                <option value="claude-haiku-4-5-20251001">Claude Haiku 4.5 (Faster / Cheaper)</option>
                <option value="claude-opus-4-6">Claude Opus 4.6 (Most Capable)</option>
              </select>
            </div>
          </div>

          <div class="info-row" *ngIf="scraperSettings">
            <span class="info-label">API Key:</span>
            <span class="info-value">{{ scraperSettings.hasApiKey ? 'Configured' : 'Not set' }}</span>
            <span class="info-label" style="margin-left:1.5rem">Model:</span>
            <span class="info-value">{{ scraperSettings.aiModel }}</span>
            <span *ngIf="scraperSettings.updatedAt" class="info-label" style="margin-left:1.5rem">Last Updated:</span>
            <span *ngIf="scraperSettings.updatedAt" class="info-value">{{ scraperSettings.updatedAt | date:'medium' }}</span>
          </div>

          <div *ngIf="scraperMessage" class="msg" [class.error]="scraperError">{{ scraperMessage }}</div>

          <div class="form-actions">
            <button class="btn-primary" (click)="saveScraperSettings()" [disabled]="savingScraper">
              {{ savingScraper ? 'Saving...' : 'Save Scraper Settings' }}
            </button>
            <button class="btn-sm btn-test" (click)="testScraperKey()" [disabled]="testingScraper" style="margin-left:.5rem">
              {{ testingScraper ? 'Testing...' : 'Test Key' }}
            </button>
          </div>
        </div>

        <div class="config-card" style="margin-top:1.25rem">
          <h3>Extraction Settings</h3>
          <p class="help-text">Configure how contact information is automatically extracted from scraped posts.</p>

          <div class="setting-section">
            <h4>Auto-Extract from Posts</h4>
            <label class="toggle-row">
              <input type="checkbox" [(ngModel)]="contactConfig.extractPhone" name="extractPhone">
              <span>Extract phone numbers from post content</span>
            </label>
            <label class="toggle-row">
              <input type="checkbox" [(ngModel)]="contactConfig.extractEmail" name="extractEmail">
              <span>Extract email addresses from post content</span>
            </label>
            <label class="toggle-row">
              <input type="checkbox" [(ngModel)]="contactConfig.aiExtract" name="aiExtract">
              <span>Use AI analysis to detect contact info (requires AI provider)</span>
            </label>
          </div>

          <div class="setting-section">
            <h4>Location Extraction</h4>
            <label class="toggle-row">
              <input type="checkbox" [(ngModel)]="contactConfig.extractLocation" name="extractLocation">
              <span>Extract city/state from Nextdoor post headers</span>
            </label>
            <label class="toggle-row">
              <input type="checkbox" [(ngModel)]="contactConfig.backfillLocation" name="backfillLocation">
              <span>Backfill location on existing prospects during reprocessing</span>
            </label>
          </div>

          <div class="setting-section">
            <h4>Deduplication</h4>
            <label class="toggle-row">
              <input type="checkbox" [(ngModel)]="contactConfig.dedup" name="dedup">
              <span>Auto-deduplicate signals and prospects during reprocessing</span>
            </label>
            <label class="toggle-row">
              <input type="checkbox" [(ngModel)]="contactConfig.fixAuthorNames" name="fixNames">
              <span>Fix generic author names (e.g. "Nextdoor Neighbor") from post content</span>
            </label>
          </div>

          <div *ngIf="contactMessage" class="msg" [class.error]="contactError">{{ contactMessage }}</div>

          <div class="form-actions">
            <button class="btn-primary" (click)="saveContactConfig()" [disabled]="savingContact">
              {{ savingContact ? 'Saving...' : 'Save Extraction Settings' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Contact Data Config Tab -->
      <div *ngIf="activeTab === 'contact'">
        <div class="enrich-grid">
          <div *ngFor="let p of enrichmentProviders" class="enrich-card">
            <div class="enrich-header">
              <div class="enrich-platform-info">
                <span class="enrich-icon" [class]="'enrich-icon-' + p.provider.toLowerCase()">
                  {{ p.provider === 'ContactOut' ? 'person_search' : p.provider === 'SerpApi' ? 'search' : p.provider === 'PeopleDataLabs' ? 'group' : 'rocket_launch' }}
                </span>
                <div>
                  <div class="enrich-platform-name">{{ p.provider }}</div>
                  <div class="enrich-username">{{ p.form.username || 'No account connected' }}</div>
                </div>
              </div>
              <span class="enrich-status-badge" [class]="p.form.isEnabled ? 'enrich-status-active' : 'enrich-status-disabled'">
                {{ p.form.isEnabled ? 'Active' : 'Disabled' }}
              </span>
            </div>

            <div class="enrich-stats">
              <div class="enrich-stat">
                <span class="enrich-stat-label">Credentials</span>
                <span class="enrich-stat-value">{{ p.hasPassword || p.hasApiKey ? 'Configured' : 'Not set' }}</span>
              </div>
              <div class="enrich-stat">
                <span class="enrich-stat-label">API Key</span>
                <span class="enrich-stat-value">{{ p.hasApiKey ? 'Set' : 'Not set' }}</span>
              </div>
              <div class="enrich-stat">
                <span class="enrich-stat-label">Last Updated</span>
                <span class="enrich-stat-value">{{ p.updatedAt ? (p.updatedAt | date:'short') : 'Never' }}</span>
              </div>
            </div>

            <div *ngIf="p.message" class="msg" [class.error]="p.error" style="margin-bottom:.5rem">{{ p.message }}</div>

            <div class="enrich-actions">
              <button class="btn-sm btn-accent" (click)="toggleProvider(p)">{{ p.form.isEnabled ? 'Disable' : 'Enable' }}</button>
              <button class="btn-sm" (click)="showProviderConfig(p)">Configure</button>
              <button class="btn-sm btn-test" (click)="testProviderConnection(p)" [disabled]="p.saving">{{ p.saving ? 'Testing...' : 'Test Connection' }}</button>
            </div>
          </div>
        </div>

        <div *ngIf="noEnrichmentConfigured()" class="enrich-empty">
          <span class="icon">contacts</span>
          <p>No enrichment accounts configured yet.</p>
          <p class="enrich-empty-sub">Connect ContactOut, Apollo, or People Data Labs to auto-fill phone numbers and emails. Add SerpApi for LinkedIn profile search.</p>
        </div>

        <!-- Configure Provider Modal -->
        <div *ngIf="configProvider" class="modal-overlay" (click)="configProvider = null">
          <div class="modal" (click)="$event.stopPropagation()">
            <h3>Configure {{ configProvider.provider }}</h3>
            <p class="help-text">{{ configProvider.provider === 'ContactOut' ? 'Find emails and phone numbers from social profiles. Used to enrich prospect contact data.' : configProvider.provider === 'SerpApi' ? 'Google search API used to find LinkedIn profiles for prospects. Get a key at serpapi.com.' : configProvider.provider === 'PeopleDataLabs' ? 'Person enrichment API — finds emails, phones, and social profiles from name + location. Great for Nextdoor leads. Get a key at peopledatalabs.com.' : 'Sales intelligence platform for finding verified emails and direct dials.' }}</p>
            <div class="form-grid">
              <div class="form-group">
                <label>Email / Username</label>
                <input type="text" [(ngModel)]="configProvider.form.username" [name]="configProvider.provider + '_user'" placeholder="Enter login email" />
              </div>
              <div class="form-group">
                <label>Password</label>
                <input type="password" [(ngModel)]="configProvider.form.password" [name]="configProvider.provider + '_pass'"
                       [placeholder]="configProvider.hasPassword ? '(saved — enter new to update)' : 'Enter password'" />
              </div>
              <div class="form-group" style="grid-column:1/-1">
                <label>API Key <span style="font-weight:400;color:#9ca3af">(optional — for direct API calls)</span></label>
                <input type="password" [(ngModel)]="configProvider.form.apiKey" [name]="configProvider.provider + '_key'"
                       [placeholder]="configProvider.hasApiKey ? '(saved — enter new to update)' : 'Enter API key'" />
              </div>
            </div>
            <div *ngIf="configProvider.message" class="msg" [class.error]="configProvider.error" style="margin-top:.75rem">{{ configProvider.message }}</div>
            <div class="form-actions" style="margin-top:1rem">
              <button class="btn-secondary" (click)="configProvider = null">Cancel</button>
              <button class="btn-primary" (click)="saveEnrichmentProvider(configProvider)" [disabled]="configProvider.saving">
                {{ configProvider.saving ? 'Saving...' : 'Save' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .config-page{padding:1.5rem}
    .page-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem}
    .page-header h2{margin:0}
    .tab-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:1.5rem}
    .tab-bar{display:flex;gap:0}
    .btn-new-account{display:flex;align-items:center;gap:.35rem;padding:.5rem 1rem;background:#2563eb;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.85rem;font-weight:500}
    .btn-new-account:hover{background:#1d4ed8}
    .tab-btn{padding:.6rem 1.25rem;border:1px solid #d1d5db;background:#fff;cursor:pointer;font-weight:500;font-size:.875rem;color:#6b7280}
    .tab-btn:first-child{border-radius:6px 0 0 6px}
    .tab-btn:last-child{border-radius:0 6px 6px 0;border-left:none}
    .tab-btn:not(:first-child):not(:last-child){border-left:none}
    .tab-btn.active{background:#2563eb;color:#fff;border-color:#2563eb}
    .config-card{background:#fff;border-radius:8px;padding:1.5rem;box-shadow:0 1px 3px rgba(0,0,0,.1)}
    .config-card h3{margin:0 0 .25rem;color:#1a1f36}
    .help-text{font-size:.85rem;color:#6b7280;margin:0 0 1.25rem}
    .form-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem}
    .form-group label{display:block;font-weight:500;margin-bottom:.25rem;color:#374151;font-size:.85rem}
    .form-group input,.form-group select{width:100%;padding:.5rem;border:1px solid #d1d5db;border-radius:4px;box-sizing:border-box;font-size:.875rem}
    .info-row{display:flex;align-items:center;flex-wrap:wrap;gap:.3rem;padding:.75rem 1rem;background:#f9fafb;border-radius:6px;border:1px solid #e5e7eb;margin-bottom:1rem;font-size:.825rem}
    .info-label{color:#6b7280;font-weight:500}
    .info-value{color:#1a1f36;font-weight:600}
    .setting-section{margin-bottom:1.5rem}
    .setting-section h4{margin:0 0 .6rem;font-size:.9rem;color:#374151}
    .toggle-row{display:flex;align-items:center;gap:.5rem;padding:.4rem 0;font-size:.85rem;color:#374151;cursor:pointer}
    .toggle-row input{accent-color:#2563eb}
    .msg{padding:.5rem .75rem;border-radius:4px;font-size:.85rem;background:#d1fae5;color:#065f46;margin-bottom:1rem}
    .msg.error{background:#fee2e2;color:#991b1b}
    .form-actions{display:flex;gap:.5rem;justify-content:flex-end}
    .btn-primary{padding:.5rem 1rem;background:#2563eb;color:#fff;border:none;border-radius:4px;cursor:pointer}
    .btn-primary:hover{background:#1d4ed8}
    .btn-primary:disabled{opacity:.5;cursor:not-allowed}
    .btn-test{padding:.45rem .75rem;background:#f8fafc;color:#334155;border:1px solid #cbd5e1;border-radius:4px;cursor:pointer;font-size:.85rem}
    .btn-test:hover{background:#e2e8f0}
    .btn-test:disabled{opacity:.5;cursor:not-allowed}
    .key-status{display:inline-flex;align-items:center;gap:3px;font-size:.75rem;font-weight:500;margin-left:.5rem;vertical-align:middle}
    .key-ok{color:#16a34a}
    .key-missing{color:#ef4444}
    .btn-secondary{padding:.5rem 1rem;background:#fff;color:#374151;border:1px solid #d1d5db;border-radius:4px;cursor:pointer}
    .btn-sm{padding:.3rem .6rem;font-size:.75rem;border:1px solid #d1d5db;border-radius:4px;cursor:pointer;background:#fff}
    .btn-accent{color:#2563eb;border-color:#2563eb}
    .btn-test{color:#7c3aed;border-color:#7c3aed}
    .enrich-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:1rem}
    .enrich-card{background:#fff;border-radius:8px;padding:1.25rem;box-shadow:0 1px 3px rgba(0,0,0,.1)}
    .enrich-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1rem}
    .enrich-platform-info{display:flex;gap:.75rem;align-items:center}
    .enrich-icon{width:40px;height:40px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-family:'Material Icons';font-size:1.25rem;color:#fff}
    .enrich-icon-contactout{background:#2563eb}
    .enrich-icon-apollo{background:#7c3aed}
    .enrich-icon-peopledatalabs{background:#0ea5e9}
    .enrich-icon-serpapi{background:#f59e0b}
    .enrich-platform-name{font-weight:600;color:#1a1f36}
    .enrich-username{color:#6b7280;font-size:.875rem}
    .enrich-status-badge{padding:.2rem .6rem;border-radius:12px;font-size:.75rem;font-weight:600}
    .enrich-status-active{background:#d1fae5;color:#065f46}
    .enrich-status-disabled{background:#e5e7eb;color:#374151}
    .enrich-stats{display:flex;gap:1.5rem;margin-bottom:1rem;padding:.75rem 0;border-top:1px solid #f3f4f6;border-bottom:1px solid #f3f4f6}
    .enrich-stat{display:flex;flex-direction:column}
    .enrich-stat-label{font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;color:#6b7280}
    .enrich-stat-value{font-weight:600;color:#1a1f36}
    .enrich-actions{display:flex;gap:.5rem;flex-wrap:wrap}
    .enrich-empty{text-align:center;padding:3rem;background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-top:1rem}
    .enrich-empty .icon{font-family:'Material Icons';font-size:2.5rem;color:#d1d5db}
    .enrich-empty p{margin:.5rem 0;color:#374151}
    .enrich-empty-sub{font-size:.85rem;color:#6b7280}
    .modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:1000}
    .modal{background:#fff;border-radius:8px;padding:1.5rem;width:540px;max-height:80vh;overflow-y:auto}
    .modal h3{margin:0 0 .5rem;color:#1a1f36}
  `]
})
export class AccountConfigComponent implements OnInit {
  activeTab: 'social' | 'ai' | 'contact' = 'social';
  socialToggle = 0;

  // AI Config
  aiSettings: any = null;
  aiForm = { aiProvider: 'Local', apiKey: '', aiModel: '' };
  savingAi = false;
  testingAi = false;
  aiMessage = '';
  aiError = false;

  // LinkedIn Scraper
  scraperSettings: any = null;
  scraperForm = { apiKey: '', aiModel: 'claude-sonnet-4-6' };
  savingScraper = false;
  testingScraper = false;
  scraperMessage = '';
  scraperError = false;

  // Enrichment Providers
  enrichmentProviders: {
    provider: string;
    form: { username: string; password: string; apiKey: string; isEnabled: boolean };
    hasPassword: boolean;
    hasApiKey: boolean;
    updatedAt: Date | null;
    saving: boolean;
    message: string;
    error: boolean;
  }[] = [
    { provider: 'ContactOut', form: { username: '', password: '', apiKey: '', isEnabled: false }, hasPassword: false, hasApiKey: false, updatedAt: null, saving: false, message: '', error: false },
    { provider: 'Apollo', form: { username: '', password: '', apiKey: '', isEnabled: false }, hasPassword: false, hasApiKey: false, updatedAt: null, saving: false, message: '', error: false },
    { provider: 'SerpApi', form: { username: '', password: '', apiKey: '', isEnabled: false }, hasPassword: false, hasApiKey: false, updatedAt: null, saving: false, message: '', error: false },
    { provider: 'PeopleDataLabs', form: { username: '', password: '', apiKey: '', isEnabled: false }, hasPassword: false, hasApiKey: false, updatedAt: null, saving: false, message: '', error: false }
  ];

  configProvider: typeof this.enrichmentProviders[0] | null = null;

  // Contact Data Config
  contactConfig = {
    extractPhone: true,
    extractEmail: true,
    aiExtract: true,
    extractLocation: true,
    backfillLocation: true,
    dedup: true,
    fixAuthorNames: true
  };
  savingContact = false;
  contactMessage = '';
  contactError = false;

  private apiUrl = environment.apiUrl;

  constructor(private http: HttpClient) {}

  ngOnInit(): void {
    this.loadAiSettings();
    this.loadScraperSettings();
    this.loadEnrichmentSettings();
    this.loadContactConfig();
  }

  loadAiSettings(): void {
    this.http.get<any>(`${this.apiUrl}/signals/ai-settings`).subscribe(s => {
      this.aiSettings = s;
      this.aiForm.aiProvider = s.aiProvider;
      this.aiForm.aiModel = s.aiModel || '';
    });
  }

  onProviderChange(): void {
    this.aiForm.apiKey = '';
    this.aiMessage = '';
    const defaults: Record<string, string> = {
      'Claude': 'claude-sonnet-4-6',
      'OpenAI': 'gpt-4o-mini',
      'Google': 'gemini-2.0-flash'
    };
    this.aiForm.aiModel = defaults[this.aiForm.aiProvider] || '';
  }

  saveAiSettings(): void {
    this.savingAi = true;
    this.aiMessage = '';
    this.aiError = false;

    const body: any = {
      aiProvider: this.aiForm.aiProvider,
      aiModel: this.aiForm.aiModel || null
    };
    if (this.aiForm.apiKey) {
      body.apiKey = this.aiForm.apiKey;
    }

    this.http.put<any>(`${this.apiUrl}/signals/ai-settings`, body).subscribe({
      next: (res) => {
        this.aiSettings = res;
        this.aiMessage = 'AI settings saved successfully';
        this.aiError = false;
        this.savingAi = false;
        this.aiForm.apiKey = '';
      },
      error: () => {
        this.aiMessage = 'Failed to save AI settings';
        this.aiError = true;
        this.savingAi = false;
      }
    });
  }

  testAiKey(): void {
    this.testingAi = true;
    this.aiMessage = '';
    this.aiError = false;

    this.http.post<any>(`${this.apiUrl}/signals/ai-settings/test`, {}).subscribe({
      next: (res) => {
        this.testingAi = false;
        this.aiMessage = res.success ? res.message : res.error;
        this.aiError = !res.success;
      },
      error: () => {
        this.testingAi = false;
        this.aiMessage = 'Failed to test API key';
        this.aiError = true;
      }
    });
  }

  // === LinkedIn Scraper Settings ===

  loadScraperSettings(): void {
    this.http.get<any>(`${this.apiUrl}/prospects/scraper-settings`).subscribe(s => {
      this.scraperSettings = s;
      this.scraperForm.aiModel = s.aiModel || 'claude-sonnet-4-6';
    });
  }

  saveScraperSettings(): void {
    this.savingScraper = true;
    this.scraperMessage = '';
    this.scraperError = false;
    const body: any = { aiModel: this.scraperForm.aiModel };
    if (this.scraperForm.apiKey) body.apiKey = this.scraperForm.apiKey;
    this.http.put<any>(`${this.apiUrl}/prospects/scraper-settings`, body).subscribe({
      next: (res) => {
        this.scraperSettings = res;
        this.scraperMessage = 'LinkedIn scraper settings saved successfully';
        this.scraperError = false;
        this.savingScraper = false;
        this.scraperForm.apiKey = '';
      },
      error: () => {
        this.scraperMessage = 'Failed to save scraper settings';
        this.scraperError = true;
        this.savingScraper = false;
      }
    });
  }

  testScraperKey(): void {
    this.testingScraper = true;
    this.scraperMessage = '';
    this.scraperError = false;
    this.http.post<any>(`${this.apiUrl}/prospects/scraper-settings/test`, {}).subscribe({
      next: (res) => {
        this.testingScraper = false;
        this.scraperMessage = res.success ? res.message : res.error;
        this.scraperError = !res.success;
      },
      error: () => {
        this.testingScraper = false;
        this.scraperMessage = 'Failed to test scraper key';
        this.scraperError = true;
      }
    });
  }

  loadEnrichmentSettings(): void {
    this.http.get<any[]>(`${this.apiUrl}/prospects/enrichment-settings`).subscribe(settings => {
      for (const s of settings) {
        const p = this.enrichmentProviders.find(x => x.provider === s.provider);
        if (p) {
          p.form.username = s.username || '';
          p.form.isEnabled = s.isEnabled;
          p.hasPassword = s.hasPassword;
          p.hasApiKey = s.hasApiKey;
          p.updatedAt = s.updatedAt;
        }
      }
    });
  }

  noEnrichmentConfigured(): boolean {
    return this.enrichmentProviders.every(p => !p.form.username && !p.hasPassword);
  }

  showProviderModal(): void {
    const unconfigured = this.enrichmentProviders.find(p => !p.form.username && !p.hasPassword);
    const target = unconfigured || this.enrichmentProviders[0];
    this.showProviderConfig(target);
  }

  showProviderConfig(p: typeof this.enrichmentProviders[0]): void {
    this.configProvider = p;
    p.message = '';
  }

  toggleProvider(p: typeof this.enrichmentProviders[0]): void {
    p.form.isEnabled = !p.form.isEnabled;
    p.message = '';
    p.error = false;

    const body: any = {
      provider: p.provider,
      username: p.form.username || null,
      isEnabled: p.form.isEnabled
    };

    this.http.put<any>(`${this.apiUrl}/prospects/enrichment-settings`, body).subscribe({
      next: (res) => {
        p.hasPassword = res.hasPassword;
        p.hasApiKey = res.hasApiKey;
        p.updatedAt = res.updatedAt;
        p.message = `${p.provider} ${p.form.isEnabled ? 'enabled' : 'disabled'}`;
        p.error = false;
      },
      error: () => {
        p.form.isEnabled = !p.form.isEnabled; // revert
        p.message = `Failed to update ${p.provider}`;
        p.error = true;
      }
    });
  }

  testProviderConnection(p: typeof this.enrichmentProviders[0]): void {
    if (!p.hasPassword && !p.hasApiKey) {
      p.message = 'No credentials configured — click Configure to add login details';
      p.error = true;
      return;
    }
    p.saving = true;
    p.message = '';
    this.http.post<any>(`${this.apiUrl}/prospects/enrichment-settings/test`, { provider: p.provider }).subscribe({
      next: (res) => {
        p.message = res.success
          ? (res.warning ? `${p.provider} connected — ${res.warning}` : `${p.provider} connection successful`)
          : (res.error || 'Connection test failed');
        p.error = !res.success;
        p.saving = false;
      },
      error: () => {
        p.message = `Failed to test ${p.provider} connection`;
        p.error = true;
        p.saving = false;
      }
    });
  }

  saveEnrichmentProvider(p: typeof this.enrichmentProviders[0]): void {
    p.saving = true;
    p.message = '';
    p.error = false;

    const body: any = {
      provider: p.provider,
      username: p.form.username || null,
      isEnabled: p.form.isEnabled
    };
    if (p.form.password) body.password = p.form.password;
    if (p.form.apiKey) body.apiKey = p.form.apiKey;

    this.http.put<any>(`${this.apiUrl}/prospects/enrichment-settings`, body).subscribe({
      next: (res) => {
        p.hasPassword = res.hasPassword;
        p.hasApiKey = res.hasApiKey;
        p.updatedAt = res.updatedAt;
        p.form.password = '';
        p.form.apiKey = '';
        p.message = `${p.provider} settings saved successfully`;
        p.error = false;
        p.saving = false;
        this.configProvider = null;
      },
      error: () => {
        p.message = `Failed to save ${p.provider} settings`;
        p.error = true;
        p.saving = false;
      }
    });
  }

  saveContactConfig(): void {
    this.savingContact = true;
    this.contactMessage = '';
    this.contactError = false;

    // Save to localStorage for now (can be moved to backend later)
    try {
      localStorage.setItem('leadpulse_contact_config', JSON.stringify(this.contactConfig));
      this.contactMessage = 'Contact data configuration saved';
      this.contactError = false;
    } catch {
      this.contactMessage = 'Failed to save contact configuration';
      this.contactError = true;
    }
    this.savingContact = false;
  }

  private loadContactConfig(): void {
    try {
      const saved = localStorage.getItem('leadpulse_contact_config');
      if (saved) {
        this.contactConfig = { ...this.contactConfig, ...JSON.parse(saved) };
      }
    } catch { /* use defaults */ }
  }
}
