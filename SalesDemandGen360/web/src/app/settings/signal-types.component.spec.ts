import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';

import { SignalTypesComponent } from './signal-types.component';
import { ResearchSource, SignalType } from '../core/config.service';

/**
 * The registry screen is where a type is created, tuned, silenced and retired.
 * Three things here are worth defending with tests:
 *
 *  - scope is decided by *which* Add button opened the form, not by a field the
 *    user could get wrong;
 *  - a no-op edit must send nothing, because an empty PATCH is a 400;
 *  - a deprecated row must not offer actions the server answers with 409.
 */

const BASE = '/api/config/signal-types';
const SOURCES = '/api/config/research-sources';

function source(over: Partial<ResearchSource> = {}): ResearchSource {
  return {
    id: crypto.randomUUID(),
    key: 'funding',
    label: 'Funding',
    description: '',
    kind: 'search',
    scopes: ['company'],
    support_only: false,
    reuse_days: null,
    builtin: true,
    status: 'active',
    status_reason: null,
    claimed_by: 0,
    attempts: 0,
    evidence: 0,
    dead_weight: false,
    ...over,
  };
}

/** A trimmed stand-in for the server registry, covering every rule that matters. */
const REGISTRY: ResearchSource[] = [
  source({ key: 'funding', label: 'Funding' }),
  source({ key: 'hiring', label: 'Hiring' }),
  source({ key: 'news', label: 'News / press', scopes: ['company', 'contact'] }),
  source({ key: 'reviews', label: 'Reviews & ratings', support_only: true }),
  source({ key: 'enrichment', label: 'Enrichment', scopes: ['contact'], kind: 'provider' }),
];

function type(over: Partial<SignalType> = {}): SignalType {
  return {
    id: crypto.randomUUID(),
    key: 'funding',
    label: 'Funding round raised',
    description: null,
    scope: 'company',
    default_ttl_days: 300,
    durability_days: null,
    durability_effective_days: 900,
    weight: 2,
    produced_by: ['funding'],
    search_instruction: null,
    search_group: null,
    kind: 'event',
    status: 'active',
    paused_at: null,
    deprecated_at: null,
    signal_count: 0,
    ...over,
  };
}

describe('SignalTypesComponent', () => {
  let fixture: ComponentFixture<SignalTypesComponent>;
  let cmp: SignalTypesComponent;
  let http: HttpTestingController;

  /** Answers both requests ngOnInit fires: the rows and the source registry. */
  function boot(rows: SignalType[], sources: ResearchSource[] = REGISTRY): void {
    fixture.detectChanges();
    http.expectOne((r) => r.url === BASE).flush(rows);
    http.expectOne((r) => r.url === SOURCES).flush(sources);
    fixture.detectChanges();
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SignalTypesComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(SignalTypesComponent);
    cmp = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  describe('loading', () => {
    it('asks for deprecated types too', () => {
      // They stay on screen, greyed. A qualification decided partly on a
      // retired type still has to be able to explain itself, so the row cannot
      // vanish the moment it is retired.
      fixture.detectChanges();
      http.expectOne((r) => r.url === SOURCES).flush(REGISTRY);
      const req = http.expectOne((r) => r.url === BASE);
      expect(req.request.params.get('include_deprecated')).toBe('true');
      expect(req.request.params.get('scope'))
        .withContext('both registries render on one screen, so scope must not be filtered')
        .toBeNull();
      req.flush([]);
    });

    it('surfaces the reason a load failed rather than an empty screen', () => {
      fixture.detectChanges();
      http.expectOne((r) => r.url === SOURCES).flush(REGISTRY);
      http
        .expectOne((r) => r.url === BASE)
        .flush({ detail: 'database is starting up' }, { status: 503, statusText: 'Unavailable' });
      fixture.detectChanges();

      expect(cmp.error()).toBe('database is starting up');
      expect(cmp.loading()).withContext('a failed load must stop loading').toBeFalse();
    });

    it('splits rows by scope', () => {
      boot([
        type({ key: 'funding', scope: 'company' }),
        type({ key: 'role_change', scope: 'contact' }),
        type({ key: 'hiring', scope: 'company' }),
      ]);

      expect(cmp.byScope('company').map((t) => t.key)).toEqual(['funding', 'hiring']);
      expect(cmp.byScope('contact').map((t) => t.key)).toEqual(['role_change']);
    });
  });

  describe('adding a type', () => {
    beforeEach(() => boot([]));

    it('sends the scope of the button that opened the form', () => {
      // The reason there are two Add buttons rather than one form with a scope
      // dropdown: a contact type filed as a company type is invisible until it
      // stops matching anything, and scope is immutable server-side.
      cmp.startAdd('contact');
      cmp.draft.key = 'role_change';
      cmp.draft.label = 'New in role';
      cmp.save();

      const req = http.expectOne((r) => r.method === 'POST' && r.url === BASE);
      expect(req.request.body.scope).toBe('contact');
      req.flush(type({ key: 'role_change', scope: 'contact' }));
      http.expectOne((r) => r.url === BASE).flush([]); // the reload after a create
    });

    it('keeps scope correct after switching to the other registry', () => {
      cmp.startAdd('company');
      cmp.startAdd('contact');
      cmp.draft.key = 'role_change';
      cmp.draft.label = 'New in role';
      cmp.save();

      const req = http.expectOne((r) => r.method === 'POST' && r.url === BASE);
      expect(req.request.body.scope)
        .withContext('the last button pressed decides, not the first')
        .toBe('contact');
      req.flush(type({ scope: 'contact' }));
      http.expectOne((r) => r.url === BASE).flush([]);
    });

    it('closes the form when the same Add button is pressed again', () => {
      cmp.startAdd('company');
      expect(cmp.adding()).toBe('company');
      cmp.startAdd('company');
      expect(cmp.adding()).toBeNull();
    });

    it('sends the families that were ticked', () => {
      cmp.startAdd('company');
      cmp.draft.key = 'budget_cycle';
      cmp.draft.label = 'Budget cycle';
      cmp.toggleFamily('news');
      cmp.toggleFamily('hiring');
      cmp.toggleFamily('news'); // untick
      cmp.save();

      const req = http.expectOne((r) => r.method === 'POST' && r.url === BASE);
      expect(req.request.body.produced_by).toEqual(['hiring']);
      req.flush(type());
      http.expectOne((r) => r.url === BASE).flush([]);
    });

    it('offers only the families that apply to each scope', () => {
      // A company type citing a contact-only family is a 422, and worse, would
      // have reported as a permanent coverage gap if it ever got through.
      expect(cmp.sourcesFor('company').map((f) => f.key)).toEqual([
        'funding', 'hiring', 'news', 'reviews',
      ]);
      expect(cmp.sourcesFor('contact').map((f) => f.key)).toEqual(['news', 'enrichment']);
    });

    it('blocks a type whose only family cannot create a signal', () => {
      // Reviews corroborates; it never fires on its own. Such a type would sit
      // in the registry looking configured and produce nothing, forever.
      cmp.draft.key = 'buyer_frustration';
      cmp.draft.label = 'Buyer frustration';
      cmp.toggleFamily('reviews');

      expect(cmp.canSave()).toBeFalse();
      expect(cmp.blocker()).toContain('never create one');

      cmp.toggleFamily('hiring');
      expect(cmp.canSave()).withContext('paired with a real producer it is fine').toBeTrue();
    });

    it('says why Add is disabled instead of just being dead', () => {
      expect(cmp.blocker()).toContain('key');

      cmp.draft.key = 'Budget Cycle';
      expect(cmp.blocker()).toContain('snake_case');

      cmp.draft.key = 'budget_cycle';
      expect(cmp.blocker()).toContain('label');

      cmp.draft.label = 'Budget cycle';
      expect(cmp.blocker()).withContext('nothing missing, so no reason to show').toBeNull();
    });

    it('warns rather than silently emptying the picker if the registry fails', () => {
      const f2 = TestBed.createComponent(SignalTypesComponent);
      f2.detectChanges();
      http.expectOne((r) => r.url === BASE).flush([]);
      http.expectOne((r) => r.url === SOURCES).flush({}, { status: 500, statusText: 'Error' });
      f2.detectChanges();

      expect(f2.componentInstance.error()).toBe('Could not load research sources.');
    });

    it('refuses a key the server would also refuse', () => {
      // canSave mirrors the server's snake_case rule. If it drifts, the user
      // gets a 422 from a button that looked enabled.
      cmp.draft.label = 'x';
      for (const bad of ['Funding Round', '2fa', 'funding-round', '', 'Funding']) {
        cmp.draft.key = bad;
        expect(cmp.canSave()).withContext(`"${bad}" should be rejected`).toBeFalse();
      }
      cmp.draft.key = 'budget_cycle';
      expect(cmp.canSave()).toBeTrue();
    });

    it('refuses a blank label', () => {
      cmp.draft.key = 'budget_cycle';
      cmp.draft.label = '   ';
      expect(cmp.canSave()).toBeFalse();
    });

    it('shows the server reason when a create is rejected', () => {
      cmp.startAdd('company');
      cmp.draft.key = 'funding';
      cmp.draft.label = 'Funding';
      cmp.save();

      http
        .expectOne((r) => r.method === 'POST' && r.url === BASE)
        .flush({ detail: 'signal type "funding" already exists' }, { status: 409, statusText: 'Conflict' });

      expect(cmp.error()).toBe('signal type "funding" already exists');
      expect(cmp.saving()).withContext('a failed save must release the button').toBeFalse();
      expect(cmp.adding())
        .withContext('the form stays open so the typing is not lost')
        .toBe('company');
    });

    it('clears the draft after a successful create', () => {
      cmp.startAdd('company');
      cmp.draft.key = 'budget_cycle';
      cmp.draft.label = 'Budget cycle';
      cmp.toggleFamily('news');
      cmp.save();

      http.expectOne((r) => r.method === 'POST' && r.url === BASE).flush(type());
      http.expectOne((r) => r.url === BASE).flush([type()]);

      expect(cmp.draft.key).toBe('');
      expect(cmp.draft.weight).withContext('weight returns to the ×1.00 baseline').toBe(1.0);
      expect(cmp.draft.produced_by).withContext('ticks clear too').toEqual([]);
      expect(cmp.adding()).toBeNull();
    });
  });

  describe('editing weight and TTL', () => {
    const row = type({ key: 'funding', weight: 2, default_ttl_days: 300 });

    beforeEach(() => boot([row, type({ key: 'hiring', weight: 1.35, default_ttl_days: 60 })]));

    it('seeds the editor from the row being edited', () => {
      // `edit` is one object reused across rows. Without a reseed, opening the
      // second row would show the first row's numbers and save them over it.
      cmp.startEdit(cmp.types()[0]);
      cmp.cancelEdit();
      cmp.startEdit(cmp.types()[1]);

      expect(cmp.edit).toEqual({
        label: 'Funding round raised',
        description: '',
        produced_by: ['funding'],
        weight: 1.35,
        default_ttl_days: 60,
        // Null, not the derived 180: the box shows its placeholder rather than
        // pinning the default as though someone had chosen it.
        durability_days: null,
        // Reseeded too: an instruction is what the search asks for, and
        // carrying the previous row's over would rewrite the wrong type's.
        search_instruction: '',
        search_group: '',
        kind: 'event',
      });
    });

    it('sends only the field that changed', () => {
      cmp.startEdit(row);
      cmp.edit.weight = 1.75;
      cmp.saveEdit(row);

      const req = http.expectOne(`${BASE}/funding`);
      expect(req.request.method).toBe('PATCH');
      expect(req.request.body).toEqual({ weight: 1.75 });
      req.flush(type({ key: 'funding', weight: 1.75 }));
    });

    it('sends nothing at all when neither value moved', () => {
      // An empty PATCH is a 400 server-side, so a no-op Save must not become a
      // visible error for the user.
      cmp.startEdit(row);
      cmp.saveEdit(row);

      expect(http.match(() => true).length)
        .withContext('a no-op edit must issue no request')
        .toBe(0);
      expect(cmp.editing()).withContext('and must still close the editor').toBeNull();
      expect(cmp.error()).toBeNull();
    });

    it('replaces the row from the response instead of refetching the list', () => {
      cmp.startEdit(row);
      cmp.edit.weight = 1.75;
      cmp.edit.default_ttl_days = 365;
      cmp.saveEdit(row);

      http.expectOne(`${BASE}/funding`).flush(type({ key: 'funding', weight: 1.75, default_ttl_days: 365 }));

      const updated = cmp.types().find((t) => t.key === 'funding')!;
      expect(updated.weight).toBe(1.75);
      expect(updated.default_ttl_days).toBe(365);
      expect(cmp.editing()).toBeNull();
      expect(cmp.types().length).withContext('the other row is untouched').toBe(2);
      expect(http.match(() => true).length)
        .withContext('the response is the new state; a reload would be a second round trip')
        .toBe(0);
    });

    it('sends a changed label, description and source list', () => {
      cmp.startEdit(row);
      cmp.edit.label = 'Funding round closed';
      cmp.edit.description = 'A disclosed raise, with the round named.';
      cmp.toggleEditFamily('hiring');
      cmp.saveEdit(row);

      const body = http.expectOne(`${BASE}/funding`).request.body as {
        label: string;
        description: string;
        produced_by: string[];
      };
      expect(body.label).toBe('Funding round closed');
      expect(body.description).toBe('A disclosed raise, with the round named.');
      expect(body.produced_by).toEqual(['funding', 'hiring']);
    });

    it('does not mutate the loaded row while ticking sources', () => {
      // `edit.produced_by` is a copy. Referencing the row's array would apply
      // the change to the screen with nothing sent, and cancelling would leave
      // it there.
      cmp.startEdit(row);
      cmp.toggleEditFamily('hiring');

      expect(row.produced_by).toEqual(['funding']);
      cmp.cancelEdit();
      expect(cmp.types().find((t) => t.key === 'funding')!.produced_by).toEqual(['funding']);
    });

    it('refuses to send a blank label', () => {
      // The server requires one, so an emptied box would turn a slip into a
      // 422 on a row the rep only meant to retune.
      cmp.startEdit(row);
      cmp.edit.label = '   ';
      cmp.edit.weight = 1.75;
      cmp.saveEdit(row);

      const body = http.expectOne(`${BASE}/funding`).request.body as Record<string, unknown>;
      expect(body['label']).toBeUndefined();
      expect(body['weight']).toBe(1.75);
    });

    it('treats a reordered source list as no change', () => {
      // `produced_by` is a set; the order is the registry's, not a choice.
      // Comparing by index would patch every row the rep merely opened.
      const two = type({ key: 'funding', produced_by: ['funding', 'hiring'] });
      cmp.types.set([two, cmp.types()[1]]);
      cmp.startEdit(two);
      cmp.edit.produced_by = ['hiring', 'funding'];
      cmp.saveEdit(two);

      expect(http.match(() => true).length)
        .withContext('same keys, different order — nothing to send')
        .toBe(0);
    });

    it('sends an explicit durability as the number given', () => {
      cmp.startEdit(row);
      cmp.edit.durability_days = 3650;
      cmp.saveEdit(row);

      const req = http.expectOne(`${BASE}/funding`);
      expect((req.request.body as { durability_days: number }).durability_days).toBe(3650);
      req.flush(type({ key: 'funding', durability_days: 3650 }));
    });

    it('sends 0 to clear a durability back to the default', () => {
      // `null` cannot carry "clear": in a patch it already means "leave this
      // field alone", so the server spells the reset as 0. Getting this wrong
      // would make the field one-way — settable and never undoable.
      const withOverride = type({ key: 'funding', durability_days: 3650 });
      cmp.types.set([withOverride, cmp.types()[1]]);
      cmp.startEdit(withOverride);
      cmp.edit.durability_days = null;
      cmp.saveEdit(withOverride);

      const req = http.expectOne(`${BASE}/funding`);
      expect((req.request.body as { durability_days: number }).durability_days).toBe(0);
      req.flush(type({ key: 'funding', durability_days: null }));
    });

    it('does not send a durability that was not touched', () => {
      // The default is stored as null and displayed as a derived number. If
      // saveEdit compared against the derived one it would patch every row it
      // opened, pinning the default and silently decoupling it from the TTL.
      cmp.startEdit(row);
      cmp.edit.weight = 1.75;
      cmp.saveEdit(row);

      const req = http.expectOne(`${BASE}/funding`);
      expect(req.request.body as Record<string, unknown>).not.toEqual(
        jasmine.objectContaining({ durability_days: jasmine.anything() }),
      );
      req.flush(type({ key: 'funding', weight: 1.75 }));
    });

    it('leaves the row alone when the server rejects the edit', () => {
      cmp.startEdit(row);
      cmp.edit.weight = 3.5; // must differ from the row's 2, or nothing is sent
      cmp.saveEdit(row);

      http
        .expectOne(`${BASE}/funding`)
        .flush({ detail: 'cannot edit a deprecated signal type' }, { status: 409, statusText: 'Conflict' });

      expect(cmp.error()).toBe('cannot edit a deprecated signal type');
      expect(cmp.types().find((t) => t.key === 'funding')!.weight)
        .withContext('the table must not show a value the server refused')
        .toBe(2);
    });
  });

  describe('pause, resume and deprecate', () => {
    it('pauses through the pause route and swaps the row in place', () => {
      boot([type({ key: 'press_mention', status: 'active' })]);
      cmp.pause(cmp.types()[0]);

      const req = http.expectOne(`${BASE}/press_mention/pause`);
      expect(req.request.method).toBe('POST');
      req.flush(type({ key: 'press_mention', status: 'paused', paused_at: '2026-09-05T00:00:00Z' }));

      expect(cmp.types()[0].status).toBe('paused');
      expect(cmp.types()[0].paused_at).not.toBeNull();
    });

    it('clears paused_at on resume', () => {
      // A resumed type that keeps a paused-since date reads as still paused in
      // every report that renders the timestamp.
      boot([type({ key: 'press_mention', status: 'paused', paused_at: '2026-09-05T00:00:00Z' })]);
      cmp.resume(cmp.types()[0]);

      http.expectOne(`${BASE}/press_mention/resume`).flush(type({ key: 'press_mention', status: 'active' }));

      expect(cmp.types()[0].status).toBe('active');
      expect(cmp.types()[0].paused_at).toBeNull();
    });

    it('asks before deleting, and only then sends', () => {
      boot([type({ key: 'typo_type', signal_count: 0 })]);
      cmp.askDelete(cmp.types()[0]);
      fixture.detectChanges();

      expect(http.match(() => true).length)
        .withContext('asking must not itself delete anything')
        .toBe(0);
      expect(fixture.nativeElement.textContent).toContain('Delete for good?');

      cmp.confirmDelete(cmp.types()[0]);
      const req = http.expectOne(`${BASE}/typo_type`);
      expect(req.request.method).toBe('DELETE');
      req.flush(null, { status: 204, statusText: 'No Content' });

      expect(cmp.types()).toEqual([]);
      expect(cmp.confirming()).toBeNull();
    });

    it('backing out of the confirm sends nothing', () => {
      boot([type({ key: 'typo_type', signal_count: 0 })]);
      cmp.askDelete(cmp.types()[0]);
      cmp.confirming.set(null);

      expect(http.match(() => true).length).toBe(0);
      expect(cmp.types().length).toBe(1);
    });

    it('keeps the row when the server refuses a delete', () => {
      // A signal can land between the page rendering and the click. The server
      // is the authority on whether history exists, not the cached count.
      boot([type({ key: 'funding', signal_count: 0 })]);
      cmp.askDelete(cmp.types()[0]);
      cmp.confirmDelete(cmp.types()[0]);

      http.expectOne(`${BASE}/funding`).flush(
        { detail: "'funding' has produced 2 signal(s) and cannot be deleted" },
        { status: 409, statusText: 'Conflict' },
      );

      expect(cmp.types().length).withContext('the row must survive a refusal').toBe(1);
      expect(cmp.error()).toContain('cannot be deleted');
      expect(cmp.confirming()).toBeNull();
    });

    it('keeps the row after deprecation rather than removing it', () => {
      boot([type({ key: 'press_mention', signal_count: 3 })]);
      cmp.deprecate(cmp.types()[0]);

      http
        .expectOne(`${BASE}/press_mention/deprecate`)
        .flush(type({ key: 'press_mention', status: 'deprecated', deprecated_at: '2026-09-05T00:00:00Z', signal_count: 3 }));

      expect(cmp.types().length).withContext('deprecate is not delete').toBe(1);
      expect(cmp.types()[0].status).toBe('deprecated');
    });

    it('surfaces a refused transition', () => {
      boot([type({ key: 'press_mention', status: 'deprecated' })]);
      cmp.pause(cmp.types()[0]);

      http
        .expectOne(`${BASE}/press_mention/pause`)
        .flush({ detail: 'cannot pause a deprecated signal type' }, { status: 409, statusText: 'Conflict' });

      expect(cmp.error()).toBe('cannot pause a deprecated signal type');
      expect(cmp.types()[0].status).toBe('deprecated');
    });
  });

  describe('what the table offers', () => {
    function actionLabels(): string[] {
      return fixture.debugElement
        .queryAll(By.css('td.actcol .act-btn')) // row actions only, not the header info toggle
        .map((b) => b.nativeElement.getAttribute('aria-label') as string);
    }

    it('offers no actions on a deprecated row that has history', () => {
      // The server answers edit and pause on a deprecated type with 409, so the
      // button should not be there to press.
      boot([type({ key: 'press_mention', status: 'deprecated', signal_count: 12 })]);
      expect(actionLabels()).toEqual([]);
      expect(fixture.nativeElement.textContent).toContain('retired');
    });

    it('offers delete rather than deprecate while nothing cites the type', () => {
      // Deprecating something that never fired leaves a tombstone explaining
      // nothing. Deleting it destroys no history, because there is none.
      boot([type({ key: 'typo_type', status: 'active', signal_count: 0 })]);
      expect(actionLabels()).toEqual(['Edit typo_type', 'Pause typo_type', 'Delete typo_type']);
    });

    it('still offers delete on a deprecated type that never fired', () => {
      // Deprecating by mistake must not trap a row in the registry forever.
      boot([type({ key: 'typo_type', status: 'deprecated', signal_count: 0 })]);
      expect(actionLabels()).toEqual(['Delete typo_type']);
      expect(fixture.nativeElement.textContent)
        .withContext('nothing to retire, so no retired label')
        .not.toContain('retired');
    });

    it('offers pause but not resume on an active row', () => {
      boot([type({ key: 'funding', status: 'active', signal_count: 4 })]);
      expect(actionLabels()).toEqual(['Edit funding', 'Pause funding', 'Deprecate funding']);
    });

    it('offers resume but not pause on a paused row', () => {
      boot([type({ key: 'funding', status: 'paused', paused_at: '2026-09-05T00:00:00Z', signal_count: 4 })]);
      expect(actionLabels()).toEqual(['Edit funding', 'Resume funding', 'Deprecate funding']);
    });

    it('swaps the row actions for save and cancel while editing', () => {
      boot([type({ key: 'funding' })]);
      cmp.startEdit(cmp.types()[0]);
      fixture.detectChanges();

      expect(actionLabels()).toEqual(['Save changes', 'Cancel editing']);
    });

    it('renders weight to two places so the baseline is legible', () => {
      // ×2 beside ×1.35 reads as a different kind of number; ×2.00 beside
      // ×1.00 reads as "twice the baseline", which is what it means.
      boot([type({ key: 'funding', weight: 2 })]);
      // Addressed by name, not position. This read `td.mono + td.mono` until a
      // Durability column landed between TTL and Weight and it silently began
      // asserting about a different number.
      expect(
        fixture.nativeElement.querySelector('td[data-col="weight"]').textContent.trim(),
      ).toBe('×2.00');
    });

    it('shows the durability as one number, with no multiplier beside it', () => {
      // "900d ×3" read as a multiplier still to apply — 2700 days — when the
      // 900 already was 300×3. The derivation belongs in the tooltip, not
      // next to the figure it would be mistaken for.
      boot([type({ key: 'funding', default_ttl_days: 300, durability_effective_days: 900 })]);
      const cell = fixture.nativeElement.querySelector('td[data-col="durability"]');

      expect(cell.textContent.trim()).toBe('900d');
      expect(cell.textContent).not.toContain('×');
    });

    it('puts the derivation in the tooltip instead', () => {
      boot([type({ key: 'funding' })]);
      const derived = type({ key: 'funding', default_ttl_days: 300, durability_days: null });
      const chosen = type({ key: 'funding', default_ttl_days: 300, durability_days: 3650 });

      expect(cmp.durabilityWhy(derived)).toContain('three times the 300-day TTL');
      expect(cmp.durabilityWhy(chosen)).toContain('Set for this type');
      expect(cmp.durabilityWhy(chosen))
        .withContext('and says what the default would have been')
        .toContain('900');
    });

    it('renders the tooltip on the cell, not just in the method', () => {
      boot([type({ key: 'funding', default_ttl_days: 300, durability_effective_days: 900 })]);
      const cell = fixture.nativeElement.querySelector('td[data-col="durability"] [title]');

      expect(cell?.getAttribute('title')).toContain('three times the 300-day TTL');
    });

    it('labels both Add buttons the same but names their scope for a screen reader', () => {
      // The visible label can drop the scope because the Company/Contact badge
      // sits beside it. A screen reader gets no such adjacency.
      boot([]);
      const buttons = fixture.debugElement.queryAll(By.css('.sec-head button'));

      expect(buttons.map((b) => b.nativeElement.textContent.trim())).toEqual([
        'Add Signal',
        'Add Signal',
      ]);
      expect(buttons.map((b) => b.nativeElement.getAttribute('aria-label'))).toEqual([
        'Add company signal type',
        'Add contact signal type',
      ]);
    });

    it('keeps the explainer folded away until the info icon is pressed', () => {
      // It is reference material — how weight works, why evidence is required.
      // Worth reading once, not worth pushing both tables below the fold on
      // every visit.
      boot([]);
      const help = () => fixture.nativeElement.querySelector('#signal-types-help');
      const icon = () =>
        fixture.debugElement.query(By.css('[aria-controls="signal-types-help"]')).nativeElement;

      expect(help()).withContext('collapsed on arrival').toBeNull();
      expect(icon().getAttribute('aria-expanded')).toBe('false');

      icon().click();
      fixture.detectChanges();
      expect(help().textContent).toContain('multiplier, not a share');
      expect(icon().getAttribute('aria-expanded'))
        .withContext('a screen reader needs the state, not just the label')
        .toBe('true');

      icon().click();
      fixture.detectChanges();
      expect(help()).withContext('and it folds back').toBeNull();
    });

    it('says which registry is empty rather than showing a bare table', () => {
      boot([type({ scope: 'company' })]);
      expect(fixture.nativeElement.textContent).toContain('No contact signal types yet.');
      expect(fixture.nativeElement.textContent).not.toContain('No company signal types yet.');
    });
  });
});
