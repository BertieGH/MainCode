import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../../environments/environment';

@Component({
  selector: 'app-scraper-test',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="test-page">
      <h2>Enhanced LinkedIn Scraper — Test Lab</h2>
      <p class="subtitle">Test the enhanced scraping (contact info modal + deep post scraping) without affecting existing code.</p>

      <!-- Cookie Setup -->
      <div class="card">
        <h3>1. LinkedIn Cookie (li_at)</h3>
        <p class="help">Required for full profile data. Go to LinkedIn in your browser &rarr; DevTools (F12) &rarr; Application tab &rarr; Cookies &rarr; linkedin.com &rarr; Copy the <code>li_at</code> value.</p>
        <div class="cookie-row">
          <input type="password" [(ngModel)]="cookieValue" placeholder="Paste li_at cookie value here..." class="cookie-input" />
          <button class="btn-primary" (click)="saveCookie()" [disabled]="savingCookie">
            {{ savingCookie ? 'Saving...' : 'Save Cookie' }}
          </button>
          <button class="btn-secondary" (click)="clearCookie()" [disabled]="savingCookie">Clear</button>
        </div>
        <div class="cookie-status">
          <span *ngIf="cookieStatus?.hasCookie" class="status-ok">Cookie saved</span>
          <span *ngIf="cookieStatus && !cookieStatus.hasCookie" class="status-warn">No cookie saved — scraping will run without login</span>
          <span *ngIf="cookieStatus?.expiresAt" class="status-info"> (expires: {{ cookieStatus!.expiresAt | date:'medium' }})</span>
        </div>
        <div *ngIf="cookieMessage" class="msg" [class.error]="cookieError">{{ cookieMessage }}</div>
      </div>

      <!-- Test Controls -->
      <div class="card">
        <h3>2. Test Scrape</h3>
        <div class="url-row">
          <input type="text" [(ngModel)]="linkedInUrl" placeholder="https://www.linkedin.com/in/someone" class="url-input" />
        </div>
        <div class="btn-row">
          <button class="btn-primary" (click)="testProfile()" [disabled]="scraping">
            {{ scrapingProfile ? 'Scraping Profile...' : 'Test Profile Scrape' }}
          </button>
          <button class="btn-accent" (click)="testPosts()" [disabled]="scraping">
            {{ scrapingPosts ? 'Scraping Posts...' : 'Test Posts Scrape' }}
          </button>
          <button class="btn-both" (click)="testBoth()" [disabled]="scraping">
            {{ scrapingBoth ? 'Running Both...' : 'Test Both' }}
          </button>
        </div>
        <div *ngIf="scraping" class="progress-bar"><div class="progress-fill"></div></div>
      </div>

      <!-- Results -->
      <div *ngIf="profileResult" class="card result-card">
        <h3>Profile Result
          <span class="result-badge" [class.success]="profileResult.success" [class.fail]="!profileResult.success">
            {{ profileResult.success ? 'SUCCESS' : 'FAILED' }}
          </span>
        </h3>
        <div *ngIf="profileResult.error" class="msg error">{{ profileResult.error }}</div>
        <ng-container *ngIf="profileResult.warnings?.length">
          <div class="msg warn" *ngFor="let w of profileResult.warnings">{{ w }}</div>
        </ng-container>

        <div *ngIf="profileResult.profile" class="data-section">
          <h4>Profile Data</h4>
          <div class="data-grid">
            <div class="data-item"><span class="label">Type:</span> {{ profileResult.profile.type }}</div>
            <div class="data-item"><span class="label">Name:</span> {{ profileResult.profile.name }}</div>
            <div class="data-item full-width"><span class="label">Headline:</span> {{ profileResult.profile.headline }}</div>
            <div class="data-item full-width"><span class="label">About:</span> {{ profileResult.profile.about || '(not found)' }}</div>
          </div>
        </div>

        <div *ngIf="profileResult.profile?.contactInfo" class="data-section">
          <h4>Contact Info (Merged: Profile + Overlay)</h4>
          <pre class="contact-json">{{ formatJson(profileResult.profile.contactInfo) }}</pre>
        </div>

        <div *ngIf="profileResult.debugLog?.length" class="data-section">
          <h4 (click)="showProfileDebug = !showProfileDebug" class="toggle-header">
            Debug Log ({{ profileResult.debugLog.length }} entries) {{ showProfileDebug ? '▾' : '▸' }}
          </h4>
          <div *ngIf="showProfileDebug" class="debug-log">
            <div *ngFor="let line of profileResult.debugLog" class="debug-line"
                 [class.error-line]="line.includes('ERROR')">{{ line }}</div>
          </div>
        </div>
      </div>

      <div *ngIf="postsResult" class="card result-card">
        <h3>Posts Result
          <span class="result-badge" [class.success]="postsResult.success" [class.fail]="!postsResult.success">
            {{ postsResult.success ? 'SUCCESS' : 'FAILED' }}
          </span>
          <span class="post-count" *ngIf="postsResult.posts?.length">{{ postsResult.posts.length }} posts</span>
        </h3>
        <div *ngIf="postsResult.error" class="msg error">{{ postsResult.error }}</div>
        <div *ngIf="postsResult.warnings?.length">
          <div class="msg warn" *ngFor="let w of postsResult.warnings">{{ w }}</div>
        </div>

        <div *ngIf="postsResult.posts?.length" class="posts-list">
          <div *ngFor="let post of postsResult.posts; let i = index" class="post-card">
            <div class="post-header">
              <span class="post-num">#{{ i + 1 }}</span>
              <span class="post-date" *ngIf="post.postDate">{{ post.postDate | date:'mediumDate' }}</span>
              <span class="post-stats">{{ post.likes }} likes &middot; {{ post.comments }} comments</span>
            </div>
            <div class="post-content">{{ post.content }}</div>
            <div *ngIf="post.postUrl" class="post-url">
              <a [href]="post.postUrl" target="_blank">View on LinkedIn &rarr;</a>
            </div>
            <div *ngIf="post.commentTexts?.length" class="post-comments">
              <strong>Comments ({{ post.commentTexts.length }}):</strong>
              <div *ngFor="let c of post.commentTexts" class="comment-text">"{{ c }}"</div>
            </div>
          </div>
        </div>

        <div *ngIf="postsResult.debugLog?.length" class="data-section">
          <h4 (click)="showPostsDebug = !showPostsDebug" class="toggle-header">
            Debug Log ({{ postsResult.debugLog.length }} entries) {{ showPostsDebug ? '▾' : '▸' }}
          </h4>
          <div *ngIf="showPostsDebug" class="debug-log">
            <div *ngFor="let line of postsResult.debugLog" class="debug-line"
                 [class.error-line]="line.includes('ERROR')">{{ line }}</div>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .test-page{padding:1.5rem;max-width:1000px}
    h2{margin:0 0 .25rem;color:#1a1f36}
    .subtitle{color:#6b7280;font-size:.9rem;margin:0 0 1.5rem}
    .card{background:#fff;border-radius:8px;padding:1.25rem;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-bottom:1rem}
    .card h3{margin:0 0 .5rem;color:#1a1f36;display:flex;align-items:center;gap:.5rem}
    .help{font-size:.85rem;color:#6b7280;margin:0 0 .75rem}
    .help code{background:#f1f5f9;padding:.1rem .3rem;border-radius:3px;font-size:.8rem}
    .cookie-row{display:flex;gap:.5rem;margin-bottom:.5rem}
    .cookie-input{flex:1;padding:.5rem;border:1px solid #d1d5db;border-radius:4px;font-family:monospace;font-size:.85rem}
    .cookie-status{font-size:.85rem;margin-bottom:.5rem}
    .status-ok{color:#16a34a;font-weight:600}
    .status-warn{color:#d97706}
    .status-info{color:#6b7280}
    .url-row{margin-bottom:.75rem}
    .url-input{width:100%;padding:.5rem;border:1px solid #d1d5db;border-radius:4px;font-size:.9rem;box-sizing:border-box}
    .btn-row{display:flex;gap:.5rem;flex-wrap:wrap}
    .btn-primary{padding:.5rem 1rem;background:#2563eb;color:#fff;border:none;border-radius:4px;cursor:pointer;font-weight:500}
    .btn-primary:hover{background:#1d4ed8}
    .btn-primary:disabled{opacity:.5;cursor:not-allowed}
    .btn-secondary{padding:.5rem 1rem;background:#fff;color:#374151;border:1px solid #d1d5db;border-radius:4px;cursor:pointer}
    .btn-accent{padding:.5rem 1rem;background:#7c3aed;color:#fff;border:none;border-radius:4px;cursor:pointer;font-weight:500}
    .btn-accent:hover{background:#6d28d9}
    .btn-accent:disabled{opacity:.5;cursor:not-allowed}
    .btn-both{padding:.5rem 1rem;background:#059669;color:#fff;border:none;border-radius:4px;cursor:pointer;font-weight:500}
    .btn-both:hover{background:#047857}
    .btn-both:disabled{opacity:.5;cursor:not-allowed}
    .progress-bar{height:4px;background:#e5e7eb;border-radius:2px;margin-top:.75rem;overflow:hidden}
    .progress-fill{height:100%;background:linear-gradient(90deg,#2563eb,#7c3aed,#2563eb);width:30%;animation:progress 1.5s ease-in-out infinite}
    @keyframes progress{0%{margin-left:-30%}100%{margin-left:100%}}
    .result-card{border-left:4px solid #e5e7eb}
    .result-card:has(.success){border-left-color:#16a34a}
    .result-card:has(.fail){border-left-color:#ef4444}
    .result-badge{font-size:.7rem;padding:.15rem .5rem;border-radius:10px;font-weight:600;letter-spacing:.05em}
    .result-badge.success{background:#d1fae5;color:#065f46}
    .result-badge.fail{background:#fee2e2;color:#991b1b}
    .post-count{font-size:.8rem;color:#6b7280;font-weight:400}
    .msg{padding:.5rem .75rem;border-radius:4px;font-size:.85rem;margin-bottom:.5rem}
    .msg.error{background:#fee2e2;color:#991b1b}
    .msg.warn{background:#fef3c7;color:#92400e}
    .data-section{margin-top:1rem;padding-top:.75rem;border-top:1px solid #f3f4f6}
    .data-section h4{margin:0 0 .5rem;color:#374151;font-size:.9rem}
    .data-grid{display:grid;grid-template-columns:1fr 1fr;gap:.4rem}
    .data-item{font-size:.85rem;color:#374151}
    .data-item .label{font-weight:600;color:#1a1f36}
    .data-item.full-width{grid-column:1/-1}
    .data-item pre{background:#f8fafc;padding:.5rem;border-radius:4px;font-size:.8rem;overflow-x:auto;margin:.25rem 0 0}
    .contact-json{background:#f0fdf4;padding:.75rem;border-radius:4px;font-size:.85rem;border:1px solid #bbf7d0;white-space:pre-wrap;word-break:break-all}
    .toggle-header{cursor:pointer;user-select:none}
    .toggle-header:hover{color:#2563eb}
    .debug-log{background:#1e293b;color:#e2e8f0;padding:.75rem;border-radius:4px;font-family:monospace;font-size:.8rem;max-height:300px;overflow-y:auto}
    .debug-line{padding:.15rem 0;border-bottom:1px solid #334155}
    .debug-line.error-line{color:#fca5a5}
    .posts-list{display:flex;flex-direction:column;gap:.75rem;margin-top:.75rem}
    .post-card{background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:.75rem}
    .post-header{display:flex;gap:.75rem;align-items:center;margin-bottom:.5rem;font-size:.8rem;color:#6b7280}
    .post-num{font-weight:700;color:#1a1f36}
    .post-stats{margin-left:auto}
    .post-content{font-size:.875rem;color:#374151;line-height:1.5;white-space:pre-wrap}
    .post-url{margin-top:.5rem;font-size:.8rem}
    .post-url a{color:#2563eb;text-decoration:none}
    .post-url a:hover{text-decoration:underline}
    .post-comments{margin-top:.5rem;padding-top:.5rem;border-top:1px solid #e2e8f0;font-size:.825rem}
    .comment-text{color:#6b7280;padding:.2rem 0;font-style:italic}
  `]
})
export class ScraperTestComponent {
  private apiUrl = environment.apiUrl;

  cookieValue = '';
  cookieStatus: { hasCookie: boolean; expiresAt: string | null } | null = null;
  savingCookie = false;
  cookieMessage = '';
  cookieError = false;

  linkedInUrl = '';
  scrapingProfile = false;
  scrapingPosts = false;
  scrapingBoth = false;

  profileResult: any = null;
  postsResult: any = null;
  showProfileDebug = false;
  showPostsDebug = false;

  get scraping(): boolean {
    return this.scrapingProfile || this.scrapingPosts || this.scrapingBoth;
  }

  constructor(private http: HttpClient) {
    this.loadCookieStatus();
  }

  loadCookieStatus(): void {
    this.http.get<any>(`${this.apiUrl}/prospects/linkedin-cookie-status`).subscribe({
      next: (res) => this.cookieStatus = res,
      error: () => {}
    });
  }

  saveCookie(): void {
    if (!this.cookieValue.trim()) return;
    this.savingCookie = true;
    this.cookieMessage = '';
    this.http.put<any>(`${this.apiUrl}/prospects/linkedin-cookie`, { cookie: this.cookieValue.trim() }).subscribe({
      next: (res) => {
        this.cookieStatus = res;
        this.cookieValue = '';
        this.cookieMessage = 'LinkedIn cookie saved and encrypted.';
        this.cookieError = false;
        this.savingCookie = false;
      },
      error: () => {
        this.cookieMessage = 'Failed to save cookie';
        this.cookieError = true;
        this.savingCookie = false;
      }
    });
  }

  clearCookie(): void {
    this.savingCookie = true;
    this.http.put<any>(`${this.apiUrl}/prospects/linkedin-cookie`, { cookie: null }).subscribe({
      next: (res) => {
        this.cookieStatus = res;
        this.cookieMessage = 'Cookie cleared.';
        this.cookieError = false;
        this.savingCookie = false;
      },
      error: () => {
        this.cookieMessage = 'Failed to clear cookie';
        this.cookieError = true;
        this.savingCookie = false;
      }
    });
  }

  testProfile(): void {
    if (!this.linkedInUrl.trim()) return;
    this.scrapingProfile = true;
    this.profileResult = null;
    this.http.post<any>(`${this.apiUrl}/prospects/test-enhanced-profile`, { linkedInUrl: this.linkedInUrl.trim() }).subscribe({
      next: (res) => {
        this.profileResult = res;
        this.scrapingProfile = false;
      },
      error: (err) => {
        this.profileResult = { success: false, error: err.error?.error || 'Request failed', debugLog: [] };
        this.scrapingProfile = false;
      }
    });
  }

  testPosts(): void {
    if (!this.linkedInUrl.trim()) return;
    this.scrapingPosts = true;
    this.postsResult = null;
    this.http.post<any>(`${this.apiUrl}/prospects/test-enhanced-posts`, { linkedInUrl: this.linkedInUrl.trim() }).subscribe({
      next: (res) => {
        this.postsResult = res;
        this.scrapingPosts = false;
      },
      error: (err) => {
        this.postsResult = { success: false, error: err.error?.error || 'Request failed', debugLog: [], posts: [] };
        this.scrapingPosts = false;
      }
    });
  }

  testBoth(): void {
    if (!this.linkedInUrl.trim()) return;
    this.scrapingBoth = true;
    this.profileResult = null;
    this.postsResult = null;

    // Run profile first, then posts
    this.http.post<any>(`${this.apiUrl}/prospects/test-enhanced-profile`, { linkedInUrl: this.linkedInUrl.trim() }).subscribe({
      next: (res) => {
        this.profileResult = res;
        // Now run posts
        this.http.post<any>(`${this.apiUrl}/prospects/test-enhanced-posts`, { linkedInUrl: this.linkedInUrl.trim() }).subscribe({
          next: (postsRes) => {
            this.postsResult = postsRes;
            this.scrapingBoth = false;
          },
          error: (err) => {
            this.postsResult = { success: false, error: err.error?.error || 'Request failed', debugLog: [], posts: [] };
            this.scrapingBoth = false;
          }
        });
      },
      error: (err) => {
        this.profileResult = { success: false, error: err.error?.error || 'Request failed', debugLog: [] };
        this.scrapingBoth = false;
      }
    });
  }

  formatJson(jsonStr: string): string {
    try {
      return JSON.stringify(JSON.parse(jsonStr), null, 2);
    } catch {
      return jsonStr;
    }
  }
}
