ALTER TABLE mailboxes ADD COLUMN last_poll_at TEXT;
ALTER TABLE mailboxes ADD COLUMN last_success_at TEXT;
ALTER TABLE mailboxes ADD COLUMN last_error TEXT;
ALTER TABLE mailboxes ADD COLUMN last_error_at TEXT;
