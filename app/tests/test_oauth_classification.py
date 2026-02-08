from app.sync.retry_worker import _oauth_alert_payload


def test_invalid_grant_maps_to_refreshable_oauth_alert():
    kind, _ = _oauth_alert_payload(Exception("invalid_grant: Token has been expired or revoked"))
    assert kind == "oauth_invalid_grant"


def test_invalid_client_maps_to_client_mismatch():
    kind, _ = _oauth_alert_payload(Exception("invalid_client: Unauthorized"))
    assert kind == "oauth_client_mismatch"


def test_scope_insufficient_maps_to_scope_alert():
    kind, _ = _oauth_alert_payload(Exception("ACCESS_TOKEN_SCOPE_INSUFFICIENT"))
    assert kind == "oauth_scope_insufficient"
