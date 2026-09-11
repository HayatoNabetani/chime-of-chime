CREATE TABLE IF NOT EXISTS processed_events (
  event_id TEXT PRIMARY KEY,
  processed_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_processed_events_at
  ON processed_events(processed_at);

CREATE TABLE IF NOT EXISTS unlock_confirmations (
  token TEXT PRIMARY KEY,
  expires_at INTEGER NOT NULL,
  used_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_unlock_confirmations_expires
  ON unlock_confirmations(expires_at);
