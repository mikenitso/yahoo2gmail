import json
import time
import urllib.parse
import urllib.request


class PushoverError(Exception):
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
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                if resp.status >= 400:
                    raise PushoverError(f"pushover http {resp.status}: {body}")
                parsed = json.loads(body) if body else {}
                if parsed.get("status") != 1:
                    raise PushoverError(f"pushover error: {body}")
                return
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                break
    raise PushoverError(str(last_exc)) from last_exc
