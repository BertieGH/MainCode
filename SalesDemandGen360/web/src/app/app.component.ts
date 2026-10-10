import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { NavigationEnd, NavigationStart, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';

import { ConfigService, Readiness } from './core/config.service';

/** Where the browse-anyway choice is remembered. */
const BROWSE_KEY = 'sdg360.browseBeforeSetup';

import { ConfirmHostComponent } from './shared/confirm-host.component';
import { ToastHostComponent } from './shared/toast-host.component';
import { ActivityBarComponent } from './shared/activity-bar.component';
import { ActivityService } from './shared/activity.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterOutlet, RouterLink, RouterLinkActive, ConfirmHostComponent, ToastHostComponent, ActivityBarComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent implements OnInit {
  private api = inject(ConfigService);
  private router = inject(Router);
  private activity = inject(ActivityService);

  /**
   * Three external connections are mandatory. Until each is stored *and*
   * verified, the pipeline is locked — enforced by the server, mirrored here.
   *
   * `null` means we have not asked yet. Treated as "not gated" so a slow or
   * failed readiness call never locks somebody out of their own application;
   * the server refuses the dangerous actions regardless, so the worst case is
   * an enabled link that lands on a 409 with the reason.
   */
  readiness = signal<Readiness | null>(null);

  /**
   * An explicit choice to navigate before setup is finished.
   *
   * There are two gates and they protect different things. The **server**
   * refuses import, promote and execute — the actions with external
   * consequences — and nothing here can turn that off. This menu is the other
   * one, and all it does is stop somebody wandering into screens whose data
   * will not make sense yet.
   *
   * Locking the menu absolutely turned out to be wrong: it also locks the
   * person who is still building the thing, or who just wants to look at what
   * they imported. So the lock stays the default and this is the deliberate,
   * visible way past it — never a hidden bypass, and it unlocks navigation
   * only.
   */
  browseAnyway = signal(false);

  /** Only Settings is built. The rest are shown disabled so the shape of the
   *  application is visible without pretending the screens exist. */
  nav = [
    { label: 'Dashboard', path: null, gated: false },
    { label: 'Account Lists', path: '/lists', gated: true },
    { label: 'Campaign Queues', path: '/queues', gated: true },
    { label: 'Outreach', path: '/campaigns', gated: true },
    { label: 'Sales Prep', path: '/prep', gated: true },
    { label: 'Learning', path: null, gated: false },
  ];

  /**
   * Ordered by what depends on what, so reading top to bottom is a working
   * sequence rather than an alphabet.
   *
   * 1. **API settings** — credentials. Nothing else can run without them, and
   *    the screen is deliberately **not** gated: it is where the missing
   *    credentials get entered, and locking the way out of an incomplete setup
   *    would be a trap. It absorbed Integrations, which used to be a second
   *    ungated entry — one screen listing credentials and another for typing
   *    them was a navigation step with nothing on the other side of it.
   * 2. **Model config** — which model each stage runs on. Its provider and
   *    model options both come from the screen above it.
   *
   * Then the content the prompts are built from, in the order they are
   * assembled into one:
   *
   * 3. **Org profile** — who we are and who we target. The first cached block
   *    of every prompt in the system.
   * 4. **Services & proof** — what we sell, and the only claims allowed to
   *    appear in a draft. The second block.
   * 5. **Writing samples** — the voice reference. The third.
   *
   * Then the pipeline itself, in the order it runs:
   *
   * 6. **Signal types** — the registry. It decides what can be extracted, and
   *    research derives its plan from it, so it comes first of the two.
   * 7. **Research** — the query families those signal types are produced by.
   * 8. **Scoring** — the weights applied at qualification.
   * 9. **Sales rules** — thread caps and persona weights, applied last, at
   *    strategy time.
   */
  settingsNav = [
    { label: 'API settings', path: '/settings/setup', gated: false },
    { label: 'Model config', path: '/settings/models', gated: true },
    // Beside Model config on purpose: one says how hard a stage thinks, the
    // other says what it is asked to do, and people look for them together.
    { label: 'Prompts', path: '/settings/prompts', gated: true },
    { label: 'ICP profiles', path: '/settings/icp-profiles', gated: true },
    { label: 'Services & proof', path: '/settings/services', gated: true },
    { label: 'Writing samples', path: '/settings/writing', gated: true },
    { label: 'Signal types', path: '/settings/signal-types', gated: true },
    { label: 'Research', path: '/settings/research', gated: true },
    { label: 'Scoring', path: '/settings/scoring', gated: true },
    { label: 'Sales rules', path: '/settings/rules', gated: true },
  ];

  ngOnInit(): void {
    // A page names where things happen ("List · test"); leaving it clears that.
    this.router.events
      .pipe(filter((e) => e instanceof NavigationStart))
      .subscribe(() => this.activity.where.set(null));
    this.browseAnyway.set(this.readStoredChoice());
    this.refresh();
    // Re-read on navigation rather than polling: the only thing that changes
    // readiness is a credential being saved or tested, and both end in a
    // route the user came back from.
    this.router.events
      .pipe(filter((e) => e instanceof NavigationEnd))
      .subscribe(() => this.refresh());
  }

  /**
   * Useful work is impossible, regardless of the browse choice.
   *
   * Reads `workable`, not `ready`: a missing La Growth Machine credential
   * stops sending and nothing else, so it must not seal a menu whose every
   * other screen would work — including the queue and campaign screens, which
   * build and approve without touching LGM. Only `execute` needs it, and the
   * server refuses that on its own.
   */
  get setupIncomplete(): boolean {
    const state = this.readiness();
    return state !== null && !state.workable;
  }

  /**
   * A demo installation is unlocked on purpose, not incompletely configured.
   *
   * Shown as its own banner rather than left silent: an unlocked menu looks
   * identical in both modes, and somebody has to be able to tell whether what
   * they are looking at is real.
   */
  get demoMode(): boolean {
    return this.readiness()?.mode === 'demo';
  }

  /** Whether the menu is actually restricted right now. */
  get locked(): boolean {
    return this.setupIncomplete && !this.browseAnyway();
  }

  blockedCount(): number {
    return this.readiness()?.blockers.length ?? 0;
  }

  /**
   * Outreach is missing but everything else works — worth saying plainly.
   *
   * Everything up to approval runs without it; only enrolling is refused. The
   * screens that would hit that refusal say so where the button is, rather
   * than being shut from here.
   */
  get outreachPending(): boolean {
    const state = this.readiness();
    return state !== null && state.workable && !state.ready;
  }

  disabled(item: { gated: boolean }): boolean {
    // Only the setup lock closes a screen now. A missing sending credential
    // used to shut the queue and campaign screens too, which cost every step
    // before the send — building a queue, promoting, drafting, approving —
    // to prevent a refusal `execute` gives anyway.
    return item.gated && this.locked;
  }

  /** Why one particular item is unavailable, for its tooltip. */
  itemReason(item: { gated: boolean }): string | null {
    return item.gated && this.locked ? this.lockReason() : null;
  }

  lockReason(): string {
    const blockers = this.readiness()?.blockers ?? [];
    return blockers.length
      ? `Finish setup first — ${blockers.join(' ')}`
      : 'Finish setup first.';
  }

  toggleBrowse(): void {
    const next = !this.browseAnyway();
    this.browseAnyway.set(next);
    try {
      if (next) localStorage.setItem(BROWSE_KEY, '1');
      else localStorage.removeItem(BROWSE_KEY);
    } catch {
      // Private browsing, or storage disabled. The choice still applies for
      // this session — losing it on reload is a far smaller problem than
      // throwing on a menu click.
    }
  }

  private readStoredChoice(): boolean {
    try {
      return localStorage.getItem(BROWSE_KEY) === '1';
    } catch {
      return false;
    }
  }

  private refresh(): void {
    this.api.readiness().subscribe({
      next: (r) => this.readiness.set(r),
      // A failed readiness call must not lock the application. The server is
      // the real gate; this is only the menu.
      error: () => this.readiness.set(null),
    });
  }
}
