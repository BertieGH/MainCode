import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { AuthService } from '../../../core/services/auth.service';

@Component({
  selector: 'app-register',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    ReactiveFormsModule,
    MatCardModule,
    MatButtonModule,
    MatInputModule,
    MatIconModule,
    MatProgressSpinnerModule
  ],
  template: `
    <div class="auth-container">
      <mat-card class="auth-card">
        <div class="auth-header">
        <div class="logo">
          <img src="assets/company-logo.png" alt="Company Logo">
        </div>
          <h1> CG-VAK SurveyHub</h1>
          <p>Create a new account</p>
        </div>

        <div *ngIf="error" class="error-banner">
          <mat-icon>error_outline</mat-icon>
          {{ error }}
        </div>

        <form [formGroup]="registerForm" (ngSubmit)="onSubmit()">
          <mat-form-field appearance="outline" class="full-width">
            <mat-label>Username</mat-label>
            <input matInput formControlName="username" autocomplete="username">
            <mat-icon matPrefix>person</mat-icon>
            <mat-error *ngIf="registerForm.get('username')?.hasError('required')">
              Username is required
            </mat-error>
            <mat-error *ngIf="registerForm.get('username')?.hasError('minlength')">
              Username must be at least 3 characters
            </mat-error>
          </mat-form-field>

          <mat-form-field appearance="outline" class="full-width">
            <mat-label>Email</mat-label>
            <input matInput formControlName="email" type="email" autocomplete="email">
            <mat-icon matPrefix>email</mat-icon>
            <mat-error *ngIf="registerForm.get('email')?.hasError('required')">
              Email is required
            </mat-error>
            <mat-error *ngIf="registerForm.get('email')?.hasError('email')">
              Please enter a valid email
            </mat-error>
          </mat-form-field>

          <mat-form-field appearance="outline" class="full-width">
            <mat-label>Password</mat-label>
            <input matInput [type]="hidePassword ? 'password' : 'text'" formControlName="password" autocomplete="new-password">
            <mat-icon matPrefix>lock</mat-icon>
            <button mat-icon-button matSuffix type="button" (click)="hidePassword = !hidePassword">
              <mat-icon>{{ hidePassword ? 'visibility_off' : 'visibility' }}</mat-icon>
            </button>
            <mat-error *ngIf="registerForm.get('password')?.hasError('required')">
              Password is required
            </mat-error>
            <mat-error *ngIf="registerForm.get('password')?.hasError('minlength')">
              Password must be at least 8 characters
            </mat-error>
          </mat-form-field>

          <button mat-raised-button color="primary" type="submit" class="full-width submit-btn"
                  [disabled]="registerForm.invalid || loading">
            <mat-spinner *ngIf="loading" diameter="20"></mat-spinner>
            <span *ngIf="!loading">Create Account</span>
          </button>
        </form>

        <div class="auth-footer">
          <span>Already have an account?</span>
          <a routerLink="/login">Sign in</a>
        </div>
      </mat-card>
    </div>
  `,
  styles: [`
    .auth-container {
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
      padding: 24px;
    }

    .auth-card {
      width: 100%;
      max-width: 420px;
      padding: 40px;
    }

    .auth-header {
      text-align: center;
      margin-bottom: 32px;
    }

    .logo {
      width: 56px;
      height: 56px;
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      border-radius: 16px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 24px;
      color: #fff;
      margin: 0 auto 16px;
    }

    .auth-header h1 {
      margin: 0;
      font-size: 24px;
      font-weight: 700;
      color: var(--text-primary, #1a1a2e);
    }

    .auth-header p {
      margin: 8px 0 0;
      color: var(--text-muted, #666);
      font-size: 14px;
    }

    .full-width {
      width: 100%;
    }

    .submit-btn {
      height: 48px;
      font-size: 16px;
      margin-top: 8px;
    }

    .error-banner {
      background: #fef2f2;
      color: #dc2626;
      padding: 12px 16px;
      border-radius: 8px;
      margin-bottom: 24px;
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 14px;
    }

    .auth-footer {
      text-align: center;
      margin-top: 24px;
      font-size: 14px;
      color: var(--text-muted, #666);
    }

    .auth-footer a {
      color: #6366f1;
      text-decoration: none;
      font-weight: 500;
      margin-left: 4px;
    }

    .auth-footer a:hover {
      text-decoration: underline;
    }

    mat-spinner {
      display: inline-block;
    }
  `]
})
export class RegisterComponent {
  registerForm: FormGroup;
  loading = false;
  error: string | null = null;
  hidePassword = true;

  constructor(
    private fb: FormBuilder,
    private authService: AuthService,
    private router: Router
  ) {
    this.registerForm = this.fb.group({
      username: ['', [Validators.required, Validators.minLength(3)]],
      email: ['', [Validators.required, Validators.email]],
      password: ['', [Validators.required, Validators.minLength(8)]]
    });
  }

  private extractError(err: any): string {
    if (err?.status === 0) return 'Unable to connect to server. Please check your connection.';
    if (err?.status === 404) return 'Registration endpoint not found. The server may need to be restarted.';
    const body = err?.error;
    if (typeof body === 'string') return body;
    if (body?.errors) {
      const msgs = Object.values(body.errors).flat();
      return msgs.join('. ');
    }
    return body?.message || body?.title || 'Registration failed. Please try again.';
  }

  onSubmit(): void {
    if (this.registerForm.invalid) return;

    this.loading = true;
    this.error = null;

    this.authService.register(this.registerForm.value).subscribe({
      next: () => {
        this.router.navigate(['/']);
      },
      error: (err) => {
        this.error = this.extractError(err);
        this.loading = false;
      }
    });
  }
}
