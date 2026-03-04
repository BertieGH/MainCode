import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatMenuModule } from '@angular/material/menu';
import { MatTabsModule } from '@angular/material/tabs';
import { MatChipsModule } from '@angular/material/chips';
import { NgChartsModule } from 'ng2-charts';
import {
  Chart, PieController, BarController, DoughnutController,
  ArcElement, BarElement, CategoryScale, LinearScale,
  Tooltip, Legend
} from 'chart.js';
import { ChartData, ChartOptions } from 'chart.js';
import { SurveyStatistics, QuestionAnalytics } from '../../../../core/models/analytics.model';
import { AnalyticsService } from '../../services/analytics.service';
import { PageTitleService } from '../../../../core/services/page-title.service';

Chart.register(
  PieController, BarController, DoughnutController,
  ArcElement, BarElement, CategoryScale, LinearScale,
  Tooltip, Legend
);

const CHART_COLORS = ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#3b82f6', '#8b5cf6', '#ec4899', '#14b8a6'];

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
    MatTabsModule,
    MatChipsModule,
    NgChartsModule
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

  // --- Question Report Chart Methods ---

  getQuestionTypeLabel(type: string): string {
    const labels: { [key: string]: string } = {
      'SingleChoice': 'Single Choice',
      'MultipleChoice': 'Multiple Choice',
      'Rating': 'Rating',
      'YesNo': 'Yes / No',
      'Text': 'Text'
    };
    return labels[type] || type;
  }

  getQuestionTypeIcon(type: string): string {
    const icons: { [key: string]: string } = {
      'SingleChoice': 'radio_button_checked',
      'MultipleChoice': 'check_box',
      'Rating': 'star',
      'YesNo': 'thumbs_up_down',
      'Text': 'short_text'
    };
    return icons[type] || 'help';
  }

  getChoiceChartData(qa: QuestionAnalytics): ChartData {
    const labels = Object.keys(qa.optionDistribution);
    const data = Object.values(qa.optionDistribution);
    const colors = labels.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]);

    if (qa.questionType === 'SingleChoice') {
      return {
        labels,
        datasets: [{
          data,
          backgroundColor: colors,
          borderColor: '#ffffff',
          borderWidth: 2
        }]
      };
    }

    // MultipleChoice - horizontal bar
    return {
      labels,
      datasets: [{
        data,
        backgroundColor: colors,
        borderRadius: 6
      }]
    };
  }

  getChoiceChartOptions(qa: QuestionAnalytics): ChartOptions {
    const total = qa.totalAnswers;

    if (qa.questionType === 'SingleChoice') {
      return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'right', labels: { padding: 16, usePointStyle: true } },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const value = ctx.parsed as number;
                const pct = total > 0 ? ((value / total) * 100).toFixed(1) : '0';
                return ` ${ctx.label}: ${value} (${pct}%)`;
              }
            }
          }
        },
        cutout: '40%'
      } as ChartOptions;
    }

    // MultipleChoice - horizontal bar
    return {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const value = ctx.parsed.x ?? 0;
              const pct = total > 0 ? ((value / total) * 100).toFixed(1) : '0';
              return ` ${value} responses (${pct}%)`;
            }
          }
        }
      },
      scales: {
        x: { beginAtZero: true, ticks: { stepSize: 1 } },
        y: { grid: { display: false } }
      }
    } as ChartOptions;
  }

  getChoiceChartType(qa: QuestionAnalytics): 'doughnut' | 'bar' {
    return qa.questionType === 'SingleChoice' ? 'doughnut' : 'bar';
  }

  getYesNoChartData(qa: QuestionAnalytics): ChartData {
    return {
      labels: ['Yes', 'No'],
      datasets: [{
        data: [qa.yesCount || 0, qa.noCount || 0],
        backgroundColor: ['#22c55e', '#ef4444'],
        borderColor: '#ffffff',
        borderWidth: 3
      }]
    };
  }

  getYesNoChartOptions(qa: QuestionAnalytics): ChartOptions {
    const total = (qa.yesCount || 0) + (qa.noCount || 0);
    return {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '50%',
      plugins: {
        legend: { position: 'bottom', labels: { padding: 20, usePointStyle: true, font: { size: 14 } } },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const value = ctx.parsed as number;
              const pct = total > 0 ? ((value / total) * 100).toFixed(1) : '0';
              return ` ${ctx.label}: ${value} (${pct}%)`;
            }
          }
        }
      }
    } as ChartOptions;
  }

  getRatingChartData(qa: QuestionAnalytics): ChartData {
    const labels = Object.keys(qa.optionDistribution);
    const data = Object.values(qa.optionDistribution);
    return {
      labels,
      datasets: [{
        data,
        backgroundColor: '#6366f1',
        borderRadius: 6
      }]
    };
  }

  getRatingChartOptions(qa: QuestionAnalytics): ChartOptions {
    const total = qa.totalAnswers;
    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const value = ctx.parsed.y ?? 0;
              const pct = total > 0 ? ((value / total) * 100).toFixed(1) : '0';
              return ` ${value} responses (${pct}%)`;
            }
          }
        }
      },
      scales: {
        y: { beginAtZero: true, ticks: { stepSize: 1 } },
        x: { grid: { display: false } }
      }
    } as ChartOptions;
  }

  getYesNoTotal(qa: QuestionAnalytics): number {
    return (qa.yesCount || 0) + (qa.noCount || 0);
  }
}
