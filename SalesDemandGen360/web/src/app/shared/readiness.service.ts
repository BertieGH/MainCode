import { Injectable, inject, signal } from '@angular/core';

import { ConfigService, Readiness } from '../core/config.service';

/**
 * Setup state, for screens that need to say *before* a click why an action
 * cannot run.
 *
 * Promote used to accept a whole form, send it, and fail on the server's gate
 * for La Growth Machine — then hide the refusal. Asking here first lets the
 * button say "connect La Growth Machine" instead.
 */
@Injectable({ providedIn: 'root' })
export class ReadinessService {
  private api = inject(ConfigService);
  readonly state = signal<Readiness | null>(null);

  /** Re-read on screen entry: a key connected in another tab should count. */
  refresh(): void {
    this.api.readiness().subscribe({
      next: (r) => this.state.set(r),
      // Unknown is not "missing": a failed read must not block anybody.
      error: () => undefined,
    });
  }

  /** `null` while unknown — callers must treat that as "do not block". */
  satisfied(kind: string): boolean | null {
    const s = this.state();
    if (!s) return null;
    const slot = s.slots.find((x) => x.kind === kind);
    return slot ? slot.satisfied : null;
  }
}
