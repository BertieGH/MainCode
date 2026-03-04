import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, ActivatedRoute, RouterModule } from '@angular/router';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { SurveyService } from '../../services/survey.service';
import { PageTitleService } from '../../../../core/services/page-title.service';

@Component({
  selector: 'app-survey-form',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterModule,
    MatCardModule,
    MatButtonModule,
    MatInputModule,
    MatProgressSpinnerModule
  ],
  template: `
    <div class="container">
      <div class="page-header">
        <h1 class="page-title">{{ isEditMode ? 'Edit Survey' : 'New Survey' }}</h1>
      </div>

      <mat-card>
        <form [formGroup]="surveyForm" (ngSubmit)="onSubmit()">
          <mat-form-field appearance="outline" class="full-width">
            <mat-label>Survey Title</mat-label>
            <input matInput formControlName="title" required>
            <mat-error *ngIf="surveyForm.get('title')?.hasError('required')">
              Survey title is required
            </mat-error>
          </mat-form-field>

          <mat-form-field appearance="outline" class="full-width">
            <mat-label>Description</mat-label>
            <textarea matInput formControlName="description" rows="4"></textarea>
          </mat-form-field>

          <div class="form-actions">
            <button mat-button type="button" routerLink="/surveys">Cancel</button>
            <button mat-raised-button color="primary" type="submit" [disabled]="surveyForm.invalid || loading">
              {{ isEditMode ? 'Update' : 'Create' }}
            </button>
          </div>
        </form>
      </mat-card>
    </div>
  `,
  styles: [`
    .container { max-width: 800px; margin: 0 auto; }
    .full-width { width: 100%; margin-bottom: 16px; }
    .form-actions { display: flex; justify-content: flex-end; gap: 16px; margin-top: 24px; }
  `]
})
export class SurveyFormComponent implements OnInit {
  surveyForm!: FormGroup;
  isEditMode = false;
  surveyId?: number;
  loading = false;

  constructor(
    private fb: FormBuilder,
    private surveyService: SurveyService,
    private router: Router,
    private route: ActivatedRoute,
    private pageTitle: PageTitleService
  ) {
    this.initForm();
  }

  ngOnInit(): void {
    this.pageTitle.setTitle(this.isEditMode ? 'Edit Survey' : 'New Survey');
    this.route.params.subscribe(params => {
      if (params['id']) {
        this.isEditMode = true;
        this.surveyId = +params['id'];
        this.loadSurvey(this.surveyId);
      }
    });
  }

  initForm(): void {
    this.surveyForm = this.fb.group({
      title: ['', [Validators.required, Validators.maxLength(300)]],
      description: ['', Validators.maxLength(2000)]
    });
  }

  loadSurvey(id: number): void {
    this.loading = true;
    this.surveyService.getSurveyById(id).subscribe({
      next: (survey) => {
        this.surveyForm.patchValue({
          title: survey.title,
          description: survey.description
        });
        this.loading = false;
      },
      error: (error) => {
        alert('Error loading survey: ' + error.message);
        this.loading = false;
      }
    });
  }

  onSubmit(): void {
    if (this.surveyForm.invalid) return;

    this.loading = true;
    const surveyData = this.surveyForm.value;

    const request = this.isEditMode && this.surveyId
      ? this.surveyService.updateSurvey(this.surveyId, surveyData)
      : this.surveyService.createSurvey(surveyData);

    request.subscribe({
      next: (survey) => {
        this.router.navigate(['/surveys', survey.id, 'builder']);
      },
      error: (error) => {
        alert('Error saving survey: ' + error.message);
        this.loading = false;
      }
    });
  }
}
