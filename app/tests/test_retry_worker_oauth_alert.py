from app.sync.retry_worker import _should_alert_oauth_invalid


def test_should_alert_oauth_invalid_from_invalid_grant_text():
    exc = Exception(
        "RefreshError('invalid_grant: Token has been expired or revoked.', {'error': 'invalid_grant'})"
    )
    assert _should_alert_oauth_invalid(exc) is True


def test_should_not_alert_oauth_invalid_for_generic_error():
    exc = Exception("TimeoutError('The read operation timed out')")
    assert _should_alert_oauth_invalid(exc) is False
