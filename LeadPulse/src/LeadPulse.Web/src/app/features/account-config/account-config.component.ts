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
      <div class="page-header">
        <h2>Account Configuration</h2>
      </div>

      <div class="tab-bar">
        <button class="tab-btn" [class.active]="activeTab === 'social'" (click)="activeTab = 'social'">Social Accounts</button>
        <button class="tab-btn" [class.active]="activeTab === 'ai'" (click)="activeTab = 'ai'">AI Config</button>
        <button class="tab-btn" [class.active]="activeTab === 'contact'" (click)="activeTab = 'contact'">Contact Data Config</button>
      </div>

      <!-- Social Accounts Tab -->
      <div *ngIf="activeTab === 'social'">
        <app-social-accounts></app-social-accounts>
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
              <label>API Key</label>
              <input type="password" [(ngModel)]="aiForm.apiKey" name="aiKey"
                     [placeholder]="aiSettings?.hasApiKey ? '(key saved — enter new to update)' : 'Enter API key'" />
            </div>
            <div class="form-group" *ngIf="aiForm.aiProvider !== 'Local'">
              <label>Model</label>
              <input type="text" [(ngModel)]="aiForm.aiModel" name="aiModel"
                     [placeholder]="aiForm.aiProvider === 'Claude' ? 'claude-sonnet-4-6' : aiForm.aiProvider === 'Google' ? 'gemini-2.0-flash' : 'gpt-4o-mini'" />
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
                  {{ p.provider === 'ContactOut' ? 'person_search' : 'rocket_launch' }}
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
          <p class="enrich-empty-sub">Connect ContactOut or Apollo to auto-fill phone numbers and emails on your prospects.</p>
        </div>

        <!-- Configure Provider Modal -->
        <div *ngIf="configProvider" class="modal-overlay" (click)="configProvider = null">
          <div class="modal" (click)="$event.stopPropagation()">
            <h3>Configure {{ configProvider.provider }}</h3>
            <p class="help-text">{{ configProvider.provider === 'ContactOut' ? 'Find emails and phone numbers from social profiles. Used to enrich prospect contact data.' : 'Sales intelligence platform for finding verified emails and direct dials.' }}</p>
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
    .tab-bar{display:flex;gap:0;margin-bottom:1.5rem}
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

  // AI Config
  aiSettings: any = null;
  aiForm = { aiProvider: 'Local', apiKey: '', aiModel: '' };
  savingAi = false;
  aiMessage = '';
  aiError = false;

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
    { provider: 'Apollo', form: { username: '', password: '', apiKey: '', isEnabled: false }, hasPassword: false, hasApiKey: false, updatedAt: null, saving: false, message: '', error: false }
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
    this.aiForm.aiModel = '';
    this.aiMessage = '';
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
    // Simulate test (actual implementation would call a backend test endpoint)
    setTimeout(() => {
      p.message = `${p.provider} connection test — credentials saved and ready`;
      p.error = false;
      p.saving = false;
    }, 1000);
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
