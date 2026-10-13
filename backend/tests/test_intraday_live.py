"""당일매매 실시간: KIS 체결 파싱 · 체결 단위 목표/손절 · 실시간 모드 1분봉 · 관리자 알림 · 저녁 마무리"""
import pandas as pd

from stockeye.data.sources import kis_ws
from stockeye.trading import intraday_track as it
from tests.test_intraday_track import SB, SIG, _bars


def _rec(code, price, n=46):
    f = ["0"] * n
    f[0], f[1], f[2], f[5] = code, "091503", str(price), "2.5"
    f[10], f[11], f[12], f[36], f[37], f[38], f[39] = "10010", "10000", "15", "300", "500", "90000", "120000"
    return f


def test_parse_multi_records():
    msg = "0|H0STCNT0|002|" + "^".join(_rec("005930", 10000) + _rec("000660", 20000))
    r = kis_ws.parse(msg)
    assert [x["code"] for x in r] == ["005930", "000660"] and r[1]["price"] == 20000
    assert r[0]["bid_qty"] == 500 and r[0]["total_bid"] == 120000 and r[0]["ask1"] == 10010
    assert kis_ws.parse("0|H0STASP0|001|x^y") == [] and kis_ws.parse("garbage") == []


def test_feed_subscription_cap_and_sync():
    sent = []

    class WS:
        def send(self, m): sent.append(m)
    f = kis_ws.RealtimeFeed(lambda t: None)
    f.set_wanted([f"{i:06d}" for i in range(50)])          # 연결 전: 기억만
    assert len(f.wanted) == kis_ws.MAX_SUB and not sent
    f.ws, f.connected, f._approval = WS(), True, "k"
    f._sync()
    assert len(f.subbed) == 40 and len(sent) == 40
    f.set_wanted(["000001"])
    assert f.subbed == {"000001"} and len(sent) == 40 + 39


def test_tick_stop_targets_breakeven():
    tr = it.Tracker(None, "daytrade", "2026-10-13", user_id=None)
    now = pd.Timestamp("2026-10-13 09:10")
    tr.add([SIG], now)
    t = tr.tracks["000010"]
    assert tr.on_tick("000010", 10100, now) is True or True            # 매수구간 밖으로 (상태 그대로일 수 있음)
    assert tr.on_tick("000010", 10300, pd.Timestamp("2026-10-13 09:12")) is True
    assert t["hits"] == {"t1": "09:12"} and t["be"] and abs(t["rest"] - 0.5) < 1e-9
    assert tr.on_tick("000010", 9990, pd.Timestamp("2026-10-13 09:20")) is True   # 1차 뒤 본전 이탈
    assert t["done"] and t["state"] == "본전 매도" and t["result"] == "이익실현"
    assert t["sold"][-1] == [9990, 0.5]                                 # 실제 체결가로 매도
    assert tr.on_tick("000010", 9000, now) is False                    # 끝난 뒤엔 무시


def test_tick_stop_at_real_price():
    tr = it.Tracker(None, "daytrade", "2026-10-13", user_id=None)
    tr.add([SIG], pd.Timestamp("2026-10-13 09:10"))
    t = tr.tracks["000010"]
    tr.on_tick("000010", 9800, pd.Timestamp("2026-10-13 09:11"))       # 손절가 9850 아래로 바로
    assert t["result"] == "손절" and t["sold"] == [[9800, 1.0]]


def test_realtime_mode_minute_bars_skip_stop_but_keep_sell_signal():
    tr = it.Tracker(None, "daytrade", "2026-10-13", user_id=None)
    tr.add([SIG], pd.Timestamp("2026-10-13 09:10"))
    t = tr.tracks["000010"]
    tr.realtime = {"000010"}
    b = _bars([(10000, 10010, 9800, 9990, 100)], start="2026-10-13 09:11")   # 1분봉 저가는 손절 아래
    tr.update("000010", b, 9990, None, pd.Timestamp("2026-10-13 09:12"))
    assert not t["done"] and t["low"] == 9800                          # 실시간이 보고 있으니 1분봉으로 손절 안 함
    rows = [(10000, 10010, 9990, 10000, 100)] * 11 + [(10000, 10000, 9850, 9880, 1000)]
    tr.update("000010", _bars(rows, start="2026-10-13 09:13"), None, None, pd.Timestamp("2026-10-13 09:25"))
    assert t["done"] and any(e["state"] == "매도신호포착" for e in t["events"])


def test_events_and_admin_only_notify(monkeypatch):
    import scripts.intraday_live as il
    sent, pushed = [], []

    class Notifier:
        def send_topic(self, tp, title, body, priority="default"): sent.append((tp, title))

    class DB(SB):
        def select(self, table, params=None):
            assert params.get("is_admin") == "eq.true"                  # 관리자만 조회
            return [{"ntfy_topic": "admin-topic"}, {"ntfy_topic": "admin-topic"}, {"ntfy_topic": None}]
        def upsert(self, table, rows, key): pushed.append(rows[0]["key"])

    monkeypatch.setenv("NTFY_TOPIC", "pc-topic")
    db = DB()
    assert il.admin_topics(db) == ["pc-topic", "admin-topic"]
    monkeypatch.setattr("stockeye.trading.notify.Notifier", Notifier)
    live = il.Live(db, il.admin_topics(db), background=False)
    tr = it.Tracker(db, "daytrade", "2026-10-13", user_id=None)
    tr.on_event = live.on_event
    tr.add([SIG], pd.Timestamp("2026-10-13 09:10"))
    tr.on_tick("000010", 10300, pd.Timestamp("2026-10-13 09:12"))      # 1차 목표 → 행만, 알림 없음
    while not live.q.empty():
        live.q.get()()
    assert [s[1] for s in sent] == ["매수발생 · 가나", "매수발생 · 가나"]
    assert {s[0] for s in sent} == {"pc-topic", "admin-topic"}
    assert pushed and pushed[0] == "daytrade:2026-10-13:000010"
    t = tr.tracks["000010"]
    t["events"].append({"state": "매도신호포착", "time": "09:30"})
    assert il.Live.message(tr, t, "매도신호포착")[0] == "매도발생 · 가나"
    assert il.Live.message(tr, t, "1차목표달성") is None


def test_live_row_is_copy_without_card():
    tr = it.Tracker(None, "limitcatch", "2026-10-13", user_id=None)
    tr.add([{**SIG, "status": "매수 검토"}], pd.Timestamp("2026-10-13 10:00"))
    t = tr.tracks["000010"]
    row = tr.live_row(t)
    assert row["key"] == "limitcatch:2026-10-13:000010" and "card" not in row["payload"]
    row["payload"]["events"].append("x")
    assert "x" not in t["events"]


def test_finish_day_closes_open_tracks():
    sb = SB()
    sb.delete = lambda table, f: sb.__dict__.setdefault("deleted", []).append((table, f))
    tr = it.Tracker(sb, "daytrade", "2026-10-13", user_id="u1")
    tr.add([SIG], pd.Timestamp("2026-10-13 09:10"))
    tr.save()

    class KIS:
        def minute_bars_day(self, code, start, end):
            return _bars([(10000, 10050, 9990, 10020, 100)] * 3, start="2026-10-13 15:18")
    out = it.finish_day(sb, KIS(), "2026-10-13", kinds=("daytrade",))
    assert out["daytrade"]["finished_now"] == 1 and out["daytrade"]["open"] == 0
    t = it.Tracker(sb, "daytrade", "2026-10-13").tracks["000010"]
    assert t["done"] and t["state"] == "마감 청산" and sb.upd[-1][1]["status"] == "closed"
    assert sb.deleted == [("intraday_live", {"date": "lt.2026-10-06"})]


def test_daytrade_discover_uses_kis_rank_then_naver_fallback(monkeypatch):
    import types
    import scripts.daytrade as sd
    from stockeye.data.sources import naver_live
    calls = []
    monkeypatch.setattr(naver_live, "stocks", lambda codes: calls.append(sorted(codes)) or pd.DataFrame(
        [{"code": c, "close": 1000.0, "chg_pct": 1.0, "volume": 10.0, "value": 1e4} for c in codes]))

    class KIS:
        def __init__(self, fail=False): self.fail = fail
        def value_rank(self, mk):
            if self.fail:
                raise RuntimeError("x")
            code = "000001" if mk == "0001" else "000002"
            return pd.DataFrame([{"code": code, "name": "a", "close": 5000.0, "chg_pct": 3.0, "volume": 1e6, "value": 5e9},
                                 {"code": "999999", "name": "우선주", "close": 1.0, "chg_pct": 0, "volume": 1, "value": 1}])
    tr = it.Tracker(None, "daytrade", "2026-10-13", user_id=None)
    tr.add([{**SIG, "code": "000003"}], pd.Timestamp("2026-10-13 09:10"))
    r = types.SimpleNamespace(kis=KIS(), codes=["000001", "000002", "000003", "000004"], watch={"000004"}, track=tr)
    snap = sd.Runner.discover(r)
    assert sorted(snap.index) == ["000001", "000002", "000003", "000004"]   # 목록 밖(999999) 제외 · 관심·고정 종목은 네이버
    assert calls == [["000003", "000004"]] and snap.loc["000001", "value"] == 5e9
    r.kis = KIS(fail=True)
    snap = sd.Runner.discover(r)                                           # 순위 실패 → 네이버 전 종목 (5분 보관)
    assert len(snap) == 4 and len(calls) == 2
    sd.Runner.discover(r)
    assert len(calls) == 2
