import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="login-container">
      <div class="login-card">
        <h1>LeadPulse</h1>
        <p class="subtitle">Insurance Lead Generation Platform</p>

        <div class="tabs">
          <button [class.active]="loginType === 'platform'" (click)="loginType = 'platform'">Platform Admin</button>
          <button [class.active]="loginType === 'tenant'" (click)="loginType = 'tenant'">Tenant User</button>
        </div>

        <form (ngSubmit)="onLogin()">
          <div *ngIf="loginType === 'tenant'" class="form-group">
            <label>Tenant ID</label>
            <input type="number" [(ngModel)]="tenantId" name="tenantId" required>
          </div>
          <div class="form-group">
            <label>Email</label>
            <input type="email" [(ngModel)]="email" name="email" required>
          </div>
          <div class="form-group">
            <label>Password</label>
            <input type="password" [(ngModel)]="password" name="password" required>
          </div>
          <div *ngIf="error" class="error">{{ error }}</div>
          <button type="submit" class="btn-primary" [disabled]="loading">
            {{ loading ? 'Signing in...' : 'Sign In' }}
          </button>
        </form>
      </div>
    </div>
  `,
  styles: [`
    .login-container {
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; background: #f5f7fa;
    }
    .login-card {
      background: white; padding: 2rem; border-radius: 8px;
      box-shadow: 0 4px 24px rgba(0,0,0,0.1); width: 400px;
    }
    h1 { color: #1a1f36; margin: 0 0 0.25rem; }
    .subtitle { color: #6b7280; margin: 0 0 1.5rem; }
    .tabs { display: flex; gap: 0.5rem; margin-bottom: 1.5rem; }
    .tabs button {
      flex: 1; padding: 0.5rem; border: 1px solid #e5e7eb; border-radius: 4px;
      background: white; cursor: pointer;
    }
    .tabs button.active { background: #2563eb; color: white; border-color: #2563eb; }
    .form-group { margin-bottom: 1rem; }
    label { display: block; margin-bottom: 0.25rem; font-weight: 500; color: #374151; }
    input {
      width: 100%; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px;
      box-sizing: border-box;
    }
    .btn-primary {
      width: 100%; padding: 0.75rem; background: #2563eb; color: white;
      border: none; border-radius: 4px; cursor: pointer; font-size: 1rem;
    }
    .btn-primary:disabled { opacity: 0.6; }
    .error { color: #ef4444; margin-bottom: 1rem; font-size: 0.875rem; }
  `]
})
export class LoginComponent {
  loginType: 'platform' | 'tenant' = 'tenant';
  email = '';
  password = '';
  tenantId = 1;
  error = '';
  loading = false;

  constructor(private authService: AuthService, private router: Router) {}

  onLogin(): void {
    this.loading = true;
    this.error = '';

    const obs = this.loginType === 'platform'
      ? this.authService.loginPlatform({ email: this.email, password: this.password })
      : this.authService.loginTenant({ tenantId: this.tenantId, email: this.email, password: this.password });

    obs.subscribe({
      next: (result) => {
        this.loading = false;
        if (result.success) {
          this.router.navigate(['/dashboard']);
        } else {
          this.error = result.error || 'Login failed';
        }
      },
      error: (err) => {
        this.loading = false;
        this.error = err.error?.error || 'An error occurred';
      }
    });
  }
}
