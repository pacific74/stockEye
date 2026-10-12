"""당일단타: 돌파·눌림목 신호, 필수 제외, 상태, 청산 시뮬레이션"""
import pandas as pd

from stockeye.engine import daytrade as dt


def _bars(rows, start="2026-10-12 09:00"):
    t = pd.date_range(start, periods=len(rows), freq="1min")
    return pd.DataFrame([{"time": t[i], "open": o, "high": h, "low": l, "close": c, "volume": v}
                         for i, (o, h, l, c, v) in enumerate(rows)])


def _ctx(b, **kw):
    return {"prev_close": 9800, "spread": 0.0008, "idx_chg": 0.5, "now": b["time"].iloc[-1], "value": 50e8, **kw}


def test_breakout_signal():
    rows = [(10000, 10040, 9990, 10030, 1000)] * 3 + [(10030, 10050, 10000, 10020, 800)] * 12
    rows += [(10020, 10045, 10010, 10040, 900)] * 3                       # 저항 10050 아래에서 다지기
    rows += [(10040, 10110, 10040, 10100, 3000)]                           # 10100 마감 · 거래량 3배 → 돌파
    b = _bars(rows)
    r = dt.evaluate(b, _ctx(b))
    assert r["type"] == "돌파" and r["signal"] and not r["excluded"]
    assert r["stop"] < 10050 and r["t1"] > r["entry"] > r["stop"] and r["t2"] > r["t1"]
    assert r["parts"]["pat25"] >= 20 and r["score"] >= 70


def test_pullback_signal():
    rows = [(10000, 10010, 9990, 10000, 1000)] * 3
    rows += [(10000 + 60 * i, 10070 + 60 * i, 9995 + 60 * i, 10060 + 60 * i, 3000) for i in range(6)]   # 상승 +3.6%
    rows += [(10350 - 30 * i, 10360 - 30 * i, 10300 - 30 * i, 10320 - 30 * i, 1200) for i in range(5)]  # 조정 (거래 감소)
    rows += [(10200, 10240, 10190, 10230, 1300), (10230, 10260, 10215, 10250, 1400),
             (10250, 10300, 10240, 10295, 2000)]                                                       # 저점 높이며 재상승
    b = _bars(rows)
    r = dt.evaluate(b, _ctx(b))
    assert r["type"] == "눌림목" and r["signal"], r


def test_exclusions_and_status():
    rows = [(10000, 10040, 9990, 10030, 1000)] * 20
    b = _bars(rows)
    r = dt.evaluate(b, _ctx(b, value=5e8, spread=0.005, news_level="severe"))
    assert r["status"] == "진입 금지" and len(r["excluded"]) == 3
    early = _bars(rows[:4])
    r2 = dt.evaluate(early, _ctx(early))
    assert any("5분" in w for w in r2["warnings"]) and r2["status"] != "진입 조건 충족"


def test_simulate_exit():
    after = _bars([(10100, 10180, 10090, 10170, 1), (10170, 10260, 10150, 10250, 1)], start="2026-10-12 09:20")
    r = dt.simulate_exit(after, 10100, 10030, 10180, 10250)
    assert r["outcome"] == "t2" and abs(r["pnl"] - ((0.5 * 10180 + 0.5 * 10250) / 10100 - 1 - dt.COST) * 100) < 1e-3
    after2 = _bars([(10100, 10120, 10020, 10050, 1)], start="2026-10-12 09:20")
    assert dt.simulate_exit(after2, 10100, 10030, 10180, 10250)["outcome"] == "stop"


def test_runner_step(monkeypatch):
    import scripts.daytrade as sd
    from stockeye.data.sources import naver_live
    rows = [(10000, 10040, 9990, 10030, 1000)] * 3 + [(10030, 10050, 10000, 10020, 800)] * 12
    rows += [(10020, 10045, 10010, 10040, 900)] * 3 + [(10040, 10110, 10040, 10100, 3000)]
    b = _bars(rows)
    b["value"] = 50e8

    flat = _bars([(5000, 5005, 4995, 5000, 100)] * 19)
    flat["value"] = 1e8

    class K:
        def minute_bars_day(self, code, s, e):
            return (b if code == "000010" else flat).copy()

        def minute_bars(self, code, e):
            return (b if code == "000010" else flat).tail(3).copy()

        def asking(self, code):
            return {"spread": 0.0008}

    snap = pd.DataFrame([{"code": "000010", "close": 10100, "chg_pct": 3.0, "value": 50e8, "status": "OPEN"},
                         {"code": "000020", "close": 5000, "chg_pct": 0.0, "value": 1e8, "status": "OPEN"}])
    monkeypatch.setattr(naver_live, "stocks", lambda codes: snap)
    monkeypatch.setattr(naver_live, "indices", lambda: pd.DataFrame([{"code": "KOSPI", "chg_pct": 0.5}]))
    monkeypatch.setattr(sd, "_now", lambda: pd.Timestamp("2026-10-12 09:19:30"))
    lst = pd.DataFrame({"code": ["000010", "000020"], "name": ["가", "나"], "market": ["KOSPI", "KOSDAQ"]})
    run = sd.Runner(None, K(), lst, top=10)
    p = run.step()
    assert p["items"][0]["code"] == "000010" and p["items"][0]["type"] == "돌파" and p["scanned"] == 1  # 거래대금 10억 미만은 분봉도 안 받음
    assert p["counts"]["진입 조건 충족"] + p["counts"]["진입 대기"] + p["counts"]["관찰"] >= 1


def test_eval_grade_replay_and_accumulate():
    import json
    from stockeye.analysis import daytrade_eval as de
    rows = [(10000, 10040, 9990, 10030, 1000)] * 3 + [(10030, 10050, 10000, 10020, 800)] * 12
    rows += [(10020, 10045, 10010, 10040, 900)] * 3 + [(10040, 10110, 10040, 10100, 3000)]
    rows += [(10100, 10650, 10090, 10600, 2000)] * 5                       # 진입 뒤 상승 → 2차 익절
    b = _bars(rows)
    b["value"] = 50e8
    s = de.replay_day(b, 9800)
    assert s and s["type"] == "돌파" and s["time"] == "09:18"
    s.update({"date": "2026-10-12", "code": "000010", "name": "가"})
    g = de.grade(s, b)
    assert g["outcome"] in ("t1", "t2") and g["pnl"] > 0

    class SB:
        def __init__(self):
            self.files = {"daytrade/signals/2026-10-12.json": json.dumps([s]).encode()}
            self.pub = None

        def download(self, k):
            return self.files.get(k)

        def upload(self, k, data, ct):
            self.files[k] = data

        def select(self, *a, **k):
            return []

        def upsert(self, table, rows, on):
            self.pub = rows

    class K:
        def minute_bars_day(self, code, s_, e):
            return b

    sb = SB()
    assert de.evaluate_day(sb, K(), "2026-10-12") == 1 and de.evaluate_day(sb, K(), "2026-10-12") == 0   # 두 번째는 중복 없음
    hist = json.loads(sb.files["daytrade/results.json"])
    assert len(hist) == 1 and de.report(hist)["by_type"]["돌파"]["n"] == 1


def test_min_target_and_adr_exclusion():
    """DT-0.2: 손절이 가까워도 1차 목표는 +3%↑ · 2차 +5%↑ · 평소 하루 변동폭 5% 미만이면 제외"""
    p = dt.plan(10000, 9950)
    assert p["t1"] >= 10300 and p["t2"] >= 10500 and p["t1_pct"] >= 3.0
    d = pd.DataFrame({"date": pd.date_range("2026-09-01", periods=21, freq="B"),
                      "high": [102.0] * 21, "low": [99.0] * 21, "close": [100.0] * 21})
    assert abs(dt.adr(d) - 0.03) < 1e-9
