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
