# Decisions

## Summary (2026-01-18)

- Added an optional LAN-only admin UI (disabled by default) for status, recent logs, and OAuth refresh.
- Implemented startup catch-up scan (process messages received while down) without changing no-backfill semantics.
- Added UIDVALIDITY change detection to reset mailbox state safely.
- Improved IMAP stability: longer IDLE timeout, reconnect on IDLE end, tolerate logout EOF, watcher restart loop.
- Added Yahoo hard-delete after confirmed Gmail insert plus catch-up deletion with retry/backoff.
- Added Pushover alerts for OAuth failures and missing tokens with cooldown, and alert history in admin UI.
- Expanded README for Gmail API setup, master key generation, env reference, and Gmailify context.
- Added `gmail_filters.md` for manual Gmail categorization rules.

## Rationale

- Admin UI addresses operational recovery without CLI access (especially for OAuth renewal).
- IMAP changes reduce frequent disconnect churn and improve reliability under Yahoo server IDLE policies.
- Deleting Yahoo messages only after successful Gmail insert ensures no data loss and helps clean up backlog.
- Pushover alerts provide proactive notification when tokens expire or are missing.
