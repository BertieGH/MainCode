import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController, provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ResearchComponent } from './research.component';

/**
 * The Research screen renders, and keeps rendering.
 *
 * The reason this file exists: `industryRows()` builds fresh objects on every
 * change-detection pass. Without `trackBy` Angular tears down and rebuilds each
 * row's `ngModel` inputs on every pass, which schedules another pass, and the
 * page spins with no console error to show for it — `ng build` is perfectly
 * happy with it. Rendering the component twice here is what catches that,
 * because a compile check never will.
 */
describe('ResearchComponent', () => {
  let fixture: ComponentFixture<ResearchComponent>;
  let cmp: ResearchComponent;
  let http: HttpTestingController;

  const SOURCES = [
    {
      id: 's1', key: 'funding', label: 'Funding', description: 'd', kind: 'search',
      scopes: ['company'], support_only: false, reuse_days: null, builtin: true,
      status: 'active', claimed_by: 1, attempts: 4, evidence: 2, dead_weight: false,
    },
    {
      id: 's2', key: 'enrichment', label: 'Enrichment', description: 'd', kind: 'provider',
      scopes: ['contact'], support_only: false, reuse_days: null, builtin: true,
      status: 'active', claimed_by: 0, attempts: 0, evidence: 0, dead_weight: false,
    },
  ];
  const TYPES = [
    { key: 'funding', label: 'Funding', status: 'active', produced_by: ['funding'], scope: 'company' },
  ];
  const SCORING = {
    id: 'c1', version: 1, is_active: true,
    dimension_weights: { fit: 20, opportunity: 20, buyer: 15, commercial: 15, intent: 20, engagement: 10 },
    industry_multipliers: { saas: { intent: 1.3 } },
    size_multipliers: { large: { buyer: 1.2 } },
    persona_role_weights: {}, band_cutoffs: { high: 75, medium: 50 },
    man_view_enabled: false, created_at: '2026-01-01T00:00:00Z',
  };

  /**
   * Answer every request the screen makes on init.
   *
   * Industries come from the **union across ICP profiles** now, not from a
   * single org-level ICP — so the default here is two profiles, which is also
   * the case worth exercising: an industry named by either needs a multiplier
   * row, and one named by both needs exactly one.
   */
  const serve = (
    profiles: { definition: Record<string, unknown> | null }[] = [
      { definition: { industries: ['SaaS'] } },
      { definition: { industries: ['Fintech', 'SaaS'] } },
    ],
  ) => {
    http.expectOne((r) => r.url.includes('/research-sources')).flush(SOURCES);
    http.expectOne((r) => r.url.endsWith('/signal-types')).flush(TYPES);
    http.expectOne((r) => r.url.endsWith('/scoring')).flush(SCORING);
    http.expectOne((r) => r.url.endsWith('/icp-profiles')).flush(
      profiles.map((p, i) => ({
        id: `p${i}`,
        name: `Profile ${i}`,
        description: null,
        definition: p.definition,
        version: p.definition ? 1 : null,
        service_codes: ['qa_engineering'],
        list_count: 0,
      })),
    );
    fixture.detectChanges();
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ResearchComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ResearchComponent);
    cmp = fixture.componentInstance;
    fixture.detectChanges();
  });

  afterEach(() => {
    http.match(() => true).forEach((r) => !r.cancelled && r.flush([]));
    http.verify();
  });

  describe('it renders without spinning', () => {
    it('survives repeated change detection', () => {
      serve();
      // The actual regression guard. A row rebuilt on every pass schedules
      // another pass; three explicit passes is enough to trip it.
      fixture.detectChanges();
      fixture.detectChanges();
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('Industry multipliers');
    });

    it('tracks rows by a stable key, not by object identity', () => {
      serve();
      const first = cmp.industryRows();
      const second = cmp.industryRows();
      // Fresh objects each call — which is exactly why trackBy is required.
      expect(first[0]).not.toBe(second[0]);
      expect(cmp.trackRow(0, first[0])).toBe(cmp.trackRow(0, second[0]));
    });
  });

  describe('the source registry', () => {
    it('shows what each source has actually produced', () => {
      /* The number that stops the registry rotting. A registry only ever
         grows, and without "read this often, produced this much" on the same
         screen a source added in March is still costing a read per account in
         December and nobody knows. */
      serve();
      const text = fixture.nativeElement.textContent;
      expect(text).toContain('4 reads');
      expect(text).toContain('2 passages');
    });

    it('says why a source that is not a search has no coverage of its own', () => {
      serve();
      expect(cmp.kindWord('provider')).toContain('never auto-run');
      expect(cmp.kindWord('fetch')).toContain('no search');
      expect(cmp.kindWord('search')).toBe('');
    });

    it('will not add a source without a key, a name and a brief', () => {
      /* The brief *is* what the search runs. A source with none would be
         planned, read and recorded, having been told nothing to read for. */
      serve();
      cmp.draft = {
        key: 'Trade Press', label: '', description: '', scope: 'company',
        reuse_days: null, support_only: false,
      };
      expect(cmp.draftValid()).toBe(false);
      cmp.draft.key = 'trade_press';
      expect(cmp.draftValid()).toBe(false);
      cmp.draft.label = 'Trade press';
      cmp.draft.description = 'Sector publications and their newsletters.';
      expect(cmp.draftValid()).toBe(true);
    });

    it('retires a source rather than deleting it', () => {
      /* Its key is written into every coverage row that recorded reading it,
         and a report that cannot resolve one prints a bare key. */
      serve();
      cmp.setStatus({ ...cmp.sources()[0], key: 'funding' } as never, 'paused');
      const req = http.expectOne((r) => r.url.endsWith('/research-sources/funding'));
      expect(req.request.method).toBe('PATCH');
      expect(req.request.body).toEqual({ status: 'paused' });
      req.flush({});
      http.match(() => true).forEach((r) => !r.cancelled && r.flush([]));
    });
  });

  describe('industry rows come from the ICP', () => {
    it('renders one row per ICP industry', () => {
      serve();
      expect(cmp.industryRows().map((r) => r.label)).toEqual(['SaaS', 'Fintech']);
    });

    it('normalises the key so a spreadsheet spelling still matches', () => {
      serve([{ definition: { industries: ['  FinTech  '] } }]);
      expect(cmp.industryRows()[0].key).toBe('fintech');
    });

    it('has no way to add an industry here', () => {
      /* The list is the ICP's. A second entry point could calibrate a market
         nobody targets, and the two lists would drift. */
      serve();
      expect(fixture.nativeElement.textContent).not.toContain('Add Industry');
    });

    it('keeps a calibrated industry the ICP no longer names', () => {
      serve([{ definition: { industries: ['Fintech'] } }]);
      const rows = cmp.industryRows();
      const orphan = rows.find((r) => r.orphan);
      expect(orphan?.key).toBe('saas');
      expect(cmp.orphanCount()).toBe(1);
    });

    it('does not orphan an industry that was never calibrated', () => {
      /* An ICP industry with no multipliers is just a row of x1.00, not a
         leftover — only values somebody actually set can be stranded. */
      serve([{ definition: { industries: ['Fintech', 'Insurance'] } }]);
      expect(cmp.industryRows().filter((r) => r.orphan).map((r) => r.key)).toEqual(['saas']);
    });
  });

  describe('size rows are fixed', () => {
    it('offers exactly the three derived bands', () => {
      serve();
      expect(cmp.sizeBands.map((b) => b.key)).toEqual(['small', 'mid', 'large']);
    });

    it('never offers unknown', () => {
      /* `unknown` is the absence of a headcount, not a size. Multipliers on it
         would score an unmeasured account on a guess. */
      serve();
      expect(cmp.sizeBands.map((b) => b.key)).not.toContain('unknown');
    });

    it('reads a stored size multiplier', () => {
      serve();
      expect(cmp.multiplierFor('size', 'large', 'buyer')).toBe(1.2);
      expect(cmp.multiplierFor('size', 'small', 'buyer')).toBe(1);
    });
  });

  describe('editing a multiplier', () => {
    it('stores a value against the right table', () => {
      serve();
      cmp.setMultiplier('industry', 'fintech', 'buyer', 1.4);
      expect(cmp.multiplierFor('industry', 'fintech', 'buyer')).toBe(1.4);
      expect(cmp.multiplierFor('size', 'fintech', 'buyer')).toBe(1);
    });

    it('drops a value set back to x1.00 rather than storing a row of ones', () => {
      serve();
      cmp.setMultiplier('industry', 'saas', 'intent', 1);
      expect(cmp.multiplierFor('industry', 'saas', 'intent')).toBe(1);
      // And with nothing left on it, the row stops being an orphan candidate.
      serve;
      expect(cmp.orphanCount()).toBe(0);
    });
  });

  describe('trying a source before storing it', () => {
    /* The reason this exists: a source costs a read per account from the
       moment it is saved, and whether it earns that used to be visible only
       afterwards. `job_board` took 26 attempts across the book to establish
       that it finds nothing. */

    const fill = () => {
      // The Try panel lives inside the Add-source form, so the form has to be
      // open for any of it to be in the DOM at all.
      cmp.adding.set(true);
      cmp.draft.key = 'trade_press';
      cmp.draft.label = 'Trade press';
      cmp.draft.description = 'Sector publications and the wires.';
      cmp.draft.scope = 'both';
      cmp.trialAccountIds = ['a1', 'a2'];
    };

    it('sends the draft as it would be stored, and both scopes', () => {
      serve();
      fill();
      cmp.tryIt();
      const req = http.expectOne('/api/config/research-sources/try');
      expect(req.request.body.key).toBe('trade_press');
      expect(req.request.body.description).toBe('Sector publications and the wires.');
      expect(req.request.body.scopes).toEqual(['company', 'contact']);
      expect(req.request.body.account_ids).toEqual(['a1', 'a2']);
      // Only a search is creatable on this screen, so only a search is tried.
      expect(req.request.body.kind).toBe('search');
      req.flush({
        route: 'search', accounts: 2, found: 1, dry: 1, failed: 0,
        input_tokens: 500, output_tokens: 40, verdict: '1 passage across 2 accounts',
        trials: [],
      });
      expect(cmp.trying()).toBeFalse();
      expect(cmp.trial()?.found).toBe(1);
    });

    it('says do not store it when nothing came back', () => {
      serve();
      fill();
      cmp.tryIt();
      http.expectOne('/api/config/research-sources/try').flush({
        route: 'search', accounts: 3, found: 0, dry: 3, failed: 0,
        input_tokens: 600, output_tokens: 20,
        verdict: 'nothing at any of 3 accounts - do not store this without changing the wording',
        trials: [],
      });
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('Do not store this yet');
    });

    it('reports a failed trial rather than leaving the button spinning', () => {
      serve();
      fill();
      cmp.tryIt();
      http.expectOne('/api/config/research-sources/try')
        .flush({ detail: 'no SERP credential' }, { status: 422, statusText: 'Unprocessable' });
      expect(cmp.trying()).toBeFalse();
      expect(cmp.trialError()).toContain('SERP');
    });
  });
});
