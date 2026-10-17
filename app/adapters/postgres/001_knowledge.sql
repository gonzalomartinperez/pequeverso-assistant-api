-- Explicit index/migration job only. Runtime receives no DDL or projection-write privileges.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS knowledge;
CREATE TABLE IF NOT EXISTS knowledge.revisions (
    version text PRIMARY KEY CHECK (version ~ '^[a-f0-9]{64}$'),
    catalog_sha256 text NOT NULL CHECK (catalog_sha256 ~ '^[a-f0-9]{64}$'),
    source_revision text NOT NULL,
    parser_version text NOT NULL,
    embedding_provider text NOT NULL,
    embedding_model text NOT NULL,
    embedding_dimensions integer NOT NULL CHECK (embedding_dimensions IN (64,1536)),
    catalog_body bytea NOT NULL CHECK (octet_length(catalog_body) <= 1048576),
    manifest jsonb NOT NULL,
    manifest_sha256 text NOT NULL,
    vector_sha256 text NOT NULL,
    verified_at timestamptz NOT NULL,
    prepared boolean NOT NULL DEFAULT false,
    UNIQUE(version,prepared),
    UNIQUE(version,embedding_dimensions)
);
CREATE TABLE IF NOT EXISTS knowledge.chunks (
    version text NOT NULL REFERENCES knowledge.revisions(version),
    id text NOT NULL,
    kind text NOT NULL,
    source_id text NOT NULL,
    title text NOT NULL,
    text text NOT NULL CHECK (octet_length(text) BETWEEN 1 AND 8000),
    url text NOT NULL,
    product_ids text[] NOT NULL,
    sha256 text NOT NULL,
    source_pointer text NOT NULL,
    embedding public.vector NOT NULL CHECK (public.vector_norm(embedding)>0),
    embedding_dimensions integer GENERATED ALWAYS AS (public.vector_dims(embedding)) STORED,
    search tsvector GENERATED ALWAYS AS
        (to_tsvector('simple', title || ' ' || text)) STORED,
    PRIMARY KEY(version,id),
    FOREIGN KEY(version,embedding_dimensions) REFERENCES knowledge.revisions(version,embedding_dimensions)
);
CREATE INDEX IF NOT EXISTS knowledge_chunks_search ON knowledge.chunks USING gin(search);
CREATE TABLE IF NOT EXISTS knowledge.state (
    id integer PRIMARY KEY CHECK (id=1),
    active_version text,
    active_prepared boolean NOT NULL DEFAULT true CHECK (active_prepared),
    verified_at timestamptz,
    last_attempt_at timestamptz,
    last_failure text,
    last_failure_at timestamptz,
    FOREIGN KEY(active_version,active_prepared) REFERENCES knowledge.revisions(version,prepared)
);
INSERT INTO knowledge.state(id) VALUES(1) ON CONFLICT(id) DO NOTHING;
