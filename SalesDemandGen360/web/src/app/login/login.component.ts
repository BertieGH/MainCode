import { CommonModule } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { AuthService } from '../core/auth.service';
import { apiError } from '../shared/api-error';

/**
 * Sign in. No registration and no "forgot password" link: accounts are made
 * by an admin, who sets the password and passes it on (`docs/17`).
 *
 * The refusal is the server's own wording — "Wrong email or password." reads
 * the same for an unknown address, by design, and a lockout says how long.
 */
@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="wrap">
      <div class="auth">
        <div class="brand">Sales Demand Gen360</div>
        <div class="brand-sub">Prospect engine</div>
        <form class="card" (ngSubmit)="submit()">
          <h1>Sign in</h1>
          <p class="row-sub" style="margin-bottom:16px;">Use the email and password your admin gave you.</p>
          <label class="f">Email
            <input class="field" type="email" name="email" [(ngModel)]="email" autocomplete="username" required autofocus>
          </label>
          <label class="f">Password
            <input class="field" type="password" name="password" [(ngModel)]="password" autocomplete="current-password" required>
          </label>
          <p class="err" *ngIf="error()" role="alert">{{ error() }}</p>
          <button class="btn btn-primary wide" type="submit" [class.busy]="busy()"
                  [disabled]="busy() || !email.trim() || !password">
            {{ busy() ? 'Signing in…' : 'Sign in' }}
          </button>
        </form>
        <p class="alt">No account, or forgot your password?<br>Ask an admin — they create accounts and reset passwords.</p>
      </div>
    </div>
  `,
  styles: [`
    .wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px 16px; background: var(--bg); }
    .auth { width: 100%; max-width: 380px; }
    .brand { font-family: 'Fraunces', Georgia, serif; font-size: 1.25rem; font-weight: 600; }
    .brand-sub { font-family: 'IBM Plex Mono', monospace; font-size: .6rem; letter-spacing: .12em; text-transform: uppercase; color: var(--faint); margin-bottom: 22px; }
    h1 { font-size: 1.15rem; margin-bottom: 4px; }
    .f { display: flex; flex-direction: column; gap: 4px; font-size: .78rem; color: var(--muted); margin-bottom: 12px; }
    .f .field { width: 100%; }
    .err { color: var(--critical); font-size: .8rem; margin: -4px 0 12px; }
    .wide { width: 100%; justify-content: center; }
    .alt { margin-top: 14px; font-size: .8rem; color: var(--muted); text-align: center; }
  `],
})
export class LoginComponent {
  private auth = inject(AuthService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);

  email = '';
  password = '';
  busy = signal(false);
  error = signal<string | null>(null);

  submit(): void {
    if (this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    this.auth.login(this.email.trim(), this.password).subscribe({
      next: () => {
        this.busy.set(false);
        this.password = '';
        // Back to where a lapsed session interrupted them — but only to a
        // path inside this app, never an address carried in from outside.
        const next = this.route.snapshot.queryParamMap.get('next');
        const safe = next && next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/login');
        void this.router.navigateByUrl(safe ? next : '/lists');
      },
      error: (err) => {
        this.busy.set(false);
        this.error.set(apiError(err, 'Could not sign in.'));
      },
    });
  }
}
