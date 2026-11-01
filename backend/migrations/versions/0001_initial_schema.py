"""Initial schema: directory, slots, bookings, documents, models, audit.

Written as explicit SQL on purpose: the constraints ARE the booking rules, and
learners should be able to read them directly.

Revision ID: 0001
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

ACTIVE_STATUSES = "('confirmed','en_route','in_progress','completed')"

UPGRADE_SQL = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ---------------------------------------------------------------- lookups
CREATE TABLE service_categories (
    code        text PRIMARY KEY CHECK (code IN ('plumbing','electrical','appliance')),
    name        text NOT NULL,
    description text NOT NULL DEFAULT ''
);

CREATE TABLE localities (
    code    text PRIMARY KEY CHECK (code ~ '^[a-z_]+$'),
    name    text NOT NULL UNIQUE,
    aliases text[] NOT NULL DEFAULT '{{}}'
);

-- ---------------------------------------------------------- technicians
CREATE TABLE technicians (
    id               serial PRIMARY KEY,
    name             text NOT NULL,
    bio              text NOT NULL DEFAULT '',
    years_experience int  NOT NULL DEFAULT 0 CHECK (years_experience >= 0),
    rating           numeric(2,1) NOT NULL DEFAULT 4.0 CHECK (rating BETWEEN 0 AND 5),
    is_active        boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE technician_categories (
    technician_id       int  NOT NULL REFERENCES technicians(id) ON DELETE CASCADE,
    category_code       text NOT NULL REFERENCES service_categories(code),
    visiting_charge_inr int  NOT NULL CHECK (visiting_charge_inr BETWEEN 1 AND 100000),
    PRIMARY KEY (technician_id, category_code)
);

CREATE TABLE technician_service_areas (
    technician_id int  NOT NULL REFERENCES technicians(id) ON DELETE CASCADE,
    locality_code text NOT NULL REFERENCES localities(code),
    PRIMARY KEY (technician_id, locality_code)
);

-- ----------------------------------------------------------------- users
CREATE TABLE users (
    id            serial PRIMARY KEY,
    email         text NOT NULL UNIQUE,
    display_name  text NOT NULL,
    role          text NOT NULL CHECK (role IN ('customer','provider','admin')),
    password_hash text NOT NULL,
    technician_id int REFERENCES technicians(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    -- a provider account must be linked to exactly one technician; others must not be
    CHECK ((role = 'provider') = (technician_id IS NOT NULL))
);

-- ------------------------------------------------------ availability slots
CREATE TABLE availability_slots (
    id            bigserial PRIMARY KEY,
    technician_id int NOT NULL REFERENCES technicians(id) ON DELETE CASCADE,
    start_at      timestamptz NOT NULL,
    end_at        timestamptz NOT NULL,
    is_withdrawn  boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now(),
    -- version 1 uses fixed one-hour slots that start on the hour (Kolkata wall clock)
    CHECK (end_at = start_at + interval '1 hour'),
    CHECK (extract(minute FROM (start_at AT TIME ZONE 'Asia/Kolkata')) = 0
           AND extract(second FROM start_at) = 0),
    -- lets bookings reference (slot, technician) together
    UNIQUE (id, technician_id),
    -- no overlapping slots for the same technician
    CONSTRAINT slots_no_overlap EXCLUDE USING gist (
        technician_id WITH =,
        tstzrange(start_at, end_at) WITH &&
    )
);
CREATE INDEX availability_slots_start_idx ON availability_slots (start_at);

-- --------------------------------------------------------------- bookings
CREATE TABLE bookings (
    id                  bigserial PRIMARY KEY,
    reference           text NOT NULL UNIQUE,
    customer_id         int  NOT NULL REFERENCES users(id),
    technician_id       int  NOT NULL,
    slot_id             bigint NOT NULL,
    category_code       text NOT NULL,
    locality_code       text NOT NULL,
    issue_description   text NOT NULL CHECK (length(issue_description) BETWEEN 3 AND 1000),
    visiting_charge_inr int  NOT NULL,
    status              text NOT NULL CHECK (status IN
                          ('confirmed','en_route','in_progress','completed',
                           'cancelled_by_customer','cancelled_by_provider')),
    idempotency_key     text NOT NULL,
    request_fingerprint text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    -- the slot must belong to the booked technician
    FOREIGN KEY (slot_id, technician_id) REFERENCES availability_slots (id, technician_id),
    -- the technician must offer this category and serve this locality
    FOREIGN KEY (technician_id, category_code)
        REFERENCES technician_categories (technician_id, category_code),
    FOREIGN KEY (technician_id, locality_code)
        REFERENCES technician_service_areas (technician_id, locality_code),
    -- the same customer retrying the same submission gets the same booking
    UNIQUE (customer_id, idempotency_key)
);
-- THE double-booking guard: at most one non-cancelled booking per slot
CREATE UNIQUE INDEX bookings_one_active_per_slot
    ON bookings (slot_id) WHERE status IN {ACTIVE_STATUSES};
CREATE INDEX bookings_customer_idx ON bookings (customer_id);
CREATE INDEX bookings_technician_idx ON bookings (technician_id);

CREATE TABLE booking_status_events (
    id            bigserial PRIMARY KEY,
    booking_id    bigint NOT NULL REFERENCES bookings(id),
    from_status   text,
    to_status     text NOT NULL,
    actor_user_id int REFERENCES users(id),
    reason        text NOT NULL DEFAULT '',
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX booking_status_events_booking_idx ON booking_status_events (booking_id);

-- A slot that carries an active booking cannot be moved, reassigned or withdrawn.
CREATE FUNCTION protect_booked_slots() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM bookings b
               WHERE b.slot_id = OLD.id AND b.status IN {ACTIVE_STATUSES}) THEN
        RAISE EXCEPTION 'slot % has an active booking and cannot be changed', OLD.id
            USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER availability_slots_protect
    BEFORE DELETE OR UPDATE OF start_at, end_at, technician_id, is_withdrawn
    ON availability_slots FOR EACH ROW EXECUTE FUNCTION protect_booked_slots();

-- --------------------------------------------------------------- documents
CREATE TABLE policy_documents (
    id               serial PRIMARY KEY,
    doc_key          text NOT NULL CHECK (doc_key ~ '^[a-z0-9_-]+$'),
    title            text NOT NULL,
    version          int  NOT NULL CHECK (version >= 1),
    status           text NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft','active','superseded','failed')),
    content          text NOT NULL,
    content_sha256   text NOT NULL,
    source_filename  text NOT NULL DEFAULT '',
    uploaded_by      int REFERENCES users(id),
    ingestion_status text NOT NULL DEFAULT 'pending'
                     CHECK (ingestion_status IN ('pending','running','succeeded','failed')),
    ingestion_error  text,
    chunk_count      int NOT NULL DEFAULT 0,
    embedding_model  text,
    ingested_at      timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (doc_key, version)
);
-- only one active version per document
CREATE UNIQUE INDEX policy_documents_one_active
    ON policy_documents (doc_key) WHERE status = 'active';

CREATE TABLE document_chunks (
    id                bigserial PRIMARY KEY,
    document_id       int  NOT NULL REFERENCES policy_documents(id) ON DELETE CASCADE,
    chunk_index       int  NOT NULL,
    section_title     text NOT NULL,
    content           text NOT NULL,
    embedding         vector(384) NOT NULL,
    embedding_model   text NOT NULL,
    is_quarantined    boolean NOT NULL DEFAULT false,
    quarantine_reason text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);
CREATE INDEX document_chunks_embedding_hnsw
    ON document_chunks USING hnsw (embedding vector_cosine_ops);

-- ------------------------------------------------- models, evaluation, audit
CREATE TABLE model_versions (
    id              serial PRIMARY KEY,
    kind            text NOT NULL,
    version         text NOT NULL,
    dataset_version text NOT NULL DEFAULT '',
    artifact_path   text NOT NULL DEFAULT '',
    metrics         jsonb NOT NULL DEFAULT '{{}}',
    is_active       boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (kind, version)
);
CREATE UNIQUE INDEX model_versions_one_active ON model_versions (kind) WHERE is_active;

CREATE TABLE evaluation_runs (
    id          serial PRIMARY KEY,
    suite       text NOT NULL,
    status      text NOT NULL CHECK (status IN ('running','succeeded','failed')),
    config      jsonb NOT NULL DEFAULT '{{}}',
    summary     jsonb NOT NULL DEFAULT '{{}}',
    failures    jsonb NOT NULL DEFAULT '[]',
    error       text,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

CREATE TABLE audit_events (
    id            bigserial PRIMARY KEY,
    request_id    text NOT NULL,
    actor_user_id int REFERENCES users(id) ON DELETE SET NULL,
    action        text NOT NULL,
    entity_type   text NOT NULL DEFAULT '',
    entity_id     text NOT NULL DEFAULT '',
    outcome       text NOT NULL,
    details       jsonb NOT NULL DEFAULT '{{}}',
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_events_request_idx ON audit_events (request_id);
CREATE INDEX audit_events_created_idx ON audit_events (created_at DESC);
"""

DOWNGRADE_SQL = """
DROP TABLE IF EXISTS audit_events, evaluation_runs, model_versions, document_chunks,
    policy_documents, booking_status_events, bookings, availability_slots, users,
    technician_service_areas, technician_categories, technicians, localities,
    service_categories CASCADE;
DROP FUNCTION IF EXISTS protect_booked_slots();
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
