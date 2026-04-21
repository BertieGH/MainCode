import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, NavigationEnd, RouterModule } from '@angular/router';
import { filter } from 'rxjs/operators';
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
        <div class="tenant-bar" *ngIf="tenantName">
          <div class="tenant-display">
            <div class="tenant-icon">{{ tenantInitials }}</div>
            <div class="tenant-info">
              <div class="tenant-name">{{ tenantName }}</div>
            </div>
          </div>
        </div>
        <nav>
          <div class="nav-section">Main</div>
          <a routerLink="/dashboard" routerLinkActive="active">
            <svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
            Dashboard
          </a>
          <a routerLink="/daily-list" routerLinkActive="active">
            <svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>
            Daily List
          </a>
          <a routerLink="/prospects" routerLinkActive="active">
            <svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>
            Prospect List
          </a>
          <a routerLink="/signals" routerLinkActive="active">
            <svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12h2m4-7v2m8-2v2m4 5h2M7.8 7.8l1.4 1.4m7.6-1.4l-1.4 1.4"/><circle cx="12" cy="12" r="3"/><path d="M12 2a10 10 0 0110 10"/><path d="M12 6a6 6 0 016 6"/></svg>
            Signal Log
          </a>

          <div class="nav-section">Manage</div>
          <a routerLink="/call-tracker" routerLinkActive="active">
            <svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6A19.79 19.79 0 012.12 4.18 2 2 0 014.11 2h3a2 2 0 012 1.72c.13.81.36 1.6.65 2.36a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.76.29 1.55.52 2.36.65a2 2 0 011.72 2.01z"/></svg>
            Call Tracker
          </a>
          <a routerLink="/strategies" routerLinkActive="active">
            <svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 21v-7M12 21V3M20 21v-11"/><path d="M4 14l4-4 4 4 8-8"/></svg>
            Strategies
          </a>
          <a routerLink="/keywords" routerLinkActive="active">
            <svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/><path d="M11 8v6M8 11h6"/></svg>
            Keywords
          </a>

          <div class="nav-section">Insights</div>
          <a routerLink="/analytics" routerLinkActive="active">
            <svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 20V10M12 20V4M6 20v-6"/></svg>
            Analytics
          </a>

          <div class="nav-section">Admin</div>
          <a routerLink="/users" routerLinkActive="active">
            <svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/></svg>
            Users
          </a>
          <a routerLink="/account-config" routerLinkActive="active">
            <svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09a1.65 1.65 0 00-1.08-1.51 1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09a1.65 1.65 0 001.51-1.08 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001.08 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9c.26.604.852.997 1.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1.08z"/></svg>
            Account Config
          </a>
          <a routerLink="/tenants" routerLinkActive="active">
            <svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 21h18M3 10h18M5 6l7-3 7 3M4 10v11M20 10v11M8 14v3M12 14v3M16 14v3"/></svg>
            Tenants
          </a>
          <a routerLink="/scraper-test" routerLinkActive="active">
            <svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18"/></svg>
            Scraper Test
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
      <div class="main-area">
        <div class="topbar">
          <div class="topbar-left">
            <h2>{{ pageTitle }}</h2>
            <div class="topbar-tenant" *ngIf="tenantName">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 21h18M3 10h18M5 6l7-3 7 3M4 10v11M20 10v11M8 14v3M12 14v3M16 14v3"/></svg>
              <span>{{ tenantName }}</span>
            </div>
          </div>
          <div class="topbar-right">
            <button class="icon-btn">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
            </button>
            <button class="icon-btn notification-btn">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>
              <span class="dot"></span>
            </button>
          </div>
        </div>
        <div class="content">
          <router-outlet></router-outlet>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .app-layout { display: flex; min-height: 100vh; }
    .sidebar {
      width: 250px; background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
      color: white; display: flex; flex-direction: column;
      box-shadow: 2px 0 8px rgba(0,0,0,0.15); flex-shrink: 0;
    }
    .sidebar-header { padding: 1.25rem 1.25rem; border-bottom: 1px solid rgba(255,255,255,0.08); }

    .tenant-bar { padding: 0.75rem 1rem; border-bottom: 1px solid rgba(255,255,255,0.08); }
    .tenant-display {
      display: flex; align-items: center; gap: 0.5rem;
      padding: 0.5rem 0.6rem; background: rgba(255,255,255,0.06);
      border-radius: 8px;
    }
    .tenant-icon {
      width: 28px; height: 28px; border-radius: 6px; background: #2563eb;
      display: flex; align-items: center; justify-content: center;
      font-size: 11px; font-weight: 700; flex-shrink: 0;
    }
    .tenant-info { flex: 1; min-width: 0; }
    .tenant-name {
      font-size: 0.75rem; font-weight: 600;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .logo { display: flex; align-items: center; gap: 0.75rem; }
    .logo-text { font-size: 1.3rem; font-weight: 700; letter-spacing: -0.02em;
      background: linear-gradient(135deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }

    nav { flex: 1; padding: 0.5rem 0; overflow-y: auto; }
    nav a {
      display: flex; align-items: center; gap: 0.75rem;
      padding: 0.6rem 1.5rem; border-left: 3px solid transparent;
      color: rgba(255,255,255,0.6); text-decoration: none;
      font-size: 0.875rem; font-weight: 500;
      transition: all 0.15s ease;
    }
    nav a:hover { color: rgba(255,255,255,0.9); background: rgba(255,255,255,0.05); }
    nav a.active { color: #fff; background: rgba(37,99,235,0.15); border-left-color: #2563eb; }

    .nav-svg { width: 20px; height: 20px; flex-shrink: 0; }

    .nav-section {
      padding: 1rem 1.5rem 0.3rem; font-size: 0.625rem; text-transform: uppercase;
      letter-spacing: 0.12em; color: rgba(255,255,255,0.35); font-weight: 600;
    }

    /* Main area: topbar + content */
    .main-area { flex: 1; display: flex; flex-direction: column; min-height: 100vh; }

    .topbar {
      background: #fff; border-bottom: 1px solid #e2e8f0;
      padding: 0 2rem; height: 56px;
      display: flex; align-items: center; justify-content: space-between;
      position: sticky; top: 0; z-index: 50;
    }
    .topbar-left { display: flex; align-items: center; gap: 1rem; }
    .topbar-left h2 { font-size: 1rem; font-weight: 600; margin: 0; color: #1e293b; }
    .topbar-tenant {
      display: flex; align-items: center; gap: 0.5rem;
      padding: 0.25rem 0.75rem; background: #eff6ff;
      border: 1px solid #bfdbfe; border-radius: 6px;
      font-size: 0.75rem; color: #1d4ed8; font-weight: 500;
    }
    .topbar-right { display: flex; align-items: center; gap: 0.75rem; }
    .icon-btn {
      width: 36px; height: 36px; border-radius: 8px; border: none;
      background: transparent; cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      color: #64748b; transition: all 0.15s; position: relative;
    }
    .icon-btn:hover { background: #f1f5f9; color: #1e293b; }
    .notification-btn .dot {
      position: absolute; top: 6px; right: 6px;
      width: 8px; height: 8px; background: #ef4444;
      border-radius: 50%; border: 2px solid #fff;
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
  tenantName = '';
  tenantInitials = '';
  pageTitle = 'Dashboard';

  private pageTitles: Record<string, string> = {
    'dashboard': 'Dashboard',
    'prospects': 'Prospects',
    'daily-list': 'Daily List',
    'call-tracker': 'Call Tracker',
    'strategies': 'Strategies',
    'signals': 'Signals Log',
    'analytics': 'Analytics',
    'keywords': 'Keywords',
    'users': 'Users',
    'account-config': 'Account Config',
    'tenants': 'Tenants',
  };

  constructor(private authService: AuthService, private router: Router) {
    this.authService.currentUser$.subscribe(user => {
      if (user) {
        this.userName = user.email?.split('@')[0] || 'User';
        this.userRole = user.role || '';
        this.tenantName = user.tenantName || '';
        this.tenantInitials = this.tenantName
          .split(' ')
          .map(w => w[0])
          .join('')
          .substring(0, 2)
          .toUpperCase();
      }
    });

    this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd)
    ).subscribe(e => {
      const segment = e.urlAfterRedirects.split('/').filter(Boolean)[0] || 'dashboard';
      this.pageTitle = this.pageTitles[segment] || 'Dashboard';
    });
  }

  logout(): void {
    this.authService.logout();
  }
}
