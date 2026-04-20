# yahoo2gmail-forwarder

Self-hosted Yahoo Mail to Gmail sync for people who want Gmailify-like behavior without relying on Yahoo forwarding.

It watches Yahoo over IMAP, fetches raw RFC822 messages, and inserts them into Gmail through the Gmail API while preserving headers, threading, HTML, inline images, and attachments. It also mirrors Yahoo `Sent` mail into Gmail `Sent`, while suppressing duplicates for messages already sent from Gmail using the Yahoo alias.

## What it does

- Syncs new Yahoo mail from `INBOX`, spam/bulk/junk folders, and `Sent`
- Preserves MIME fidelity by inserting raw RFC822 into Gmail
- Preserves Gmail threading using `Message-ID`, `In-Reply-To`, and `References`
- Uses SQLite state and retry logic to avoid duplicate inserts across restarts
- Deletes processed Yahoo messages after successful handling
- Exposes an optional local admin UI for OAuth setup and runtime status
- Supports optional Pushover alerts with DNS-refresh and retry hardening

## What it does not do

- Backfill old Yahoo mail before first startup
- Two-way sync from Gmail back to Yahoo
- Label, read-state, or delete reconciliation between systems
- Full bidirectional mailbox mirroring

## Why this exists

Yahoo forwarding is inconsistent, especially for spam/bulk folders. Gmailify used to cover much of this use case, but it is no longer broadly available and it was never a self-hosted option. This project is a pragmatic one-way bridge: get Yahoo mail into Gmail reliably, preserve the original message, and keep failure handling simple enough to run on a home server.

## How it works

```text
Yahoo IMAP (INBOX / Spam / Bulk / Sent)
  -> watcher detects new UID
  -> raw RFC822 fetched from Yahoo
  -> SQLite state + lease decides whether work is new / retryable
  -> Gmail API insert/import runs
  -> Yahoo message is deleted after success

Sent folder special case:
  -> strict Message-ID lookup in Gmail
  -> already exists in Gmail: delete Yahoo Sent copy only
  -> not found in Gmail: insert into Gmail SENT, attach to thread if possible, then delete from Yahoo Sent
```

## Architecture

- Runtime: single container, long-running process
- Yahoo side: IMAP over TLS with IDLE per watched mailbox
- Gmail side: Gmail API OAuth, `insert` or `import` delivery
- State: SQLite for exactly-once semantics, retries, leases, and secret storage
- Secrets: encrypted at rest with `APP_MASTER_KEY`
- Admin UI: optional LAN-only UI for OAuth and status

## Quick start

### 1. Create Google OAuth credentials

1. Create or select a Google Cloud project.
2. Enable the Gmail API.
3. Create an OAuth client.
4. Set `GMAIL_OAUTH_CLIENT_ID`, `GMAIL_OAUTH_CLIENT_SECRET`, and `GMAIL_OAUTH_REDIRECT_URI`.

### 2. Generate an app master key

```bash
openssl rand -base64 32
```

Set the output as `APP_MASTER_KEY`.

### 3. Configure environment

Copy your env file and fill in the required values:

```bash
cp .env.example .env
```

Minimum required variables:

- `YAHOO_EMAIL`
- `YAHOO_APP_PASSWORD`
- `APP_MASTER_KEY`
- `GMAIL_OAUTH_CLIENT_ID`
- `GMAIL_OAUTH_CLIENT_SECRET`
- `GMAIL_OAUTH_REDIRECT_URI`

### 4. Complete Gmail OAuth

```bash
python -m app.cmd.main oauth <AUTH_CODE>
```

If tokens are missing, the app logs an authorization URL you can open in a browser.

### 5. Start the service

```bash
docker compose up --build -d
```

Persist `/data` to keep SQLite state and encrypted OAuth tokens.

## Docker / Portainer notes

The included `docker-compose.yml` is suitable for a long-running home-server deployment:

- container restart policy is `unless-stopped`
- persistent data is stored under `/data`
- admin UI is exposed on port `8787`
- runtime env vars are passed through directly from `.env`

If you deploy with Portainer from GitHub, pushing to `main` is enough for a standard repo-based stack update.

## Configuration reference

### Required

- `YAHOO_EMAIL`: Yahoo account used for IMAP login
- `YAHOO_APP_PASSWORD`: Yahoo app password; stored encrypted after first run
- `APP_MASTER_KEY`: 32-byte base64 key used to encrypt stored secrets
- `GMAIL_OAUTH_CLIENT_ID`: Google OAuth client ID
- `GMAIL_OAUTH_CLIENT_SECRET`: Google OAuth client secret
- `GMAIL_OAUTH_REDIRECT_URI`: Redirect URI configured in Google Cloud

### Common optional settings

- `SQLITE_PATH` default `/data/app.db`
- `YAHOO_IMAP_HOST` default `imap.mail.yahoo.com`
- `YAHOO_IMAP_PORT` default `993`
- `GMAIL_LABEL` default `yahoo`
- `GMAIL_DELIVERY_MODE` default `insert`
- `DELIVER_TO_INBOX` default `true`
- `WATCH_MAILBOXES` default auto-discovery of `INBOX`, spam/bulk/junk, and `Sent`
- `LOG_LEVEL` default `INFO`
- `ADMIN_ENABLED` default `false`
- `ADMIN_HOST` default `0.0.0.0`
- `ADMIN_PORT` default `8787`

### Pushover

- `PUSHOVER_ENABLED`
- `PUSHOVER_API_TOKEN`
- `PUSHOVER_USER_KEY`
- `PUSHOVER_COOLDOWN_MINUTES` default `360`

Pushover delivery is hardened for long-uptime containers by forcing a DNS lookup of `api.pushover.net` before each send attempt and retrying transient failures with `2s` then `5s` backoff.

## Sent mirroring behavior

Yahoo `Sent` is treated differently from inbound mail:

- If Gmail already contains the same `Message-ID`, the Yahoo Sent copy is treated as a duplicate and deleted
- If Gmail does not contain that `Message-ID`, the message is inserted into Gmail with the `SENT` label only
- If `In-Reply-To` or `References` match an existing Gmail message, the inserted sent message joins that Gmail conversation
- Sent messages inserted from Yahoo-originated clients do not get the custom Yahoo label and do not receive the `INBOX` label

This makes Gmail alias sends and Yahoo-originated sends coexist cleanly.

## Admin UI

When `ADMIN_ENABLED=true`, the app starts a small LAN-facing admin server that provides:

- Gmail OAuth bootstrap and re-authorization flow
- current status and recent errors
- per-mailbox watcher heartbeat data, including last success and last error
- recent in-memory logs
- a basic Pushover test action

If you expose it beyond your LAN, put it behind authentication.

## Reliability model

- No backfill: only mail arriving after startup is processed
- Yahoo UID plus SQLite state is the source of truth for exactly-once handling
- Retry worker handles transient Gmail failures with exponential backoff
- Stuck leases are recovered on startup
- Processed Yahoo messages are deleted only after the required Gmail-side action succeeds

## Manual verification

See [ACCEPTANCE_CHECKLIST.md](ACCEPTANCE_CHECKLIST.md) for the current manual acceptance tests, including:

- inbound forwarding
- Gmail threading
- spam/bulk handling
- restart safety
- Yahoo Sent duplicate suppression
- Yahoo-originated Sent mirroring

## Repository guide

- [SPEC.md](SPEC.md): current product and behavior spec
- [TASKS.md](TASKS.md): implementation progress notes
- [docs/plans/2026-03-28-yahoo-sent-mirroring-plan.md](docs/plans/2026-03-28-yahoo-sent-mirroring-plan.md): planning doc for Sent mirroring

## Status

The project is currently best described as a robust one-way Yahoo to Gmail bridge with Sent mirroring. It is suitable for self-hosted personal use, but it is not yet a general-purpose two-way mail sync engine.
