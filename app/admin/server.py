import html
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

from app.gmail.oauth import exchange_code_for_tokens, get_authorization_url, load_tokens
from app.log.logger import get_recent_log_lines, log_event


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    value = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _token_status(conn, master_key: bytes) -> dict:
    tokens = load_tokens(conn, master_key)
    if not tokens:
        return {"status": "missing", "expiry": None, "refresh_token": False}
    expiry_raw = tokens.get("expiry")
    expiry = _parse_iso(expiry_raw)
    refresh_token = bool(tokens.get("refresh_token"))
    if not expiry:
        return {"status": "unknown", "expiry": expiry_raw, "refresh_token": refresh_token}
    now = datetime.now(timezone.utc)
    status = "expired" if expiry <= now else "valid"
    return {"status": status, "expiry": expiry_raw, "refresh_token": refresh_token}


def _fetch_status(conn, master_key: bytes) -> dict:
    token = _token_status(conn, master_key)
    last_insert = conn.execute(
        """
        SELECT mailbox_name, uidvalidity, uid, gmail_message_id, updated_at
          FROM messages
         WHERE state = 'INSERTED'
         ORDER BY updated_at DESC
         LIMIT 1
        """
    ).fetchone()
    last_delete = conn.execute(
        """
        SELECT mailbox_name, uidvalidity, uid, yahoo_deleted_at
          FROM messages
         WHERE yahoo_deleted_at IS NOT NULL
         ORDER BY yahoo_deleted_at DESC
         LIMIT 1
        """
    ).fetchone()
    last_error = conn.execute(
        """
        SELECT mailbox_name, uidvalidity, uid, last_error, updated_at
          FROM messages
         WHERE last_error IS NOT NULL
         ORDER BY updated_at DESC
         LIMIT 1
        """
    ).fetchone()
    last_delete_error = conn.execute(
        """
        SELECT mailbox_name, uidvalidity, uid, yahoo_delete_last_error, updated_at
          FROM messages
         WHERE yahoo_delete_last_error IS NOT NULL
         ORDER BY updated_at DESC
         LIMIT 1
        """
    ).fetchone()
    return {
        "token": token,
        "last_insert": last_insert,
        "last_delete": last_delete,
        "last_error": last_error,
        "last_delete_error": last_delete_error,
    }


def _row_to_text(row) -> str:
    if not row:
        return "none"
    return " | ".join(str(value) for value in row)


def _render_page(status: dict, logs: list[str], auth_url: Optional[str], message: Optional[str]) -> bytes:
    logs_text = "\n".join(logs)
    html_body = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>y2g admin</title>
    <style>
      body {{ font-family: Arial, sans-serif; margin: 24px; }}
      pre {{ background: #f4f4f4; padding: 12px; }}
      .section {{ margin-bottom: 24px; }}
      .label {{ font-weight: bold; }}
      input[type=text] {{ width: 100%; padding: 6px; }}
      button {{ padding: 6px 10px; }}
    </style>
  </head>
  <body>
    <h1>Yahoo → Gmail Forwarder</h1>
    {f"<p><strong>{html.escape(message)}</strong></p>" if message else ""}
    <div class="section">
      <h2>Status</h2>
      <div><span class="label">Token:</span> {html.escape(status["token"]["status"])}</div>
      <div><span class="label">Token expiry:</span> {html.escape(str(status["token"]["expiry"]))}</div>
      <div><span class="label">Refresh token present:</span> {status["token"]["refresh_token"]}</div>
      <div><span class="label">Last insert:</span> {html.escape(_row_to_text(status["last_insert"]))}</div>
      <div><span class="label">Last Yahoo delete:</span> {html.escape(_row_to_text(status["last_delete"]))}</div>
      <div><span class="label">Last error:</span> {html.escape(_row_to_text(status["last_error"]))}</div>
      <div><span class="label">Last Yahoo delete error:</span> {html.escape(_row_to_text(status["last_delete_error"]))}</div>
    </div>
    <div class="section">
      <h2>OAuth</h2>
      <form method="post" action="/oauth_url">
        <button type="submit">Generate auth URL</button>
      </form>
      {f"<p><strong>Auth URL:</strong> {html.escape(auth_url)}</p>" if auth_url else ""}
      <form method="post" action="/oauth_exchange">
        <p>Paste full redirect URL:</p>
        <input type="text" name="redirect_url" />
        <button type="submit">Exchange & store tokens</button>
      </form>
    </div>
    <div class="section">
      <h2>Recent logs (last 20)</h2>
      <pre>{html.escape(logs_text)}</pre>
    </div>
  </body>
</html>
"""
    return html_body.encode("utf-8")


def start_admin_server(
    host: str,
    port: int,
    conn_factory: Callable[[], object],
    master_key: bytes,
    logger,
    oauth_client_id: str,
    oauth_client_secret: str,
    oauth_redirect_uri: str,
) -> None:
    auth_url_cache = {"url": None}
    status_message = {"msg": None}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, content: bytes, status_code: int = 200) -> None:
            self.send_response(status_code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def _render(self) -> None:
            conn = conn_factory()
            try:
                status = _fetch_status(conn, master_key)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
            logs = get_recent_log_lines(20)
            content = _render_page(status, logs, auth_url_cache["url"], status_message["msg"])
            status_message["msg"] = None
            self._send(content)

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/":
                self.send_response(404)
                self.end_headers()
                return
            self._render()

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            data = parse_qs(raw)
            if self.path == "/oauth_url":
                auth_url, _ = get_authorization_url(
                    oauth_client_id,
                    oauth_client_secret,
                    oauth_redirect_uri,
                )
                auth_url_cache["url"] = auth_url
                status_message["msg"] = "Generated new auth URL."
                if logger:
                    log_event(logger, "oauth_url", "gmail oauth url", auth_url=auth_url)
                self._render()
                return
            if self.path == "/oauth_exchange":
                redirect_url = data.get("redirect_url", [""])[0].strip()
                code = redirect_url
                if "://" in redirect_url:
                    parsed = urlparse(redirect_url)
                    query = parse_qs(parsed.query)
                    if "code" in query and query["code"]:
                        code = query["code"][0]
                if not code:
                    status_message["msg"] = "Missing code in redirect URL."
                    self._render()
                    return
                conn = conn_factory()
                try:
                    exchange_code_for_tokens(
                        conn,
                        master_key,
                        oauth_client_id,
                        oauth_client_secret,
                        oauth_redirect_uri,
                        code,
                    )
                    status_message["msg"] = "OAuth tokens updated."
                    if logger:
                        log_event(logger, "oauth_saved", "gmail oauth tokens saved")
                except Exception as exc:
                    status_message["msg"] = f"OAuth exchange failed: {exc}"
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
                self._render()
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, format, *args):  # noqa: A002
            return

    server = ThreadingHTTPServer((host, port), Handler)

    def _serve():
        server.serve_forever()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
