import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  SurveyStatistics,
  ClientSurveyHistory,
  DashboardSummary,
  SurveyResponseItem,
  ResponseDetail
} from '../../../core/models/analytics.model';
import { environment } from '../../../../environments/environment';

@Injectable({
  providedIn: 'root'
})
export class AnalyticsService {
  private readonly apiUrl = `${environment.apiUrl}/analytics`;

  constructor(private http: HttpClient) {}

  /**
   * Get survey statistics with question-level analytics
   */
  getSurveyStatistics(surveyId: number): Observable<SurveyStatistics> {
    return this.http.get<SurveyStatistics>(`${this.apiUrl}/survey/${surveyId}`);
  }

  /**
   * Get client survey history
   */
  getClientSurveyHistory(crmClientId: string): Observable<ClientSurveyHistory> {
    return this.http.get<ClientSurveyHistory>(`${this.apiUrl}/client/${crmClientId}`);
  }

  /**
   * Get dashboard summary
   */
  getDashboardSummary(): Observable<DashboardSummary> {
    return this.http.get<DashboardSummary>(`${this.apiUrl}/dashboard`);
  }

  /**
   * Get all responses for a survey
   */
  getSurveyResponses(surveyId: number): Observable<SurveyResponseItem[]> {
    return this.http.get<SurveyResponseItem[]>(`${this.apiUrl}/survey/${surveyId}/responses`);
  }

  /**
   * Get a single response with full answer details
   */
  getResponseDetail(responseId: number): Observable<ResponseDetail> {
    return this.http.get<ResponseDetail>(`${this.apiUrl}/response/${responseId}`);
  }

  /**
   * Export survey results as CSV
   */
  exportSurveyResultsCsv(surveyId: number): Observable<Blob> {
    return this.http.get(`${this.apiUrl}/export/survey/${surveyId}?format=csv`, {
      responseType: 'blob'
    });
  }

  /**
   * Export survey results as JSON
   */
  exportSurveyResultsJson(surveyId: number): Observable<Blob> {
    return this.http.get(`${this.apiUrl}/export/survey/${surveyId}?format=json`, {
      responseType: 'blob'
    });
  }
}
