import {
  HttpTestingController, provideHttpClientTesting,
} from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { IcpEditorComponent } from './icp-editor.component';

/**
 * The ICP editor, and the one rule that matters more than the controls.
 *
 * `org_profile.icp` is deliberately free-form, and this block is the first
 * cached section of every prompt the system sends. A form over free-form data
 * destroys whatever it does not understand — and a key dropped on save changes
 * what every stage is told without appearing in any diff a person reads.
 *
 * So most of what is asserted here is **preservation**, not editing.
 */
describe('IcpEditorComponent', () => {
  let fixture: ComponentFixture<IcpEditorComponent>;
  let cmp: IcpEditorComponent;

  /** The last value the editor emitted. */
  let emitted: Record<string, unknown> | null;

  const load = (icp: Record<string, unknown>) => {
    cmp.value = icp;
    fixture.detectChanges();
  };

  /** A band by its label, so a test reads the way the buttons do. */
  const band = (label: string) => {
    const found = cmp.presets.find((p) => p.label === label);
    if (!found) throw new Error(`no band labelled ${label}`);
    return found;
  };

  /** Which band buttons are currently lit. */
  const lit = () => cmp.presets.filter((p) => cmp.isPreset(p)).map((p) => p.label);

  let http: HttpTestingController;

  /** The signal types the editor asks for on init. */
  const ACTIVE = [
    { key: 'funding', status: 'active' },
    { key: 'engineering_scaling', status: 'active' },
    { key: 'public_pain_statement', status: 'active' },
    { key: 'role_change', status: 'active' },
  ];

  /** Answer the signal-types request. Nothing is judged until this lands. */
  const serveTypes = (types: unknown[] = ACTIVE) => {
    http.expectOne((r) => r.url.endsWith('/signal-types')).flush(types);
    fixture.detectChanges();
  };

  const signalsFactor = () => cmp.factors.find((f) => f.key === 'signals_that_matter')!;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [IcpEditorComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(IcpEditorComponent);
    cmp = fixture.componentInstance;
    emitted = null;
    cmp.valueChange.subscribe((v) => (emitted = v));
    fixture.detectChanges();
  });

  afterEach(() => {
    // Every instance asks for signal types and research sources on init, and
    // most tests have no reason to answer either. Drain those two, then verify
    // nothing *else* is outstanding — which is the assertion worth keeping.
    http.match((r) => r.url.endsWith('/signal-types')).forEach((r) => r.flush([]));
    http.match((r) => r.url.includes('/research-sources')).forEach((r) => r.flush([]));
    http.verify();
  });

  describe('where to look', () => {
    /** The registry, as the editor receives it. */
    const SOURCES = [
      {
        id: 's1', key: 'news', label: 'News / press', description: 'd', kind: 'search',
        scopes: ['company'], support_only: false, reuse_days: null, builtin: true,
        status: 'active', claimed_by: 1, attempts: 0, evidence: 0, dead_weight: false,
      },
      {
        id: 's2', key: 'hiring', label: 'Hiring', description: 'd', kind: 'search',
        scopes: ['company'], support_only: false, reuse_days: null, builtin: true,
        status: 'active', claimed_by: 1, attempts: 0, evidence: 0, dead_weight: false,
      },
    ];

    const withSources = (
      icp: Record<string, unknown>,
      types: unknown[] = [
        { key: 'funding', status: 'active', scope: 'company', produced_by: ['news'] },
        { key: 'engineering_scaling', status: 'active', scope: 'company', produced_by: ['hiring'] },
      ],
    ) => {
      load(icp);
      http.expectOne((r) => r.url.endsWith('/signal-types')).flush(types);
      http.expectOne((r) => r.url.includes('/research-sources')).flush(SOURCES);
      fixture.detectChanges();
    };

    it('carries the chosen sources back out unchanged', () => {
      withSources({ sources: ['news'] });
      expect(cmp.pickedSources()).toEqual(['news']);
      cmp.toggleSource('hiring');
      expect((emitted as Record<string, unknown>)['sources']).toEqual(['news', 'hiring']);
    });

    it('is omitted rather than written as an empty list', () => {
      /* Absent means "nothing accepted yet", and research falls back to what
         the signals name. `[]` would mean "read nothing", which is not a
         thing a rep can express by leaving a control alone. */
      withSources({ sources: ['news'] });
      cmp.toggleSource('news');
      expect('sources' in (emitted as Record<string, unknown>)).toBe(false);
    });

    it('names a source the signals expect but the set leaves out', () => {
      /* Drift, shown rather than merged in silently: the accepted set is what
         a run is recorded against, so changing it is a person's decision. */
      withSources({ sources: ['news'], signals_that_matter: ['funding', 'engineering_scaling'] });
      expect(cmp.driftedSources()).toEqual(['hiring']);
      cmp.addDrifted();
      expect(cmp.pickedSources()).toEqual(['news', 'hiring']);
      expect(cmp.driftedSources()).toEqual([]);
    });

    it('reports no drift before anything has been accepted', () => {
      /* An ICP that has never been through this screen researches exactly as
         it did before; warning about every source would be noise. */
      withSources({ signals_that_matter: ['funding'] });
      expect(cmp.driftedSources()).toEqual([]);
    });

    it('counts the exception searches on top of the sources', () => {
      /* They are a different kind of spend: a source is read once whatever
         asked for it, while each of these is a call bought for one
         conclusion. Grouped ones share a call. */
      withSources(
        { sources: ['news'], signals_that_matter: ['funding', 'engineering_scaling'] },
        [
          {
            key: 'funding', status: 'active', scope: 'company', produced_by: ['news'],
            search_instruction: 'Named filings.', search_group: null,
          },
          {
            key: 'engineering_scaling', status: 'active', scope: 'company',
            produced_by: ['hiring'], search_instruction: null, search_group: null,
          },
        ],
      );
      expect(cmp.extraSearches()).toBe(1);
    });
  });

  describe('reading an existing profile', () => {
    it('splits known factors into their own controls', () => {
      load({
        industries: ['SaaS', 'Fintech'],
        regions: ['US', 'UK'],
        employees: '50-500',
      });
      expect(cmp.chips['industries']).toEqual(['SaaS', 'Fintech']);
      expect(cmp.chips['regions']).toEqual(['US', 'UK']);
      expect(cmp.rangeMin).toBe(50);
      expect(cmp.rangeMax).toBe(500);
    });

    it('reads an open-ended band', () => {
      load({ employees: '5000+' });
      expect(cmp.rangeMin).toBe(5000);
      expect(cmp.rangeMax).toBeNull();
    });
  });

  describe('signals that matter', () => {
    /**
     * The one closed set in an otherwise free-form editor, and it earns that.
     *
     * `extraction._reject_reason` drops any signal whose type is unknown or
     * inactive, so a hand-typed trigger cannot become a signal — it is research
     * paid for and discarded, visible only in a log. The picker exists to stop
     * an ICP naming something the system can never record.
     */

    it('offers the active signal types, not a hardcoded list', () => {
      load({});
      serveTypes();
      expect(cmp.unusedSuggestions(signalsFactor())).toEqual([
        'funding', 'engineering_scaling', 'public_pain_statement', 'role_change',
      ]);
    });

    it('leaves out types that cannot produce a signal', () => {
      load({});
      serveTypes([
        { key: 'funding', status: 'active' },
        { key: 'hiring_surge', status: 'paused' },
        { key: 'vendor_churn', status: 'deprecated' },
      ]);
      // Paused and deprecated are rejected by the guard exactly like unknown
      // ones, so offering them would repeat the trap this picker closes.
      expect(cmp.unusedSuggestions(signalsFactor())).toEqual(['funding']);
    });

    it('does not offer one already chosen', () => {
      load({ signals_that_matter: ['funding'] });
      serveTypes();
      expect(cmp.unusedSuggestions(signalsFactor())).not.toContain('funding');
    });

    it('marks a stored value that no active type backs', () => {
      load({ signals_that_matter: ['funding', 'hiring_surge', 'expansion'] });
      serveTypes();
      const f = signalsFactor();
      expect(cmp.isOrphan(f, 'funding')).toBe(false);
      expect(cmp.isOrphan(f, 'hiring_surge')).toBe(true);
      expect(cmp.orphanCount(f)).toBe(2);
    });

    it('keeps an orphan rather than dropping it on save', () => {
      load({ signals_that_matter: ['funding', 'hiring_surge'] });
      serveTypes();
      cmp.emit();
      // Removing it silently would change what every prompt is told without
      // appearing in any diff a person reads. It is shown struck through and
      // removed deliberately, or not at all.
      expect(emitted!['signals_that_matter']).toEqual(['funding', 'hiring_surge']);
    });

    it('accuses nothing before the types have arrived', () => {
      load({ signals_that_matter: ['funding', 'hiring_surge'] });
      // Request still in flight: with an empty list every value would look
      // like an orphan and a correct ICP would be reported as broken.
      expect(cmp.orphanCount(signalsFactor())).toBe(0);
      serveTypes();
      // Only hiring_surge: funding is a real active type.
      expect(cmp.orphanCount(signalsFactor())).toBe(1);
    });

    it('accuses nothing when the types could not be fetched', () => {
      load({ signals_that_matter: ['funding', 'hiring_surge'] });
      http.expectOne((r) => r.url.endsWith('/signal-types'))
        .error(new ProgressEvent('network error'));
      fixture.detectChanges();
      expect(cmp.orphanCount(signalsFactor())).toBe(0);
      expect(cmp.optionsPlaceholder(signalsFactor())).toBe('could not load signal types');
    });

    it('says why the picker is empty, differently in each case', () => {
      load({});
      expect(cmp.optionsPlaceholder(signalsFactor())).toBe('loading…');
      serveTypes();
      expect(cmp.optionsPlaceholder(signalsFactor())).toBe('choose a signal type…');
      for (const key of ['funding', 'engineering_scaling', 'public_pain_statement', 'role_change']) {
        cmp.addChipFor('signals_that_matter', key);
      }
      expect(cmp.optionsPlaceholder(signalsFactor()))
        .toBe('every signal type is already listed');
    });

    it('carries no hardcoded suggestions any more', () => {
      // The list that had drifted: six triggers no type backed, and two real
      // types missing.
      expect(signalsFactor().suggestions).toBeUndefined();
      expect(signalsFactor().optionsFrom).toBe('signal-types');
    });

    it('leaves the other chip factors free text', () => {
      const industries = cmp.factors.find((f) => f.key === 'industries')!;
      expect(industries.optionsFrom).toBeUndefined();
      expect(cmp.isOrphan(industries, 'anything at all')).toBe(false);
    });
  });

  describe('signals split by scope', () => {
    /**
     * Shown in two groups, company and contact, by the scope each type carries
     * on the Signal types screen — and still stored as one list, because the
     * scope belongs to the type and a second copy could only disagree with it.
     */
    const SCOPED = [
      { key: 'funding', status: 'active', scope: 'company' },
      { key: 'engineering_scaling', status: 'active', scope: 'company' },
      { key: 'role_change', status: 'active', scope: 'contact' },
      { key: 'public_pain_statement', status: 'active', scope: 'contact' },
    ];

    it('shows each chosen signal under the scope its type carries', () => {
      load({ signals_that_matter: ['funding', 'role_change', 'engineering_scaling'] });
      serveTypes(SCOPED);
      const f = signalsFactor();
      expect(cmp.chipsInScope(f, 'company')).toEqual(['funding', 'engineering_scaling']);
      expect(cmp.chipsInScope(f, 'contact')).toEqual(['role_change']);
    });

    it('offers each picker only its own scope', () => {
      load({ signals_that_matter: ['funding'] });
      serveTypes(SCOPED);
      const f = signalsFactor();
      expect(cmp.unusedInScope(f, 'company')).toEqual(['engineering_scaling']);
      expect(cmp.unusedInScope(f, 'contact')).toEqual(['role_change', 'public_pain_statement']);
    });

    it('still stores one list', () => {
      load({});
      serveTypes(SCOPED);
      cmp.addChipFor('signals_that_matter', 'role_change');
      cmp.addChipFor('signals_that_matter', 'funding');
      expect(emitted!['signals_that_matter']).toEqual(['role_change', 'funding']);
    });

    it('keeps a value no type backs out of both groups, and says so', () => {
      load({ signals_that_matter: ['funding', 'expansion'] });
      serveTypes(SCOPED);
      const f = signalsFactor();
      expect(cmp.chipsInScope(f, 'company')).toEqual(['funding']);
      expect(cmp.chipsInScope(f, 'contact')).toEqual([]);
      expect(cmp.orphans(f)).toEqual(['expansion']);
    });

    it('says when a scope has no types at all', () => {
      load({});
      serveTypes([{ key: 'funding', status: 'active', scope: 'company' }]);
      expect(cmp.scopePlaceholder(signalsFactor(), 'contact')).toBe('no contact signal types yet');
    });
  });

  describe('buyer personas', () => {
    /**
     * Who to reach lives here and nowhere else: a buying role plus the titles
     * that fill it. Enrichment and research refuse an ICP that names nobody.
     */

    it('reads the role-and-titles form into rows', () => {
      load({ personas: [{ buying_role: 'technical_buyer', titles: ['CTO', 'CIO'] }] });
      expect(cmp.personas).toEqual([{ buying_role: 'technical_buyer', titles: ['CTO', 'CIO'] }]);
      expect(cmp.passthroughKeys()).toEqual([]);
    });

    it('carries an older list of bare titles through untouched', () => {
      // Enrichment still reads it; coercing it into a role would put words in
      // somebody's mouth.
      load({ personas: ['CTO', 'IT head'] });
      expect(cmp.personas).toEqual([]);
      expect(cmp.passthroughKeys()).toEqual(['personas']);
      cmp.emit();
      expect(emitted!['personas']).toEqual(['CTO', 'IT head']);
    });

    it('adds a persona with a role nobody has used yet', () => {
      load({ personas: [{ buying_role: 'economic_buyer', titles: ['CEO'] }] });
      cmp.addPersona();
      expect(cmp.personas[1].buying_role).toBe('technical_buyer');
    });

    it('writes titles, refusing a duplicate regardless of case', () => {
      load({});
      cmp.addPersona();
      cmp.addPersonaTitleFor(0, 'CTO');
      cmp.addPersonaTitleFor(0, 'cto');
      expect(emitted!['personas']).toEqual([{ buying_role: 'economic_buyer', titles: ['CTO'] }]);
    });

    it('does not save a role with no titles', () => {
      load({});
      cmp.addPersona();
      expect('personas' in emitted!).toBe(false);
    });

    it('changes a role and removes a persona', () => {
      load({ personas: [{ buying_role: 'economic_buyer', titles: ['CEO'] }] });
      cmp.setPersonaRole(0, 'champion');
      expect(emitted!['personas']).toEqual([{ buying_role: 'champion', titles: ['CEO'] }]);
      cmp.removePersona(0);
      expect('personas' in emitted!).toBe(false);
    });
  });

  describe('choosing headcount bands', () => {
    /**
     * The ICP holds one min-max, so a selection is always a contiguous span:
     * "50-100 and 500-1000" cannot exclude the middle, whatever the buttons
     * look like. Every case below is about that span staying honest.
     */

    it('starts empty, with nothing lit', () => {
      load({});
      expect(lit()).toEqual([]);
    });

    it('lights the one band clicked', () => {
      load({});
      cmp.applyPreset(band('100-200'));
      expect(lit()).toEqual(['100-200']);
    });

    it('extends to reach a band beyond the selection', () => {
      load({});
      cmp.applyPreset(band('50-100'));
      cmp.applyPreset(band('200-500'));
      // Everything between comes with it — there is no way to store a hole.
      expect(lit()).toEqual(['50-100', '100-200', '200-500']);
      expect(cmp.rangeMin).toBe(50);
      expect(cmp.rangeMax).toBe(500);
    });

    it('extends downwards just as well', () => {
      load({});
      cmp.applyPreset(band('200-500'));
      cmp.applyPreset(band('1-50'));
      expect(lit()).toEqual(['1-50', '50-100', '100-200', '200-500']);
    });

    it('trims from the end that was clicked', () => {
      load({});
      cmp.applyPreset(band('50-100'));
      cmp.applyPreset(band('200-500'));
      cmp.applyPreset(band('200-500'));
      expect(lit()).toEqual(['50-100', '100-200']);
      cmp.applyPreset(band('50-100'));
      expect(lit()).toEqual(['100-200']);
    });

    it('clears back to any when the only lit band is clicked again', () => {
      load({});
      cmp.applyPreset(band('100-200'));
      cmp.applyPreset(band('100-200'));
      expect(lit()).toEqual([]);
      expect(cmp.rangeMin).toBeNull();
      expect(cmp.rangeMax).toBeNull();
      expect(emitted!['employees']).toBeUndefined();
    });

    it('collapses to a single band when one inside the span is clicked', () => {
      load({});
      cmp.applyPreset(band('1-50'));
      cmp.applyPreset(band('500-1000'));
      cmp.applyPreset(band('100-200'));
      // An interior click has to do something; doing nothing is a dead button.
      expect(lit()).toEqual(['100-200']);
    });

    it('keeps the open-ended band open rather than inventing a ceiling', () => {
      load({});
      cmp.applyPreset(band('>1000'));
      expect(cmp.rangeMin).toBe(1000);
      expect(cmp.rangeMax).toBeNull();
      // Stored as `1000+`, which is the form `parseBand` already reads — the
      // label is for the reader, not for the file.
      expect(emitted!['employees']).toBe('1000+');
    });

    it('a bounded range never lights the open-ended band', () => {
      load({});
      cmp.rangeMin = 500;
      cmp.rangeMax = 100000;
      expect(lit()).not.toContain('>1000');
    });

    it('an open range lights every band above its floor', () => {
      load({ employees: '200+' });
      expect(lit()).toEqual(['200-500', '500-1000', '>1000']);
    });

    it('lights nothing for a range that matches no band', () => {
      load({ employees: '60-90' });
      expect(lit()).toEqual([]);
      // The typed numbers still stand; the buttons simply have nothing to say.
      expect(cmp.rangeMin).toBe(60);
      expect(cmp.rangeMax).toBe(90);
    });

    it('offers the bands that were asked for, in order', () => {
      expect(cmp.presets.map((p) => p.label)).toEqual([
        '1-50', '50-100', '100-200', '200-500', '500-1000', '>1000',
      ]);
    });
  });

  describe('preserving what it cannot represent', () => {
    it('carries an unknown key through untouched', () => {
      load({ industries: ['SaaS'], funding_stage: ['Series B'] });
      cmp.addChipFor('industries', 'Logistics');
      expect(emitted!['funding_stage']).toEqual(['Series B']);
    });

    it('lists unknown keys rather than hiding them', () => {
      // Still going into every prompt, so it has to be visible.
      load({ funding_stage: ['Series B'] });
      expect(cmp.passthroughKeys()).toEqual(['funding_stage']);
    });

    it('does not coerce a known key whose value is the wrong shape', () => {
      // Rewriting this into chips would quietly change what a prompt says.
      load({ industries: { primary: 'SaaS' } });
      expect(cmp.passthroughKeys()).toEqual(['industries']);
      expect(cmp.chips['industries']).toBeUndefined();
    });

    it('keeps a nested structure intact across an edit', () => {
      const nested = { revenue: { min: 1000000, currency: 'USD' } };
      load({ ...nested, regions: ['US'] });
      cmp.addChipFor('regions', 'UK');
      expect(emitted!['revenue']).toEqual(nested.revenue);
      expect(emitted!['regions']).toEqual(['US', 'UK']);
    });
  });

  describe('editing', () => {
    it('adds and removes chips', () => {
      load({});
      cmp.addChipFor('regions', 'US');
      expect(emitted!['regions']).toEqual(['US']);
      cmp.removeChip('regions', 'US');
      // Removed entirely rather than left as an empty array — see below.
      expect(emitted!['regions']).toBeUndefined();
    });

    it('refuses a duplicate regardless of case', () => {
      // "SaaS" and "saas" reaching a prompt as two separate facts is the
      // spelling problem this editor exists to stop.
      load({ industries: ['SaaS'] });
      cmp.addChipFor('industries', 'saas');
      expect(emitted!['industries']).toEqual(['SaaS']);
    });

    it('omits an empty factor rather than writing a blank', () => {
      // An empty array and an absent key read differently to a model: one says
      // "no industries qualify", the other says "industry is not a constraint".
      load({ industries: ['SaaS'] });
      cmp.removeChip('industries', 'SaaS');
      expect('industries' in emitted!).toBe(false);
    });

    it('composes a headcount band from the two inputs', () => {
      load({});
      cmp.rangeMin = 50;
      cmp.rangeMax = 500;
      cmp.emit();
      expect(emitted!['employees']).toBe('50-500');
    });

    it('composes an open-ended band from a minimum alone', () => {
      load({});
      cmp.rangeMin = 5000;
      cmp.emit();
      expect(emitted!['employees']).toBe('5000+');
    });

    it('applies a band', () => {
      load({});
      cmp.applyPreset(band('50-100'));
      expect(emitted!['employees']).toBe('50-100');
    });

    it('spans several adjoining bands as one range', () => {
      load({});
      cmp.applyPreset(band('50-100'));
      cmp.applyPreset(band('200-500'));
      expect(emitted!['employees']).toBe('50-500');
    });

    it('does not offer a suggestion already chosen', () => {
      load({ regions: ['US'] });
      const regions = cmp.factors.find((f) => f.key === 'regions')!;
      expect(cmp.unusedSuggestions(regions)).not.toContain('US');
      expect(cmp.unusedSuggestions(regions)).toContain('UK');
    });
  });

  describe('the JSON escape hatch', () => {
    it('stays in step with the fields', () => {
      // Two editors over one value that disagree is worse than one bad editor,
      // because whichever saves last silently wins.
      load({ regions: ['US'] });
      cmp.raw = '{"regions":["IN","EU"],"custom":1}';
      cmp.onRawEdit();
      expect(cmp.chips['regions']).toEqual(['IN', 'EU']);
      expect(emitted!['custom']).toBe(1);
    });

    it('reports malformed JSON without discarding the fields', () => {
      load({ regions: ['US'] });
      cmp.raw = '{ oops';
      cmp.onRawEdit();
      expect(cmp.rawError()).toContain('Not valid JSON');
      expect(cmp.chips['regions']).toEqual(['US']);
    });

    it('refuses a top-level array', () => {
      load({});
      cmp.raw = '["US"]';
      cmp.onRawEdit();
      expect(cmp.rawError()).toContain('must be a JSON object');
    });
  });
});
