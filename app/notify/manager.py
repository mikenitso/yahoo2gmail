from app.notify import alerts, pushover


class AlertManager:
    def __init__(self, enabled: bool, api_token: str | None, user_key: str | None, cooldown_minutes: int):
        self.enabled = enabled and bool(api_token) and bool(user_key)
        self.api_token = api_token
        self.user_key = user_key
        self.cooldown_minutes = cooldown_minutes

    def send(self, conn, kind: str, title: str, message: str, logger=None) -> None:
        if not self.enabled:
            return
        last = alerts.get_last_success_alert_time(conn, kind)
        if last and alerts.within_cooldown(last, self.cooldown_minutes):
            return
        self._send_now(conn, kind, title, message, logger=logger, apply_cooldown=False)

    def send_test(self, conn, title: str, message: str, logger=None) -> None:
        if not self.enabled:
            return
        self._send_now(conn, "pushover_test", title, message, logger=logger, apply_cooldown=False)

    def _send_now(self, conn, kind: str, title: str, message: str, logger=None, apply_cooldown: bool = False) -> None:
        if apply_cooldown:
            last = alerts.get_last_success_alert_time(conn, kind)
            if last and alerts.within_cooldown(last, self.cooldown_minutes):
                return
        try:
            pushover.send_pushover(self.api_token, self.user_key, title, message)
            alerts.log_alert(conn, kind, title, message, success=True)
            if logger:
                logger.info(
                    "pushover alert sent",
                    extra={"event": "pushover_alert", "extra_fields": {"kind": kind}},
                )
        except Exception as exc:
            alerts.log_alert(conn, kind, title, f"send_failed: {exc}", success=False)
            if logger:
                logger.info(
                    "pushover alert failed",
                    extra={"event": "pushover_alert_failed", "extra_fields": {"kind": kind, "error": str(exc)}},
                )
