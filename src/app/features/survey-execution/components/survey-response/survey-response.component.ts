import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatRadioModule } from '@angular/material/radio';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { SurveyExecutionService } from '../../services/survey-execution.service';
import {
  SurveyExecution,
  ExecutionQuestion,
  SubmitAnswerRequest
} from '../../../../core/models/survey-execution.model';
import { PageTitleService } from '../../../../core/services/page-title.service';

interface QuestionAnswer {
  answerText?: string;
  selectedOptionIds: number[];
  rating?: number;
}

@Component({
  selector: 'app-survey-response',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatRadioModule,
    MatCheckboxModule,
    MatProgressSpinnerModule,
    MatSnackBarModule
  ],
  template: `
    <div class="container">
      <!-- Loading -->
      <div *ngIf="loading" class="loading-spinner">
        <mat-spinner></mat-spinner>
      </div>

      <!-- Error -->
      <mat-card *ngIf="error" class="error-card">
        <mat-icon color="warn">error</mat-icon>
        <h3>Error loading survey</h3>
        <p>{{ error }}</p>
        <button mat-raised-button routerLink="/execute">Back to Surveys</button>
      </mat-card>

      <!-- Success -->
      <mat-card *ngIf="submitted" class="success-card">
        <mat-icon class="success-icon">check_circle</mat-icon>
        <h2>Thank you!</h2>
        <p>Your survey response has been submitted successfully.</p>
        <button mat-raised-button color="primary" routerLink="/execute">Take Another Survey</button>
      </mat-card>

      <!-- Survey Form -->
      <div *ngIf="!loading && !error && !submitted && survey">
        <div class="page-header">
          <button mat-button routerLink="/execute">
            <mat-icon>arrow_back</mat-icon>
            Back
          </button>
          <h1 class="page-title">{{ survey.surveyTitle }}</h1>
        </div>

        <p *ngIf="survey.description" class="survey-description">{{ survey.description }}</p>

        <mat-card *ngFor="let question of survey.questions; let i = index" class="question-card">
          <div class="question-header">
            <span class="question-number">{{ i + 1 }}.</span>
            <span class="question-text">{{ question.questionText }}</span>
            <span *ngIf="question.isRequired" class="required-mark">*</span>
          </div>

          <!-- Single Choice -->
          <mat-radio-group *ngIf="question.questionType === 'SingleChoice'" class="options"
                           [(ngModel)]="answers[question.surveyQuestionId].selectedOptionIds[0]">
            <mat-radio-button *ngFor="let option of question.options" [value]="option.id">
              {{ option.optionText }}
            </mat-radio-button>
          </mat-radio-group>

          <!-- Multiple Choice -->
          <div *ngIf="question.questionType === 'MultipleChoice'" class="options">
            <mat-checkbox *ngFor="let option of question.options"
                          [checked]="isOptionSelected(question.surveyQuestionId, option.id)"
                          (change)="toggleOption(question.surveyQuestionId, option.id, $event.checked)">
              {{ option.optionText }}
            </mat-checkbox>
          </div>

          <!-- Text -->
          <mat-form-field *ngIf="question.questionType === 'Text'" appearance="outline" class="full-width">
            <mat-label>Your answer</mat-label>
            <textarea matInput rows="3"
                      [(ngModel)]="answers[question.surveyQuestionId].answerText"></textarea>
          </mat-form-field>

          <!-- Rating -->
          <div *ngIf="question.questionType === 'Rating'" class="rating-group">
            <button mat-icon-button *ngFor="let star of [1,2,3,4,5]"
                    (click)="setRating(question.surveyQuestionId, star)"
                    [class.active]="(answers[question.surveyQuestionId].rating || 0) >= star">
              <mat-icon>{{ (answers[question.surveyQuestionId].rating || 0) >= star ? 'star' : 'star_border' }}</mat-icon>
            </button>
            <span class="rating-label" *ngIf="answers[question.surveyQuestionId].rating">
              {{ answers[question.surveyQuestionId].rating }} / 5
            </span>
          </div>

          <!-- Yes/No -->
          <mat-radio-group *ngIf="question.questionType === 'YesNo'" class="options"
                           [(ngModel)]="answers[question.surveyQuestionId].answerText">
            <mat-radio-button value="Yes">Yes</mat-radio-button>
            <mat-radio-button value="No">No</mat-radio-button>
          </mat-radio-group>
        </mat-card>

        <div class="submit-section">
          <p *ngIf="validationError" class="validation-error">{{ validationError }}</p>
          <button mat-raised-button color="primary" (click)="submitSurvey()"
                  [disabled]="submitting" class="submit-button">
            <mat-spinner *ngIf="submitting" diameter="20"></mat-spinner>
            <span *ngIf="!submitting">Submit Survey</span>
          </button>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .container { max-width: 900px; margin: 0 auto; }
    .survey-description { color: #666; margin-bottom: 24px; font-size: 16px; }
    .question-card { margin-bottom: 20px; padding: 24px; }
    .question-header { display: flex; gap: 8px; margin-bottom: 16px; font-size: 16px; font-weight: 500; }
    .question-number { color: #666; }
    .required-mark { color: #f44336; font-weight: bold; }
    .options { display: flex; flex-direction: column; gap: 12px; margin-left: 24px; }
    .full-width { width: 100%; margin-left: 24px; }
    .rating-group { display: flex; align-items: center; gap: 4px; margin-left: 24px; }
    .rating-group button { color: #ccc; }
    .rating-group button.active { color: #ffc107; }
    .rating-label { margin-left: 12px; color: #666; }
    .submit-section { margin: 32px 0; text-align: center; }
    .submit-button { padding: 8px 48px; font-size: 16px; }
    .validation-error { color: #f44336; margin-bottom: 16px; }
    .loading-spinner { display: flex; justify-content: center; padding: 48px; }
    .error-card { text-align: center; padding: 48px; }
    .error-card mat-icon { font-size: 64px; width: 64px; height: 64px; }
    .success-card { text-align: center; padding: 48px; }
    .success-icon { font-size: 72px; width: 72px; height: 72px; color: #4caf50; }
    .page-header { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
    .page-title { margin: 0; }
  `]
})
export class SurveyResponseComponent implements OnInit {
  survey?: SurveyExecution;
  answers: { [questionId: number]: QuestionAnswer } = {};
  loading = false;
  submitting = false;
  submitted = false;
  error: string | null = null;
  validationError: string | null = null;

  private surveyId!: number;
  private clientId = '';
  private clientData: { [key: string]: string } = {};

  constructor(
    private route: ActivatedRoute,
    private executionService: SurveyExecutionService,
    private snackBar: MatSnackBar,
    private pageTitle: PageTitleService
  ) {}

  ngOnInit(): void {
    this.pageTitle.setTitle('Survey Response');
    this.route.params.subscribe(params => {
      this.surveyId = +params['id'];
    });
    this.route.queryParams.subscribe(params => {
      this.clientId = params['clientId'] || '';
      if (params['clientData']) {
        try {
          this.clientData = JSON.parse(params['clientData']);
        } catch {
          this.clientData = {};
        }
      }
      if (this.surveyId && this.clientId) {
        this.loadSurvey();
      } else if (!this.clientId) {
        this.error = 'No client ID provided. Please go back and enter a Client ID.';
      }
    });
  }

  loadSurvey(): void {
    this.loading = true;
    this.executionService.prepareSurvey(this.surveyId, this.clientId, this.clientData).subscribe({
      next: (survey) => {
        this.survey = survey;
        this.initAnswers(survey.questions);
        this.loading = false;
      },
      error: (error) => {
        this.error = error.error?.message || error.message || 'Failed to load survey';
        this.loading = false;
      }
    });
  }

  private initAnswers(questions: ExecutionQuestion[]): void {
    for (const q of questions) {
      this.answers[q.surveyQuestionId] = {
        answerText: undefined,
        selectedOptionIds: [],
        rating: undefined
      };
    }
  }

  isOptionSelected(questionId: number, optionId: number): boolean {
    return this.answers[questionId]?.selectedOptionIds.includes(optionId) ?? false;
  }

  toggleOption(questionId: number, optionId: number, checked: boolean): void {
    const answer = this.answers[questionId];
    if (checked) {
      answer.selectedOptionIds.push(optionId);
    } else {
      answer.selectedOptionIds = answer.selectedOptionIds.filter(id => id !== optionId);
    }
  }

  setRating(questionId: number, rating: number): void {
    this.answers[questionId].rating = rating;
    this.answers[questionId].answerText = rating.toString();
  }

  private validate(): boolean {
    if (!this.survey) return false;

    for (const question of this.survey.questions) {
      if (!question.isRequired) continue;

      const answer = this.answers[question.surveyQuestionId];
      const hasAnswer =
        (question.questionType === 'Text' || question.questionType === 'YesNo') ? !!answer.answerText?.trim() :
        (question.questionType === 'Rating') ? !!answer.rating :
        (question.questionType === 'SingleChoice' || question.questionType === 'MultipleChoice') ? answer.selectedOptionIds.length > 0 :
        false;

      if (!hasAnswer) {
        this.validationError = `Please answer question: "${question.questionText}"`;
        return false;
      }
    }

    this.validationError = null;
    return true;
  }

  private buildAnswers(): SubmitAnswerRequest[] {
    if (!this.survey) return [];

    return this.survey.questions.map(q => {
      const answer = this.answers[q.surveyQuestionId];
      const request: SubmitAnswerRequest = {
        surveyQuestionId: q.surveyQuestionId
      };

      if (q.questionType === 'Text' || q.questionType === 'YesNo' || q.questionType === 'Rating') {
        request.answerText = answer.answerText;
      }

      if (q.questionType === 'SingleChoice' || q.questionType === 'MultipleChoice') {
        request.selectedOptionIds = answer.selectedOptionIds.filter(id => id != null);
      }

      return request;
    });
  }

  submitSurvey(): void {
    if (!this.validate()) return;

    this.submitting = true;

    // Step 1: Start the survey response
    this.executionService.startSurvey({
      surveyId: this.surveyId,
      crmClientId: this.clientId,
      clientData: this.clientData
    }).subscribe({
      next: (response) => {
        // Step 2: Submit answers
        this.executionService.submitAnswers({
          responseId: response.id,
          answers: this.buildAnswers()
        }).subscribe({
          next: () => {
            // Step 3: Complete the survey
            this.executionService.completeSurvey(response.id).subscribe({
              next: () => {
                this.submitted = true;
                this.submitting = false;
              },
              error: (error) => {
                this.snackBar.open('Error completing survey: ' + (error.error?.message || error.message), 'Close', { duration: 5000 });
                this.submitting = false;
              }
            });
          },
          error: (error) => {
            this.snackBar.open('Error submitting answers: ' + (error.error?.message || error.message), 'Close', { duration: 5000 });
            this.submitting = false;
          }
        });
      },
      error: (error) => {
        this.snackBar.open('Error starting survey: ' + (error.error?.message || error.message), 'Close', { duration: 5000 });
        this.submitting = false;
      }
    });
  }
}
