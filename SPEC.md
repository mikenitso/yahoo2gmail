Yahoo → Gmail Forwarder (v1) — Codex Build Sheet

0) Summary

Build a Dockerized service that:
	•	Connects to Yahoo via IMAP over TLS using an app password
	•	Uses IMAP IDLE to detect new messages in near real-time
	•	Fetches each new email as raw RFC822 bytes (preserve MIME exactly)
	•	Inserts the email into Gmail via Gmail API (users.messages.insert) unchanged
	•	Applies a Gmail label (default: yahoo) and places it in INBOX
	•	Lets Gmail auto-classify messages into its categories/spam (no special handling)
	•	Ensures exactly-once semantics using SQLite state + leases + dedupe keys
	•	Logs everything (structured), no UI, no external alerts (logs only)
	•	No backfill: it only forwards messages arriving after startup cutover

⸻

1) Requirements

1.1 Functional
	1.	Monitor Yahoo mailboxes using IMAP IDLE:
	•	Must include INBOX and Spam/Bulk/Junk equivalent.
	•	Must not rely on Yahoo’s paid forwarding.
	2.	Forward every message from watched mailboxes (no filters).
	3.	Preserve full fidelity:
	•	Insert raw RFC822 unchanged (HTML, inline images, attachments intact).
	4.	Preserve original sender and threading in Gmail:
	•	Keep original headers (Message-ID, In-Reply-To, References, Subject, Date).
	5.	Gmail insertion:
	•	Use Gmail API with OAuth consent.
	•	Message must arrive in INBOX and get label yahoo (configurable).
	6.	Exactly-once semantics:
	•	No duplicates across restarts, network failures, partial crashes.
	7.	Retry on failure with exponential backoff; log failures.

1.2 Non-functional
	•	Runs on home server in Docker
	•	Uses SQLite for dedupe + state
	•	Encrypt Yahoo app password (and optionally Gmail tokens) using an env-provided master key
	•	Logging must be “production-grade” (structured JSON recommended)
	•	If Pushover alerts are enabled, resolve `api.pushover.net` before each send attempt to avoid stale DNS state in long-uptime containers
	•	If Pushover alerts are enabled, retry transient failures with backoff (`2s`, then `5s`) and log DNS failures separately from generic send failures

⸻

2) Architecture

2.1 Modules (source layout)

/app
  /cmd
    main.py (or main.ts)
  /config
    config.py
  /imap
    yahoo_client.py
    mailbox_watcher.py
  /gmail
    oauth.py
    gmail_client.py
    labels.py
  /store
    db.py
    migrations.py
    models.py
    lease.py
  /sync
    orchestrator.py
    retry_worker.py
    message_pipeline.py
  /crypto
    secretbox.py
  /log
    logger.py
  /tests
    ...
Dockerfile
docker-compose.yml
README.md

2.2 Runtime processes
	•	Single process with:
	•	N mailbox watcher tasks (one per mailbox selected/IDLE)
	•	One retry worker task polling SQLite for due work

⸻

3) Configuration

3.1 Environment variables

Required:
	•	YAHOO_EMAIL
	•	YAHOO_APP_PASSWORD (bootstrap only; stored encrypted after first run)
	•	APP_MASTER_KEY (required; base64/hex; used to encrypt secrets)
	•	GMAIL_OAUTH_CLIENT_ID
	•	GMAIL_OAUTH_CLIENT_SECRET
	•	GMAIL_OAUTH_REDIRECT_URI
	•	SQLITE_PATH default /data/app.db

Recommended defaults:
	•	YAHOO_IMAP_HOST=imap.mail.yahoo.com
	•	YAHOO_IMAP_PORT=993
	•	GMAIL_LABEL=yahoo
	•	DELIVER_TO_INBOX=true
	•	LOG_LEVEL=INFO

Mailbox selection:
	•	WATCH_MAILBOXES optional comma-separated list; if unset:
	•	auto-discover and include: INBOX + spam/bulk/junk equivalents
	•	exclude: Sent/Drafts/Trash/Archive by default (future-proofing two-way)

⸻

4) Gmail API behavior

4.1 OAuth scopes (minimum)
	•	https://www.googleapis.com/auth/gmail.insert
	•	https://www.googleapis.com/auth/gmail.labels (to create/find label)

(If library requires broader but still safe, document why.)

4.2 Labeling
	•	On startup:
	•	Lookup label by name GMAIL_LABEL
	•	If missing, create it
	•	Cache labelId in SQLite table gmail_labels

4.3 Insert call

Use users.messages.insert with:
	•	raw: base64url(RFC822 bytes)
	•	labelIds: include
	•	INBOX if DELIVER_TO_INBOX=true
	•	<labelId for yahoo>
	•	UNREAD if Yahoo flags do NOT include \Seen

Store returned IDs:
	•	Gmail id → gmail_message_id
	•	Gmail threadId → gmail_thread_id

Do not use send endpoint (no SMTP sending) because we want import semantics and thread/header preservation.

⸻

5) Yahoo IMAP behavior

5.1 Connection
	•	TLS to imap.mail.yahoo.com:993
	•	LOGIN with YAHOO_EMAIL + app password
	•	Detect server capabilities; require IDLE, otherwise fallback to polling (polling is allowed as fallback but IDLE is primary).

5.2 No backfill

On first startup (or when mailbox newly added):
	•	Determine highest current UID in that mailbox and set last_seen_uid to it.
	•	Start IDLE and process only UIDs greater than last_seen_uid.

5.3 New mail detection

When IDLE reports changes:
	•	Exit IDLE
	•	UID SEARCH UID <last_seen_uid+1>:* (or equivalent)
	•	For each UID found:
	•	Create messages row if not exists
	•	Fetch RFC822 + FLAGS + INTERNALDATE
	•	Transition state → FETCHED
	•	Update last_seen_uid to max processed UID
	•	Re-enter IDLE

5.4 Watched mailboxes

If auto-discovery:
	•	LIST "" "*"
	•	Include:
	•	mailbox name equals INBOX (case-insensitive)
	•	mailbox name contains one of: Bulk, Junk, Spam (case-insensitive)
	•	Exclude (unless explicitly configured):
	•	Sent, Drafts, Trash, Deleted, Archive
Store discovered mailbox + UIDVALIDITY in mailboxes.

⸻

6) Storage (SQLite)

6.1 Tables (must implement)

secrets(key, ciphertext, created_at)

accounts(id, yahoo_email, gmail_user, created_at)

mailboxes(id, account_id, name, uidvalidity, last_seen_uid, created_at, updated_at)

messages( id, account_id, mailbox_name, uidvalidity, uid, message_id, rfc822_sha256, imap_internaldate, imap_flags_json, state, attempt_count, next_attempt_at, last_error, gmail_message_id, gmail_thread_id, created_at, updated_at )
Unique:
	•	(account_id, mailbox_name, uidvalidity, uid)

gmail_labels(account_id, label_name, label_id)

6.2 Message states
	•	DISCOVERED (optional intermediary)
	•	FETCHED
	•	INSERTING
	•	INSERTED
	•	FAILED_RETRY
	•	FAILED_PERM

⸻

7) Exactly-once semantics

7.1 Primary dedupe key
	•	(account_id, mailbox_name, uidvalidity, uid) is the source-of-truth identity.

7.2 Lease / atomic transition

To begin insertion:
	•	Transaction:
	•	UPDATE messages SET state='INSERTING', updated_at=now WHERE id=? AND state IN ('FETCHED','FAILED_RETRY') AND (next_attempt_at IS NULL OR next_attempt_at <= now);
	•	Only proceed if affected rows == 1.

On success:
	•	Transaction: set INSERTED and store Gmail IDs.

On failure:
	•	Set FAILED_RETRY, set attempt_count += 1, set next_attempt_at.

7.3 Crash recovery
	•	On startup, any row stuck in INSERTING older than 10 minutes → move to FAILED_RETRY and retry.

7.4 Future-proof headers (must add, non-visible)

Before inserting into Gmail, add headers without changing body/MIME:
	•	X-Y2G-Source: yahoo
	•	X-Y2G-Mailbox: <mailbox_name>
	•	X-Y2G-UIDValidity: <uidvalidity>
	•	X-Y2G-UID: <uid>
	•	X-Y2G-RFC822-SHA256: <hash>
These support future two-way reconciliation and post-crash dedupe strategies.

Implementation detail:
	•	Add headers by rewriting only the RFC822 header section (preserving CRLF), not modifying MIME parts.

⸻

8) Retry policy

8.1 Backoff schedule

Exponential with cap + jitter:
	•	1m, 2m, 4m, 8m, 15m, 30m, 60m (cap)

8.2 Retryable conditions
	•	Network errors
	•	Gmail 429, 5xx
	•	OAuth refresh failures (retry after token refresh attempt)

8.3 Non-retryable
	•	Gmail 4xx indicating permanent invalid message (rare)
	•	Invalid credentials after one refresh cycle

⸻

9) Logging

9.1 Format
	•	Structured JSON logs (one event per line)

9.2 Required log events
	•	Startup config summary (redacting secrets)
	•	Mailbox discovery list
	•	IDLE connect/disconnect/reconnect
	•	Message discovered (mailbox, uidvalidity, uid)
	•	Message fetched (size, sha256, message-id)
	•	Insert attempt (lease acquired)
	•	Insert success (gmail_message_id, threadId)
	•	Insert failure (error class/status, retry schedule)
	•	SQLite migration status

9.3 Correlation IDs
	•	Use correlation id = mailbox|uidvalidity|uid

⸻

10) Docker

10.1 Persistent storage
	•	Mount /data for SQLite and OAuth token storage.

10.2 Minimal docker-compose requirements
	•	restart: unless-stopped
	•	env vars
	•	volume mount

⸻

11) Acceptance tests (manual is fine for v1)
	1.	Cutover test (no backfill)
	•	Stop Gmailify.
	•	Start service.
	•	Send test email to Yahoo; verify appears in Gmail within ~1 minute.
	2.	Threading
	•	Reply to a Yahoo email in Yahoo to create In-Reply-To/References.
	•	Confirm Gmail shows the reply in the same thread.
	3.	Inline images / rich HTML
	•	Send newsletter-style HTML email with CID images.
	•	Verify Gmail renders identically (or as close as Gmail normally does) and inline images appear.
	4.	Attachments
	•	Send PDF attachment; verify appears in Gmail and opens.
	5.	Spam
	•	Ensure a message landing in Yahoo “Bulk/Spam” is also inserted into Gmail; allow Gmail to auto-classify.
	6.	Exactly-once under restart
	•	While sending multiple emails to Yahoo, restart the container repeatedly.
	•	Verify no duplicates in Gmail.
	7.	Failure + retry
	•	Block outbound network temporarily.
	•	Confirm failures logged and retries occur; eventually messages insert.

⸻

12) Implementation notes for Codex (important “gotchas”)
	•	IMAP IDLE is per-selected mailbox; use one connection per mailbox.
	•	Yahoo mailbox naming differs by locale; the spam folder name may vary; use capability + LIST scanning for “Bulk/Spam/Junk” substrings.
	•	Gmail API expects base64url encoding (not standard base64).
	•	Message-ID headers can be malformed; parsing must be lenient and never crash the watcher. Treat invalid or missing Message-ID as null.
	•	When adding X-Y2G-* headers, preserve CRLF and ensure header folding rules (RFC 5322) are respected.
	•	Token refresh must be robust; store tokens persistently.

⸻
