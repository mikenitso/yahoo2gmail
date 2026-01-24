# Decisions

## Summary (2026-01-18)

- Added an optional LAN-only admin UI (disabled by default) for status, recent logs, and OAuth refresh.
- Implemented startup catch-up scan (process messages received while down) without changing no-backfill semantics.
- Added UIDVALIDITY change detection to reset mailbox state safely.
- Improved IMAP stability: longer IDLE timeout, reconnect on IDLE end, tolerate logout EOF, watcher restart loop.
- Added Yahoo hard-delete after confirmed Gmail import plus catch-up deletion with retry/backoff.
- Added Pushover alerts for OAuth failures and missing tokens with cooldown, and alert history in admin UI.
- Expanded README for Gmail API setup, master key generation, env reference, and Gmailify context.
- Added `gmail_filters.md` for manual Gmail categorization rules.

## Summary (2026-01-24)

- Switched Gmail ingestion to `users.messages.import` so Gmail can apply standard processing (spam/categorization/user filters).
- Kept label semantics (yahoo label, optional INBOX, UNREAD based on Yahoo \\Seen).
- Preserved threading by keeping original headers and using thread lookup where possible.

## Rationale

- Admin UI addresses operational recovery without CLI access (especially for OAuth renewal).
- IMAP changes reduce frequent disconnect churn and improve reliability under Yahoo server IDLE policies.
- Deleting Yahoo messages only after successful Gmail import ensures no data loss and helps clean up backlog.
- Pushover alerts provide proactive notification when tokens expire or are missing.

## Rationale (2026-01-24)

- `messages.import` aligns with Gmail's inbound processing pipeline while avoiding outbound re-sends.
- Maintaining label policy and threading preserves existing user expectations while enabling Gmail classification.
