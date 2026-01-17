import json
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


def build_credentials(
    conn,
    master_key: bytes,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    alert_manager=None,
    logger=None,
) -> Credentials:
    token_dict = load_tokens(conn, master_key)
    if not token_dict:
        raise OAuthError("Gmail OAuth tokens not found; run OAuth flow")

    creds = Credentials.from_authorized_user_info(token_dict, SCOPES)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:
            if alert_manager:
                alert_manager.send(
                    conn,
                    "oauth_invalid",
                    "Gmail OAuth refresh failed",
                    f"Refresh token failed: {exc}. Re-authorize via admin UI.",
                    logger=logger,
                )
            raise
        save_tokens(conn, master_key, {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
            "expiry": creds.expiry.isoformat() if creds.expiry else None,
        })
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
    token_dict = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }
    save_tokens(conn, master_key, token_dict)
    return token_dict
