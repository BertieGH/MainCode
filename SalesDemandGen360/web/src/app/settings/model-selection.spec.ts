import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { CredentialFormComponent } from './credential-form.component';
import { ModelConfigComponent } from './model-config.component';

/**
 * Choosing models beside the key, and consuming that choice per stage.
 *
 * The two screens have to agree, and the failure when they do not is quiet: a
 * dropdown offering something the server will refuse, or a stage silently
 * pointed at a provider whose key never worked. Both are asserted here rather
 * than left to the two components to get right independently.
 */

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
    key: 'gemini',
    label: 'Google Gemini',
    kind: 'llm',
    purpose: '',
    console_url: 'https://aistudio.google.com/apikey',
    runnable: true,
    verifiable: true,
    credential_types: ['api_key'],
    models: [
      { id: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash', structured_output: true, effort: true, prompt_caching: true, tier: 'balanced', notes: null },
    ],
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
    {
      provider: 'gemini',
      label: 'Google Gemini',
      runnable: true,
      enabled: ['gemini-3.8-flash'],
      catalogue: ['gemini-3.8-flash'],
      custom: [],
      defaulted: false,
    },
  ],
  in_use: [
    { provider: 'anthropic', model: 'claude-opus-5', scenarios: ['outreach_drafting'] },
  ],
};

const cred = (provider: string, status: string) => ({
  id: provider,
  provider,
  credential_type: 'api_key',
  last_four: 'aaaa',
  status,
  last_tested_at: null,
  spend_cap: null,
});

const NO_SPEND = {
  days: 7,
  since: '2026-09-14T00:00:00Z',
  calls: 0,
  failed: 0,
  input_tokens: 0,
  output_tokens: 0,
  cache_read_tokens: 0,
  by_stage: [],
  note: 'Tokens, not currency — apply your own vendor rates.',
};

describe('choosing models beside the key on Setup', () => {
  let fixture: ComponentFixture<CredentialFormComponent>;
  let cmp: CredentialFormComponent;
  let http: HttpTestingController;

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

  it('offers the picker only for providers that run models', () => {
    cmp.draft.provider = 'anthropic';
    cmp.onProviderChange();
    expect(cmp.llmProvider()?.key).toBe('anthropic');

    // A CRM key has no models to choose, and offering an empty tick-list
    // reads as a broken screen.
    cmp.draft.provider = 'crm';
    cmp.onProviderChange();
    expect(cmp.llmProvider()).toBeUndefined();
  });

  it('shows what is already selected for that provider', () => {
    expect(cmp.enabledFor('anthropic')).toEqual(['claude-opus-5']);
    expect(cmp.isEnabled('anthropic', 'claude-sonnet-5')).toBe(false);
  });

  it('locks a model a stage is using, and says which stage', () => {
    // Removing it would not fail here — it would fail at that stage's next
    // real call, naming a model rather than the setting that removed it.
    expect(cmp.isLocked('anthropic', 'claude-opus-5')).toBe(true);
    expect(cmp.usedBy('anthropic', 'claude-opus-5')).toBe('outreach_drafting');

    cmp.toggleModel('anthropic', 'claude-opus-5');
    expect(cmp.isEnabled('anthropic', 'claude-opus-5')).toBe(true);
  });

  it('adds and removes an unused model', () => {
    cmp.toggleModel('anthropic', 'claude-sonnet-5');
    expect(cmp.enabledFor('anthropic')).toContain('claude-sonnet-5');
    cmp.toggleModel('anthropic', 'claude-sonnet-5');
    expect(cmp.enabledFor('anthropic')).not.toContain('claude-sonnet-5');
  });

  it('keeps a model id the catalogue does not know', () => {
    // Vendor ids drift; the Gemini ones were wrong until checked live.
    cmp.customDraft = 'gemini-9-experimental';
    cmp.addCustom('gemini');
    expect(cmp.customFor('gemini')).toEqual(['gemini-9-experimental']);
  });

  it('saves without needing the key pasted again', () => {
    cmp.toggleModel('anthropic', 'claude-sonnet-5');
    cmp.saveModels('anthropic');

    const req = http.expectOne('/api/config/model-availability');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body.enabled.anthropic).toEqual([
      'claude-opus-5',
      'claude-sonnet-5',
    ]);
    // The credential value is a separate concern and must not be involved.
    expect(JSON.stringify(req.request.body)).not.toContain('value');
    req.flush(AVAILABILITY);
  });

  it('does not freeze a provider that has made no choice', () => {
    // A provider left out resolves to its whole catalogue. Sending every
    // provider would silently convert those defaults into fixed lists.
    cmp.availability.set([
      { ...AVAILABILITY.providers[0] },
      { ...AVAILABILITY.providers[1], defaulted: true },
    ]);
    cmp.toggleModel('anthropic', 'claude-sonnet-5');
    cmp.saveModels('anthropic');

    const req = http.expectOne('/api/config/model-availability');
    expect(Object.keys(req.request.body.enabled)).toEqual(['anthropic']);
    req.flush(AVAILABILITY);
  });
});

describe('consuming that choice on Model config', () => {
  let fixture: ComponentFixture<ModelConfigComponent>;
  let cmp: ModelConfigComponent;
  let http: HttpTestingController;

  const CONFIGS = [
    {
      id: '1',
      scenario: 'outreach_drafting',
      provider: 'anthropic',
      model: 'claude-opus-5',
      effort: 'high',
      max_tokens: 16000,
      thinking_mode: 'adaptive',
      output_contract: 'DraftSet',
      version: 1,
      is_active: true,
      runnable: true,
    },
  ];

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ModelConfigComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(ModelConfigComponent);
    cmp = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    http.expectOne('/api/config/llm').flush(CONFIGS);
    http.expectOne('/api/config/model-availability').flush(AVAILABILITY);
    http.expectOne('/api/config/credentials').flush([
      cred('anthropic', 'valid'),
      cred('gemini', 'valid'),
      cred('openai', 'invalid'),
    ]);
    http.expectOne('/api/config/providers').flush(PROVIDERS);
    // The spend panel loads with the screen: effort and token budget are the
    // levers, and what they cost belongs beside them.
    http.expectOne('/api/config/llm/spend?days=7').flush(NO_SPEND);
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('names the stage whose worst call dwarfs its average', () => {
    const c = fixture.componentInstance as any;
    // The shape `strategy_synthesis` actually had: adaptive thinking at xhigh
    // effort, ordinary most of the time and ruinous occasionally. An average
    // alone hides it completely.
    const runaway = {
      scenario: 'strategy_synthesis', model: 'gemini-3.8-flash', calls: 6, failed: 2,
      input_tokens: 13000, output_tokens: 36000, cache_read_tokens: 0,
      avg_output: 600, worst_output: 30208, avg_ms: 9000,
    };
    const steady = {
      scenario: 'signal_extraction', model: 'gemini-3.5-flash-lite', calls: 40, failed: 0,
      input_tokens: 80000, output_tokens: 20000, cache_read_tokens: 0,
      avg_output: 500, worst_output: 900, avg_ms: 1200,
    };
    expect(c.runaway(runaway)).toBeTrue();
    expect(c.times(runaway)).toBe(50);
    expect(c.runaway(steady)).toBeFalse();
  });

  it('does not cry runaway over a couple of calls', () => {
    const c = fixture.componentInstance as any;
    expect(c.runaway({ calls: 2, avg_output: 100, worst_output: 5000 })).toBeFalse();
  });


  it('offers only providers whose key the vendor accepted', () => {
    // A stage pointed at a provider we cannot authenticate to fails on its
    // first real call, three screens from the setting that caused it.
    expect(cmp.selectableProviders('anthropic')).toEqual(['anthropic', 'gemini']);
  });

  it('keeps a stage readable when its provider key goes bad', () => {
    // Otherwise the dropdown silently rewrites a configuration nobody touched.
    expect(cmp.selectableProviders('openai')).toContain('openai');
  });

  it('offers only the models selected for that provider', () => {
    cmp.startEdit(CONFIGS[0]);
    expect(cmp.modelsForEdit().map((m) => m.id)).toEqual(['claude-opus-5']);
    // Sonnet is in the catalogue and not selected, so it must not appear —
    // saving it would be refused by the server.
    expect(cmp.modelsForEdit().map((m) => m.id)).not.toContain('claude-sonnet-5');
  });

  it('re-filters when the provider changes', () => {
    cmp.startEdit(CONFIGS[0]);
    cmp.edit.provider = 'gemini';
    cmp.onProviderChange();
    expect(cmp.modelsForEdit().map((m) => m.id)).toEqual(['gemini-3.8-flash']);
    // And the model follows, rather than leaving a stage pointed at a model
    // its new provider does not have.
    expect(cmp.edit.model).toBe('gemini-3.8-flash');
  });
});
