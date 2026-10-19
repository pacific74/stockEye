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


def test_first_day_only_and_grid():
    import numpy as np
    from stockeye.analysis import rec_eval as re_
    from stockeye.analysis.hitrate import simulate
    o = np.array([105.0, 99.0, 100.0]); h = np.array([106.0, 100.0, 112.0])
    lo = np.array([104.0, 98.0, 99.0]); c = np.array([105.0, 99.0, 111.0])
    r = simulate(o, h, lo, c, [(100.0, 100.0)], (110.0, 120.0, 130.0), 95.0, first_day_only=True)
    assert r["outcome"] is None                                    # 다음 날(1일째) 1차 구간까지 안 내려옴 → 미체결
    r2 = simulate(o, h, lo, c, [(100.0, 100.0)], (110.0, 120.0, 130.0), 95.0)
    assert r2["outcome"] == "t1"                                   # 예전 규칙은 2일째 체결
    # 1일째 체결 → 1차 → 매수가 복귀 = 매수가매도
    o = np.array([100.0, 108.0, 104.0]); h = np.array([101.0, 111.0, 105.0])
    lo = np.array([99.0, 107.0, 99.0]); c = np.array([100.0, 109.0, 100.0])
    r = simulate(o, h, lo, c, [(100.0, 100.0)], (110.0, 120.0, 130.0), 95.0, first_day_only=True)
    assert r["outcome"] == "t1" and r["even"] == 3 and r["exit_day"] == 3 and re_.category("t1", r) == "even"
    rows = [{"rec_date": "2026-10-15", "kind": "v3", "score": 91, "res_status": "매수가매도", "res_done": True,
             "res_pnl": 4.0, "res_days": 3},
            {"rec_date": "2026-10-15", "kind": "v3", "score": 95, "res_status": "미체결", "res_done": True},
            {"rec_date": "2026-10-15", "kind": "daytrade", "score": 82, "res_status": "1차 목표 · 보유중", "res_done": False,
             "res_pnl": 1.0, "res_days": 2},
            {"rec_date": "2026-10-15", "kind": "v3", "score": 55, "res_status": "손절", "res_done": True, "res_pnl": -3}]
    g = re_.grid(rows)["2026-10-15"]
    assert g["90|v3"]["d"] == {"n": 2, "f": 1, "p": 4.0, "even": [1, 3]}
    assert "d" not in g["80|daytrade"] and g["80|daytrade"]["h"]["t1"] == [1, 2]
    assert not any(k.startswith("50") for k in g)


def test_track_result():
    from stockeye.analysis.rec_eval import track_result
    t = {"done": True, "bought": True, "hits": {"t1": "09:40", "t2": "10:00"}, "events": [{"state": "매수가매도"}],
         "result": "이익실현", "pnl": 1.2, "date": "2026-10-14", "exit_time": "2026-10-14 10:16"}
    assert track_result(t)["status"] == "매수가매도" and track_result(t)["days"] == 1
    t = {**t, "events": [], "hits": {"t1": "a", "t2": "b", "t3": "c"}}
    assert track_result(t)["status"] == "3차 목표"
    t = {"done": True, "bought": True, "hits": {}, "events": [], "result": "이익실현", "pnl": 2, "date": "2026-10-13",
         "exit_time": "2026-10-14 09:30", "kind": "x"}
    assert track_result({**t, "result": "손절"})["days"] == 2
    assert track_result({"done": True, "bought": False, "result": "미체결"})["status"] == "미체결"


def test_grid_time():
    from stockeye.analysis import rec_eval as re_
    assert re_.time_bucket("09:07") == "09:00" and re_.time_bucket("09:59") == "09:50"
    assert re_.time_bucket("10:02") == "10:00" and re_.time_bucket("08:59") is None and re_.time_bucket(None) is None
    rows = [{"rec_date": "2026-10-15", "kind": "daytrade", "score": 85, "rec_time": "09:23", "res_status": "1차 목표",
             "res_done": True, "res_pnl": 1.5, "res_days": 1},
            {"rec_date": "2026-10-15", "kind": "v3", "score": 85, "rec_time": "마감", "res_status": "손절", "res_done": True}]
    g = re_.grid_time(rows)
    assert g == {"2026-10-15": {"09:20|80": {"d": {"n": 1, "f": 1, "p": 1.5, "t1": [1, 1]}}}}


def test_grid_time_index():
    from stockeye.analysis import rec_eval as re_
    from stockeye.analysis.index_snap import since, weighted, members
    assert since(1.0, 2.0) == round((1.02 / 1.01 - 1) * 100, 2) and since(None, 1) is None
    assert weighted({"a": 1.0, "b": 3.0}, {"a": 1, "b": 3}, ["a", "b", "c"]) == 2.5
    assert members("x", {"x": "S", "a": "S", "b": "S", "c": "T"}, {"a": 5, "b": 1}) == ["a", "b"]
    rows = [{"rec_date": "2026-10-16", "kind": "daytrade", "code": "A", "score": 91, "rec_time": "09:12",
             "res_status": "1차 목표", "res_done": True, "res_pnl": 1.0, "res_days": 1},
            {"rec_date": "2026-10-16", "kind": "daytrade", "code": "B", "score": 92, "rec_time": "09:15",
             "res_status": "손절", "res_done": True, "res_pnl": -1.5, "res_days": 1}]
    ix = {"2026-10-16": {"A": {"buy": [0.5, -0.2, "09:12", "KOSPI"], "t1": [0.8, 0.3, "09:30", "KOSPI"]},
                         "B": {"buy": [-0.3, None, "09:15", "KOSDAQ"], "stop": [-0.9, None, "09:40", "KOSDAQ"]}}}
    m = re_.grid_time(rows, ix=ix)["2026-10-16"]["09:10|90"]["d"]
    assert m["ib"] == [2, 1, 1, 0]
    assert m["t1"][:2] == [1, 1] and m["t1"][3] == 1 and m["t1"][5] == 1
    assert m["stop"][3] == 1 and m["stop"][5] == 0 and m["stop"][2] < 0


def test_grid_nx():
    from stockeye.analysis import rec_eval as re_
    assert re_.nx_of({"nxt_after": {"chg": 1.2}, "nxt_pre": [100, -0.5]}) == {"a": 1.2, "p": -0.5}
    assert re_.nx_of({}) is None
    rows = [{"rec_date": "2026-10-15", "kind": "closingbet", "code": "A", "score": 88, "res_pnl": 1.0, "res_done": True},
            {"rec_date": "2026-10-15", "kind": "closingbet", "code": "B", "score": 91, "res_pnl": None, "res_done": True},
            {"rec_date": "2026-10-15", "kind": "closingbet", "code": "C", "score": 85, "res_pnl": -1.0, "res_done": True}]
    nx = {"2026-10-15": {"A": {"a": 1.2, "p": -0.5}, "B": {"a": 2, "p": 2}, "C": {"a": -0.3, "p": None}}}
    assert re_.grid_nx(rows, nx) == {"2026-10-15": {"80": {"d": [2, 1, 1, 0]}}}



def test_detail_list_and_all_ix():
    from stockeye.analysis import rec_eval as re_
    rows = [{"rec_date": "2026-10-16", "kind": "daytrade", "code": "A", "name": "에이", "score": 91, "rec_time": "09:12",
             "res_status": "1차 목표 · 보유중", "res_done": False, "res_pnl": 1.0, "res_days": 1},
            {"rec_date": "2026-10-16", "kind": "closingbet", "code": "B", "name": "비", "score": 82, "rec_time": "14:55",
             "res_status": "손절", "res_done": True, "res_pnl": -1.5, "res_days": 2},
            {"rec_date": "2026-10-16", "kind": "v3", "code": "C", "name": "씨", "score": 55, "res_status": "손절"},          # 60점 미만 → 제외
            {"rec_date": "2026-10-16", "kind": "v3", "code": "D", "name": "디", "score": 85, "res_status": "계획 없음"},     # 결과 없음 → 제외
            {"rec_date": "2025-01-02", "kind": "v3", "code": "E", "name": "이", "score": 85, "res_status": "손절"}]           # 150일 지남 → 제외
    ix = {"daytrade": {"2026-10-16": {"A": {"buy": [0.5, None, "09:12", "KOSPI"]}}}}
    d = re_.detail(rows, ix, "2026-10-17")
    assert [(x["c"], x["st"], x["cat"], x["tb"], x["b"]) for x in d] == [("A", "1차 목표", "t1", "09:10", 90), ("B", "손절", "stop", None, 80)]
    assert d[0]["ix"]["buy"][0] == 0.5 and "ix" not in d[1] and d[0]["dn"] is False and d[1]["dy"] == 2

    class Sb:
        def __init__(self): self.files = {}
        def download(self, f):
            if f.startswith("track/"):
                if f.endswith("2026-10-16.json"):
                    return json.dumps({"tracks": {"B": {"ix": {"buy": [1.0, 2.0, "14:55", "KOSDAQ"]}}, "Z": {}}}).encode()
                raise FileNotFoundError(f)
            return self.files.get(f)
        def upload(self, f, b, ct): self.files[f] = b
    sb = Sb()
    out = re_.all_ix(sb, "2026-10-17")
    assert out["closingbet"]["2026-10-16"] == {"B": {"buy": [1.0, 2.0, "14:55", "KOSDAQ"]}}
    assert set(sb.files) == {"stats/dt_ix.json", "stats/cb_ix.json", "stats/lc_ix.json"}
