import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatRadioModule } from '@angular/material/radio';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { SurveyService } from '../../services/survey.service';
import { Survey } from '../../../../core/models/survey.model';
import { PageTitleService } from '../../../../core/services/page-title.service';

@Component({
  selector: 'app-survey-preview',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatRadioModule,
    MatCheckboxModule,
    MatProgressSpinnerModule
  ],
  template: `
    <div class="container">
      <div class="page-header">
        <h1 class="page-title">Survey Preview</h1>
        <button mat-button [routerLink]="['/surveys', surveyId, 'builder']">
          <mat-icon>arrow_back</mat-icon>
          Back to Builder
        </button>
      </div>

      <div *ngIf="loading" class="loading-spinner">
        <mat-spinner></mat-spinner>
      </div>

      <mat-card *ngIf="!loading && survey" class="preview-card">
        <h2>{{ survey.title }}</h2>
        <p *ngIf="survey.description" class="survey-description">{{ survey.description }}</p>

        <div class="questions">
          <div *ngFor="let question of survey.questions; let i = index" class="question">
            <div class="question-header">
              <span class="question-number">{{ i + 1 }}.</span>
              <span class="question-text">{{ question.questionText }}</span>
              <span *ngIf="question.isRequired" class="required-mark">*</span>
            </div>

            <!-- Single Choice -->
            <mat-radio-group *ngIf="question.questionType === 'SingleChoice'" class="options">
              <mat-radio-button *ngFor="let option of question.options" [value]="option.id" disabled>
                {{ option.optionText }}
              </mat-radio-button>
            </mat-radio-group>

            <!-- Multiple Choice -->
            <div *ngIf="question.questionType === 'MultipleChoice'" class="options">
              <mat-checkbox *ngFor="let option of question.options" disabled>
                {{ option.optionText }}
              </mat-checkbox>
            </div>

            <!-- Text -->
            <div *ngIf="question.questionType === 'Text'" class="text-answer">
              <textarea disabled placeholder="Answer will be entered here..."></textarea>
            </div>

            <!-- Rating -->
            <div *ngIf="question.questionType === 'Rating'" class="rating">
              <mat-icon *ngFor="let star of [1,2,3,4,5]">star_border</mat-icon>
            </div>

            <!-- Yes/No -->
            <mat-radio-group *ngIf="question.questionType === 'YesNo'" class="options">
              <mat-radio-button value="yes" disabled>Yes</mat-radio-button>
              <mat-radio-button value="no" disabled>No</mat-radio-button>
            </mat-radio-group>
          </div>
        </div>

        <div class="preview-footer">
          <p><em>This is a preview. The actual survey will have functional inputs.</em></p>
        </div>
      </mat-card>
    </div>
  `,
  styles: [`
    .container { max-width: 900px; margin: 0 auto; }
    .preview-card { padding: 32px; }
    .survey-description { color: #666; margin-bottom: 32px; }
    .question { margin-bottom: 32px; padding-bottom: 24px; border-bottom: 1px solid #eee; }
    .question:last-child { border-bottom: none; }
    .question-header { display: flex; gap: 8px; margin-bottom: 16px; font-weight: 500; }
    .question-number { color: #666; }
    .required-mark { color: #f44336; font-weight: bold; }
    .options { display: flex; flex-direction: column; gap: 12px; margin-left: 24px; }
    .text-answer textarea { width: 100%; min-height: 100px; padding: 12px; border: 1px solid #ddd; border-radius: 4px; }
    .rating { display: flex; gap: 8px; margin-left: 24px; color: #ffc107; }
    .preview-footer { margin-top: 32px; padding-top: 24px; border-top: 2px solid #e0e0e0; text-align: center; color: #999; }
  `]
})
export class SurveyPreviewComponent implements OnInit {
  survey?: Survey;
  surveyId!: number;
  loading = false;

  constructor(
    private route: ActivatedRoute,
    private surveyService: SurveyService,
    private pageTitle: PageTitleService
  ) {}

  ngOnInit(): void {
    this.pageTitle.setTitle('Survey Preview');
    this.route.params.subscribe(params => {
      this.surveyId = +params['id'];
      this.loadSurvey();
    });
  }

  loadSurvey(): void {
    this.loading = true;
    this.surveyService.getSurveyById(this.surveyId).subscribe({
      next: (survey) => {
        this.survey = survey;
        this.loading = false;
      },
      error: (error) => {
        alert('Error loading survey: ' + error.message);
        this.loading = false;
      }
    });
  }
}
