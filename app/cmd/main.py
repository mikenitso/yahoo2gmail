import os
import sys
import time

from app.config.config import ConfigError, config_summary, load_config
from app.crypto.secretbox import load_master_key
from app.gmail.gmail_client import build_service
from app.gmail.labels import ensure_label, get_system_label_ids
from app.gmail.oauth import OAuthError, build_credentials, exchange_code_for_tokens, get_authorization_url
from app.imap.mailbox_watcher import discover_mailboxes
from app.imap.yahoo_client import YahooIMAPClient, load_or_store_app_password
from app.log.logger import get_logger, log_event
from app.notify.manager import AlertManager
from app.store.db import connect
from app.store.migrations import apply_migrations
from app.sync.orchestrator import run
from app.admin.server import start_admin_server


def _ensure_account(conn, yahoo_email: str, gmail_user: str) -> int:
    row = conn.execute(
        "SELECT id FROM accounts WHERE yahoo_email=? AND gmail_user=?",
        (yahoo_email, gmail_user),
    ).fetchone()
    if row:
        return row[0]
    with conn:
        cur = conn.execute(
            "INSERT INTO accounts(yahoo_email, gmail_user) VALUES (?, ?)",
            (yahoo_email, gmail_user),
        )
        return cur.lastrowid


def main() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    logger = get_logger("y2g", config.log_level)
    log_event(logger, "startup", "starting yahoo2gmail-forwarder", **config_summary(config))

    master_key = load_master_key(config.app_master_key)
    conn = connect(config.sqlite_path)

    migrations_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "migrations"))
    apply_migrations(config.sqlite_path, migrations_dir, logger=logger)

    if len(sys.argv) > 1 and sys.argv[1] == "oauth":
        auth_url, _ = get_authorization_url(
            config.gmail_oauth_client_id,
            config.gmail_oauth_client_secret,
            config.gmail_oauth_redirect_uri,
        )
        log_event(logger, "oauth_url", "gmail oauth url", auth_url=auth_url)
        if len(sys.argv) > 2:
            exchange_code_for_tokens(
                conn,
                master_key,
                config.gmail_oauth_client_id,
                config.gmail_oauth_client_secret,
                config.gmail_oauth_redirect_uri,
                sys.argv[2],
            )
            log_event(logger, "oauth_saved", "gmail oauth tokens saved")
            return 0
        return 1

    alert_manager = AlertManager(
        config.pushover_enabled,
        config.pushover_api_token,
        config.pushover_user_key,
        config.pushover_cooldown_minutes,
    )

    if config.admin_enabled:
        start_admin_server(
            config.admin_host,
            config.admin_port,
            conn_factory=lambda: connect(config.sqlite_path),
            master_key=master_key,
            logger=logger,
            oauth_client_id=config.gmail_oauth_client_id,
            oauth_client_secret=config.gmail_oauth_client_secret,
            oauth_redirect_uri=config.gmail_oauth_redirect_uri,
        )

    try:
        creds = build_credentials(
            conn,
            master_key,
            config.gmail_oauth_client_id,
            config.gmail_oauth_client_secret,
            config.gmail_oauth_redirect_uri,
            alert_manager=alert_manager,
            logger=logger,
        )
    except OAuthError:
        auth_url, _ = get_authorization_url(
            config.gmail_oauth_client_id,
            config.gmail_oauth_client_secret,
            config.gmail_oauth_redirect_uri,
        )
        log_event(logger, "oauth_missing", "gmail oauth tokens missing", auth_url=auth_url)
        alert_manager.send(
            conn,
            "oauth_missing",
            "Gmail OAuth tokens missing",
            f"Tokens missing. Re-authorize via admin UI. Auth URL: {auth_url}",
            logger=logger,
        )
        if config.admin_enabled:
            while True:
                time.sleep(60)
        return 1

    service = build_service(creds)
    account_id = _ensure_account(conn, config.yahoo_email, "me")
    label_id = None
    if config.gmail_label:
        label_id = ensure_label(service, conn, account_id, config.gmail_label)
    system_labels = get_system_label_ids(service, ["INBOX", "UNREAD"])

    app_password = load_or_store_app_password(conn, master_key, config.yahoo_app_password)

    def imap_client_factory():
        client = YahooIMAPClient(
            config.yahoo_imap_host,
            config.yahoo_imap_port,
            config.yahoo_email,
            app_password,
        )
        client.connect()
        return client

    if config.watch_mailboxes:
        watch_mailboxes = config.watch_mailboxes
    else:
        client = imap_client_factory()
        all_mailboxes = client.list_mailboxes()
        client.close()
        watch_mailboxes = discover_mailboxes(all_mailboxes)

    log_event(logger, "mailboxes", "watching mailboxes", mailboxes=watch_mailboxes)

    conn.close()

    run(
        account_id,
        imap_client_factory,
        service,
        "me",
        label_id,
        config.deliver_to_inbox,
        system_labels["INBOX"],
        system_labels["UNREAD"],
        watch_mailboxes,
        logger=logger,
        conn_factory=lambda: connect(config.sqlite_path),
        alert_manager=alert_manager,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
