#!/usr/bin/env python3
import argparse
import base64
import email.message
import email.utils
import os
import sys
from typing import Optional

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

from app.crypto.secretbox import load_master_key
from app.gmail.gmail_client import build_service
from app.gmail.labels import ensure_label, get_system_label_ids
from app.gmail.oauth import build_credentials
from app.store.db import connect


def load_env_file(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if (value.startswith("\"") and value.endswith("\"")) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            if key not in os.environ:
                os.environ[key] = value


def resolve_sqlite_path(explicit_path: Optional[str]) -> str:
    if explicit_path:
        return explicit_path
    env_path = os.getenv("SQLITE_PATH")
    local_path = os.path.join(REPO_ROOT, "data", "app.db")
    if env_path:
        if os.path.exists(env_path):
            return env_path
        if os.path.exists(local_path):
            return local_path
        return env_path
    if os.path.exists(local_path):
        return local_path
    return "/data/app.db"


def read_rfc822_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def build_rfc822_bytes(sender: str, recipient: str, subject: str, body: str) -> bytes:
    msg = email.message.EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid()
    msg.set_content(body)
    return msg.as_bytes()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test Gmail users.messages.import with mailbox label application.",
    )
    parser.add_argument(
        "--eml",
        help="Path to RFC822 .eml file to import.",
    )
    parser.add_argument(
        "--from",
        dest="from_addr",
        help="From email address for generated message.",
    )
    parser.add_argument(
        "--to",
        dest="to_addr",
        help="To email address for generated message.",
    )
    parser.add_argument(
        "--subject",
        help="Subject for generated message.",
    )
    parser.add_argument(
        "--body",
        help="Body text for generated message.",
    )
    parser.add_argument(
        "--env",
        default=os.path.join(REPO_ROOT, ".env"),
        help="Path to .env file (default: repo .env).",
    )
    parser.add_argument(
        "--sqlite-path",
        help="Override SQLITE_PATH for token/label storage.",
    )
    parser.add_argument(
        "--user-id",
        default="me",
        help="Gmail userId for API calls (default: me).",
    )
    parser.add_argument(
        "--account-id",
        type=int,
        help="Account id for label cache (default: first row in accounts).",
    )
    parser.add_argument(
        "--gmail-label",
        help="Override GMAIL_LABEL (base label).",
    )
    parser.add_argument(
        "--skip-base-label",
        action="store_true",
        help="Do not apply the base GMAIL_LABEL.",
    )
    parser.add_argument(
        "--mailbox",
        help="Mailbox name to apply as a sub-label of GMAIL_LABEL.",
    )
    parser.add_argument(
        "--mailbox-label",
        help="Explicit mailbox label name (overrides --mailbox).",
    )
    parser.add_argument(
        "--no-inbox",
        action="store_true",
        help="Do not apply the INBOX label.",
    )
    parser.add_argument(
        "--read",
        action="store_true",
        help="Mark as read (omit UNREAD label).",
    )
    parser.add_argument(
        "--internal-date-source",
        default="dateHeader",
        choices=["dateHeader", "receivedTime"],
        help="Import internalDateSource (default: dateHeader).",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Fetch imported message metadata and print resolved labels.",
    )
    args = parser.parse_args()
    has_eml = bool(args.eml)
    has_generated = all([args.from_addr, args.to_addr, args.subject, args.body])
    if not has_eml and not has_generated:
        parser.error("Provide --eml or all of --from, --to, --subject, --body.")
    if has_eml and has_generated:
        parser.error("Use either --eml or --from/--to/--subject/--body, not both.")
    return args


def main() -> int:
    args = parse_args()
    load_env_file(args.env)

    master_key_raw = os.getenv("APP_MASTER_KEY")
    if not master_key_raw:
        print("APP_MASTER_KEY is required (from .env).", file=sys.stderr)
        return 1

    client_id = os.getenv("GMAIL_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GMAIL_OAUTH_CLIENT_SECRET")
    redirect_uri = os.getenv("GMAIL_OAUTH_REDIRECT_URI")
    if not client_id or not client_secret or not redirect_uri:
        print("Missing Gmail OAuth env vars (client id/secret/redirect uri).", file=sys.stderr)
        return 1

    sqlite_path = resolve_sqlite_path(args.sqlite_path)
    conn = connect(sqlite_path)

    if args.account_id is None:
        row = conn.execute("SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()
        if not row:
            print("No accounts found in SQLite. Provide --account-id.", file=sys.stderr)
            return 1
        account_id = int(row[0])
    else:
        account_id = args.account_id

    master_key = load_master_key(master_key_raw)
    credentials = build_credentials(
        conn,
        master_key,
        client_id,
        client_secret,
        redirect_uri,
    )
    service = build_service(credentials)

    if args.eml:
        raw_bytes = read_rfc822_bytes(args.eml)
    else:
        raw_bytes = build_rfc822_bytes(
            args.from_addr,
            args.to_addr,
            args.subject,
            args.body,
        )
    raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

    label_ids = []
    base_label = args.gmail_label if args.gmail_label is not None else os.getenv("GMAIL_LABEL", "yahoo")
    if base_label and not args.skip_base_label:
        label_ids.append(ensure_label(service, conn, account_id, base_label))

    mailbox_label = None
    if args.mailbox_label:
        mailbox_label = args.mailbox_label
    elif args.mailbox:
        mailbox_label = f"{base_label}/{args.mailbox}" if base_label else args.mailbox
    if mailbox_label:
        label_ids.append(ensure_label(service, conn, account_id, mailbox_label))

    system_label_names = []
    if not args.no_inbox:
        system_label_names.append("INBOX")
    if not args.read:
        system_label_names.append("UNREAD")
    if system_label_names:
        system_labels = get_system_label_ids(service, system_label_names)
        label_ids.extend(system_labels[name] for name in system_label_names)

    body = {
        "raw": raw_b64,
        "labelIds": label_ids,
        "internalDateSource": args.internal_date_source,
    }
    result = (
        service.users()
        .messages()
        .import_(userId=args.user_id, body=body)
        .execute()
    )

    msg_id = result.get("id")
    thread_id = result.get("threadId")
    print("Imported message")
    print(f"  id: {msg_id}")
    print(f"  threadId: {thread_id}")
    print(f"  labelIds: {label_ids}")

    if args.verify and msg_id:
        msg = (
            service.users()
            .messages()
            .get(userId=args.user_id, id=msg_id, format="metadata")
            .execute()
        )
        applied = msg.get("labelIds", [])
        labels = service.users().labels().list(userId=args.user_id).execute().get("labels", [])
        label_map = {label.get("id"): label.get("name") for label in labels}
        resolved = [label_map.get(label_id, label_id) for label_id in applied]
        print("Verified labels")
        print(f"  labelIds: {applied}")
        print(f"  labels: {resolved}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
