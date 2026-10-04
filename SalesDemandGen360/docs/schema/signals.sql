-- ===========================================================================
-- Sales Demand Gen360 — signal storage
-- PostgreSQL 16
--
-- Four tables. The ordering below is the dependency order and also the data
-- flow: a type is registered, a document becomes evidence, evidence is
-- interpreted into a signal, and the join records which evidence supports it.
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- 1. signal_type — the registry
--
-- Configuration, not schema. Adding a type is an INSERT, not a migration:
-- the extraction prompt and its output schema are built from the active rows.
-- ---------------------------------------------------------------------------
CREATE TABLE signal_type (
    key               TEXT PRIMARY KEY,
    label             TEXT NOT NULL,
    description       TEXT,                       -- goes into the extraction prompt
    scope             TEXT NOT NULL
                        CHECK (scope IN ('company','contact')),
    default_ttl_days  INT  NOT NULL CHECK (default_ttl_days > 0),
    weight            NUMERIC(4,2) NOT NULL DEFAULT 1.00 CHECK (weight >= 0),
    produced_by       TEXT[]       NOT NULL DEFAULT '{}',   -- query families
    status            TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active','deprecated')),
    deprecated_at     TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ,

    CHECK ((status = 'deprecated') = (deprecated_at IS NOT NULL))
);

-- Needed so `signal` can carry a composite FK on (type, scope) — see below.
CREATE UNIQUE INDEX signal_type_key_scope ON signal_type (key, scope);

COMMENT ON COLUMN signal_type.scope IS
  'No ''both'': a signal is about an organisation or about a person. A type '
  'claiming to be either would have no consistent home in persona ranking.';


-- ---------------------------------------------------------------------------
-- 2. evidence — stored, never interpreted
--
-- The bottom of every audit trail. Holds metadata plus the quoted passage.
-- The full document lives in object storage via raw_ref, never in Postgres.
-- ---------------------------------------------------------------------------
CREATE TABLE evidence (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id     UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    run_id         UUID REFERENCES run(id),

    source_type    TEXT NOT NULL
                     CHECK (source_type IN ('web','news','jobs','linkedin',
                                            'crm','provider','filing','manual')),
    source_url     TEXT,
    source_name    TEXT,
    title          TEXT,
    excerpt        TEXT NOT NULL,          -- the passage a claim rests on

    observed_at    DATE,                   -- when the fact was TRUE
    retrieved_at   TIMESTAMPTZ NOT NULL DEFAULT now(),  -- when we fetched it

    -- manual capture only
    author_id      TEXT,
    capture_method TEXT CHECK (capture_method IN
                     ('conversation','email','event','inbound','other')),

    source_hash    TEXT NOT NULL,          -- hash of the document  (NOT unique)
    excerpt_hash   TEXT NOT NULL,          -- hash of source_url + excerpt
    raw_ref        TEXT,                   -- object-storage key
    raw_status     TEXT NOT NULL DEFAULT 'stored'
                     CHECK (raw_status IN ('stored','unavailable','purged')),
    reliability    NUMERIC(4,3) CHECK (reliability BETWEEN 0 AND 1),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- a manual observation must say who logged it and how
    CHECK (source_type <> 'manual'
           OR (author_id IS NOT NULL AND capture_method IS NOT NULL)),
    -- a stored snapshot must have somewhere to point
    CHECK (raw_status <> 'stored' OR raw_ref IS NOT NULL)
);

-- One document yields MANY excerpts, so the dedup key is the excerpt, not the
-- document. A unique index on the document would admit only the first excerpt;
-- signals citing the rejected ones would then be dropped by the
-- missing-evidence guard, looking exactly like hallucinated citations.
CREATE UNIQUE INDEX evidence_dedup     ON evidence (account_id, excerpt_hash);
CREATE INDEX        evidence_by_source ON evidence (account_id, source_hash);
CREATE INDEX        evidence_by_type   ON evidence (account_id, source_type);


-- ---------------------------------------------------------------------------
-- 3. signal — a typed, dated interpretation of evidence
-- ---------------------------------------------------------------------------
CREATE TABLE signal (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id           UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    contact_id           UUID REFERENCES contact(id) ON DELETE CASCADE,
    run_id               UUID REFERENCES run(id),

    signal_type          TEXT NOT NULL,
    scope                TEXT NOT NULL CHECK (scope IN ('company','contact')),

    summary              TEXT NOT NULL,
    business_implication TEXT,
    strength             TEXT NOT NULL CHECK (strength IN ('low','medium','high')),
    confidence           NUMERIC(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),

    observed_at          DATE NOT NULL,
    expires_at           DATE,             -- observed_at + type's default_ttl_days
    lifecycle_state      TEXT NOT NULL DEFAULT 'discovered'
                           CHECK (lifecycle_state IN
                             ('discovered','validated','active','stale','expired')),

    is_hypothesis        BOOLEAN NOT NULL DEFAULT false,
    superseded_by        UUID REFERENCES signal(id),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ,

    -- scope is denormalised from the registry so the rule below can be a CHECK
    -- rather than application code. The composite FK keeps the two in step.
    FOREIGN KEY (signal_type, scope) REFERENCES signal_type (key, scope),

    -- a contact signal must name a contact; a company signal must not
    CHECK ((scope = 'contact' AND contact_id IS NOT NULL)
        OR (scope = 'company' AND contact_id IS NULL)),

    CHECK (expires_at IS NULL OR expires_at >= observed_at)
);

CREATE INDEX signal_by_account ON signal (account_id, lifecycle_state);
CREATE INDEX signal_by_contact ON signal (contact_id) WHERE contact_id IS NOT NULL;
CREATE INDEX signal_live       ON signal (account_id, expires_at)
       WHERE lifecycle_state IN ('validated','active');

COMMENT ON CONSTRAINT signal_signal_type_scope_fkey ON signal IS
  'Composite FK on (type, scope) stops a contact-scoped type being written as '
  'a company signal — the mismatch cannot be represented.';


-- ---------------------------------------------------------------------------
-- 4. signal_evidence — which evidence supports which signal
-- ---------------------------------------------------------------------------
CREATE TABLE signal_evidence (
    signal_id   UUID NOT NULL REFERENCES signal(id)   ON DELETE CASCADE,
    evidence_id UUID NOT NULL REFERENCES evidence(id) ON DELETE RESTRICT,
    role        TEXT NOT NULL DEFAULT 'supporting'
                  CHECK (role IN ('primary','supporting')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (signal_id, evidence_id)
);

CREATE INDEX signal_evidence_by_evidence ON signal_evidence (evidence_id);

-- ON DELETE RESTRICT is deliberate: evidence cited by a live signal cannot be
-- deleted. Retention purges the object-storage snapshot (raw_status='purged'),
-- never the row — a signal must never lose its citation.


-- ---------------------------------------------------------------------------
-- 5. The one invariant a CHECK cannot express
--
-- "No signal without evidence" spans two tables, so it needs a deferred
-- constraint trigger: the join rows are inserted after the signal, and the
-- check must run at COMMIT rather than per statement.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION signal_requires_evidence() RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM signal_evidence WHERE signal_id = NEW.id) THEN
        RAISE EXCEPTION 'signal % has no evidence', NEW.id
              USING HINT = 'Every signal must cite at least one evidence row.';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER signal_evidence_required
    AFTER INSERT ON signal
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION signal_requires_evidence();

-- This is the database half. The service layer holds the other half: it
-- resolves every evidence_id the model returns against this table and DROPS
-- any signal citing an id that does not exist, logging it as an evaluation
-- failure. A hallucinated citation is the single failure mode that would
-- destroy rep trust, so it fails closed rather than degrading quietly.


-- ---------------------------------------------------------------------------
-- 6. Ageing — deterministic, no LLM
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW signal_current AS
SELECT s.*,
       st.weight        AS type_weight,
       st.label         AS type_label,
       CASE
         WHEN s.expires_at IS NOT NULL AND s.expires_at <  current_date THEN 'expired'
         WHEN s.expires_at IS NOT NULL AND s.expires_at <  current_date + 30 THEN 'stale'
         ELSE s.lifecycle_state
       END AS effective_state
FROM signal s
JOIN signal_type st ON st.key = s.signal_type
WHERE st.status = 'active';

-- Deprecating a type removes it from this view, so it stops influencing new
-- work — while the underlying rows survive for audit and for the Learning
-- layer. That is why a type that has produced signals is deprecated, never
-- deleted (one with none may be deleted — nothing cites it): a qualification
-- decided partly on a since-retired type must still be able to explain itself.
