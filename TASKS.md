# v1 Tasks (Implement in order)

1. Repo scaffolding
   - [x] Create directory structure per SPEC.md
   - [x] Add README.md with setup overview

2. Config + logging
   - [x] Env var parsing and validation
   - [x] JSON structured logging with correlation ids

3. SQLite store
   - [x] Create schema + migrations
   - [x] Implement message state machine + lease transitions
   - [x] Implement secret encryption storage

4. Gmail integration
   - [x] OAuth consent flow + token storage
   - [x] Ensure label exists (create if missing)
   - [x] Insert raw RFC822 using users.messages.insert with labelIds (INBOX + yahoo label + UNREAD as needed)

5. Yahoo IMAP integration
   - [x] IMAP TLS connection + LOGIN using app password (stored encrypted after bootstrap)
   - [x] Mailbox discovery (INBOX + spam/bulk/junk); exclude sent/drafts/trash/archive unless configured
   - [x] One watcher per mailbox using IMAP IDLE
   - [x] On startup: set last_seen_uid to current max UID (no backfill)
   - [x] On EXISTS/RECENT: search for UIDs > last_seen_uid, fetch RFC822+FLAGS+INTERNALDATE

6. Pipeline + retries
   - [x] Persist discovered/fetched messages in SQLite
   - [x] Retry worker with exponential backoff + jitter
   - [x] Crash recovery for INSERTING older than threshold -> FAILED_RETRY

7. Docker
   - [x] Dockerfile
   - [x] docker-compose.yml
   - [x] .env.example

8. Tests / verification
   - [x] Unit tests for parsing, hashing, state transitions, backoff schedule
   - [x] Provide manual acceptance checklist script / docs

Definition of done:
- Meets all acceptance criteria in SPEC.md
- No UI, no backfill, no filters
