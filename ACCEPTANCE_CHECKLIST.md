# Manual Acceptance Checklist (v1)

1) Cutover test (no backfill)
   - Stop any existing forwarders.
   - Start this service.
   - Send a test email to Yahoo; verify it appears in Gmail within ~1 minute.

2) Threading
   - Reply to a Yahoo email to create In-Reply-To/References.
   - Confirm Gmail shows the reply in the same thread.

3) Inline images / rich HTML
   - Send an HTML email with inline images (CID).
   - Verify Gmail renders as expected.

4) Attachments
   - Send a PDF attachment.
   - Verify it appears in Gmail and opens.

5) Spam
   - Ensure a message landing in Yahoo Bulk/Spam is inserted into Gmail.
   - Confirm Gmail can auto-classify it (no special handling).

6) Exactly-once under restart
   - While sending multiple emails, restart the container repeatedly.
   - Verify no duplicates in Gmail.

7) Failure + retry
   - Block outbound network temporarily.
   - Confirm failures logged and retries occur; eventually messages insert.

8) Pushover DNS resilience
   - Simulate DNS resolution failure for `api.pushover.net`.
   - Verify send attempts retry with `2s` then `5s` backoff.
   - Verify failure is logged as DNS-specific (`send_failed_dns`) instead of generic send failure.

9) Gmail alias send suppression
   - Send from Gmail using the `mikenitso@yahoo.com` alias.
   - Verify the message appears in Yahoo Sent.
   - Verify the service deletes the Yahoo Sent copy without creating a duplicate in Gmail Sent.

10) Yahoo-originated Sent mirroring
   - Send directly from Yahoo web, Apple Mail, or iOS Mail.
   - Verify the message appears in Gmail Sent exactly once.
   - Verify the Yahoo Sent copy is deleted after processing.

11) Sent reply threading
   - Reply from Yahoo web, Apple Mail, or iOS Mail to a conversation that already exists in Gmail.
   - Verify the mirrored sent message appears in the existing Gmail conversation thread even though it only has the `SENT` label.
