import { Injectable, Optional, signal } from '@angular/core';

import { ActivityService, activityLog } from './activity.service';

export type NoticeKind = 'success' | 'info' | 'warning' | 'error';

/** A button on a notice. Retry is the only one so far. */
export interface NoticeAction {
  label: string;
  run: () => void;
}

export interface Notice {
  id: number;
  kind: NoticeKind;
  text: string;
  /** The server's reason, or what was left out — shown smaller beneath. */
  detail: string | null;
  action: NoticeAction | null;
  /** The Activity entry this notice was recorded as — "View in activity". */
  activityId: string | null;
}

export interface NoticeOptions {
  /**
   * Offered as a Retry button. Pass it only where running the same thing again
   * is safe — a save, a load, a redraw — never where a second try could send,
   * bill or duplicate something.
   */
  retry?: () => void;
}

/**
 * What an action did, shown where it cannot be scrolled past.
 *
 * The screens used to write outcomes into a banner at the top of the page.
 * Promote failed that way: the card closed, the reason appeared above the fold,
 * and the click looked like it had done nothing. Notices sit in a fixed stack
 * in the corner instead (`app-toast-host`).
 *
 * Success and info clear themselves. Warnings and errors stay until dismissed —
 * a partial result or a refusal is exactly the message a rep must not miss.
 */
@Injectable({ providedIn: 'root' })
export class NotifyService {
  /** How long a success lingers. Long enough to read a sentence. */
  static readonly SUCCESS_MS = 5000;
  /** More than this and the oldest drop off; a wall of notices is noise. */
  static readonly MAX = 4;

  readonly notices = signal<Notice[]>([]);
  private seq = 0;

  /**
   * Every notice is also kept in the Activity log, so it can be traced after
   * it has cleared. Optional: unit tests build this with `new` and no log.
   */
  private readonly activity: ActivityService | null;

  constructor(@Optional() activity?: ActivityService) {
    this.activity = activity ?? activityLog();
  }

  success(text: string, detail?: string | null, opts?: NoticeOptions): void {
    this.push('success', text, detail, NotifyService.SUCCESS_MS, opts);
  }

  info(text: string, detail?: string | null, opts?: NoticeOptions): void {
    this.push('info', text, detail, NotifyService.SUCCESS_MS, opts);
  }

  warning(text: string, detail?: string | null, opts?: NoticeOptions): void {
    this.push('warning', text, detail, undefined, opts);
  }

  error(text: string, detail?: string | null, opts?: NoticeOptions): void {
    this.push('error', text, detail, undefined, opts);
  }

  dismiss(id: number): void {
    this.notices.update((all) => all.filter((n) => n.id !== id));
  }

  /**
   * Whether an HTTP failure is worth offering Retry for: no answer at all, or
   * a server fault. A 4xx is the server saying no for a reason, and asking
   * again gets the same reason.
   */
  static retryable(err: unknown): boolean {
    const status = (err as { status?: number })?.status;
    return !status || status >= 500;
  }

  private push(
    kind: NoticeKind, text: string, detail?: string | null, ttlMs?: number,
    opts?: NoticeOptions,
  ): void {
    const entry = this.activity?.record(kind, text, detail ?? null) ?? null;
    const notice: Notice = {
      id: ++this.seq,
      kind,
      text,
      detail: detail ?? null,
      action: opts?.retry ? { label: 'Retry', run: opts.retry } : null,
      activityId: entry?.id ?? null,
    };
    this.notices.update((all) => [...all, notice].slice(-NotifyService.MAX));
    if (ttlMs) setTimeout(() => this.dismiss(notice.id), ttlMs);
  }
}
