import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CredentialFormComponent } from './credential-form.component';

/**
 * The credential rules from CLAUDE.md, asserted on the client too.
 *
 * The backend already cannot return a value. These cover the other half: the
 * browser must not keep one either, because a secret left in a bound field
 * ends up in a component snapshot, a screenshot, or an autofill store.
 *
 * These tests followed the form when Integrations was merged into Setup —
 * the screen moved, the rules did not.
 */
describe('CredentialFormComponent', () => {
  let fixture: ComponentFixture<CredentialFormComponent>;
  let cmp: CredentialFormComponent;
  let http: HttpTestingController;

  const SECRET = 'sk-ant-EXAMPLE-NOT-REAL-9f2a';

  const PROVIDERS = [
    {
      key: 'anthropic',
      label: 'Anthropic',
      kind: 'llm',
      purpose: '',
      console_url: 'https://console.anthropic.com/settings/keys',
      runnable: true,
      verifiable: true,
      credential_types: ['api_key'],
      models: [
        { id: 'claude-opus-5', label: 'Opus 5', structured_output: true, effort: true, prompt_caching: true, tier: 'frontier', notes: null },
        { id: 'claude-sonnet-5', label: 'Sonnet 5', structured_output: true, effort: true, prompt_caching: true, tier: 'balanced', notes: null },
      ],
    },
    {
      key: 'lgm',
      label: 'La Growth Machine',
      kind: 'outreach',
      purpose: '',
      console_url: 'https://app.lagrowthmachine.com/settings/api',
      runnable: false,
      verifiable: false,
      credential_types: ['api_key'],
      models: [],
    },
  ];

  const AVAILABILITY = {
    providers: [
      {
        provider: 'anthropic',
        label: 'Anthropic',
        runnable: true,
        enabled: ['claude-opus-5'],
        catalogue: ['claude-opus-5', 'claude-sonnet-5'],
        custom: [],
        defaulted: false,
      },
    ],
    in_use: [
      { provider: 'anthropic', model: 'claude-opus-5', scenarios: ['outreach_drafting'] },
    ],
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CredentialFormComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(CredentialFormComponent);
    cmp = fixture.componentInstance;
    cmp.provider = 'anthropic';
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    http.expectOne('/api/config/providers').flush(PROVIDERS);
    http.expectOne('/api/config/model-availability').flush(AVAILABILITY);
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('clears the value from component state once stored', () => {
    cmp.draft.value = SECRET;
    cmp.save();

    http.expectOne('/api/config/credentials').flush({
      id: '1', provider: 'anthropic', credential_type: 'api_key',
      last_four: '9f2a', status: 'untested', last_tested_at: null, spend_cap: null,
    });

    expect(cmp.draft.value).toBe('');
  });

  it('never renders the value into the DOM', () => {
    cmp.draft.value = SECRET;
    fixture.detectChanges();
    expect(fixture.nativeElement.innerHTML).not.toContain(SECRET);
  });

  it('uses a password input so the value is not shoulder-readable', () => {
    const input: HTMLInputElement = fixture.nativeElement.querySelector('input[type=password]');
    expect(input).toBeTruthy();
  });

  it('rejects a provider key that would become a second, identical-looking one', () => {
    // " Anthropic " and "anthropic" render the same and share no credential.
    cmp.draft.provider = 'Anthropic';
    cmp.onProviderChange();
    expect(cmp.providerError()).toContain('Lowercase');
  });

  it('suggests only the providers for its slot', () => {
    cmp.kind = 'outreach';
    expect(cmp.suggestions().map((p) => p.key)).toEqual(['lgm']);
    // Entering an outreach key under the enrichment heading was possible
    // while Setup and Integrations were separate screens.
    cmp.kind = 'llm';
    expect(cmp.suggestions().map((p) => p.key)).toEqual(['anthropic']);
  });

  describe('the model shortlist beside the key', () => {
    it('appears only for a provider that runs models', () => {
      expect(cmp.llmProvider()?.key).toBe('anthropic');

      cmp.draft.provider = 'lgm';
      cmp.onProviderChange();
      // An outreach key has no models to choose, and an empty tick-list reads
      // as a broken screen.
      expect(cmp.llmProvider()).toBeUndefined();
    });

    it('locks a model a stage is using, and names the stage', () => {
      expect(cmp.isLocked('anthropic', 'claude-opus-5')).toBe(true);
      expect(cmp.usedBy('anthropic', 'claude-opus-5')).toBe('outreach_drafting');
      cmp.toggleModel('anthropic', 'claude-opus-5');
      expect(cmp.isEnabled('anthropic', 'claude-opus-5')).toBe(true);
    });

    it('saves without the credential value being involved', () => {
      // Changing which models a key may drive must not require pasting the
      // key again — they are separate requests for separate reasons.
      cmp.draft.value = SECRET;
      cmp.toggleModel('anthropic', 'claude-sonnet-5');
      cmp.saveModels('anthropic');

      const req = http.expectOne('/api/config/model-availability');
      expect(req.request.method).toBe('PUT');
      expect(JSON.stringify(req.request.body)).not.toContain(SECRET);
      req.flush(AVAILABILITY);
    });
  });
});
