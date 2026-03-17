import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { DashboardService } from '../../core/services/dashboard.service';
import { AuthService } from '../../core/services/auth.service';
import { DashboardResponse } from '../../core/models/dashboard.model';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="dashboard">
      <!-- Welcome Banner -->
      <div class="welcome-banner">
        <div>
          <h1>Good {{ greeting }}, {{ userName }}!</h1>
          <p>You have {{ data?.newProspectsToday ?? 0 }} new prospects and {{ data?.followUpReminders?.length ?? 0 }} follow-ups today.</p>
        </div>
        <div class="date-badge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>
          {{ today | date:'EEEE, MMMM d, y' }}
        </div>
      </div>

      <!-- KPI Cards -->
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">
            <svg class="kpi-icon" style="color:#2563eb" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/></svg>
            New Prospects
          </div>
          <div class="kpi-value">{{ data?.newProspectsToday ?? 0 }}</div>
          <div *ngIf="data" class="kpi-change" [class.up]="data.prospectsTrend >= 0" [class.down]="data.prospectsTrend < 0">
            <svg *ngIf="data.prospectsTrend >= 0" class="trend-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
            <svg *ngIf="data.prospectsTrend < 0" class="trend-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></svg>
            {{ data.prospectsTrend >= 0 ? '+' : '' }}{{ data.prospectsTrend }}% vs yesterday
          </div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">
            <svg class="kpi-icon" style="color:#16a34a" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6A19.79 19.79 0 012.12 4.18 2 2 0 014.11 2h3a2 2 0 012 1.72c.13.81.36 1.6.65 2.36a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.76.29 1.55.52 2.36.65a2 2 0 011.72 2.01z"/></svg>
            Calls Made
          </div>
          <div class="kpi-value">{{ data?.callsMadeToday ?? 0 }}</div>
          <div *ngIf="data" class="kpi-change" [class.up]="data.callsTrend >= 0" [class.down]="data.callsTrend < 0">
            <svg *ngIf="data.callsTrend >= 0" class="trend-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
            <svg *ngIf="data.callsTrend < 0" class="trend-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></svg>
            {{ data.callsTrend >= 0 ? '+' : '' }}{{ data.callsTrend }} from yesterday
          </div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">
            <svg class="kpi-icon" style="color:#f59e0b" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 014-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 01-4 4H3"/></svg>
            Conversion Rate
          </div>
          <div class="kpi-value">{{ data?.conversionRate ?? 0 }}%</div>
          <div *ngIf="data" class="kpi-change" [class.up]="data.conversionTrend >= 0" [class.down]="data.conversionTrend < 0">
            <svg *ngIf="data.conversionTrend >= 0" class="trend-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
            <svg *ngIf="data.conversionTrend < 0" class="trend-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></svg>
            {{ data.conversionTrend >= 0 ? '+' : '' }}{{ data.conversionTrend }}% this week
          </div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">
            <svg class="kpi-icon" style="color:#8b5cf6" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12h2m4-7v2m8-2v2m4 5h2M7.8 7.8l1.4 1.4m7.6-1.4l-1.4 1.4"/><circle cx="12" cy="12" r="3"/><path d="M12 2a10 10 0 0110 10"/><path d="M12 6a6 6 0 016 6"/></svg>
            Active Signals
          </div>
          <div class="kpi-value">{{ data?.activeSignals ?? 0 }}</div>
          <div *ngIf="data" class="kpi-change" [class.up]="data.signalsTrend >= 0" [class.down]="data.signalsTrend < 0">
            <svg *ngIf="data.signalsTrend >= 0" class="trend-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
            <svg *ngIf="data.signalsTrend < 0" class="trend-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></svg>
            {{ data.signalsTrend >= 0 ? '+' : '' }}{{ data.signalsTrend }} new today
          </div>
        </div>
      </div>

      <!-- Main Grid: Prospects + Right Column -->
      <div class="dash-grid">
        <!-- Top Prospects -->
        <div class="card">
          <div class="card-header">
            <h3>Today's Top Prospects</h3>
            <span class="see-all" (click)="goTo('/prospects')">View All</span>
          </div>
          <div *ngIf="data?.topProspects?.length; else noProspects">
            <div *ngFor="let p of data!.topProspects" class="prospect-card">
              <div class="score-circle" [class]="scoreCircleClass(p.compositeScore)">{{ p.compositeScore }}</div>
              <div class="prospect-info">
                <div class="prospect-name">{{ p.name }}</div>
                <div class="prospect-meta">
                  <span class="chip" [class]="'chip chip-' + (p.category || 'other').toLowerCase()">{{ p.category || 'Other' }}</span>
                  <span class="urgency-badge" [class]="'urgency-badge urgency-' + p.urgency.toLowerCase()">{{ p.urgency }}</span>
                  <span class="platform-tag" *ngIf="p.platform">{{ p.platform }}</span>
                </div>
              </div>
            </div>
          </div>
          <ng-template #noProspects><p class="empty">No prospects yet</p></ng-template>
        </div>

        <!-- Right Column: Follow-ups + Activity -->
        <div class="right-col">
          <div class="card">
            <div class="card-header"><h3>Follow-Up Reminders</h3></div>
            <div *ngIf="data?.followUpReminders?.length; else noFollowups">
              <div *ngFor="let f of data!.followUpReminders" class="followup-item">
                <span class="followup-time">{{ f.followUpTime || (f.followUpDate | date:'shortTime') }}</span>
                <span class="followup-name">{{ f.prospectName }}</span>
              </div>
            </div>
            <ng-template #noFollowups><p class="empty">No follow-ups scheduled</p></ng-template>
          </div>

          <div class="card">
            <div class="card-header"><h3>Recent Activity</h3></div>
            <div *ngIf="data?.recentActivity?.length; else noActivity">
              <div *ngFor="let a of data!.recentActivity" class="activity-item">
                <div class="activity-icon" [style.background]="activityColor(a.actionType)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2">
                    <circle *ngIf="a.actionType === 'ProspectCreated'" cx="12" cy="7" r="4"/><path *ngIf="a.actionType === 'ProspectCreated'" d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/>
                    <path *ngIf="a.actionType === 'CallLogged'" d="M22 16.92v3a2 2 0 01-2.18 2 19.5 19.5 0 01-8.63-3.07 19.5 19.5 0 01-6-6A19.5 19.5 0 012.12 4.18 2 2 0 014.11 2h3"/>
                    <path *ngIf="a.actionType !== 'ProspectCreated' && a.actionType !== 'CallLogged'" d="M12 2a10 10 0 0110 10M12 6a6 6 0 016 6"/><circle *ngIf="a.actionType !== 'ProspectCreated' && a.actionType !== 'CallLogged'" cx="12" cy="12" r="3"/>
                  </svg>
                </div>
                <div class="activity-text">
                  {{ a.description }}
                  <div class="activity-time">{{ a.createdAt | date:'shortTime' }}</div>
                </div>
              </div>
            </div>
            <ng-template #noActivity><p class="empty">No recent activity</p></ng-template>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .dashboard { padding: 1.5rem; }

    /* Welcome Banner */
    .welcome-banner {
      background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
      color: #fff; border-radius: 12px; padding: 1.5rem 1.75rem;
      margin-bottom: 1.5rem; display: flex; align-items: center; justify-content: space-between;
    }
    .welcome-banner h1 { font-size: 1.375rem; font-weight: 700; margin: 0 0 0.25rem; }
    .welcome-banner p { font-size: 0.875rem; opacity: 0.85; margin: 0; }
    .date-badge {
      background: rgba(255,255,255,0.2); padding: 0.5rem 1rem;
      border-radius: 8px; font-size: 0.8rem; font-weight: 500;
      display: flex; align-items: center; gap: 0.4rem; white-space: nowrap;
    }

    /* KPI Grid */
    .kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 1.5rem; }
    .kpi-card { background: #fff; border-radius: 12px; border: 1px solid #e2e8f0; padding: 1.25rem; }
    .kpi-label {
      font-size: 0.75rem; color: #64748b; font-weight: 500;
      text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.5rem;
      display: flex; align-items: center; gap: 0.4rem;
    }
    .kpi-icon { flex-shrink: 0; }
    .kpi-value { font-size: 1.75rem; font-weight: 700; color: #1e293b; }
    .kpi-change { font-size: 0.75rem; font-weight: 600; margin-top: 0.25rem; display: flex; align-items: center; gap: 3px; }
    .kpi-change.up { color: #16a34a; }
    .kpi-change.down { color: #ef4444; }
    .trend-svg { width: 16px; height: 16px; flex-shrink: 0; }

    /* Main Grid */
    .dash-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 1.5rem; }
    .right-col { display: flex; flex-direction: column; gap: 1.5rem; }

    /* Cards */
    .card { background: #fff; border-radius: 12px; border: 1px solid #e2e8f0; padding: 1.25rem; }
    .card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
    .card-header h3 { margin: 0; font-size: 0.95rem; font-weight: 600; }
    .see-all { font-size: 0.8rem; color: #2563eb; cursor: pointer; font-weight: 500; }
    .see-all:hover { text-decoration: underline; }

    /* Prospect Cards */
    .prospect-card {
      border: 1px solid #e2e8f0; border-radius: 10px; padding: 1rem;
      margin-bottom: 0.75rem; display: flex; align-items: center; gap: 1rem;
      transition: box-shadow 0.15s; cursor: pointer; background: #fff;
    }
    .prospect-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
    .score-circle {
      width: 48px; height: 48px; border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-weight: 700; font-size: 1rem; color: #fff; flex-shrink: 0;
    }
    .score-high { background: #16a34a; }
    .score-medium { background: #f59e0b; }
    .score-low { background: #94a3b8; }
    .prospect-info { flex: 1; min-width: 0; }
    .prospect-name { font-weight: 600; font-size: 0.875rem; margin-bottom: 0.35rem; }
    .prospect-meta { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
    .chip {
      display: inline-flex; padding: 0.1rem 0.5rem; border-radius: 4px;
      font-size: 0.7rem; font-weight: 600;
    }
    .chip-home { background: #dcfce7; color: #166534; }
    .chip-auto { background: #dbeafe; color: #1d4ed8; }
    .chip-life { background: #fef3c7; color: #92400e; }
    .chip-health { background: #fce7f3; color: #9d174d; }
    .chip-commercial { background: #e0e7ff; color: #3730a3; }
    .chip-other { background: #f1f5f9; color: #475569; }
    .urgency-badge {
      font-size: 0.65rem; font-weight: 700; padding: 0.1rem 0.5rem;
      border-radius: 4px; text-transform: uppercase;
    }
    .urgency-hot { background: #fef2f2; color: #dc2626; }
    .urgency-warm { background: #fff7ed; color: #ea580c; }
    .urgency-cool { background: #f0f9ff; color: #0284c7; }
    .platform-tag { font-size: 0.7rem; color: #64748b; font-weight: 500; }

    /* Follow-up Items */
    .followup-item {
      display: flex; align-items: center; gap: 0.75rem;
      padding: 0.65rem 0; border-bottom: 1px solid #f1f5f9;
    }
    .followup-item:last-child { border-bottom: none; }
    .followup-time { font-size: 0.8rem; font-weight: 600; color: #2563eb; min-width: 60px; }
    .followup-name { font-size: 0.8rem; color: #374151; }

    /* Activity Items */
    .activity-item {
      display: flex; align-items: flex-start; gap: 0.65rem;
      padding: 0.65rem 0; border-bottom: 1px solid #f1f5f9;
    }
    .activity-item:last-child { border-bottom: none; }
    .activity-icon {
      width: 28px; height: 28px; border-radius: 6px;
      display: flex; align-items: center; justify-content: center; flex-shrink: 0;
    }
    .activity-text { font-size: 0.8rem; color: #374151; }
    .activity-time { color: #94a3b8; font-size: 0.7rem; margin-top: 0.15rem; }

    .empty { color: #9ca3af; font-style: italic; font-size: 0.875rem; }
  `]
})
export class DashboardComponent implements OnInit {
  data: DashboardResponse | null = null;
  userName = 'User';
  greeting = 'morning';
  today = new Date();

  constructor(
    private dashboardService: DashboardService,
    private authService: AuthService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.dashboardService.getDashboard().subscribe(d => this.data = d);
    this.authService.currentUser$.subscribe(u => {
      if (u) this.userName = u.email?.split('@')[0] || 'User';
    });
    const h = new Date().getHours();
    this.greeting = h < 12 ? 'morning' : h < 17 ? 'afternoon' : 'evening';
  }

  scoreCircleClass(score: number): string {
    if (score >= 70) return 'score-circle score-high';
    if (score >= 40) return 'score-circle score-medium';
    return 'score-circle score-low';
  }

  activityColor(type: string): string {
    switch (type) {
      case 'CallLogged': return '#16a34a';
      case 'ProspectCreated': return '#2563eb';
      default: return '#8b5cf6';
    }
  }

  goTo(path: string): void {
    this.router.navigate([path]);
  }
}
