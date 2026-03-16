import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { KeywordRuleResponse, CreateKeywordRuleRequest, UpdateKeywordRuleRequest } from '../models/keyword.model';
import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class KeywordService {
  private baseUrl = `${environment.apiUrl}/keywords`;

  constructor(private http: HttpClient) {}

  getAll(category?: string, isActive?: boolean): Observable<KeywordRuleResponse[]> {
    const params: any = {};
    if (category) params.category = category;
    if (isActive !== undefined) params.isActive = isActive;
    return this.http.get<KeywordRuleResponse[]>(this.baseUrl, { params });
  }

  getById(id: number): Observable<KeywordRuleResponse> {
    return this.http.get<KeywordRuleResponse>(`${this.baseUrl}/${id}`);
  }

  create(request: CreateKeywordRuleRequest): Observable<KeywordRuleResponse> {
    return this.http.post<KeywordRuleResponse>(this.baseUrl, request);
  }

  update(id: number, request: UpdateKeywordRuleRequest): Observable<KeywordRuleResponse> {
    return this.http.put<KeywordRuleResponse>(`${this.baseUrl}/${id}`, request);
  }

  delete(id: number): Observable<any> {
    return this.http.delete(`${this.baseUrl}/${id}`);
  }

  toggle(id: number): Observable<KeywordRuleResponse> {
    return this.http.post<KeywordRuleResponse>(`${this.baseUrl}/${id}/toggle`, {});
  }

  exportCsv(): Observable<Blob> {
    return this.http.get(`${this.baseUrl}/export`, { responseType: 'blob' });
  }

  importCsv(rows: any[]): Observable<any> {
    return this.http.post(`${this.baseUrl}/import`, rows);
  }
}
