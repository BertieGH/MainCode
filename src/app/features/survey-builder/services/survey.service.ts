import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';
import { PagedResult } from '../../../core/models/question-bank.model';
import {
  Survey,
  CreateSurvey,
  UpdateSurvey,
  UpdateSurveyStatus,
  AddQuestionToSurvey,
  ModifySurveyQuestion,
  ReorderQuestions,
  SurveyQuestion
} from '../../../core/models/survey.model';

@Injectable({
  providedIn: 'root'
})
export class SurveyService {
  constructor(private api: ApiService) {}

  // Survey CRUD
  getSurveys(pageNumber: number = 1, pageSize: number = 20): Observable<PagedResult<Survey>> {
    return this.api.get<PagedResult<Survey>>('surveys', { pageNumber, pageSize });
  }

  getSurveyById(id: number): Observable<Survey> {
    return this.api.get<Survey>(`surveys/${id}`);
  }

  createSurvey(survey: CreateSurvey): Observable<Survey> {
    return this.api.post<Survey>('surveys', survey);
  }

  updateSurvey(id: number, survey: UpdateSurvey): Observable<Survey> {
    return this.api.put<Survey>(`surveys/${id}`, survey);
  }

  deleteSurvey(id: number): Observable<void> {
    return this.api.delete<void>(`surveys/${id}`);
  }

  updateSurveyStatus(id: number, status: UpdateSurveyStatus): Observable<Survey> {
    return this.api.patch<Survey>(`surveys/${id}/status`, status);
  }

  duplicateSurvey(id: number, newTitle: string): Observable<Survey> {
    return this.api.post<Survey>(`surveys/${id}/duplicate`, { newTitle });
  }

  // Survey Questions
  getSurveyQuestions(surveyId: number): Observable<SurveyQuestion[]> {
    return this.api.get<SurveyQuestion[]>(`surveys/${surveyId}/surveyquestions`);
  }

  addQuestionToSurvey(surveyId: number, dto: AddQuestionToSurvey): Observable<SurveyQuestion> {
    return this.api.post<SurveyQuestion>(`surveys/${surveyId}/surveyquestions`, dto);
  }

  modifyQuestionInSurvey(surveyId: number, questionId: number, dto: ModifySurveyQuestion): Observable<SurveyQuestion> {
    return this.api.put<SurveyQuestion>(`surveys/${surveyId}/surveyquestions/${questionId}`, dto);
  }

  removeQuestionFromSurvey(surveyId: number, questionId: number): Observable<void> {
    return this.api.delete<void>(`surveys/${surveyId}/surveyquestions/${questionId}`);
  }

  reorderQuestions(surveyId: number, dto: ReorderQuestions): Observable<SurveyQuestion[]> {
    return this.api.patch<SurveyQuestion[]>(`surveys/${surveyId}/surveyquestions/reorder`, dto);
  }
}
