import os
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class AppConfig:
    yahoo_email: str
    yahoo_app_password: Optional[str]
    yahoo_imap_host: str
    yahoo_imap_port: int
    gmail_oauth_client_id: str
    gmail_oauth_client_secret: str
    gmail_oauth_redirect_uri: str
    gmail_label: str
    deliver_to_inbox: bool
    watch_mailboxes: Optional[List[str]]
    sqlite_path: str
    app_master_key: str
    log_level: str


class ConfigError(Exception):
    pass


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _get_bool(name: str, default: bool) -> bool:
    value = _get_env(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _get_int(name: str, default: int) -> int:
    value = _get_env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _parse_mailboxes(raw: Optional[str]) -> Optional[List[str]]:
    if not raw:
        return None
    items = [part.strip() for part in raw.split(",") if part.strip()]
    return items or None


def load_config() -> AppConfig:
    yahoo_email = _get_env("YAHOO_EMAIL")
    yahoo_app_password = _get_env("YAHOO_APP_PASSWORD")
    app_master_key = _get_env("APP_MASTER_KEY")
    gmail_oauth_client_id = _get_env("GMAIL_OAUTH_CLIENT_ID")
    gmail_oauth_client_secret = _get_env("GMAIL_OAUTH_CLIENT_SECRET")
    gmail_oauth_redirect_uri = _get_env("GMAIL_OAUTH_REDIRECT_URI")

    missing = []
    if not yahoo_email:
        missing.append("YAHOO_EMAIL")
    if not app_master_key:
        missing.append("APP_MASTER_KEY")
    if not gmail_oauth_client_id:
        missing.append("GMAIL_OAUTH_CLIENT_ID")
    if not gmail_oauth_client_secret:
        missing.append("GMAIL_OAUTH_CLIENT_SECRET")
    if not gmail_oauth_redirect_uri:
        missing.append("GMAIL_OAUTH_REDIRECT_URI")

    if missing:
        raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")

    gmail_label_raw = os.getenv("GMAIL_LABEL")
    if gmail_label_raw is None:
        gmail_label = "yahoo"
    else:
        gmail_label = gmail_label_raw

    return AppConfig(
        yahoo_email=yahoo_email,
        yahoo_app_password=yahoo_app_password,
        yahoo_imap_host=_get_env("YAHOO_IMAP_HOST", "imap.mail.yahoo.com"),
        yahoo_imap_port=_get_int("YAHOO_IMAP_PORT", 993),
        gmail_oauth_client_id=gmail_oauth_client_id,
        gmail_oauth_client_secret=gmail_oauth_client_secret,
        gmail_oauth_redirect_uri=gmail_oauth_redirect_uri,
        gmail_label=gmail_label,
        deliver_to_inbox=_get_bool("DELIVER_TO_INBOX", True),
        watch_mailboxes=_parse_mailboxes(_get_env("WATCH_MAILBOXES")),
        sqlite_path=_get_env("SQLITE_PATH", "/data/app.db"),
        app_master_key=app_master_key,
        log_level=_get_env("LOG_LEVEL", "INFO"),
    )


def config_summary(config: AppConfig) -> dict:
    return {
        "yahoo_email": config.yahoo_email,
        "yahoo_app_password": "set" if config.yahoo_app_password else "not_set",
        "yahoo_imap_host": config.yahoo_imap_host,
        "yahoo_imap_port": config.yahoo_imap_port,
        "gmail_oauth_client_id": "set" if config.gmail_oauth_client_id else "not_set",
        "gmail_oauth_client_secret": "set" if config.gmail_oauth_client_secret else "not_set",
        "gmail_oauth_redirect_uri": config.gmail_oauth_redirect_uri,
        "gmail_label": config.gmail_label if config.gmail_label else "disabled",
        "deliver_to_inbox": config.deliver_to_inbox,
        "watch_mailboxes": config.watch_mailboxes,
        "sqlite_path": config.sqlite_path,
        "app_master_key": "set" if config.app_master_key else "not_set",
        "log_level": config.log_level,
    }
