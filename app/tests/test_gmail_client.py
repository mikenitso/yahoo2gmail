from app.gmail.gmail_client import find_message_by_rfc822msgid


class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeMessagesAPI:
    def __init__(self):
        self.list_calls = []
        self.get_calls = []

    def list(self, userId, q, maxResults):
        self.list_calls.append({"userId": userId, "q": q, "maxResults": maxResults})
        return _FakeRequest({"messages": [{"id": "gmail-msg-1"}]})

    def get(self, userId, id, format):
        self.get_calls.append({"userId": userId, "id": id, "format": format})
        return _FakeRequest({"id": id, "threadId": "gmail-thread-1"})


class _FakeUsersAPI:
    def __init__(self):
        self._messages = _FakeMessagesAPI()

    def messages(self):
        return self._messages


class _FakeGmailService:
    def __init__(self):
        self._users = _FakeUsersAPI()

    def users(self):
        return self._users


def test_find_message_by_rfc822msgid_returns_message_and_thread_ids():
    service = _FakeGmailService()

    result = find_message_by_rfc822msgid(service, "me", "<abc@example.com>")

    assert result == ("gmail-msg-1", "gmail-thread-1")
