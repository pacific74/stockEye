import pytest
from fastapi.testclient import TestClient

from stockeye.config import load_config, data_dir


def _cfg():
    return load_config()


@pytest.mark.skipif(not (data_dir(load_config()) / "ohlcv.parquet").exists(),
                    reason="데이터 없음 (python -m scripts.collect --synthetic 먼저 실행)")
def test_api_flow(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    from api import main
    monkeypatch.setattr(main, "_journal", lambda: main.Journal(tmp_path / "j.db"))
    c = TestClient(main.app)
    d = c.get("/api/dashboard").json()
    assert d["market"]["mood"] and len(d["top10"]) <= 10 and set(d["strategies"]) == set("ABCDE")
    code = d["top10"][0]["code"]
    s = c.get(f"/api/stocks/{code}").json()
    assert s["candidate"]["plan"]["stop"] < s["candidate"]["plan"]["price"] and s["chart"]
    assert c.get(f"/api/stocks/{code}/explain").json()["text"]
    sim = c.get(f"/api/stocks/{code}/similar").json()
    assert sim["matches"] and "disclaimer" in sim
    for lst in ("overall", "A", "B"):
        assert c.get(f"/api/candidates?list={lst}").status_code == 200
    assert c.get("/api/sectors").status_code == 200
    other = c.get("/api/search?q=합성기업00").json()[0]["code"]
    assert c.get(f"/api/stocks/{other}").json()["candidate"]["code"] == other
    h = c.post("/api/portfolio", json={"code": code, "qty": 10, "avg_price": 10000, "buy_date": "2026-09-01 09:43"}).json()
    assert h["mode"] == "manual" and h["score"] is not None and h["entry_time"] == "2026-09-01 09:43:00"
    rv = c.get("/api/portfolio/review").json()
    assert rv[0]["code"] == code and "status" in rv[0]
    closed = c.post(f"/api/journal/{h['id']}/close", json={"price": 10800, "exit_time": "2026-09-05 10:00"}).json()
    assert closed["ret_pct"] == 8.0 and closed["result"] == "성공" and closed["hold_days"] == 3
    an = c.get("/api/journal/analysis").json()
    assert an["closed"] == 1
    assert c.get("/api/journal/analysis/ai").json()["summary"]["text"]
    h2 = c.post("/api/portfolio", json={"code": code, "qty": 1, "avg_price": 10000}).json()
    assert c.delete(f"/api/portfolio/{h2['id']}").json()["deleted"]
    # 승인 대기 주문 → 승인 (내부 모의 브로커)
    j = main._journal()
    rep = c.get("/api/dashboard").json()
    cand = rep["top10"][0]
    oid = j.add_order("paper", "buy", cand["code"], 3, price=cand["plan"]["price"], name=cand["name"],
                      snapshot=cand, expires_min=10)
    assert c.get("/api/orders").json()[0]["id"] == oid
    semi = main.deep_merge(_cfg(), {"trading": {"mode": "semi_auto", "broker": "paper"}})
    monkeypatch.setattr(main, "load_config", lambda: semi)
    r = c.post(f"/api/orders/{oid}/approve").json()
    assert "ok" in r
    if r["ok"]:
        assert main._journal().positions(status="open", mode="paper")
    assert c.get("/api/trading/status").json()["mode"] in ("alert", "paper", "semi_auto")
    bt = c.post("/api/backtest", json={"strategy": "D", "start": "2025-06-01", "run_audit": False}).json()
    assert bt["metrics"]["trades"] >= 0
    st = c.get("/api/strategies").json()
    assert next(x for x in st if x["key"] == "D")["backtest"] is not None
