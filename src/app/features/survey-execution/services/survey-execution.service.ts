import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';
import { FieldMapping } from '../../../core/models/field-mapping.model';
import {
  SurveyExecution,
  StartSurveyRequest,
  SubmitResponseRequest,
  SurveyResponse
} from '../../../core/models/survey-execution.model';

@Injectable({
  providedIn: 'root'
})
export class SurveyExecutionService {
  constructor(private api: ApiService) {}

  getFieldMappings(): Observable<FieldMapping[]> {
    return this.api.get<FieldMapping[]>('fieldmappings');
  }

  prepareSurvey(surveyId: number, crmClientId: string, clientData: { [key: string]: string }): Observable<SurveyExecution> {
    return this.api.post<SurveyExecution>(
      `surveyexecution/${surveyId}/prepare?crmClientId=${encodeURIComponent(crmClientId)}`,
      clientData
    );
  }

  startSurvey(request: StartSurveyRequest): Observable<SurveyResponse> {
    return this.api.post<SurveyResponse>('surveyexecution/start', request);
  }

  submitAnswers(request: SubmitResponseRequest): Observable<void> {
    return this.api.post<void>('surveyexecution/submit-answers', request);
  }

  completeSurvey(responseId: number): Observable<SurveyResponse> {
    return this.api.post<SurveyResponse>(`surveyexecution/responses/${responseId}/complete`, {});
  }
}
