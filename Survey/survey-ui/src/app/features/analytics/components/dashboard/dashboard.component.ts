import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTableModule } from '@angular/material/table';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
  DashboardSummary,
  SurveyResponseItem,
  ResponseDetail
} from '../../../../core/models/analytics.model';
import { AnalyticsService } from '../../services/analytics.service';
import { SurveyService } from '../../../survey-builder/services/survey.service';
import { Survey } from '../../../../core/models/survey.model';
import { PageTitleService } from '../../../../core/services/page-title.service';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatTableModule,
    MatProgressSpinnerModule,
    MatTooltipModule
  ],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.scss']
})
export class DashboardComponent implements OnInit {
  dashboard: DashboardSummary | null = null;
  loading = true;
  error = '';

  surveyColumns = ['title', 'status', 'responseCount', 'completionRate', 'actions'];
  responseColumns = ['surveyTitle', 'crmClientId', 'completedAt'];

  // Drill-down state
  drillLevel: 'dashboard' | 'surveys' | 'responses' | 'detail' = 'dashboard';
  allSurveys: Survey[] = [];
  surveyResponses: SurveyResponseItem[] = [];
  responseDetail: ResponseDetail | null = null;
  drillLoading = false;
  selectedSurveyTitle = '';
  selectedSurveyId = 0;
  selectedClientId = '';

  allSurveyColumns = ['title', 'status', 'questionCount', 'actions'];
  responseListColumns = ['crmClientId', 'startedAt', 'completedAt', 'status', 'actions'];

  constructor(
    private analyticsService: AnalyticsService,
    private surveyService: SurveyService,
    private router: Router,
    private pageTitle: PageTitleService
  ) {}

  ngOnInit(): void {
    this.pageTitle.setTitle('Dashboard', 'Welcome back! Here\'s your survey overview.');
    this.loadDashboard();
  }

  loadDashboard(): void {
    this.loading = true;
    this.analyticsService.getDashboardSummary().subscribe({
      next: (data) => {
        this.dashboard = data;
        this.loading = false;
      },
      error: (err) => {
        this.error = 'Failed to load dashboard data';
        this.loading = false;
        console.error('Error loading dashboard:', err);
      }
    });
  }

  viewSurveyAnalytics(surveyId: number): void {
    this.router.navigate(['/analytics/survey', surveyId]);
  }

  viewClientHistory(crmClientId: string): void {
    this.router.navigate(['/analytics/client', crmClientId]);
  }

  // Drill-down: Total Surveys card clicked
  drillIntoSurveys(): void {
    this.drillLevel = 'surveys';
    this.drillLoading = true;
    this.surveyService.getSurveys(1, 100).subscribe({
      next: (result) => {
        this.allSurveys = result.items;
        this.drillLoading = false;
      },
      error: (err) => {
        console.error('Error loading surveys:', err);
        this.drillLoading = false;
      }
    });
  }

  // Drill-down: Click a survey to see its responses
  drillIntoResponses(survey: Survey): void {
    this.selectedSurveyTitle = survey.title;
    this.selectedSurveyId = survey.id;
    this.drillLevel = 'responses';
    this.drillLoading = true;
    this.analyticsService.getSurveyResponses(survey.id).subscribe({
      next: (responses) => {
        this.surveyResponses = responses;
        this.drillLoading = false;
      },
      error: (err) => {
        console.error('Error loading responses:', err);
        this.drillLoading = false;
      }
    });
  }

  // Drill-down: Click a client to see the full response
  drillIntoDetail(response: SurveyResponseItem): void {
    this.selectedClientId = response.crmClientId;
    this.drillLevel = 'detail';
    this.drillLoading = true;
    this.analyticsService.getResponseDetail(response.responseId).subscribe({
      next: (detail) => {
        this.responseDetail = detail;
        this.drillLoading = false;
      },
      error: (err) => {
        console.error('Error loading response detail:', err);
        this.drillLoading = false;
      }
    });
  }

  // Navigation back
  goBack(): void {
    if (this.drillLevel === 'detail') {
      this.drillLevel = 'responses';
      this.responseDetail = null;
    } else if (this.drillLevel === 'responses') {
      this.drillLevel = 'surveys';
      this.surveyResponses = [];
    } else if (this.drillLevel === 'surveys') {
      this.drillLevel = 'dashboard';
      this.allSurveys = [];
    }
  }

  // Gauge chart helpers
  getGaugeDash(rate: number): string {
    // Arc length for a semicircle with radius 50: π * 50 ≈ 157
    const arcLength = Math.PI * 50;
    const filled = (rate / 100) * arcLength;
    return `${filled} ${arcLength}`;
  }

  getGaugeColor(rate: number): string {
    if (rate >= 75) return '#10b981';
    if (rate >= 50) return '#f59e0b';
    return '#ef4444';
  }

  getBreadcrumb(): string[] {
    const crumbs = ['Dashboard'];
    if (this.drillLevel === 'surveys' || this.drillLevel === 'responses' || this.drillLevel === 'detail') {
      crumbs.push('All Surveys');
    }
    if (this.drillLevel === 'responses' || this.drillLevel === 'detail') {
      crumbs.push(this.selectedSurveyTitle);
    }
    if (this.drillLevel === 'detail') {
      crumbs.push(`Client: ${this.selectedClientId}`);
    }
    return crumbs;
  }
}
