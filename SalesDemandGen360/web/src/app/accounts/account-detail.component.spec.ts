import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';

import { AccountDetailComponent } from './account-detail.component';
import { Intelligence, SignalRow } from '../core/pipeline.service';

/**
 * The signals tab, and specifically which signals count as live.
 *
 * A `mgt_change` observed in April 2021 sat on this screen in October 2026
 * beside a current one, with only a date between them. It read as news. It was
 * in zero prompts the whole time — `context.live_signals` filters on
 * `expires_at` — so the screen was the only place it could mislead anyone.
 *
 * The rule under test is that "live" here means what it means everywhere else:
 * not expired **and** not superseded. Getting the second half wrong is the
 * harder bug, because the only symptom is a signal a rep expected to see
 * quoted in a draft and never did.
 */

const ACCOUNT = 'acc-1';
const URL = `/api/accounts/${ACCOUNT}/intelligence`;

function ahead(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function sig(over: Partial<SignalRow> = {}): SignalRow {
  return {
    id: crypto.randomUUID(),
    signal_type: 'mgt_change',
    scope: 'company',
    summary: 'Appointed a new benefits lead',
    business_implication: null,
    strength: 'medium',
    confidence: 0.8,
    observed_at: ahead(-30),
    expires_at: ahead(150),
    lifecycle_state: 'validated',
    superseded_by: null,
    is_hypothesis: false,
    contact_id: null,
    contact_name: null,
    evidence: [],
    ...over,
  };
}

function intel(signals: SignalRow[], over: Partial<Intelligence> = {}): Intelligence {
  return {
    account_id: ACCOUNT,
    account_name: 'Champion Risk',
    domain: 'championrisk.test',
    profile: null,
    contact_profiles: [],
    signals,
    coverage: [],
    context_narrative: null,
    unattributed_evidence: [],
    context_version: null,
    qualification: null,
    outreach: [],
    ...over,
  };
}

describe('AccountDetailComponent · live and background signals', () => {
  let fixture: ComponentFixture<AccountDetailComponent>;
  let cmp: AccountDetailComponent;
  let http: HttpTestingController;

  function boot(signals: SignalRow[]): void {
    fixture = TestBed.createComponent(AccountDetailComponent);
    cmp = fixture.componentInstance;
    fixture.detectChanges();
    http.expectOne(URL).flush(intel(signals));
    // The tab strip's counts are loaded up front, so the contacts request
    // fires too. Answered rather than verified — it is not what this is about.
    http.match(() => true).forEach((r) => r.flush([]));
    cmp.tab.set('signals');
    fixture.detectChanges();
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [AccountDetailComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: { get: () => ACCOUNT } } },
        },
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify({ ignoreCancelled: true }));

  describe('the partition', () => {
    it('counts an unexpired, unsuperseded signal as live', () => {
      const s = sig();
      boot([s]);

      expect(cmp.isLive(s)).toBeTrue();
      expect(cmp.live([s]).length).toBe(1);
      expect(cmp.background([s]).length).toBe(0);
    });

    it('counts an expired signal as background', () => {
      // The live case: observed 2021-04-01, expired 2021-09-28, still on screen
      // in October 2026.
      const s = sig({ observed_at: '2021-04-01', expires_at: '2021-09-28' });
      boot([s]);

      expect(cmp.isLive(s)).toBeFalse();
      expect(cmp.background([s]).length).toBe(1);
    });

    it('counts a superseded signal as background even though it has not expired', () => {
      // The half that is easy to get wrong. `drafting` refuses to cite a
      // superseded signal, so showing it as live promises something outreach
      // will not deliver.
      const s = sig({ expires_at: ahead(150), superseded_by: crypto.randomUUID() });
      boot([s]);

      expect(cmp.isLive(s)).toBeFalse();
      expect(cmp.background([s]).length).toBe(1);
    });

    it('treats a signal with no expiry as live', () => {
      // Null expiry is "does not age", not "aged out". Reading it the other way
      // would bury every signal of a type that never expires.
      const s = sig({ expires_at: null });
      boot([s]);

      expect(cmp.isLive(s)).toBeTrue();
    });
  });

  describe('the labels', () => {
    it('says superseded ahead of expired when a signal is both', () => {
      // Superseded is the more specific fact and the more actionable one: it
      // says a newer reading exists, which "expired" does not.
      const s = sig({ expires_at: '2021-09-28', superseded_by: crypto.randomUUID() });
      boot([s]);

      expect(cmp.stateLabel(s)).toBe('superseded');
    });

    it('shows the lifecycle state for a live signal rather than inventing one', () => {
      const s = sig({ lifecycle_state: 'validated' });
      boot([s]);

      expect(cmp.stateLabel(s)).toBe('validated');
    });

    it('explains each state in a tooltip', () => {
      const expired = sig({ expires_at: '2021-09-28' });
      const superseded = sig({ superseded_by: crypto.randomUUID() });
      boot([expired]);

      expect(cmp.stateWhy(expired)).toContain('still true');
      expect(cmp.stateWhy(superseded)).toContain('newer reading');
    });
  });

  describe('what gets rendered', () => {
    it('keeps background signals out of the live list and in their own group', () => {
      boot([
        sig({ summary: 'Appointed a new benefits lead this month' }),
        sig({ summary: 'Appointed a different lead in 2021', expires_at: '2021-09-28' }),
      ]);

      const group = fixture.nativeElement.querySelector('details.bg-group');
      expect(group).withContext('the background group should exist').toBeTruthy();
      expect(group.textContent).toContain('no longer a trigger (1)');
      expect(group.textContent).toContain('Appointed a different lead in 2021');
      expect(group.textContent)
        .withContext('the live one belongs above, not inside')
        .not.toContain('this month');
    });

    it('collapses the background group by default', () => {
      // The clutter is the whole complaint; opening it is one click.
      boot([sig({ expires_at: '2021-09-28' })]);

      expect(fixture.nativeElement.querySelector('details.bg-group').open).toBeFalse();
      expect(cmp.showBackground()).toBeFalse();
    });

    it('shows no background group when every signal is live', () => {
      boot([sig(), sig()]);

      expect(fixture.nativeElement.querySelector('details.bg-group')).toBeNull();
    });

    it('says so when everything found has aged out', () => {
      // Distinct from "no signals yet": research ran and found things, and all
      // of them are history. Silence here reads as never having looked.
      boot([sig({ expires_at: '2021-09-28' })]);
      const text = fixture.nativeElement.textContent;

      expect(text).toContain('Nothing live');
      expect(text).not.toContain('Research has not run');
    });

    it('still says nothing has run when there are no signals at all', () => {
      boot([]);
      const text = fixture.nativeElement.textContent;

      expect(text).toContain('Research has not run');
      expect(text).not.toContain('Nothing live');
    });

    it('marks background cards so they read as receded', () => {
      boot([sig({ expires_at: '2021-09-28' })]);

      expect(fixture.nativeElement.querySelector('.sig.sig-bg')).toBeTruthy();
    });
  });
});

/**
 * The profile tab.
 *
 * `account.profile` and `contact.profile` have been written by the profile
 * stage, read by the context builder, and so consumed by qualification,
 * strategy and drafting — while being shown on no screen at all. The one
 * reader who could not see them was the rep.
 *
 * What these guard is the distinction the profile exists for: a profile is
 * what a company or a person *is*, carries no expiry, and must never be
 * presented as a dated trigger. And that "no profile" and "a profile that
 * established nothing" do not read alike.
 */
describe('AccountDetailComponent · profile tab', () => {
  let fixture: ComponentFixture<AccountDetailComponent>;
  let cmp: AccountDetailComponent;
  let http: HttpTestingController;

  const COMPANY = {
    what_they_do: 'A managing program administrator for nonprofits.',
    services: ['Workers Compensation'],
    target_customers: ['Nonprofit organizations'],
    size: 'About 20 employees',
    founded: '1985',
    sources: ['https://www.charityfirst.com/about'],
    verbatim: [{ text: 'Charity First began in 1985 as an MGU.', url: 'https://x.test/a' }],
  };

  const PERSON = {
    contact_id: 'c-1',
    contact_name: 'Mark Raby',
    title: 'Chief Executive Officer',
    profile: {
      summary: 'Runs the brokerage and owns the technology budget.',
      responsibilities: ['Technology spend'],
      tenure: 'Thirty years in the industry',
      verbatim: [{ text: 'I am a seasoned insurance professional.', url: 'https://x.test/b' }],
    },
  };

  function boot(over: Partial<Intelligence> = {}): void {
    fixture = TestBed.createComponent(AccountDetailComponent);
    cmp = fixture.componentInstance;
    fixture.detectChanges();
    http.expectOne(URL).flush(intel([], over));
    http.match(() => true).forEach((r) => r.flush([]));
    cmp.tab.set('profile');
    fixture.detectChanges();
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [AccountDetailComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: { get: () => ACCOUNT } } },
        },
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('shows the company profile the pipeline already stored', () => {
    boot({ profile: COMPANY });
    const text = fixture.nativeElement.textContent;

    expect(text).toContain('A managing program administrator for nonprofits.');
    expect(text).toContain('Nonprofit organizations');
    expect(text).toContain('About 20 employees');
  });

  it('shows a profile for each person at the company', () => {
    boot({ profile: COMPANY, contact_profiles: [PERSON] });
    const text = fixture.nativeElement.textContent;

    expect(text).toContain('Mark Raby');
    expect(text).toContain('Chief Executive Officer');
    expect(text).toContain('Runs the brokerage and owns the technology budget.');
  });

  it('keeps the source text behind a disclosure, per subject', () => {
    boot({ profile: COMPANY, contact_profiles: [PERSON] });

    // Two independent toggles, not one: opening the company's passages must
    // not open a person's. They are different claims about different subjects.
    cmp.toggle('prof-company');
    fixture.detectChanges();
    let text = fixture.nativeElement.textContent;
    expect(text).toContain('Charity First began in 1985 as an MGU.');
    expect(text).not.toContain('I am a seasoned insurance professional.');

    cmp.toggle('prof-c-1');
    fixture.detectChanges();
    text = fixture.nativeElement.textContent;
    expect(text).toContain('I am a seasoned insurance professional.');
  });

  it('never presents a profile as dated', () => {
    boot({ profile: COMPANY, contact_profiles: [PERSON] });
    const text = fixture.nativeElement.textContent;

    // The whole reason this is not a signal type. A TTL here would expire a
    // fact that has not changed.
    expect(text).not.toContain('expires');
    expect(text).not.toContain('Observed');
  });

  it('says a company has not been researched rather than showing it blank', () => {
    boot({ profile: null });
    const text = fixture.nativeElement.textContent;

    expect(text).toContain('not researched');
    expect(text).toContain('No profile for Champion Risk yet');
  });

  it('counts described people, and shows a dash rather than zero', () => {
    boot({ profile: COMPANY });

    // "0 profiles" reads as a measurement; nothing here has been measured.
    expect(cmp.countFor('profile', intel([], { profile: COMPANY }))).toBe('—');
    expect(cmp.countFor('profile', intel([], { contact_profiles: [PERSON] }))).toBe(1);
  });

  it('shortens a source URL to its host but links the whole thing', () => {
    boot({ profile: COMPANY });
    const link: HTMLAnchorElement = fixture.nativeElement.querySelector('.psrc a');

    expect(link.textContent!.trim()).toBe('charityfirst.com');
    expect(link.href).toBe('https://www.charityfirst.com/about');
  });

  it('shows one link per host, not the same word twice', () => {
    // Champion Risk cites two pages on its own site. Rendered naively the
    // line read "championrisk.com, championrisk.com, insurancejournal.com",
    // which looks like a bug whatever the hrefs say.
    boot({
      profile: {
        ...COMPANY,
        sources: [
          'https://www.championrisk.com/a',
          'https://www.championrisk.com/b',
          'https://www.insurancejournal.com/c',
        ],
      },
    });
    const labels = [...fixture.nativeElement.querySelectorAll('.psrc a')].map(
      (a: any) => a.textContent.trim(),
    );

    expect(labels).toEqual(['championrisk.com', 'insurancejournal.com']);
  });
});

/**
 * What a signal card calls itself.
 *
 * The type key alone was doing two jobs badly: `contact_profile` sat on the
 * signals tab reading as though it were the person's profile, which is a
 * different object, lives on its own tab, and carries no expiry.
 */
describe('AccountDetailComponent · company and contact signal sections', () => {
  let fixture: ComponentFixture<AccountDetailComponent>;
  let http: HttpTestingController;

  function boot(signals: SignalRow[]): void {
    fixture = TestBed.createComponent(AccountDetailComponent);
    fixture.detectChanges();
    http.expectOne(URL).flush(intel(signals));
    http.match(() => true).forEach((r) => r.flush([]));
    fixture.componentInstance.tab.set('signals');
    fixture.detectChanges();
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [AccountDetailComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: { get: () => ACCOUNT } } },
        },
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('heads the two kinds separately', () => {
    boot([
      sig({ scope: 'company' }),
      sig({ scope: 'contact', contact_name: 'Mark Raby' }),
    ]);
    const text = fixture.nativeElement.textContent;

    expect(text).toContain('Company signals');
    expect(text).toContain('Contact signals');
  });

  it('omits a heading for a kind with nothing in it', () => {
    boot([sig({ scope: 'company' })]);
    const text = fixture.nativeElement.textContent;

    expect(text).toContain('Company signals');
    expect(text).not.toContain('Contact signals');
  });

  it('never puts the registry key on the face of a card', () => {
    // It was the first thing a rep read, and contact_profile read as the
    // person's profile — a different object, on its own tab, with no expiry.
    boot([sig({ scope: 'contact', signal_type: 'contact_profile' })]);

    expect(fixture.nativeElement.querySelector('.sig-head code')).toBeNull();
    expect(fixture.nativeElement.textContent).not.toContain('contact_profile');
  });

  it('keeps the key reachable on hover for registry work', () => {
    boot([sig({ signal_type: 'mgt_change' })]);
    const line = fixture.nativeElement.querySelector('.sig strong');

    expect(line.title).toBe('signal type: mgt_change');
  });

  it('drops the per-card scope badge the heading now carries', () => {
    boot([sig({ scope: 'company' })]);
    const head = fixture.nativeElement.querySelector('.sig-head').textContent;

    expect(head).not.toContain('company signal');
    expect(head).not.toContain('contact signal');
  });
});
