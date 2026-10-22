from stockeye.data import collector


def test_retry_recovers(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("x")
        return "ok"
    assert collector._retry(fn, "t") == "ok" and len(calls) == 3


def test_retry_gives_up(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)

    def fn():
        raise ConnectionError("x")
    assert collector._retry(fn, "t") is None
