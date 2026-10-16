import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, catchError, of, shareReplay, switchMap, tap } from 'rxjs';

export type Level = 'none' | 'view' | 'edit';

export interface SessionUser {
  id: string;
  email: string;
  full_name: string;
  role: 'admin' | 'aiops' | 'marketing' | 'demandgen';
  status: string;
  last_login_at: string | null;
}

export interface Permissions {
  modules: Record<string, Level>;
  actions: string[];
}

export interface Me {
  user: SessionUser;
  permissions: Permissions;
}

/** The role-grid modules, as the Roles screen names them. */
export const MODULE_LABELS: Record<string, string> = {
  dashboard: 'Dashboard, Cost & health',
  lists: 'Account Lists & research',
  queues: 'Campaign Queues',
  outreach: 'Outreach',
  prep: 'Sales Prep',
  models_prompts: 'Model & Prompts config',
  sources_signals: 'Sources & signals',
  content: 'Services & proof, ICP, Writing samples',
  scoring: 'Weights & scoring',
  rules_cadences: 'Sales rules & Cadences',
};

export const ROLE_LABELS: Record<SessionUser['role'], string> = {
  admin: 'Admin',
  aiops: 'AIOps',
  demandgen: 'DemandGen',
  marketing: 'Marketing',
};

/**
 * Who is signed in, and what their role lets them do.
 *
 * What this holds is for **clarity, not safety**: it hides menu items and
 * buttons a role cannot use, so nobody clicks into a refusal. The server
 * checks every request against the same grid regardless (`docs/17`) — a stale
 * copy here can only show something the server will then refuse, never let
 * something through.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);

  /** `undefined` until asked; `null` once we know nobody is signed in. */
  readonly me = signal<Me | null | undefined>(undefined);
  readonly user = computed(() => this.me()?.user ?? null);
  readonly isAdmin = computed(() => this.user()?.role === 'admin');

  /** The one in-flight "who am I", shared by the guard and the shell. */
  private pending: Observable<Me | null> | null = null;

  load(force = false): Observable<Me | null> {
    if (!force && this.me() !== undefined) return of(this.me() ?? null);
    if (!force && this.pending) return this.pending;
    this.pending = this.http.get<Me>('/api/auth/me').pipe(
      catchError(() => of(null)),
      tap((me) => {
        this.me.set(me);
        this.pending = null;
      }),
      shareReplay(1),
    );
    return this.pending;
  }

  /** Errors pass through: the sign-in page shows the server's own words. */
  login(email: string, password: string): Observable<Me | null> {
    // The login answer is only the user; permissions come from /me, so the
    // two always describe the same grid version.
    return this.http
      .post<SessionUser>('/api/auth/login', { email, password })
      .pipe(switchMap(() => this.load(true)));
  }

  logout(): Observable<unknown> {
    return this.http.post('/api/auth/logout', {}).pipe(
      catchError(() => of(null)),
      tap(() => this.me.set(null)),
    );
  }

  changePassword(current_password: string, new_password: string): Observable<SessionUser> {
    return this.http.post<SessionUser>('/api/auth/password', { current_password, new_password });
  }

  /** Forget the session locally — the server already has (a 401 said so). */
  signedOut(): void {
    this.me.set(null);
  }

  level(module: string): Level {
    return this.me()?.permissions.modules[module] ?? 'none';
  }

  canSee(module: string): boolean {
    return this.level(module) !== 'none';
  }

  canEdit(module: string): boolean {
    return this.level(module) === 'edit';
  }

  can(action: string): boolean {
    return this.me()?.permissions.actions.includes(action) ?? false;
  }
}
