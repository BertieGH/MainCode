import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

/**
 * Sales prep — what a rep needs before a call, one contact at a time.
 *
 * The types here mirror the API exactly, including the parts that look
 * redundant and are not. Three of them carry most of the screen's value:
 *
 * - `days: number | null` on every freshness entry. `null` is "never", `0` is
 *   "today", and rendering both the same tells a rep research is current when
 *   nobody has looked.
 * - `unassessed` beside `assessed_average`. A dimension scored with nothing to
 *   go on is an absence, not a low score, and the difference decides whether a
 *   rep researches the account or walks away from it.
 * - `unobservable` and `unobservable_why`. A zero we cannot see behind is not
 *   a zero we measured.
 */

export interface Freshness {
  kind: 'research' | 'signals' | 'engagement';
  /** Null means it has never happened — not zero days ago. */
  days: number | null;
  at: string | null;
  detail: string;
}

export interface Engagement {
  /** The furthest rung actually reached. Never inferred from an earlier one. */
  reached: string | null;
  counts: Record<string, number>;
  unobservable: string[];
  /**
   * Why, for rungs that will never be observable rather than merely not yet.
   * `delivered` is permanently here: LGM reports messages sent and received
   * and never delivery.
   */
  unobservable_why: Record<string, string>;
  detail: string;
}

export interface PrepDimension {
  dimension: string;
  score: number;
  /** `evidence`, `contacts`, `outreach`, `no_evidence`, `unknown`. */
  basis: string;
  reason: string;
  evidence_count: number;
}

export interface PrepQualification {
  priority_score: number;
  priority_band: string;
  scoring_config_version: number;
  dimensions: PrepDimension[];
  man: Record<string, string | null>;
  /** The average over dimensions the scorer could actually assess. */
  assessed_average: number | null;
  /** Dimensions it had nothing to go on for. Absences, not low scores. */
  unassessed: string[];
}

export interface SignalEvidence {
  id: string;
  source_name: string | null;
  source_url: string | null;
  excerpt: string;
  /** When the source says it happened. */
  observed_at: string | null;
  /** When we read it. A stale fact can be freshly retrieved. */
  retrieved_at: string | null;
  reliability: number | null;
}

export interface PrepSignal {
  id: string;
  signal_type: string;
  scope: string;
  summary: string;
  business_implication: string | null;
  strength: string;
  /** How reliably the source supports the fact — not how good the idea is. */
  evidence_confidence: number;
  observed_at: string | null;
  expires_at: string | null;
  lifecycle_state: string;
  is_hypothesis: boolean;
  age_days: number | null;
  expires_in_days: number | null;
  evidence_count: number;
  sources: string[];
  evidence: SignalEvidence[];
  /**
   * Why this signal matters here, derived from what cites it — the strategy
   * names its trigger, the scorer names the evidence each dimension used.
   * Null means nothing cites it, which is worth seeing on its own.
   */
  relevance: string | null;
  /** What a rep said about it, if anything. */
  rep_verdict: string | null;
}

export interface PrepThread {
  id: string;
  thread_status: string;
  problem_hypothesis: string;
  trigger_summary: string;
  positioning: string;
  cta: string;
  channel_sequence: string[];
  /** How well the approach fits the context. Not whether the problem is real. */
  strategy_confidence: number | null;
  without_live_trigger: boolean;
  avoid_list: string[];
}

export interface PrepProof {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  metrics: Record<string, unknown>;
  /** False means it may describe a capability but must not claim a result. */
  has_metric: boolean;
}

export interface BriefOpening {
  label: string;
  words: string;
  use_when: string;
  why_it_works: string;
}

export interface BriefQuestion {
  question: string;
  listening_for: string;
  dimension: string | null;
  /** What the answer changes. A question that changes nothing is cut. */
  changes: string;
  branches: string[];
}

export interface BriefObjection {
  objection: string;
  pre_empt: string;
  likelihood: string;
  /** `observed` only if the prospect actually said it. */
  kind: 'anticipated' | 'observed';
  follow_up: string | null;
}

export interface BriefNextStep {
  condition: string;
  action: string;
}

export interface Brief {
  /** Named for what it is, not for what sales calls it — see the contract. */
  what_to_find_out: string;
  what_not_to_attempt: string | null;
  /** Required: the hypothesis, named as a hypothesis. */
  problem_is_unproven: string;
  openings: BriefOpening[];
  listen_for: string[];
  next_steps: BriefNextStep[];
  what_we_know: string[];
  what_we_suspect: string[];
  what_we_do_not_know: string[];
  /** A trap, not a gap — what the rep must not treat as true. */
  do_not_assume: string[];
  elevator_pitch: string;
  pitch_structure: Record<string, string>;
  discovery_questions: BriefQuestion[];
  objections: BriefObjection[];
  already_said: string[];
  their_replies: string[];
  open_questions: string[];
}

export interface LastRun {
  at: string | null;
  status: string | null;
  planned: number;
  ran: number;
  empty: number;
  failed: number;
  evidence: number;
}

export interface Prep {
  contact_id: string;
  contact_name: string;
  title: string | null;
  seniority: string | null;
  persona_role: string | null;
  buying_role: string | null;
  /** Where the persona came from: recorded, inferred, or not established. */
  persona_basis: string;
  email_status: string | null;
  do_not_contact: boolean;
  do_not_contact_reason: string | null;
  linkedin_url: string | null;

  account_id: string;
  account_name: string;
  domain: string | null;
  industry: string | null;
  employee_count: number | null;

  freshness: Freshness[];
  engagement: Engagement;
  qualification: PrepQualification | null;
  signals: PrepSignal[];
  thread: PrepThread | null;
  proof: PrepProof[];
  brief: Brief | null;
  brief_id: string | null;
  brief_generated_at: string | null;
  /** The mode the stored brief was written in, which can differ from `mode`. */
  brief_mode: string | null;
  /**
   * Something has happened since the brief was written. Not wrong — older
   * than the facts beside it, which is cheaper to say than to regenerate on
   * every view.
   */
  brief_is_stale: boolean;
  hypothesis_verdict: string | null;
  outcome: string | null;
  rep_note: string | null;
  /** What the last research run actually did, shown before a refresh is bought. */
  last_run: LastRun | null;
  list_ids: string[];
  /** Decided from the engagement ladder, not chosen by a rep. */
  mode: 'pre_engagement' | 'engagement_aware';
}

export interface GeneratedBrief {
  prep_id: string;
  mode: string;
  brief: Brief;
  generated_at: string;
}

export interface PrepRow {
  contact_id: string;
  contact_name: string;
  title: string | null;
  persona_role: string | null;
  account_id: string;
  account_name: string;
  why_now: string;
  /** `signal`, `thread`, `no_trigger`, or `none`. */
  why_now_kind: string;
  research_days: number | null;
  engagement: string | null;
  has_thread: boolean;
  do_not_contact: boolean;
}

export interface PrepIndex {
  queue: PrepRow[];
  /**
   * Set when the queue is empty for a structural reason rather than because
   * nothing qualifies. "No event can arrive yet" is a build state; "nobody has
   * replied" is a sales fact, and the screen must not show one as the other.
   */
  queue_blocked: string | null;
  results: PrepRow[];
  total: number;
}

@Injectable({ providedIn: 'root' })
export class PrepService {
  private http = inject(HttpClient);

  index(q?: string): Observable<PrepIndex> {
    const query = q?.trim() ? `?q=${encodeURIComponent(q.trim())}` : '';
    return this.http.get<PrepIndex>(`/api/prep${query}`);
  }

  forContact(contactId: string): Observable<Prep> {
    return this.http.get<Prep>(`/api/prep/${contactId}`);
  }

  /** One contact, on demand. Never batched — see the API docstring. */
  generate(contactId: string): Observable<GeneratedBrief> {
    return this.http.post<GeneratedBrief>(`/api/prep/${contactId}/generate`, {});
  }

  /**
   * Re-run research for this account only, with the cost stated first.
   *
   * The list decides which ICPs say what to look for. With exactly one the
   * route resolves it; with several it refuses rather than picking, because
   * researching against the wrong ICP succeeds and is wrong.
   */
  refresh(accountId: string, listId?: string): Observable<unknown> {
    const q = listId ? `?list_id=${listId}` : '';
    return this.http.post(`/api/accounts/${accountId}/run-research${q}`, {});
  }

  /**
   * What a rep saw, stored as attributed evidence. Research never opens
   * LinkedIn; this is how a post or a profile line gets in.
   */
  addIntel(
    accountId: string,
    body: { text: string; url?: string | null; contact_id?: string },
  ): Observable<unknown> {
    return this.http.post(`/api/accounts/${accountId}/pasted-evidence`, body);
  }

  /**
   * What a rep says about a signal, kept where evaluations are kept.
   *
   * `outdated` and `inaccurate` stay apart: one says the refresh cadence is
   * wrong, the other that the reading is.
   */
  judgeSignal(signalId: string, verdict: string, note?: string) {
    return this.http.post(`/api/prep/signals/${signalId}/verdict`, { verdict, note });
  }

  /**
   * What happened on the call. The hypothesis verdict is the measure worth
   * watching: briefs whose hypotheses keep being rejected mean the signal
   * interpretation or the account selection is wrong, not the prose.
   */
  verdict(
    prepId: string,
    body: { hypothesis_verdict?: string; outcome?: string; rep_note?: string },
  ): Observable<GeneratedBrief> {
    return this.http.post<GeneratedBrief>(`/api/prep/${prepId}/verdict`, body);
  }
}

/** Research, signals, engagement — the order a rep's trust degrades in. */
export function freshnessOf(prep: Prep, kind: Freshness['kind']): Freshness | undefined {
  return prep.freshness.find((f) => f.kind === kind);
}

/**
 * How an age should read. Null is never, which is not a number of days, and a
 * screen that prints "0 days" for it has told the rep the opposite of the truth.
 */
export function ageLabel(days: number | null): string {
  if (days === null) return 'never';
  if (days === 0) return 'today';
  if (days === 1) return '1 day';
  return `${days} days`;
}

/**
 * Whether an age should alarm. Thresholds rather than a gradient because a rep
 * is deciding one thing: refresh first, or go.
 */
export function ageTone(kind: Freshness['kind'], days: number | null): 'good' | 'warn' | 'critical' {
  if (days === null) return 'critical';
  if (kind === 'engagement') return 'good';
  if (kind === 'research') return days <= 7 ? 'good' : days <= 30 ? 'warn' : 'critical';
  return days <= 30 ? 'good' : days <= 120 ? 'warn' : 'critical';
}
