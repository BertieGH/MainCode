import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatMenuModule } from '@angular/material/menu';
import { MatTabsModule } from '@angular/material/tabs';
import { SurveyStatistics, QuestionAnalytics } from '../../../../core/models/analytics.model';
import { AnalyticsService } from '../../services/analytics.service';
import { PageTitleService } from '../../../../core/services/page-title.service';

@Component({
  selector: 'app-survey-analytics',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatMenuModule,
    MatTabsModule
  ],
  templateUrl: './survey-analytics.component.html',
  styleUrls: ['./survey-analytics.component.scss']
})
export class SurveyAnalyticsComponent implements OnInit {
  surveyId!: number;
  statistics: SurveyStatistics | null = null;
  loading = true;
  error = '';

  constructor(
    private route: ActivatedRoute,
    private analyticsService: AnalyticsService,
    private pageTitle: PageTitleService
  ) {}

  ngOnInit(): void {
    this.pageTitle.setTitle('Survey Analytics', 'Detailed survey statistics');
    this.surveyId = Number(this.route.snapshot.paramMap.get('id'));
    this.loadStatistics();
  }

  loadStatistics(): void {
    this.loading = true;
    this.analyticsService.getSurveyStatistics(this.surveyId).subscribe({
      next: (data) => {
        this.statistics = data;
        this.loading = false;
      },
      error: (err) => {
        this.error = 'Failed to load survey statistics';
        this.loading = false;
        console.error('Error loading statistics:', err);
      }
    });
  }

  exportCsv(): void {
    this.analyticsService.exportSurveyResultsCsv(this.surveyId).subscribe({
      next: (blob) => {
        this.downloadFile(blob, `survey_${this.surveyId}_results.csv`);
      },
      error: (err) => {
        console.error('Error exporting CSV:', err);
        alert('Failed to export CSV');
      }
    });
  }

  exportJson(): void {
    this.analyticsService.exportSurveyResultsJson(this.surveyId).subscribe({
      next: (blob) => {
        this.downloadFile(blob, `survey_${this.surveyId}_results.json`);
      },
      error: (err) => {
        console.error('Error exporting JSON:', err);
        alert('Failed to export JSON');
      }
    });
  }

  private downloadFile(blob: Blob, filename: string): void {
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    window.URL.revokeObjectURL(url);
  }

  getOptionKeys(distribution: { [key: string]: number }): string[] {
    return Object.keys(distribution);
  }

  getOptionValue(distribution: { [key: string]: number }, key: string): number {
    return distribution[key];
  }

  calculatePercentage(count: number, total: number): number {
    return total > 0 ? (count / total) * 100 : 0;
  }
}
