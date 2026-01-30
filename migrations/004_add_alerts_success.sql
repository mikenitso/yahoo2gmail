-- Track successful vs failed outbound alerts

ALTER TABLE alerts ADD COLUMN success INTEGER NOT NULL DEFAULT 1;

UPDATE alerts
   SET success = 0
 WHERE message LIKE 'send_failed:%';

CREATE INDEX IF NOT EXISTS idx_alerts_kind_success_created
  ON alerts(kind, success, created_at);
