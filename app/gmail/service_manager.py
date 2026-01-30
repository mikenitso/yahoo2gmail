from app.gmail.gmail_client import build_service
from app.gmail.oauth import OAuthError, TOKEN_SECRET_KEY, build_credentials
from app.log.logger import log_event
from app.store import secrets


class GmailServiceManager:
    def __init__(
        self,
        master_key: bytes,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        alert_manager=None,
        logger=None,
    ):
        self.master_key = master_key
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.alert_manager = alert_manager
        self.logger = logger
        self._service = None
        self._token_created_at = None

    def _token_timestamp(self, conn):
        return secrets.get_secret_created_at(conn, TOKEN_SECRET_KEY)

    def _build(self, conn):
        creds = build_credentials(
            conn,
            self.master_key,
            self.client_id,
            self.client_secret,
            self.redirect_uri,
            alert_manager=self.alert_manager,
            logger=self.logger,
        )
        return build_service(creds)

    def get_service(self, conn):
        token_created_at = self._token_timestamp(conn)
        if self._service is None:
            self._service = self._build(conn)
            self._token_created_at = token_created_at
            return self._service
        if token_created_at and token_created_at != self._token_created_at:
            try:
                self._service = self._build(conn)
                self._token_created_at = token_created_at
                if self.logger:
                    log_event(self.logger, "oauth_reloaded", "gmail oauth tokens reloaded")
            except OAuthError as exc:
                if self.logger:
                    log_event(
                        self.logger,
                        "oauth_reload_failed",
                        "gmail oauth reload failed; keeping existing service",
                        error=str(exc),
                    )
        return self._service
