import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { ActivatedRouteSnapshot, NavigationEnd, NavigationStart, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';

import { AuthService, MODULE_LABELS, ROLE_LABELS } from './core/auth.service';
import { ConfigService, Readiness } from './core/config.service';

/** Where the browse-anyway choice is remembered. */
const BROWSE_KEY = 'sdg360.browseBeforeSetup';

import { ConfirmHostComponent } from './shared/confirm-host.component';
import { ToastHostComponent } from './shared/toast-host.component';
import { ActivityBarComponent } from './shared/activity-bar.component';
import { ActivityService } from './shared/activity.service';
import { ResearchModeService } from './shared/research-mode.service';
import { UserMenuComponent } from './shared/user-menu.component';

/** A menu entry. `module` is its role-grid module; `admin` means admin only. */
interface NavItem {
  label: string;
  path: string | null;
  gated: boolean;
  module?: string;
  admin?: boolean;
  children?: NavItem[];
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, UserMenuComponent, RouterOutlet, RouterLink, RouterLinkActive, ConfirmHostComponent, ToastHostComponent, ActivityBarComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent implements OnInit {
  private api = inject(ConfigService);
  private router = inject(Router);
  private activity = inject(ActivityService);
  private mode = inject(ResearchModeService);
  readonly auth = inject(AuthService);

  /** The sign-in page draws without the sidebar. */
  bare = signal(false);

  /**
   * The module the open screen belongs to, when this role can only read it.
   * Said once above the screen, so a refusal on Save is never the first a
   * person hears of it. The server refuses the write either way.
   */
  viewOnlyHere = signal<string | null>(null);
  readonly roleLabels = ROLE_LABELS;

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
  nav: NavItem[] = [
    // No screen of its own yet, and already grouping one. The parent stays
    // inert and the child carries the link.
    {
      label: 'Dashboard',
      path: null,
      gated: false,
      children: [
        // Ungated: this is where somebody looks when the pipeline is refusing
        // to run, which is exactly when setup is unfinished.
        { label: 'Cost & health', path: '/dashboard/cost-health', gated: false, module: 'dashboard' },
      ],
    },
    { label: 'Account Lists', path: '/lists', gated: true, module: 'lists' },
    { label: 'Campaign Queues', path: '/queues', gated: true, module: 'queues' },
    { label: 'Outreach', path: '/campaigns', gated: true, module: 'outreach' },
    { label: 'Sales Prep', path: '/prep', gated: true, module: 'prep' },
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
  /**
   * `path: null` means the screen is not built yet, and the nav renders it
   * inert. Typed explicitly because every entry happens to have a route
   * today — without this the inferred type forbids the null the template
   * branch exists to handle, and the next person to add a menu item ahead of
   * its screen would find the type fighting them.
   */
  settingsNav: NavItem[] = [
    { label: 'API config', path: '/settings/setup', gated: false, admin: true },
    { label: 'Model config', path: '/settings/models', gated: true, module: 'models_prompts' },
    // Beside Model config on purpose: one says how hard a stage thinks, the
    // other says what it is asked to do, and people look for them together.
    { label: 'Prompts config', path: '/settings/prompts', gated: true, module: 'models_prompts' },
    { label: 'Services & proof', path: '/settings/services', gated: true, module: 'content' },
    // An ICP is written in terms of the services it buys, so it sits under
    // them rather than beside Scoring, which only consumes it.
    { label: 'ICP profiles', path: '/settings/icp-profiles', gated: true, module: 'content' },
    // Sources and the types that claim them, on one screen: a type names
    // the sources its fact lives in, so they are edited together.
    { label: 'Sources & signals', path: '/settings/signal-types', gated: true, module: 'sources_signals' },
    { label: 'Writing samples', path: '/settings/writing', gated: true, module: 'content' },
    // Absorbed the reuse window and the two multiplier tables: one screen
    // for what a thing is worth.
    { label: 'Weights & scoring', path: '/settings/scoring', gated: true, module: 'scoring' },
    { label: 'Sales rules', path: '/settings/rules', gated: true, module: 'rules_cadences' },
    // Who can sign in, and what each role may do. Ungated: managing people
    // has nothing to do with whether the connections are set up.
    { label: 'Users', path: '/settings/users', gated: false, admin: true },
    { label: 'Roles', path: '/settings/roles', gated: false, admin: true },
    // Monitoring moved out: what a run costs is read beside the pipeline it
    // belongs to, not beside the knobs that configure it.
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
      .pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd))
      .subscribe((e) => {
        this.bare.set(e.urlAfterRedirects.startsWith('/login'));
        this.viewOnlyHere.set(this.readOnlyModule());
        this.refresh();
      });
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

  // --- who is signed in ----------------------------------------------------

  /**
   * Whether a menu item shows. Before anyone is known (`me` undefined —
   * only ever true in a spec, because the guard loads it before any screen)
   * everything shows: hiding on not-knowing would flash an empty menu.
   */
  visible(item: NavItem): boolean {
    if (this.auth.me() === undefined) return true;
    if (item.admin) return this.auth.isAdmin();
    if (item.children?.length && !item.path) return item.children.some((c) => this.visible(c));
    return !item.module || this.auth.canSee(item.module);
  }

  /** Opens read-only for this role — said in the menu so nobody is surprised. */
  viewOnly(item: NavItem): boolean {
    return !!item.module && this.auth.me() != null && this.auth.level(item.module) === 'view';
  }

  private readOnlyModule(): string | null {
    let snap: ActivatedRouteSnapshot | null = this.router.routerState.snapshot.root;
    let module: string | undefined;
    while (snap) {
      module = (snap.data['module'] as string | undefined) ?? module;
      snap = snap.firstChild;
    }
    return module && this.auth.level(module) === 'view' ? MODULE_LABELS[module] ?? module : null;
  }

  private refresh(): void {
    // Nobody to ask on behalf of: the sign-in page, or a session that ended.
    // These would only come back 401.
    if (this.bare() || this.auth.me() === null) return;
    // The installation's research depth, loaded where every other app-wide
    // fact is. The service that holds it does not fetch: root-provided and
    // self-loading is how a shared service ends up in every parent's tests.
    this.api.researchSettings().subscribe({
      next: (s) => this.mode.setAppDefault(s.default_tier),
      // The built-in default stands. Screens still work and still say what
      // they will buy; only the inherited label would be wrong, and a toast
      // about it would be noise on every page.
      error: () => undefined,
    });
    this.api.readiness().subscribe({
      next: (r) => this.readiness.set(r),
      // A failed readiness call must not lock the application. The server is
      // the real gate; this is only the menu.
      error: () => this.readiness.set(null),
    });
  }
}
