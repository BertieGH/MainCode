import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatChipsModule } from '@angular/material/chips';
import { SurveyService } from '../../../survey-builder/services/survey.service';
import { SurveyExecutionService } from '../../services/survey-execution.service';
import { Survey } from '../../../../core/models/survey.model';
import { FieldMapping } from '../../../../core/models/field-mapping.model';
import { PageTitleService } from '../../../../core/services/page-title.service';

@Component({
  selector: 'app-survey-select',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatChipsModule
  ],
  template: `
    <div class="container">
      <div class="page-header">
        <h1 class="page-title">Take a Survey</h1>
      </div>

      <mat-card class="client-card">
        <h3>Client Information</h3>
        <mat-form-field appearance="outline" class="full-width">
          <mat-label>Client ID</mat-label>
          <input matInput [(ngModel)]="clientId" placeholder="Enter CRM Client ID">
        </mat-form-field>
        <mat-form-field *ngFor="let mapping of requiredMappings" appearance="outline" class="full-width">
          <mat-label>{{ mapping.crmFieldName }}</mat-label>
          <input matInput [(ngModel)]="clientData[mapping.crmFieldName]"
                 [placeholder]="'Enter ' + mapping.crmFieldName + ' (' + mapping.fieldType + ')'">
        </mat-form-field>
      </mat-card>

      <div *ngIf="loading" class="loading-spinner">
        <mat-spinner></mat-spinner>
      </div>

      <div *ngIf="!loading">
        <h2>Active Surveys</h2>

        <mat-card *ngFor="let survey of activeSurveys" class="survey-card">
          <div class="survey-header">
            <div class="survey-info">
              <h3>{{ survey.title }}</h3>
              <p *ngIf="survey.description">{{ survey.description }}</p>
              <div class="survey-meta">
                <mat-chip-set>
                  <mat-chip>{{ survey.questionCount }} questions</mat-chip>
                </mat-chip-set>
              </div>
            </div>
            <div class="survey-actions">
              <button mat-raised-button color="primary"
                      [disabled]="!canStart()"
                      (click)="startSurvey(survey)">
                <mat-icon>play_arrow</mat-icon>
                Take Survey
              </button>
            </div>
          </div>
        </mat-card>

        <mat-card *ngIf="activeSurveys.length === 0" class="empty-state">
          <mat-icon>inbox</mat-icon>
          <h3>No active surveys</h3>
          <p>There are no active surveys available to take.</p>
        </mat-card>
      </div>
    </div>
  `,
  styles: [`
    .container { max-width: 1200px; margin: 0 auto; }
    .client-card { margin-bottom: 24px; }
    .full-width { width: 100%; }
    .survey-card { margin-bottom: 16px; }
    .survey-header { display: flex; justify-content: space-between; align-items: center; }
    .survey-info { flex: 1; }
    .survey-info h3 { margin: 0 0 8px 0; }
    .survey-meta { margin-top: 12px; }
    .survey-actions { margin-left: 16px; }
    .empty-state { text-align: center; padding: 48px; }
    .empty-state mat-icon { font-size: 64px; width: 64px; height: 64px; color: #ccc; }
    .loading-spinner { display: flex; justify-content: center; padding: 48px; }
  `]
})
export class SurveySelectComponent implements OnInit {
  activeSurveys: Survey[] = [];
  clientId = '';
  clientData: { [key: string]: string } = {};
  requiredMappings: FieldMapping[] = [];
  loading = false;

  constructor(
    private surveyService: SurveyService,
    private executionService: SurveyExecutionService,
    private router: Router,
    private pageTitle: PageTitleService
  ) {}

  ngOnInit(): void {
    this.pageTitle.setTitle('Take a Survey', 'Select a survey to complete');
    this.loadSurveys();
    this.loadFieldMappings();
  }

  loadSurveys(): void {
    this.loading = true;
    this.surveyService.getSurveys(1, 100).subscribe({
      next: (result) => {
        this.activeSurveys = result.items.filter(s => s.status === 'Active');
        this.loading = false;
      },
      error: (error) => {
        console.error('Error loading surveys:', error);
        this.loading = false;
      }
    });
  }

  loadFieldMappings(): void {
    this.executionService.getFieldMappings().subscribe({
      next: (mappings) => {
        this.requiredMappings = mappings.filter(m => m.isRequired);
        for (const m of this.requiredMappings) {
          this.clientData[m.crmFieldName] = '';
        }
      },
      error: (error) => {
        console.error('Error loading field mappings:', error);
      }
    });
  }

  canStart(): boolean {
    if (!this.clientId.trim()) return false;
    for (const m of this.requiredMappings) {
      if (!this.clientData[m.crmFieldName]?.trim()) return false;
    }
    return true;
  }

  startSurvey(survey: Survey): void {
    const queryParams: any = { clientId: this.clientId.trim() };
    if (Object.keys(this.clientData).length > 0) {
      queryParams.clientData = JSON.stringify(this.clientData);
    }
    this.router.navigate(['/execute', survey.id], { queryParams });
  }
}
