import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { SortState, sortParams } from '../shared/sortable';

export interface AccountList {
  id: string;
  label: string;
  description: string | null;
  source: string;
  created_by: string;
  account_count: number;
  /** What the list is worked for, as names — no second request per row. */
  service_codes: string[];
  icp_names: string[];
  /**
   * Enrichment progress, as two numbers rather than a percentage: "0 of 40"
   * and "0 of 0" mean entirely different things and a percentage renders both
   * as nothing.
   */
  contact_count: number;
  verified_count: number;
  /** ISO timestamp. The index sorts on this. */
  created_at: string;
}

/** One company a source thinks a row might be. */
export interface ResolutionCandidate {
  name: string | null;
  domain: string | null;
  linkedin_url: string | null;
  industry: string | null;
  employee_count: number | null;
  confidence: number;
  rationale: string | null;
  /** Which source proposed it — Apollo can confirm a domain; a model shown
   *  the answer cannot, so the source changes how much the number is worth. */
  source: string | null;
}

export interface Account {
  id: string;
  name: string;
  domain: string | null;
  linkedin_url: string | null;
  industry: string | null;
  employee_count: number | null;
  hq_country: string | null;
  icp_match_score: number | null;
  status: string;
  research_status: string;
  enrichment_status: string;
  pipeline_note: string | null;
  /** Set while the account is on no list and in no campaign queue. */
  dormant_at?: string | null;
  dormant_reason?: string | null;
  /** Tier 0 — `unresolved` / `resolved` / `needs_review` / `rejected`. */
  resolution_status: string;
  resolution_confidence: number | null;
  resolution_note: string | null;
  resolved_by: string | null;
  resolution_candidates: ResolutionCandidate[] | null;
  /** The latest qualification's roll-up. Null until it has been judged —
   *  which is not the same as, and must not read as, a score of zero. */
  priority_score: number | null;
  priority_band: string | null;
}

/** What one resolution pass did, and what it could not do. */
export interface ResolveReport {
  ran: boolean;
  blocked: string | null;
  order: string[];
  checked: number;
  resolved: number;
  needs_review: number;
  unresolved: number;
  unavailable: number;
  outcomes: {
    account_id: string;
    name: string;
    outcome: string;
    detail: string;
    sources_called: string[];
  }[];
}

/** One field the importer can fill, and what filling it changes. */
export interface ImportField {
  key: string;
  label: string;
  /** `account` or `contact` — which record the column lands on. */
  entity: string;
  hint: string;
  required: boolean;
}

export interface DeleteListResult {
  accounts_deleted: number;
  /** Kept because another list still holds them — a list is a selection, not
   *  an owner, and the same company legitimately appears on several. */
  accounts_kept: number;
  /** On nothing else, with work behind them: hidden, nothing deleted. */
  accounts_dormant?: number;
}

/** What deleting a list would do to its accounts, asked before confirming. */
export interface DeletePreview {
  accounts: number;
  on_other_lists: number;
  /** On no other list, but kept live by a campaign queue. */
  in_queues: number;
  dormant: number;
  deleted: number;
}

/**
 * One person, with everything enrichment learned about them.
 *
 * Wide because the API is wide: eight fields across three providers, and until
 * now none of them reached a screen. Which of these a table shows is the
 * reader's choice — see `table-view`.
 */
export interface Contact {
  id: string;
  account_id: string;
  account_name: string;
  account_domain: string | null;
  full_name: string;
  title: string | null;
  seniority: string | null;
  persona_role: string | null;
  buying_role: string | null;
  email: string | null;
  /** Only `verified` may be sent to; a provider's `guessed` arrives as `risky`. */
  email_status: string | null;
  email_confidence: number | null;
  email_provider: string | null;
  phone: string | null;
  phone_status: string | null;
  phone_provider: string | null;
  linkedin_url: string | null;
  is_hypothesis: boolean;
  email_verified_at?: string | null;
  /** Verified long enough ago (90 days) to be checked again. */
  email_recheck?: boolean;
  created_at: string;
  updated_at: string | null;
  /** Off limits, and why. Nothing clears it but a rep. */
  do_not_contact?: boolean;
  do_not_contact_reason?: string | null;
  /** The company's rating, read for the ICP this screen works for. */
  qualification_score?: number | null;
  qualification_band?: string | null;
  icp_name?: string | null;
  gate?: string;
  gate_detail?: string;
}

export interface QueueSummary {
  id: string;
  label: string;
  /** A promoted queue refuses new members; the chooser greys it out. */
  locked_at?: string | null;
}

export interface BulkQueueReport {
  added: number;
  already: number;
  refused: { account_id: string; reason: string }[];
}

export interface ImportMapping {
  headers: string[];
  suggested: Record<string, string | null>;
  sample_rows: Record<string, string>[];
  /** Every field, not only the ones that happened to match. An unmapped
   *  `title` is invisible otherwise, and that is how a file imports with no
   *  contacts at all. */
  fields: ImportField[];
  unmapped_headers: string[];
  predicted_grain: string;
  warnings: string[];
}

export interface ImportRow {
  row_number: number;
  name: string | null;
  domain: string | null;
  outcome: string;
  detail: string;
}

/** What to look for among the Apollo contacts this account already owns. */
export interface ApolloBuildIn {
  /** Apollo's own employee bands: `1-10`, `11-50`, `51-200`, `201-500`, … */
  size_bands: string[];
  /** Apollo's own industry names. Empty means every industry. */
  industries: string[];
  /** Each company must field every one of these, or it is skipped. */
  personas: string[];
  verified_only: boolean;
  per_company: number;
  limit: number;
}

/** Where the numbers fall away. Every one of these is free to compute. */
export interface ApolloFunnel {
  saved_total: number;
  verified: number;
  titled: number;
  in_band: number;
  /** Read in this pass — bounded, so a sample of `in_band` rather than all. */
  read: number;
  companies: number;
  /** Companies that can fill every requested persona. The real filter. */
  usable_companies: number;
  available: number;
}

export interface ApolloBuild {
  ran: boolean;
  blocked: string | null;
  funnel: ApolloFunnel;
  note: string;
  list_id?: string | null;
  created: number;
  merged: number;
  contacts: number;
  /** Preview rows, carrying no name and no address — the question it answers
   *  is "is this the right shape of list", which needs neither. */
  sample: { company: string; domain: string; title: string | null;
            persona: string; email_status: string | null }[];
}

export interface ImportReport {
  total_rows: number;
  committed: boolean;
  counts: Record<string, number>;
  rows: ImportRow[];
  /**
   * Distinct companies this import will touch, counted on the key rather than
   * on the row. The server has always sent it and the client never declared
   * it, so the button counted account-grain outcomes instead — which are zero
   * on a contact-grain file, and the preview read "Import 0 accounts" for a
   * file that would create twenty-five.
   */
  accounts_touched: number;
  /** `"contact"` when the file is one row per person, `"account"` otherwise. */
  grain: 'account' | 'contact';
}

/** Shape of the 422 the sort allowlist returns. */
export interface UnsortableField {
  error: 'unsortable_field';
  field: string;
  allowed: string[];
}

export function asUnsortableField(err: unknown): UnsortableField | null {
  const detail = (err as HttpErrorResponse)?.error?.detail;
  return detail?.error === 'unsortable_field' ? (detail as UnsortableField) : null;
}

export interface ListTargeting {
  service_ids: string[];
  icp_profile_ids: string[];
  /** ICPs reachable from the chosen services, as the server computes it. */
  available_icps: string[];
}

export interface ConflictOption {
  value: string;
  source: string;
}

/** Something the company check could not settle on its own. */
export interface CompanyConflict {
  field: 'domain' | 'linkedin_url' | 'hq_country';
  current: string | null;
  options: ConflictOption[];
  note: string;
}

export interface CompanyCheckReport {
  checked: number;
  /** False when no Apollo key is stored: only the websites were read. */
  apollo_available: boolean;
  apollo_error: string | null;
  apollo_credits: number;
  filled: number;
  conflicts: number;
}

export interface OpenConflicts {
  account_id: string;
  name: string;
  domain: string | null;
  hq_country: string | null;
  linkedin_url: string | null;
  checked_at: string | null;
  conflicts: CompanyConflict[];
}

export interface FindReport {
  ran: boolean;
  blocked: string | null;
  service_code: string | null;
  per_persona: number;
  personas: string[];
  skipped_personas: string[];
  searches: number;
  proposed: number;
  refreshed: number;
  on_list: number;
  known: number;
  already_decided: number;
  filtered: number;
  /** Undecided suggestions from an earlier search that this one no longer keeps. */
  dropped: number;
}

/** Somebody Apollo's free search proposed. Nothing here is revealed yet. */
export interface ContactSuggestion {
  id: string;
  account_id: string;
  account_name: string;
  account_domain: string | null;
  /** The company's rating, read for the ICP this screen works for. */
  qualification_score?: number | null;
  qualification_band?: string | null;
  icp_name?: string | null;
  gate?: string;
  gate_detail?: string;

  first_name: string | null;
  /** Apollo's obfuscated surname, e.g. `Pe***d`. */
  last_name_hint: string | null;
  title: string | null;
  persona: string | null;
  buying_role: string | null;
  has_email: boolean;
  has_location: boolean;
  refreshed_at: string | null;
  status: 'proposed' | 'accepted' | 'rejected' | 'revealed' | 'known' | 'not_found';
  note: string | null;
  contact_id: string | null;
  contact_name: string | null;
  contact_email_status: string | null;
  contact_has_linkedin: boolean;
  /** The contact's profile — known once revealed, or when already on the list. */
  linkedin_url?: string | null;
  revealed_at: string | null;
}

export interface RevealReport {
  ran: boolean;
  blocked: string | null;
  asked: number;
  revealed: number;
  created: number;
  updated: number;
  verified: number;
  risky: number;
  no_email: number;
  linkedin: number;
  not_found: number;
  credits: number;
  /** Revealed before — stored details used, no credit spent. */
  reused?: number;
  /** Saved as contacts in the Apollo account (label Gen360). */
  saved_to_apollo?: number;
  save_error?: string | null;
  /** Apollo ran out of credits part-way; the rest stay accepted. */
  stopped?: string | null;
  company_country: number;
  company_linkedin: number;
  notes: string[];
}

export interface VerifyOutcome {
  contact_id: string;
  full_name: string;
  outcome: string;
  detail: string;
  providers_called: string[];
}

export interface VerifyReport {
  ran: boolean;
  blocked: string | null;
  service_code: string | null;
  waterfall: string[];
  checked: number;
  verified: number;
  with_phone: number;
  with_linkedin: number;
  risky: number;
  not_found: number;
  unavailable: number;
  skipped?: number;
  out_of_persona?: number;
  unknown_persona?: number;
  /** Missing LinkedIn links filled on this pass — from the provider, or the company's own site. */
  contact_linkedin_from_provider?: number;
  contact_linkedin_from_site?: number;
  company_linkedin_from_provider?: number;
  company_linkedin_from_site?: number;
  linkedin_notes?: string[];
  /** Aged verified addresses re-confirmed from saved Apollo contacts, free. */
  reconfirmed_free?: number;
  saved_to_apollo?: number;
  apollo_note?: string | null;
  outcomes: VerifyOutcome[];
}

@Injectable({ providedIn: 'root' })
export class ListsService {
  private http = inject(HttpClient);

  lists(sort: SortState): Observable<AccountList[]> {
    return this.http.get<AccountList[]>('/api/lists', { params: sortParams(sort) });
  }

  /**
   * What these filters would give, from the Apollo contacts already owned.
   *
   * Costs nothing, which is why it is a separate call rather than a dry-run
   * flag: a dry run that might spend money is not something anybody presses
   * twice, and this screen recounts on every change.
   */
  /** Apollo's industry names, in this account's order of volume. Served
   *  rather than held here because a wrong name fails silently — an industry
   *  Apollo does not know returns zero, exactly like a real one nobody is in. */
  apolloIndustries(): Observable<string[]> {
    return this.http.get<string[]>('/api/lists/from-apollo/industries');
  }

  previewFromApollo(body: ApolloBuildIn, deep = false): Observable<ApolloBuild> {
    return this.http.post<ApolloBuild>('/api/lists/from-apollo/preview', body, {
      params: deep ? { deep: 'true' } : {},
    });
  }

  /** Create the list and fill it. Still no credits — these are already yours. */
  buildFromApollo(label: string, body: ApolloBuildIn): Observable<ApolloBuild> {
    return this.http.post<ApolloBuild>('/api/lists/from-apollo', body, {
      params: { label },
    });
  }

  createList(body: { label: string; description?: string; source?: string }) {
    return this.http.post<AccountList>('/api/lists', body);
  }

  list(listId: string): Observable<AccountList> {
    return this.http.get<AccountList>(`/api/lists/${listId}`);
  }

  /**
   * Delete a list nothing downstream depends on.
   *
   * The server refuses — with a sentence — when an account has been researched
   * or promoted to a queue. Accounts left on no other list go with it, so the
   * response says how many were removed and how many were kept.
   */
  deleteList(listId: string): Observable<DeleteListResult> {
    return this.http.delete<DeleteListResult>(`/api/lists/${listId}`);
  }

  deletePreview(listId: string): Observable<DeletePreview> {
    return this.http.get<DeletePreview>(`/api/lists/${listId}/delete-preview`);
  }

  /** Put existing accounts on a list — how a dormant account comes back. */
  addToList(
    listId: string,
    accountIds: string[],
  ): Observable<{ added: number; already: number; revived: number; not_found: number }> {
    return this.http.post<{ added: number; already: number; revived: number; not_found: number }>(
      `/api/lists/${listId}/accounts/add`,
      { account_ids: accountIds },
    );
  }

  targeting(listId: string): Observable<ListTargeting> {
    return this.http.get<ListTargeting>(`/api/lists/${listId}/targeting`);
  }

  setTargeting(
    listId: string,
    body: { service_ids: string[]; icp_profile_ids: string[] },
  ): Observable<ListTargeting> {
    return this.http.put<ListTargeting>(`/api/lists/${listId}/targeting`, body);
  }

  /**
   * Run the enrichment waterfall for one service.
   *
   * `serviceId` is a required query parameter, not an optional one. Made
   * optional it would default to "everyone", which is the indiscriminate pass
   * the whole targeting flow exists to remove.
   */
  verifyContacts(
    listId: string,
    serviceId: string,
    accountIds?: string[],
    contactIds?: string[],
  ): Observable<VerifyReport> {
    const body =
      accountIds?.length || contactIds?.length
        ? { account_ids: accountIds ?? [], contact_ids: contactIds ?? [] }
        : null;
    return this.http.post<VerifyReport>(
      `/api/lists/${listId}/verify-contacts`,
      body,
      { params: { service_id: serviceId } },
    );
  }

  /** Country and LinkedIn page for confirmed accounts. The websites are free;
   *  Apollo's organisation record is a credit, asked only while one is missing. */
  checkCompanies(listId: string, accountIds?: string[]): Observable<CompanyCheckReport> {
    return this.http.post<CompanyCheckReport>(
      `/api/lists/${listId}/check-companies`,
      accountIds?.length ? { account_ids: accountIds } : null,
    );
  }

  companyConflicts(listId: string): Observable<OpenConflicts[]> {
    return this.http.get<OpenConflicts[]>(`/api/lists/${listId}/company-conflicts`);
  }

  /** `value` null keeps what is on record. */
  settleConflict(accountId: string, field: string, value: string | null): Observable<OpenConflicts> {
    return this.http.post<OpenConflicts>(`/api/accounts/${accountId}/company-check/settle`, {
      field,
      value,
    });
  }

  /** Apollo's People API Search for the ICP personas. Free; suggestions only. */
  findContacts(listId: string, serviceId: string, accountIds?: string[]): Observable<FindReport> {
    return this.http.post<FindReport>(
      `/api/lists/${listId}/find-contacts`,
      accountIds?.length ? { account_ids: accountIds } : null,
      { params: { service_id: serviceId } },
    );
  }

  suggestions(listId: string, statuses?: string[]): Observable<ContactSuggestion[]> {
    return this.http.get<ContactSuggestion[]>(`/api/lists/${listId}/suggestions`, {
      params: statuses?.length ? { status: statuses } : {},
    });
  }

  decideSuggestions(listId: string, ids: string[], status: string): Observable<{ changed: number }> {
    return this.http.post<{ changed: number }>(`/api/lists/${listId}/suggestions/decide`, {
      ids,
      status,
    });
  }

  /** Paid: one Apollo credit per accepted person it has data for. */
  revealSuggestions(listId: string, ids?: string[]): Observable<RevealReport> {
    return this.http.post<RevealReport>(
      `/api/lists/${listId}/suggestions/reveal`,
      ids?.length ? { ids } : null,
    );
  }

  listAccounts(listId: string, sort: SortState): Observable<Account[]> {
    return this.http.get<Account[]>(`/api/lists/${listId}/accounts`, {
      params: sortParams(sort),
    });
  }

  accounts(
    sort: SortState,
    q?: string,
    dormant?: 'exclude' | 'include' | 'only',
  ): Observable<Account[]> {
    const params: Record<string, string> = { ...sortParams(sort) };
    if (q) params['q'] = q;
    if (dormant) params['dormant'] = dormant;
    return this.http.get<Account[]>('/api/accounts', { params });
  }

  /**
   * Tier 0 — identify the companies on this list.
   *
   * `limit` defaults low on purpose: the first run is the one most likely to
   * reveal the CSV is wrong, and finding that out over 50 rows costs less
   * than over 5,000.
   */
  resolveAccounts(
    listId: string,
    limit = 50,
    accountIds?: string[],
    recheck = false,
  ): Observable<ResolveReport> {
    // A selection narrows it; without one the server takes every unresolved
    // account on the list.
    return this.http.post<ResolveReport>(
      `/api/lists/${listId}/resolve`,
      accountIds?.length ? { account_ids: accountIds } : null,
      { params: recheck ? { limit, recheck: true } : { limit } },
    );
  }

  /** Record what a rep decided about one account's identity. */
  setResolution(
    accountId: string,
    body: {
      status?: string;
      domain?: string | null;
      linkedin_url?: string | null;
      industry?: string | null;
      employee_count?: number | null;
    },
  ): Observable<Account> {
    return this.http.patch<Account>(
      `/api/accounts/${accountId}/resolution`,
      body,
    );
  }

  /** Everyone on a list, across its accounts — where enrichment is run. */
  listContacts(listId: string, sort: SortState): Observable<Contact[]> {
    return this.http.get<Contact[]>(`/api/lists/${listId}/contacts`, {
      params: sortParams(sort),
    });
  }

  /** Everyone known at one company. */
  accountContacts(accountId: string, sort: SortState): Observable<Contact[]> {
    return this.http.get<Contact[]>(`/api/accounts/${accountId}/contacts`, {
      params: sortParams(sort),
    });
  }

  /**
   * Take accounts off a list. The accounts are kept — a list is a selection,
   * not an owner. POST rather than DELETE because a selection is a body, and
   * DELETE bodies are dropped by enough proxies to be unreliable.
   */
  removeFromList(
    listId: string,
    accountIds: string[],
  ): Observable<{ removed: number; not_members: number; dormant?: number }> {
    return this.http.post<{ removed: number; not_members: number; dormant?: number }>(
      `/api/lists/${listId}/accounts/remove`,
      { account_ids: accountIds },
    );
  }

  /** Score accounts that already hold signals. No research, no provider credits. */
  qualifyAccounts(listId: string, accountIds: string[]): Observable<any> {
    return this.http.post(`/api/lists/${listId}/qualify`, { account_ids: accountIds });
  }

  /**
   * Research only the selected accounts. Unconfirmed ones are skipped
   * server-side, and families answered inside the reuse window are reused —
   * unless `force`, which is "Rerun research".
   *
   * `scope` decides which halves are bought and `forceScope` which halves a
   * rerun re-buys. Both default the way the money says they should: a rerun
   * re-sweeps the company and leaves its people inside their window, because
   * the contact pass is four grounded searches for a tenth of the evidence
   * and re-buying it on every rerun is what made a day's work cost $10.
   */
  researchAccounts(
    listId: string,
    accountIds: string[],
    force = false,
    contactIds?: string[],
    opts: { scope?: 'both' | 'company' | 'contacts';
            forceScope?: 'both' | 'company' | 'contacts' } = {},
  ): Observable<any> {
    const params: Record<string, string> = {};
    if (force) params['force'] = 'true';
    if (opts.scope) params['scope'] = opts.scope;
    if (opts.forceScope) params['force_scope'] = opts.forceScope;
    return this.http.post(
      `/api/lists/${listId}/run-research`,
      { account_ids: accountIds, contact_ids: contactIds ?? [] },
      { params },
    );
  }

  /**
   * Research one account, or named people at it, from the account screen.
   *
   * `listId` is only needed when the account is on more than one list: a
   * list's ICPs decide which signal types research looks for, so the server
   * refuses to guess between two that may disagree and returns `which_list`
   * with the options.
   */
  researchAccount(
    accountId: string,
    opts: { contactIds?: string[]; force?: boolean; listId?: string } = {},
  ): Observable<any> {
    const params: Record<string, string | string[]> = {};
    if (opts.force) params['force'] = 'true';
    if (opts.listId) params['list_id'] = opts.listId;
    if (opts.contactIds?.length) params['contact_ids'] = opts.contactIds;
    return this.http.post(`/api/accounts/${accountId}/run-research`, null, { params });
  }

  /**
   * Mark people do-not-contact, or allow them again.
   *
   * Never a delete: their signals, evidence and outreach history stay. What
   * changes is that enrichment, research, queues and execution refuse them.
   */
  setSuppression(
    contactIds: string[],
    doNotContact: boolean,
    reason?: string,
  ): Observable<{ updated: number; not_found: number }> {
    return this.http.post<{ updated: number; not_found: number }>(
      '/api/contacts/suppression',
      { contact_ids: contactIds, do_not_contact: doNotContact, reason: reason ?? null },
    );
  }

  queues(): Observable<QueueSummary[]> {
    return this.http.get<QueueSummary[]>('/api/queues');
  }

  addToQueue(
    queueId: string,
    accountIds: string[],
    sourceListId: string | null,
  ): Observable<BulkQueueReport> {
    return this.http.post<BulkQueueReport>(`/api/queues/${queueId}/members/bulk`, {
      account_ids: accountIds,
      source_list_id: sourceListId,
    });
  }

  /** People by name, to a queue — a campaign sends to people, not companies. */
  addContactsToQueue(
    queueId: string,
    contactIds: string[],
    sourceListId: string | null,
  ): Observable<{ added: number; already: number; refused: { contact_id: string; reason: string }[] }> {
    return this.http.post<{ added: number; already: number; refused: { contact_id: string; reason: string }[] }>(
      `/api/queues/${queueId}/contacts/bulk`,
      { contact_ids: contactIds, source_list_id: sourceListId },
    );
  }

  inspectCsv(listId: string, file: File): Observable<ImportMapping> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<ImportMapping>(`/api/lists/${listId}/import/inspect`, form);
  }

  /**
   * `dryRun` defaults to true here as well as on the server. Two defaults
   * rather than one, because an import that writes because a flag was
   * forgotten is the failure worth being redundant about.
   */
  importCsv(
    listId: string,
    file: File,
    mapping: Record<string, string | null>,
    dryRun = true,
  ): Observable<ImportReport> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<ImportReport>(`/api/lists/${listId}/import`, form, {
      params: { mapping: JSON.stringify(mapping), dry_run: String(dryRun) },
    });
  }
}
