import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, ActivatedRoute, RouterModule } from '@angular/router';
import { FormBuilder, FormGroup, FormArray, Validators, ReactiveFormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { QuestionBankService } from '../../services/question-bank.service';
import { QuestionType, QuestionCategory } from '../../../../core/models/question-bank.model';
import { PageTitleService } from '../../../../core/services/page-title.service';

@Component({
  selector: 'app-question-form',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterModule,
    MatCardModule,
    MatButtonModule,
    MatInputModule,
    MatSelectModule,
    MatIconModule,
    MatProgressSpinnerModule
  ],
  templateUrl: './question-form.component.html',
  styleUrls: ['./question-form.component.scss']
})
export class QuestionFormComponent implements OnInit {
  questionForm!: FormGroup;
  categories: QuestionCategory[] = [];
  questionTypes = Object.values(QuestionType);
  isEditMode = false;
  questionId?: number;
  loading = false;
  error: string | null = null;

  constructor(
    private fb: FormBuilder,
    private questionBankService: QuestionBankService,
    private router: Router,
    private route: ActivatedRoute,
    private pageTitle: PageTitleService
  ) {
    this.initForm();
  }

  ngOnInit(): void {
    this.pageTitle.setTitle(this.isEditMode ? 'Edit Question' : 'New Question', 'Question Bank');
    this.loadCategories();

    this.route.params.subscribe(params => {
      if (params['id']) {
        this.isEditMode = true;
        this.questionId = +params['id'];
        this.loadQuestion(this.questionId);
      }
    });

    this.questionForm.get('questionType')?.valueChanges.subscribe(type => {
      this.onQuestionTypeChange(type);
    });
  }

  initForm(): void {
    this.questionForm = this.fb.group({
      questionText: ['', [Validators.required, Validators.maxLength(1000)]],
      questionType: [QuestionType.Text, Validators.required],
      categoryId: [null],
      tags: ['', Validators.maxLength(500)],
      options: this.fb.array([])
    });
  }

  get options(): FormArray {
    return this.questionForm.get('options') as FormArray;
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

  loadQuestion(id: number): void {
    this.loading = true;
    this.questionBankService.getQuestionById(id).subscribe({
      next: (question) => {
        this.questionForm.patchValue({
          questionText: question.questionText,
          questionType: question.questionType,
          categoryId: question.categoryId,
          tags: question.tags
        });

        this.options.clear();
        question.options.forEach(option => {
          this.addOption(option.optionText, option.orderIndex);
        });

        this.loading = false;
      },
      error: (error) => {
        this.error = error.message;
        this.loading = false;
      }
    });
  }

  onQuestionTypeChange(type: QuestionType): void {
    if (type === QuestionType.SingleChoice || type === QuestionType.MultipleChoice) {
      if (this.options.length === 0) {
        this.addOption();
        this.addOption();
      }
    }
  }

  addOption(text: string = '', orderIndex?: number): void {
    const optionGroup = this.fb.group({
      optionText: [text, Validators.required],
      orderIndex: [orderIndex ?? this.options.length]
    });
    this.options.push(optionGroup);
  }

  removeOption(index: number): void {
    this.options.removeAt(index);
  }

  needsOptions(): boolean {
    const type = this.questionForm.get('questionType')?.value;
    return type === QuestionType.SingleChoice || type === QuestionType.MultipleChoice;
  }

  onSubmit(): void {
    if (this.questionForm.invalid) {
      return;
    }

    const formValue = this.questionForm.value;
    const questionData = {
      ...formValue,
      options: this.needsOptions() ? formValue.options : []
    };

    this.loading = true;

    const request = this.isEditMode && this.questionId
      ? this.questionBankService.updateQuestion(this.questionId, questionData)
      : this.questionBankService.createQuestion(questionData);

    request.subscribe({
      next: () => {
        this.router.navigate(['/question-bank']);
      },
      error: (error) => {
        this.error = error.message;
        this.loading = false;
      }
    });
  }

  cancel(): void {
    this.router.navigate(['/question-bank']);
  }
}
