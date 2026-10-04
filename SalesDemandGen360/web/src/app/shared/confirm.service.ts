import { Injectable, signal } from '@angular/core';

/** What a confirmation asks, and how its buttons read. */
export interface ConfirmRequest {
  title: string;
  /** The consequence, in plain words — counts included. Line breaks are kept. */
  body?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Styles the confirm button as destructive and focuses Cancel first. */
  danger?: boolean;
}

interface Pending extends ConfirmRequest {
  resolve: (answer: boolean) => void;
}

/**
 * Ask before doing something that cannot be taken back.
 *
 * Replaces `window.confirm`, which the in-app browser suppresses: measured,
 * it returned `false` in 45 ms without ever drawing a dialog. Every delete,
 * remove and reject built on it therefore cancelled itself silently, and the
 * screens read as broken. This renders its own dialog (`app-confirm-host`), so
 * it behaves the same in every browser.
 *
 * One question at a time. Asking again while a dialog is open answers the
 * first one "no" — two stacked confirmations are a question nobody can read.
 */
@Injectable({ providedIn: 'root' })
export class ConfirmService {
  readonly current = signal<Pending | null>(null);

  ask(request: ConfirmRequest): Promise<boolean> {
    this.current()?.resolve(false);
    return new Promise<boolean>((resolve) => this.current.set({ ...request, resolve }));
  }

  answer(yes: boolean): void {
    const open = this.current();
    if (!open) return;
    this.current.set(null);
    open.resolve(yes);
  }
}
