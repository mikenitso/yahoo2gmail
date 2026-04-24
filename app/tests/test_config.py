import pytest

from app.config.config import ConfigError, config_summary, load_config


@pytest.fixture(autouse=True)
def _required_env(monkeypatch):
    monkeypatch.setenv("YAHOO_EMAIL", "user@yahoo.com")
    monkeypatch.setenv("APP_MASTER_KEY", "base64-key")
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GMAIL_OAUTH_REDIRECT_URI", "http://localhost")


def test_load_config_defaults_replay_window_to_500():
    config = load_config()

    assert config.yahoo_replay_window_uids == 500


def test_load_config_rejects_negative_replay_window(monkeypatch):
    monkeypatch.setenv("YAHOO_REPLAY_WINDOW_UIDS", "-1")

    with pytest.raises(ConfigError):
        load_config()


def test_config_summary_includes_replay_window():
    config = load_config()

    summary = config_summary(config)

    assert summary["yahoo_replay_window_uids"] == 500
