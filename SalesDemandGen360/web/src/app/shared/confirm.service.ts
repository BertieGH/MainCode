import { Injectable, signal } from '@angular/core';

/** One of several ways to do the thing being confirmed. */
export interface ConfirmChoice {
  value: string;
  label: string;
  /** What it costs, or how long it takes. Shown beside the label. */
  cost?: string;
  /** What it buys, in plain words. */
  detail?: string;
}

/** What a confirmation asks, and how its buttons read. */
export interface ConfirmRequest {
  title: string;
  /** The consequence, in plain words — counts included. Line breaks are kept. */
  body?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Styles the confirm button as destructive and focuses Cancel first. */
  danger?: boolean;
  /**
   * Offer a choice as part of confirming, rather than asking twice.
   *
   * **Here rather than in a menu** because this dialog already exists to say
   * what something will cost before it is paid for, and research now has
   * three prices. Three entries per action in an eleven-button selection bar
   * would be the same question asked in the place least able to answer it —
   * the menu cannot show what each one buys.
   */
  choices?: ConfirmChoice[];
  /** Which choice starts selected. Defaults to the first. */
  chosen?: string;
}

interface Pending extends ConfirmRequest {
  resolve: (answer: ConfirmAnswer) => void;
}

/**
 * `false` is always "no". A plain `true` is yes to a question with no choice
 * in it; a string is the choice made. Callers that never pass `choices` can
 * keep treating the result as a boolean, which is why this is a union rather
 * than an object — every existing `if (ok)` still reads correctly.
 */
export type ConfirmAnswer = boolean | string;

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

  ask(request: ConfirmRequest): Promise<ConfirmAnswer> {
    this.current()?.resolve(false);
    return new Promise<ConfirmAnswer>((resolve) =>
      this.current.set({ ...request, resolve }),
    );
  }

  answer(yes: ConfirmAnswer): void {
    const open = this.current();
    if (!open) return;
    this.current.set(null);
    open.resolve(yes);
  }
}
