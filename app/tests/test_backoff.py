from app.sync.retry_worker import BACKOFF_SCHEDULE_SECONDS


def test_backoff_schedule_length():
    assert BACKOFF_SCHEDULE_SECONDS == [60, 120, 240, 480, 900, 1800, 3600]
