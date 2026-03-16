import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';

@Component({
  selector: 'app-layout',
  standalone: true,
  imports: [CommonModule, RouterModule],
  template: `
    <div class="app-layout">
      <aside class="sidebar">
        <div class="sidebar-header">
          <div class="logo">
            <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
              <rect width="32" height="32" rx="8" fill="#2563eb"/>
              <path d="M10 22V10l6 4-6 4zm7-8l6 4-6 4V14z" fill="white"/>
            </svg>
            <span class="logo-text">LeadPulse</span>
          </div>
        </div>
        <nav>
          <a routerLink="/dashboard" routerLinkActive="active">
            <span class="nav-icon" style="background:#3b82f6" innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>'></span>
            Dashboard
          </a>
          <a routerLink="/prospects" routerLinkActive="active">
            <span class="nav-icon" style="background:#8b5cf6" innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>'></span>
            Prospects
          </a>
          <a routerLink="/daily-list" routerLinkActive="active">
            <span class="nav-icon" style="background:#06b6d4" innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="M9 14l2 2 4-4"/></svg>'></span>
            Daily List
          </a>

          <div class="nav-section">Manage</div>
          <a routerLink="/call-tracker" routerLinkActive="active">
            <span class="nav-icon" style="background:#10b981" innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6A19.79 19.79 0 012.12 4.18 2 2 0 014.11 2h3a2 2 0 012 1.72c.13.81.36 1.6.65 2.36a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.76.29 1.55.52 2.36.65a2 2 0 011.72 2.01z"/></svg>'></span>
            Call Tracker
          </a>
          <a routerLink="/strategies" routerLinkActive="active">
            <span class="nav-icon" style="background:#f59e0b" innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>'></span>
            Strategies
          </a>
          <a routerLink="/signals" routerLinkActive="active">
            <span class="nav-icon" style="background:#ef4444" innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M2 12h2m4-7v2m8-2v2m4 5h2M7.8 7.8l1.4 1.4m7.6-1.4l-1.4 1.4"/><circle cx="12" cy="12" r="3"/><path d="M12 2a10 10 0 0110 10"/><path d="M12 6a6 6 0 016 6"/></svg>'></span>
            Signals Log
          </a>

          <div class="nav-section">Insights</div>
          <a routerLink="/analytics" routerLinkActive="active">
            <span class="nav-icon" style="background:#ec4899" innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M18 20V10M12 20V4M6 20v-6"/></svg>'></span>
            Analytics
          </a>

          <div class="nav-section">Admin</div>
          <a routerLink="/keywords" routerLinkActive="active">
            <span class="nav-icon" style="background:#14b8a6" innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 11-7.78 7.78 5.5 5.5 0 017.78-7.78zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>'></span>
            Keywords
          </a>
          <a routerLink="/users" routerLinkActive="active">
            <span class="nav-icon" style="background:#6366f1" innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/></svg>'></span>
            Users
          </a>
          <a routerLink="/account-config" routerLinkActive="active">
            <span class="nav-icon" style="background:#64748b" innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09a1.65 1.65 0 00-1.08-1.51 1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09a1.65 1.65 0 001.51-1.08 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001.08 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9c.26.604.852.997 1.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1.08z"/></svg>'></span>
            Account Config
          </a>
          <a routerLink="/tenants" routerLinkActive="active">
            <span class="nav-icon" style="background:#78716c" innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M3 21h18M3 10h18M5 6l7-3 7 3M4 10v11M20 10v11M8 14v3M12 14v3M16 14v3"/></svg>'></span>
            Tenants
          </a>
        </nav>
        <div class="sidebar-footer">
          <div class="user-info">
            <div class="user-avatar">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            </div>
            <div class="user-details">
              <div class="user-name">{{ userName }}</div>
              <div class="user-role">{{ userRole }}</div>
            </div>
          </div>
          <button (click)="logout()">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"/></svg>
            Logout
          </button>
        </div>
      </aside>
      <main class="content">
        <router-outlet></router-outlet>
      </main>
    </div>
  `,
  styles: [`
    .app-layout { display: flex; min-height: 100vh; }
    .sidebar {
      width: 250px; background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
      color: white; display: flex; flex-direction: column;
      box-shadow: 2px 0 8px rgba(0,0,0,0.15);
    }
    .sidebar-header { padding: 1.25rem 1.25rem; border-bottom: 1px solid rgba(255,255,255,0.08); }
    .logo { display: flex; align-items: center; gap: 0.75rem; }
    .logo-text { font-size: 1.3rem; font-weight: 700; letter-spacing: -0.02em;
      background: linear-gradient(135deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }

    nav { flex: 1; padding: 0.75rem 0; overflow-y: auto; }
    nav a {
      display: flex; align-items: center; gap: 0.75rem;
      padding: 0.5rem 1rem; margin: 2px 0.6rem; border-radius: 8px;
      color: rgba(255,255,255,0.65); text-decoration: none;
      font-size: 0.875rem; font-weight: 500;
      transition: all 0.15s ease;
    }
    nav a:hover { color: white; background: rgba(255,255,255,0.08); }
    nav a.active { color: white; background: rgba(37,99,235,0.25); }
    nav a.active .nav-icon { box-shadow: 0 0 0 2px rgba(255,255,255,0.3); }

    .nav-icon {
      width: 30px; height: 30px; border-radius: 6px;
      display: flex; align-items: center; justify-content: center;
      flex-shrink: 0;
    }
    .nav-icon svg { width: 16px; height: 16px; }

    .nav-section {
      padding: 1.1rem 1.25rem 0.35rem; font-size: 0.65rem; text-transform: uppercase;
      letter-spacing: 0.12em; color: rgba(255,255,255,0.3); font-weight: 600;
    }

    .content { flex: 1; background: #f1f5f9; overflow-y: auto; }

    .sidebar-footer {
      padding: 0.75rem 1rem; border-top: 1px solid rgba(255,255,255,0.08);
      display: flex; flex-direction: column; gap: 0.6rem;
    }
    .user-info { display: flex; align-items: center; gap: 0.6rem; padding: 0.25rem 0; }
    .user-avatar {
      width: 32px; height: 32px; border-radius: 8px;
      background: linear-gradient(135deg, #3b82f6, #8b5cf6);
      display: flex; align-items: center; justify-content: center;
      flex-shrink: 0;
    }
    .user-avatar svg { width: 18px; height: 18px; color: white; }
    .user-details { min-width: 0; }
    .user-name { font-size: 0.8rem; font-weight: 600; color: rgba(255,255,255,0.9); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .user-role { font-size: 0.7rem; color: rgba(255,255,255,0.45); }
    .sidebar-footer button {
      width: 100%; padding: 0.45rem; background: rgba(255,255,255,0.06);
      color: rgba(255,255,255,0.6); border: 1px solid rgba(255,255,255,0.08);
      border-radius: 6px; cursor: pointer; font-size: 0.8rem;
      display: flex; align-items: center; justify-content: center; gap: 0.4rem;
      transition: all 0.15s ease;
    }
    .sidebar-footer button:hover { background: rgba(239,68,68,0.15); color: #fca5a5; border-color: rgba(239,68,68,0.3); }
  `]
})
export class LayoutComponent {
  userName = '';
  userRole = '';

  constructor(private authService: AuthService) {
    this.authService.currentUser$.subscribe(user => {
      if (user) {
        this.userName = user.email?.split('@')[0] || 'User';
        this.userRole = user.role || '';
      }
    });
  }

  logout(): void {
    this.authService.logout();
  }
}
