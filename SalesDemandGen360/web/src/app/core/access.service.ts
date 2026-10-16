import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { Level, SessionUser } from './auth.service';

export interface AdminUser extends SessionUser {
  created_at: string;
  /** What they have done that a record points at. Empty means deletable. */
  history: Record<string, number>;
  /** The super admin: nobody else can change this account. */
  protected: boolean;
}

/** `{modules: {role: {module: level}}, actions: {role: [action]}}` — admin is never in it. */
export interface RoleGrid {
  modules: Record<string, Record<string, Level>>;
  actions: Record<string, string[]>;
}

export interface RolesView {
  version: number;
  saved_at: string | null;
  saved_by: string | null;
  grid: RoleGrid;
  roles: string[];
  modules: Record<string, string>;
  admin_modules: Record<string, string>;
  actions: Record<string, string>;
  levels: Level[];
}

/** Settings › Users and Settings › Roles. Admin only, on the server too. */
@Injectable({ providedIn: 'root' })
export class AccessService {
  private http = inject(HttpClient);

  users(): Observable<AdminUser[]> {
    return this.http.get<AdminUser[]>('/api/users');
  }

  createUser(body: { email: string; full_name: string; role: string; password: string }): Observable<AdminUser> {
    return this.http.post<AdminUser>('/api/users', body);
  }

  updateUser(id: string, body: { full_name?: string; role?: string }): Observable<AdminUser> {
    return this.http.patch<AdminUser>(`/api/users/${id}`, body);
  }

  deactivate(id: string): Observable<AdminUser> {
    return this.http.post<AdminUser>(`/api/users/${id}/deactivate`, {});
  }

  /** Only an account with no history; the server refuses anyone else. */
  deleteUser(id: string): Observable<void> {
    return this.http.delete<void>(`/api/users/${id}`);
  }

  reactivate(id: string): Observable<AdminUser> {
    return this.http.post<AdminUser>(`/api/users/${id}/reactivate`, {});
  }

  setPassword(id: string, password: string): Observable<AdminUser> {
    return this.http.post<AdminUser>(`/api/users/${id}/password`, { password });
  }

  roles(): Observable<RolesView> {
    return this.http.get<RolesView>('/api/roles');
  }

  saveRoles(grid: RoleGrid): Observable<RolesView> {
    return this.http.put<RolesView>('/api/roles', { grid });
  }
}

/**
 * A password an admin can read out or paste: 14 characters from an alphabet
 * without the look-alikes (0/O, 1/l/I), in dash-separated groups. Drawn from
 * the browser's CSPRNG, never Math.random.
 */
export function generatePassword(): string {
  const alphabet = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  const bytes = new Uint32Array(12);
  crypto.getRandomValues(bytes);
  const chars = Array.from(bytes, (b) => alphabet[b % alphabet.length]).join('');
  return `${chars.slice(0, 4)}-${chars.slice(4, 8)}-${chars.slice(8, 12)}`;
}
