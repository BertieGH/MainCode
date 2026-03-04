import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { SurveyService } from '../../services/survey.service';
import { Survey, SurveyStatus } from '../../../../core/models/survey.model';
import { PageTitleService } from '../../../../core/services/page-title.service';

@Component({
  selector: 'app-survey-list',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatPaginatorModule,
    MatProgressSpinnerModule
  ],
  template: `
    <div class="container">
      <div class="page-header">
        <h1 class="page-title">Surveys</h1>
        <button mat-raised-button color="primary" routerLink="/surveys/new">
          <mat-icon>add</mat-icon>
          New Survey
        </button>
      </div>

      <div *ngIf="loading" class="loading-spinner">
        <mat-spinner></mat-spinner>
      </div>

      <div *ngIf="!loading">
        <mat-card *ngFor="let survey of surveys" class="survey-card">
          <div class="survey-header">
            <div class="survey-info">
              <h3>{{ survey.title }}</h3>
              <p *ngIf="survey.description">{{ survey.description }}</p>
              <div class="survey-meta">
                <mat-chip-set>
                  <mat-chip [highlighted]="survey.status === 'Active'">
                    {{ survey.status }}
                  </mat-chip>
                  <mat-chip>{{ survey.questionCount }} questions</mat-chip>
                </mat-chip-set>
              </div>
            </div>
            <div class="survey-actions">
              <button mat-icon-button [routerLink]="['/surveys', survey.id, 'builder']" matTooltip="Build Survey">
                <mat-icon>edit</mat-icon>
              </button>
              <button mat-icon-button [routerLink]="['/surveys', survey.id, 'preview']" matTooltip="Preview">
                <mat-icon>visibility</mat-icon>
              </button>
              <button mat-icon-button (click)="duplicateSurvey(survey)" matTooltip="Duplicate">
                <mat-icon>content_copy</mat-icon>
              </button>
              <button mat-icon-button (click)="deleteSurvey(survey.id)" matTooltip="Delete" color="warn">
                <mat-icon>delete</mat-icon>
              </button>
            </div>
          </div>
          <div class="survey-footer">
            <small>Created: {{ survey.createdAt | date:'short' }} | Updated: {{ survey.updatedAt | date:'short' }}</small>
          </div>
        </mat-card>

        <mat-card *ngIf="surveys.length === 0" class="empty-state">
          <mat-icon>inbox</mat-icon>
          <h3>No surveys found</h3>
          <p>Create your first survey to get started.</p>
        </mat-card>

        <mat-paginator
          *ngIf="totalCount > 0"
          [length]="totalCount"
          [pageSize]="pageSize"
          [pageIndex]="pageNumber - 1"
          [pageSizeOptions]="[10, 20, 50]"
          (page)="onPageChange($event)">
        </mat-paginator>
      </div>
    </div>
  `,
  styles: [`
    .container { max-width: 1200px; margin: 0 auto; }
    .survey-card { margin-bottom: 16px; }
    .survey-header { display: flex; justify-content: space-between; align-items: flex-start; }
    .survey-info { flex: 1; }
    .survey-info h3 { margin: 0 0 8px 0; }
    .survey-meta { margin-top: 12px; }
    .survey-actions { display: flex; gap: 8px; }
    .survey-footer { margin-top: 12px; padding-top: 12px; border-top: 1px solid #eee; color: #666; }
    .empty-state { text-align: center; padding: 48px; }
    .empty-state mat-icon { font-size: 64px; width: 64px; height: 64px; color: #ccc; }
  `]
})
export class SurveyListComponent implements OnInit {
  surveys: Survey[] = [];
  loading = false;
  totalCount = 0;
  pageNumber = 1;
  pageSize = 20;

  constructor(private surveyService: SurveyService, private pageTitle: PageTitleService) {}

  ngOnInit(): void {
    this.pageTitle.setTitle('Surveys', 'Build and manage your surveys');
    this.loadSurveys();
  }

  loadSurveys(): void {
    this.loading = true;
    this.surveyService.getSurveys(this.pageNumber, this.pageSize).subscribe({
      next: (result) => {
        this.surveys = result.items;
        this.totalCount = result.totalCount;
        this.loading = false;
      },
      error: (error) => {
        console.error('Error loading surveys:', error);
        this.loading = false;
      }
    });
  }

  onPageChange(event: PageEvent): void {
    this.pageNumber = event.pageIndex + 1;
    this.pageSize = event.pageSize;
    this.loadSurveys();
  }

  duplicateSurvey(survey: Survey): void {
    const newTitle = prompt('Enter new survey title:', survey.title + ' (Copy)');
    if (newTitle) {
      this.surveyService.duplicateSurvey(survey.id, newTitle).subscribe({
        next: () => {
          this.loadSurveys();
        },
        error: (error) => {
          alert('Error duplicating survey: ' + error.message);
        }
      });
    }
  }

  deleteSurvey(id: number): void {
    if (confirm('Are you sure you want to delete this survey?')) {
      this.surveyService.deleteSurvey(id).subscribe({
        next: () => {
          this.loadSurveys();
        },
        error: (error) => {
          alert('Error deleting survey: ' + error.message);
        }
      });
    }
  }
}
