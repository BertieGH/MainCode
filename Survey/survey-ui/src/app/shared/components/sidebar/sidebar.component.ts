import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';
import { AuthResponse, UserRole } from '../../../core/models/user.model';
import { Subscription } from 'rxjs';

interface NavItem {
  icon: string;
  label: string;
  route: string;
  badge?: string;
  adminOnly?: boolean;
  roles?: string[];
}

interface NavSection {
  title: string;
  items: NavItem[];
}

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [CommonModule, RouterModule],
  template: `
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="logo">S</div>
        <div>
          <h1>SurveyHub</h1>
          <span>CRM Integration</span>
        </div>
      </div>

      <nav class="sidebar-nav">
        <div *ngFor="let section of filteredSections">
          <div class="nav-section">{{ section.title }}</div>
          <a *ngFor="let item of section.items"
             class="nav-item"
             [routerLink]="item.route"
             routerLinkActive="active"
             [routerLinkActiveOptions]="{ exact: item.route === '/analytics/dashboard' }">
            <span class="material-icons-outlined">{{ item.icon }}</span>
            {{ item.label }}
            <span *ngIf="item.badge" class="badge">{{ item.badge }}</span>
          </a>
        </div>
      </nav>

      <div class="sidebar-footer">
        <div class="avatar">{{ userInitial }}</div>
        <div class="user-info">
          <div>{{ currentUser?.username || 'User' }}</div>
          <div class="role">{{ currentUser?.role || '' }}</div>
        </div>
        <button class="logout-btn" (click)="logout()" title="Logout">
          <span class="material-icons-outlined">logout</span>
        </button>
      </div>
    </aside>
  `,
  styles: [`
    .sidebar {
      width: 260px;
      background: #1a1a2e;
      color: #fff;
      display: flex;
      flex-direction: column;
      position: fixed;
      top: 0;
      left: 0;
      bottom: 0;
      z-index: 100;
      overflow-y: auto;
    }

    .sidebar-header {
      padding: 24px 20px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .logo {
      width: 36px;
      height: 36px;
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 16px;
      flex-shrink: 0;
    }

    .sidebar-header h1 {
      font-size: 18px;
      font-weight: 600;
      margin: 0;
    }

    .sidebar-header span {
      font-size: 11px;
      color: rgba(255, 255, 255, 0.5);
    }

    .sidebar-nav {
      flex: 1;
      overflow-y: auto;
    }

    .nav-section {
      padding: 16px 12px 8px;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 1px;
      color: rgba(255, 255, 255, 0.35);
    }

    .nav-item {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 10px 16px;
      margin: 2px 8px;
      border-radius: 8px;
      cursor: pointer;
      color: rgba(255, 255, 255, 0.65);
      transition: all 0.2s;
      font-size: 14px;
      font-weight: 400;
      text-decoration: none;
    }

    .nav-item:hover {
      background: rgba(255, 255, 255, 0.08);
      color: #fff;
    }

    .nav-item.active {
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      color: #fff;
      font-weight: 500;
      box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
    }

    .nav-item .material-icons-outlined {
      font-size: 20px;
    }

    .badge {
      margin-left: auto;
      background: rgba(255, 255, 255, 0.15);
      padding: 2px 8px;
      border-radius: 10px;
      font-size: 11px;
    }

    .active .badge {
      background: rgba(255, 255, 255, 0.25);
    }

    .sidebar-footer {
      margin-top: auto;
      padding: 16px;
      border-top: 1px solid rgba(255, 255, 255, 0.08);
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .avatar {
      width: 36px;
      height: 36px;
      border-radius: 50%;
      background: linear-gradient(135deg, #f472b6, #6366f1);
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 600;
      font-size: 14px;
      flex-shrink: 0;
    }

    .user-info {
      font-size: 13px;
      flex: 1;
      min-width: 0;
    }

    .user-info > div:first-child {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .user-info .role {
      font-size: 11px;
      color: rgba(255, 255, 255, 0.45);
    }

    .logout-btn {
      background: none;
      border: none;
      color: rgba(255, 255, 255, 0.45);
      cursor: pointer;
      padding: 4px;
      border-radius: 4px;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.2s;
    }

    .logout-btn:hover {
      color: #fff;
      background: rgba(255, 255, 255, 0.1);
    }

    .logout-btn .material-icons-outlined {
      font-size: 20px;
    }
  `]
})
export class SidebarComponent implements OnInit, OnDestroy {
  currentUser: AuthResponse | null = null;
  userInitial = 'U';
  private subscription?: Subscription;

  navSections: NavSection[] = [
    {
      title: 'Main',
      items: [
        { icon: 'dashboard', label: 'Dashboard', route: '/analytics/dashboard', roles: ['Admin', 'Manager'] },
        { icon: 'quiz', label: 'Question Bank', route: '/question-bank' },
        { icon: 'assignment', label: 'Build Survey', route: '/surveys' },
        { icon: 'category', label: 'Categories', route: '/question-bank/categories' },
      ]
    },
    {
      title: 'Execution',
      items: [
        { icon: 'play_circle', label: 'Take Survey', route: '/execute' },
      ]
    },
    {
      title: 'Analytics',
      items: [
        { icon: 'bar_chart', label: 'Analytics', route: '/analytics', roles: ['Admin', 'Manager'] },
      ]
    },
    {
      title: 'System',
      items: [
        { icon: 'sync_alt', label: 'CRM Mappings', route: '/field-mapping', roles: ['Admin', 'Manager'] },
        { icon: 'people', label: 'User Management', route: '/users', adminOnly: true },
      ]
    }
  ];

  filteredSections: NavSection[] = [];

  constructor(private authService: AuthService) {}

  ngOnInit(): void {
    this.subscription = this.authService.currentUser$.subscribe(user => {
      this.currentUser = user;
      this.userInitial = user?.username?.charAt(0).toUpperCase() || 'U';
      this.updateFilteredSections();
    });
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
  }

  logout(): void {
    this.authService.logout();
  }

  private updateFilteredSections(): void {
    const isAdmin = this.currentUser?.role === UserRole.Admin;
    const userRole = this.currentUser?.role;
    this.filteredSections = this.navSections
      .map(section => ({
        ...section,
        items: section.items.filter(item => {
          if (item.adminOnly && !isAdmin) return false;
          if (item.roles && (!userRole || !item.roles.includes(userRole))) return false;
          return true;
        })
      }))
      .filter(section => section.items.length > 0);
  }
}
