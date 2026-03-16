import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { DashboardService } from '../../core/services/dashboard.service';
import { DashboardResponse } from '../../core/models/dashboard.model';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="dashboard">
      <div class="welcome">
        <h2>Dashboard</h2>
      </div>

      <div class="kpi-grid">
        <div class="kpi-card">
          <span class="kpi-value">{{ data?.newProspectsToday ?? 0 }}</span>
          <span class="kpi-label">New Prospects Today</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-value">{{ data?.callsMadeToday ?? 0 }}</span>
          <span class="kpi-label">Calls Made Today</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-value">{{ data?.conversionRate ?? 0 }}%</span>
          <span class="kpi-label">Conversion Rate</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-value">{{ data?.activeSignals ?? 0 }}</span>
          <span class="kpi-label">Active Signals (7d)</span>
        </div>
      </div>

      <div class="two-col">
        <div class="card">
          <h3>Top Prospects</h3>
          <div *ngIf="data?.topProspects?.length; else noProspects">
            <div *ngFor="let p of data!.topProspects" class="prospect-row">
              <div class="prospect-info">
                <strong>{{ p.name }}</strong>
                <span class="sub-text">{{ p.category || p.platform }}</span>
              </div>
              <div class="prospect-score">
                <span class="score" [class]="scoreClass(p.compositeScore)">{{ p.compositeScore }}</span>
                <span class="urgency-badge" [class]="'urgency-' + p.urgency.toLowerCase()">{{ p.urgency }}</span>
              </div>
            </div>
          </div>
          <ng-template #noProspects><p class="empty">No prospects yet</p></ng-template>
        </div>

        <div class="card">
          <h3>Follow-Up Reminders</h3>
          <div *ngIf="data?.followUpReminders?.length; else noFollowups">
            <div *ngFor="let f of data!.followUpReminders" class="followup-row">
              <div>
                <strong>{{ f.prospectName }}</strong>
                <span class="sub-text">{{ f.followUpDate | date:'mediumDate' }}</span>
              </div>
              <span class="sub-text" *ngIf="f.notes">{{ f.notes }}</span>
            </div>
          </div>
          <ng-template #noFollowups><p class="empty">No follow-ups scheduled</p></ng-template>
        </div>
      </div>

      <div class="card">
        <h3>Recent Activity</h3>
        <div *ngIf="data?.recentActivity?.length; else noActivity">
          <div *ngFor="let a of data!.recentActivity" class="activity-row">
            <span class="activity-type">{{ a.actionType }}</span>
            <span>{{ a.description }}</span>
            <span class="sub-text">{{ a.userName }} — {{ a.createdAt | date:'short' }}</span>
          </div>
        </div>
        <ng-template #noActivity><p class="empty">No recent activity</p></ng-template>
      </div>
    </div>
  `,
  styles: [`
    .dashboard { padding: 1.5rem; }
    .welcome h2 { margin: 0 0 1.5rem; }
    .kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 1.5rem; }
    .kpi-card { background: white; padding: 1.25rem; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }
    .kpi-value { display: block; font-size: 2rem; font-weight: 700; color: #1a1f36; }
    .kpi-label { display: block; color: #6b7280; margin-top: 0.25rem; font-size: 0.85rem; }
    .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem; }
    .card { background: white; border-radius: 8px; padding: 1.25rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .card h3 { margin: 0 0 1rem; font-size: 1rem; color: #1a1f36; }
    .prospect-row { display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0; border-bottom: 1px solid #f3f4f6; }
    .prospect-info { display: flex; flex-direction: column; }
    .prospect-score { display: flex; align-items: center; gap: 0.5rem; }
    .score { font-weight: 700; padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.85rem; }
    .score-high { background: #d1fae5; color: #065f46; }
    .score-med { background: #fef3c7; color: #92400e; }
    .score-low { background: #e5e7eb; color: #374151; }
    .urgency-badge { padding: 0.1rem 0.35rem; border-radius: 10px; font-size: 0.65rem; font-weight: 600; }
    .urgency-hot { background: #fee2e2; color: #991b1b; }
    .urgency-warm { background: #fef3c7; color: #92400e; }
    .urgency-cool { background: #dbeafe; color: #1d4ed8; }
    .followup-row { padding: 0.5rem 0; border-bottom: 1px solid #f3f4f6; }
    .activity-row { display: flex; gap: 0.75rem; align-items: center; padding: 0.4rem 0; border-bottom: 1px solid #f3f4f6; font-size: 0.85rem; }
    .activity-type { background: #ede9fe; color: #5b21b6; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.7rem; font-weight: 600; white-space: nowrap; }
    .sub-text { font-size: 0.75rem; color: #6b7280; }
    .empty { color: #9ca3af; font-style: italic; font-size: 0.875rem; }
  `]
})
export class DashboardComponent implements OnInit {
  data: DashboardResponse | null = null;

  constructor(private dashboardService: DashboardService) {}

  ngOnInit(): void {
    this.dashboardService.getDashboard().subscribe(d => this.data = d);
  }

  scoreClass(score: number): string {
    if (score >= 70) return 'score score-high';
    if (score >= 40) return 'score score-med';
    return 'score score-low';
  }
}
