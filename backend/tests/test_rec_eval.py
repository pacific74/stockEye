"""추천주 검증: 관심 탭 20거래일 결과 · 장중 탭 결과 가져오기 · 통계"""
import json

import numpy as np
import pandas as pd

from stockeye.analysis import rec_eval as re_


def _row(**kw):
    r = {"rec_date": "2026-10-01", "kind": "v3", "code": "000010", "score": 82, "entry": 10000, "stop": 9500,
         "target1": 10500, "target2": 11000, "target3": 11500, "zone1_high": 10100, "zone1_w": 100,
         "zone2_high": None, "zone2_w": None, "zone3_high": None, "zone3_w": None}
    return r | kw


def _bars(closes, start="2026-10-02"):
    d = pd.bdate_range(start, periods=len(closes))
    c = np.array(closes, float)
    return pd.DataFrame({"date": d, "code": "000010", "open": c, "high": c * 1.01, "low": c * 0.99, "close": c})


def test_grade_daily_target_and_open():
    up = _bars([10000, 10200, 10450, 10700, 11200, 11700])               # 1·2·3차 목표 차례로 → 끝
    r = re_.grade_daily(_row(), up)
    assert r["res_status"] == "3차 목표" and r["res_done"] and r["res_pnl"] > 0 and r["res_d_t1"] == 3
    flat = _bars([10000, 10050, 10020])                                   # 3일만 지남 → 보유중
    r = re_.grade_daily(_row(), flat)
    assert not r["res_done"] and r["res_status"] == "보유중" and r["res_days"] == 3
    hi = _bars([10500] * 20)                                              # 매수구간까지 안 내려옴 · 20일
    r = re_.grade_daily(_row(), hi)
    assert r["res_status"] == "미체결" and r["res_done"] and r["res_pnl"] is None
    down = _bars([10000, 9400])
    r = re_.grade_daily(_row(), down)
    assert r["res_status"] == "손절" and r["res_done"] and r["res_pnl"] < 0
    assert re_.grade_daily(_row(), _bars([10000], start="2026-09-30")) is None   # 다음 날 봉 아직 없음


def test_grade_intraday():
    res = {("2026-10-01", "000010"): {"outcome": "t1", "pnl": 1.2}}
    r = re_.grade_intraday(_row(kind="daytrade"), res, "2026-10-01")
    assert r["res_status"] == "1차 목표" and r["res_done"] and r["res_pnl"] == 1.2
    assert re_.grade_intraday(_row(kind="closingbet", code="9"), res, "2026-10-02") is None
    assert re_.grade_intraday(_row(kind="closingbet", code="9"), res, "2026-10-20")["res_status"] == "결과 없음"


def test_grade_open_and_summary():
    store = {"daytrade/results.json": json.dumps([{"date": "2026-10-01", "code": "000020", "outcome": "stop",
                                                    "pnl": -1.5}]).encode()}
    rows = [_row(), _row(kind="daytrade", code="000020"), _row(kind="nextday")]

    class SB:
        def __init__(self): self.up = []
        def select(self, t, q):
            return rows if q.get("offset") == "0" else []
        def download(self, k): return store.get(k)
        def upsert(self, t, r, key, **kw): self.up += r

    sb = SB()
    oh = _bars([10000, 10200, 10450, 10700, 11200, 11700])
    assert re_.grade_open(sb, oh, "2026-10-12") == 3
    by = {(u["kind"], u["code"]): u for u in sb.up}
    assert by[("daytrade", "000020")]["res_status"] == "손절" and by[("v3", "000010")]["res_done"]
    merged = [r | by[(r["kind"], r["code"])] for r in rows]
    s = re_.summarize(merged)
    assert s["total"]["n"] == 3 and s["total"]["done"] == 3 and s["total"]["win"] == round(2 / 3 * 100, 1)
    assert s["by_overlap"]["여러 구분 겹침"]["n"] == 2 and s["by_overlap"]["한 구분만"]["n"] == 1
    assert set(s["by_kind"]) == {"v3", "nextday", "daytrade"} and "2026-10-01" in s["by_day"]
