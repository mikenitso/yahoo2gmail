import base64

from googleapiclient.discovery import build
try:
    from googleapiclient.errors import HttpError
except Exception:  # pragma: no cover
    HttpError = None


def build_service(credentials):
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def import_raw_message(
    service,
    user_id: str,
    raw_bytes: bytes,
    label_ids: list[str],
    thread_id: str | None = None,
    internal_date_source: str | None = "dateHeader",
):
    raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")
    body = {
        "raw": raw_b64,
        "labelIds": label_ids,
    }
    if thread_id:
        body["threadId"] = thread_id
    result = (
        service.users()
        .messages()
        .import_(userId=user_id, body=body, internalDateSource=internal_date_source)
        .execute()
    )
    return result.get("id"), result.get("threadId")


def find_thread_id_by_rfc822msgid(service, user_id: str, msgid: str) -> str | None:
    if not msgid:
        return None
    try:
        query = f"rfc822msgid:{msgid}"
        result = service.users().messages().list(userId=user_id, q=query, maxResults=1).execute()
        messages = result.get("messages", [])
        if not messages:
            return None
        msg_id = messages[0].get("id")
        if not msg_id:
            return None
        msg = service.users().messages().get(userId=user_id, id=msg_id, format="metadata").execute()
        return msg.get("threadId")
    except Exception as exc:
        if HttpError and isinstance(exc, HttpError):
            status = getattr(exc.resp, "status", None)
            if status == 403:
                return None
        raise
