import { Injectable, computed, inject, signal } from '@angular/core';

export type ActivityKind = 'success' | 'info' | 'warning' | 'error';

/** One account's result inside a run — "Figma — Apollo rate limit reached". */
export interface ActivityItem {
  name: string;
  kind: 'success' | 'warning' | 'error';
  text: string;
}

/** How a run went, attached to the message it ended with. */
export interface ActivityRun {
  verb: string;
  completed: number;
  total: number;
  cancelled: boolean;
  elapsed: string;
}

export interface ActivityEntry {
  id: string;
  at: number;
  kind: ActivityKind;
  text: string;
  detail: string | null;
  /** Where it happened — "List · test", or the section of the app. */
  where: string | null;
  path: string;
  items: ActivityItem[];
  run: ActivityRun | null;
}

/** A finished run waiting for the message that reports it. */
interface StagedRun {
  run: ActivityRun;
  items: ActivityItem[];
  at: number;
}

const ENTRIES_KEY = 'sdg360.activity.v1';
const SEEN_KEY = 'sdg360.activity.seen';

/**
 * Every outcome message, kept — so a result can be traced after its notice is gone.
 *
 * Notices in the corner are for the moment: a success clears itself in five
 * seconds, and a fifth notice pushes the oldest out. Reported: "the run
 * message/error go away and not able to trace". Everything `NotifyService`
 * says is recorded here too, newest first, with where it happened and — for a
 * run over several accounts — each account's own result.
 *
 * Kept in this browser (`localStorage`), capped at `MAX`. It is a trace of what
 * this person did, not a shared record; the server's own tables remain the
 * record of what happened to the data.
 */
@Injectable({ providedIn: 'root' })
export class ActivityService {
  static readonly MAX = 200;
  /** A run's per-account results attach to a message that follows within this. */
  static readonly STAGE_MS = 15000;

  readonly entries = signal<ActivityEntry[]>(ActivityService.load());
  /** When the panel was last opened; errors after this count as unseen. */
  readonly seenAt = signal<number>(ActivityService.loadSeen());
  readonly open = signal(false);
  /** The entry "View in activity" pointed at. */
  readonly highlight = signal<string | null>(null);
  /** Set by a page that knows a better name for where things happen. */
  readonly where = signal<string | null>(null);

  readonly unseenErrors = computed(
    () => this.entries().filter((e) => e.kind === 'error' && e.at > this.seenAt()).length,
  );
  readonly todayCount = computed(() => {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    return this.entries().filter((e) => e.at >= start.getTime()).length;
  });

  private staged: StagedRun | null = null;
  private seq = 0;

  /** Record one outcome. Returns the entry, for a notice to point at. */
  record(kind: ActivityKind, text: string, detail: string | null = null): ActivityEntry {
    const now = Date.now();
    const staged = this.staged && now - this.staged.at <= ActivityService.STAGE_MS ? this.staged : null;
    this.staged = null;
    const path = typeof location !== 'undefined' ? location.pathname : '';
    const entry: ActivityEntry = {
      id: `${now.toString(36)}-${(++this.seq).toString(36)}`,
      at: now,
      kind,
      text,
      detail,
      where: this.where() ?? ActivityService.section(path),
      path,
      items: staged?.items ?? [],
      run: staged?.run ?? null,
    };
    this.entries.update((all) => [entry, ...all].slice(0, ActivityService.MAX));
    this.save();
    return entry;
  }

  /** A run has finished; its results belong to the message that reports it next. */
  stageRun(run: ActivityRun, items: ActivityItem[]): void {
    this.staged = { run, items, at: Date.now() };
  }

  toggle(): void {
    this.open.update((v) => !v);
    if (this.open()) this.markSeen();
  }

  /** Open the panel on one entry — "View in activity" from a notice. */
  reveal(id: string): void {
    this.open.set(true);
    this.highlight.set(id);
    this.markSeen();
    setTimeout(() => {
      if (typeof document === 'undefined') return;
      document.getElementById(`act-${id}`)?.scrollIntoView({ block: 'nearest' });
      if (typeof window !== 'undefined') window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  markSeen(): void {
    this.seenAt.set(Date.now());
    try {
      localStorage.setItem(SEEN_KEY, String(this.seenAt()));
    } catch {
      /* a private window — the count simply resets on reload */
    }
  }

  clear(): void {
    this.entries.set([]);
    this.highlight.set(null);
    this.save();
  }

  /** "lists/abc" → "Lists": where a message came from when no page said. */
  static section(path: string): string | null {
    const first = (path || '').split('/').filter(Boolean)[0];
    return first ? first.charAt(0).toUpperCase() + first.slice(1) : null;
  }

  private save(): void {
    try {
      localStorage.setItem(ENTRIES_KEY, JSON.stringify(this.entries()));
    } catch {
      /* storage full or unavailable — the panel still works for this visit */
    }
  }

  private static load(): ActivityEntry[] {
    try {
      const raw = localStorage.getItem(ENTRIES_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed.slice(0, ActivityService.MAX) : [];
    } catch {
      return [];
    }
  }

  private static loadSeen(): number {
    try {
      return Number(localStorage.getItem(SEEN_KEY)) || 0;
    } catch {
      return 0;
    }
  }
}

/**
 * The shared log when there is an injection context, and none otherwise.
 * `NotifyService` and `SequentialRun` are also built with `new` in unit tests,
 * where `inject` throws; they simply keep no trace there.
 */
export function activityLog(): ActivityService | null {
  try {
    return inject(ActivityService);
  } catch {
    return null;
  }
}
