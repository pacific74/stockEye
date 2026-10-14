"""NXT(넥스트레이드) 프리·애프터마켓 기록"""
import json

import pandas as pd

from stockeye.analysis import nxt_ctx
from stockeye.data.sources.naver_live import parse_item
from stockeye.trading import intraday_track as it
from tests.test_intraday_track import SB, SIG


def test_parse_over_market():
    m = {"itemCode": "005930", "closePrice": "70,000", "compareToPreviousPrice": {"code": "3"}, "fluctuationsRatio": "0",
         "overMarketPriceInfo": {"overPrice": "72,100", "overMarketStatus": "OPEN", "tradingSessionType": "PRE_MARKET"}}
    r = parse_item(m)
    assert r["over_price"] == 72100 and r["over_session"] == "PRE_MARKET"
    pre = nxt_ctx.pre_snapshot(pd.DataFrame([r]))
    assert pre == {"005930": [72100.0, 3.0]}


def test_fix_records_pre_and_cb_rows():
    sb = SB()
    tr = it.Tracker(sb, "daytrade", "2026-10-14", user_id=None)
    tr.nxt_pre = {"000010": [10300.0, 3.0]}
    tr.add([SIG], pd.Timestamp("2026-10-14 09:10"))
    assert tr.tracks["000010"]["nxt_pre"] == [10300.0, 3.0]
    # 종가배팅: 어제 산 것 + 애프터·프리 → 오늘 행
    t = {"code": "000030", "name": "다라", "date": "2026-10-13", "time": "15:00", "bought": True, "buy_time": "15:05",
         "entry": 10000, "done": True, "result": "손절", "pnl": -3.1, "nxt_after": {"chg": -2.0, "time": "19:05"},
         "nxt_pre": [9700.0, -2.5]}
    sb.store["track/closingbet/2026-10-13.json"] = json.dumps({"tracks": {"000030": t}}).encode()
    status = {}
    sb.select = lambda tb, p: []
    sb.upsert = lambda tb, rows, key, **k: status.update({rows[0]["key"]: rows[0]["payload"]})
    out = nxt_ctx.publish_cb(sb, "2026-10-14")
    p = status["closingbet_nxt"]
    assert out["rows"] == 1 and p["rows"][0]["after"] == -2.0 and p["rows"][0]["pre"] == -2.5
    g = p["stats"]["groups"][0]["rows"]
    assert g[0]["label"] == "−1% 아래" and g[0]["n"] == 1 and g[0]["win"] == 0.0


def test_record_after():
    sb = SB()
    t = {"code": "000030", "name": "다라", "date": "2026-10-14", "time": "15:00", "bought": True, "entry": 10000,
         "done": False}
    sb.store["track/closingbet/2026-10-14.json"] = json.dumps({"tracks": {"000030": t}}).encode()
    n = nxt_ctx.record_after(sb, "2026-10-14", lambda codes: pd.DataFrame(
        [{"code": "000030", "close": 10000.0, "over_price": 10150.0, "over_status": "OPEN"}]))
    saved = json.loads(sb.store["track/closingbet/2026-10-14.json"])["tracks"]["000030"]
    assert n == 1 and saved["nxt_after"]["chg"] == 1.5
