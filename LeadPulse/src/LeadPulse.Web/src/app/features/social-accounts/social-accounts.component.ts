import { Component, OnInit, OnChanges, SimpleChanges, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { SocialAccountService } from '../../core/services/social-account.service';
import {
  SocialAccountResponse,
  CreateSocialAccountRequest,
  UpdateSyncConfigRequest,
  SyncJobResponse
} from '../../core/models/social-account.model';

@Component({
  selector: 'app-social-accounts',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="social-page">
      <!-- Add Account Form -->
      <div *ngIf="showAddForm" class="form-card">
        <h3>Connect New Account</h3>
        <div class="form-grid">
          <div class="form-group">
            <label>Platform</label>
            <select [(ngModel)]="newAccount.platform" name="platform">
              <option value="Reddit">Reddit</option>
              <option value="LinkedIn">LinkedIn</option>
              <option value="Facebook">Facebook</option>
              <option value="Nextdoor">Nextdoor</option>
              <option value="X">X (Twitter)</option>
            </select>
          </div>
          <div class="form-group">
            <label>{{ newAccount.platform === 'Reddit' ? 'Subreddit (e.g. insurance, personalfinance)' : 'Username / Email' }}</label>
            <input [(ngModel)]="newAccount.username" name="username"
              [placeholder]="newAccount.platform === 'Reddit' ? 'insurance' : 'account@example.com'">
          </div>
          <div class="form-group">
            <label>{{ newAccount.platform === 'Reddit' ? 'Search Keywords (comma-separated, optional)' : 'Password' }}</label>
            <input [type]="newAccount.platform === 'Reddit' ? 'text' : 'password'"
              [(ngModel)]="newAccount.password" name="password"
              [placeholder]="newAccount.platform === 'Reddit' ? 'car insurance, home insurance' : ''">
          </div>
          <div class="form-group">
            <label>MFA Secret (optional)</label>
            <input [(ngModel)]="newAccount.mfaSecret" name="mfaSecret" placeholder="TOTP secret key">
          </div>
        </div>
        <div class="form-actions">
          <button class="btn-secondary" (click)="cancelAdd()">Cancel</button>
          <button class="btn-primary" (click)="createAccount()">Connect</button>
        </div>
        <div *ngIf="formError" class="error">{{ formError }}</div>
      </div>

      <!-- Accounts List -->
      <div class="accounts-grid">
        <div *ngFor="let account of accounts" class="account-card">
          <div class="account-header">
            <div class="platform-info">
              <span class="platform-icon" [class]="'platform-' + account.platform.toLowerCase()">
                {{ getPlatformIcon(account.platform) }}
              </span>
              <div>
                <div class="platform-name">{{ account.platform }}</div>
                <div class="username">{{ account.username }}</div>
              </div>
            </div>
            <span class="status-badge" [class]="'status-' + account.status.toLowerCase()">
              {{ account.status }}
            </span>
          </div>

          <div class="account-stats">
            <div class="stat">
              <span class="stat-label">Posts Scraped</span>
              <span class="stat-value">{{ account.totalPostsScraped }}</span>
            </div>
            <div class="stat">
              <span class="stat-label">Last Sync</span>
              <span class="stat-value">{{ account.lastSyncAt ? (account.lastSyncAt | date:'short') : 'Never' }}</span>
            </div>
            <div class="stat">
              <span class="stat-label">Frequency</span>
              <span class="stat-value">{{ account.syncFrequencyMinutes }}m</span>
            </div>
          </div>

          <div class="account-actions">
            <button class="btn-sm" (click)="testLogin(account)">Test Login</button>
            <button class="btn-sm btn-accent" (click)="syncNow(account)">Sync Now</button>
            <button class="btn-sm" (click)="showConfig(account)">Configure</button>
            <button class="btn-sm btn-targets" (click)="showTargets(account)">Scrape Targets</button>
            <button class="btn-sm" (click)="showJobs(account)">History</button>
            <button class="btn-sm btn-danger" (click)="confirmDelete(account)">Disconnect</button>
          </div>
        </div>
      </div>

      <div *ngIf="accounts.length === 0 && !showAddForm" class="empty-state">
        <span class="icon">share</span>
        <p>No social accounts connected yet.</p>
        <button class="btn-primary" (click)="showAddForm = true">Connect Your First Account</button>
      </div>

      <!-- Sync Config Modal -->
      <div *ngIf="configAccount" class="modal-overlay" (click)="configAccount = null">
        <div class="modal" (click)="$event.stopPropagation()">
          <h3>Sync Configuration — {{ configAccount.platform }} ({{ configAccount.username }})</h3>
          <div class="form-grid">
            <div class="form-group">
              <label>Sync Frequency (minutes)</label>
              <input type="number" [(ngModel)]="syncConfig.syncFrequencyMinutes" name="freq" min="60" max="2880">
              <small>60–2880 minutes</small>
            </div>
            <div class="form-group">
              <label>Max Posts Per Sync</label>
              <input type="number" [(ngModel)]="syncConfig.maxPostsPerSync" name="maxPosts" min="1" max="200">
            </div>
            <div class="form-group">
              <label>Sync Window Start</label>
              <input type="time" [(ngModel)]="syncConfig.syncWindowStart" name="windowStart">
            </div>
            <div class="form-group">
              <label>Sync Window End</label>
              <input type="time" [(ngModel)]="syncConfig.syncWindowEnd" name="windowEnd">
            </div>
            <div class="form-group">
              <label>Scrape Depth</label>
              <select [(ngModel)]="syncConfig.scrapeDepth" name="depth">
                <option value="shallow">Shallow</option>
                <option value="medium">Medium</option>
                <option value="deep">Deep</option>
              </select>
            </div>
            <div class="form-group">
              <label>Auto Retry Max</label>
              <input type="number" [(ngModel)]="syncConfig.autoRetryMax" name="retry" min="0" max="5">
            </div>
          </div>
          <div class="form-actions">
            <button class="btn-secondary" (click)="configAccount = null">Cancel</button>
            <button class="btn-primary" (click)="saveConfig()">Save</button>
          </div>
        </div>
      </div>

      <!-- Sync Jobs Modal -->
      <div *ngIf="jobsAccount" class="modal-overlay" (click)="jobsAccount = null">
        <div class="modal modal-wide" (click)="$event.stopPropagation()">
          <h3>Sync History — {{ jobsAccount.platform }} ({{ jobsAccount.username }})</h3>
          <table *ngIf="syncJobs.length > 0">
            <thead>
              <tr>
                <th>Status</th>
                <th>Posts</th>
                <th>Started</th>
                <th>Duration</th>
                <th>Retries</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              <tr *ngFor="let job of syncJobs">
                <td><span class="status-badge" [class]="'status-' + job.status.toLowerCase()">{{ job.status }}</span></td>
                <td>{{ job.postsFound }}</td>
                <td>{{ job.startedAt ? (job.startedAt | date:'short') : '—' }}</td>
                <td>{{ job.durationSeconds ? job.durationSeconds + 's' : '—' }}</td>
                <td>{{ job.retryCount }}</td>
                <td class="error-cell">{{ job.errorMessage || '—' }}</td>
              </tr>
            </tbody>
          </table>
          <p *ngIf="syncJobs.length === 0" class="empty-text">No sync jobs yet.</p>
          <div class="form-actions">
            <button class="btn-secondary" (click)="jobsAccount = null">Close</button>
          </div>
        </div>
      </div>

      <!-- Scrape Targets Modal -->
      <div *ngIf="targetsAccount" class="modal-overlay" (click)="targetsAccount = null">
        <div class="modal modal-wide" (click)="$event.stopPropagation()">
          <h3>Scrape Targets — {{ targetsAccount.platform }} ({{ targetsAccount.username }})</h3>
          <p class="help-text">Add URLs where the scraper should look for posts. If no targets are configured, defaults will be used. You can add group pages, search URLs, feed pages, etc.</p>

          <!-- Add Target Form -->
          <div class="target-add-row">
            <input [(ngModel)]="newTargetUrl" name="targetUrl" placeholder="https://nextdoor.com/group/..." class="target-input">
            <input [(ngModel)]="newTargetName" name="targetName" placeholder="Label (optional)" class="target-name-input">
            <button class="btn-primary" (click)="addTarget()">Add</button>
          </div>

          <!-- Targets List -->
          <table *ngIf="targets.length > 0">
            <thead>
              <tr>
                <th>Label</th>
                <th>URL</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr *ngFor="let t of targets" [class.inactive-row]="!t.isActive">
                <td>{{ t.groupName || '—' }}</td>
                <td class="url-cell"><a [href]="t.groupUrl" target="_blank">{{ t.groupUrl }}</a></td>
                <td>
                  <span class="status-badge" [class]="t.isActive ? 'status-active' : 'status-disabled'">
                    {{ t.isActive ? 'Active' : 'Disabled' }}
                  </span>
                </td>
                <td class="actions-cell">
                  <button class="btn-sm btn-accent" (click)="testTarget(t)" [disabled]="testingTargetId === t.id">
                    {{ testingTargetId === t.id ? 'Testing...' : 'Test' }}
                  </button>
                  <button class="btn-sm" (click)="toggleTargetActive(t)">{{ t.isActive ? 'Disable' : 'Enable' }}</button>
                  <button class="btn-sm btn-danger" (click)="removeTarget(t)">Remove</button>
                </td>
              </tr>
            </tbody>
          </table>
          <p *ngIf="targets.length === 0" class="empty-text">No targets configured — the scraper will use default URLs.</p>

          <!-- Test Results -->
          <div *ngIf="testResults" class="test-results">
            <div class="test-results-header">
              <h4>Test Results — {{ testResultsLabel }}</h4>
              <button class="btn-sm" (click)="testResults = null">Clear</button>
            </div>
            <div *ngIf="testResults.error" class="error">{{ testResults.error }}</div>
            <p *ngIf="testResults.success" class="test-summary">Found {{ testResults.postsFound }} posts</p>
            <div *ngIf="testResults.posts?.length > 0" class="test-posts">
              <div *ngFor="let p of testResults.posts" class="test-post">
                <div class="test-post-meta">
                  <strong>{{ p.author }}</strong>
                  <span *ngIf="p.postDate">{{ p.postDate | date:'short' }}</span>
                </div>
                <div class="test-post-content">{{ p.content }}</div>
                <a *ngIf="p.postUrl" [href]="p.postUrl" target="_blank" class="test-post-link">View Post</a>
              </div>
            </div>
            <p *ngIf="testResults.success && testResults.posts?.length === 0" class="empty-text">No posts found at this URL.</p>
          </div>

          <div class="form-actions">
            <button class="btn-secondary" (click)="targetsAccount = null; testResults = null">Close</button>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .social-page{padding:0.75rem 1.5rem 1.5rem}
    .form-card,.account-card,.empty-state{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1)}
    .form-card{padding:1.5rem;margin-bottom:1.5rem}
    .form-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
    .form-group{margin-bottom:.5rem}
    .form-group label{display:block;font-weight:500;margin-bottom:.25rem;color:#374151;font-size:.875rem}
    .form-group small{color:#6b7280;font-size:.75rem}
    input,select{width:100%;padding:.5rem;border:1px solid #d1d5db;border-radius:4px;box-sizing:border-box}
    .form-actions{display:flex;gap:.5rem;justify-content:flex-end;margin-top:1rem}
    .accounts-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:1rem}
    .account-card{padding:1.25rem}
    .account-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1rem}
    .platform-info{display:flex;gap:.75rem;align-items:center}
    .platform-icon{width:40px;height:40px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:1.25rem;color:#fff}
    .platform-linkedin{background:#0077b5}.platform-facebook{background:#1877f2}.platform-nextdoor{background:#8ed500}.platform-x{background:#000}.platform-reddit{background:#ff4500}
    .platform-name{font-weight:600;color:#1a1f36}
    .username,.help-text,.empty-text,.form-group small,.stat-label,.test-post-meta{color:#6b7280}
    .username{font-size:.875rem}
    .status-badge{padding:.2rem .6rem;border-radius:12px;font-size:.75rem;font-weight:600}
    .status-active,.status-success{background:#d1fae5;color:#065f46}
    .status-syncing,.status-running{background:#dbeafe;color:#1d4ed8}
    .status-loginfailed,.status-failed{background:#fee2e2;color:#991b1b}
    .status-disabled{background:#e5e7eb;color:#374151}
    .status-queued{background:#fef3c7;color:#92400e}
    .account-stats{display:flex;gap:1.5rem;margin-bottom:1rem;padding:.75rem 0;border-top:1px solid #f3f4f6;border-bottom:1px solid #f3f4f6}
    .stat{display:flex;flex-direction:column}
    .stat-label{font-size:.7rem;text-transform:uppercase;letter-spacing:.05em}
    .stat-value{font-weight:600;color:#1a1f36}
    .account-actions,.actions-cell{display:flex;gap:.5rem;flex-wrap:wrap}
    .actions-cell{gap:.25rem}
    .empty-state{text-align:center;padding:3rem}
    .empty-state p{margin:1rem 0}
    .modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:1000}
    .modal{background:#fff;border-radius:8px;padding:1.5rem;width:540px;max-height:80vh;overflow-y:auto}
    .modal-wide{width:720px}
    h3{margin:0 0 1rem;color:#1a1f36}
    table{width:100%;border-collapse:collapse}
    th,td{padding:.5rem .75rem;text-align:left;border-bottom:1px solid #e5e7eb;font-size:.875rem}
    th{font-weight:600;color:#374151}
    .error-cell{max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#dc2626}
    .empty-text{text-align:center;padding:2rem}
    .btn-primary{padding:.5rem 1rem;background:#2563eb;color:#fff;border:none;border-radius:4px;cursor:pointer}
    .btn-secondary{padding:.5rem 1rem;background:#fff;color:#374151;border:1px solid #d1d5db;border-radius:4px;cursor:pointer}
    .btn-sm{padding:.3rem .6rem;font-size:.75rem;border:1px solid #d1d5db;border-radius:4px;cursor:pointer;background:#fff}
    .btn-accent{color:#2563eb;border-color:#2563eb}
    .btn-danger{color:#dc2626;border-color:#dc2626}
    .btn-targets{color:#7c3aed;border-color:#7c3aed}
    .error{color:#ef4444;margin-top:.5rem;font-size:.875rem}
    .help-text{font-size:.85rem;margin:0 0 1rem}
    .target-add-row{display:flex;gap:.5rem;margin-bottom:1rem}
    .target-input{flex:2}.target-name-input{flex:1}
    .url-cell{max-width:350px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .url-cell a{color:#2563eb;text-decoration:none;font-size:.8rem}
    .inactive-row{opacity:.5}
    .test-results{margin-top:1rem;border:1px solid #e5e7eb;border-radius:6px;padding:1rem;background:#f9fafb}
    .test-results-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem}
    .test-results-header h4{margin:0;font-size:.9rem;color:#1a1f36}
    .test-summary{font-size:.85rem;color:#065f46;font-weight:600;margin:.25rem 0 .75rem}
    .test-posts{display:flex;flex-direction:column;gap:.5rem;max-height:300px;overflow-y:auto}
    .test-post{background:#fff;border:1px solid #e5e7eb;border-radius:4px;padding:.75rem}
    .test-post-meta{font-size:.8rem;display:flex;justify-content:space-between;margin-bottom:.25rem}
    .test-post-content{font-size:.85rem;color:#374151;white-space:pre-wrap;word-break:break-word}
    .test-post-link{font-size:.8rem;color:#2563eb;display:inline-block;margin-top:.25rem}
  `]
})
export class SocialAccountsComponent implements OnInit, OnChanges {
  accounts: SocialAccountResponse[] = [];
  @Input() toggleAdd = 0;
  showAddForm = false;
  formError = '';

  newAccount: CreateSocialAccountRequest = { platform: 'Reddit', username: '', password: '' };

  configAccount: SocialAccountResponse | null = null;
  syncConfig: UpdateSyncConfigRequest = this.defaultSyncConfig();

  jobsAccount: SocialAccountResponse | null = null;
  syncJobs: SyncJobResponse[] = [];

  targetsAccount: SocialAccountResponse | null = null;
  targets: any[] = [];
  newTargetUrl = '';
  newTargetName = '';
  testingTargetId: number | null = null;
  testResults: any = null;
  testResultsLabel = '';

  constructor(private socialService: SocialAccountService) {}

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['toggleAdd'] && !changes['toggleAdd'].firstChange) {
      this.showAddForm = !this.showAddForm;
    }
  }

  ngOnInit(): void {
    this.loadAccounts();
  }

  loadAccounts(): void {
    this.socialService.getAll().subscribe(accounts => this.accounts = accounts);
  }

  createAccount(): void {
    this.formError = '';
    if (!this.newAccount.username?.trim()) { this.formError = 'Username is required'; return; }

    // Build request — omit empty password for platforms that don't need it (e.g. Reddit)
    const req: any = { platform: this.newAccount.platform, username: this.newAccount.username };
    if (this.newAccount.password?.trim()) req.password = this.newAccount.password;
    if (this.newAccount.mfaSecret?.trim()) req.mfaSecret = this.newAccount.mfaSecret;

    this.socialService.create(req).subscribe({
      next: () => { this.cancelAdd(); this.loadAccounts(); },
      error: (err) => {
        if (err.error?.errors) {
          const msgs = Object.values(err.error.errors).flat();
          this.formError = (msgs as string[]).join('. ');
        } else {
          this.formError = err.error?.error || err.error?.title || 'Failed to connect account';
        }
      }
    });
  }

  cancelAdd(): void {
    this.showAddForm = false;
    this.newAccount = { platform: 'Reddit', username: '' };
    this.formError = '';
  }

  testLogin(account: SocialAccountResponse): void {
    this.socialService.testLogin(account.id).subscribe({
      next: () => { alert('Login test successful!'); this.loadAccounts(); },
      error: () => alert('Login test failed')
    });
  }

  syncNow(account: SocialAccountResponse): void {
    this.socialService.syncNow(account.id).subscribe({
      next: (res: any) => {
        alert(res.message || `Sync complete: ${res.postsFound} posts found`);
        this.loadAccounts();
      },
      error: (err) => alert(err.error?.error || 'Sync failed')
    });
  }

  showConfig(account: SocialAccountResponse): void {
    this.configAccount = account;
    this.syncConfig = {
      syncFrequencyMinutes: account.syncFrequencyMinutes,
      syncWindowStart: account.syncWindowStart,
      syncWindowEnd: account.syncWindowEnd,
      maxPostsPerSync: account.maxPostsPerSync,
      scrapeDepth: account.scrapeDepth,
      autoRetryMax: account.autoRetryMax
    };
  }

  saveConfig(): void {
    if (!this.configAccount) return;
    this.socialService.updateSyncConfig(this.configAccount.id, this.syncConfig).subscribe({
      next: () => { this.configAccount = null; this.loadAccounts(); },
      error: (err) => alert(err.error?.error || 'Failed to save configuration')
    });
  }

  showJobs(account: SocialAccountResponse): void {
    this.jobsAccount = account;
    this.socialService.getSyncJobs(account.id).subscribe(jobs => this.syncJobs = jobs);
  }

  confirmDelete(account: SocialAccountResponse): void {
    if (confirm(`Disconnect ${account.platform} account "${account.username}"? This will also delete all sync history.`)) {
      this.socialService.delete(account.id).subscribe(() => this.loadAccounts());
    }
  }

  getPlatformIcon(platform: string): string {
    const icons: Record<string, string> = {
      'Reddit': 'forum', 'LinkedIn': 'work', 'Facebook': 'facebook', 'Nextdoor': 'home', 'X': 'tag'
    };
    return icons[platform] || 'share';
  }

  showTargets(account: SocialAccountResponse): void {
    this.targetsAccount = account;
    this.newTargetUrl = '';
    this.newTargetName = '';
    this.socialService.getTargets(account.id).subscribe(t => this.targets = t);
  }

  addTarget(): void {
    if (!this.targetsAccount || !this.newTargetUrl.trim()) return;
    this.socialService.addTarget(this.targetsAccount.id, this.newTargetUrl.trim(), this.newTargetName.trim() || undefined).subscribe({
      next: () => {
        this.newTargetUrl = '';
        this.newTargetName = '';
        this.socialService.getTargets(this.targetsAccount!.id).subscribe(t => this.targets = t);
      },
      error: (err) => alert(err.error?.error || 'Failed to add target')
    });
  }

  toggleTargetActive(target: any): void {
    if (!this.targetsAccount) return;
    this.socialService.toggleTarget(this.targetsAccount.id, target.id).subscribe(() => {
      this.socialService.getTargets(this.targetsAccount!.id).subscribe(t => this.targets = t);
    });
  }

  removeTarget(target: any): void {
    if (!this.targetsAccount || !confirm('Remove this scrape target?')) return;
    this.socialService.deleteTarget(this.targetsAccount.id, target.id).subscribe(() => {
      this.socialService.getTargets(this.targetsAccount!.id).subscribe(t => this.targets = t);
    });
  }

  testTarget(target: any): void {
    if (!this.targetsAccount) return;
    this.testingTargetId = target.id;
    this.testResults = null;
    this.testResultsLabel = target.groupName || target.groupUrl;
    this.socialService.testTarget(this.targetsAccount.id, target.id).subscribe({
      next: (res) => {
        this.testResults = res;
        this.testingTargetId = null;
      },
      error: (err) => {
        this.testResults = { success: false, error: err.error?.error || 'Test failed', posts: [] };
        this.testingTargetId = null;
      }
    });
  }

  private defaultSyncConfig(): UpdateSyncConfigRequest {
    return { syncFrequencyMinutes: 360, syncWindowStart: null, syncWindowEnd: null, maxPostsPerSync: 50, scrapeDepth: 'medium', autoRetryMax: 2 };
  }
}
