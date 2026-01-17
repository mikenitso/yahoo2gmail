# yahoo2gmail-forwarder

Yahoo → Gmail Forwarder (v1). Dockerized service that watches Yahoo IMAP (IDLE), fetches raw RFC822, and inserts into Gmail via Gmail API with exactly-once semantics.

## Quick start (v1)

### Gmail API setup

1) Create a Google Cloud project (or use an existing one).

2) Enable the Gmail API for that project.

3) Create an OAuth client (Desktop app or Web app):
   - You will get a client ID and client secret (from the JSON client secrets).
   - Set the redirect URI to match `GMAIL_OAUTH_REDIRECT_URI` (default example: `http://localhost`).
   - Note the project ID (sometimes called "application ID" in the console) for your records.

4) Copy the OAuth values into `.env`:
   - `GMAIL_OAUTH_CLIENT_ID`
   - `GMAIL_OAUTH_CLIENT_SECRET`
   - `GMAIL_OAUTH_REDIRECT_URI`

### Generate the master key

The app encrypts stored secrets (Yahoo app password and OAuth tokens) using a 32-byte master key.

Generate one (base64):

```bash
openssl rand -base64 32
```

Set it in `.env` as `APP_MASTER_KEY`.

### Admin UI (optional)

Set `ADMIN_ENABLED=true` to start a small LAN-only admin UI inside the container.
By default it binds to `0.0.0.0:8787`.

The UI provides:
- Status (last insert, last Yahoo delete, token validity, last errors)
- Recent logs (last 20 lines, from an in-memory buffer)
- OAuth flow: generate auth URL and exchange a full redirect URL

If you expose it beyond your LAN, add a reverse proxy with authentication.

1) Copy env template:

```bash
cp .env.example .env
```

2) Fill in required environment variables in `.env`.

3) Complete Gmail OAuth (one-time):

```bash
python -m app.cmd.main oauth <AUTH_CODE>
```

The command will log an authorization URL if you don’t already have one. Visit it, approve access, and paste the returned code.
OAuth tokens are stored (encrypted) in the SQLite database.

4) Run with Docker:

```bash
docker compose up --build
```

Data (SQLite + OAuth tokens) is stored in `/data` inside the container and should be mounted to a host volume.

## .env reference

All configuration is driven by environment variables in `.env` (see `.env.example`).

Required:

- `YAHOO_EMAIL`: Your Yahoo email address used for IMAP login.
- `YAHOO_APP_PASSWORD`: Yahoo app password (stored encrypted after first run).
- `APP_MASTER_KEY`: 32‑byte base64 master key for encrypting stored secrets.
- `GMAIL_OAUTH_CLIENT_ID`: OAuth client ID from Google Cloud.
- `GMAIL_OAUTH_CLIENT_SECRET`: OAuth client secret from Google Cloud.
- `GMAIL_OAUTH_REDIRECT_URI`: Redirect URI configured on the OAuth client.

Optional / defaults:

- `SQLITE_PATH` (default `/data/app.db`): SQLite DB path inside the container.
- `YAHOO_IMAP_HOST` (default `imap.mail.yahoo.com`): IMAP hostname.
- `YAHOO_IMAP_PORT` (default `993`): IMAP TLS port.
- `GMAIL_LABEL` (default `yahoo`): Gmail label applied to inserted messages. Set empty to disable.
- `DELIVER_TO_INBOX` (default `true`): Add INBOX label when inserting into Gmail.
- `LOG_LEVEL` (default `INFO`): Log level (e.g., INFO, DEBUG).
- `Y2G_DATA_PATH` (optional): Host path to bind‑mount to `/data` in Docker Compose.
- `ADMIN_ENABLED` (default `false`): Enable the admin UI.
- `ADMIN_HOST` (default `0.0.0.0`): Bind address for the admin UI.
- `ADMIN_PORT` (default `8787`): Port for the admin UI.

## Notes

- No backfill: only messages arriving after startup are forwarded.
- No UI; logs only.
- See `SPEC.md` and `TASKS.md` for requirements and progress.
