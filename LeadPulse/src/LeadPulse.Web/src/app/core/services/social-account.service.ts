import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  SocialAccountResponse,
  CreateSocialAccountRequest,
  UpdateCredentialsRequest,
  UpdateSyncConfigRequest,
  SyncJobResponse
} from '../models/social-account.model';
import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class SocialAccountService {
  private baseUrl = `${environment.apiUrl}/social-accounts`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<SocialAccountResponse[]> {
    return this.http.get<SocialAccountResponse[]>(this.baseUrl);
  }

  getById(id: number): Observable<SocialAccountResponse> {
    return this.http.get<SocialAccountResponse>(`${this.baseUrl}/${id}`);
  }

  create(request: CreateSocialAccountRequest): Observable<SocialAccountResponse> {
    return this.http.post<SocialAccountResponse>(this.baseUrl, request);
  }

  updateCredentials(id: number, request: UpdateCredentialsRequest): Observable<SocialAccountResponse> {
    return this.http.put<SocialAccountResponse>(`${this.baseUrl}/${id}/credentials`, request);
  }

  updateSyncConfig(id: number, request: UpdateSyncConfigRequest): Observable<SocialAccountResponse> {
    return this.http.put<SocialAccountResponse>(`${this.baseUrl}/${id}/sync-config`, request);
  }

  testLogin(id: number): Observable<any> {
    return this.http.post(`${this.baseUrl}/${id}/test-login`, {});
  }

  syncNow(id: number): Observable<any> {
    return this.http.post(`${this.baseUrl}/${id}/sync-now`, {});
  }

  getSyncJobs(id: number, limit = 20): Observable<SyncJobResponse[]> {
    return this.http.get<SyncJobResponse[]>(`${this.baseUrl}/${id}/sync-jobs`, { params: { limit } });
  }

  delete(id: number): Observable<any> {
    return this.http.delete(`${this.baseUrl}/${id}`);
  }

  getTargets(id: number): Observable<any[]> {
    return this.http.get<any[]>(`${this.baseUrl}/${id}/targets`);
  }

  addTarget(id: number, groupUrl: string, groupName?: string): Observable<any> {
    return this.http.post(`${this.baseUrl}/${id}/targets`, { groupUrl, groupName });
  }

  updateTarget(id: number, targetId: number, groupUrl: string, groupName?: string): Observable<any> {
    return this.http.put(`${this.baseUrl}/${id}/targets/${targetId}`, { groupUrl, groupName });
  }

  toggleTarget(id: number, targetId: number): Observable<any> {
    return this.http.patch(`${this.baseUrl}/${id}/targets/${targetId}/toggle`, {});
  }

  testTarget(id: number, targetId: number): Observable<any> {
    return this.http.post(`${this.baseUrl}/${id}/targets/${targetId}/test`, {});
  }

  deleteTarget(id: number, targetId: number): Observable<any> {
    return this.http.delete(`${this.baseUrl}/${id}/targets/${targetId}`);
  }
}
