from arxiv_tracker import client


class FakeResponse:
    def __init__(self, status_code, headers=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text


def test_http_429_respects_retry_after_header(monkeypatch):
    responses = iter(
        [
            FakeResponse(429, {"Retry-After": "60"}),
            FakeResponse(200, text="ok"),
        ]
    )
    sleeps = []

    monkeypatch.setattr(client, "MAX_ATTEMPTS", 2)
    monkeypatch.setattr(client, "BASE_PAUSE", 1.5)
    monkeypatch.setattr(client.random, "uniform", lambda _a, _b: 0)
    monkeypatch.setattr(client.time, "sleep", sleeps.append)
    monkeypatch.setattr(client._session, "get", lambda *args, **kwargs: next(responses))

    response = client._do_get("https://export.arxiv.org/api/query", {})

    assert response.status_code == 200
    assert sleeps == [60.0]
