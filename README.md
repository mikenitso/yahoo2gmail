# yahoo2gmail-forwarder

Yahoo → Gmail Forwarder (v1). Dockerized service that watches Yahoo IMAP (IDLE), fetches raw RFC822, and inserts into Gmail via Gmail API with exactly-once semantics.

## Quick start (v1)

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

4) Run with Docker:

```bash
docker compose up --build
```

Data (SQLite + OAuth tokens) is stored in `/data` inside the container and should be mounted to a host volume.

## Notes

- No backfill: only messages arriving after startup are forwarded.
- No UI; logs only.
- See `SPEC.md` and `TASKS.md` for requirements and progress.
