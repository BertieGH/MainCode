import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { ProspectResponse, ProspectListResponse, ProspectFilter, ProspectFullDataResponse } from '../models/prospect.model';
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

  searchLinkedIn(id: number): Observable<any> {
    return this.http.post<any>(`${this.baseUrl}/${id}/search-linkedin`, {});
  }

  saveLinkedIn(id: number, linkedInUrl: string): Observable<any> {
    return this.http.put<any>(`${this.baseUrl}/${id}/linkedin`, { linkedInUrl });
  }

  scrubLinkedInProfile(id: number): Observable<any> {
    return this.http.post<any>(`${this.baseUrl}/${id}/scrub-linkedin-profile`, {});
  }

  scrubLinkedInPosts(id: number): Observable<any> {
    return this.http.post<any>(`${this.baseUrl}/${id}/scrub-linkedin-posts`, {});
  }

  getLinkedInPosts(id: number): Observable<any[]> {
    return this.http.get<any[]>(`${this.baseUrl}/${id}/linkedin-posts`);
  }

  getFullData(id: number): Observable<ProspectFullDataResponse> {
    return this.http.get<ProspectFullDataResponse>(`${this.baseUrl}/${id}/full-data`);
  }

  reprocess(): Observable<any> {
    return this.http.post<any>(`${this.baseUrl}/reprocess`, {});
  }

  analyzeProspect(id: number): Observable<any> {
    return this.http.post<any>(`${this.baseUrl}/${id}/analyze`, {});
  }

  analyzeAll(): Observable<any> {
    return this.http.post<any>(`${this.baseUrl}/analyze-all`, {});
  }

  getAiSettings(): Observable<any> {
    return this.http.get<any>(`${this.baseUrl}/ai-settings`);
  }

  updateAiSettings(body: any): Observable<any> {
    return this.http.put<any>(`${this.baseUrl}/ai-settings`, body);
  }

  testAiKey(): Observable<any> {
    return this.http.post<any>(`${this.baseUrl}/ai-settings/test`, {});
  }

  getScraperSettings(): Observable<any> {
    return this.http.get<any>(`${this.baseUrl}/scraper-settings`);
  }

  updateScraperSettings(body: any): Observable<any> {
    return this.http.put<any>(`${this.baseUrl}/scraper-settings`, body);
  }

  testScraperKey(): Observable<any> {
    return this.http.post<any>(`${this.baseUrl}/scraper-settings/test`, {});
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
