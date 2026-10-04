import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

/**
 * Typed client for the /api/config surface.
 *
 * Note what is absent from `Credential`: any field carrying the value. The
 * backend response model has nowhere to put one, and mirroring that here means
 * a component cannot bind a secret into the DOM even by accident.
 */

export interface SalesRules {
  id: string;
  version: number;
  is_active: boolean;
  priority_threshold: number;
  persona_weight_threshold: number;
  max_concurrent_threads: number;
  thread_start_offset_days: number;
  signal_ttl_days: Record<string, number>;
  sample_rate: number;
  no_go: Record<string, unknown> | null;
  compliance: Record<string, unknown> | null;
  created_at: string;
}

export type SalesRulesInput = Omit<
  SalesRules,
  'id' | 'version' | 'is_active' | 'created_at'
>;

export interface ScoringConfig {
  id: string;
  version: number;
  is_active: boolean;
  dimension_weights: Record<string, number>;
  /** Keyed on the normalised industry — see `scoring.normalise_industry`. */
  industry_multipliers: Record<string, Record<string, number>>;
  /** Keyed on `small` | `mid` | `large`. Never `unknown`. */
  size_multipliers: Record<string, Record<string, number>>;
  persona_role_weights: Record<string, number>;
  band_cutoffs: Record<string, number>;
  man_view_enabled: boolean;
  /** The weakest band that may join a queue; `low` is no restriction. */
  min_queue_band?: string;
  created_at: string;
}

export interface SignalType {
  id: string;
  key: string;
  label: string;
  description: string | null;
  scope: 'company' | 'contact';
  default_ttl_days: number;
  /**
   * How long a fact of this type stays worth *reading*, as against how long it
   * stays a hook — that is `default_ttl_days`. Null means the default, three
   * times the TTL. Research refuses a document older than this and extraction
   * refuses a signal dated beyond it, so a signal can no longer be stored
   * already expired.
   */
  durability_days: number | null;
  /** The number that actually applies, default resolved. Read this to show it. */
  durability_effective_days: number;
  weight: number;
  produced_by: string[];
  status: 'active' | 'paused' | 'deprecated';
  paused_at: string | null;
  deprecated_at: string | null;
  /** Signals citing this type. Zero means it can be deleted outright. */
  signal_count: number;  /** What to look for. Runs as its own search when no family is claimed. */
  search_instruction: string | null;
  /** Types sharing a label are searched once, together. */
  search_group: string | null;
  /**
   * `event` — one signal per dated occurrence. `theme` — one live reading that
   * moves forward when a newer one arrives.
   */
  kind: 'event' | 'theme';
}

/**
 * A place research reads about an account.
 *
 * Configuration now, not a closed set in code — but still served by the API and
 * never hardcoded here, for the reason that made it closed in the first place:
 * a source key nothing runs reports as a permanent coverage gap on a prospect
 * who may be perfectly well covered.
 */
export interface ResearchSource {
  id: string;
  key: string;
  label: string;
  /** The brief. What a search of this place is told to read for. */
  description: string;
  /** `search` | `fetch` | `provider` | `manual`. Only search is creatable. */
  kind: string;
  scopes: ('company' | 'contact')[];
  support_only: boolean;
  /** Overrides the global reuse window. News weekly, filings quarterly. */
  reuse_days: number | null;
  /** Shipped with the product: its key and kind cannot change. */
  builtin: boolean;
  status: string;
  /** Active signal types naming it. Zero is allowed — an ICP may add its own. */
  claimed_by: number;
  /** Reads attempted lately, and evidence rows they produced. */
  attempts: number;
  evidence: number;
  /** Read repeatedly, produced nothing. A prompt to look, not a verdict. */
  dead_weight: boolean;
}

/** Where one signal type is usually found, proposed rather than applied. */
export interface TypeSourceSuggestion {
  sources: string[];
  search_instruction: string;
  why: string;
  new_sources: { key: string; label: string; description: string; scopes: string[]; why: string }[];
}

/** The sources an ICP should read, assembled and explained. */
export interface IcpSourceSuggestions {
  sources: { key: string; for_types: string[]; why: string }[];
  new_sources: { key: string; label: string; description: string; scopes: string[]; why: string }[];
  notes: string;
}

/** A research query family. Served by the API, never hardcoded here. */
export interface QueryFamily {
  key: string;
  label: string;
  description: string;
  scopes: ('company' | 'contact')[];
  /** Can corroborate a signal but never create one on its own. */
  support_only: boolean;
  /**
   * `search` | `provider` | `manual`. Not every family is a web search:
   * `enrichment` is a metered provider waterfall whose coverage comes from the
   * verification report, and `manual` is a rep's keyboard. Neither is auto-run,
   * and neither reports "found nothing" as a coverage gap.
   */
  runner?: string;
}

/**
 * Who is *selling*. Identity only — who you sell to lives on `IcpProfile`,
 * shared across the services that sell to it.
 */
export interface OrgProfile {
  id: string;
  name: string;
  description: string | null;
  version: number;
  is_active: boolean;
  created_at: string;
}

export interface ProofPoint {
  id: string;
  service_id: string | null;
  kind: string;
  title: string;
  body: string;
  client_industry: string | null;
  client_size_band: string | null;
  metrics: Record<string, unknown> | null;
  /** Only approved claims may reach a prompt. Set on its own route, never here. */
  is_approved: boolean;
  source: string | null;
}

export interface WritingSample {
  id: string;
  channel: string;
  subject: string | null;
  body: string;
  notes: string | null;
  is_active: boolean;
}

export interface ModelOption {
  id: string;
  label: string;
  structured_output: boolean;
  effort: boolean;
  prompt_caching: boolean;
  /** frontier | balanced | economy — pick a cost tier without knowing ids. */
  tier: string;
  notes: string | null;
}

/** A vendor we ship suggestions for — not the list of vendors you may use. */
export interface ProviderInfo {
  key: string;
  label: string;
  /** llm | enrichment | outreach | crm. Decides which mandatory slot it fills. */
  kind: string;
  purpose: string;
  console_url: string;
  /** Whether an adapter exists to do this provider's actual work. */
  runnable: boolean;
  /** Whether its key can be checked against the vendor. Independent of
   *  `runnable` — a Gemini key is checkable and no stage can run on it. */
  verifiable: boolean;
  credential_types: string[];
  models: ModelOption[];
}

/** One provider's model shortlist, and everything it could have been. */
export interface ProviderAvailability {
  provider: string;
  label: string;
  runnable: boolean;
  /** Model ids a stage may be pointed at. */
  enabled: string[];
  /** Everything the catalogue knows — the tick-list. */
  catalogue: string[];
  /** Enabled ids the catalogue does not know. Vendor ids drift. */
  custom: string[];
  /** No choice made yet; the catalogue is standing in. */
  defaulted: boolean;
}

export interface ModelInUse {
  provider: string;
  model: string;
  /** Stages that would be stranded if this model were removed. */
  scenarios: string[];
}

export interface Availability {
  providers: ProviderAvailability[];
  in_use: ModelInUse[];
}

export interface LlmConfig {
  id: string;
  scenario: string;
  provider: string;
  model: string;
  effort: string;
  max_tokens: number;
  thinking_mode: string;
  output_contract: string;
  version: number;
  is_active: boolean;
  /** Derived from whether an adapter exists — never stored. */
  runnable: boolean;
}

export interface CredentialState {
  provider: string;
  label: string;
  status: string;
  last_four: string | null;
  console_url: string | null;
  last_test_code?: string | null;
  last_test_detail?: string | null;
  runnable: boolean;
  verifiable: boolean;
}

/** One mandatory external dependency. */
export interface Slot {
  kind: string;
  title: string;
  why: string;
  /** missing | unverified | ready — three different instructions to the reader. */
  state: string;
  satisfied: boolean;
  blocker: string | null;
  /** Satisfied, but something downstream will still fail. Never gates. */
  warning: string | null;
  credentials: CredentialState[];
}

export interface InstallationMode {
  id: string;
  mode: 'production' | 'demo';
  reason: string | null;
  switched_by: string | null;
  version: number;
  is_active: boolean;
}

export interface Readiness {
  /** Everything connected, outreach included. The whole-installation answer. */
  ready: boolean;
  /**
   * LLM and enrichment connected — enough to import, enrich, research,
   * qualify and strategise. **This is what the menu locks on.**
   *
   * Separate from `ready` because La Growth Machine only matters at send time.
   * Locking the whole application on it sealed an installation that could do
   * everything up to a draft.
   */
  workable: boolean;
  /** An unlocked menu means very different things in each mode. */
  mode: 'production' | 'demo';
  /** Runs that produced fixture evidence. Surfaced even in production. */
  demo_runs: number;
  slots: Slot[];
  blockers: string[];
  /** Reported even when ready — see Slot.warning. */
  warnings: string[];
  enrichment_order: string[];
  /**
   * Configuration decisions nobody has made yet — a service to sell, and an
   * ICP saying who it is for. Separate from the credential slots because a key
   * connects you to a vendor without telling it who to look for.
   */
  requirements?: string[];
  /**
   * Stored credentials belonging to no slot — a provider name the backend
   * cannot classify, which in practice means a typo. Rendered so it can be
   * deleted: every other credential reaches the screen through a slot, so an
   * unclassifiable one used to reach it not at all.
   */
  unrecognised?: CredentialState[];
}

export interface EnrichmentConfig {
  id: string;
  provider_order: string[];
  required_fields: string[];
  /** People Find contacts may propose per persona per account. */
  suggestions_per_persona?: number;
  version: number;
  is_active: boolean;
}

export interface Credential {
  id: string;
  provider: string;
  credential_type: string;
  /** Never the value — only its final four characters. */
  last_four: string | null;
  status: 'valid' | 'invalid' | 'untested' | 'expired';
  last_tested_at: string | null;
  spend_cap: number | null;
  /** Why the last test ended as it did, as a slug. See `statusLabel()`. */
  last_test_code?: string | null;
  /** The same reason in a sentence, for a tooltip. Never the value. */
  last_test_detail?: string | null;
  /** Where this provider issues keys. */
  console_url?: string | null;
}

/**
 * A kind of buyer, named once and shared by the services that sell to it.
 *
 * `definition` is `null` when no version has been written yet — distinct from
 * `{}` on purpose. A profile a service is linked to but nobody has described
 * cannot target anyone, and enrichment refuses it rather than running blind.
 */
export interface IcpProfile {
  id: string;
  name: string;
  description: string | null;
  definition: Record<string, unknown> | null;
  version: number | null;
  service_codes: string[];
  /** Account lists pointing at it. Zero means it can be deleted outright. */
  list_count: number;
}

/** The research reuse window. `version` 0 means nothing saved; the default applies. */
export interface ResearchSettings {
  id: string | null;
  version: number;
  freshness_days: number;
}

export interface Service {
  id: string;
  code: string;
  name: string;
  description: string;
  positioning_angles: string[] | null;
  /** Who signs off, broadly. The people to reach are an ICP's buyer personas. */
  economic_buyer: string | null;
  is_active: boolean;
}

@Injectable({ providedIn: 'root' })
export class ConfigService {
  private http = inject(HttpClient);
  private base = '/api/config';

  // --- prompts: what each stage is asked to do ---
  // Reads are open; writes carry the unlock token. Seeing a prompt is not the
  // risk — changing one quietly is.
  promptGate(): Observable<PromptGate> {
    return this.http.get<PromptGate>(`${this.base}/prompts/gate`);
  }
  setPromptPassword(body: {
    password: string;
    current_password?: string;
  }): Observable<PromptUnlock> {
    return this.http.post<PromptUnlock>(`${this.base}/prompts/gate`, body);
  }
  unlockPrompts(password: string): Observable<PromptUnlock> {
    return this.http.post<PromptUnlock>(`${this.base}/prompts/unlock`, { password });
  }
  listPrompts(): Observable<PromptSummary[]> {
    return this.http.get<PromptSummary[]>(`${this.base}/prompts`);
  }
  readPrompt(scenario: string): Observable<PromptDetail> {
    return this.http.get<PromptDetail>(`${this.base}/prompts/${scenario}`);
  }
  promptHistory(scenario: string): Observable<PromptVersion[]> {
    return this.http.get<PromptVersion[]>(`${this.base}/prompts/${scenario}/history`);
  }
  savePrompt(
    scenario: string,
    body: { body: string; note?: string | null },
    token: string,
  ): Observable<PromptDetail> {
    return this.http.post<PromptDetail>(`${this.base}/prompts/${scenario}`, body, {
      headers: { 'X-Admin-Token': token },
    });
  }
  resetPrompt(scenario: string, token: string): Observable<PromptDetail> {
    return this.http.post<PromptDetail>(
      `${this.base}/prompts/${scenario}/reset`,
      {},
      { headers: { 'X-Admin-Token': token } },
    );
  }
  restorePrompt(scenario: string, version: number, token: string): Observable<PromptDetail> {
    return this.http.post<PromptDetail>(
      `${this.base}/prompts/${scenario}/restore/${version}`,
      {},
      { headers: { 'X-Admin-Token': token } },
    );
  }

  // --- sales rules: PUT writes a new version, never mutates ---
  getSalesRules(): Observable<SalesRules> {
    return this.http.get<SalesRules>(`${this.base}/sales-rules`);
  }
  saveSalesRules(body: SalesRulesInput): Observable<SalesRules> {
    return this.http.put<SalesRules>(`${this.base}/sales-rules`, body);
  }
  salesRulesVersions(): Observable<SalesRules[]> {
    return this.http.get<SalesRules[]>(`${this.base}/sales-rules/versions`);
  }

  // --- scoring ---
  getScoring(): Observable<ScoringConfig> {
    return this.http.get<ScoringConfig>(`${this.base}/scoring`);
  }
  saveScoring(body: unknown): Observable<ScoringConfig> {
    return this.http.put<ScoringConfig>(`${this.base}/scoring`, body);
  }

  /** The families a signal type may claim. Static, but server-owned: a picker
   *  offering a family no agent runs produces a permanent phantom coverage gap. */
  queryFamilies(): Observable<QueryFamily[]> {
    return this.http.get<QueryFamily[]>(`${this.base}/query-families`);
  }

  researchSources(includeRetired = false): Observable<ResearchSource[]> {
    const q = includeRetired ? '?include_retired=true' : '';
    return this.http.get<ResearchSource[]>(`${this.base}/research-sources${q}`);
  }

  createResearchSource(body: unknown): Observable<ResearchSource> {
    return this.http.post<ResearchSource>(`${this.base}/research-sources`, body);
  }

  updateResearchSource(key: string, changes: unknown): Observable<ResearchSource> {
    return this.http.patch<ResearchSource>(`${this.base}/research-sources/${key}`, changes);
  }

  /**
   * Ask where one signal type would be found.
   *
   * Sent from the form rather than looked up by key, because the question is
   * most useful while the description is still being typed.
   */
  suggestSourcesForType(body: {
    key?: string;
    label: string;
    scope: string;
    description?: string | null;
  }): Observable<TypeSourceSuggestion> {
    return this.http.post<TypeSourceSuggestion>(
      `${this.base}/signal-types/suggest-sources`,
      body,
    );
  }

  /** Assemble the sources an ICP should read. Proposed, never applied. */
  suggestSourcesForIcp(profileId: string): Observable<IcpSourceSuggestions> {
    return this.http.post<IcpSourceSuggestions>(
      `${this.base}/icp-profiles/${profileId}/suggest-sources`,
      {},
    );
  }

  // --- signal types, split by scope ---
  signalTypes(scope?: 'company' | 'contact', includeDeprecated = false): Observable<SignalType[]> {
    const params: Record<string, string> = {};
    if (scope) params['scope'] = scope;
    if (includeDeprecated) params['include_deprecated'] = 'true';
    return this.http.get<SignalType[]>(`${this.base}/signal-types`, { params });
  }
  /**
   * Ask which type-owned searches read the same sources.
   *
   * A suggestion, never an application: grouping changes what every later
   * search asks for, so a person applies it.
   */
  suggestSignalTypeGroups(): Observable<{
    groups: { label: string; type_keys: string[]; why: string }[];
    ungrouped: string[];
  }> {
    return this.http.post<{
      groups: { label: string; type_keys: string[]; why: string }[];
      ungrouped: string[];
    }>(`${this.base}/signal-types/suggest-groups`, {});
  }

  createSignalType(body: unknown): Observable<SignalType> {
    return this.http.post<SignalType>(`${this.base}/signal-types`, body);
  }
  /** Tuning only — key and scope are not editable server-side. */
  updateSignalType(
    key: string,
    changes: {
      weight?: number;
      default_ttl_days?: number;
      /** `0` clears it back to the default; null in a patch means "leave alone". */
      durability_days?: number;
      produced_by?: string[];
      search_instruction?: string | null;
      search_group?: string | null;
      kind?: 'event' | 'theme';
    },
  ): Observable<SignalType> {
    return this.http.patch<SignalType>(`${this.base}/signal-types/${key}`, changes);
  }

  /** Reversible: a paused type is expected to come back. */
  pauseSignalType(key: string): Observable<SignalType> {
    return this.http.post<SignalType>(`${this.base}/signal-types/${key}/pause`, {});
  }
  resumeSignalType(key: string): Observable<SignalType> {
    return this.http.post<SignalType>(`${this.base}/signal-types/${key}/resume`, {});
  }

  /** Terminal, but non-destructive: the row and its signals stay. */
  deprecateSignalType(key: string): Observable<SignalType> {
    return this.http.post<SignalType>(`${this.base}/signal-types/${key}/deprecate`, {});
  }

  /** Only legal while `signal_count` is 0 — the server refuses otherwise. */
  deleteSignalType(key: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/signal-types/${key}`);
  }

  // --- credentials: write-only ---
  credentials(): Observable<Credential[]> {
    return this.http.get<Credential[]>(`${this.base}/credentials`);
  }
  saveCredential(body: {
    provider: string;
    credential_type: string;
    value: string;
    spend_cap?: number | null;
    console_url?: string | null;
  }): Observable<Credential> {
    return this.http.put<Credential>(`${this.base}/credentials`, body);
  }
  /** Which models this installation may point a stage at. */
  modelAvailability(): Observable<Availability> {
    return this.http.get<Availability>(`${this.base}/model-availability`);
  }

  /** Refused if it would strand a stage — the server names which. */
  saveModelAvailability(enabled: Record<string, string[]>): Observable<Availability> {
    return this.http.put<Availability>(`${this.base}/model-availability`, { enabled });
  }

  /** The vendors we ship suggestions for. Adding another is still allowed. */
  providers(): Observable<ProviderInfo[]> {
    return this.http.get<ProviderInfo[]>(`${this.base}/providers`);
  }

  mode(): Observable<InstallationMode> {
    return this.http.get<InstallationMode>(`${this.base}/mode`);
  }

  /** Leaving demo needs `acknowledge_demo_data` once fixture runs exist. */
  setMode(body: {
    mode: 'production' | 'demo';
    reason?: string | null;
    switched_by?: string | null;
    acknowledge_demo_data?: boolean;
  }): Observable<InstallationMode> {
    return this.http.put<InstallationMode>(`${this.base}/mode`, body);
  }

  /** Recomputed server-side on every call — never a stored "setup done" flag. */
  readiness(): Observable<Readiness> {
    return this.http.get<Readiness>(`${this.base}/readiness`);
  }

  enrichmentConfig(): Observable<EnrichmentConfig> {
    return this.http.get<EnrichmentConfig>(`${this.base}/enrichment`);
  }

  saveEnrichmentConfig(body: {
    provider_order: string[];
    required_fields: string[];
    suggestions_per_persona?: number;
  }): Observable<EnrichmentConfig> {
    return this.http.put<EnrichmentConfig>(`${this.base}/enrichment`, body);
  }

  /** Never refused — a credential is a secret, not a record. Removing the
   *  last one for a mandatory slot re-closes the setup gate, by design. */
  deleteCredential(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/credentials/${id}`);
  }

  testCredential(id: string): Observable<Credential> {
    return this.http.post<Credential>(`${this.base}/credentials/${id}/test`, {});
  }

  // --- services and proof points ---
  services(): Observable<Service[]> {
    return this.http.get<Service[]>(`${this.base}/services`);
  }
  createService(body: unknown): Observable<Service> {
    return this.http.post<Service>(`${this.base}/services`, body);
  }

  /** Reversible: an inactive service stops being weighed but keeps its history. */
  setServiceActive(code: string, active: boolean): Observable<Service> {
    return this.http.patch<Service>(`${this.base}/services/${code}`, null, {
      params: { active },
    });
  }
  /** How old research may be and still be reused. */
  researchSettings(): Observable<ResearchSettings> {
    return this.http.get<ResearchSettings>(`${this.base}/research-settings`);
  }
  /** A new version of the reuse window. */
  saveResearchSettings(freshness_days: number): Observable<ResearchSettings> {
    return this.http.put<ResearchSettings>(`${this.base}/research-settings`, { freshness_days });
  }

  /** Edit what a service says about itself. The code never changes. */
  updateService(
    code: string,
    body: {
      name?: string;
      description?: string;
      positioning_angles?: string[];
      economic_buyer?: string | null;
    },
  ): Observable<Service> {
    return this.http.put<Service>(`${this.base}/services/${code}`, body);
  }
  /** Only legal while nothing references it — the server refuses otherwise. */
  deleteService(code: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/services/${code}`);
  }

  proofPoints(): Observable<ProofPoint[]> {
    return this.http.get<ProofPoint[]>(`${this.base}/proof-points`);
  }
  createProofPoint(body: unknown): Observable<ProofPoint> {
    return this.http.post<ProofPoint>(`${this.base}/proof-points`, body);
  }
  /** Approval is its own act on its own route — a claim cannot arrive approved. */
  approveProofPoint(id: string): Observable<ProofPoint> {
    return this.http.post<ProofPoint>(`${this.base}/proof-points/${id}/approve`, {});
  }

  /** Stops a claim reaching any future prompt without destroying the record. */
  withdrawProofPoint(id: string): Observable<ProofPoint> {
    return this.http.post<ProofPoint>(`${this.base}/proof-points/${id}/withdraw`, {});
  }
  /** Refused once a draft quotes it — withdraw instead. */
  deleteProofPoint(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/proof-points/${id}`);
  }

  // --- org profile: PUT writes a new version ---
  /**
   * The active ICP for a service. 404 when nobody has written one — which is a
   * different fact from an empty ICP, and the two must not collapse: the first
   * blocks enrichment for this service, the second is a choice somebody made.
   */
  icpProfiles(): Observable<IcpProfile[]> {
    return this.http.get<IcpProfile[]>(`${this.base}/icp-profiles`);
  }

  /**
   * Create a profile, its first version and its service links in one call.
   *
   * One call rather than three because the links are not optional: created
   * separately, a profile could exist linked to nothing between two requests.
   */
  createIcpProfile(body: {
    name: string;
    description?: string | null;
    definition: Record<string, unknown>;
    service_codes: string[];
  }): Observable<IcpProfile> {
    return this.http.post<IcpProfile>(`${this.base}/icp-profiles`, body);
  }

  /** Activate a new version. The old one stays readable by the runs that used it. */
  saveIcpDefinition(
    id: string,
    definition: Record<string, unknown>,
  ): Observable<IcpProfile> {
    return this.http.put<IcpProfile>(`${this.base}/icp-profiles/${id}`, { definition });
  }

  /** Replace the set of services this ICP sells to. At least one required. */
  setIcpServices(id: string, service_codes: string[]): Observable<IcpProfile> {
    return this.http.put<IcpProfile>(`${this.base}/icp-profiles/${id}/services`, {
      service_codes,
    });
  }

  deleteIcpProfile(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/icp-profiles/${id}`);
  }

  getOrgProfile(): Observable<OrgProfile> {
    return this.http.get<OrgProfile>(`${this.base}/org-profile`);
  }
  saveOrgProfile(body: {
    name: string;
    description?: string | null;
  }): Observable<OrgProfile> {
    return this.http.put<OrgProfile>(`${this.base}/org-profile`, body);
  }
  orgProfileVersions(): Observable<OrgProfile[]> {
    return this.http.get<OrgProfile[]>(`${this.base}/org-profile/versions`);
  }

  // --- writing samples ---
  writingSamples(): Observable<WritingSample[]> {
    return this.http.get<WritingSample[]>(`${this.base}/writing-samples`);
  }
  createWritingSample(body: unknown): Observable<WritingSample> {
    return this.http.post<WritingSample>(`${this.base}/writing-samples`, body);
  }
  setWritingSampleActive(id: string, active: boolean): Observable<WritingSample> {
    return this.http.patch<WritingSample>(`${this.base}/writing-samples/${id}`, null, {
      params: { active },
    });
  }
  /** Unconditional: nothing stores a reference to a sample, only its text. */
  deleteWritingSample(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/writing-samples/${id}`);
  }

  // --- scoring versions ---
  scoringVersions(): Observable<ScoringConfig[]> {
    return this.http.get<ScoringConfig[]>(`${this.base}/scoring/versions`);
  }

  // --- per-stage model config ---
  llmConfigs(): Observable<LlmConfig[]> {
    return this.http.get<LlmConfig[]>(`${this.base}/llm`);
  }
  saveLlmConfig(scenario: string, body: unknown): Observable<LlmConfig> {
    return this.http.put<LlmConfig>(`${this.base}/llm/${scenario}`, body);
  }

  /** What the model calls used, by stage. Tokens — never currency. */
  llmSpend(days = 30): Observable<LlmSpend> {
    return this.http.get<LlmSpend>(`${this.base}/llm/spend`, { params: { days } });
  }
}

export interface LlmSpendRow {
  scenario: string;
  model: string;
  calls: number;
  failed: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  avg_output: number;
  /**
   * The dearest single call. It earns its column: a stage configured into
   * runaway thinking has an ordinary average and a ruinous maximum.
   */
  worst_output: number;
  avg_ms: number;
}

export interface LlmSpend {
  days: number;
  since: string;
  calls: number;
  failed: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  by_stage: LlmSpendRow[];
  note: string;
}

/**
 * Whether the prompt editor is locked, and with what.
 *
 * `configured: false` means no password has been set — the screen offers to
 * set one. It deliberately does not mean "locked": treating it that way would
 * shut the owner out of their own installation with no way back.
 */
export interface PromptGate {
  configured: boolean;
  token_header: string;
  ttl_seconds: number;
  min_password_length: number;
}

export interface PromptUnlock {
  token: string;
  ttl_seconds: number;
}

export interface PromptSummary {
  scenario: string;
  version: number | null;
  /** The first question a new admin asks: what have we changed? */
  differs_from_default: boolean;
  note: string | null;
  updated_at: string | null;
  chars: number;
  /**
   * False when the code has a stage no migration seeded. It runs on its
   * shipped text, and the screen says so rather than implying it was edited.
   */
  seeded: boolean;
}

export interface PromptVersion {
  version: number;
  is_active: boolean;
  note: string | null;
  created_at: string;
  chars: number;
  body: string;
}

export interface PromptDetail {
  scenario: string;
  body: string;
  version: number | null;
  note: string | null;
  updated_at: string | null;
  shipped_default: string;
  differs_from_default: boolean;
  /**
   * Prepended to every stage and editable by nobody. It carries the rule that
   * retrieved text is data rather than instruction, and the one that nothing
   * is asserted without a citation. Shown read-only so an admin can see what
   * their words sit beneath.
   */
  common_preamble: string;
  seeded: boolean;
}
