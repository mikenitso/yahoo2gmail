UPDATE messages
   SET last_error = NULL,
       next_attempt_at = NULL
 WHERE state IN ('INSERTED', 'SUPPRESSED_DUPLICATE')
   AND last_error IS NOT NULL;
