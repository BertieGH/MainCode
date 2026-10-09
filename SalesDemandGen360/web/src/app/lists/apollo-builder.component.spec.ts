import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ApolloBuilderComponent } from './apollo-builder.component';
import { ApolloBuild } from '../core/lists.service';

/**
 * Which answer decides whether the list can be built.
 *
 * There are two counts with very different costs — a coarse one that runs on
 * every change, and a deep one that reads the pages — and they can disagree
 * about whether Apollo is reachable *right now*. Getting that wrong disabled
 * Create while a perfectly good result sat on screen.
 */
function build(over: Partial<ApolloBuild> = {}): ApolloBuild {
  return {
    ran: true,
    blocked: null,
    funnel: {
      saved_total: 356830, verified: 250344, titled: 88841, in_band: 24705,
      read: 0, companies: 0, usable_companies: 0, available: 0,
    },
    note: '',
    created: 0,
    merged: 0,
    contacts: 0,
    sample: [],
    ...over,
  };
}

describe('ApolloBuilderComponent · which count enables Create', () => {
  let fixture: ComponentFixture<ApolloBuilderComponent>;
  let cmp: ApolloBuilderComponent;
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ApolloBuilderComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    fixture = TestBed.createComponent(ApolloBuilderComponent);
    cmp = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify({ ignoreCancelled: true }));

  it('needs a name', () => {
    cmp.result.set(build());
    cmp.label = '   ';
    expect(cmp.canBuild()).toBe(false);
  });

  it('is ready on the coarse count alone', () => {
    cmp.result.set(build());
    cmp.label = 'A list';
    expect(cmp.canBuild()).toBe(true);
  });

  it('stays ready when the coarse count fails but a deep read succeeded', () => {
    // The bug. Apollo's rate limit fails the cheap call, which runs on every
    // keystroke, while the expensive call that actually proves a build will
    // work has already come back. Create was disabled beside its own answer.
    cmp.result.set(build({ ran: false, blocked: 'Apollo rate limit reached' }));
    cmp.deep.set(build({ ran: true, funnel: { ...build().funnel, available: 102 } }));
    cmp.label = 'A list';

    expect(cmp.canBuild()).toBe(true);
    expect(cmp.willTake()).toBe(100);
  });

  it('is not ready when both counts failed', () => {
    cmp.result.set(build({ ran: false, blocked: 'Apollo rate limit reached' }));
    cmp.deep.set(build({ ran: false, blocked: 'Apollo rate limit reached' }));
    cmp.label = 'A list';
    expect(cmp.canBuild()).toBe(false);
  });

  it('shows the refusal rather than going silently blank', () => {
    // The funnel is bound to the failing answer, so it vanished and nothing
    // took its place: no numbers, no error, a disabled button and no reason.
    cmp.result.set(build({ ran: false, blocked: 'Apollo rate limit reached' }));
    expect(cmp.refusal()).toBe('Apollo rate limit reached');
  });

  it('prefers the deep answer, which carries every number the coarse one has', () => {
    const deep = build({ funnel: { ...build().funnel, read: 1600, usable_companies: 51 } });
    cmp.result.set(build());
    cmp.deep.set(deep);
    expect(cmp.shown()).toBe(deep);
  });

  it('falls back to the coarse answer before any deep read', () => {
    const coarse = build();
    cmp.result.set(coarse);
    expect(cmp.shown()).toBe(coarse);
  });
});

describe('ApolloBuilderComponent · the suggested name', () => {
  let cmp: ApolloBuilderComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ApolloBuilderComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    cmp = TestBed.createComponent(ApolloBuilderComponent).componentInstance;
  });

  it('is a real value, not a placeholder', () => {
    // It was grey placeholder text, so the field was empty, Create stayed
    // disabled, and the only way on was to type the suggestion out by hand.
    cmp.ngOnInit();
    expect(cmp.label).toBe('Apollo · 51-200 · both personas');
  });

  it('follows the filters', () => {
    cmp.ngOnInit();
    cmp.toggleIndustry('information technology & services');
    expect(cmp.label).toContain('IT services');
  });

  it('stops following once it has been typed in', () => {
    // A field that rewrites itself under the cursor is worse than no help.
    cmp.ngOnInit();
    cmp.label = 'My own name';
    cmp.labelTyped();
    cmp.toggleIndustry('insurance');
    expect(cmp.label).toBe('My own name');
  });
});
