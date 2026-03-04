import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { CdkDragDrop, DragDropModule, moveItemInArray } from '@angular/cdk/drag-drop';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatSelectModule } from '@angular/material/select';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatDialogModule, MatDialog } from '@angular/material/dialog';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { SurveyService } from '../../services/survey.service';
import { QuestionBankService } from '../../../question-bank/services/question-bank.service';
import { Survey, SurveyQuestion, SurveyStatus } from '../../../../core/models/survey.model';
import { QuestionBank, QuestionCategory, QuestionType } from '../../../../core/models/question-bank.model';
import { PageTitleService } from '../../../../core/services/page-title.service';

@Component({
  selector: 'app-survey-builder',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterModule,
    DragDropModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatCheckboxModule,
    MatSelectModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatDialogModule,
    MatChipsModule,
    MatTooltipModule,
    MatSnackBarModule
  ],
  templateUrl: './survey-builder.component.html',
  styleUrls: ['./survey-builder.component.scss']
})
export class SurveyBuilderComponent implements OnInit {
  survey?: Survey;
  surveyQuestions: SurveyQuestion[] = [];
  availableQuestions: QuestionBank[] = [];
  filteredQuestions: QuestionBank[] = [];
  categories: QuestionCategory[] = [];
  loading = false;
  surveyId!: number;

  // Save status
  saveStatus: 'idle' | 'saving' | 'saved' = 'idle';
  private saveTimeout: any;

  // Filters
  searchText = '';
  filterType: string = '';
  filterCategory: number | null = null;
  questionTypes = Object.values(QuestionType);
  showFilters = true;

  constructor(
    private route: ActivatedRoute,
    private surveyService: SurveyService,
    private questionBankService: QuestionBankService,
    private dialog: MatDialog,
    private pageTitle: PageTitleService,
    private snackBar: MatSnackBar
  ) {}

  ngOnInit(): void {
    this.pageTitle.setTitle('Survey Builder', 'Add and arrange questions');
    this.route.params.subscribe(params => {
      this.surveyId = +params['id'];
      this.loadSurvey();
      this.loadAvailableQuestions();
      this.loadCategories();
    });
  }

  loadSurvey(): void {
    this.loading = true;
    this.surveyService.getSurveyById(this.surveyId).subscribe({
      next: (survey) => {
        this.survey = survey;
        this.surveyQuestions = survey.questions;
        this.loading = false;
      },
      error: (error) => {
        alert('Error loading survey: ' + error.message);
        this.loading = false;
      }
    });
  }

  loadAvailableQuestions(): void {
    this.questionBankService.getQuestions(1, 100).subscribe({
      next: (result) => {
        this.availableQuestions = result.items;
        this.applyFilters();
      },
      error: (error) => {
        console.error('Error loading questions:', error);
      }
    });
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

  applyFilters(): void {
    let filtered = [...this.availableQuestions];

    if (this.searchText.trim()) {
      const search = this.searchText.toLowerCase();
      filtered = filtered.filter(q =>
        q.questionText.toLowerCase().includes(search) ||
        (q.tags && q.tags.toLowerCase().includes(search))
      );
    }

    if (this.filterType) {
      filtered = filtered.filter(q => q.questionType === this.filterType);
    }

    if (this.filterCategory) {
      filtered = filtered.filter(q => q.categoryId === this.filterCategory);
    }

    this.filteredQuestions = filtered;
  }

  clearFilters(): void {
    this.searchText = '';
    this.filterType = '';
    this.filterCategory = null;
    this.applyFilters();
  }

  hasActiveFilters(): boolean {
    return !!this.searchText.trim() || !!this.filterType || !!this.filterCategory;
  }

  onDrop(event: CdkDragDrop<SurveyQuestion[]>): void {
    moveItemInArray(this.surveyQuestions, event.previousIndex, event.currentIndex);

    const reorderDto = {
      questions: this.surveyQuestions.map((q, index) => ({
        surveyQuestionId: q.id,
        orderIndex: index
      }))
    };

    this.surveyService.reorderQuestions(this.surveyId, reorderDto).subscribe({
      next: (questions) => {
        this.surveyQuestions = questions;
        this.showSaved('Question order saved');
      },
      error: (error) => {
        alert('Error reordering questions: ' + error.message);
        this.loadSurvey();
      }
    });
  }

  addQuestion(questionBankId: number): void {
    this.saveStatus = 'saving';
    this.surveyService.addQuestionToSurvey(this.surveyId, {
      questionBankId,
      isRequired: false
    }).subscribe({
      next: () => {
        this.loadSurvey();
        this.showSaved('Question added successfully');
      },
      error: (error) => {
        alert('Error adding question: ' + error.message);
      }
    });
  }

  removeQuestion(questionId: number): void {
    if (confirm('Remove this question from the survey?')) {
      this.surveyService.removeQuestionFromSurvey(this.surveyId, questionId).subscribe({
        next: () => {
          this.loadSurvey();
          this.showSaved('Question removed');
        },
        error: (error) => {
          alert('Error removing question: ' + error.message);
        }
      });
    }
  }

  toggleRequired(question: SurveyQuestion): void {
    this.surveyService.modifyQuestionInSurvey(this.surveyId, question.id, {
      isRequired: question.isRequired
    }).subscribe({
      next: () => {
        this.showSaved(question.isRequired ? 'Question marked as required' : 'Question marked as optional');
      },
      error: (error) => {
        question.isRequired = !question.isRequired;
        alert('Error updating question: ' + error.message);
      }
    });
  }

  updateSurveyStatus(status: SurveyStatus): void {
    if (status === SurveyStatus.Active && this.surveyQuestions.length === 0) {
      alert('Cannot activate survey without questions');
      return;
    }

    this.surveyService.updateSurveyStatus(this.surveyId, { status }).subscribe({
      next: (survey) => {
        this.survey = survey;
        this.showSaved(`Survey ${status === SurveyStatus.Active ? 'activated' : 'status updated'} successfully`);
      },
      error: (error) => {
        alert('Error updating status: ' + error.message);
      }
    });
  }

  private showSaved(message: string): void {
    this.saveStatus = 'saved';
    this.snackBar.open(message, 'OK', { duration: 3000 });
    clearTimeout(this.saveTimeout);
    this.saveTimeout = setTimeout(() => this.saveStatus = 'idle', 4000);
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
