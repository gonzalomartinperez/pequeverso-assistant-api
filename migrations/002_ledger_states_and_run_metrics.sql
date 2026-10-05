-- Ledger rows carry an explicit state: pending (run active), settled (provider-reported usage)
-- or unreported (run ended without usage: the reservation stays counted as an estimate).
ALTER TABLE spend_ledger ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'settled', 'unreported'));
UPDATE spend_ledger SET status = CASE WHEN actual_micro IS NOT NULL THEN 'settled' ELSE 'unreported' END;
ALTER TABLE spend_ledger ADD COLUMN reasoning_tokens INTEGER;
ALTER TABLE spend_ledger ADD COLUMN settled_at TEXT;
CREATE INDEX spend_ledger_status ON spend_ledger (status);

-- Content-free operations record of each accepted or refused run. No session id, no text,
-- no client key. Retained 90 days (maintenance task).
CREATE TABLE run_metrics (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    day TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('completed', 'failed', 'cancelled', 'interrupted', 'refused')),
    code TEXT,
    model_call INTEGER NOT NULL CHECK (model_call IN (0, 1)),
    replaced INTEGER NOT NULL CHECK (replaced IN (0, 1)),
    language TEXT CHECK (language IN ('es', 'en')),
    first_delta_ms INTEGER CHECK (first_delta_ms >= 0),
    total_ms INTEGER NOT NULL CHECK (total_ms >= 0)
);
CREATE INDEX run_metrics_started_at ON run_metrics (started_at);

-- When the last catalog refresh failure happened (last_failure is cleared on success, this is not).
ALTER TABLE catalog_state ADD COLUMN last_failure_at TEXT;
