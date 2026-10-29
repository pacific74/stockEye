"""당일매매 추적: 고정 계획 · 상태 시각 · 결과(이익실현/매수가매도/손절) · 매매일지 기록"""
import json

import numpy as np
import pandas as pd

from stockeye.trading import intraday_track as it


def _bars(rows, start="2026-10-13 09:10"):
    t = pd.date_range(start, periods=len(rows), freq="1min")
    return pd.DataFrame([{"time": t[i], "open": o, "high": h, "low": l, "close": c, "volume": v}
                         for i, (o, h, l, c, v) in enumerate(rows)])


class SB:
    def __init__(self):
        self.store, self.ins, self.upd = {}, [], []
    def download(self, k): return self.store.get(k)
    def upload(self, k, b, ct): self.store[k] = b
    def insert(self, t, row, returning=True):
        self.ins.append(row); return [{"id": f"p{len(self.ins)}"}]
    def update(self, t, f, patch, returning=False): self.upd.append((f, patch)); return []


SIG = {"code": "000010", "name": "가나", "status": "진입 조건 충족", "score": 85, "price": 10000, "entry": 10000,
       "stop": 9850, "t1": 10300, "t2": 10500, "type": "A", "reasons": ["돌파"]}


def test_profit_targets_and_journal():
    sb = SB()
    tr = it.Tracker(sb, "daytrade", "2026-10-13", user_id="u1")
    now = pd.Timestamp("2026-10-13 09:10")
    assert tr.add([SIG, {**SIG, "code": "000020", "status": "진입 대기"}], now) == ["000010"]
    assert tr.add([SIG], now) == []                                    # 같은 종목은 한 번만
    t = tr.tracks["000010"]
    assert t["t3"] == 10700 and t["events"][0] == {"state": "매수구간", "time": "09:10"} and sb.ins[0]["mode"] == "signal"
    b = _bars([(10000, 10050, 9990, 10040, 1000), (10040, 10320, 10030, 10300, 1200), (10300, 10520, 10290, 10500, 1500),
               (10500, 10720, 10480, 10700, 1500)], start="2026-10-13 09:11")
    tr.update("000010", b, 10700, 86, pd.Timestamp("2026-10-13 09:15"))
    assert t["done"] and t["result"] == "이익실현" and t["hits"] == {"t1": "09:12", "t2": "09:13", "t3": "09:14"}
    exp = (0.5 * 10300 + 0.3 * 10500 + 0.2 * 10700) / 10000 * 100 - 100 - it.COST
    assert abs(t["pnl"] - round(exp, 3)) < 1e-6
    patch = sb.upd[-1][1]
    assert patch["exit_reason"] == "이익실현" and patch["status"] == "closed" and patch["result"] == "성공"
    view = json.loads(sb.store["track/daytrade/2026-10-13.json"] if "track/daytrade/2026-10-13.json" in sb.store else "{}")
    tr.save()
    assert "000010" in json.loads(sb.store["track/daytrade/2026-10-13.json"])["tracks"]


def test_stop_hold_and_sell_signal():
    tr = it.Tracker(None, "daytrade", "2026-10-13", user_id=None)
    tr.add([SIG], pd.Timestamp("2026-10-13 09:10"))
    t = tr.tracks["000010"]
    tr.update("000010", None, 10010, 70, pd.Timestamp("2026-10-13 09:15"))
    assert t["state"] == "신규진입보류" and not t["done"]
    b = _bars([(10000, 10010, 9840, 9845, 1000)], start="2026-10-13 09:16")
    tr.update("000010", b, 9845, 70, pd.Timestamp("2026-10-13 09:17"))
    assert t["result"] == "손절" and t["state"] == "손절" and t["pnl"] < 0
    tr2 = it.Tracker(None, "daytrade", "2026-10-13", user_id=None)
    tr2.add([SIG], pd.Timestamp("2026-10-13 09:00"))
    rows = [(10000, 10010, 9990, 10005, 100)] * 11 + [(10080, 10090, 9960, 9965, 900)]   # 거래량 9배 + 음봉
    tr2.update("000010", _bars(rows, start="2026-10-13 09:01"), 9965, 85, pd.Timestamp("2026-10-13 09:13"))
    t2 = tr2.tracks["000010"]
    assert t2["result"] == "매수가매도" and t2["state"] == "매도신호포착"


def test_close_out_and_limitcatch_overnight():
    tr = it.Tracker(None, "daytrade", "2026-10-13", user_id=None)
    tr.add([SIG], pd.Timestamp("2026-10-13 09:10"))
    tr.update("000010", None, 9950, 85, pd.Timestamp("2026-10-13 15:20"))
    assert tr.tracks["000010"]["result"] == "손절" and tr.tracks["000010"]["state"] == "마감 청산"
    sb = SB()
    lc = it.Tracker(sb, "limitcatch", "2026-10-13", user_id="u1")
    lc.add([{"code": "000030", "name": "다", "status": "매수 검토", "score": 80, "price": 13000, "entry": 13000,
             "stop": 12000}], pd.Timestamp("2026-10-13 10:00"))
    t = lc.tracks["000030"]
    assert (t["t1"], t["t2"], t["t3"]) == (13390, 13780, 14300) and t["stop"] == 12480     # 손절 = 매수가 −4%
    lc.update("000030", None, 13000, 80, pd.Timestamp("2026-10-13 15:20"))
    assert not t["done"]                                               # 상한가포착은 다음 날까지
    lc.save()
    nxt = it.Tracker(sb, "limitcatch", "2026-10-14", user_id="u1")      # 다음 날: 전날 종목 이어서
    assert nxt.codes() == ["000030"]
    b = _bars([(13800, 13900, 13700, 13850, 5000)] * 31, start="2026-10-14 09:00")
    nxt.update("000030", b, 13850, None, pd.Timestamp("2026-10-14 09:31"))
    c = nxt.carry["000030"]
    assert c["done"] and c["result"] == "이익실현" and c["hits"].get("t2") == "09:00"
    nxt.save()
    assert json.loads(sb.store["track/limitcatch/2026-10-13.json"])["tracks"]["000030"]["done"]


def _hold_setup():
    tr = it.Tracker(None, "daytrade", "2026-10-13", user_id=None)
    tr.add([SIG], pd.Timestamp("2026-10-13 09:10"))
    return tr, tr.tracks["000010"]


def _flat(n, px=10000, vol=1000, start="2026-10-13 09:11"):
    return _bars([(px, px + 5, px - 5, px, vol)] * n, start=start)


def _hold(t):
    return [e for e in t["events"] if e["state"] == "신규진입보류"]


def test_hold_when_price_leaves_zone_above():
    tr, t = _hold_setup()
    hi = t["buy_hi"]
    tr.update("000010", _flat(3), hi * 1.004, 90, pd.Timestamp("2026-10-13 09:14"))
    assert not _hold(t)                                                # 구간 위 1% 안쪽은 그대로
    tr.update("000010", _flat(3), hi * 1.012, 90, pd.Timestamp("2026-10-13 09:15"))
    assert len(_hold(t)) == 1 and "위로" in _hold(t)[0]["why"] and t["state"] == "신규진입보류"


def test_hold_below_zone_needs_two_minutes():
    tr, t = _hold_setup()
    lo = t["buy_lo"]
    tr.update("000010", _flat(3), lo * 0.999, 90, pd.Timestamp("2026-10-13 09:14"))
    assert not _hold(t)
    tr.update("000010", _flat(3), lo * 0.999, 90, pd.Timestamp("2026-10-13 09:15"))
    assert "아래로 2분" in _hold(t)[0]["why"]
    tr2, t2 = _hold_setup()                                            # 중간에 구간으로 돌아오면 다시 셈
    tr2.update("000010", _flat(3), lo * 0.999, 90, pd.Timestamp("2026-10-13 09:14"))
    tr2.update("000010", _flat(3), (lo + t2["buy_hi"]) / 2, 90, pd.Timestamp("2026-10-13 09:15"))
    tr2.update("000010", _flat(3), lo * 0.999, 90, pd.Timestamp("2026-10-13 09:16"))
    assert not _hold(t2)


def test_hold_on_sudden_drop_bar_and_volume_dry():
    tr, t = _hold_setup()
    b = _bars([(10000, 10005, 9995, 10000, 1000)] * 4 + [(10100, 10100, 9945, 9945, 3000)], start="2026-10-13 09:11")
    tr.update("000010", b, 10000, 90, pd.Timestamp("2026-10-13 09:16"))   # 1분봉 −1.5%↓ (손절가 9850 은 안 건드림), 가격(구간)은 그대로
    assert "급락" in _hold(t)[0]["why"]
    tr2, t2 = _hold_setup()
    rows = [(10000, 10005, 9995, 10000, 1000)] * 20 + [(10000, 10005, 9995, 10000, 300)] * 5
    tr2.update("000010", _bars(rows, start="2026-10-13 09:11"), 10000, 90, pd.Timestamp("2026-10-13 09:36"))
    assert "거래량 급감" in _hold(t2)[0]["why"]


def test_hold_vwap_two_minutes_and_not_after_target():
    tr, t = _hold_setup()
    up = [(10000, 10040, 9995, 10035, 5000)] * 3                         # VWAP 이 높게 형성
    dn = [(10030, 10032, 9990, 9995, 800), (9995, 9998, 9985, 9990, 800)]
    tr.update("000010", _bars(up + dn[:1], start="2026-10-13 09:11"), 10000, 90, pd.Timestamp("2026-10-13 09:15"))
    assert not _hold(t)
    tr.update("000010", _bars(up + dn, start="2026-10-13 09:11"), 10000, 90, pd.Timestamp("2026-10-13 09:16"))
    assert "VWAP 아래 2분" in _hold(t)[0]["why"]
    tr3, t3 = _hold_setup()                                              # 1차 목표를 먹은 뒤엔 구간 위여도 보류 안 띄움
    b = _bars([(10000, 10320, 9995, 10310, 2000)], start="2026-10-13 09:11")
    tr3.update("000010", b, 10310, 90, pd.Timestamp("2026-10-13 09:12"))
    assert t3["hits"] and not _hold(t3)


def test_limitcatch_unchanged_by_new_hold_rules():
    tr = it.Tracker(None, "limitcatch", "2026-10-13", user_id=None)
    tr.add([{**SIG, "status": "매수 검토"}], pd.Timestamp("2026-10-13 09:10"))
    t = tr.tracks["000010"]
    tr.update("000010", _flat(3), t["buy_hi"] * 1.05, 90, pd.Timestamp("2026-10-13 09:15"))
    assert not _hold(t)
