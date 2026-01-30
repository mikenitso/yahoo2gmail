from datetime import datetime, timedelta, timezone


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def log_alert(conn, kind: str, title: str, message: str, success: bool = True) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO alerts(kind, title, message, success, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (kind, title, message, 1 if success else 0, _utc_now_iso()),
        )


def get_recent_alerts(conn, limit: int = 20):
    return conn.execute(
        """
        SELECT kind, title, message, created_at, success
          FROM alerts
         ORDER BY created_at DESC
         LIMIT ?
        """,
        (limit,),
    ).fetchall()


def get_last_success_alert_time(conn, kind: str):
    row = conn.execute(
        """
        SELECT created_at FROM alerts
         WHERE kind = ?
           AND success = 1
         ORDER BY created_at DESC
         LIMIT 1
        """,
        (kind,),
    ).fetchone()
    return row[0] if row else None


def within_cooldown(last_iso: str, cooldown_minutes: int) -> bool:
    if not last_iso:
        return False
    value = last_iso.replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - ts < timedelta(minutes=cooldown_minutes)
