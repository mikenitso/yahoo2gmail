-- Add Yahoo delete tracking fields

ALTER TABLE messages ADD COLUMN yahoo_deleted_at TEXT;
ALTER TABLE messages ADD COLUMN yahoo_delete_attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE messages ADD COLUMN yahoo_delete_next_attempt_at TEXT;
ALTER TABLE messages ADD COLUMN yahoo_delete_last_error TEXT;
