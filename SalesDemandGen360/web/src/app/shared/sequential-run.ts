import { computed, signal } from '@angular/core';
import { Observable, firstValueFrom } from 'rxjs';

import { ActivityItem, ActivityService, activityLog } from './activity.service';
import { apiError } from './api-error';

/** One thing a run works through — an account, usually. */
export interface RunItem {
  id: string;
  name: string;
}

/** What a run looks like while it is going. `null` when nothing is running. */
export interface RunState {
  /** "Researching", "Enriching" — what the progress line says it is doing. */
  verb: string;
  done: number;
  total: number;
  /** The item in flight. */
  current: string | null;
  startedAt: number;
  /** Cancel was pressed; the run stops once the item in flight returns. */
  cancelling: boolean;
  /** What has come back so far, in the caller's words. */
  summary: string;
}

export interface RunOutcome {
  completed: number;
  /** Stopped by Cancel before the last item. */
  cancelled: boolean;
  /** Stopped because a result or error said to — a blocked capability, say. */
  stopped: boolean;
}

/**
 * Slow actions, one item at a time, where the screen can watch.
 *
 * Resolve, enrich and research used to be one request each for the whole
 * selection: the button spun for a minute or three and then everything
 * arrived at once, or nothing did. The server already worked through the
 * accounts in order — this moves that loop into the browser, so the screen
 * can say "Researching 3 of 8… 0:42" and mean it, show partial results as
 * they land, and stop between accounts when asked.
 *
 * Cancel never abandons a request in flight. The server would carry on (and
 * bill) regardless, so pretending otherwise would only hide a result that
 * then turns up anyway. It stops before the *next* item, and says so.
 */
export class SequentialRun {
  readonly state = signal<RunState | null>(null);
  readonly busy = computed(() => this.state() !== null);
  /** Ticks once a second while running, so an elapsed clock can be shown. */
  readonly now = signal(Date.now());

  private cancelRequested = false;

  /** Where each item's result is kept, for the message that reports the run. */
  constructor(private readonly activity: ActivityService | null = activityLog()) {}

  /** "0:42" since the run started. */
  readonly elapsed = computed(() => {
    const s = this.state();
    if (!s) return '0:00';
    const secs = Math.max(0, Math.floor((this.now() - s.startedAt) / 1000));
    return `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`;
  });

  cancel(): void {
    this.cancelRequested = true;
    this.state.update((s) => (s ? { ...s, cancelling: true } : s));
  }

  async run<T>(opts: {
    verb: string;
    items: RunItem[];
    call: (id: string) => Observable<T>;
    /** Return 'stop' to end the run — a refusal that would repeat for every item. */
    onResult: (item: RunItem, result: T) => 'stop' | void | undefined;
    onError: (item: RunItem, error: unknown) => 'stop' | void | undefined;
    summary: () => string;
    /** One item's result in a line, for the Activity log. Errors describe themselves. */
    describe?: (item: RunItem, result: T) => Omit<ActivityItem, 'name'>;
  }): Promise<RunOutcome> {
    const total = opts.items.length;
    this.cancelRequested = false;
    this.now.set(Date.now());
    this.state.set({
      verb: opts.verb, done: 0, total, current: null,
      startedAt: Date.now(), cancelling: false, summary: '',
    });
    const clock = setInterval(() => this.now.set(Date.now()), 1000);

    let completed = 0;
    let stopped = false;
    const noted: ActivityItem[] = [];
    try {
      for (const item of opts.items) {
        if (this.cancelRequested) break;
        this.state.update((s) => (s ? { ...s, current: item.name } : s));
        let verdict: 'stop' | void | undefined;
        let result: T;
        try {
          result = await firstValueFrom(opts.call(item.id));
        } catch (err) {
          // One failure costs one item, not the run — unless the caller says
          // the same failure would repeat for every item.
          noted.push({ name: item.name, kind: 'error', text: failure(err) });
          verdict = opts.onError(item, err);
          completed += 1;
          this.state.update((s) => (s ? { ...s, done: completed, summary: opts.summary() } : s));
          if (verdict === 'stop') {
            stopped = true;
            break;
          }
          continue;
        }
        noted.push({ name: item.name, ...(opts.describe?.(item, result) ?? { kind: 'success', text: 'done' }) });
        try {
          verdict = opts.onResult(item, result);
        } catch (err) {
          verdict = opts.onError(item, err);
        }
        completed += 1;
        this.state.update((s) => (s ? { ...s, done: completed, summary: opts.summary() } : s));
        if (verdict === 'stop') {
          stopped = true;
          break;
        }
      }
    } finally {
      clearInterval(clock);
      const cancelled = this.cancelRequested && completed < total;
      this.activity?.stageRun(
        { verb: opts.verb, completed, total, cancelled, elapsed: this.elapsed() },
        noted,
      );
      this.state.set(null);
    }
    return { completed, cancelled: this.cancelRequested && completed < total, stopped };
  }
}


/** An item's failure in words: the server's message when it gave one. */
function failure(err: unknown): string {
  const detail = (err as { error?: { detail?: { message?: string } } })?.error?.detail;
  return (detail && typeof detail === 'object' && detail.message) || apiError(err, 'failed');
}
