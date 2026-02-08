import json
from datetime import datetime, timezone
from json import JSONDecodeError
from typing import Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.store import secrets

SCOPES = [
    "https://www.googleapis.com/auth/gmail.insert",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.readonly",
]

TOKEN_SECRET_KEY = "gmail_oauth_tokens"


class OAuthError(Exception):
    pass


def _client_config(client_id: str, client_secret: str, redirect_uri: str) -> dict:
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": [redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def load_tokens(conn, master_key: bytes) -> Optional[dict]:
    raw = secrets.get_secret(conn, TOKEN_SECRET_KEY, master_key)
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def save_tokens(conn, master_key: bytes, token_dict: dict) -> None:
    payload = json.dumps(token_dict, separators=(",", ":")).encode("utf-8")
    secrets.set_secret(conn, TOKEN_SECRET_KEY, payload, master_key)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _alert_reauth_required(conn, alert_manager, logger, kind: str, detail: str) -> None:
    if not alert_manager:
        return
    alert_manager.send(
        conn,
        kind,
        "Gmail OAuth requires re-authorization",
        f"{detail}. Refresh OAuth tokens via admin UI.",
        logger=logger,
    )


def _refresh_error_alert_kind(exc: Exception) -> str:
    lower = str(exc).lower()
    if "invalid_grant" in lower:
        return "oauth_invalid_grant"
    if "invalid_client" in lower:
        return "oauth_client_mismatch"
    return "oauth_invalid"


def build_credentials(
    conn,
    master_key: bytes,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    alert_manager=None,
    logger=None,
) -> Credentials:
    try:
        token_dict = load_tokens(conn, master_key)
    except (UnicodeDecodeError, JSONDecodeError) as exc:
        _alert_reauth_required(
            conn,
            alert_manager,
            logger,
            "oauth_token_corrupt",
            f"Stored OAuth token payload is unreadable ({exc})",
        )
        raise OAuthError("Gmail OAuth tokens are unreadable; re-authorize via admin UI") from exc

    if not token_dict:
        _alert_reauth_required(
            conn, alert_manager, logger, "oauth_missing", "Gmail OAuth tokens are missing"
        )
        raise OAuthError("Gmail OAuth tokens not found; run OAuth flow")

    token_client_id = token_dict.get("client_id")
    if token_client_id and token_client_id != client_id:
        _alert_reauth_required(
            conn,
            alert_manager,
            logger,
            "oauth_client_mismatch",
            "Stored tokens belong to a different OAuth client_id",
        )
        raise OAuthError("Stored OAuth tokens are for a different client_id; re-authorize via admin UI")

    creds = Credentials.from_authorized_user_info(token_dict, SCOPES)
    token_scopes = set(token_dict.get("scopes") or [])
    if token_scopes and not set(SCOPES).issubset(token_scopes):
        _alert_reauth_required(
            conn,
            alert_manager,
            logger,
            "oauth_scope_insufficient",
            "Stored token scopes are missing required Gmail scopes",
        )
        raise OAuthError("Stored OAuth token scopes are insufficient; re-authorize via admin UI")

    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        previous_refresh = token_dict.get("refresh_token")
        previous_refresh_updated_at = token_dict.get("refresh_token_updated_at")
        try:
            creds.refresh(Request())
        except Exception as exc:
            _alert_reauth_required(
                conn,
                alert_manager,
                logger,
                _refresh_error_alert_kind(exc),
                f"OAuth refresh failed: {exc}",
            )
            raise
        now_iso = _now_iso()
        refresh_updated_at = previous_refresh_updated_at
        if creds.refresh_token and creds.refresh_token != previous_refresh:
            refresh_updated_at = now_iso
        save_tokens(
            conn,
            master_key,
            {
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": creds.scopes,
                "expiry": creds.expiry.isoformat() if creds.expiry else None,
                "last_access_token_refresh_at": now_iso,
                "refresh_token_updated_at": refresh_updated_at,
            },
        )
        return creds

    raise OAuthError("Gmail OAuth token invalid and not refreshable")


def get_authorization_url(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> Tuple[str, str]:
    flow = Flow.from_client_config(
        _client_config(client_id, client_secret, redirect_uri),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return auth_url, state


def exchange_code_for_tokens(
    conn,
    master_key: bytes,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
) -> dict:
    flow = Flow.from_client_config(
        _client_config(client_id, client_secret, redirect_uri),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        state=None,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    now_iso = _now_iso()
    token_dict = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
        "last_access_token_refresh_at": now_iso,
        "refresh_token_updated_at": now_iso if creds.refresh_token else None,
    }
    save_tokens(conn, master_key, token_dict)
    return token_dict
