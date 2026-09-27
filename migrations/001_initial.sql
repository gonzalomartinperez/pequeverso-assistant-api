-- Sessions and their conversation. Deleting a session cascades to messages and runs.
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    secret_digest BLOB NOT NULL UNIQUE,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX sessions_expires_at ON sessions (expires_at);

CREATE TABLE messages (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    details TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX messages_session ON messages (session_id, seq);

CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active', 'completed', 'failed', 'cancelled')),
    assistant_message_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, idempotency_key)
);
CREATE UNIQUE INDEX runs_one_active ON runs (session_id) WHERE state = 'active';

-- Spend survives session deletion on purpose: it holds no conversation data.
CREATE TABLE spend_ledger (
    run_id TEXT PRIMARY KEY,
    month TEXT NOT NULL,
    day TEXT NOT NULL,
    reserved_micro INTEGER NOT NULL CHECK (reserved_micro >= 0),
    actual_micro INTEGER CHECK (actual_micro >= 0),
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cached_input_tokens INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX spend_ledger_month ON spend_ledger (month);
CREATE INDEX spend_ledger_day ON spend_ledger (day);

CREATE TABLE rate_counters (
    key TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (key, window_start)
);

CREATE TABLE catalog_snapshots (
    sha256 TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    source_revision TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    activated_at TEXT NOT NULL,
    body BLOB NOT NULL
);

CREATE TABLE catalog_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    active_sha256 TEXT REFERENCES catalog_snapshots (sha256),
    verified_at TEXT,
    last_attempt_at TEXT,
    last_failure TEXT
);
INSERT INTO catalog_state (id) VALUES (1);
