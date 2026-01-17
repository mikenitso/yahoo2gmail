from typing import Optional


def _get_cached_label_id(conn, account_id: int, label_name: str) -> Optional[str]:
    row = conn.execute(
        """
        SELECT label_id FROM gmail_labels
         WHERE account_id = ? AND label_name = ?
        """,
        (account_id, label_name),
    ).fetchone()
    return row[0] if row else None


def _cache_label_id(conn, account_id: int, label_name: str, label_id: str) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO gmail_labels(account_id, label_name, label_id)
            VALUES (?, ?, ?)
            ON CONFLICT(account_id, label_name) DO UPDATE SET
              label_id=excluded.label_id
            """,
            (account_id, label_name, label_id),
        )


def ensure_label(service, conn, account_id: int, label_name: str) -> str:
    cached = _get_cached_label_id(conn, account_id, label_name)
    if cached:
        return cached

    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for label in labels:
        if label.get("name") == label_name:
            _cache_label_id(conn, account_id, label_name, label.get("id"))
            return label.get("id")

    created = (
        service.users()
        .labels()
        .create(
            userId="me",
            body={"name": label_name, "labelListVisibility": "labelShow"},
        )
        .execute()
    )
    label_id = created.get("id")
    _cache_label_id(conn, account_id, label_name, label_id)
    return label_id


def get_system_label_ids(service, names: list[str]) -> dict:
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    by_name = {label.get("name"): label.get("id") for label in labels}
    missing = [name for name in names if name not in by_name]
    if missing:
        raise ValueError(f"Missing Gmail system labels: {', '.join(missing)}")
    return {name: by_name[name] for name in names}
