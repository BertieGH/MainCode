import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { QuestionBankService } from '../../services/question-bank.service';
import { QuestionCategory } from '../../../../core/models/question-bank.model';
import { PageTitleService } from '../../../../core/services/page-title.service';

@Component({
  selector: 'app-category-management',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterModule,
    MatCardModule,
    MatButtonModule,
    MatInputModule,
    MatIconModule,
    MatListModule,
    MatProgressSpinnerModule
  ],
  template: `
    <div class="container">
      <div class="page-header">
        <h1 class="page-title">Category Management</h1>
        <button mat-button routerLink="/question-bank">
          <mat-icon>arrow_back</mat-icon>
          Back to Questions
        </button>
      </div>

      <div class="content-grid">
        <!-- Category Form -->
        <mat-card>
          <h2>{{ isEditMode ? 'Edit Category' : 'New Category' }}</h2>
          <form [formGroup]="categoryForm" (ngSubmit)="onSubmit()">
            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Category Name</mat-label>
              <input matInput formControlName="name" required>
            </mat-form-field>

            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Description</mat-label>
              <textarea matInput formControlName="description" rows="3"></textarea>
            </mat-form-field>

            <div class="form-actions">
              <button mat-button type="button" (click)="cancelEdit()" *ngIf="isEditMode">Cancel</button>
              <button mat-raised-button color="primary" type="submit" [disabled]="categoryForm.invalid || loading">
                {{ isEditMode ? 'Update' : 'Create' }}
              </button>
            </div>
          </form>
        </mat-card>

        <!-- Categories List -->
        <mat-card>
          <h2>Categories</h2>
          <div *ngIf="loading" class="loading-spinner">
            <mat-spinner></mat-spinner>
          </div>
          <mat-list *ngIf="!loading">
            <mat-list-item *ngFor="let category of categories">
              <div class="category-item">
                <div class="category-info">
                  <strong>{{ category.name }}</strong>
                  <small *ngIf="category.description">{{ category.description }}</small>
                  <small class="question-count">{{ category.questionCount }} questions</small>
                </div>
                <div class="category-actions">
                  <button mat-icon-button (click)="editCategory(category)">
                    <mat-icon>edit</mat-icon>
                  </button>
                  <button mat-icon-button (click)="deleteCategory(category.id)" color="warn">
                    <mat-icon>delete</mat-icon>
                  </button>
                </div>
              </div>
            </mat-list-item>
          </mat-list>
        </mat-card>
      </div>
    </div>
  `,
  styles: [`
    .container { max-width: 1200px; margin: 0 auto; }
    .content-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
    .full-width { width: 100%; margin-bottom: 16px; }
    .form-actions { display: flex; justify-content: flex-end; gap: 16px; margin-top: 16px; }
    .category-item { display: flex; justify-content: space-between; align-items: center; width: 100%; padding: 8px 0; }
    .category-info { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 0; overflow: hidden; }
    .category-info strong { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .category-info small { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block; }
    .question-count { color: #666; }
    .category-actions { display: flex; gap: 4px; flex-shrink: 0; margin-left: 8px; }
    ::ng-deep .mat-mdc-list-item { height: auto !important; min-height: 64px; }
    ::ng-deep .mat-mdc-list-item .mdc-list-item__content { overflow: visible; }
    @media (max-width: 768px) { .content-grid { grid-template-columns: 1fr; } }
  `]
})
export class CategoryManagementComponent implements OnInit {
  categories: QuestionCategory[] = [];
  categoryForm!: FormGroup;
  isEditMode = false;
  editingCategoryId?: number;
  loading = false;

  constructor(
    private fb: FormBuilder,
    private questionBankService: QuestionBankService,
    private pageTitle: PageTitleService
  ) {
    this.initForm();
  }

  ngOnInit(): void {
    this.pageTitle.setTitle('Categories', 'Manage question categories');
    this.loadCategories();
  }

  initForm(): void {
    this.categoryForm = this.fb.group({
      name: ['', [Validators.required, Validators.maxLength(200)]],
      description: ['', Validators.maxLength(1000)]
    });
  }

  loadCategories(): void {
    this.loading = true;
    this.questionBankService.getCategories().subscribe({
      next: (categories) => {
        this.categories = categories;
        this.loading = false;
      },
      error: (error) => {
        console.error('Error loading categories:', error);
        this.loading = false;
      }
    });
  }

  onSubmit(): void {
    if (this.categoryForm.invalid) return;

    const categoryData = this.categoryForm.value;
    const request = this.isEditMode && this.editingCategoryId
      ? this.questionBankService.updateCategory(this.editingCategoryId, categoryData)
      : this.questionBankService.createCategory(categoryData);

    request.subscribe({
      next: () => {
        this.loadCategories();
        this.cancelEdit();
      },
      error: (error) => {
        alert('Error saving category: ' + error.message);
      }
    });
  }

  editCategory(category: QuestionCategory): void {
    this.isEditMode = true;
    this.editingCategoryId = category.id;
    this.categoryForm.patchValue({
      name: category.name,
      description: category.description
    });
  }

  cancelEdit(): void {
    this.isEditMode = false;
    this.editingCategoryId = undefined;
    this.categoryForm.reset();
  }

  deleteCategory(id: number): void {
    if (confirm('Are you sure you want to delete this category?')) {
      this.questionBankService.deleteCategory(id).subscribe({
        next: () => {
          this.loadCategories();
        },
        error: (error) => {
          alert('Error deleting category: ' + error.message);
        }
      });
    }
  }
}
