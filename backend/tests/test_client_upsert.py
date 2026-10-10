"""큰 업로드: 크기 제한으로 나누고, 5xx(Cloudflare 525 등)면 반으로 나눠 재시도"""
from stockeye.cloud import client as C


class R:
    def __init__(self, code, text=""):
        self.status_code, self.text = code, text


def _sb(fail_over: int):
    sb = C.Supabase.__new__(C.Supabase)
    sb.url, sent = "http://x", []

    class S:
        def request(self, method, url, data=None, **kw):
            n = data.count(b'"code"')
            if n > fail_over:
                return R(525, "<!DOCTYPE html><html><head><title>SSL handshake failed</title></head></html>")
            sent.append(n)
            return R(201)
    sb.s = S()
    return sb, sent


def test_split_on_5xx(monkeypatch):
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    sb, sent = _sb(fail_over=20)
    rows = [{"code": f"{i:06d}", "x": "a" * 10} for i in range(100)]
    assert sb.upsert("t", rows, "code", chunk=60) == 100
    assert sum(sent) == 100 and max(sent) <= 20


def test_split_by_bytes(monkeypatch):
    sb, sent = _sb(fail_over=10_000)
    rows = [{"code": f"{i:06d}", "x": "a" * 1000} for i in range(50)]
    sb.upsert("t", rows, "code", chunk=50, max_bytes=10_000)
    assert sum(sent) == 50 and max(sent) <= 10


def test_cloudflare_error_is_short(monkeypatch):
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    sb, _ = _sb(fail_over=0)
    try:
        sb.upsert("t", [{"code": "1"}], "code")
    except C.SupabaseError as e:
        assert "SSL handshake failed" in str(e) and "DOCTYPE" not in str(e)
