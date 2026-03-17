import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DashboardService } from '../../core/services/dashboard.service';
import { AnalyticsResponse, CategoryBreakdownDto } from '../../core/models/dashboard.model';

@Component({
  selector: 'app-analytics',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="analytics-page">
      <div class="page-header">
        <h2>Analytics</h2>
        <select [(ngModel)]="days" (change)="load()" name="days">
          <option [ngValue]="7">Last 7 days</option>
          <option [ngValue]="30">Last 30 days</option>
          <option [ngValue]="90">Last 90 days</option>
        </select>
      </div>

      <div *ngIf="data">
        <!-- KPI Cards -->
        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-label">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2"><path d="M2 12h2m4-7v2m8-2v2m4 5h2M7.8 7.8l1.4 1.4m7.6-1.4l-1.4 1.4"/><circle cx="12" cy="12" r="3"/></svg>
              Total Signals ({{ days }}d)
            </div>
            <div class="kpi-value">{{ data.funnel.totalSignals | number }}</div>
            <div class="kpi-change" [class.up]="data.funnel.signalsTrend >= 0" [class.down]="data.funnel.signalsTrend < 0">
              <svg *ngIf="data.funnel.signalsTrend >= 0" class="trend-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
              <svg *ngIf="data.funnel.signalsTrend < 0" class="trend-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></svg>
              {{ data.funnel.signalsTrend >= 0 ? '+' : '' }}{{ data.funnel.signalsTrend }}% vs prior
            </div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>
              Prospects Generated
            </div>
            <div class="kpi-value">{{ data.funnel.totalProspects | number }}</div>
            <div class="kpi-change" [class.up]="data.funnel.prospectsTrend >= 0" [class.down]="data.funnel.prospectsTrend < 0">
              <svg *ngIf="data.funnel.prospectsTrend >= 0" class="trend-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
              <svg *ngIf="data.funnel.prospectsTrend < 0" class="trend-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></svg>
              {{ data.funnel.prospectsTrend >= 0 ? '+' : '' }}{{ data.funnel.prospectsTrend }}% vs prior
            </div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6A19.79 19.79 0 012.12 4.18 2 2 0 014.11 2h3"/></svg>
              Contacted
            </div>
            <div class="kpi-value">{{ data.funnel.contacted | number }}</div>
            <div class="kpi-change" [class.up]="data.funnel.contactedTrend >= 0" [class.down]="data.funnel.contactedTrend < 0">
              <svg *ngIf="data.funnel.contactedTrend >= 0" class="trend-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
              <svg *ngIf="data.funnel.contactedTrend < 0" class="trend-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></svg>
              {{ data.funnel.contactedTrend >= 0 ? '+' : '' }}{{ data.funnel.contactedTrend }}% vs prior
            </div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
              Converted
            </div>
            <div class="kpi-value">{{ data.funnel.converted | number }}</div>
            <div class="kpi-change up" *ngIf="data.funnel.totalProspects > 0">
              <svg class="trend-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
              {{ (data.funnel.converted / data.funnel.totalProspects * 100) | number:'1.1-1' }}% rate
            </div>
          </div>
        </div>

        <!-- Row: Signal Volume + Category Breakdown -->
        <div class="two-col">
          <div class="card">
            <div class="card-header"><h3>Signal Volume ({{ days }} Days)</h3></div>
            <div class="volume-chart">
              <div *ngFor="let d of data.signalVolume; let i = index" class="vol-bar"
                   [style.height.%]="barHeight(d.count)"
                   [style.background]="volumeBarColor(i)">
                <span class="vol-val" *ngIf="i === data.signalVolume.length - 1">{{ d.count }}</span>
              </div>
            </div>
            <div class="chart-footer" *ngIf="data.signalVolume.length">Trending over {{ data.signalVolume.length }} days</div>
            <p *ngIf="!data.signalVolume.length" class="empty">No signal data</p>
          </div>

          <div class="card">
            <div class="card-header"><h3>Category Breakdown</h3></div>
            <div class="donut-container">
              <div class="donut" [style.background]="donutGradient">
                <div class="donut-center">
                  <span class="donut-big">{{ totalSignals | number }}</span>
                  <span class="donut-small">signals</span>
                </div>
              </div>
            </div>
            <div class="legend">
              <div *ngFor="let c of data.categoryBreakdown" class="legend-item">
                <div class="legend-dot" [style.background]="categoryColor(c.category)"></div>
                {{ c.category }} ({{ c.percentage }}%)
              </div>
            </div>
            <p *ngIf="!data.categoryBreakdown.length" class="empty">No category data</p>
          </div>
        </div>

        <!-- Row: Platform Distribution + Conversion Funnel -->
        <div class="two-col">
          <div class="card">
            <div class="card-header"><h3>Platform Distribution</h3></div>
            <div class="platform-chart">
              <div *ngFor="let p of data.platformDistribution" class="platform-col">
                <div class="platform-bar" [style.height.%]="platformPct(p.count)" [style.background]="platformColor(p.platform)">
                  <span class="platform-val">{{ p.count | number }}</span>
                </div>
                <span class="platform-label">{{ p.platform }}</span>
              </div>
            </div>
            <p *ngIf="!data.platformDistribution.length" class="empty">No platform data</p>
          </div>

          <div class="card">
            <div class="card-header"><h3>Conversion Funnel</h3></div>
            <div class="funnel">
              <div class="funnel-step" [style.width.%]="100" style="background:#93c5fd;">Signals: {{ data.funnel.totalSignals | number }}</div>
              <div class="funnel-step" [style.width.%]="funnelPct(data.funnel.totalProspects, data.funnel.totalSignals)" style="background:#60a5fa;">Prospects: {{ data.funnel.totalProspects | number }}</div>
              <div class="funnel-step" [style.width.%]="funnelPct(data.funnel.contacted, data.funnel.totalSignals)" style="background:#3b82f6;">Contacted: {{ data.funnel.contacted | number }}</div>
              <div class="funnel-step" [style.width.%]="funnelPct(data.funnel.converted, data.funnel.totalSignals)" style="background:#2563eb;">Converted: {{ data.funnel.converted | number }}</div>
            </div>
          </div>
        </div>

        <!-- API Cost Tracking -->
        <div class="card">
          <div class="card-header"><h3>API Cost Tracking</h3></div>
          <table *ngIf="data.apiCosts.length">
            <thead>
              <tr><th>Service</th><th>Calls</th><th>Cost</th><th>Date</th></tr>
            </thead>
            <tbody>
              <tr *ngFor="let a of data.apiCosts">
                <td><strong>{{ a.service }}</strong></td>
                <td>{{ a.callCount | number }}</td>
                <td>{{ a.cost | currency }}</td>
                <td>{{ a.date | date:'shortDate' }}</td>
              </tr>
            </tbody>
          </table>
          <p *ngIf="!data.apiCosts.length" class="empty">No API usage data</p>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .analytics-page { padding: 1.5rem; }
    .page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; }
    .page-header h2 { margin: 0; font-size: 1.25rem; font-weight: 600; }
    .page-header select { padding: 0.5rem 0.75rem; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 0.8rem; font-family: inherit; }

    /* KPI Grid */
    .kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 1.5rem; }
    .kpi-card { background: #fff; border-radius: 12px; border: 1px solid #e2e8f0; padding: 1.25rem; }
    .kpi-label { font-size: 0.75rem; color: #64748b; font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.5rem; display: flex; align-items: center; gap: 0.4rem; }
    .kpi-value { font-size: 1.75rem; font-weight: 700; color: #1e293b; }
    .kpi-change { font-size: 0.75rem; font-weight: 600; margin-top: 0.25rem; display: flex; align-items: center; gap: 3px; }
    .kpi-change.up { color: #16a34a; }
    .kpi-change.down { color: #ef4444; }
    .trend-svg { width: 16px; height: 16px; flex-shrink: 0; }

    /* Cards */
    .card { background: #fff; border-radius: 12px; border: 1px solid #e2e8f0; padding: 1.25rem; margin-bottom: 1rem; }
    .card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
    .card-header h3 { margin: 0; font-size: 0.95rem; font-weight: 600; }
    .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }

    /* Signal Volume bars */
    .volume-chart { display: flex; align-items: flex-end; gap: 4px; height: 160px; padding: 0 4px; }
    .vol-bar { flex: 1; border-radius: 4px 4px 0 0; min-width: 8px; position: relative; transition: height 0.3s; }
    .vol-bar:hover { opacity: 0.8; }
    .vol-val { position: absolute; top: -18px; left: 50%; transform: translateX(-50%); font-size: 10px; font-weight: 600; color: #374151; }
    .chart-footer { text-align: center; font-size: 0.7rem; color: #94a3b8; margin-top: 0.75rem; }

    /* Donut chart */
    .donut-container { display: flex; align-items: center; justify-content: center; padding: 0.75rem 0; }
    .donut { width: 180px; height: 180px; border-radius: 50%; position: relative; }
    .donut-center { position: absolute; inset: 35px; background: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex-direction: column; }
    .donut-big { font-size: 1.375rem; font-weight: 700; }
    .donut-small { font-size: 0.7rem; color: #64748b; }
    .legend { display: flex; flex-wrap: wrap; gap: 0.75rem; justify-content: center; margin-top: 1rem; }
    .legend-item { display: flex; align-items: center; gap: 0.4rem; font-size: 0.75rem; color: #475569; }
    .legend-dot { width: 10px; height: 10px; border-radius: 3px; }

    /* Platform Distribution */
    .platform-chart { display: flex; align-items: flex-end; justify-content: center; gap: 2rem; height: 160px; padding-bottom: 1.5rem; }
    .platform-col { display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; }
    .platform-bar { width: 60px; border-radius: 4px 4px 0 0; position: relative; transition: height 0.3s; min-height: 20px; }
    .platform-val { position: absolute; top: -18px; left: 50%; transform: translateX(-50%); font-size: 10px; font-weight: 600; color: #374151; white-space: nowrap; }
    .platform-label { font-size: 0.7rem; color: #64748b; margin-top: 0.35rem; }

    /* Conversion Funnel */
    .funnel { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 1.25rem 0; }
    .funnel-step { height: 40px; display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 600; font-size: 0.8rem; border-radius: 4px; transition: width 0.3s; }

    /* Table */
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 0.6rem 0.75rem; text-align: left; border-bottom: 1px solid #e5e7eb; font-size: 0.85rem; }
    th { font-weight: 600; color: #374151; }
    .empty { color: #9ca3af; font-style: italic; font-size: 0.875rem; }
  `]
})
export class AnalyticsComponent implements OnInit {
  data: AnalyticsResponse | null = null;
  days = 30;
  totalSignals = 0;
  donutGradient = '';
  private maxSignalCount = 0;
  private maxPlatformCount = 0;

  private categoryColors: Record<string, string> = {
    'Home': '#16a34a', 'Auto': '#3b82f6', 'Life': '#f59e0b',
    'Health': '#ec4899', 'Commercial': '#6366f1'
  };
  private platformColors: Record<string, string> = {
    'Facebook': '#1877f2', 'LinkedIn': '#0077b5', 'Nextdoor': '#00b246',
    'Twitter': '#1da1f2', 'Reddit': '#ff4500', 'Instagram': '#e1306c'
  };

  constructor(private dashboardService: DashboardService) {}

  ngOnInit(): void { this.load(); }

  load(): void {
    this.dashboardService.getAnalytics(this.days).subscribe(d => {
      this.data = d;
      this.maxSignalCount = Math.max(...d.signalVolume.map(s => s.count), 1);
      this.maxPlatformCount = Math.max(...d.platformDistribution.map(p => p.count), 1);
      this.totalSignals = d.funnel.totalSignals;
      this.donutGradient = this.buildDonutGradient(d.categoryBreakdown);
    });
  }

  funnelPct(value: number, total: number): number {
    return total > 0 ? Math.max((value / total) * 100, 8) : 8;
  }

  barHeight(count: number): number {
    return Math.max((count / this.maxSignalCount) * 100, 5);
  }

  platformPct(count: number): number {
    return Math.max((count / this.maxPlatformCount) * 100, 8);
  }

  volumeBarColor(index: number): string {
    if (!this.data) return '#2563eb';
    const total = this.data.signalVolume.length;
    const progress = total > 1 ? index / (total - 1) : 1;
    if (progress < 0.33) return '#93c5fd';
    if (progress < 0.66) return '#60a5fa';
    if (progress < 0.85) return '#3b82f6';
    return '#2563eb';
  }

  categoryColor(category: string): string {
    return this.categoryColors[category] || '#94a3b8';
  }

  platformColor(platform: string): string {
    return this.platformColors[platform] || '#64748b';
  }

  private buildDonutGradient(categories: CategoryBreakdownDto[]): string {
    if (!categories.length) return '#e2e8f0';
    let cumulative = 0;
    const stops = categories.map(c => {
      const start = cumulative;
      cumulative += c.percentage;
      const color = this.categoryColor(c.category);
      return `${color} ${start}% ${cumulative}%`;
    });
    return `conic-gradient(${stops.join(', ')})`;
  }
}
