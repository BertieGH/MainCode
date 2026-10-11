import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController, provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ResearchSource, SignalType } from '../core/config.service';
import { SourceRegistryComponent } from './source-registry.component';

/**
 * The Research screen renders, and keeps rendering.
 *
 * The reason this file exists: `industryRows()` builds fresh objects on every
 * change-detection pass. Without `trackBy` Angular tears down and rebuilds each
 * row's `ngModel` inputs on every pass, which schedules another pass, and the
 * page spins with no console error to show for it — `ng build` is perfectly
 * happy with it. Rendering the component twice here is what catches that,
 * because a compile check never will.
 */describe('SourceRegistryComponent', () => {  let fixture: ComponentFixture<SourceRegistryComponent>;
  let cmp: SourceRegistryComponent;
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
  /**
   * Hand the panel its data. It fetches none of it.
   *
   * It used to load sources, types, accounts and settings itself, which meant
   * the screen that embeds it made every request twice — and every spec of
   * that screen had to know about requests this component made. Inputs down,
   * events up.
   */
  const serve = () => {
    cmp.sources.set(SOURCES as ResearchSource[]);
    cmp.types.set(TYPES as SignalType[]);
    fixture.detectChanges();
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SourceRegistryComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(SourceRegistryComponent);
    cmp = fixture.componentInstance;
    fixture.detectChanges();
  });

  afterEach(() => {
    http.match(() => true).forEach((r) => !r.cancelled && r.flush([]));
    http.verify();
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
  });});
