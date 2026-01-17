import imaplib
import re
import ssl
from typing import List, Optional, Tuple


class YahooIMAPError(Exception):
    pass


YAHOO_APP_PASSWORD_SECRET_KEY = "yahoo_app_password"


class YahooIMAPClient:
    def __init__(self, host: str, port: int, email: str, app_password: str, timeout: int = 30):
        self.host = host
        self.port = port
        self.email = email
        self.app_password = app_password
        self.timeout = timeout
        self._imap: Optional[imaplib.IMAP4_SSL] = None

    def connect(self) -> None:
        context = ssl.create_default_context()
        self._imap = imaplib.IMAP4_SSL(self.host, self.port, ssl_context=context, timeout=self.timeout)
        status, _ = self._imap.login(self.email, self.app_password)
        if status != "OK":
            raise YahooIMAPError("IMAP login failed")

    def close(self) -> None:
        if self._imap is None:
            return
        try:
            self._imap.logout()
        finally:
            self._imap = None

    @property
    def imap(self) -> imaplib.IMAP4_SSL:
        if not self._imap:
            raise YahooIMAPError("IMAP connection not initialized")
        return self._imap

    def has_idle(self) -> bool:
        capabilities = getattr(self.imap, "capabilities", ())
        return b"IDLE" in capabilities or "IDLE" in capabilities

    def list_mailboxes(self) -> List[str]:
        status, data = self.imap.list()
        if status != "OK":
            raise YahooIMAPError("LIST failed")
        mailboxes = []
        for line in data:
            if not line:
                continue
            decoded = line.decode("utf-8", errors="ignore")
            match = re.findall(r"\"([^\"]*)\"", decoded)
            if match:
                mailboxes.append(match[-1])
            else:
                mailbox = decoded.split(" ")[-1].strip().strip('"')
                if mailbox:
                    mailboxes.append(mailbox)
        return mailboxes

    def select(self, mailbox: str, readonly: bool = True) -> Tuple[int, int]:
        status, data = self.imap.select(f'"{mailbox}"', readonly=readonly)
        if status != "OK":
            raise YahooIMAPError(f"SELECT failed for {mailbox}")
        uidvalidity = self._extract_uidvalidity_from_select(data)
        if uidvalidity is None:
            uidvalidity = self._get_uidvalidity(mailbox)
        exists = int(data[0]) if data and data[0] else 0
        return uidvalidity, exists

    def _extract_uidvalidity_from_select(self, data) -> Optional[int]:
        if not data:
            return None
        for item in data:
            if not item:
                continue
            if isinstance(item, bytes):
                text = item.decode("utf-8", errors="ignore")
            else:
                text = str(item)
            match = re.search(r"UIDVALIDITY[^0-9]*(\d+)", text, flags=re.IGNORECASE)
            if match:
                return int(match.group(1))
            upper = text.upper()
            idx = upper.find("UIDVALIDITY")
            if idx != -1:
                tail = text[idx:]
                digits = ""
                for ch in tail:
                    if ch.isdigit():
                        digits += ch
                    elif digits:
                        break
                if digits:
                    return int(digits)
        return None

    def _get_uidvalidity(self, mailbox: str) -> int:
        status, data = self.imap.status(f'"{mailbox}"', "(UIDVALIDITY)")
        if status != "OK":
            raise YahooIMAPError("STATUS UIDVALIDITY failed")
        raw = data[0].decode("utf-8", errors="ignore") if data else ""
        match = re.search(r"UIDVALIDITY[^0-9]*(\d+)", raw, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        upper = raw.upper()
        idx = upper.find("UIDVALIDITY")
        if idx == -1:
            raise YahooIMAPError(f"UIDVALIDITY not found in STATUS: {raw}")
        tail = raw[idx:]
        digits = ""
        for ch in tail:
            if ch.isdigit():
                digits += ch
            elif digits:
                break
        if digits:
            return int(digits)
        raise YahooIMAPError(f"UIDVALIDITY not found in STATUS: {raw}")

    def search_uids(self, since_uid: int) -> List[int]:
        query = f"UID {since_uid}:*"
        status, data = self.imap.uid("SEARCH", None, query)
        if status != "OK":
            raise YahooIMAPError("UID SEARCH failed")
        if not data or not data[0]:
            return []
        return [int(uid) for uid in data[0].split()]

    def noop(self) -> None:
        self.imap.noop()

    def fetch_rfc822(self, uid: int) -> Tuple[bytes, List[str], Optional[str]]:
        status, data = self.imap.uid("FETCH", str(uid), "(RFC822 FLAGS INTERNALDATE)")
        if status != "OK" or not data:
            raise YahooIMAPError("FETCH failed")
        rfc822 = b""
        flags: List[str] = []
        internaldate = None
        for item in data:
            if not item or not isinstance(item, tuple):
                continue
            meta, body = item
            if body:
                rfc822 = body
            if meta:
                parsed_flags = imaplib.ParseFlags(meta)
                if parsed_flags:
                    flags = [f.decode("utf-8", errors="ignore") for f in parsed_flags]
                meta_str = meta.decode("utf-8", errors="ignore")
                match = re.search(r"INTERNALDATE\\s+\"([^\"]+)\"", meta_str)
                if match:
                    internaldate = match.group(1)
        if not rfc822:
            raise YahooIMAPError("RFC822 body missing")
        return rfc822, flags, internaldate

    def delete_uid(self, mailbox: str, uidvalidity: int, uid: int) -> None:
        current_uidvalidity, _ = self.select(mailbox, readonly=False)
        if current_uidvalidity != uidvalidity:
            raise YahooIMAPError("UIDVALIDITY changed; refusing to delete")
        status, _ = self.imap.uid("STORE", str(uid), "+FLAGS.SILENT", r"(\Deleted)")
        if status != "OK":
            raise YahooIMAPError("UID STORE \\Deleted failed")
        status, _ = self.imap.expunge()
        if status != "OK":
            raise YahooIMAPError("EXPUNGE failed")

    def idle_wait(self, timeout_seconds: int = 60) -> Optional[bytes]:
        if not self.has_idle():
            return None
        # imaplib has no public IDLE API; fall back to polling if this fails.
        try:
            tag = self.imap._new_tag()  # type: ignore[attr-defined]
            self.imap.send(f"{tag} IDLE\r\n".encode("utf-8"))
            _ = self.imap._get_line()  # type: ignore[attr-defined]
            old_timeout = self.imap.sock.gettimeout()
            self.imap.sock.settimeout(timeout_seconds)
            try:
                line = self.imap.readline()  # type: ignore[attr-defined]
            except Exception:
                line = None
            finally:
                try:
                    self.imap.sock.settimeout(old_timeout)
                except Exception:
                    pass
                try:
                    self.imap.send(b"DONE\r\n")
                    self.imap._get_tagged_response(tag)  # type: ignore[attr-defined]
                except Exception:
                    pass
            return line
        except Exception:
            return None


def load_or_store_app_password(conn, master_key: bytes, env_password: Optional[str]) -> str:
    from app.store import secrets

    stored = secrets.get_secret(conn, YAHOO_APP_PASSWORD_SECRET_KEY, master_key)
    if stored:
        return stored.decode("utf-8")
    if not env_password:
        raise YahooIMAPError("YAHOO_APP_PASSWORD not provided and no stored secret found")
    secrets.set_secret(conn, YAHOO_APP_PASSWORD_SECRET_KEY, env_password.encode("utf-8"), master_key)
    return env_password
