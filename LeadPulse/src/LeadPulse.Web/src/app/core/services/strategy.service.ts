import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { StrategyResponse, CreateStrategyRequest, DailyListResponse } from '../models/strategy.model';
import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class StrategyService {
  private baseUrl = `${environment.apiUrl}/strategies`;
  private dailyListUrl = `${environment.apiUrl}/daily-lists`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<StrategyResponse[]> {
    return this.http.get<StrategyResponse[]>(this.baseUrl);
  }

  getById(id: number): Observable<StrategyResponse> {
    return this.http.get<StrategyResponse>(`${this.baseUrl}/${id}`);
  }

  create(request: CreateStrategyRequest): Observable<StrategyResponse> {
    return this.http.post<StrategyResponse>(this.baseUrl, request);
  }

  update(id: number, request: any): Observable<StrategyResponse> {
    return this.http.put<StrategyResponse>(`${this.baseUrl}/${id}`, request);
  }

  delete(id: number): Observable<any> {
    return this.http.delete(`${this.baseUrl}/${id}`);
  }

  generateDailyList(id: number): Observable<any> {
    return this.http.post(`${this.baseUrl}/${id}/generate`, {});
  }

  getDailyLists(strategyId?: number): Observable<DailyListResponse[]> {
    const params: any = {};
    if (strategyId) params.strategyId = strategyId;
    return this.http.get<DailyListResponse[]>(this.dailyListUrl, { params });
  }

  getDailyList(id: number): Observable<DailyListResponse> {
    return this.http.get<DailyListResponse>(`${this.dailyListUrl}/${id}`);
  }

  getTodayList(strategyId?: number): Observable<any> {
    const params: any = {};
    if (strategyId) params.strategyId = strategyId;
    return this.http.get(`${this.dailyListUrl}/today`, { params });
  }

  updateItemStatus(itemId: number, status: string): Observable<any> {
    return this.http.put(`${this.dailyListUrl}/items/${itemId}/status`, { status });
  }
}
