import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { QuestionBankService } from '../../services/question-bank.service';
import { QuestionBank, QuestionCategory } from '../../../../core/models/question-bank.model';
import { PageTitleService } from '../../../../core/services/page-title.service';

@Component({
  selector: 'app-question-list',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    FormsModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatSelectModule,
    MatChipsModule,
    MatProgressSpinnerModule,
    MatPaginatorModule
  ],
  templateUrl: './question-list.component.html',
  styleUrls: ['./question-list.component.scss']
})
export class QuestionListComponent implements OnInit {
  questions: QuestionBank[] = [];
  categories: QuestionCategory[] = [];
  loading = false;
  error: string | null = null;

  // Filters
  searchQuery = '';
  selectedCategoryId: number | null = null;

  // Pagination
  totalCount = 0;
  pageNumber = 1;
  pageSize = 20;

  constructor(private questionBankService: QuestionBankService, private pageTitle: PageTitleService) {}

  ngOnInit(): void {
    this.pageTitle.setTitle('Question Bank', 'Manage your question library');
    this.loadCategories();
    this.loadQuestions();
  }

  loadCategories(): void {
    this.questionBankService.getCategories().subscribe({
      next: (categories) => {
        this.categories = categories;
      },
      error: (error) => {
        console.error('Error loading categories:', error);
      }
    });
  }

  loadQuestions(): void {
    this.loading = true;
    this.error = null;

    this.questionBankService.getQuestions(
      this.pageNumber,
      this.pageSize,
      this.selectedCategoryId || undefined,
      this.searchQuery || undefined
    ).subscribe({
      next: (result) => {
        this.questions = result.items;
        this.totalCount = result.totalCount;
        this.loading = false;
      },
      error: (error) => {
        this.error = error.message;
        this.loading = false;
      }
    });
  }

  onSearch(): void {
    this.pageNumber = 1;
    this.loadQuestions();
  }

  onCategoryChange(): void {
    this.pageNumber = 1;
    this.loadQuestions();
  }

  onPageChange(event: PageEvent): void {
    this.pageNumber = event.pageIndex + 1;
    this.pageSize = event.pageSize;
    this.loadQuestions();
  }

  deleteQuestion(id: number): void {
    if (confirm('Are you sure you want to delete this question?')) {
      this.questionBankService.deleteQuestion(id).subscribe({
        next: () => {
          this.loadQuestions();
        },
        error: (error) => {
          alert('Error deleting question: ' + error.message);
        }
      });
    }
  }

  getQuestionTypeLabel(type: string): string {
    const labels: any = {
      'SingleChoice': 'Single Choice',
      'MultipleChoice': 'Multiple Choice',
      'Text': 'Text',
      'Rating': 'Rating',
      'YesNo': 'Yes/No'
    };
    return labels[type] || type;
  }
}
