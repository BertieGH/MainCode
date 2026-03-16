import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { DashboardResponse, AnalyticsResponse } from '../models/dashboard.model';
import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class DashboardService {
  constructor(private http: HttpClient) {}

  getDashboard(): Observable<DashboardResponse> {
    return this.http.get<DashboardResponse>(`${environment.apiUrl}/dashboard`);
  }

  getAnalytics(days = 30): Observable<AnalyticsResponse> {
    return this.http.get<AnalyticsResponse>(`${environment.apiUrl}/analytics`, { params: { days } });
  }
}
