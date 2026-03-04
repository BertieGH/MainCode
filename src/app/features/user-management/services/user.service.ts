import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';
import { User, CreateUser, UpdateUser } from '../../../core/models/user.model';
import { PagedResult } from '../../../core/models/question-bank.model';

@Injectable({
  providedIn: 'root'
})
export class UserService {
  constructor(private api: ApiService) {}

  getUsers(pageNumber: number = 1, pageSize: number = 20, search?: string, role?: string): Observable<PagedResult<User>> {
    const params: any = { pageNumber, pageSize };
    if (search) params.search = search;
    if (role) params.role = role;
    return this.api.get<PagedResult<User>>('users', params);
  }

  getUserById(id: number): Observable<User> {
    return this.api.get<User>(`users/${id}`);
  }

  createUser(user: CreateUser): Observable<User> {
    return this.api.post<User>('users', user);
  }

  updateUser(id: number, user: UpdateUser): Observable<User> {
    return this.api.put<User>(`users/${id}`, user);
  }

  deleteUser(id: number): Observable<void> {
    return this.api.delete<void>(`users/${id}`);
  }

  toggleActive(id: number): Observable<User> {
    return this.api.patch<User>(`users/${id}/toggle-active`, {});
  }

  changeRole(id: number, role: string): Observable<User> {
    return this.api.patch<User>(`users/${id}/role`, { role });
  }

  changePassword(id: number, newPassword: string): Observable<void> {
    return this.api.patch<void>(`users/${id}/password`, { newPassword });
  }
}
