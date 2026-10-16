import { CommonModule } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { AuthService, ROLE_LABELS } from '../core/auth.service';
import { apiError } from './api-error';
import { NotifyService } from './notify.service';

/**
 * Who is signed in, at the foot of the sidebar, and the two things they can
 * do about it: change their password, or sign out.
 *
 * Changing your password signs out every other browser you are in — the
 * server bumps your session version and re-issues this one's cookie.
 */
@Component({
  selector: 'app-user-menu',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="me" *ngIf="auth.user() as u">
      <button type="button" class="me-btn" (click)="open.set(!open())"
              [attr.aria-expanded]="open()" aria-haspopup="menu">
        <span class="me-name">{{ u.full_name }}</span>
        <span class="me-role">{{ roleLabels[u.role] }}</span>
      </button>
      <div class="me-menu" *ngIf="open()" role="menu">
        <div class="me-email">{{ u.email }}</div>
        <button type="button" role="menuitem" (click)="openPassword()">Change password</button>
        <button type="button" role="menuitem" (click)="signOut()">Sign out</button>
      </div>
    </div>

    <div class="pw-backdrop" *ngIf="pwOpen()" (click)="pwOpen.set(false)">
      <form class="card pw" (click)="$event.stopPropagation()" (ngSubmit)="savePassword()"
            role="dialog" aria-modal="true" aria-labelledby="pw-title">
        <h3 id="pw-title">Change password</h3>
        <label class="f">Current password
          <input class="field" type="password" name="current" [(ngModel)]="pw.current" autocomplete="current-password" required>
        </label>
        <label class="f">New password <span class="row-sub">at least 10 characters</span>
          <input class="field" type="password" name="next" [(ngModel)]="pw.next" autocomplete="new-password" required>
        </label>
        <label class="f">New password again
          <input class="field" type="password" name="again" [(ngModel)]="pw.again" autocomplete="new-password" required>
        </label>
        <p class="pw-err" *ngIf="pwError()" role="alert">{{ pwError() }}</p>
        <div style="display:flex;gap:10px;">
          <button class="btn btn-primary" type="submit" [class.busy]="pwBusy()"
                  [disabled]="pwBusy() || !pw.current || !pw.next || !pw.again">
            {{ pwBusy() ? 'Saving…' : 'Change password' }}
          </button>
          <button class="btn" type="button" (click)="pwOpen.set(false)">Cancel</button>
        </div>
      </form>
    </div>
  `,
  styles: [`
    .me { position: relative; }
    .me-btn { width: 100%; text-align: left; font: inherit; background: var(--sidebar-active); border: 0; border-radius: 9px; padding: 9px 10px; cursor: pointer; display: flex; flex-direction: column; }
    .me-name { color: #fff; font-size: .84rem; font-weight: 500; }
    .me-role { font-family: 'IBM Plex Mono', monospace; font-size: .62rem; letter-spacing: .08em; text-transform: uppercase; color: var(--sidebar-dim); }
    .me-menu { position: absolute; bottom: calc(100% + 6px); left: 0; right: 0; background: var(--surface); border: 1px solid var(--border); border-radius: 9px; box-shadow: var(--shadow); padding: 6px; z-index: 20; }
    .me-email { font-size: .74rem; color: var(--muted); padding: 4px 9px 6px; overflow-wrap: anywhere; }
    .me-menu button { display: block; width: 100%; text-align: left; font: inherit; font-size: .82rem; padding: 7px 9px; border: 0; background: none; color: var(--text); border-radius: 6px; cursor: pointer; }
    .me-menu button:hover { background: var(--surface-2); }
    .pw-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.35); display: flex; align-items: center; justify-content: center; z-index: 50; padding: 16px; }
    .pw { width: 100%; max-width: 380px; }
    .pw h3 { font-size: 1rem; margin-bottom: 12px; }
    .f { display: flex; flex-direction: column; gap: 4px; font-size: .78rem; color: var(--muted); margin-bottom: 12px; }
    .pw-err { color: var(--critical); font-size: .8rem; margin: -4px 0 12px; }
  `],
})
export class UserMenuComponent {
  readonly auth = inject(AuthService);
  private router = inject(Router);
  private notify = inject(NotifyService);
  readonly roleLabels = ROLE_LABELS;

  open = signal(false);
  pwOpen = signal(false);
  pwBusy = signal(false);
  pwError = signal<string | null>(null);
  pw = { current: '', next: '', again: '' };

  signOut(): void {
    this.open.set(false);
    this.auth.logout().subscribe(() => void this.router.navigate(['/login']));
  }

  openPassword(): void {
    this.open.set(false);
    this.pw = { current: '', next: '', again: '' };
    this.pwError.set(null);
    this.pwOpen.set(true);
  }

  savePassword(): void {
    if (this.pw.next !== this.pw.again) {
      this.pwError.set('The two new passwords differ.');
      return;
    }
    this.pwBusy.set(true);
    this.pwError.set(null);
    this.auth.changePassword(this.pw.current, this.pw.next).subscribe({
      next: () => {
        this.pwBusy.set(false);
        this.pwOpen.set(false);
        this.notify.success('Password changed.', 'Any other browser you were signed in on is signed out.');
      },
      error: (err) => {
        this.pwBusy.set(false);
        this.pwError.set(apiError(err, 'The password was not changed.'));
      },
    });
  }
}
