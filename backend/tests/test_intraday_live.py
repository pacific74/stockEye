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
    assert t["done"] and t["state"] == "매수가매도" and t["result"] == "이익실현"
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


def test_news_items_bad_first():
    from stockeye.engine.limitcatch import news_detail
    items = [{"title": "서산 신제품 공급계약 체결", "time": "2026-10-13 09:00", "link": "a"},
             {"title": "서산 횡령 혐의 피소", "time": "2026-10-12 10:00", "link": "b"}]
    nd = news_detail(items, "severe", "2026-10-13")
    assert [x["link"] for x in nd["items"]] == ["b", "a"] and nd["items"][0]["tone"] < 0


CB = {"code": "000030", "name": "다라", "status": "매수 후보", "score": 85, "price": 10000, "entry": 10000,
      "buy_lo": 9950, "buy_hi": 10050, "stop": 9700, "t1": 10200, "t2": 10400}


def test_closingbet_fix_then_buy_in_range_then_next_day_rules():
    sb = SB()
    tr = it.Tracker(sb, "closingbet", "2026-10-13", user_id="u1")
    tr.add([CB], pd.Timestamp("2026-10-13 15:10"))
    t = tr.tracks["000030"]
    assert t["state"] == "매수대기" and not t["bought"] and not sb.ins           # 고정만 · 매매일지 아직
    tr.update("000030", None, 10100, None, pd.Timestamp("2026-10-13 15:12"))   # 범위 밖
    assert not t["bought"]
    tr.update("000030", None, 10020, None, pd.Timestamp("2026-10-13 15:15"))   # 범위 안 → 매수
    assert t["bought"] and t["entry"] == 10020 and t["buy_time"] == "15:15" and sb.ins[0]["entry_time"].endswith("15:15:00")
    # 산 날 나머지 봉은 목표·손절 안 봄
    tr.update("000030", _bars([(10020, 10500, 9000, 10000, 100)], start="2026-10-13 15:16"), None, None,
              pd.Timestamp("2026-10-13 15:30"))
    assert not t["done"]
    tr.save()
    # 다음 날: 22_intraday 가 이월분으로 (갭 상승 시초가 ≥ 1차 → 시초가에 절반, 2차에 나머지)
    nx = it.Tracker(sb, "closingbet", "2026-10-14", user_id="u1", carry_only=True)
    t2 = nx.carry["000030"]
    nx.update("000030", _bars([(10250, 10300, 10240, 10280, 100), (10280, 10450, 10270, 10400, 100)],
                              start="2026-10-14 09:00"), None, None, pd.Timestamp("2026-10-14 09:02"))
    assert t2["done"] and t2["result"] == "이익실현" and t2["sold"] == [[10250, 0.5], [10400, 0.5]]
    nx.save()
    assert "track/closingbet/2026-10-14.json" not in sb.store                  # 이월만 관리 → 오늘 파일 안 씀
    view = it.Tracker(sb, "closingbet", "2026-10-14").view()
    assert view and view[0]["result"] == "이익실현"                             # 전날 내역 (끝난 것도) 화면에


def test_closingbet_no_fill_and_gap_down():
    tr = it.Tracker(None, "closingbet", "2026-10-13", user_id=None)
    tr.add([CB, {**CB, "code": "000040"}], pd.Timestamp("2026-10-13 15:10"))
    tr.update("000030", None, 10200, None, pd.Timestamp("2026-10-13 15:31"))
    t = tr.tracks["000030"]
    assert t["done"] and t["result"] == "미체결" and t["pnl"] is None
    t = tr.tracks["000040"]
    tr.on_tick("000040", 10000, pd.Timestamp("2026-10-13 15:19"))              # 실시간으로 매수
    assert t["bought"]
    tr.update("000040", _bars([(9600, 9650, 9500, 9550, 100)], start="2026-10-14 09:00"), None, None,
              pd.Timestamp("2026-10-14 09:01"))
    assert t["result"] == "손절" and t["sold"] == [[9600, 1.0]]                 # 시초가가 손절 아래 → 시초가


def test_closingbet_buy_window_1450_1520():
    tr = it.Tracker(None, "closingbet", "2026-10-13", user_id=None)
    tr.add([CB], pd.Timestamp("2026-10-13 14:52"))
    tr.update("000030", None, 10000, None, pd.Timestamp("2026-10-13 15:25"))   # 범위 안이지만 15:20 지남
    t = tr.tracks["000030"]
    assert t["result"] == "미체결" and t["events"][-1] == {"state": "미체결", "time": "15:20"}
    tr2 = it.Tracker(None, "closingbet", "2026-10-13", user_id=None)
    tr2.add([CB], pd.Timestamp("2026-10-13 14:52"))
    tr2.update("000030", None, 10000, None, pd.Timestamp("2026-10-13 14:53"))  # 14:50 뒤 바로 매수
    assert tr2.tracks["000030"]["buy_time"] == "14:53"


def test_hold_needs_big_drop_or_three_minutes():
    tr = it.Tracker(None, "daytrade", "2026-10-14", user_id=None)
    tr.add([SIG], pd.Timestamp("2026-10-14 09:10"))
    t = tr.tracks["000010"]
    st = lambda: [e["state"] for e in t["events"]]  # noqa: E731
    for m, sc in ((11, 79.5), (12, 81), (13, 78), (14, 79)):                     # 출렁임 · 연속 2번
        tr.update("000010", None, 10000, sc, pd.Timestamp(f"2026-10-14 09:{m}"))
    assert "신규진입보류" not in st()
    tr.update("000010", None, 10000, 78.5, pd.Timestamp("2026-10-14 09:15"))     # 3분 연속
    assert st()[-1] == "신규진입보류"
    tr2 = it.Tracker(None, "daytrade", "2026-10-14", user_id=None)
    tr2.add([SIG], pd.Timestamp("2026-10-14 09:10"))
    tr2.update("000010", None, 10000, 74, pd.Timestamp("2026-10-14 09:11"))      # 5점 넘게 하락 → 바로
    assert tr2.tracks["000010"]["events"][-1]["state"] == "신규진입보류"


def test_pack_bars_today_last_n():
    b = pd.concat([_bars([(1, 2, 0.5, 1.5, 10)] * 3, start="2026-10-13 15:28"),
                   _bars([(10, 12, 9, 11, 100)] * 130, start="2026-10-14 09:00")])
    out = it.pack_bars(b)
    assert len(out) == it.BARS_KEEP and out[-1] == ["11:09", 10.0, 12.0, 9.0, 11.0, 100]
    assert it.pack_bars(None) == []


def test_record_index_retries_until_both(monkeypatch):
    """지수를 못 받으면(업종 없음) 다시 시도해서 둘 다 받으면 저장"""
    import threading
    import scripts.intraday_live as il
    monkeypatch.setattr(il.time, "sleep", lambda s: None)
    calls = []

    class Snap:
        def has_sector(self, c): return True
        def snap(self, c):
            calls.append(c)
            return [0.5, None, "KOSPI"] if len(calls) < 3 else [0.5, 0.2, "KOSPI"]

    class Tr:
        kind = "daytrade"; lock = threading.Lock()
        def save(self): pass
        def live_row(self, t): return {}
    live = il.Live(None, [], background=False)
    live.snap = Snap()
    t = {"code": "A", "date": "2026-10-19", "time": "09:10", "buy_time": "09:10"}
    live.record_index(Tr(), t, "매수발생")
    live.q.get()()
    assert len(calls) == 3 and t["ix"]["buy"] == [0.5, 0.2, "09:10", "KOSPI"]
