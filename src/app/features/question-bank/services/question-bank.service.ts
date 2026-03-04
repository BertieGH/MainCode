import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';
import {
  QuestionBank,
  CreateQuestionBank,
  UpdateQuestionBank,
  PagedResult,
  QuestionCategory,
  CreateQuestionCategory
} from '../../../core/models/question-bank.model';

@Injectable({
  providedIn: 'root'
})
export class QuestionBankService {
  constructor(private api: ApiService) {}

  // Question Bank Methods
  getQuestions(pageNumber: number = 1, pageSize: number = 20, categoryId?: number, search?: string): Observable<PagedResult<QuestionBank>> {
    const params: any = { pageNumber, pageSize };
    if (categoryId) params.categoryId = categoryId;
    if (search) params.search = search;
    return this.api.get<PagedResult<QuestionBank>>('questionbank', params);
  }

  getQuestionById(id: number): Observable<QuestionBank> {
    return this.api.get<QuestionBank>(`questionbank/${id}`);
  }

  createQuestion(question: CreateQuestionBank): Observable<QuestionBank> {
    return this.api.post<QuestionBank>('questionbank', question);
  }

  updateQuestion(id: number, question: UpdateQuestionBank): Observable<QuestionBank> {
    return this.api.put<QuestionBank>(`questionbank/${id}`, question);
  }

  deleteQuestion(id: number): Observable<void> {
    return this.api.delete<void>(`questionbank/${id}`);
  }

  searchQuestions(query: string): Observable<QuestionBank[]> {
    return this.api.get<QuestionBank[]>('questionbank/search', { query });
  }

  getQuestionVersions(questionId: number): Observable<QuestionBank[]> {
    return this.api.get<QuestionBank[]>(`questionbank/versions/${questionId}`);
  }

  // Category Methods
  getCategories(): Observable<QuestionCategory[]> {
    return this.api.get<QuestionCategory[]>('questioncategories');
  }

  getCategoryById(id: number): Observable<QuestionCategory> {
    return this.api.get<QuestionCategory>(`questioncategories/${id}`);
  }

  createCategory(category: CreateQuestionCategory): Observable<QuestionCategory> {
    return this.api.post<QuestionCategory>('questioncategories', category);
  }

  updateCategory(id: number, category: CreateQuestionCategory): Observable<QuestionCategory> {
    return this.api.put<QuestionCategory>(`questioncategories/${id}`, category);
  }

  deleteCategory(id: number): Observable<void> {
    return this.api.delete<void>(`questioncategories/${id}`);
  }
}
