import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DashboardService } from '../../core/services/dashboard.service';
import { AnalyticsResponse } from '../../core/models/dashboard.model';

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
        <!-- Funnel -->
        <div class="card funnel-card">
          <h3>Conversion Funnel</h3>
          <div class="funnel">
            <div class="funnel-step">
              <div class="funnel-bar" [style.width.%]="100">{{ data.funnel.totalSignals }}</div>
              <span>Signals</span>
            </div>
            <div class="funnel-step">
              <div class="funnel-bar bar-2" [style.width.%]="funnelPct(data.funnel.totalProspects, data.funnel.totalSignals)">{{ data.funnel.totalProspects }}</div>
              <span>Prospects</span>
            </div>
            <div class="funnel-step">
              <div class="funnel-bar bar-3" [style.width.%]="funnelPct(data.funnel.contacted, data.funnel.totalSignals)">{{ data.funnel.contacted }}</div>
              <span>Contacted</span>
            </div>
            <div class="funnel-step">
              <div class="funnel-bar bar-4" [style.width.%]="funnelPct(data.funnel.converted, data.funnel.totalSignals)">{{ data.funnel.converted }}</div>
              <span>Converted</span>
            </div>
          </div>
        </div>

        <div class="two-col">
          <!-- Signal Volume -->
          <div class="card">
            <h3>Signal Volume by Day</h3>
            <div class="bar-chart">
              <div *ngFor="let d of data.signalVolume" class="chart-bar-container">
                <div class="chart-bar" [style.height.%]="barHeight(d.count)">{{ d.count }}</div>
                <span class="bar-label">{{ d.date | date:'M/d' }}</span>
              </div>
            </div>
            <p *ngIf="!data.signalVolume.length" class="empty">No signal data</p>
          </div>

          <!-- Category Breakdown -->
          <div class="card">
            <h3>Category Breakdown</h3>
            <div *ngFor="let c of data.categoryBreakdown" class="breakdown-row">
              <div class="breakdown-label">{{ c.category }}</div>
              <div class="breakdown-bar-bg">
                <div class="breakdown-bar" [style.width.%]="c.percentage"></div>
              </div>
              <div class="breakdown-value">{{ c.count }} ({{ c.percentage }}%)</div>
            </div>
            <p *ngIf="!data.categoryBreakdown.length" class="empty">No category data</p>
          </div>
        </div>

        <div class="two-col">
          <!-- Platform Distribution -->
          <div class="card">
            <h3>Platform Distribution</h3>
            <div *ngFor="let p of data.platformDistribution" class="breakdown-row">
              <div class="breakdown-label">{{ p.platform }}</div>
              <div class="breakdown-bar-bg">
                <div class="breakdown-bar platform-bar" [style.width.%]="platformPct(p.count)"></div>
              </div>
              <div class="breakdown-value">{{ p.count }}</div>
            </div>
            <p *ngIf="!data.platformDistribution.length" class="empty">No platform data</p>
          </div>

          <!-- API Costs -->
          <div class="card">
            <h3>API Cost Tracking</h3>
            <table *ngIf="data.apiCosts.length">
              <thead><tr><th>Service</th><th>Calls</th><th>Cost</th><th>Date</th></tr></thead>
              <tbody>
                <tr *ngFor="let a of data.apiCosts">
                  <td>{{ a.service }}</td>
                  <td>{{ a.callCount }}</td>
                  <td>{{ a.cost | currency }}</td>
                  <td>{{ a.date | date:'shortDate' }}</td>
                </tr>
              </tbody>
            </table>
            <p *ngIf="!data.apiCosts.length" class="empty">No API usage data</p>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .analytics-page { padding: 1.5rem; }
    .page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; }
    .page-header h2 { margin: 0; }
    .page-header select { padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px; }
    .card { background: white; border-radius: 8px; padding: 1.25rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 1rem; }
    .card h3 { margin: 0 0 1rem; font-size: 1rem; color: #1a1f36; }
    .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    .funnel { display: flex; flex-direction: column; gap: 0.5rem; }
    .funnel-step { display: flex; align-items: center; gap: 0.75rem; }
    .funnel-step span { font-size: 0.85rem; color: #374151; min-width: 80px; }
    .funnel-bar { background: #2563eb; color: white; padding: 0.4rem 0.75rem; border-radius: 4px; font-weight: 600; font-size: 0.85rem; min-width: 40px; text-align: center; transition: width 0.3s; }
    .bar-2 { background: #3b82f6; }
    .bar-3 { background: #60a5fa; }
    .bar-4 { background: #93c5fd; }
    .bar-chart { display: flex; align-items: flex-end; gap: 4px; height: 150px; padding-top: 1rem; }
    .chart-bar-container { display: flex; flex-direction: column; align-items: center; flex: 1; }
    .chart-bar { background: #2563eb; color: white; font-size: 0.65rem; text-align: center; border-radius: 2px 2px 0 0; min-height: 20px; display: flex; align-items: center; justify-content: center; width: 100%; }
    .bar-label { font-size: 0.65rem; color: #6b7280; margin-top: 2px; }
    .breakdown-row { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem; }
    .breakdown-label { min-width: 100px; font-size: 0.85rem; font-weight: 500; }
    .breakdown-bar-bg { flex: 1; background: #f3f4f6; border-radius: 4px; height: 20px; overflow: hidden; }
    .breakdown-bar { background: #2563eb; height: 100%; border-radius: 4px; transition: width 0.3s; }
    .platform-bar { background: #8b5cf6; }
    .breakdown-value { font-size: 0.85rem; font-weight: 600; min-width: 80px; text-align: right; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 0.5rem; text-align: left; border-bottom: 1px solid #e5e7eb; font-size: 0.85rem; }
    th { font-weight: 600; color: #374151; }
    .empty { color: #9ca3af; font-style: italic; font-size: 0.875rem; }
  `]
})
export class AnalyticsComponent implements OnInit {
  data: AnalyticsResponse | null = null;
  days = 30;
  private maxSignalCount = 0;
  private maxPlatformCount = 0;

  constructor(private dashboardService: DashboardService) {}

  ngOnInit(): void { this.load(); }

  load(): void {
    this.dashboardService.getAnalytics(this.days).subscribe(d => {
      this.data = d;
      this.maxSignalCount = Math.max(...d.signalVolume.map(s => s.count), 1);
      this.maxPlatformCount = Math.max(...d.platformDistribution.map(p => p.count), 1);
    });
  }

  funnelPct(value: number, total: number): number {
    return total > 0 ? Math.max((value / total) * 100, 5) : 5;
  }

  barHeight(count: number): number {
    return Math.max((count / this.maxSignalCount) * 100, 5);
  }

  platformPct(count: number): number {
    return Math.max((count / this.maxPlatformCount) * 100, 5);
  }
}
