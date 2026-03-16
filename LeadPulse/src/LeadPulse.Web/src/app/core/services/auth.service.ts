import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, tap } from 'rxjs';
import { Router } from '@angular/router';
import { AuthResult, LoginRequest, TenantLoginRequest, DecodedToken } from '../models/auth.model';
import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private tokenKey = 'lp_token';
  private currentUserSubject = new BehaviorSubject<DecodedToken | null>(this.getDecodedToken());
  currentUser$ = this.currentUserSubject.asObservable();

  constructor(private http: HttpClient, private router: Router) {}

  loginPlatform(request: LoginRequest): Observable<AuthResult> {
    return this.http.post<AuthResult>(`${environment.apiUrl}/auth/platform/login`, request)
      .pipe(tap(result => this.handleLoginResult(result)));
  }

  loginTenant(request: TenantLoginRequest): Observable<AuthResult> {
    return this.http.post<AuthResult>(`${environment.apiUrl}/auth/tenant/login`, request)
      .pipe(tap(result => this.handleLoginResult(result)));
  }

  logout(): void {
    localStorage.removeItem(this.tokenKey);
    this.currentUserSubject.next(null);
    this.router.navigate(['/login']);
  }

  getToken(): string | null {
    return localStorage.getItem(this.tokenKey);
  }

  isAuthenticated(): boolean {
    const token = this.getDecodedToken();
    if (!token) return false;
    return token.exp * 1000 > Date.now();
  }

  get role(): string | null {
    return this.getDecodedToken()?.role ?? null;
  }

  get tenantId(): number | null {
    const id = this.getDecodedToken()?.tenantId;
    return id ? parseInt(id) : null;
  }

  private handleLoginResult(result: AuthResult): void {
    if (result.success && result.token) {
      localStorage.setItem(this.tokenKey, result.token);
      this.currentUserSubject.next(this.getDecodedToken());
    }
  }

  private getDecodedToken(): DecodedToken | null {
    const token = localStorage.getItem(this.tokenKey);
    if (!token) return null;
    try {
      const payload = token.split('.')[1];
      return JSON.parse(atob(payload));
    } catch {
      return null;
    }
  }
}
