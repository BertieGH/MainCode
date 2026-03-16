import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { UserResponse, CreateUserRequest, UpdateUserRequest, InviteUserRequest, PermissionsMatrix } from '../models/user.model';
import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class UserService {
  private baseUrl = `${environment.apiUrl}/users`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<UserResponse[]> {
    return this.http.get<UserResponse[]>(this.baseUrl);
  }

  getById(id: number): Observable<UserResponse> {
    return this.http.get<UserResponse>(`${this.baseUrl}/${id}`);
  }

  create(request: CreateUserRequest): Observable<UserResponse> {
    return this.http.post<UserResponse>(this.baseUrl, request);
  }

  update(id: number, request: UpdateUserRequest): Observable<UserResponse> {
    return this.http.put<UserResponse>(`${this.baseUrl}/${id}`, request);
  }

  disable(id: number): Observable<any> {
    return this.http.put(`${this.baseUrl}/${id}/disable`, {});
  }

  enable(id: number): Observable<any> {
    return this.http.put(`${this.baseUrl}/${id}/enable`, {});
  }

  resetPassword(id: number, newPassword: string): Observable<any> {
    return this.http.post(`${this.baseUrl}/${id}/reset-password`, { newPassword });
  }

  invite(request: InviteUserRequest): Observable<any> {
    return this.http.post(`${this.baseUrl}/invite`, request);
  }

  getInvitations(): Observable<any[]> {
    return this.http.get<any[]>(`${this.baseUrl}/invitations`);
  }

  getPermissionsMatrix(): Observable<PermissionsMatrix> {
    return this.http.get<PermissionsMatrix>(`${this.baseUrl}/permissions-matrix`);
  }
}
