"""추천 기록: 행 만들기 · 매수가(1차 중앙값) · 손익비 · 하루 첫 기록만"""
from stockeye.cloud import recommend as rc


class SB:
    def __init__(self):
        self.calls = []

    def upsert(self, table, rows, key, **kw):
        self.calls.append((table, rows, key, kw))


def _cand():
    return {"code": "005930", "name": "삼성전자", "rank": 1, "score": 82.345, "market": "KOSPI", "sector": "전기전자",
            "plan": {"price": 10000, "entry_low": 9800, "entry_high": 10100, "target1": 11000, "target2": 12000,
                     "target3": 13000, "stop": 9300, "verdict": "매수 후보",
                     "zones": [{"name": "1차", "low": 9800, "high": 10100, "weight": 30},
                               {"name": "2차", "low": 9500, "high": 9700, "weight": 30},
                               {"name": "3차", "low": 9350, "high": 9450, "weight": 40}]}}


def test_from_candidate_zones_entry_rr():
    r = rc.from_candidate("nextday", "2026-10-12", _cand(), version="NX-1")
    assert set(r) == set(rc.COLS)
    assert r["entry"] == 9950 and r["zone3_low"] == 9350 and r["zone2_w"] == 30
    assert r["entry_avg"] == round((9950 * 30 + 9600 * 30 + 9400 * 40) / 100)
    assert r["rr1"] == round((11000 - 9950) / (9950 - 9300), 2) and r["target3"] == 13000 and r["rec_time"] == "마감"
    assert r["stop_pct"] < 0 and r["score"] in (82.34, 82.35)


def test_from_candidate_without_zones():
    c = _cand()
    c["plan"].pop("zones")
    r = rc.from_candidate("v3", "2026-10-12", c)
    assert r["zone1_low"] == 9800 and r["zone2_low"] is None and r["entry"] == 9950 and r["entry_avg"] == 9950


def test_record_daily_and_dedup():
    sb = SB()
    rep = {"date": "2026-10-12", "strategies": {"v3": {"candidates": [_cand(), _cand()]},
                                                "nextday": {"candidates": [_cand()]}, "other": {"candidates": [_cand()]}}}
    assert rc.record_daily(sb, rep) == 2                               # 같은 구분 안 중복 1건 · 모르는 구분 제외
    table, rows, key, kw = sb.calls[0]
    assert table == "recommendations" and key == "rec_date,kind,code" and kw == {"ignore_duplicates": True}
    assert {r["kind"] for r in rows} == {"v3", "nextday"}


def test_intraday_recorder_once():
    sb = SB()
    rec = rc.IntradayRecorder(sb, "closingbet", "pc")
    items = [{"code": "000010", "name": "가", "status": "매수 후보", "score": 85, "entry": 10000, "buy_lo": 9950,
              "buy_hi": 10050, "t1": 10300, "t2": 10500, "stop": 9800, "type": "돌파"},
             {"code": "000020", "name": "나", "status": "관찰", "score": 72, "entry": 5000}]
    assert rec("2026-10-12", items, "CB-0.1", "15:12") == 1
    assert rec("2026-10-12", items, "CB-0.1", "15:13") == 0             # 같은 종목은 다시 안 보냄
    r = sb.calls[0][1][0]
    assert r["rec_time"] == "15:12" and r["zone1_low"] == 9950 and r["rr1"] == 1.5 and r["source"] == "pc"
    lc = rc.IntradayRecorder(sb, "limitcatch", "github")
    assert lc("2026-10-12", [{"code": "1", "status": "매수 검토", "entry": 13000, "stop": 12000, "time": "10:01"}]) == 1
    assert sb.calls[-1][1][0]["stop_pct"] < 0 and sb.calls[-1][1][0]["rec_time"] == "10:01"


def test_same_stock_in_several_kinds_kept_separately():
    sb = SB()
    rep = {"date": "2026-10-12", "strategies": {k: {"candidates": [_cand()]} for k in rc.DAILY_KINDS}}
    assert rc.record_daily(sb, rep) == len(rc.DAILY_KINDS)            # 같은 종목이 5개 구분 모두 → 5줄
    rows = sb.calls[0][1]
    assert {r["kind"] for r in rows} == set(rc.DAILY_KINDS) and {r["code"] for r in rows} == {"005930"}
    rec = rc.IntradayRecorder(sb, "daytrade", "pc")                  # 같은 날 당일단타에도 나오면 또 한 줄
    assert rec("2026-10-12", [{"code": "005930", "status": "진입 조건 충족", "entry": 10000, "stop": 9850}]) == 1


def test_collect_past_day():
    import json as js
    from scripts.record_recommendations import collect

    class SB2:
        def select(self, table, q):
            if table == "candidates":
                return [{"list": "v3", "payload": _cand()}, {"list": "nextday", "payload": _cand()}]
            return [{"payload": {"date": "2026-10-12", "time": "15:20",
                                 "items": [{"code": "000010", "status": "매수 후보", "entry": 10000, "stop": 9800}]}}]

        def download(self, key):
            return {"daytrade/signals/2026-10-12.json": js.dumps([{"code": "000030", "time": "09:12", "entry": 5000,
                                                                    "stop": 4930, "t1": 5150}]).encode()}.get(key)
    rows = collect(SB2(), "2026-10-12")
    assert [r["kind"] for r in rows] == ["v3", "nextday", "daytrade", "closingbet"]
    assert rows[2]["status"] == "진입 조건 충족" and rows[3]["rec_time"] == "15:20"
