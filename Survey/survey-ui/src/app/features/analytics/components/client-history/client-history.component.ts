import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTableModule } from '@angular/material/table';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { ClientSurveyHistory } from '../../../../core/models/analytics.model';
import { AnalyticsService } from '../../services/analytics.service';
import { PageTitleService } from '../../../../core/services/page-title.service';

@Component({
  selector: 'app-client-history',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatTableModule,
    MatProgressSpinnerModule
  ],
  templateUrl: './client-history.component.html',
  styleUrls: ['./client-history.component.scss']
})
export class ClientHistoryComponent implements OnInit {
  crmClientId!: string;
  history: ClientSurveyHistory | null = null;
  loading = true;
  error = '';

  displayedColumns = ['surveyTitle', 'completedAt', 'status', 'actions'];

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private analyticsService: AnalyticsService,
    private pageTitle: PageTitleService
  ) {}

  ngOnInit(): void {
    this.pageTitle.setTitle('Client History', 'Client survey response history');
    this.crmClientId = this.route.snapshot.paramMap.get('id') || '';
    this.loadHistory();
  }

  loadHistory(): void {
    this.loading = true;
    this.analyticsService.getClientSurveyHistory(this.crmClientId).subscribe({
      next: (data) => {
        this.history = data;
        this.loading = false;
      },
      error: (err) => {
        this.error = 'Failed to load client survey history';
        this.loading = false;
        console.error('Error loading history:', err);
      }
    });
  }

  viewSurveyAnalytics(surveyId: number): void {
    this.router.navigate(['/analytics/survey', surveyId]);
  }
}
