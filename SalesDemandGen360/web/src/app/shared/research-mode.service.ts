import { Injectable, computed, inject, signal } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { filter } from 'rxjs';

import { ResearchTier } from '../core/lists.service';

/** The three depths, cheapest first, with what each one buys. */
export const TIERS: {
  value: ResearchTier;
  label: string;
  /** Per account. Measured from `llm_call` and `serp_call`, not estimated. */
  cost: number;
  detail: string;
}[] = [
  {
    value: 'light',
    label: 'Light',
    cost: 0.07,
    detail:
      'Their site, job boards, the LinkedIn index and trade press. '
      + 'Finds 85% of the signals the full run finds.',
  },
  {
    value: 'standard',
    label: 'Standard',
    cost: 0.105,
    detail: 'Light, plus company data and funding providers.',
  },
  {
    value: 'deep',
    label: 'Deep',
    cost: 0.245,
    detail: 'Everything: licence registers and the conference circuit.',
  },
];

/**
 * What depth research runs at here, and what it falls back to.
 *
 * **Three places can answer, and the nearest wins**: what somebody picked for
 * this visit, the list's own setting, the installation's default. The server
 * resolves the last two into `effective_tier`, so no screen has to know that
 * order — the order is exactly the thing that would drift between screens.
 *
 * **The override lasts for the visit and no longer.** It is cleared on every
 * completed navigation, so switching to Deep to work one account cannot
 * silently become the setting that researches the next two hundred. A
 * lasting change is the list's dropdown or the installation's, both of which
 * say what they are.
 */
@Injectable({ providedIn: 'root' })
export class ResearchModeService {
  private router = inject(Router);

  /** The installation's answer. Loaded once; a screen may ask again. */
  readonly appDefault = signal<ResearchTier>('standard');
  /** Picked for this visit, or null when nothing has been picked. */
  private readonly override = signal<ResearchTier | null>(null);
  readonly overridden = computed(() => this.override() !== null);

  constructor() {
    this.router.events
      .pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd))
      .subscribe(() => this.override.set(null));
  }

  /**
   * Told, not fetched.
   *
   * **This service makes no HTTP call of its own, deliberately.** The first
   * version loaded the setting in its constructor, and because it is
   * root-provided that request appeared in every component test that renders
   * anything using it — 71 specs failed on one unexpected GET. A shared thing
   * that fetches is a shared thing that breaks every parent's expectations;
   * the shell loads this once and hands it over.
   */
  setAppDefault(tier: ResearchTier | undefined | null): void {
    if (tier) this.appDefault.set(tier);
  }

  /** What a run would use, given what this screen knows. */
  effective(scopeDefault?: ResearchTier | null): ResearchTier {
    return this.override() ?? scopeDefault ?? this.appDefault();
  }

  pick(tier: ResearchTier | null): void {
    this.override.set(tier);
  }

  static label(tier: ResearchTier): string {
    return TIERS.find((t) => t.value === tier)?.label ?? tier;
  }
}
