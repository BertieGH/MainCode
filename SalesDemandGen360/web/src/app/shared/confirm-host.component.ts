import { CommonModule } from '@angular/common';
import { Component, ElementRef, HostListener, ViewChild, effect, inject } from '@angular/core';

import { ConfirmService } from './confirm.service';

/**
 * The dialog behind `ConfirmService`. Mounted once, in the app shell.
 *
 * Escape and the backdrop mean "no"; Enter means "yes". Focus starts on the
 * confirm button, whose label names the act — "Delete queue", "Stop campaign" —
 * so what Enter will do is always the thing on screen. Tab to Cancel and Enter
 * presses Cancel, as any focused button would.
 */
@Component({
  selector: 'app-confirm-host',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="backdrop" *ngIf="svc.current() as c" (click)="svc.answer(false)">
      <div class="dialog" role="alertdialog" aria-modal="true"
           aria-labelledby="confirm-title" [attr.aria-describedby]="c.body ? 'confirm-body' : null"
           (click)="$event.stopPropagation()">
        <h3 id="confirm-title">{{ c.title }}</h3>
        <p id="confirm-body" *ngIf="c.body">{{ c.body }}</p>
        <div class="actions">
          <button #cancel type="button" class="btn" (click)="svc.answer(false)">
            {{ c.cancelLabel ?? 'Cancel' }}
          </button>
          <button #ok type="button" class="btn" [class.btn-primary]="!c.danger"
                  [class.danger]="c.danger" (click)="svc.answer(true)">
            {{ c.confirmLabel ?? 'Confirm' }}
          </button>
        </div>
      </div>
    </div>
  `,
  styles: [
    `
      .backdrop { position: fixed; inset: 0; z-index: 1000; background: rgba(10, 14, 20, 0.42);
                  display: flex; align-items: flex-start; justify-content: center; padding-top: 14vh; }
      .dialog { background: var(--card, #fff); color: inherit; border-radius: 10px;
                border: 1px solid var(--line); box-shadow: 0 18px 50px rgba(0, 0, 0, 0.28);
                width: min(460px, calc(100vw - 32px)); padding: 18px 20px 16px; }
      h3 { font-size: 1rem; margin: 0 0 8px; }
      p { margin: 0 0 16px; font-size: 0.86rem; color: var(--muted); white-space: pre-line; }
      .actions { display: flex; justify-content: flex-end; gap: 8px; }
    `,
  ],
})
export class ConfirmHostComponent {
  svc = inject(ConfirmService);
  @ViewChild('ok') ok?: ElementRef<HTMLButtonElement>;
  @ViewChild('cancel') cancel?: ElementRef<HTMLButtonElement>;

  constructor() {
    effect(() => {
      const open = this.svc.current();
      if (!open) return;
      // After render: the buttons do not exist until the dialog is drawn.
      setTimeout(() => this.ok?.nativeElement.focus());
    });
  }

  @HostListener('document:keydown', ['$event'])
  onKey(event: KeyboardEvent): void {
    if (!this.svc.current()) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      this.svc.answer(false);
      return;
    }
    if (event.key === 'Enter') {
      // A focused Cancel keeps its meaning; anywhere else Enter confirms.
      if (document.activeElement === this.cancel?.nativeElement) return;
      event.preventDefault();
      this.svc.answer(true);
    }
  }
}
