# v1 Tasks (Implement in order)

1. Repo scaffolding
   - Create directory structure per SPEC.md
   - Add README.md with setup overview

2. Config + logging
   - Env var parsing and validation
   - JSON structured logging with correlation ids

3. SQLite store
   - Create schema + migrations
   - Implement message state machine + lease transitions
   - Implement secret encryption storage

4. Gmail integration
   - OAuth consent flow + token storage
   - Ensure label exists (create if missing)
   - Insert raw RFC822 using users.messages.insert with labelIds (INBOX + yahoo label + UNREAD as needed)

5. Yahoo IMAP integration
   - IMAP TLS connection + LOGIN using app password (stored encrypted after bootstrap)
   - Mailbox discovery (INBOX + spam/bulk/junk); exclude sent/drafts/trash/archive unless configured
   - One watcher per mailbox using IMAP IDLE
   - On startup: set last_seen_uid to current max UID (no backfill)
   - On EXISTS/RECENT: search for UIDs > last_seen_uid, fetch RFC822+FLAGS+INTERNALDATE

6. Pipeline + retries
   - Persist discovered/fetched messages in SQLite
   - Retry worker with exponential backoff + jitter
   - Crash recovery for INSERTING older than threshold -> FAILED_RETRY

7. Docker
   - Dockerfile
   - docker-compose.yml
   - .env.example

8. Tests / verification
   - Unit tests for parsing, hashing, state transitions, backoff schedule
   - Provide manual acceptance checklist script / docs

Definition of done:
- Meets all acceptance criteria in SPEC.md
- No UI, no backfill, no filters
