import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { ProspectResponse, ProspectListResponse, ProspectFilter } from '../models/prospect.model';
import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class ProspectService {
  private baseUrl = `${environment.apiUrl}/prospects`;

  constructor(private http: HttpClient) {}

  getAll(filter: ProspectFilter = {}): Observable<ProspectListResponse> {
    let params = new HttpParams();
    Object.entries(filter).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        params = params.set(key, value.toString());
      }
    });
    return this.http.get<ProspectListResponse>(this.baseUrl, { params });
  }

  getById(id: number): Observable<ProspectResponse> {
    return this.http.get<ProspectResponse>(`${this.baseUrl}/${id}`);
  }

  updateStatus(id: number, status: string): Observable<ProspectResponse> {
    return this.http.put<ProspectResponse>(`${this.baseUrl}/${id}/status`, { status });
  }

  dismiss(id: number): Observable<ProspectResponse> {
    return this.http.put<ProspectResponse>(`${this.baseUrl}/${id}/dismiss`, {});
  }

  enrich(id: number, data: any): Observable<ProspectResponse> {
    return this.http.put<ProspectResponse>(`${this.baseUrl}/${id}/enrich`, data);
  }

  lookupContact(id: number): Observable<any> {
    return this.http.post<any>(`${this.baseUrl}/${id}/lookup`, {});
  }

  exportCsv(filter: ProspectFilter = {}): Observable<Blob> {
    let params = new HttpParams();
    Object.entries(filter).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        params = params.set(key, value.toString());
      }
    });
    return this.http.get(`${this.baseUrl}/export`, { params, responseType: 'blob' });
  }
}
