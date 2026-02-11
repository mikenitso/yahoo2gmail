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

9. Post-v1 enhancements (implemented)
   - [x] Startup catch-up scan on watcher start (still no backfill beyond stored last_seen_uid)
   - [x] UIDVALIDITY change detection and reset
   - [x] IMAP resilience improvements (watcher restart loop, longer IDLE, reconnect on IDLE end, tolerate EOF on logout)
   - [x] Harden Message-ID parsing to tolerate malformed headers without crashing watchers
   - [x] Yahoo hard-delete after successful Gmail insert + catch-up deletes with retry/backoff
   - [x] Admin UI (LAN-only) for status, logs, and OAuth refresh
   - [x] Pushover alerts on OAuth failures + alert history in admin UI
   - [x] README expanded with Gmail API setup, master key generation, env reference, and project rationale
   - [x] Added `gmail_filters.md` documenting Gmail filter rules (manual use)
   - [x] Added explicit DNS servers in docker-compose to avoid OAuth/Pushover failures when container DNS breaks
   - [x] Pushover reliability: force DNS refresh (`getaddrinfo`) before each send attempt
   - [x] Pushover retries: increase backoff to `2s`, then `5s`
   - [x] Pushover observability: log DNS failures separately from generic send failures
   - [x] Added unit tests for per-attempt DNS refresh and DNS error handling
