import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

/**
 * Everything between a qualified account and a send.
 *
 * Note what is absent: any way to choose which threads are sampled. `redraw`
 * takes no ids and `acceptSample` submits decisions for exactly the drawn set —
 * the server refuses anything else. Randomness a rep can re-roll is still
 * random; randomness a rep can hand-pick is not.
 */

export interface EvidenceRef {
  id: string;
  source_type: string;
  source_url: string | null;
  source_name: string | null;
  title: string | null;
  excerpt: string;
  observed_at: string | null;
  raw_status: string;
  reliability?: number | null;
}

export interface SignalRow {
  id: string;
  signal_type: string;
  scope: string;
  summary: string;
  business_implication: string | null;
  strength: string;
  confidence: number;
  observed_at: string;
  expires_at: string | null;
  lifecycle_state: string;
  /**
   * Set when a newer reading of an ongoing theme replaced this one. As dead as
   * expired — `drafting` refuses to cite either — so both are grouped as
   * background rather than shown beside live signals.
   */
  superseded_by: string | null;
  is_hypothesis: boolean;
  contact_id: string | null;
  contact_name: string | null;
  evidence: EvidenceRef[];
}

export interface CoverageRow {
  family: string;
  status: string;
  evidence_count: number;
  detail: string | null;
  /** What the family searched for and could not establish. */
  not_found: string[];
  /**
   * Remarks about the shape of what came back — "20 more recent entries not
   * kept" — as distinct from what could not be established. They shared a
   * field once, and a sweep that found thirty entries reported a failure.
   */
  notes?: string[];
  /** The passages this family found in this run. */
  evidence: EvidenceRef[];
  /** When this family was last answered — families can come from different runs. */
  researched_at: string | null;
  /** The person this row is about; null for the company. */
  contact_id: string | null;
  contact_name: string | null;
  contact_title: string | null;
}

export interface DimensionRow {
  dimension: string;
  score: number;
  reason: string;
  basis: string;
  evidence_ids: string[];
}

export interface QualificationView {
  id: string;
  priority_score: number;
  priority_band: string;
  scoring_config_version: number;
  dimensions: DimensionRow[];
  man: Record<string, string> | null;
  /** The same assessment read for each ICP — fit and buyer recomputed, no AI call. */
  by_icp?: IcpScoreRow[];
}

export interface ThreadView {
  id: string;
  contact_id: string;
  contact_name: string;
  contact_title: string | null;
  weight: number;
  rank: number;
  thread_status: string;
  problem_hypothesis: string;
  trigger_summary: string;
  positioning: string;
  cta: string;
  channel_sequence: string[];
  start_offset_days: number;
  confidence: number | null;
}

export interface MatrixCell {
  contact_id: string;
  contact_name: string;
  service_code: string;
  weight: number;
  rationale: string | null;
}

export interface StrategyView {
  id: string;
  version: number;
  status: string;
  threads: ThreadView[];
  /** The full matrix, including combinations that never activated. */
  matrix: MatrixCell[];
}

export interface Intelligence {
  account_id: string;
  account_name: string;
  domain: string | null;
  signals: SignalRow[];
  coverage: CoverageRow[];
  /** The model's reading of the signals: themes, what changed, what is unknown. */
  context_narrative: {
    summary?: string;
    what_changed?: string | null;
    themes?: { label: string; reading: string; weight?: string }[];
    unknowns?: { question: string; why_it_matters: string; would_be_answered_by?: string | null }[];
  } | null;
  /** From the coverage run, stored before passages recorded their family. */
  unattributed_evidence: EvidenceRef[];
  context_version: number | null;
  qualification: QualificationView | null;
  /** Each campaign this company's people are in — strategy and drafts live there. */
  outreach: OutreachEntry[];
}

export interface Queue {
  id: string;
  label: string;
  description: string | null;
  status: string;
  locked_at: string | null;
  account_count: number;
  /** People chosen for the queue by name. */
  contact_count?: number;
  promoted_to_campaign_id: string | null;
  cloned_from_queue_id: string | null;
  /** The service everyone in it is approached about, and the ICP it is built for. */
  service_id?: string | null;
  service_code?: string | null;
  icp_profile_id?: string | null;
  icp_name?: string | null;
  icp_version?: number | null;
}

/** One person in a campaign, against its service and ICP. */
export interface DraftBatch {
  drafted: number;
  failed: number;
  seconds: number;
  /** sequence id → why it could not be drafted. */
  errors: Record<string, string>;
}

export interface StrategyBatch {
  built: number;
  failed: number;
  /** How long the whole batch took, server-side. */
  seconds: number;
  results: StrategyBuild[];
  /** account id → why it failed. */
  errors: Record<string, string>;
}

export interface CampaignPerson {
  sequence_id: string;
  contact_id: string;
  full_name: string;
  title: string | null;
  account_id: string;
  account_name: string;
  reachable: boolean;
  weight: number;
  /** The sales rules' answer: pursue, below_threshold, over_limit or not_reachable. */
  default_decision: string;
  decision_detail: string;
  live_signals: number;
  expired_signals: number;
  qualification_band: string | null;
  qualification_score: number | null;
  gate: string;
  gate_detail: string;
  strategy_status: string | null;
  chosen_by_rep: boolean;
  without_live_trigger: boolean;
  problem_hypothesis: string | null;
  /**
   * Withdrawn from this campaign — kept visible and greyed, with the reason.
   * Not a score an override can undo: reinstating is its own act.
   */
  withdrawn?: boolean;
  withdraw_reason?: string | null;
  /** Where their cadence drafts stand, and how many touches exist. */
  draft_state: string;
  draft_state_label: string;
  touch_count: number;
  edited: boolean;
}

export interface CampaignPeople {
  ready: boolean;
  blocked: string | null;
  service_code: string | null;
  icp_name: string | null;
  icp_version: number | null;
  threshold: number | null;
  cap: number | null;
  people: CampaignPerson[];
}

export interface StrategyBuild {
  account_id: string;
  name: string;
  built: boolean;
  version: number | null;
  pursued: string[];
  overridden: string[];
  without_trigger: string[];
  excluded: { name: string; reason: string }[];
  note: string;
}

export interface QueueMember {
  account_id: string;
  account_name: string;
  domain: string | null;
  source_list_id: string | null;
  priority_score: number | null;
  priority_band: string | null;
}

/** A person chosen for a queue — campaigns send to people. */
export interface QueueContact {
  contact_id: string;
  full_name: string;
  title: string | null;
  account_id: string;
  account_name: string;
  email: string | null;
  email_status: string | null;
  linkedin_url: string | null;
  /** `email` (verified), `LinkedIn`, or `not reachable`. */
  reachable_by: string;
  source_list_id: string | null;
  /** The company's rating, read for the ICP this screen works for. */
  qualification_score?: number | null;
  qualification_band?: string | null;
  icp_name?: string | null;
  gate?: string;
  gate_detail?: string;
}

export interface Campaign {
  id: string;
  label: string;
  status: string;
  cadence_shape_key: string | null;
}

export interface LgmCampaignOption {
  id: string;
  name: string;
  status: string | null;
  audience_id: string | null;
  audience_name: string | null;
  audience_size: number | null;
}

export interface ShapeCheck {
  key: string;
  /** The registration's own id, for a caller that just created one. */
  shape_id: string | null;
  /** True when the live campaign agrees with what is registered here. */
  sound: boolean;
  /** False when there was no key to check with, or LGM could not be reached. */
  checked: boolean;
  lgm_status: string | null;
  audience_name: string | null;
  steps: number;
  channels: string[];
  findings: string[];
  detail: string;
}

/** The blockers among a shape's notes — warnings are not blockers. */
export function blockersOf(shape: { blocks: { severity?: string }[] }): unknown[] {
  return shape.blocks.filter((b) => (b.severity ?? 'block') === 'block');
}

export interface CadenceShapeView {
  id: string;
  key: string;
  label: string;
  lgm_campaign_id: string;
  touch_count: number;
  /** Null for everything registered since timing became LGM's. */
  span_days: number | null;
  attributes_used: number;
  lgm_status: string | null;
  /** The LGM audience this shape writes leads into — enrolment, over there. */
  lgm_audience_name: string | null;
  verified_at: string | null;
  verified_by: string | null;
  lgm_updated_at: string | null;
  durable_from_step: number | null;
  active: boolean;
  /**
   * Only entries with `severity: 'block'` stop an enrolment. A `'warn'` states
   * what happens next — a campaign never launched in LGM takes its people and
   * holds them until somebody launches it there.
   */
  blocks: { reason: string; detail: string; severity?: string }[];
}

export interface ThreadCard {
  sequence_id: string;
  contact_name: string;
  contact_title: string | null;
  account_name: string;
  problem_hypothesis: string;
  thread_status: string;
  confidence: number | null;
  touch_count: number;
  approved: boolean;
  flag_reasons: string[];
  in_sample: boolean;
}

export interface ApprovalView {
  campaign_id: string;
  campaign_label: string;
  campaign_status: string;
  /** Whether deleting is allowed — the server re-checks on the call itself. */
  deletable: boolean;
  sample_rate: number;
  /** Never sampled — every one is read individually. */
  flagged: ThreadCard[];
  clean: ThreadCard[];
  sample_size: number;
  stratum_size: number;
  sample_id: string | null;
  escalated: boolean;
  /** Why the campaign is smaller than the queue that fed it, if it is. */
  promotion_notes: string[];
  /** People not yet saved for approval, and where their drafts stand. */
  /** Not saved for approval yet — the people blocking the gate. */
  waiting?: WaitingThread[];
}

export interface OutreachEvent {
  id: string;
  occurred_at: string;
  event_type: string;
  channel: string | null;
  direction: string | null;
  preview: string | null;
  contact_id: string | null;
  contact_name: string | null;
  account_name: string | null;
  sequence_id: string | null;
  /** `webhook` or `poll`, and how the person was matched. */
  received_via: string;
  matched_by: string | null;
}

export interface CampaignActivity {
  campaign_id: string;
  sent: number;
  received: number;
  people_replied: number;
  last_event_at: string | null;
  events: OutreachEvent[];
}

export interface SyncReport {
  ran: boolean;
  blocked: string | null;
  stored: number;
  duplicates: number;
  unmatched: number;
  replies: number;
  orphans: string[];
  since: string | null;
}

export interface WaitingThread {
  sequence_id: string;
  contact_id: string | null;
  name: string;
  account_name: string;
  /** not drafted, drafted — not saved, strategy needed, withdrawn — <reason>… */
  state: string;
  touch_count: number;
  /** Taken out of this campaign. Shown greyed; counts towards nothing. */
  withdrawn?: boolean;
}

export interface PreflightCheck {
  key: string;
  label: string;
  passed: boolean;
  detail: string;
  subjects: string[];
  /** Who the check is about — the screen links straight to them. */
  people: CheckPerson[];
}

export interface CheckPerson {
  sequence_id: string;
  contact_id: string | null;
  name: string;
}

export interface PreflightView {
  campaign_id: string;
  passed: boolean;
  checks: PreflightCheck[];
}

export interface TouchView {
  step_no: number;
  /** Null when LGM owns the schedule, which is everything drafted now. */
  day_offset: number | null;
  channel: string;
  purpose: string | null;
  subject: string | null;
  body: string;
  signal_dependence: string;
  status: string;
  content_sync_status: string;
  version: number;
  /** arc, regeneration or rep_edit. */
  generated_as: string | null;

  /**
   * Where this content lands in LGM. The binding is the whole integration and
   * used to be invisible — a rep could not tell which slot a draft occupied,
   * nor whether a subject line would appear at all.
   */
  lgm_attribute: string | null;
  lgm_attribute_label: string | null;
  subject_attribute: string | null;
  subject_attribute_label: string | null;
  /** False for every LinkedIn step, and for an email whose subject is fixed. */
  subject_allowed: boolean;
  /**
   * The channel LGM runs this step on — the one that decides what sends.
   * `channel` is the model's proposal and the two can disagree, so this is
   * shown in preference to it.
   */
  lgm_channel: string | null;
  /**
   * Where this step sits in the LGM campaign, and its name there. A campaign's
   * own steps include profile visits and connection requests that carry no
   * copy, so step 1 here is rarely position 1 over there — and a name like
   * "Not Accepted - Email" says this is a branch, not a follow-up.
   */
  lgm_position: number | null;
  lgm_step_name: string | null;
}

export interface ArcView {
  sequence_id: string;
  contact_name: string;
  account_name: string;
  problem_hypothesis: string;
  positioning: string;
  cta: string;
  trigger_summary: string;
  status: string;
  approved: boolean;
  touches: TouchView[];
  contact_id: string | null;
  campaign_id: string | null;
  cadence_label: string | null;
  cadence_touches: number | null;
  cadence_days: number | null;
  /** Slots this cadence occupies, out of LGM's twenty per lead. */
  attributes_used: number;
  attribute_budget: number;
  has_strategy: boolean;
  edited: boolean;
  /** strategy_needed, not_drafted, drafted, saved, approved or enrolled. */
  state: string;
  state_label: string;
}

export interface IcpScoreRow {
  icp_profile_id: string;
  icp_name: string;
  icp_version: number;
  priority_score: number;
  priority_band: string;
  fit: number;
  buyer: number;
}

export interface OutreachEntry {
  campaign_id: string;
  label: string;
  status: string;
  service_code: string | null;
  icp_name: string | null;
  priority_score: number | null;
  priority_band: string | null;
  people: {
    contact_id: string;
    full_name: string;
    title: string | null;
    sequence_id: string;
    strategy: string;
    problem_hypothesis: string | null;
    drafts: string;
  }[];
}

export interface DraftRow {
  sequence_id: string;
  contact_id: string;
  full_name: string;
  title: string | null;
  account_id: string;
  account_name: string;
  cadence_key: string | null;
  cadence_label: string | null;
  cadence_touches: number | null;
  cadence_days: number | null;
  has_strategy: boolean;
  touch_count: number;
  edited: boolean;
  state: string;
  state_label: string;
  status: string;
  qualification_score: number | null;
  qualification_band: string | null;
  gate: string;
  gate_detail: string;
}

export interface DraftVersion {
  version: number;
  subject: string | null;
  body: string;
  generated_as: string;
  regenerated_reason: string | null;
  model: string | null;
  is_current: boolean;
  created_at: string | null;
}

export interface PersonDetail {
  person: CampaignPerson;
  service_code: string | null;
  icp_name: string | null;
  icp_version: number | null;
  threshold: number | null;
  cap: number | null;
  score: {
    icp_name: string;
    icp_version: number;
    priority_score: number;
    priority_band: string;
    scoring_config_version: number;
    dimensions: { dimension: string; score: number; reason: string; basis: string }[];
  } | null;
  strategy: {
    problem_hypothesis: string;
    trigger_summary: string;
    positioning: string;
    channel_sequence: string[];
    cta: string;
    avoid_list: string[];
    confidence: number | null;
    thread_status: string;
    rank: number;
    start_offset_days: number;
    weight: number;
    chosen_by_rep: boolean;
    without_live_trigger: boolean;
  } | null;
  trigger_signals: { id: string; summary: string; observed_at: string | null; expires_at: string | null }[];
  versions: { version: number; status: string; built_at: string | null; argued_for_this_person: boolean }[];
}

@Injectable({ providedIn: 'root' })
export class PipelineService {
  private http = inject(HttpClient);

  intelligence(accountId: string): Observable<Intelligence> {
    return this.http.get<Intelligence>(`/api/accounts/${accountId}/intelligence`);
  }

  /**
   * Store what a rep saw — a LinkedIn post, a profile line — as attributed
   * evidence. Research never opens LinkedIn; this is how it gets in.
   */
  pasteEvidence(
    accountId: string,
    body: { text: string; url: string | null; contact_id: string | null; observed_at: string | null },
  ): Observable<{ evidence: EvidenceRef; dated_from: 'given' | 'post link' | 'unknown' }> {
    return this.http.post<{ evidence: EvidenceRef; dated_from: 'given' | 'post link' | 'unknown' }>(
      `/api/accounts/${accountId}/pasted-evidence`,
      body,
    );
  }

  // --- queues ---
  queues(): Observable<Queue[]> {
    return this.http.get<Queue[]>('/api/queues');
  }
  createQueue(body: {
    label: string;
    description?: string | null;
    service_id?: string | null;
    icp_profile_id?: string | null;
  }) {
    return this.http.post<{ id: string }>('/api/queues', body);
  }

  // --- a campaign's people: qualification and strategy for its service and ICP ---
  campaignPeople(campaignId: string): Observable<CampaignPeople> {
    return this.http.get<CampaignPeople>(`/api/campaigns/${campaignId}/people`);
  }
  setCampaignTargets(campaignId: string, body: { service_id: string; icp_profile_id: string }) {
    return this.http.post<CampaignPeople>(`/api/campaigns/${campaignId}/targets`, body);
  }
  personDetail(campaignId: string, contactId: string): Observable<PersonDetail> {
    return this.http.get<PersonDetail>(`/api/campaigns/${campaignId}/people/${contactId}`);
  }

  // --- cadence drafts ---
  campaignDrafts(campaignId: string): Observable<DraftRow[]> {
    return this.http.get<DraftRow[]>(`/api/campaigns/${campaignId}/drafts`);
  }
  /** One AI call: every touch of the person's cadence, from their strategy. */
  writeDrafts(sequenceId: string): Observable<ArcView> {
    return this.http.post<ArcView>(`/api/sequences/${sequenceId}/drafts/write`, {});
  }
  /** Saved as a new version; a saved or approved cadence returns to drafting. */
  editTouch(sequenceId: string, stepNo: number, body: { subject: string | null; body: string }): Observable<ArcView> {
    return this.http.put<ArcView>(`/api/sequences/${sequenceId}/touches/${stepNo}`, body);
  }
  /**
   * Take one person out of a campaign before anything is sent.
   *
   * Not a delete: the sequence, its drafts and the strategy all stay. Refused
   * once enrolled — the lever there is stopping the sequence.
   */
  /** What LGM has reported for this campaign — sends, replies, status changes. */
  campaignActivity(campaignId: string): Observable<CampaignActivity> {
    return this.http.get<CampaignActivity>(`/api/campaigns/${campaignId}/activity`);
  }

  /**
   * Pull everything LGM has since the last event we hold.
   *
   * The webhook pushes replies as they happen where a public URL exists; this
   * is the fallback and the reconciler, and it costs nothing but a few calls.
   */
  syncCampaign(campaignId: string): Observable<SyncReport> {
    return this.http.post<SyncReport>(`/api/campaigns/${campaignId}/sync`, {});
  }

  withdrawFromCampaign(sequenceId: string, reason: string) {
    return this.http.post<{ withdrawn: boolean; reason: string }>(
      `/api/sequences/${sequenceId}/withdraw`, { reason },
    );
  }

  /** Put a withdrawn person back. Their drafts survived; their approval did not. */
  reinstateIntoCampaign(sequenceId: string) {
    return this.http.post<{ withdrawn: boolean }>(`/api/sequences/${sequenceId}/reinstate`, {});
  }

  saveDrafts(sequenceId: string): Observable<ArcView> {
    return this.http.post<ArcView>(`/api/sequences/${sequenceId}/save`, {});
  }
  touchVersions(sequenceId: string, stepNo: number): Observable<DraftVersion[]> {
    return this.http.get<DraftVersion[]>(`/api/sequences/${sequenceId}/touches/${stepNo}/versions`);
  }
  /**
   * Several companies in one request, run concurrently on the server.
   *
   * The browser used to issue these one at a time so a progress line could
   * say "3 of 8". Honest, and unusable at scale: sixty companies meant sixty
   * calls end to end before drafting had begun.
   */
  /** Several people drafted in one request, concurrently on the server. */
  writeDraftsBatch(campaignId: string, sequenceIds: string[]): Observable<DraftBatch> {
    return this.http.post<DraftBatch>(`/api/campaigns/${campaignId}/drafts/write-many`, {
      sequence_ids: sequenceIds,
    });
  }

  buildCampaignStrategyBatch(
    campaignId: string,
    body: { account_ids: string[]; pursue_anyway: string[]; allow_without_signal: string[] },
  ): Observable<StrategyBatch> {
    return this.http.post<StrategyBatch>(
      `/api/campaigns/${campaignId}/strategy/batch`,
      body,
    );
  }

  buildCampaignStrategy(
    campaignId: string,
    body: { account_id: string; pursue_anyway: string[]; allow_without_signal: string[] },
  ): Observable<StrategyBuild> {
    return this.http.post<StrategyBuild>(`/api/campaigns/${campaignId}/strategy`, body);
  }
  queueMembers(queueId: string): Observable<QueueMember[]> {
    return this.http.get<QueueMember[]>(`/api/queues/${queueId}/members`);
  }
  /**
   * `sourceListId` is a provenance stamp with no behaviour — it records where
   * an account came from and is nullable so it survives that list being
   * deleted.
   */
  addQueueMember(queueId: string, accountId: string, sourceListId?: string | null) {
    return this.http.post<{ added: boolean }>(`/api/queues/${queueId}/members`, {
      account_id: accountId,
      source_list_id: sourceListId ?? null,
    });
  }
  removeQueueMember(queueId: string, accountId: string): Observable<void> {
    return this.http.delete<void>(`/api/queues/${queueId}/members/${accountId}`);
  }

  queueContacts(queueId: string): Observable<QueueContact[]> {
    return this.http.get<QueueContact[]>(`/api/queues/${queueId}/contacts`);
  }

  /** Each refusal is named: a person needs a verified email or LinkedIn. */
  addQueueContacts(
    queueId: string,
    contactIds: string[],
    sourceListId: string | null,
  ): Observable<{ added: number; already: number; refused: { contact_id: string; reason: string }[] }> {
    return this.http.post<{ added: number; already: number; refused: { contact_id: string; reason: string }[] }>(
      `/api/queues/${queueId}/contacts/bulk`,
      { contact_ids: contactIds, source_list_id: sourceListId },
    );
  }

  removeQueueContact(queueId: string, contactId: string): Observable<void> {
    return this.http.delete<void>(`/api/queues/${queueId}/contacts/${contactId}`);
  }
  /** Only legal while nothing has reached LGM. The server is the authority. */
  deleteCampaign(campaignId: string): Observable<void> {
    return this.http.delete<void>(`/api/campaigns/${campaignId}`);
  }

  /** Only legal while the queue is a draft — a promoted one is a record. */
  deleteQueue(queueId: string): Observable<void> {
    return this.http.delete<void>(`/api/queues/${queueId}`);
  }

  /** The only way to get an editable copy of a promoted queue. */
  cloneQueue(queueId: string, label: string) {
    return this.http.post<{ id: string }>(`/api/queues/${queueId}/clone`, { label });
  }

  // --- campaigns ---
  campaigns(): Observable<Campaign[]> {
    return this.http.get<Campaign[]>('/api/campaigns');
  }
  /**
   * Locks every source queue, permanently, and copies their members' strategy
   * threads in as sequences. `label` is optional — it defaults to the queue's
   * own name so the work keeps one identity across the boundary.
   */
  promote(body: { label?: string | null; queue_ids: string[]; cadence_shape_id?: string | null }) {
    return this.http.post<{
      id: string;
      label: string;
      sequences: number;
      notes: string[];
    }>('/api/campaigns', body);
  }
  /**
   * Registered shapes.
   *
   * `live` asks LGM whether each registered campaign still exists there before
   * answering — a campaign deleted in LGM leaves a row here that looks
   * verified and healthy, and nothing stored can tell you it has gone. Every
   * screen that *picks* a cadence passes it; one that merely lists them need
   * not.
   */
  /**
   * Move a campaign to a different registered cadence.
   *
   * Refused once anything has been written to LGM, and refused when the steps
   * would not line up. For the case where an LGM campaign is deleted and
   * rebuilt: the registration dies, the approved drafts behind it do not.
   */
  changeCadence(campaignId: string, cadenceShapeId: string) {
    return this.http.patch<{
      changed: boolean;
      touches_remapped: number;
      sequences: number;
      detail: string;
    }>(`/api/campaigns/${campaignId}/cadence`, { cadence_shape_id: cadenceShapeId });
  }

  cadenceShapes(live = false): Observable<CadenceShapeView[]> {
    return this.http.get<CadenceShapeView[]>(
      `/api/cadence-shapes${live ? '?live=true' : ''}`,
    );
  }

  /**
   * Check a registered shape against the live LGM campaign.
   *
   * Reads the campaign and its step templates: the templates name the
   * attributes each step actually sends, so a map pointing our copy at an
   * attribute nothing reads is caught here rather than by a prospect.
   */
  /**
   * Point a shape at the real LGM campaign and audience.
   *
   * Registration only — the steps and their timing come from LGM. Changing the
   * campaign id clears the verification: what the new id's steps send is
   * unknown until somebody checks.
   */
  updateCadenceShape(
    key: string,
    body: { lgm_campaign_id?: string; lgm_audience_name?: string; active?: boolean },
  ): Observable<CadenceShapeView> {
    return this.http.patch<CadenceShapeView>(`/api/cadence-shapes/${encodeURIComponent(key)}`, body);
  }

  /**
   * The campaigns in the connected LGM account.
   *
   * Empty when no key is stored, and the registration screen then falls back
   * to typing an id — a 24-character hex string nobody should have to copy by
   * eye when the account can be asked.
   */
  lgmCampaigns(): Observable<LgmCampaignOption[]> {
    return this.http.get<LgmCampaignOption[]>('/api/lgm/campaigns');
  }

  /**
   * Remove a registration nothing has used.
   *
   * Refused by the server once a campaign or sequence points at it: what a
   * person actually received has to stay answerable.
   */
  deleteCadenceShape(key: string) {
    return this.http.delete<void>(`/api/cadence-shapes/${encodeURIComponent(key)}`);
  }

  /**
   * Register an LGM campaign as a cadence shape.
   *
   * The steps come from LGM — touch count and the attribute each step sends
   * are read from its templates, never typed — and so is the schedule, in the
   * sense that LGM keeps it and never tells us. Nothing about timing is sent.
   */
  createCadenceShape(body: {
    lgm_campaign_id: string;
    label: string;
  }): Observable<ShapeCheck> {
    return this.http.post<ShapeCheck>('/api/cadence-shapes', body);
  }

  /**
   * Give this shape's LGM campaign an audience, creating it if needed.
   *
   * A campaign with no audience cannot enrol anybody — membership of the
   * audience is the enrolment — and LGM only allows one to be set before the
   * campaign's first launch.
   */
  attachAudience(key: string, name?: string): Observable<ShapeCheck> {
    return this.http.post<ShapeCheck>(
      `/api/cadence-shapes/${encodeURIComponent(key)}/audience`,
      name ? { name } : {},
    );
  }

  verifyCadenceShape(key: string): Observable<ShapeCheck> {
    return this.http.post<ShapeCheck>(`/api/cadence-shapes/${encodeURIComponent(key)}/verify`, {});
  }

  // --- approval ---
  approval(campaignId: string): Observable<ApprovalView> {
    return this.http.get<ApprovalView>(`/api/campaigns/${campaignId}/approval`);
  }
  /** Server-side draw. Takes no ids — a rep may re-roll but never choose. */
  redraw(campaignId: string): Observable<ApprovalView> {
    return this.http.post<ApprovalView>(`/api/campaigns/${campaignId}/approval/redraw`, {});
  }
  acceptSample(campaignId: string, decisions: Record<string, string>) {
    return this.http.post<{ sampled: number; inherited: number }>(
      `/api/campaigns/${campaignId}/approval/accept-sample`,
      { decisions },
    );
  }
  decide(sequenceId: string, body: { decision: string; reject_reason?: string; comment?: string }) {
    return this.http.post<{ ok: boolean }>(`/api/sequences/${sequenceId}/decision`, body);
  }
  arc(sequenceId: string): Observable<ArcView> {
    return this.http.get<ArcView>(`/api/sequences/${sequenceId}/arc`);
  }

  // --- execution ---
  preflight(campaignId: string): Observable<PreflightView> {
    return this.http.get<PreflightView>(`/api/campaigns/${campaignId}/preflight`);
  }
  /**
   * Irreversible: after this the copy is frozen on the LGM lead.
   *
   * `awaiting_launch` means the people and their copy are in the LGM
   * audience and the campaign there has never been launched, so nothing is
   * sending yet — LGM will not launch an empty campaign, so this write is
   * what makes that launch possible.
   */
  execute(campaignId: string) {
    return this.http.post<{
      enrolled: string[];
      failed: Record<string, string>;
      skipped: Record<string, string>;
      awaiting_launch: boolean;
      audience: string | null;
    }>(`/api/campaigns/${campaignId}/execute`, {});
  }
  stopSequence(sequenceId: string, reason = 'manual') {
    return this.http.post<{ status: string }>(`/api/sequences/${sequenceId}/stop`, null, {
      params: { reason },
    });
  }
  stopCampaign(campaignId: string, reason = 'manual') {
    return this.http.post<{ stopped: number }>(`/api/campaigns/${campaignId}/stop`, null, {
      params: { reason },
    });
  }
}
