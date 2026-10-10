import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';

import { PrepService, ageLabel, ageTone } from './prep.service';

describe('PrepService', () => {
  let api: PrepService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [PrepService, provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(PrepService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('asks for one contact in one request', () => {
    api.forContact('c-1').subscribe();
    http.expectOne('/api/prep/c-1').flush({});
  });

  it('sends no query at all when the box is empty', () => {
    api.index('   ').subscribe();
    http.expectOne('/api/prep').flush({ queue: [], queue_blocked: null, results: [], total: 0 });
  });

  it('encodes a search term', () => {
    api.index('AI & agents').subscribe();
    http.expectOne('/api/prep?q=AI%20%26%20agents').flush({
      queue: [],
      queue_blocked: null,
      results: [],
      total: 0,
    });
  });
});

describe('ageLabel', () => {
  /**
   * The distinction the whole freshness panel rests on. A screen that prints
   * "0 days" for a null has told the rep research is current when nobody has
   * ever looked — the opposite of the truth, in the one place the design exists
   * to be careful about.
   */
  it('never renders never as a number of days', () => {
    expect(ageLabel(null)).toBe('never');
    expect(ageLabel(0)).toBe('today');
    expect(ageLabel(0)).not.toBe(ageLabel(null));
  });

  it('reads naturally at the boundaries', () => {
    expect(ageLabel(1)).toBe('1 day');
    expect(ageLabel(2)).toBe('2 days');
  });
});

describe('ageTone', () => {
  it('treats never as the worst case, not the best', () => {
    expect(ageTone('research', null)).toBe('critical');
    expect(ageTone('signals', null)).toBe('critical');
  });

  it('holds research to a tighter standard than signals', () => {
    // A signal is about something that happened; it ages honestly. A *look* is
    // about us, and a month-old look may have missed everything since.
    expect(ageTone('research', 20)).toBe('warn');
    expect(ageTone('signals', 20)).toBe('good');
  });

  it('does not alarm about an engagement age', () => {
    // How long ago we wrote to someone is context, not a defect. Only
    // "never sent" matters, and the ladder says that in words.
    expect(ageTone('engagement', 400)).toBe('good');
  });
});
