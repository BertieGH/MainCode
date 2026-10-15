import { CommonModule } from '@angular/common';
import {
  Component, ElementRef, HostListener, ViewChild, effect, inject, signal,
} from '@angular/core';

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

        <!-- A radio group rather than a select: three options whose whole
             point is the comparison between them, and a select hides two
             thirds of it behind a click. -->
        <div class="choices" *ngIf="c.choices?.length" role="radiogroup"
             [attr.aria-label]="c.title">
          <label class="choice" *ngFor="let ch of c.choices"
                 [class.on]="picked() === ch.value">
            <input type="radio" name="confirm-choice" [value]="ch.value"
                   [checked]="picked() === ch.value"
                   (change)="picked.set(ch.value)" />
            <span class="line">
              <span class="label">{{ ch.label }}</span>
              <span class="cost" *ngIf="ch.cost">{{ ch.cost }}</span>
            </span>
            <span class="detail" *ngIf="ch.detail">{{ ch.detail }}</span>
          </label>
        </div>

        <div class="actions">
          <button #cancel type="button" class="btn" (click)="svc.answer(false)">
            {{ c.cancelLabel ?? 'Cancel' }}
          </button>
          <button #ok type="button" class="btn" [class.btn-primary]="!c.danger"
                  [class.danger]="c.danger" (click)="confirm()">
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
      .choices { display: flex; flex-direction: column; gap: 6px; margin: 0 0 16px; }
      .choice { display: grid; grid-template-columns: auto 1fr; gap: 2px 9px;
                align-items: start; padding: 9px 11px; border-radius: 8px;
                border: 1px solid var(--line); cursor: pointer; }
      .choice.on { border-color: var(--accent, #3b5bdb);
                   background: rgba(59, 91, 219, 0.045); }
      .choice input { margin: 2px 0 0; grid-row: span 2; }
      .line { display: flex; justify-content: space-between; gap: 10px;
              align-items: baseline; font-size: 0.86rem; }
      .label { font-weight: 500; }
      .cost { font-family: 'IBM Plex Mono', monospace; font-size: 0.76rem;
              color: var(--muted); white-space: nowrap; }
      .detail { font-size: 0.78rem; color: var(--muted); line-height: 1.45; }
    `,
  ],
})
export class ConfirmHostComponent {
  svc = inject(ConfirmService);
  /** The choice on screen. Meaningless, and unread, without `choices`. */
  picked = signal<string>('');
  @ViewChild('ok') ok?: ElementRef<HTMLButtonElement>;
  @ViewChild('cancel') cancel?: ElementRef<HTMLButtonElement>;

  constructor() {
    effect(() => {
      const open = this.svc.current();
      if (!open) return;
      // Reset per dialog, or the second one opens on the first one's answer.
      this.picked.set(open.chosen ?? open.choices?.[0]?.value ?? '');
      // After render: the buttons do not exist until the dialog is drawn.
      setTimeout(() => this.ok?.nativeElement.focus());
      // `allowSignalWrites`, because the line above that resets `picked` is a
      // signal write inside an effect and Angular refuses those by default —
      // silently, as a thrown NG0600 nothing here catches. The symptom was a
      // dialog that opened with no option selected and answered with an empty
      // string, which a caller reads as "cancel".
    }, { allowSignalWrites: true });
  }

  /** Yes, carrying the choice when the dialog offered one. */
  confirm(): void {
    const open = this.svc.current();
    this.svc.answer(open?.choices?.length ? this.picked() : true);
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
      // Through `confirm()`, or Enter would answer a dialog with three
      // prices on it as a bare yes and buy whichever the caller defaulted to.
      this.confirm();
    }
  }
}
