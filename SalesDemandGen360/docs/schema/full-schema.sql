-- GENERATED FILE — do not edit by hand.
--
-- The whole schema, dumped from the development database so that reading it is
-- faster than reading 40-odd migrations. It is a *convenience*, not the source
-- of truth: the SQLAlchemy models and the alembic migrations are, and this file
-- drifts the moment either changes without being regenerated.
--
-- Regenerate with:
--   pg_dump -h localhost -U postgres -d sdg360 --schema-only
--           --no-owner --no-privileges -f docs/schema/full-schema.sql
--
-- Generated 2026-10-04 · PostgreSQL 17.9 · 53 tables.
--
-- PostgreSQL database dump
--

\restrict q9FDgfb9x3w0F5vxfw4jWuBlkPT3qvuld7FU8Ijx8cPgwcQGJjyTU1OxbaEreQb

-- Dumped from database version 17.9
-- Dumped by pg_dump version 17.9

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: execution_requires_approval(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.execution_requires_approval() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.status = 'sent' AND NOT EXISTS (
                SELECT 1 FROM approval
                 WHERE subject_type = 'outreach_sequence'
                   AND subject_id = NEW.sequence_id
                   AND decision = 'approve'
            ) THEN
                RAISE EXCEPTION
                    'sequence % has no approval; nothing sends without one', NEW.sequence_id
                    USING HINT = 'Record an approval before writing a sent execution_record.';
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: signal_requires_evidence(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.signal_requires_evidence() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM signal_evidence WHERE signal_id = NEW.id) THEN
                RAISE EXCEPTION 'signal % has no evidence', NEW.id
                      USING HINT = 'Every signal must cite at least one evidence row.';
            END IF;
            RETURN NULL;
        END;
        $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: account; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account (
    name text NOT NULL,
    domain text,
    linkedin_url text,
    industry text,
    employee_count integer,
    revenue_band text,
    funding_stage text,
    hq_country text,
    hq_region text,
    crm_record_id text,
    icp_match_score numeric(5,2),
    icp_match_reasons jsonb,
    status text DEFAULT 'new'::text NOT NULL,
    research_status text DEFAULT 'not_started'::text NOT NULL,
    research_completed_at timestamp with time zone,
    enrichment_status text DEFAULT 'not_started'::text NOT NULL,
    enrichment_completed_at timestamp with time zone,
    pipeline_note text,
    disqualified_reason text,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    industry_key text,
    resolution_status text DEFAULT 'unresolved'::text NOT NULL,
    resolution_confidence numeric(4,3),
    resolved_by text,
    resolution_note text,
    resolved_at timestamp with time zone,
    resolution_candidates jsonb,
    company_check jsonb,
    dormant_at timestamp with time zone,
    dormant_reason text,
    CONSTRAINT ck_account_disqualified_needs_a_reason CHECK (((status <> 'disqualified'::text) OR (disqualified_reason IS NOT NULL))),
    CONSTRAINT ck_account_enrichment_status_valid CHECK ((enrichment_status = ANY (ARRAY['not_started'::text, 'running'::text, 'complete'::text, 'partial'::text, 'failed'::text, 'skipped'::text]))),
    CONSTRAINT ck_account_research_status_valid CHECK ((research_status = ANY (ARRAY['not_started'::text, 'running'::text, 'complete'::text, 'partial'::text, 'failed'::text]))),
    CONSTRAINT ck_account_resolution_status_valid CHECK ((resolution_status = ANY (ARRAY['unresolved'::text, 'resolved'::text, 'needs_review'::text, 'rejected'::text]))),
    CONSTRAINT ck_account_status_valid CHECK ((status = ANY (ARRAY['new'::text, 'researching'::text, 'qualified'::text, 'disqualified'::text, 'active'::text, 'closed'::text])))
);


--
-- Name: account_alias; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account_alias (
    account_id uuid NOT NULL,
    alias text NOT NULL,
    alias_type text NOT NULL,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    CONSTRAINT ck_account_alias_alias_type_valid CHECK ((alias_type = ANY (ARRAY['name'::text, 'domain'::text, 'crm_id'::text])))
);


--
-- Name: account_context; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account_context (
    account_id uuid NOT NULL,
    run_id uuid,
    version integer NOT NULL,
    parent_version integer,
    payload jsonb NOT NULL,
    signal_ids jsonb NOT NULL,
    token_count integer,
    builder_version text,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    CONSTRAINT ck_account_context_parent_precedes_child CHECK (((parent_version IS NULL) OR (parent_version < version))),
    CONSTRAINT ck_account_context_version_positive CHECK ((version > 0))
);


--
-- Name: account_list; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account_list (
    label text NOT NULL,
    description text,
    source text NOT NULL,
    created_by text NOT NULL,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    CONSTRAINT ck_account_list_source_valid CHECK ((source = ANY (ARRAY['csv'::text, 'manual'::text, 'crm'::text])))
);


--
-- Name: account_list_icp; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account_list_icp (
    list_id uuid NOT NULL,
    icp_profile_id uuid NOT NULL
);


--
-- Name: account_list_member; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account_list_member (
    list_id uuid NOT NULL,
    account_id uuid NOT NULL,
    added_at timestamp with time zone DEFAULT now() NOT NULL,
    added_by text,
    import_row_reason text,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: account_list_service; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account_list_service (
    list_id uuid NOT NULL,
    service_id uuid NOT NULL
);


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: approval; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval (
    subject_type text NOT NULL,
    subject_id uuid NOT NULL,
    decision text NOT NULL,
    reject_reason text,
    comment text,
    edited_body text,
    reviewer_id text NOT NULL,
    review_depth text DEFAULT 'individual'::text NOT NULL,
    sample_id uuid,
    sample_size integer,
    stratum_size integer,
    decided_at timestamp with time zone DEFAULT now() NOT NULL,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    CONSTRAINT ck_approval_a_rejection_says_why CHECK (((decision <> 'reject'::text) OR (reject_reason IS NOT NULL))),
    CONSTRAINT ck_approval_an_edit_carries_its_delta CHECK (((decision <> 'edit'::text) OR (edited_body IS NOT NULL))),
    CONSTRAINT ck_approval_decision_valid CHECK ((decision = ANY (ARRAY['approve'::text, 'edit'::text, 'regenerate'::text, 'reject'::text]))),
    CONSTRAINT ck_approval_reject_reason_valid CHECK (((reject_reason IS NULL) OR (reject_reason = ANY (ARRAY['wrong_persona'::text, 'wrong_signal'::text, 'wrong_problem'::text, 'wrong_solution'::text, 'poor_message'::text, 'other'::text])))),
    CONSTRAINT ck_approval_review_depth_valid CHECK ((review_depth = ANY (ARRAY['individual'::text, 'sampled'::text, 'inherited'::text]))),
    CONSTRAINT ck_approval_sampled_and_inherited_cite_their_sample CHECK (((review_depth = 'individual'::text) OR (sample_id IS NOT NULL))),
    CONSTRAINT ck_approval_subject_type_valid CHECK ((subject_type = ANY (ARRAY['strategy'::text, 'outreach_sequence'::text, 'draft'::text])))
);


--
-- Name: approval_sample; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_sample (
    campaign_id uuid NOT NULL,
    draw_number integer DEFAULT 1 NOT NULL,
    sequence_ids jsonb NOT NULL,
    stratum_size integer NOT NULL,
    sample_size integer NOT NULL,
    sample_rate double precision,
    rejections integer DEFAULT 0 NOT NULL,
    escalated_to_individual boolean DEFAULT false NOT NULL,
    is_current boolean DEFAULT true NOT NULL,
    accepted_at timestamp with time zone,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    CONSTRAINT ck_approval_sample_draw_number_positive CHECK ((draw_number > 0)),
    CONSTRAINT ck_approval_sample_rejections_non_negative CHECK ((rejections >= 0)),
    CONSTRAINT ck_approval_sample_sample_fits_inside_its_stratum CHECK ((sample_size <= stratum_size)),
    CONSTRAINT ck_approval_sample_sample_size_non_negative CHECK ((sample_size >= 0)),
    CONSTRAINT ck_approval_sample_stratum_size_non_negative CHECK ((stratum_size >= 0)),
    CONSTRAINT ck_approval_sample_the_drawn_ids_match_the_stated_size CHECK ((jsonb_array_length(sequence_ids) = sample_size))
);


--
-- Name: cadence_shape; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cadence_shape (
    key text NOT NULL,
    label text NOT NULL,
    lgm_campaign_id text NOT NULL,
    touch_count integer NOT NULL,
    span_days integer,
    attribute_map jsonb DEFAULT '{}'::jsonb NOT NULL,
    attributes_used integer DEFAULT 0 NOT NULL,
    selection_rule jsonb,
    verified_at timestamp with time zone,
    verified_by text,
    lgm_updated_at timestamp with time zone,
    lgm_channels text[],
    lgm_status text,
    durable_from_step integer,
    active boolean DEFAULT true NOT NULL,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    lgm_audience_name text,
    lgm_audience_id text,
    subject_attribute_map jsonb DEFAULT '{}'::jsonb NOT NULL,
    step_channels jsonb DEFAULT '{}'::jsonb NOT NULL,
    slot_labels jsonb DEFAULT '{}'::jsonb NOT NULL,
    step_meta jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT ck_cadence_shape_span_positive CHECK (((span_days IS NULL) OR (span_days > 0))),
    CONSTRAINT ck_cadence_shape_touch_count_positive CHECK ((touch_count > 0)),
    CONSTRAINT ck_cadence_shape_verification_is_attributed CHECK (((verified_at IS NULL) OR (verified_by IS NOT NULL))),
    CONSTRAINT ck_cadence_shape_within_the_attribute_budget CHECK (((attributes_used >= 0) AND (attributes_used <= 20)))
);


--
-- Name: campaign_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.campaign_queue (
    label text NOT NULL,
    description text,
    status text DEFAULT 'draft'::text NOT NULL,
    locked_at timestamp with time zone,
    promoted_to_campaign_id uuid,
    cloned_from_queue_id uuid,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    service_id uuid,
    icp_profile_id uuid,
    icp_version integer,
    CONSTRAINT ck_campaign_queue_locked_at_consistent CHECK (((status = 'locked'::text) = (locked_at IS NOT NULL))),
    CONSTRAINT ck_campaign_queue_status_valid CHECK ((status = ANY (ARRAY['draft'::text, 'locked'::text])))
);


--
-- Name: campaign_queue_contact; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.campaign_queue_contact (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    queue_id uuid NOT NULL,
    contact_id uuid NOT NULL,
    account_id uuid NOT NULL,
    source_list_id uuid,
    added_by text
);


--
-- Name: campaign_queue_member; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.campaign_queue_member (
    queue_id uuid NOT NULL,
    account_id uuid NOT NULL,
    source_list_id uuid,
    qualification_id uuid,
    added_by text,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: contact; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.contact (
    account_id uuid NOT NULL,
    full_name text NOT NULL,
    title text,
    seniority text DEFAULT 'unknown'::text NOT NULL,
    persona_role text,
    buying_role text,
    linkedin_url text,
    email text,
    email_status text DEFAULT 'unverified'::text NOT NULL,
    email_confidence numeric(4,3),
    email_provider text,
    email_provider_record_id text,
    phone text,
    phone_status text DEFAULT 'unverified'::text NOT NULL,
    phone_provider text,
    phone_provider_record_id text,
    is_hypothesis boolean DEFAULT false NOT NULL,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    lgm_identity_id uuid,
    city text,
    country text,
    apollo_person_id text,
    email_verified_at timestamp with time zone,
    apollo_contact_id text,
    apollo_saved_at timestamp with time zone,
    do_not_contact boolean DEFAULT false NOT NULL,
    do_not_contact_reason text,
    do_not_contact_at timestamp with time zone,
    CONSTRAINT ck_contact_buying_role_valid CHECK ((buying_role = ANY (ARRAY['economic_buyer'::text, 'technical_buyer'::text, 'champion'::text, 'influencer'::text, 'blocker'::text]))),
    CONSTRAINT ck_contact_dnc_carries_a_reason CHECK (((NOT do_not_contact) OR (do_not_contact_reason IS NOT NULL))),
    CONSTRAINT ck_contact_email_provider_valid CHECK ((email_provider = ANY (ARRAY['apollo'::text, 'contactout'::text, 'manual'::text]))),
    CONSTRAINT ck_contact_email_status_valid CHECK ((email_status = ANY (ARRAY['verified'::text, 'risky'::text, 'invalid'::text, 'unverified'::text]))),
    CONSTRAINT ck_contact_phone_provider_valid CHECK ((phone_provider = ANY (ARRAY['apollo'::text, 'contactout'::text, 'manual'::text]))),
    CONSTRAINT ck_contact_phone_status_valid CHECK ((phone_status = ANY (ARRAY['verified'::text, 'unverified'::text, 'invalid'::text]))),
    CONSTRAINT ck_contact_seniority_valid CHECK ((seniority = ANY (ARRAY['c_level'::text, 'vp'::text, 'director'::text, 'manager'::text, 'ic'::text, 'unknown'::text])))
);


--
-- Name: contact_suggestion; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.contact_suggestion (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    list_id uuid,
    account_id uuid NOT NULL,
    apollo_person_id text NOT NULL,
    first_name text,
    last_name_hint text,
    title text,
    persona text,
    buying_role text,
    has_email boolean DEFAULT false NOT NULL,
    has_location boolean DEFAULT false NOT NULL,
    has_direct_phone boolean DEFAULT false NOT NULL,
    refreshed_at timestamp with time zone,
    contact_id uuid,
    status text DEFAULT 'proposed'::text NOT NULL,
    note text,
    revealed_at timestamp with time zone,
    CONSTRAINT ck_contact_suggestion_buying_role_valid CHECK (((buying_role IS NULL) OR (buying_role = ANY (ARRAY['economic_buyer'::text, 'technical_buyer'::text, 'champion'::text, 'influencer'::text, 'blocker'::text])))),
    CONSTRAINT ck_contact_suggestion_status_valid CHECK ((status = ANY (ARRAY['proposed'::text, 'accepted'::text, 'rejected'::text, 'revealed'::text, 'known'::text, 'not_found'::text])))
);


--
-- Name: deferred_enrolment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.deferred_enrolment (
    campaign_id uuid NOT NULL,
    contact_id uuid NOT NULL,
    blocked_by_sequence_id uuid,
    status text DEFAULT 'waiting'::text NOT NULL,
    resolved_at timestamp with time zone,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    CONSTRAINT ck_deferred_enrolment_status_valid CHECK ((status = ANY (ARRAY['waiting'::text, 'enrolled'::text, 'abandoned'::text])))
);


--
-- Name: draft; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.draft (
    touch_id uuid NOT NULL,
    version integer NOT NULL,
    subject text,
    body text NOT NULL,
    cited_proof_point_ids jsonb,
    cited_signal_ids jsonb,
    signal_dependence text DEFAULT 'durable'::text NOT NULL,
    model text,
    prompt_version text,
    generated_as text DEFAULT 'arc'::text NOT NULL,
    regenerated_reason text,
    is_current boolean DEFAULT true NOT NULL,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    CONSTRAINT ck_draft_dependence_valid CHECK ((signal_dependence = ANY (ARRAY['dated'::text, 'implied'::text, 'durable'::text]))),
    CONSTRAINT ck_draft_generated_as_valid CHECK ((generated_as = ANY (ARRAY['arc'::text, 'regeneration'::text, 'rep_edit'::text]))),
    CONSTRAINT ck_draft_regeneration_needs_a_reason CHECK (((generated_as <> 'regeneration'::text) OR (regenerated_reason IS NOT NULL))),
    CONSTRAINT ck_draft_version_positive CHECK ((version > 0))
);


--
-- Name: enrichment_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enrichment_config (
    provider_order jsonb NOT NULL,
    required_fields jsonb DEFAULT '["email"]'::jsonb NOT NULL,
    version integer NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    resolution_order jsonb DEFAULT '["apollo_org", "website", "llm_web"]'::jsonb NOT NULL,
    suggestions_per_persona integer DEFAULT 5 NOT NULL,
    CONSTRAINT ck_enrichment_config_suggestions_per_persona_range CHECK (((suggestions_per_persona >= 1) AND (suggestions_per_persona <= 25))),
    CONSTRAINT ck_enrichment_config_the_waterfall_has_at_least_one_provider CHECK ((jsonb_array_length(provider_order) > 0))
);


--
-- Name: evaluation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evaluation (
    subject_type text NOT NULL,
    subject_id uuid NOT NULL,
    method text NOT NULL,
    verdict text NOT NULL,
    scores jsonb,
    issues jsonb,
    evaluator_version text,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    CONSTRAINT ck_evaluation_a_warning_or_failure_says_what_is_wrong CHECK (((verdict = 'pass'::text) OR ((issues IS NOT NULL) AND (jsonb_array_length(issues) > 0)))),
    CONSTRAINT ck_evaluation_method_valid CHECK ((method = ANY (ARRAY['rules'::text, 'llm'::text, 'hybrid'::text]))),
    CONSTRAINT ck_evaluation_subject_type_valid CHECK ((subject_type = ANY (ARRAY['research'::text, 'signal'::text, 'qualification'::text, 'strategy'::text, 'outreach_sequence'::text, 'draft'::text, 'sales_prep'::text, 'execution'::text]))),
    CONSTRAINT ck_evaluation_verdict_valid CHECK ((verdict = ANY (ARRAY['pass'::text, 'warn'::text, 'fail'::text])))
);


--
-- Name: evidence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evidence (
    account_id uuid NOT NULL,
    run_id uuid,
    source_type text NOT NULL,
    source_url text,
    source_name text,
    title text,
    excerpt text NOT NULL,
    observed_at date,
    retrieved_at timestamp with time zone DEFAULT now() NOT NULL,
    author_id text,
    capture_method text,
    source_hash text NOT NULL,
    excerpt_hash text NOT NULL,
    raw_ref text,
    raw_status text DEFAULT 'stored'::text NOT NULL,
    reliability numeric(4,3),
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    family text,
    contact_id uuid,
    CONSTRAINT ck_evidence_capture_method_valid CHECK (((capture_method IS NULL) OR (capture_method = ANY (ARRAY['conversation'::text, 'email'::text, 'event'::text, 'inbound'::text, 'other'::text])))),
    CONSTRAINT ck_evidence_manual_capture_is_attributed CHECK (((source_type <> 'manual'::text) OR ((author_id IS NOT NULL) AND (capture_method IS NOT NULL)))),
    CONSTRAINT ck_evidence_raw_status_valid CHECK ((raw_status = ANY (ARRAY['stored'::text, 'unavailable'::text, 'purged'::text]))),
    CONSTRAINT ck_evidence_reliability_is_a_proportion CHECK (((reliability IS NULL) OR ((reliability >= (0)::numeric) AND (reliability <= (1)::numeric)))),
    CONSTRAINT ck_evidence_source_type_valid CHECK ((source_type = ANY (ARRAY['web'::text, 'news'::text, 'jobs'::text, 'linkedin'::text, 'crm'::text, 'provider'::text, 'filing'::text, 'manual'::text]))),
    CONSTRAINT ck_evidence_stored_has_a_ref CHECK (((raw_status <> 'stored'::text) OR (raw_ref IS NOT NULL)))
);


--
-- Name: execution_record; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.execution_record (
    sequence_id uuid NOT NULL,
    touch_id uuid,
    provider text DEFAULT 'lgm'::text NOT NULL,
    provider_ref text,
    action text,
    status text NOT NULL,
    skip_reason text,
    error text,
    interlock_snapshot jsonb,
    sent_at timestamp with time zone,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    CONSTRAINT ck_execution_record_a_failure_says_why CHECK (((status <> 'failed'::text) OR (error IS NOT NULL))),
    CONSTRAINT ck_execution_record_a_send_has_a_timestamp CHECK (((status <> 'sent'::text) OR (sent_at IS NOT NULL))),
    CONSTRAINT ck_execution_record_a_skip_says_why CHECK (((status <> 'skipped'::text) OR (skip_reason IS NOT NULL))),
    CONSTRAINT ck_execution_record_skip_reason_valid CHECK (((skip_reason IS NULL) OR (skip_reason = ANY (ARRAY['account_disqualified'::text, 'no_go_list'::text, 'unsubscribed'::text, 'contact_unverified'::text, 'sequence_stopped'::text])))),
    CONSTRAINT ck_execution_record_status_valid CHECK ((status = ANY (ARRAY['queued'::text, 'sent'::text, 'failed'::text, 'skipped'::text])))
);


--
-- Name: icp_profile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.icp_profile (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: icp_profile_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.icp_profile_version (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    icp_profile_id uuid NOT NULL,
    definition jsonb DEFAULT '{}'::jsonb NOT NULL,
    version integer NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: installation_mode; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.installation_mode (
    mode text NOT NULL,
    reason text,
    switched_by text,
    version integer NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    CONSTRAINT ck_installation_mode_mode_valid CHECK ((mode = ANY (ARRAY['production'::text, 'demo'::text])))
);


--
-- Name: integration_credential; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.integration_credential (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    provider text NOT NULL,
    credential_type text NOT NULL,
    value_encrypted bytea NOT NULL,
    last_four character varying(4),
    status text DEFAULT 'untested'::text NOT NULL,
    last_tested_at timestamp with time zone,
    spend_cap numeric(12,2),
    console_url text,
    last_test_code text,
    last_test_detail text,
    CONSTRAINT ck_integration_credential_ck_integration_credential_cre_2d9f CHECK ((credential_type = ANY (ARRAY['api_key'::text, 'token'::text, 'webhook_secret'::text, 'base_url'::text]))),
    CONSTRAINT ck_integration_credential_ck_integration_credential_sta_9dd9 CHECK ((status = ANY (ARRAY['valid'::text, 'invalid'::text, 'untested'::text, 'expired'::text]))),
    CONSTRAINT ck_integration_credential_provider_valid CHECK ((provider ~ '^[a-z][a-z0-9_-]{1,39}$'::text))
);


--
-- Name: lgm_identity; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lgm_identity (
    linkedin_slug text,
    email text,
    name_company_key text,
    resolution_state text DEFAULT 'resolved'::text NOT NULL,
    conflict_detail text,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    CONSTRAINT ck_lgm_identity_at_least_one_identifier CHECK (((linkedin_slug IS NOT NULL) OR (email IS NOT NULL) OR (name_company_key IS NOT NULL))),
    CONSTRAINT ck_lgm_identity_conflict_needs_a_reason CHECK (((resolution_state <> 'conflict'::text) OR (conflict_detail IS NOT NULL))),
    CONSTRAINT ck_lgm_identity_resolution_state_valid CHECK ((resolution_state = ANY (ARRAY['resolved'::text, 'conflict'::text])))
);


--
-- Name: llm_call; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.llm_call (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scenario text NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    effort text NOT NULL,
    input_tokens integer DEFAULT 0 NOT NULL,
    output_tokens integer DEFAULT 0 NOT NULL,
    cache_read_tokens integer DEFAULT 0 NOT NULL,
    cache_write_tokens integer DEFAULT 0 NOT NULL,
    duration_ms integer DEFAULT 0 NOT NULL,
    ok boolean DEFAULT true NOT NULL,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    CONSTRAINT ck_llm_call_tokens_non_negative CHECK (((input_tokens >= 0) AND (output_tokens >= 0)))
);


--
-- Name: llm_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.llm_config (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    scenario text NOT NULL,
    model text DEFAULT 'claude-opus-5'::text NOT NULL,
    effort text NOT NULL,
    max_tokens integer NOT NULL,
    thinking_mode text DEFAULT 'adaptive'::text NOT NULL,
    output_contract text NOT NULL,
    version integer NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    provider text DEFAULT 'anthropic'::text NOT NULL,
    CONSTRAINT ck_llm_config_ck_llm_config_effort_valid CHECK ((effort = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text, 'xhigh'::text, 'max'::text]))),
    CONSTRAINT ck_llm_config_ck_llm_config_max_tokens_positive CHECK ((max_tokens > 0)),
    CONSTRAINT ck_llm_config_provider_valid CHECK ((provider ~ '^[a-z][a-z0-9_-]{1,39}$'::text))
);


--
-- Name: model_availability; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_availability (
    enabled jsonb DEFAULT '{}'::jsonb NOT NULL,
    version integer NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: org_profile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.org_profile (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    name text NOT NULL,
    description text,
    version integer NOT NULL,
    is_active boolean DEFAULT false NOT NULL
);


--
-- Name: outreach_campaign; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outreach_campaign (
    label text NOT NULL,
    description text,
    cadence_shape_id uuid,
    status text DEFAULT 'draft'::text NOT NULL,
    started_at timestamp with time zone,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    promotion_notes jsonb,
    service_id uuid,
    icp_profile_id uuid,
    icp_version integer,
    CONSTRAINT ck_outreach_campaign_status_valid CHECK ((status = ANY (ARRAY['draft'::text, 'pending_approval'::text, 'executing'::text, 'paused'::text, 'completed'::text, 'cancelled'::text])))
);


--
-- Name: outreach_campaign_source; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outreach_campaign_source (
    campaign_id uuid NOT NULL,
    queue_id uuid NOT NULL,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone
);


--
-- Name: outreach_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outreach_event (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    source text DEFAULT 'lgm'::text NOT NULL,
    received_via text NOT NULL,
    external_id text,
    event_type text NOT NULL,
    channel text,
    direction text,
    occurred_at timestamp with time zone NOT NULL,
    lgm_lead_id text,
    lgm_campaign_id text,
    conversation_id text,
    preview text,
    contact_id uuid,
    sequence_id uuid,
    campaign_id uuid,
    payload jsonb,
    CONSTRAINT ck_outreach_event_ck_outreach_event_direction_valid CHECK (((direction IS NULL) OR (direction = ANY (ARRAY['sent'::text, 'received'::text])))),
    CONSTRAINT ck_outreach_event_ck_outreach_event_received_via_valid CHECK ((received_via = ANY (ARRAY['webhook'::text, 'poll'::text])))
);


--
-- Name: outreach_sequence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outreach_sequence (
    thread_id uuid,
    campaign_id uuid,
    cadence_shape_id uuid,
    lgm_identity_id uuid,
    start_offset_days integer DEFAULT 0 NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    lgm_campaign_id text,
    lgm_lead_id text,
    selection_log jsonb,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    contact_id uuid,
    withdrawn_at timestamp with time zone,
    withdraw_reason text,
    first_reply_at timestamp with time zone,
    last_event_at timestamp with time zone,
    CONSTRAINT ck_outreach_sequence_names_a_person CHECK (((thread_id IS NOT NULL) OR (contact_id IS NOT NULL))),
    CONSTRAINT ck_outreach_sequence_offset_non_negative CHECK ((start_offset_days >= 0)),
    CONSTRAINT ck_outreach_sequence_status_valid CHECK ((status = ANY (ARRAY['draft'::text, 'pending_eval'::text, 'pending_approval'::text, 'approved'::text, 'executing'::text, 'paused'::text, 'completed'::text, 'stopped'::text, 'cancelled'::text]))),
    CONSTRAINT ck_outreach_sequence_withdrawal_carries_a_reason CHECK (((status <> 'cancelled'::text) OR (withdraw_reason IS NOT NULL)))
);


--
-- Name: persona_service_score; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.persona_service_score (
    strategy_id uuid NOT NULL,
    contact_id uuid NOT NULL,
    service_id uuid NOT NULL,
    weight numeric(5,2) NOT NULL,
    rationale text,
    evidence_ids jsonb,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    CONSTRAINT ck_persona_service_score_weight_non_negative CHECK ((weight >= (0)::numeric))
);


--
-- Name: proof_point; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.proof_point (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    service_id uuid,
    kind text NOT NULL,
    title text NOT NULL,
    body text NOT NULL,
    client_industry text,
    client_size_band text,
    metrics jsonb,
    is_approved boolean DEFAULT false NOT NULL,
    source text,
    CONSTRAINT ck_proof_point_ck_proof_point_kind_valid CHECK ((kind = ANY (ARRAY['case_study'::text, 'metric'::text, 'logo'::text, 'testimonial'::text])))
);


--
-- Name: qualification; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qualification (
    account_id uuid NOT NULL,
    context_id uuid,
    run_id uuid,
    fit_score numeric(5,2),
    opportunity_score numeric(5,2),
    buyer_score numeric(5,2),
    commercial_score numeric(5,2),
    intent_score numeric(5,2),
    engagement_score numeric(5,2),
    priority_score numeric(5,2) NOT NULL,
    priority_band text NOT NULL,
    reasons jsonb NOT NULL,
    man_money text,
    man_authority text,
    man_need text,
    scoring_config_version integer NOT NULL,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    CONSTRAINT ck_qualification_band_valid CHECK ((priority_band = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text]))),
    CONSTRAINT ck_qualification_priority_is_a_percentage CHECK (((priority_score >= (0)::numeric) AND (priority_score <= (100)::numeric)))
);


--
-- Name: research_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.research_config (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    version integer NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    freshness_days integer DEFAULT 30 NOT NULL,
    CONSTRAINT ck_research_config_freshness_is_a_day_to_a_year CHECK (((freshness_days >= 1) AND (freshness_days <= 365)))
);


--
-- Name: research_coverage; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.research_coverage (
    run_id uuid NOT NULL,
    account_id uuid NOT NULL,
    family text NOT NULL,
    status text NOT NULL,
    evidence_count integer DEFAULT 0 NOT NULL,
    detail text,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    not_found jsonb DEFAULT '[]'::jsonb NOT NULL,
    contact_id uuid,
    notes jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT ck_research_coverage_count_matches_status CHECK (((status = 'ran'::text) = (evidence_count > 0))),
    CONSTRAINT ck_research_coverage_count_non_negative CHECK ((evidence_count >= 0)),
    CONSTRAINT ck_research_coverage_failed_needs_a_reason CHECK (((status <> 'failed'::text) OR (detail IS NOT NULL))),
    CONSTRAINT ck_research_coverage_status_valid CHECK ((status = ANY (ARRAY['ran'::text, 'empty'::text, 'failed'::text, 'skipped'::text])))
);


--
-- Name: research_source; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.research_source (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    key text NOT NULL,
    label text NOT NULL,
    description text NOT NULL,
    kind text DEFAULT 'search'::text NOT NULL,
    scopes jsonb DEFAULT '["company"]'::jsonb NOT NULL,
    support_only boolean DEFAULT false NOT NULL,
    reuse_days integer,
    builtin boolean DEFAULT false NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    CONSTRAINT ck_research_source_kind_valid CHECK ((kind = ANY (ARRAY['search'::text, 'fetch'::text, 'provider'::text, 'manual'::text]))),
    CONSTRAINT ck_research_source_reuse_days_positive CHECK (((reuse_days IS NULL) OR (reuse_days > 0))),
    CONSTRAINT ck_research_source_scopes_not_empty CHECK ((jsonb_array_length(scopes) > 0)),
    CONSTRAINT ck_research_source_status_valid CHECK ((status = ANY (ARRAY['active'::text, 'paused'::text, 'deprecated'::text])))
);


--
-- Name: run; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.run (
    account_id uuid,
    list_id uuid,
    objective text,
    stage text DEFAULT 'resolution'::text NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    triggered_by text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    input_tokens bigint,
    output_tokens bigint,
    cache_read_tokens bigint,
    error text,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    mode text DEFAULT 'production'::text NOT NULL,
    icp_version_ids jsonb,
    CONSTRAINT ck_run_failed_needs_an_error CHECK (((status <> 'failed'::text) OR (error IS NOT NULL))),
    CONSTRAINT ck_run_stage_valid CHECK ((stage = ANY (ARRAY['resolution'::text, 'research'::text, 'signals'::text, 'context'::text, 'qualification'::text, 'strategy'::text, 'content'::text, 'evaluation'::text, 'awaiting_approval'::text, 'done'::text]))),
    CONSTRAINT ck_run_status_valid CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'succeeded'::text, 'failed'::text, 'cancelled'::text])))
);


--
-- Name: sales_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sales_rules (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    version integer NOT NULL,
    priority_threshold numeric(5,2) NOT NULL,
    persona_weight_threshold numeric(5,2) NOT NULL,
    max_concurrent_threads integer DEFAULT 2 NOT NULL,
    thread_start_offset_days integer DEFAULT 3 NOT NULL,
    signal_ttl_days jsonb DEFAULT '{}'::jsonb NOT NULL,
    sample_rate numeric(4,3) DEFAULT 0.40 NOT NULL,
    no_go jsonb,
    compliance jsonb,
    is_active boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_sales_rules_ck_sales_rules_sample_rate_range CHECK (((sample_rate > (0)::numeric) AND (sample_rate <= (1)::numeric))),
    CONSTRAINT ck_sales_rules_ck_sales_rules_thread_cap_positive CHECK ((max_concurrent_threads > 0))
);


--
-- Name: scoring_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scoring_config (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    version integer NOT NULL,
    dimension_weights jsonb NOT NULL,
    persona_role_weights jsonb DEFAULT '{}'::jsonb NOT NULL,
    band_cutoffs jsonb NOT NULL,
    man_view_enabled boolean DEFAULT true NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    industry_multipliers jsonb DEFAULT '{}'::jsonb NOT NULL,
    size_multipliers jsonb DEFAULT '{}'::jsonb NOT NULL,
    min_queue_band text DEFAULT 'low'::text NOT NULL,
    CONSTRAINT ck_scoring_config_min_queue_band_valid CHECK ((min_queue_band = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text])))
);


--
-- Name: service_catalog; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.service_catalog (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    code text NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    positioning_angles jsonb,
    is_active boolean DEFAULT true NOT NULL,
    economic_buyer text
);


--
-- Name: service_icp_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.service_icp_link (
    service_id uuid NOT NULL,
    icp_profile_id uuid NOT NULL
);


--
-- Name: signal; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.signal (
    account_id uuid NOT NULL,
    contact_id uuid,
    run_id uuid,
    signal_type text NOT NULL,
    scope text NOT NULL,
    summary text NOT NULL,
    business_implication text,
    strength text NOT NULL,
    confidence numeric(4,3) NOT NULL,
    observed_at date NOT NULL,
    expires_at date,
    lifecycle_state text DEFAULT 'discovered'::text NOT NULL,
    is_hypothesis boolean DEFAULT false NOT NULL,
    superseded_by uuid,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    CONSTRAINT ck_signal_confidence_is_a_proportion CHECK (((confidence >= (0)::numeric) AND (confidence <= (1)::numeric))),
    CONSTRAINT ck_signal_contact_id_matches_scope CHECK ((((scope = 'contact'::text) AND (contact_id IS NOT NULL)) OR ((scope = 'company'::text) AND (contact_id IS NULL)))),
    CONSTRAINT ck_signal_expiry_after_observation CHECK (((expires_at IS NULL) OR (expires_at >= observed_at))),
    CONSTRAINT ck_signal_lifecycle_state_valid CHECK ((lifecycle_state = ANY (ARRAY['discovered'::text, 'validated'::text, 'active'::text, 'stale'::text, 'expired'::text]))),
    CONSTRAINT ck_signal_scope_valid CHECK ((scope = ANY (ARRAY['company'::text, 'contact'::text]))),
    CONSTRAINT ck_signal_strength_valid CHECK ((strength = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text])))
);


--
-- Name: signal_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.signal_type (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    key text NOT NULL,
    label text NOT NULL,
    description text,
    scope text NOT NULL,
    default_ttl_days integer NOT NULL,
    weight numeric(4,2) DEFAULT 1.00 NOT NULL,
    produced_by text[] DEFAULT '{}'::text[] NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    deprecated_at timestamp with time zone,
    paused_at timestamp with time zone,
    search_instruction text,
    search_group text,
    kind text DEFAULT 'event'::text NOT NULL,
    durability_days integer,
    CONSTRAINT ck_signal_type_ck_signal_type_deprecated_at_consistent CHECK (((status = 'deprecated'::text) = (deprecated_at IS NOT NULL))),
    CONSTRAINT ck_signal_type_ck_signal_type_scope_valid CHECK ((scope = ANY (ARRAY['company'::text, 'contact'::text]))),
    CONSTRAINT ck_signal_type_ck_signal_type_ttl_positive CHECK ((default_ttl_days > 0)),
    CONSTRAINT ck_signal_type_ck_signal_type_weight_non_negative CHECK ((weight >= (0)::numeric)),
    CONSTRAINT ck_signal_type_durability_covers_ttl CHECK (((durability_days IS NULL) OR (durability_days >= default_ttl_days))),
    CONSTRAINT ck_signal_type_kind_valid CHECK ((kind = ANY (ARRAY['event'::text, 'theme'::text]))),
    CONSTRAINT ck_signal_type_paused_at_consistent CHECK (((status = 'paused'::text) = (paused_at IS NOT NULL))),
    CONSTRAINT ck_signal_type_status_valid CHECK ((status = ANY (ARRAY['active'::text, 'paused'::text, 'deprecated'::text])))
);


--
-- Name: signal_current; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.signal_current AS
 SELECT s.account_id,
    s.contact_id,
    s.run_id,
    s.signal_type,
    s.scope,
    s.summary,
    s.business_implication,
    s.strength,
    s.confidence,
    s.observed_at,
    s.expires_at,
    s.lifecycle_state,
    s.is_hypothesis,
    s.superseded_by,
    s.id,
    s.created_at,
    s.updated_at,
    st.weight AS type_weight,
    st.label AS type_label,
        CASE
            WHEN ((s.expires_at IS NOT NULL) AND (s.expires_at < CURRENT_DATE)) THEN 'expired'::text
            WHEN ((s.expires_at IS NOT NULL) AND (s.expires_at < (CURRENT_DATE + 30))) THEN 'stale'::text
            ELSE s.lifecycle_state
        END AS effective_state
   FROM (public.signal s
     JOIN public.signal_type st ON ((st.key = s.signal_type)))
  WHERE (st.status = 'active'::text);


--
-- Name: signal_evidence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.signal_evidence (
    signal_id uuid NOT NULL,
    evidence_id uuid NOT NULL,
    role text DEFAULT 'supporting'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_signal_evidence_role_valid CHECK ((role = ANY (ARRAY['primary'::text, 'supporting'::text])))
);


--
-- Name: strategy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.strategy (
    account_id uuid NOT NULL,
    qualification_id uuid,
    run_id uuid,
    version integer NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    campaign_id uuid,
    service_id uuid,
    icp_profile_id uuid,
    CONSTRAINT ck_strategy_status_valid CHECK ((status = ANY (ARRAY['draft'::text, 'evaluated'::text, 'approved'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT ck_strategy_version_positive CHECK ((version > 0))
);


--
-- Name: strategy_thread; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.strategy_thread (
    strategy_id uuid NOT NULL,
    contact_id uuid NOT NULL,
    service_id uuid NOT NULL,
    weight numeric(5,2) NOT NULL,
    rank integer NOT NULL,
    thread_status text NOT NULL,
    problem_hypothesis text NOT NULL,
    trigger_summary text NOT NULL,
    trigger_signal_ids jsonb NOT NULL,
    positioning text NOT NULL,
    channel_sequence jsonb NOT NULL,
    cta text NOT NULL,
    avoid_list jsonb,
    confidence numeric(4,3),
    start_offset_days integer DEFAULT 0 NOT NULL,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    chosen_by_rep boolean DEFAULT false NOT NULL,
    without_live_trigger boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_strategy_thread_confidence_is_a_proportion CHECK (((confidence IS NULL) OR ((confidence >= (0)::numeric) AND (confidence <= (1)::numeric)))),
    CONSTRAINT ck_strategy_thread_offset_non_negative CHECK ((start_offset_days >= 0)),
    CONSTRAINT ck_strategy_thread_primary_is_rank_one CHECK (((thread_status <> 'active_primary'::text) OR (rank = 1))),
    CONSTRAINT ck_strategy_thread_rank_positive CHECK ((rank > 0)),
    CONSTRAINT ck_strategy_thread_thread_status_valid CHECK ((thread_status = ANY (ARRAY['active_primary'::text, 'active_secondary'::text, 'queued'::text, 'not_activated'::text]))),
    CONSTRAINT ck_strategy_thread_threads_cite_a_trigger CHECK ((without_live_trigger OR (jsonb_array_length(trigger_signal_ids) > 0)))
);


--
-- Name: touch; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.touch (
    sequence_id uuid NOT NULL,
    step_no integer NOT NULL,
    day_offset integer,
    channel text NOT NULL,
    purpose text,
    status text DEFAULT 'pending'::text NOT NULL,
    scheduled_at timestamp with time zone,
    sent_at timestamp with time zone,
    lgm_step_id text,
    lgm_attribute text,
    content_sync_status text DEFAULT 'pending'::text NOT NULL,
    content_written_at timestamp with time zone,
    stop_reason text,
    subject_source text DEFAULT 'lgm_template'::text NOT NULL,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    CONSTRAINT ck_touch_channel_valid CHECK ((channel = ANY (ARRAY['linkedin_connect'::text, 'linkedin_message'::text, 'linkedin_engage'::text, 'inmail'::text, 'email'::text]))),
    CONSTRAINT ck_touch_day_offset_non_negative CHECK (((day_offset IS NULL) OR (day_offset >= 0))),
    CONSTRAINT ck_touch_only_sent_touches_have_a_sent_at CHECK (((sent_at IS NULL) OR (status = 'sent'::text))),
    CONSTRAINT ck_touch_status_valid CHECK ((status = ANY (ARRAY['pending'::text, 'scheduled'::text, 'sent'::text, 'skipped'::text, 'failed'::text]))),
    CONSTRAINT ck_touch_step_positive CHECK ((step_no > 0)),
    CONSTRAINT ck_touch_stop_reason_valid CHECK (((stop_reason IS NULL) OR (stop_reason = ANY (ARRAY['signal_expired'::text, 'reply_received'::text, 'compliance'::text, 'manual'::text])))),
    CONSTRAINT ck_touch_subject_source_valid CHECK ((subject_source = ANY (ARRAY['lgm_template'::text, 'custom_attribute'::text]))),
    CONSTRAINT ck_touch_sync_status_valid CHECK ((content_sync_status = ANY (ARRAY['pending'::text, 'written'::text, 'failed'::text]))),
    CONSTRAINT ck_touch_written_names_its_attribute CHECK (((content_sync_status <> 'written'::text) OR (lgm_attribute IS NOT NULL)))
);


--
-- Name: writing_sample; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.writing_sample (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    channel text NOT NULL,
    subject text,
    body text NOT NULL,
    notes text,
    is_active boolean DEFAULT true NOT NULL,
    CONSTRAINT ck_writing_sample_ck_writing_sample_channel_valid CHECK ((channel = ANY (ARRAY['linkedin'::text, 'email'::text])))
);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: evidence evidence_dedup; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence
    ADD CONSTRAINT evidence_dedup UNIQUE (account_id, excerpt_hash);


--
-- Name: signal_type key_scope; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal_type
    ADD CONSTRAINT key_scope UNIQUE (key, scope);


--
-- Name: persona_service_score one_cell_per_pair; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_service_score
    ADD CONSTRAINT one_cell_per_pair UNIQUE (strategy_id, contact_id, service_id);


--
-- Name: deferred_enrolment one_deferral_per_pair; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deferred_enrolment
    ADD CONSTRAINT one_deferral_per_pair UNIQUE (campaign_id, contact_id);


--
-- Name: draft one_draft_per_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.draft
    ADD CONSTRAINT one_draft_per_version UNIQUE (touch_id, version);


--
-- Name: campaign_queue_member one_membership_per_queue; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue_member
    ADD CONSTRAINT one_membership_per_queue UNIQUE (queue_id, account_id);


--
-- Name: execution_record one_record_per_touch_outcome; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.execution_record
    ADD CONSTRAINT one_record_per_touch_outcome UNIQUE (touch_id, status);


--
-- Name: research_coverage one_row_per_family_per_run; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_coverage
    ADD CONSTRAINT one_row_per_family_per_run UNIQUE NULLS NOT DISTINCT (run_id, family, contact_id);


--
-- Name: account_context one_row_per_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_context
    ADD CONSTRAINT one_row_per_version UNIQUE (account_id, version);


--
-- Name: outreach_campaign_source one_source_per_pair; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_campaign_source
    ADD CONSTRAINT one_source_per_pair UNIQUE (campaign_id, queue_id);


--
-- Name: strategy one_strategy_version_per_account; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy
    ADD CONSTRAINT one_strategy_version_per_account UNIQUE (account_id, version);


--
-- Name: strategy_thread one_thread_per_contact; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_thread
    ADD CONSTRAINT one_thread_per_contact UNIQUE (strategy_id, contact_id);


--
-- Name: touch one_touch_per_step; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.touch
    ADD CONSTRAINT one_touch_per_step UNIQUE (sequence_id, step_no);


--
-- Name: account pk_account; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account
    ADD CONSTRAINT pk_account PRIMARY KEY (id);


--
-- Name: account_alias pk_account_alias; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_alias
    ADD CONSTRAINT pk_account_alias PRIMARY KEY (id);


--
-- Name: account_context pk_account_context; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_context
    ADD CONSTRAINT pk_account_context PRIMARY KEY (id);


--
-- Name: account_list pk_account_list; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_list
    ADD CONSTRAINT pk_account_list PRIMARY KEY (id);


--
-- Name: account_list_icp pk_account_list_icp; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_list_icp
    ADD CONSTRAINT pk_account_list_icp PRIMARY KEY (list_id, icp_profile_id);


--
-- Name: account_list_member pk_account_list_member; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_list_member
    ADD CONSTRAINT pk_account_list_member PRIMARY KEY (id);


--
-- Name: account_list_service pk_account_list_service; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_list_service
    ADD CONSTRAINT pk_account_list_service PRIMARY KEY (list_id, service_id);


--
-- Name: approval pk_approval; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval
    ADD CONSTRAINT pk_approval PRIMARY KEY (id);


--
-- Name: approval_sample pk_approval_sample; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_sample
    ADD CONSTRAINT pk_approval_sample PRIMARY KEY (id);


--
-- Name: cadence_shape pk_cadence_shape; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cadence_shape
    ADD CONSTRAINT pk_cadence_shape PRIMARY KEY (id);


--
-- Name: campaign_queue pk_campaign_queue; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue
    ADD CONSTRAINT pk_campaign_queue PRIMARY KEY (id);


--
-- Name: campaign_queue_contact pk_campaign_queue_contact; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue_contact
    ADD CONSTRAINT pk_campaign_queue_contact PRIMARY KEY (id);


--
-- Name: campaign_queue_member pk_campaign_queue_member; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue_member
    ADD CONSTRAINT pk_campaign_queue_member PRIMARY KEY (id);


--
-- Name: contact pk_contact; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contact
    ADD CONSTRAINT pk_contact PRIMARY KEY (id);


--
-- Name: contact_suggestion pk_contact_suggestion; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contact_suggestion
    ADD CONSTRAINT pk_contact_suggestion PRIMARY KEY (id);


--
-- Name: deferred_enrolment pk_deferred_enrolment; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deferred_enrolment
    ADD CONSTRAINT pk_deferred_enrolment PRIMARY KEY (id);


--
-- Name: draft pk_draft; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.draft
    ADD CONSTRAINT pk_draft PRIMARY KEY (id);


--
-- Name: enrichment_config pk_enrichment_config; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enrichment_config
    ADD CONSTRAINT pk_enrichment_config PRIMARY KEY (id);


--
-- Name: evaluation pk_evaluation; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluation
    ADD CONSTRAINT pk_evaluation PRIMARY KEY (id);


--
-- Name: evidence pk_evidence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence
    ADD CONSTRAINT pk_evidence PRIMARY KEY (id);


--
-- Name: execution_record pk_execution_record; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.execution_record
    ADD CONSTRAINT pk_execution_record PRIMARY KEY (id);


--
-- Name: icp_profile pk_icp_profile; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icp_profile
    ADD CONSTRAINT pk_icp_profile PRIMARY KEY (id);


--
-- Name: icp_profile_version pk_icp_profile_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icp_profile_version
    ADD CONSTRAINT pk_icp_profile_version PRIMARY KEY (id);


--
-- Name: installation_mode pk_installation_mode; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.installation_mode
    ADD CONSTRAINT pk_installation_mode PRIMARY KEY (id);


--
-- Name: integration_credential pk_integration_credential; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.integration_credential
    ADD CONSTRAINT pk_integration_credential PRIMARY KEY (id);


--
-- Name: lgm_identity pk_lgm_identity; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lgm_identity
    ADD CONSTRAINT pk_lgm_identity PRIMARY KEY (id);


--
-- Name: llm_call pk_llm_call; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_call
    ADD CONSTRAINT pk_llm_call PRIMARY KEY (id);


--
-- Name: llm_config pk_llm_config; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_config
    ADD CONSTRAINT pk_llm_config PRIMARY KEY (id);


--
-- Name: model_availability pk_model_availability; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_availability
    ADD CONSTRAINT pk_model_availability PRIMARY KEY (id);


--
-- Name: org_profile pk_org_profile; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_profile
    ADD CONSTRAINT pk_org_profile PRIMARY KEY (id);


--
-- Name: outreach_campaign pk_outreach_campaign; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_campaign
    ADD CONSTRAINT pk_outreach_campaign PRIMARY KEY (id);


--
-- Name: outreach_campaign_source pk_outreach_campaign_source; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_campaign_source
    ADD CONSTRAINT pk_outreach_campaign_source PRIMARY KEY (id);


--
-- Name: outreach_event pk_outreach_event; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_event
    ADD CONSTRAINT pk_outreach_event PRIMARY KEY (id);


--
-- Name: outreach_sequence pk_outreach_sequence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_sequence
    ADD CONSTRAINT pk_outreach_sequence PRIMARY KEY (id);


--
-- Name: persona_service_score pk_persona_service_score; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_service_score
    ADD CONSTRAINT pk_persona_service_score PRIMARY KEY (id);


--
-- Name: proof_point pk_proof_point; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proof_point
    ADD CONSTRAINT pk_proof_point PRIMARY KEY (id);


--
-- Name: qualification pk_qualification; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qualification
    ADD CONSTRAINT pk_qualification PRIMARY KEY (id);


--
-- Name: research_config pk_research_config; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_config
    ADD CONSTRAINT pk_research_config PRIMARY KEY (id);


--
-- Name: research_coverage pk_research_coverage; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_coverage
    ADD CONSTRAINT pk_research_coverage PRIMARY KEY (id);


--
-- Name: research_source pk_research_source; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_source
    ADD CONSTRAINT pk_research_source PRIMARY KEY (id);


--
-- Name: run pk_run; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run
    ADD CONSTRAINT pk_run PRIMARY KEY (id);


--
-- Name: sales_rules pk_sales_rules; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sales_rules
    ADD CONSTRAINT pk_sales_rules PRIMARY KEY (id);


--
-- Name: scoring_config pk_scoring_config; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scoring_config
    ADD CONSTRAINT pk_scoring_config PRIMARY KEY (id);


--
-- Name: service_catalog pk_service_catalog; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.service_catalog
    ADD CONSTRAINT pk_service_catalog PRIMARY KEY (id);


--
-- Name: service_icp_link pk_service_icp_link; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.service_icp_link
    ADD CONSTRAINT pk_service_icp_link PRIMARY KEY (service_id, icp_profile_id);


--
-- Name: signal pk_signal; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal
    ADD CONSTRAINT pk_signal PRIMARY KEY (id);


--
-- Name: signal_evidence pk_signal_evidence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal_evidence
    ADD CONSTRAINT pk_signal_evidence PRIMARY KEY (signal_id, evidence_id);


--
-- Name: signal_type pk_signal_type; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal_type
    ADD CONSTRAINT pk_signal_type PRIMARY KEY (id);


--
-- Name: strategy pk_strategy; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy
    ADD CONSTRAINT pk_strategy PRIMARY KEY (id);


--
-- Name: strategy_thread pk_strategy_thread; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_thread
    ADD CONSTRAINT pk_strategy_thread PRIMARY KEY (id);


--
-- Name: touch pk_touch; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.touch
    ADD CONSTRAINT pk_touch PRIMARY KEY (id);


--
-- Name: writing_sample pk_writing_sample; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.writing_sample
    ADD CONSTRAINT pk_writing_sample PRIMARY KEY (id);


--
-- Name: account_alias uq_account_alias; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_alias
    ADD CONSTRAINT uq_account_alias UNIQUE (alias, alias_type);


--
-- Name: cadence_shape uq_cadence_shape_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cadence_shape
    ADD CONSTRAINT uq_cadence_shape_key UNIQUE (key);


--
-- Name: campaign_queue_contact uq_campaign_queue_contact_queue_contact; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue_contact
    ADD CONSTRAINT uq_campaign_queue_contact_queue_contact UNIQUE (queue_id, contact_id);


--
-- Name: contact_suggestion uq_contact_suggestion_account_person; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contact_suggestion
    ADD CONSTRAINT uq_contact_suggestion_account_person UNIQUE (account_id, apollo_person_id);


--
-- Name: integration_credential uq_credential_provider_type; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.integration_credential
    ADD CONSTRAINT uq_credential_provider_type UNIQUE (provider, credential_type);


--
-- Name: enrichment_config uq_enrichment_config_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enrichment_config
    ADD CONSTRAINT uq_enrichment_config_version UNIQUE (version);


--
-- Name: icp_profile uq_icp_profile_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icp_profile
    ADD CONSTRAINT uq_icp_profile_name UNIQUE (name);


--
-- Name: icp_profile_version uq_icp_profile_version_number; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icp_profile_version
    ADD CONSTRAINT uq_icp_profile_version_number UNIQUE (icp_profile_id, version);


--
-- Name: installation_mode uq_installation_mode_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.installation_mode
    ADD CONSTRAINT uq_installation_mode_version UNIQUE (version);


--
-- Name: lgm_identity uq_lgm_identity_email; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lgm_identity
    ADD CONSTRAINT uq_lgm_identity_email UNIQUE (email);


--
-- Name: lgm_identity uq_lgm_identity_linkedin_slug; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lgm_identity
    ADD CONSTRAINT uq_lgm_identity_linkedin_slug UNIQUE (linkedin_slug);


--
-- Name: lgm_identity uq_lgm_identity_name_company_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lgm_identity
    ADD CONSTRAINT uq_lgm_identity_name_company_key UNIQUE (name_company_key);


--
-- Name: account_list_member uq_list_member; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_list_member
    ADD CONSTRAINT uq_list_member UNIQUE (list_id, account_id);


--
-- Name: llm_config uq_llm_config_scenario_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_config
    ADD CONSTRAINT uq_llm_config_scenario_version UNIQUE (scenario, version);


--
-- Name: model_availability uq_model_availability_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_availability
    ADD CONSTRAINT uq_model_availability_version UNIQUE (version);


--
-- Name: org_profile uq_org_profile_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_profile
    ADD CONSTRAINT uq_org_profile_version UNIQUE (version);


--
-- Name: research_config uq_research_config_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_config
    ADD CONSTRAINT uq_research_config_version UNIQUE (version);


--
-- Name: research_source uq_research_source_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_source
    ADD CONSTRAINT uq_research_source_key UNIQUE (key);


--
-- Name: sales_rules uq_sales_rules_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sales_rules
    ADD CONSTRAINT uq_sales_rules_version UNIQUE (version);


--
-- Name: scoring_config uq_scoring_config_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scoring_config
    ADD CONSTRAINT uq_scoring_config_version UNIQUE (version);


--
-- Name: service_catalog uq_service_catalog_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.service_catalog
    ADD CONSTRAINT uq_service_catalog_code UNIQUE (code);


--
-- Name: signal_type uq_signal_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal_type
    ADD CONSTRAINT uq_signal_type_key UNIQUE (key);


--
-- Name: evidence_by_contact; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX evidence_by_contact ON public.evidence USING btree (contact_id) WHERE (contact_id IS NOT NULL);


--
-- Name: evidence_by_run_family; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX evidence_by_run_family ON public.evidence USING btree (run_id, family);


--
-- Name: evidence_by_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX evidence_by_source ON public.evidence USING btree (account_id, source_hash);


--
-- Name: evidence_by_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX evidence_by_type ON public.evidence USING btree (account_id, source_type);


--
-- Name: ix_account_context_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_account_context_account ON public.account_context USING btree (account_id, version);


--
-- Name: ix_account_dormant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_account_dormant ON public.account USING btree (dormant_at) WHERE (dormant_at IS NOT NULL);


--
-- Name: ix_account_industry_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_account_industry_key ON public.account USING btree (industry_key);


--
-- Name: ix_account_list_icp_icp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_account_list_icp_icp ON public.account_list_icp USING btree (icp_profile_id);


--
-- Name: ix_account_resolution_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_account_resolution_status ON public.account USING btree (resolution_status);


--
-- Name: ix_account_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_account_status ON public.account USING btree (status);


--
-- Name: ix_approval_sample; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_approval_sample ON public.approval USING btree (sample_id);


--
-- Name: ix_approval_subject; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_approval_subject ON public.approval USING btree (subject_type, subject_id);


--
-- Name: ix_campaign_queue_contact_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_campaign_queue_contact_account ON public.campaign_queue_contact USING btree (account_id);


--
-- Name: ix_campaign_queue_contact_queue; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_campaign_queue_contact_queue ON public.campaign_queue_contact USING btree (queue_id);


--
-- Name: ix_campaign_queue_member_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_campaign_queue_member_account ON public.campaign_queue_member USING btree (account_id);


--
-- Name: ix_contact_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_contact_account ON public.contact USING btree (account_id);


--
-- Name: ix_contact_apollo_person; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_contact_apollo_person ON public.contact USING btree (apollo_person_id);


--
-- Name: ix_contact_do_not_contact; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_contact_do_not_contact ON public.contact USING btree (account_id) WHERE do_not_contact;


--
-- Name: ix_contact_suggestion_list; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_contact_suggestion_list ON public.contact_suggestion USING btree (list_id, status);


--
-- Name: ix_evaluation_subject; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evaluation_subject ON public.evaluation USING btree (subject_type, subject_id);


--
-- Name: ix_execution_record_sequence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_execution_record_sequence ON public.execution_record USING btree (sequence_id);


--
-- Name: ix_list_member_list; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_list_member_list ON public.account_list_member USING btree (list_id);


--
-- Name: ix_llm_call_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_call_created_at ON public.llm_call USING btree (created_at);


--
-- Name: ix_llm_call_scenario; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_call_scenario ON public.llm_call USING btree (scenario, created_at);


--
-- Name: ix_outreach_event_campaign; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outreach_event_campaign ON public.outreach_event USING btree (campaign_id, occurred_at);


--
-- Name: ix_outreach_event_contact; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outreach_event_contact ON public.outreach_event USING btree (contact_id, occurred_at);


--
-- Name: ix_outreach_sequence_campaign; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outreach_sequence_campaign ON public.outreach_sequence USING btree (campaign_id);


--
-- Name: ix_outreach_sequence_contact; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outreach_sequence_contact ON public.outreach_sequence USING btree (contact_id);


--
-- Name: ix_persona_service_score_strategy; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_persona_service_score_strategy ON public.persona_service_score USING btree (strategy_id);


--
-- Name: ix_proof_point_approved; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proof_point_approved ON public.proof_point USING btree (service_id) WHERE is_approved;


--
-- Name: ix_proof_point_service_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proof_point_service_id ON public.proof_point USING btree (service_id);


--
-- Name: ix_qualification_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_qualification_account ON public.qualification USING btree (account_id);


--
-- Name: ix_qualification_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_qualification_priority ON public.qualification USING btree (priority_band, priority_score);


--
-- Name: ix_research_coverage_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_research_coverage_account ON public.research_coverage USING btree (account_id);


--
-- Name: ix_run_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_run_account ON public.run USING btree (account_id);


--
-- Name: ix_service_icp_link_icp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_service_icp_link_icp ON public.service_icp_link USING btree (icp_profile_id);


--
-- Name: ix_signal_type_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_signal_type_active ON public.signal_type USING btree (scope) WHERE (status = 'active'::text);


--
-- Name: ix_signal_type_search_group; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_signal_type_search_group ON public.signal_type USING btree (search_group) WHERE (search_group IS NOT NULL);


--
-- Name: ix_strategy_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_strategy_account ON public.strategy USING btree (account_id, version);


--
-- Name: ix_strategy_campaign; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_strategy_campaign ON public.strategy USING btree (campaign_id, account_id);


--
-- Name: ix_strategy_thread_strategy; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_strategy_thread_strategy ON public.strategy_thread USING btree (strategy_id, rank);


--
-- Name: ix_touch_sequence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_touch_sequence ON public.touch USING btree (sequence_id, step_no);


--
-- Name: one_active_sequence_per_lgm_identity; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX one_active_sequence_per_lgm_identity ON public.outreach_sequence USING btree (lgm_identity_id) WHERE (status = ANY (ARRAY['pending_approval'::text, 'approved'::text, 'executing'::text, 'paused'::text]));


--
-- Name: one_current_draft_per_touch; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX one_current_draft_per_touch ON public.draft USING btree (touch_id) WHERE is_current;


--
-- Name: one_current_sample_per_campaign; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX one_current_sample_per_campaign ON public.approval_sample USING btree (campaign_id) WHERE is_current;


--
-- Name: signal_by_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX signal_by_account ON public.signal USING btree (account_id, lifecycle_state);


--
-- Name: signal_by_contact; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX signal_by_contact ON public.signal USING btree (contact_id) WHERE (contact_id IS NOT NULL);


--
-- Name: signal_evidence_by_evidence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX signal_evidence_by_evidence ON public.signal_evidence USING btree (evidence_id);


--
-- Name: signal_live; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX signal_live ON public.signal USING btree (account_id, expires_at) WHERE (lifecycle_state = ANY (ARRAY['validated'::text, 'active'::text]));


--
-- Name: uq_account_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_account_domain ON public.account USING btree (lower(domain)) WHERE (domain IS NOT NULL);


--
-- Name: uq_contact_email_per_account; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_contact_email_per_account ON public.contact USING btree (account_id, lower(email)) WHERE (email IS NOT NULL);


--
-- Name: uq_enrichment_config_single_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_enrichment_config_single_active ON public.enrichment_config USING btree ((true)) WHERE is_active;


--
-- Name: uq_icp_profile_single_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_icp_profile_single_active ON public.icp_profile_version USING btree (icp_profile_id) WHERE is_active;


--
-- Name: uq_installation_mode_single_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_installation_mode_single_active ON public.installation_mode USING btree ((true)) WHERE is_active;


--
-- Name: uq_llm_config_active_per_scenario; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_llm_config_active_per_scenario ON public.llm_config USING btree (scenario) WHERE is_active;


--
-- Name: uq_model_availability_single_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_model_availability_single_active ON public.model_availability USING btree ((true)) WHERE is_active;


--
-- Name: uq_org_profile_single_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_org_profile_single_active ON public.org_profile USING btree ((true)) WHERE is_active;


--
-- Name: uq_outreach_event_external; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_outreach_event_external ON public.outreach_event USING btree (source, external_id) WHERE (external_id IS NOT NULL);


--
-- Name: uq_research_config_single_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_research_config_single_active ON public.research_config USING btree ((true)) WHERE is_active;


--
-- Name: uq_sales_rules_single_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_sales_rules_single_active ON public.sales_rules USING btree ((true)) WHERE is_active;


--
-- Name: uq_scoring_config_single_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_scoring_config_single_active ON public.scoring_config USING btree ((true)) WHERE is_active;


--
-- Name: execution_record execution_approval_required; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER execution_approval_required BEFORE INSERT OR UPDATE ON public.execution_record FOR EACH ROW EXECUTE FUNCTION public.execution_requires_approval();


--
-- Name: signal signal_evidence_required; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER signal_evidence_required AFTER INSERT ON public.signal DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.signal_requires_evidence();


--
-- Name: account_alias fk_account_alias_account_id_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_alias
    ADD CONSTRAINT fk_account_alias_account_id_account FOREIGN KEY (account_id) REFERENCES public.account(id) ON DELETE CASCADE;


--
-- Name: account_context fk_account_context_account_id_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_context
    ADD CONSTRAINT fk_account_context_account_id_account FOREIGN KEY (account_id) REFERENCES public.account(id) ON DELETE CASCADE;


--
-- Name: account_context fk_account_context_run_id_run; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_context
    ADD CONSTRAINT fk_account_context_run_id_run FOREIGN KEY (run_id) REFERENCES public.run(id);


--
-- Name: account_list_icp fk_account_list_icp_icp_profile_id_icp_profile; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_list_icp
    ADD CONSTRAINT fk_account_list_icp_icp_profile_id_icp_profile FOREIGN KEY (icp_profile_id) REFERENCES public.icp_profile(id) ON DELETE CASCADE;


--
-- Name: account_list_icp fk_account_list_icp_list_id_account_list; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_list_icp
    ADD CONSTRAINT fk_account_list_icp_list_id_account_list FOREIGN KEY (list_id) REFERENCES public.account_list(id) ON DELETE CASCADE;


--
-- Name: account_list_member fk_account_list_member_account_id_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_list_member
    ADD CONSTRAINT fk_account_list_member_account_id_account FOREIGN KEY (account_id) REFERENCES public.account(id) ON DELETE CASCADE;


--
-- Name: account_list_member fk_account_list_member_list_id_account_list; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_list_member
    ADD CONSTRAINT fk_account_list_member_list_id_account_list FOREIGN KEY (list_id) REFERENCES public.account_list(id) ON DELETE CASCADE;


--
-- Name: account_list_service fk_account_list_service_list_id_account_list; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_list_service
    ADD CONSTRAINT fk_account_list_service_list_id_account_list FOREIGN KEY (list_id) REFERENCES public.account_list(id) ON DELETE CASCADE;


--
-- Name: account_list_service fk_account_list_service_service_id_service_catalog; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_list_service
    ADD CONSTRAINT fk_account_list_service_service_id_service_catalog FOREIGN KEY (service_id) REFERENCES public.service_catalog(id) ON DELETE CASCADE;


--
-- Name: approval_sample fk_approval_sample_campaign_id_outreach_campaign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_sample
    ADD CONSTRAINT fk_approval_sample_campaign_id_outreach_campaign FOREIGN KEY (campaign_id) REFERENCES public.outreach_campaign(id) ON DELETE CASCADE;


--
-- Name: approval fk_approval_sample_id_approval_sample; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval
    ADD CONSTRAINT fk_approval_sample_id_approval_sample FOREIGN KEY (sample_id) REFERENCES public.approval_sample(id);


--
-- Name: campaign_queue fk_campaign_queue_cloned_from_queue_id_campaign_queue; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue
    ADD CONSTRAINT fk_campaign_queue_cloned_from_queue_id_campaign_queue FOREIGN KEY (cloned_from_queue_id) REFERENCES public.campaign_queue(id);


--
-- Name: campaign_queue_contact fk_campaign_queue_contact_account_id_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue_contact
    ADD CONSTRAINT fk_campaign_queue_contact_account_id_account FOREIGN KEY (account_id) REFERENCES public.account(id) ON DELETE CASCADE;


--
-- Name: campaign_queue_contact fk_campaign_queue_contact_contact_id_contact; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue_contact
    ADD CONSTRAINT fk_campaign_queue_contact_contact_id_contact FOREIGN KEY (contact_id) REFERENCES public.contact(id) ON DELETE CASCADE;


--
-- Name: campaign_queue_contact fk_campaign_queue_contact_queue_id_campaign_queue; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue_contact
    ADD CONSTRAINT fk_campaign_queue_contact_queue_id_campaign_queue FOREIGN KEY (queue_id) REFERENCES public.campaign_queue(id) ON DELETE CASCADE;


--
-- Name: campaign_queue_contact fk_campaign_queue_contact_source_list_id_account_list; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue_contact
    ADD CONSTRAINT fk_campaign_queue_contact_source_list_id_account_list FOREIGN KEY (source_list_id) REFERENCES public.account_list(id) ON DELETE SET NULL;


--
-- Name: campaign_queue fk_campaign_queue_icp_profile_id_icp_profile; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue
    ADD CONSTRAINT fk_campaign_queue_icp_profile_id_icp_profile FOREIGN KEY (icp_profile_id) REFERENCES public.icp_profile(id) ON DELETE SET NULL;


--
-- Name: campaign_queue_member fk_campaign_queue_member_account_id_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue_member
    ADD CONSTRAINT fk_campaign_queue_member_account_id_account FOREIGN KEY (account_id) REFERENCES public.account(id);


--
-- Name: campaign_queue_member fk_campaign_queue_member_qualification_id_qualification; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue_member
    ADD CONSTRAINT fk_campaign_queue_member_qualification_id_qualification FOREIGN KEY (qualification_id) REFERENCES public.qualification(id);


--
-- Name: campaign_queue_member fk_campaign_queue_member_queue_id_campaign_queue; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue_member
    ADD CONSTRAINT fk_campaign_queue_member_queue_id_campaign_queue FOREIGN KEY (queue_id) REFERENCES public.campaign_queue(id) ON DELETE CASCADE;


--
-- Name: campaign_queue_member fk_campaign_queue_member_source_list_id_account_list; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue_member
    ADD CONSTRAINT fk_campaign_queue_member_source_list_id_account_list FOREIGN KEY (source_list_id) REFERENCES public.account_list(id) ON DELETE SET NULL;


--
-- Name: campaign_queue fk_campaign_queue_promoted_to_campaign_id_outreach_campaign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue
    ADD CONSTRAINT fk_campaign_queue_promoted_to_campaign_id_outreach_campaign FOREIGN KEY (promoted_to_campaign_id) REFERENCES public.outreach_campaign(id);


--
-- Name: campaign_queue fk_campaign_queue_service_id_service_catalog; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_queue
    ADD CONSTRAINT fk_campaign_queue_service_id_service_catalog FOREIGN KEY (service_id) REFERENCES public.service_catalog(id) ON DELETE SET NULL;


--
-- Name: contact fk_contact_account_id_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contact
    ADD CONSTRAINT fk_contact_account_id_account FOREIGN KEY (account_id) REFERENCES public.account(id) ON DELETE CASCADE;


--
-- Name: contact fk_contact_lgm_identity_id_lgm_identity; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contact
    ADD CONSTRAINT fk_contact_lgm_identity_id_lgm_identity FOREIGN KEY (lgm_identity_id) REFERENCES public.lgm_identity(id);


--
-- Name: contact_suggestion fk_contact_suggestion_account_id_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contact_suggestion
    ADD CONSTRAINT fk_contact_suggestion_account_id_account FOREIGN KEY (account_id) REFERENCES public.account(id) ON DELETE CASCADE;


--
-- Name: contact_suggestion fk_contact_suggestion_contact_id_contact; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contact_suggestion
    ADD CONSTRAINT fk_contact_suggestion_contact_id_contact FOREIGN KEY (contact_id) REFERENCES public.contact(id) ON DELETE SET NULL;


--
-- Name: contact_suggestion fk_contact_suggestion_list_id_account_list; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contact_suggestion
    ADD CONSTRAINT fk_contact_suggestion_list_id_account_list FOREIGN KEY (list_id) REFERENCES public.account_list(id) ON DELETE SET NULL;


--
-- Name: deferred_enrolment fk_deferred_enrolment_blocked_by_sequence_id_outreach_sequence; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deferred_enrolment
    ADD CONSTRAINT fk_deferred_enrolment_blocked_by_sequence_id_outreach_sequence FOREIGN KEY (blocked_by_sequence_id) REFERENCES public.outreach_sequence(id);


--
-- Name: deferred_enrolment fk_deferred_enrolment_campaign_id_outreach_campaign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deferred_enrolment
    ADD CONSTRAINT fk_deferred_enrolment_campaign_id_outreach_campaign FOREIGN KEY (campaign_id) REFERENCES public.outreach_campaign(id) ON DELETE CASCADE;


--
-- Name: deferred_enrolment fk_deferred_enrolment_contact_id_contact; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deferred_enrolment
    ADD CONSTRAINT fk_deferred_enrolment_contact_id_contact FOREIGN KEY (contact_id) REFERENCES public.contact(id);


--
-- Name: draft fk_draft_touch_id_touch; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.draft
    ADD CONSTRAINT fk_draft_touch_id_touch FOREIGN KEY (touch_id) REFERENCES public.touch(id) ON DELETE CASCADE;


--
-- Name: evidence fk_evidence_account_id_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence
    ADD CONSTRAINT fk_evidence_account_id_account FOREIGN KEY (account_id) REFERENCES public.account(id) ON DELETE CASCADE;


--
-- Name: evidence fk_evidence_contact_id_contact; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence
    ADD CONSTRAINT fk_evidence_contact_id_contact FOREIGN KEY (contact_id) REFERENCES public.contact(id) ON DELETE SET NULL;


--
-- Name: evidence fk_evidence_run_id_run; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence
    ADD CONSTRAINT fk_evidence_run_id_run FOREIGN KEY (run_id) REFERENCES public.run(id);


--
-- Name: execution_record fk_execution_record_sequence_id_outreach_sequence; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.execution_record
    ADD CONSTRAINT fk_execution_record_sequence_id_outreach_sequence FOREIGN KEY (sequence_id) REFERENCES public.outreach_sequence(id);


--
-- Name: execution_record fk_execution_record_touch_id_touch; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.execution_record
    ADD CONSTRAINT fk_execution_record_touch_id_touch FOREIGN KEY (touch_id) REFERENCES public.touch(id);


--
-- Name: icp_profile_version fk_icp_profile_version_icp_profile_id_icp_profile; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.icp_profile_version
    ADD CONSTRAINT fk_icp_profile_version_icp_profile_id_icp_profile FOREIGN KEY (icp_profile_id) REFERENCES public.icp_profile(id) ON DELETE CASCADE;


--
-- Name: outreach_campaign fk_outreach_campaign_cadence_shape_id_cadence_shape; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_campaign
    ADD CONSTRAINT fk_outreach_campaign_cadence_shape_id_cadence_shape FOREIGN KEY (cadence_shape_id) REFERENCES public.cadence_shape(id);


--
-- Name: outreach_campaign fk_outreach_campaign_icp_profile_id_icp_profile; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_campaign
    ADD CONSTRAINT fk_outreach_campaign_icp_profile_id_icp_profile FOREIGN KEY (icp_profile_id) REFERENCES public.icp_profile(id) ON DELETE SET NULL;


--
-- Name: outreach_campaign fk_outreach_campaign_service_id_service_catalog; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_campaign
    ADD CONSTRAINT fk_outreach_campaign_service_id_service_catalog FOREIGN KEY (service_id) REFERENCES public.service_catalog(id) ON DELETE SET NULL;


--
-- Name: outreach_campaign_source fk_outreach_campaign_source_campaign_id_outreach_campaign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_campaign_source
    ADD CONSTRAINT fk_outreach_campaign_source_campaign_id_outreach_campaign FOREIGN KEY (campaign_id) REFERENCES public.outreach_campaign(id) ON DELETE CASCADE;


--
-- Name: outreach_campaign_source fk_outreach_campaign_source_queue_id_campaign_queue; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_campaign_source
    ADD CONSTRAINT fk_outreach_campaign_source_queue_id_campaign_queue FOREIGN KEY (queue_id) REFERENCES public.campaign_queue(id);


--
-- Name: outreach_event fk_outreach_event_campaign_id_outreach_campaign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_event
    ADD CONSTRAINT fk_outreach_event_campaign_id_outreach_campaign FOREIGN KEY (campaign_id) REFERENCES public.outreach_campaign(id) ON DELETE CASCADE;


--
-- Name: outreach_event fk_outreach_event_contact_id_contact; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_event
    ADD CONSTRAINT fk_outreach_event_contact_id_contact FOREIGN KEY (contact_id) REFERENCES public.contact(id) ON DELETE SET NULL;


--
-- Name: outreach_event fk_outreach_event_sequence_id_outreach_sequence; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_event
    ADD CONSTRAINT fk_outreach_event_sequence_id_outreach_sequence FOREIGN KEY (sequence_id) REFERENCES public.outreach_sequence(id) ON DELETE SET NULL;


--
-- Name: outreach_sequence fk_outreach_sequence_cadence_shape_id_cadence_shape; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_sequence
    ADD CONSTRAINT fk_outreach_sequence_cadence_shape_id_cadence_shape FOREIGN KEY (cadence_shape_id) REFERENCES public.cadence_shape(id);


--
-- Name: outreach_sequence fk_outreach_sequence_campaign_id_outreach_campaign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_sequence
    ADD CONSTRAINT fk_outreach_sequence_campaign_id_outreach_campaign FOREIGN KEY (campaign_id) REFERENCES public.outreach_campaign(id);


--
-- Name: outreach_sequence fk_outreach_sequence_contact_id_contact; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_sequence
    ADD CONSTRAINT fk_outreach_sequence_contact_id_contact FOREIGN KEY (contact_id) REFERENCES public.contact(id);


--
-- Name: outreach_sequence fk_outreach_sequence_lgm_identity_id_lgm_identity; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_sequence
    ADD CONSTRAINT fk_outreach_sequence_lgm_identity_id_lgm_identity FOREIGN KEY (lgm_identity_id) REFERENCES public.lgm_identity(id);


--
-- Name: outreach_sequence fk_outreach_sequence_thread_id_strategy_thread; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outreach_sequence
    ADD CONSTRAINT fk_outreach_sequence_thread_id_strategy_thread FOREIGN KEY (thread_id) REFERENCES public.strategy_thread(id) ON DELETE CASCADE;


--
-- Name: persona_service_score fk_persona_service_score_contact_id_contact; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_service_score
    ADD CONSTRAINT fk_persona_service_score_contact_id_contact FOREIGN KEY (contact_id) REFERENCES public.contact(id);


--
-- Name: persona_service_score fk_persona_service_score_service_id_service_catalog; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_service_score
    ADD CONSTRAINT fk_persona_service_score_service_id_service_catalog FOREIGN KEY (service_id) REFERENCES public.service_catalog(id);


--
-- Name: persona_service_score fk_persona_service_score_strategy_id_strategy; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_service_score
    ADD CONSTRAINT fk_persona_service_score_strategy_id_strategy FOREIGN KEY (strategy_id) REFERENCES public.strategy(id) ON DELETE CASCADE;


--
-- Name: proof_point fk_proof_point_service_id_service_catalog; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proof_point
    ADD CONSTRAINT fk_proof_point_service_id_service_catalog FOREIGN KEY (service_id) REFERENCES public.service_catalog(id) ON DELETE CASCADE;


--
-- Name: qualification fk_qualification_account_id_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qualification
    ADD CONSTRAINT fk_qualification_account_id_account FOREIGN KEY (account_id) REFERENCES public.account(id) ON DELETE CASCADE;


--
-- Name: qualification fk_qualification_context_id_account_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qualification
    ADD CONSTRAINT fk_qualification_context_id_account_context FOREIGN KEY (context_id) REFERENCES public.account_context(id);


--
-- Name: qualification fk_qualification_run_id_run; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qualification
    ADD CONSTRAINT fk_qualification_run_id_run FOREIGN KEY (run_id) REFERENCES public.run(id);


--
-- Name: research_coverage fk_research_coverage_account_id_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_coverage
    ADD CONSTRAINT fk_research_coverage_account_id_account FOREIGN KEY (account_id) REFERENCES public.account(id) ON DELETE CASCADE;


--
-- Name: research_coverage fk_research_coverage_contact_id_contact; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_coverage
    ADD CONSTRAINT fk_research_coverage_contact_id_contact FOREIGN KEY (contact_id) REFERENCES public.contact(id) ON DELETE CASCADE;


--
-- Name: research_coverage fk_research_coverage_run_id_run; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_coverage
    ADD CONSTRAINT fk_research_coverage_run_id_run FOREIGN KEY (run_id) REFERENCES public.run(id) ON DELETE CASCADE;


--
-- Name: run fk_run_account_id_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run
    ADD CONSTRAINT fk_run_account_id_account FOREIGN KEY (account_id) REFERENCES public.account(id) ON DELETE CASCADE;


--
-- Name: run fk_run_list_id_account_list; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run
    ADD CONSTRAINT fk_run_list_id_account_list FOREIGN KEY (list_id) REFERENCES public.account_list(id) ON DELETE SET NULL;


--
-- Name: service_icp_link fk_service_icp_link_icp_profile_id_icp_profile; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.service_icp_link
    ADD CONSTRAINT fk_service_icp_link_icp_profile_id_icp_profile FOREIGN KEY (icp_profile_id) REFERENCES public.icp_profile(id) ON DELETE CASCADE;


--
-- Name: service_icp_link fk_service_icp_link_service_id_service_catalog; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.service_icp_link
    ADD CONSTRAINT fk_service_icp_link_service_id_service_catalog FOREIGN KEY (service_id) REFERENCES public.service_catalog(id) ON DELETE CASCADE;


--
-- Name: signal fk_signal_account_id_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal
    ADD CONSTRAINT fk_signal_account_id_account FOREIGN KEY (account_id) REFERENCES public.account(id) ON DELETE CASCADE;


--
-- Name: signal fk_signal_contact_id_contact; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal
    ADD CONSTRAINT fk_signal_contact_id_contact FOREIGN KEY (contact_id) REFERENCES public.contact(id) ON DELETE CASCADE;


--
-- Name: signal_evidence fk_signal_evidence_evidence_id_evidence; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal_evidence
    ADD CONSTRAINT fk_signal_evidence_evidence_id_evidence FOREIGN KEY (evidence_id) REFERENCES public.evidence(id) ON DELETE RESTRICT;


--
-- Name: signal_evidence fk_signal_evidence_signal_id_signal; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal_evidence
    ADD CONSTRAINT fk_signal_evidence_signal_id_signal FOREIGN KEY (signal_id) REFERENCES public.signal(id) ON DELETE CASCADE;


--
-- Name: signal fk_signal_run_id_run; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal
    ADD CONSTRAINT fk_signal_run_id_run FOREIGN KEY (run_id) REFERENCES public.run(id);


--
-- Name: signal fk_signal_superseded_by_signal; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal
    ADD CONSTRAINT fk_signal_superseded_by_signal FOREIGN KEY (superseded_by) REFERENCES public.signal(id);


--
-- Name: strategy fk_strategy_account_id_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy
    ADD CONSTRAINT fk_strategy_account_id_account FOREIGN KEY (account_id) REFERENCES public.account(id) ON DELETE CASCADE;


--
-- Name: strategy fk_strategy_campaign_id_outreach_campaign; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy
    ADD CONSTRAINT fk_strategy_campaign_id_outreach_campaign FOREIGN KEY (campaign_id) REFERENCES public.outreach_campaign(id) ON DELETE CASCADE;


--
-- Name: strategy fk_strategy_icp_profile_id_icp_profile; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy
    ADD CONSTRAINT fk_strategy_icp_profile_id_icp_profile FOREIGN KEY (icp_profile_id) REFERENCES public.icp_profile(id) ON DELETE SET NULL;


--
-- Name: strategy fk_strategy_qualification_id_qualification; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy
    ADD CONSTRAINT fk_strategy_qualification_id_qualification FOREIGN KEY (qualification_id) REFERENCES public.qualification(id);


--
-- Name: strategy fk_strategy_run_id_run; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy
    ADD CONSTRAINT fk_strategy_run_id_run FOREIGN KEY (run_id) REFERENCES public.run(id);


--
-- Name: strategy fk_strategy_service_id_service_catalog; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy
    ADD CONSTRAINT fk_strategy_service_id_service_catalog FOREIGN KEY (service_id) REFERENCES public.service_catalog(id) ON DELETE SET NULL;


--
-- Name: strategy_thread fk_strategy_thread_contact_id_contact; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_thread
    ADD CONSTRAINT fk_strategy_thread_contact_id_contact FOREIGN KEY (contact_id) REFERENCES public.contact(id);


--
-- Name: strategy_thread fk_strategy_thread_service_id_service_catalog; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_thread
    ADD CONSTRAINT fk_strategy_thread_service_id_service_catalog FOREIGN KEY (service_id) REFERENCES public.service_catalog(id);


--
-- Name: strategy_thread fk_strategy_thread_strategy_id_strategy; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_thread
    ADD CONSTRAINT fk_strategy_thread_strategy_id_strategy FOREIGN KEY (strategy_id) REFERENCES public.strategy(id) ON DELETE CASCADE;


--
-- Name: touch fk_touch_sequence_id_outreach_sequence; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.touch
    ADD CONSTRAINT fk_touch_sequence_id_outreach_sequence FOREIGN KEY (sequence_id) REFERENCES public.outreach_sequence(id) ON DELETE CASCADE;


--
-- Name: signal signal_type_scope_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal
    ADD CONSTRAINT signal_type_scope_fk FOREIGN KEY (signal_type, scope) REFERENCES public.signal_type(key, scope);


--
-- PostgreSQL database dump complete
--

\unrestrict q9FDgfb9x3w0F5vxfw4jWuBlkPT3qvuld7FU8Ijx8cPgwcQGJjyTU1OxbaEreQb

