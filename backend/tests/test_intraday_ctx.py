"""당일매매 시장·업종 기록: 행 계산 · 누적(최근 40일) · 구간별 통계"""
import json

import numpy as np
import pandas as pd

from stockeye.analysis import intraday_ctx as ic


def _b(slope, day="2026-10-14"):
    t = pd.date_range(f"{day} 09:00", f"{day} 15:30", freq="1min")
    c = 10000 * (1 + slope * np.arange(len(t)))
    return pd.DataFrame({"time": t, "close": c})


LIST = pd.DataFrame({"code": ["A", "S1", "069500", "229200"], "name": ["에이", "s1", "k", "q"],
                     "market": ["KOSPI", "KOSPI", "KOSPI", "KOSPI"]})
SEC = pd.DataFrame({"code": ["A", "S1"], "sector": ["전기", "전기"], "marcap": [1e12, 2e12]})


class SB:
    def __init__(self):
        self.store, self.status = {}, {}
    def download(self, k): return self.store.get(k)
    def upload(self, k, b, ct): self.store[k] = b
    def select(self, t, p): return [{"payload": self.status.get("intraday_ctx")}] if "intraday_ctx" in self.status else []
    def upsert(self, t, rows, key, **kw):
        for r in rows:
            self.status[r["key"]] = r["payload"]
        return len(rows)


def test_rows_and_stats():
    tr = [{"code": "A", "name": "에이", "date": "2026-10-14", "time": "09:20", "done": True, "pnl": 1.0,
           "exit_time": "2026-10-14 10:00", "result": "이익실현"},
          {"code": "A", "name": "에이2", "date": "2026-10-14", "time": "09:45", "done": True, "pnl": -2.0,
           "exit_time": "2026-10-14 10:10", "result": "손절"},
          {"code": "A", "date": "2026-10-14", "time": "14:55", "done": True, "pnl": 1, "exit_time": "2026-10-15 09:30",
           "result": "이익실현"}]                                                     # 날 넘김 → 제외
    bars = {"A": _b(0.0001), "S1": _b(0.00005), "069500": _b(-0.00002)}
    rows = ic.ctx_rows(lambda c: bars.get(c, pd.DataFrame(columns=["time", "close"])), tr, LIST, SEC,
                       pd.Timestamp("2026-10-14 15:30"))
    assert len(rows) == 2 and rows[0]["bucket"] == "~09:30" and rows[1]["bucket"] == "09:30~10:00"
    assert rows[0]["mkt"] < 0 and rows[0]["sec"] > 0 and rows[0]["sector_n"] == 1 and rows[0]["stock"] == 1.25
    st = ic.stats(rows)
    assert st["all"] == {"n": 2, "win": 50.0, "pnl": -0.5, "sum": -1.0}
    hold = next(g for g in st["groups"] if g["title"] == "진입 시각")
    assert [x["n"] for x in hold["rows"]] == [1, 1, 0]


def test_run_accumulates(monkeypatch):
    sb = SB()
    track = {"code": "A", "name": "에이", "date": "2026-10-14", "time": "09:20", "done": True, "pnl": 1.0,
             "exit_time": "2026-10-14 10:00", "result": "이익실현"}
    sb.store["track/daytrade/2026-10-14.json"] = json.dumps({"tracks": {"A": track}}).encode()
    sb.status["intraday_ctx"] = {"rows": [{"date": "2026-10-13", "done": True, "result": "손절", "pnl": -1.5,
                                           "bucket": "10:00~"}, {"date": "2026-10-14", "old": True}]}

    class KIS:
        def minute_bars_day(self, code, a, b): return _b(0.0001 if code == "A" else 0.0)
    out = ic.run(sb, KIS(), LIST, SEC, "2026-10-14")
    p = sb.status["intraday_ctx"]
    assert out == {"today": 1, "rows": 2, "days": 2} and p["days"] == 2
    assert not any(r.get("old") for r in p["rows"]) and p["stats"]["all"]["n"] == 2
    assert "ctx/intraday/2026-10-14.json" in sb.store
