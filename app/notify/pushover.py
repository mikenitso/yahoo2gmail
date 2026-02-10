import json
import socket
import time
import urllib.parse
import urllib.request


class PushoverError(Exception):
    pass


class PushoverDnsError(PushoverError):
    pass


def send_pushover(api_token: str, user_key: str, title: str, message: str) -> None:
    payload = {
        "token": api_token,
        "user": user_key,
        "title": title,
        "message": message,
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request("https://api.pushover.net/1/messages.json", data=data)
    last_exc: Exception | None = None
    retry_backoff_seconds = [2, 5]
    for attempt in range(3):
        try:
            socket.getaddrinfo("api.pushover.net", 443, type=socket.SOCK_STREAM)
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                if resp.status >= 400:
                    raise PushoverError(f"pushover http {resp.status}: {body}")
                parsed = json.loads(body) if body else {}
                if parsed.get("status") != 1:
                    raise PushoverError(f"pushover error: {body}")
                return
        except socket.gaierror as exc:
            last_exc = PushoverDnsError(f"pushover dns resolution failed: {exc}")
        except Exception as exc:
            last_exc = exc
        if attempt < len(retry_backoff_seconds):
            time.sleep(retry_backoff_seconds[attempt])
        else:
            break
    if isinstance(last_exc, PushoverDnsError):
        raise last_exc
    raise PushoverError(str(last_exc)) from last_exc
