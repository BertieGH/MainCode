import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { AppComponent } from './app.component';
import { Readiness } from './core/config.service';

/** Readiness with every mandatory slot satisfied. */
const READY: Readiness = {
  ready: true,
  workable: true,
  mode: 'production',
  demo_runs: 0,
  slots: [],
  blockers: [],
  warnings: [],
  enrichment_order: ['contactout', 'apollo'],
};

/** A demo installation: ready, but by stubs rather than real connections. */
const DEMO: Readiness = {
  ready: true,
  workable: true,
  mode: 'demo',
  demo_runs: 3,
  slots: [],
  blockers: [],
  warnings: [],
  enrichment_order: ['demo_enrichment'],
};

const NOT_READY: Readiness = {
  ready: false,
  workable: false,
  mode: 'production',
  demo_runs: 0,
  slots: [],
  blockers: ['No contact enrichment provider is configured.'],
  warnings: [],
  enrichment_order: [],
};

/**
 * Everything connected except outreach.
 *
 * The common real state, and the one the old single flag got wrong: a missing
 * La Growth Machine credential locked the whole application, including
 * importing a CSV, which LGM has nothing to do with.
 */
const OUTREACH_PENDING: Readiness = {
  ready: false,
  workable: true,
  mode: 'production',
  demo_runs: 0,
  slots: [],
  blockers: ['No outreach provider is configured.'],
  warnings: [],
  enrichment_order: ['apollo'],
};

describe('AppComponent', () => {
  let fixture: ComponentFixture<AppComponent>;
  let cmp: AppComponent;
  let http: HttpTestingController;

  /** Answer the calls the shell makes on init. */
  const settle = (state: Readiness) => {
    http.match('/api/config/readiness').forEach((r) => r.flush(state));
    // The installation's research depth. Loaded here rather than by the
    // service that holds it: root-provided and self-loading put this request
    // into every component spec that rendered anything using it.
    http.match('/api/config/research-settings').forEach((r) =>
      r.flush({ id: null, version: 0, freshness_days: 30, default_tier: 'standard' }),
    );
    fixture.detectChanges();
  };

  beforeEach(async () => {
    // The browse-anyway choice persists across reloads, so it also persists
    // across specs unless cleared — one test opting in would silently unlock
    // every test after it.
    localStorage.removeItem('sdg360.browseBeforeSetup');

    await TestBed.configureTestingModule({
      imports: [AppComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(AppComponent);
    cmp = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  afterEach(() => {
    http.match('/api/config/readiness').forEach((r) => r.flush(READY));
    http.match('/api/config/research-settings').forEach((r) =>
      r.flush({ id: null, version: 0, freshness_days: 30, default_tier: 'standard' }),
    );
    http.verify();
  });

  it('renders', () => {
    settle(READY);
    expect(cmp).toBeTruthy();
  });

  it('shows the whole application shape, not only what is built', () => {
    settle(READY);
    // Unbuilt sections stay visible-but-disabled rather than hidden. Hiding
    // them makes the app look finished and hides where it is going.
    const labels = cmp.nav.map((n) => n.label);
    expect(labels).toContain('Dashboard');
    expect(labels).toContain('Campaign Queues');
    expect(labels).toContain('Sales Prep');
  });

  it('links only the sections that exist', () => {
    settle(READY);
    const linked = cmp.nav.filter((n) => n.path).map((n) => n.label);
    expect(linked).toEqual(['Account Lists', 'Campaign Queues', 'Outreach', 'Sales Prep']);
  });

  it('leaves Dashboard and Learning inert', () => {
    settle(READY);
    // Their backing tables do not exist yet, and a link to an empty screen
    // reads as broken rather than as unbuilt.
    //
    // Sales Prep left this list when /prep shipped. Its queue is still empty —
    // that waits on outreach events — but the search path works and the screen
    // says why the queue cannot fill, which is the opposite of looking broken.
    const unlinked = cmp.nav.filter((n) => !n.path).map((n) => n.label);
    expect(unlinked).toEqual(['Dashboard', 'Learning']);
  });

  it('renders unbuilt sections as inert spans, not dead links', () => {
    settle(READY);
    const disabled = fixture.nativeElement.querySelectorAll('.nav-item.disabled');
    // Dashboard and Learning in the main nav; every settings entry has a
    // screen, so that nav contributes none. Dashboard's child is a link and
    // is not counted here.
    const unbuilt =
      cmp.nav.filter((n) => !n.path).length +
      cmp.settingsNav.filter((n) => !n.path).length;
    expect(disabled.length).toBe(unbuilt);
    // A disabled entry must not be an anchor — an <a> with no href still looks
    // clickable and reports as a link to assistive technology.
    disabled.forEach((el: Element) => expect(el.tagName).toBe('SPAN'));
  });

  it('orders the settings by what depends on what', () => {
    settle(READY);
    // Reading top to bottom is a working sequence: credentials, then the
    // models they unlock, then what those models are asked to do, then the
    // content every prompt is assembled from, then the pipeline in the order
    // it runs.
    //
    // "Prompts" sits next to "Model config" because they are two halves of one
    // question — how hard a stage thinks, and what it is asked to do — and
    // people come looking for them together. It is above the content screens
    // because it is the instruction, not something assembled into it.
    //
    // "Org profile" is gone: it held who is selling *and* who we sell to, and
    // the second half moved to ICP profiles — which absorbed the remaining two
    // identity fields rather than leaving a near-empty screen behind.
    expect(cmp.settingsNav.map((n) => n.label)).toEqual([
      'API config',
      'Model config',
      'Prompts config',
      'Services & proof',
      'ICP profiles',
      'Sources & signals',
      'Writing samples',
      'Weights & scoring',
      'Sales rules',
    ]);
  });

  it('puts signal types before the sources they are read out of', () => {
    settle(READY);
    // A plan is derived from the active signal types, so configuring them the
    // other way round means picking sources for signals that do not exist yet.
    // "Research" was renamed "Sources & weights": it named the activity rather
    // than the thing the screen configures.
    const labels = cmp.settingsNav.map((n) => n.label);
    expect(labels.indexOf('Sources & signals')).toBeLessThan(
      labels.indexOf('Weights & scoring'),
    );
  });

  it('keeps an ICP under the services it is written in terms of', () => {
    settle(READY);
    const labels = cmp.settingsNav.map((n) => n.label);
    expect(labels.indexOf('Services & proof')).toBeLessThan(
      labels.indexOf('ICP profiles'),
    );
  });

  it('reads what a run cost beside the pipeline, not beside its knobs', () => {
    settle(READY);
    // It was last in Settings, which put "what did that cost" next to the
    // switches that configure a run rather than next to the run. A cost is
    // an outcome, so it belongs under Dashboard — and Dashboard has no page
    // of its own, so the child is the only thing in that group you can open.
    expect(cmp.settingsNav.map((n) => n.label)).not.toContain('Monitoring');

    const dashboard = cmp.nav.find((n) => n.label === 'Dashboard');
    expect(dashboard?.children?.map((c) => c.label)).toEqual(['Cost & health']);
    expect(dashboard?.children?.[0].path).toBe('/dashboard/cost-health');
  });

  it('renders a child entry as a link under its parent', () => {
    settle(READY);
    // The parent is an inert span; a child that did not render would leave
    // the group unreachable with nothing on screen saying so.
    const child = [...fixture.nativeElement.querySelectorAll('.nav-item.child')];
    expect(child.map((el: Element) => el.textContent?.trim())).toEqual(['Cost & health']);
    expect(child[0].tagName).toBe('A');
  });

  it('never shuts the cost screen, whatever setup is missing', () => {
    settle(NOT_READY);
    // Same reason API config stays open: this is where somebody looks when
    // the pipeline is refusing to run, which is exactly when setup is
    // unfinished. Its parent is inert for want of a page, not for want of
    // credentials, so the gate must not reach the child through it.
    const child = cmp.nav.find((n) => n.label === 'Dashboard')?.children?.[0];
    expect(child && cmp.disabled(child)).toBe(false);
  });

  it('every settings entry has a route today', () => {
    settle(READY);
    // Monitoring was the last one without; it was built, then moved under
    // Dashboard. The rule below is what keeps this honest if another entry is
    // added before its screen exists.
    expect(cmp.settingsNav.filter((n) => !n.path)).toEqual([]);
  });

  it('renders a settings entry with no route inert rather than as a dead link', () => {
    settle(READY);
    // Asserted by injecting one, because none exists at the moment and the
    // branch would otherwise go untested until the next time somebody adds a
    // menu item ahead of its screen — which is exactly when it matters. A
    // null path used to render as a live link to nowhere: a broken screen
    // rather than an unbuilt one.
    cmp.settingsNav = [...cmp.settingsNav, { label: 'Not yet', path: null, gated: false }];
    fixture.detectChanges();

    const inert = [...fixture.nativeElement.querySelectorAll('.nav-item.disabled')].filter(
      (el: Element) => el.textContent?.trim() === 'Not yet',
    );
    expect(inert.length).toBe(1);
    expect(inert[0].tagName).toBe('SPAN');
  });

  describe('the setup gate', () => {
    it('locks the pipeline until the mandatory connections are verified', () => {
      settle(NOT_READY);
      expect(cmp.locked).toBe(true);
      expect(cmp.disabled({ gated: true })).toBe(true);
    });

    it('never locks API settings', () => {
      settle(NOT_READY);
      // Locking the way out of an incomplete setup would be a trap: this is
      // where the missing credentials get entered.
      const open = cmp.settingsNav.filter((n) => !cmp.disabled(n)).map((n) => n.label);
      expect(open).toEqual(['API config']);
    });

    it('unlocks everything once ready', () => {
      settle(READY);
      expect(cmp.locked).toBe(false);
      expect(cmp.settingsNav.every((n) => !cmp.disabled(n))).toBe(true);
    });

    it('does not lock the application when readiness cannot be read', () => {
      // The server refuses the dangerous actions regardless, so an unreachable
      // readiness endpoint must not leave somebody unable to use their own
      // installation. Worst case is an enabled link that lands on a 409.
      http.match('/api/config/readiness').forEach((r) => r.error(new ProgressEvent('fail')));
      fixture.detectChanges();
      expect(cmp.locked).toBe(false);
    });

    it('names how many connections are outstanding rather than only that some are', () => {
      settle(NOT_READY);
      const banner: HTMLElement = fixture.nativeElement.querySelector('.lock');
      expect(banner).toBeTruthy();
      expect(banner.textContent).toContain('1 connection to finish');
      // A bare "setup incomplete" sends someone hunting; the reason does not.
      expect(cmp.lockReason()).toContain('enrichment provider is configured');
    });

    it('shows no banner when setup is complete', () => {
      settle(READY);
      expect(fixture.nativeElement.querySelector('.lock')).toBeNull();
    });
  });

  describe('an installation with no outreach credential', () => {
    it('is not locked — LGM only matters at send time', () => {
      // The regression this guards: importing a list, enriching contacts and
      // researching an account do not touch La Growth Machine, so a missing
      // sending credential must not seal them.
      settle(OUTREACH_PENDING);
      expect(cmp.locked).toBe(false);
      expect(cmp.setupIncomplete).toBe(false);
    });

    it('shuts nothing — every screen before the send works without it', () => {
      // This used to shut Campaign Queues and Outreach. Building a queue,
      // promoting it, drafting and approving touch nothing at LGM; only
      // enrolling does, and the server refuses that on its own. Shutting the
      // screens cost every step before the send to prevent one refusal.
      settle(OUTREACH_PENDING);
      const shut = cmp.nav.filter((n) => cmp.disabled(n)).map((n) => n.label);
      expect(shut).toEqual([]);
    });

    it('leaves every settings screen open', () => {
      settle(OUTREACH_PENDING);
      expect(cmp.settingsNav.every((n) => !cmp.disabled(n))).toBe(true);
    });

    it('claims nothing about any screen, because none is blocked', () => {
      settle(OUTREACH_PENDING);
      for (const item of cmp.nav) {
        expect(cmp.itemReason(item))
          .withContext(`${item.label} was given a reason it does not have`)
          .toBeNull();
      }
    });

    it('surfaces the outstanding step rather than looking finished', () => {
      // The screens are open, so the only place the gap shows is where the
      // send is attempted. Saying it here as well keeps "nothing has been
      // sent" from reading as a fault in the campaign.
      settle(OUTREACH_PENDING);
      expect(cmp.outreachPending).toBe(true);
    });

    it('does not claim outreach is pending once it is connected', () => {
      settle(READY);
      expect(cmp.outreachPending).toBe(false);
    });
  });

  describe('a demo installation', () => {
    it('is unlocked without the setup-incomplete banner', () => {
      // Ready is ready. A demo installation is not a half-configured one, and
      // showing a "finish setup" warning would be untrue.
      settle(DEMO);
      expect(cmp.locked).toBe(false);
      expect(cmp.setupIncomplete).toBe(false);
      expect(fixture.nativeElement.querySelector('.lock')).toBeNull();
    });

    it('says so, because an unlocked menu looks the same in both modes', () => {
      settle(DEMO);
      const badge: HTMLElement = fixture.nativeElement.querySelector('.demo-badge');
      expect(badge).toBeTruthy();
      expect(badge.textContent).toContain('nothing is called or sent');
    });

    it('shows no demo badge on a production installation', () => {
      settle(READY);
      expect(fixture.nativeElement.querySelector('.demo-badge')).toBeNull();
    });
  });

  describe('browsing before setup is finished', () => {
    /**
     * Locking the menu absolutely also locks the person still building the
     * thing. The escape hatch is deliberate and visible — and it must never
     * touch the server-side refusal on import, promote and execute.
     */
    it('unlocks the menu without pretending setup is done', () => {
      settle(NOT_READY);
      expect(cmp.locked).toBe(true);

      cmp.toggleBrowse();
      fixture.detectChanges();

      expect(cmp.locked).toBe(false);
      expect(cmp.settingsNav.every((n) => !cmp.disabled(n))).toBe(true);
      // Still incomplete. The distinction is the whole point: the menu is
      // open, the pipeline is not.
      expect(cmp.setupIncomplete).toBe(true);
    });

    it('keeps the banner up while browsing', () => {
      settle(NOT_READY);
      cmp.toggleBrowse();
      fixture.detectChanges();

      const banner: HTMLElement = fixture.nativeElement.querySelector('.lock');
      expect(banner).toBeTruthy();
      // A vanished banner would read as a working system.
      expect(banner.textContent).toContain('still refused by the server');
    });

    it('is reversible', () => {
      settle(NOT_READY);
      cmp.toggleBrowse();
      expect(cmp.locked).toBe(false);
      cmp.toggleBrowse();
      expect(cmp.locked).toBe(true);
    });

    it('survives a reload', () => {
      settle(NOT_READY);
      cmp.toggleBrowse();
      expect(localStorage.getItem('sdg360.browseBeforeSetup')).toBe('1');
    });

    it('does nothing once setup is actually complete', () => {
      // Not a mode. When the three connections are in place there is nothing
      // to unlock, and the toggle must not leave a stale banner behind.
      cmp.toggleBrowse();
      settle(READY);
      expect(cmp.setupIncomplete).toBe(false);
      expect(fixture.nativeElement.querySelector('.lock')).toBeNull();
    });
  });
});
