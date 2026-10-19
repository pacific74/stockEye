"""상한가포착: 잠김·풀림 · 잔량 · 1·2단계 · 다음 날 청산 · 되돌려 보기 · 실전 기록"""
import json

import numpy as np
import pandas as pd

from stockeye.engine import limitcatch as lc
from stockeye.analysis import limitcatch_eval as le

PREV = 10000.0
LIM = 13000.0      # 10000 × 1.3


def _daily(n=60, c=PREV, spike=False):
    d = pd.bdate_range("2026-07-01", periods=n)
    close = c * (1 + 0.001 * np.arange(n)) / (1 + 0.001 * (n - 1))
    df = pd.DataFrame({"date": d, "open": close * 0.998, "high": close * 1.01, "low": close * 0.99, "close": close,
                       "volume": 1e6})
    if spike:                                                         # 어제 상한가
        df.loc[n - 1, "close"] = df.loc[n - 2, "close"] * 1.3
    return df


def _bars(closes, start="2026-10-12 09:00", highs=None, vol=20000.0):
    t = pd.date_range(start, periods=len(closes), freq="1min")
    c = np.array(closes, float)
    h = np.array(highs, float) if highs is not None else c
    return pd.DataFrame({"time": t, "open": c, "high": np.maximum(h, c), "low": c * 0.999, "close": c,
                         "volume": vol, "value": np.cumsum(c * vol) * 300})


def test_lock_profile_releases():
    closes = [12000] * 5 + [LIM] * 5 + [12900] * 2 + [LIM] * 10          # 도달 → 2분 풀림 → 다시 잠김
    lp = lc.lock_profile(_bars(closes), LIM)
    assert lp["reached"] and lp["reach_time"] == "09:05" and lp["releases"] == 1 and lp["release_min"] == 2
    assert lp["locked_now"] and lp["relocked"] and lp["last_release"] == 2
    lp2 = lc.lock_profile(_bars([12000] * 3 + [LIM] * 3 + [12500] * 4), LIM)
    assert lp2["releases"] == 1 and not lp2["locked_now"] and lp2["last_release"] == 4
    assert not lc.lock_profile(_bars([12000] * 5), LIM)["reached"]


def _today(bars, value=300e8):
    return {"open": float(bars["open"].iloc[0]), "high": float(bars["high"].max()), "low": float(bars["low"].min()),
            "close": float(bars["close"].iloc[-1]), "volume": float(bars["volume"].sum()), "value": value,
            "prev_close": PREV, "listed_shares": 20_000_000}


def test_locked_thick_book_is_buy_review():
    b = _bars([12000] * 10 + [LIM] * 20)
    book = {"bid1": LIM, "bid_qty": 900_000, "ask1": 0, "ask_qty": 0, "total_bid": 1_500_000, "total_ask": 0}
    hist = [{"bid_qty": 850_000, "locked": True}] * 5
    nd = {"level": "pos", "fresh": True, "official": True, "pos": ["OO 대규모 공급계약 체결"]}
    r = lc.evaluate(_daily(), _today(b), b, book, {"news": nd, "sector": {"up_ratio": 0.8, "chg_pct": 3.0},
                                                   "book_hist": hist, "now": pd.Timestamp("2026-10-12 10:00")})
    assert r["group"] == "도달" and r["lock"]["locked_now"] and r["stage1"] and r["stage2"], r
    assert r["status"] == "매수 검토" and r["entry"] == LIM and r["stop"] == 12000 and r["loss_pct"] < 0
    assert r["fill_warn"] and r["parts"]["time15"] == 7.5 and r["parts"]["heat10"] == 10
    assert r["book"]["bid_value_ratio"] > 0.3 and abs(r["book"]["chg1"] - 900 / 850 + 1) < 1e-3


def test_bid_drop_and_release_block_stage2():
    b = _bars([12000] * 10 + [LIM] * 20)
    book = {"bid1": LIM, "bid_qty": 300_000, "total_bid": 400_000, "total_ask": 0}
    hist = [{"bid_qty": 900_000, "locked": True}] * 5
    r = lc.evaluate(_daily(), _today(b), b, book, {"book_hist": hist, "now": pd.Timestamp("2026-10-12 10:00")})
    assert "상한가 매수잔량 급감" in r["risks"] and not r["stage2"]
    # 풀린 채 + 매도세 지속 (2번 풀림)
    b2 = _bars([12000] * 5 + [LIM] * 3 + [12600] * 3 + [LIM] * 3 + [12400] * 8)
    r2 = lc.evaluate(_daily(), _today(b2), b2, None, {"now": pd.Timestamp("2026-10-12 10:00")})
    assert r2["lock"]["releases"] == 2 and not r2["stage2"] and any("풀림" in x for x in r2["risks"])


def test_exclusions_invalid_and_consecutive():
    b = _bars([12000] * 10 + [LIM] * 10)
    r = lc.evaluate(_daily(), _today(b), b, None, {"danger": "투자경고", "now": pd.Timestamp("2026-10-12 10:00")})
    assert r["status"] == "제외"
    fell = _bars([12000] * 5 + [LIM] * 5 + [11500] * 5)                 # 도달 후 +15% 로 밀림
    r = lc.evaluate(_daily(), _today(fell), fell, None, {"now": pd.Timestamp("2026-10-12 11:00")})
    assert r["status"] == "조건 무효"
    r = lc.evaluate(_daily(spike=True), _today(b), b, None, {"now": pd.Timestamp("2026-10-12 10:00")})
    assert r["first"]["consecutive"] and r["parts"]["first10"] == 2
    low = lc.evaluate(_daily(), _today(b, value=50e8), b, None, {"now": pd.Timestamp("2026-10-12 10:00")})
    assert low["status"] == "대상 아님"


def test_near_limit_unreached_group():
    b = _bars([11000] * 10 + [12800] * 10)                               # +28%, 상한가 전
    book = {"bid1": 12790, "bid_qty": 5000, "total_bid": 300_000, "total_ask": 100_000}
    r = lc.evaluate(_daily(), _today(b), b, book, {"now": pd.Timestamp("2026-10-12 10:00")})
    assert r["group"] == "미도달" and r["entry"] == 12800 and r["parts"]["bid25"] > 5


def test_simulate_next():
    t = pd.date_range("2026-10-13 09:00", periods=4, freq="1min")
    m = pd.DataFrame({"time": t, "open": [14000, 14300, 14100, 13800], "high": [14300, 14400, 14150, 13900],
                      "low": [13950, 14250, 13900, 13700], "close": [14250, 14150, 13950, 13800]})
    r = lc.simulate_next(m, LIM)
    # 시가 14000 절반 · 고점 14400 의 −3% = 13968 → 3번째 봉 저가 13900 에서 이탈
    exp = (0.5 * 14000 + 0.5 * 14400 * 0.97) / LIM - 1 - lc.COST
    assert r["outcome"] == "trail" and abs(r["pnl"] - exp * 100) < 1e-2 and r["gap_pct"] > 7


def test_replay_and_finish():
    closes = [11000] * 20 + [12800] * 5 + [LIM] * 10 + [12900] * 3 + [LIM] * 200
    m = _bars(closes)
    tr = le.replay_day(m, _daily(), PREV)
    assert set(tr) == {"a1", "a2", "a3"}
    assert tr["a1"]["entry"] == 12800 and tr["a3"]["entry"] == LIM and tr["a2"]["filled"] and tr["a3"]["locked_close"]
    nb = _bars([14000] * 30, start="2026-10-13 09:00")
    r = le.finish(tr["a3"], nb)
    assert r["outcome"] == "time" and r["pnl"] > 0
    # 도달 후 끝까지 잠김 → ② 못 삼
    tr2 = le.replay_day(_bars([11000] * 10 + [LIM] * 300), _daily(), PREV)
    assert not tr2["a2"]["filled"] and le.finish(tr2["a2"], nb) is None
    # 매수 뒤 +20% 아래로 → 조건 무효
    tr3 = le.replay_day(_bars([11000] * 10 + [LIM] * 5 + [11800] * 30), _daily(), PREV)
    r3 = le.finish(tr3["a3"], None)
    assert r3["outcome"] == "invalid" and r3["pnl"] < -9


def test_evaluate_prev_and_report():
    sig = {"date": "2026-10-12", "first_buy": [
        {"code": "000010", "name": "가", "date": "2026-10-12", "time": "10:00", "score": 82, "group": "도달",
         "entry": LIM, "stop": 12000, "limit": LIM, "prev_close": PREV, "releases_at": 0, "reach_time": "09:40"}],
        "final": [{"code": "000010", "name": "가", "date": "2026-10-12", "score": 82, "status": "강세 후보",
                   "group": "도달", "limit": LIM, "lock": {"releases": 0, "reach_time": "09:40"}},
                  {"code": "000020", "name": "나", "date": "2026-10-12", "score": 70, "status": "관찰",
                   "group": "미도달", "limit": LIM, "lock": {}}]}
    store = {"limitcatch/signals/2026-10-12.json": json.dumps(sig).encode()}

    class SB:
        def download(self, k): return store.get(k)
        def upload(self, k, b, ct): store[k] = b
        def select(self, *a, **k): return []
        def upsert(self, table, rows, key): store[f"_{table}"] = rows

    class K:
        def minute_bars(self, code, until): return _bars([14000] * 30, start="2026-10-13 09:01")

    rows = {("000010", "2026-10-12"): {"close": LIM}, ("000010", "2026-10-13"): {"open": 14000},
            ("000020", "2026-10-12"): {"close": 12500}, ("000020", "2026-10-13"): {"open": 12000}}
    n = le.evaluate_prev(SB(), K(), "2026-10-13", lambda c, d: rows.get((c, d)))
    assert n == 3
    res = json.loads(store[le.RESULTS])
    assert res[0]["fill"] == "체결 불확실" and res[0]["locked_close"] and res[0]["pnl"] > 0
    fin = json.loads(store[le.FINALS])
    rep = le.report(fin)
    assert rep["by_score"]["80~89"]["hold"] == 100 and rep["by_score"]["75 미만"]["hold"] == 0
    assert store["_backtests"][0]["key"] == "LIMIT" if "_backtests" in store else True
    assert le.evaluate_prev(SB(), K(), "2026-10-13", lambda c, d: rows.get((c, d))) == 0     # 두 번 매기지 않음


def test_runner_step(monkeypatch, tmp_path):
    import scripts.limitcatch as sl
    from stockeye.data.sources import naver_live
    d = _daily()
    oh = pd.concat([d.assign(code=c) for c in ("000010", "000020", "000030")])
    listing = pd.DataFrame({"code": ["000010", "000020", "000030"], "name": ["가전자", "나바이오", "다화학"],
                            "market": ["KOSDAQ"] * 3, "is_admin": [False, False, True]})
    sectors = pd.DataFrame({"code": ["000010", "000020", "000030"], "sector": ["전기", "전기", "화학"]})
    snap = pd.DataFrame({"code": ["000010", "000020", "000030"], "close": [LIM, 11000, LIM], "chg_pct": [30.0, 10.0, 30.0],
                         "value": [300e8, 300e8, 300e8], "volume": [1e6] * 3})
    monkeypatch.setattr(naver_live, "stocks", lambda codes, **k: (_ for _ in ()).throw(AssertionError("전 종목 시세 호출")))

    class K:
        def fluctuation_rank(self): return snap.copy()
        def price(self, c):
            return {"price": LIM, "change_pct": 30.0, "open": 11000, "high": LIM, "low": 11000, "prev_close": PREV,
                    "volume": 2e6, "value": 300e8, "listed_shares": 2e7, "upper_limit": LIM, "status_code": "55",
                    "warn_code": "01", "halted": False}
        def asking(self, c): return {"bid1": LIM, "bid_qty": 800_000, "total_bid": 1e6, "total_ask": 0}
        def minute_bars_day(self, c, s, e): return _bars([12000] * 10 + [LIM] * 20)
        def minute_bars(self, c, e): return _bars([LIM], start="2026-10-12 09:30")

    monkeypatch.setattr(sl, "_now", lambda: pd.Timestamp("2026-10-12 10:00"))      # 날짜 고정 (Runner 가 만들 때 오늘을 읽음)
    run = sl.Runner(None, K(), listing, oh, sectors, workers=2, log_dir=tmp_path)
    p = run.step()
    codes = {r["code"]: r for r in p["items"]}
    assert set(codes) == {"000010", "000030"} and codes["000030"]["status"] == "제외"
    # 뉴스·업종 정보 없이(중립) 잠김·두꺼운 잔량 → 70점대 (재료·업종이 붙어야 75 넘음)
    assert codes["000010"]["status"] in ("관찰", "강세 후보") and codes["000010"]["score"] > 68 and p["groups"]["도달"] == 2
    assert (tmp_path / "ticks_2026-10-12.jsonl").exists() and p["version"] == lc.VERSION
    assert sl.danger_of({"warn_code": "02"}, False) == "투자경고" and sl.danger_of({"warn_code": "01"}, False) is None


def test_discover_falls_back_to_naver_every_5min(monkeypatch):
    import scripts.limitcatch as sl
    from stockeye.data.sources import naver_live
    calls = []
    snap = pd.DataFrame({"code": ["000010"], "close": [LIM], "chg_pct": [30.0], "value": [300e8], "volume": [1e6]})
    monkeypatch.setattr(naver_live, "stocks", lambda codes, **k: calls.append(1) or snap.copy())

    class K:
        def fluctuation_rank(self): raise RuntimeError("x")
    listing = pd.DataFrame({"code": ["000010"], "name": ["가전자"]})
    run = sl.Runner(None, K(), listing, _daily().assign(code="000010"), None)
    run.discover(); run.discover()
    assert len(calls) == 1                                          # 5분 안에는 다시 받지 않음
    live = {"time": "10:10", "groups": [{"group": "전기", "chg_pct": 2.0, "n": 10, "up": 7}]}
    assert sl.sector_of(live, "전기") == {"up_ratio": 0.7, "chg_pct": 2.0, "n": 10, "at": "10:10"}
    assert sl.sector_of(live, "화학") is None


def test_runner_pre(monkeypatch, tmp_path):
    """상한가 예비: +10~20% · 고가 근처 · 거래대금 가속 → 'pre' 목록과 첫 기록"""
    import scripts.limitcatch as sl
    d = _daily()
    oh = d.assign(code="000020")
    listing = pd.DataFrame({"code": ["000020"], "name": ["나바이오"], "market": ["KOSDAQ"], "is_admin": [False]})
    snap = pd.DataFrame({"code": ["000020"], "close": [11500], "chg_pct": [15.0], "value": [80e8], "volume": [1e6]})

    class K:
        def fluctuation_rank(self, market="0000"): return snap.copy()
        def price(self, c):
            return {"price": 11500, "change_pct": 15.0, "open": 10100, "high": 11520, "low": 10000, "prev_close": 10000,
                    "volume": 7e5, "value": 80e8, "upper_limit": 13000, "status_code": "55", "warn_code": "00",
                    "halted": False}
        def asking(self, c): return {"total_bid": 3e5, "total_ask": 1e5}
        def minute_bars_day(self, c, s, e):
            b = _bars([10000 + 50 * i for i in range(30)])
            b.loc[b.index[-5:], "volume"] = b["volume"].iloc[0] * 4
            return b
        def minute_bars(self, c, e): return self.minute_bars_day(c, None, None).tail(1)

    monkeypatch.setattr(sl, "_now", lambda: pd.Timestamp("2026-10-12 09:40"))
    run = sl.Runner(None, K(), listing, oh, None, workers=2, log_dir=tmp_path)
    p = run.step()
    assert p["pre"] and p["pre"][0]["code"] == "000020" and p["pre"][0]["status"] in ("상한가 예비", "관찰")
    assert p["pre_version"] == "LP-0.1"
    if p["pre"][0]["status"] == "상한가 예비":
        assert p["pre_first"][0]["time"] == "09:40"


def test_limitcatch_buy_alerts_admin(monkeypatch):
    """상한가포착 단독 실행에서도 매수발생 → 관리자 알림"""
    import scripts.limitcatch as sl
    import scripts.intraday_live as il
    from stockeye.trading.notify import Notifier
    sent = []
    monkeypatch.setattr(Notifier, "send_topic", lambda self, tp, title, body, priority="default": sent.append((tp, title)) or True)
    monkeypatch.setattr(il, "admin_topics", lambda sb: ["adm"])
    listing = pd.DataFrame({"code": ["000010"], "name": ["가"], "market": ["KOSPI"]})
    run = sl.Runner(None, None, listing, _daily().assign(code="000010"), None)
    t = {"name": "가", "code": "000010", "time": "10:05", "entry": 10000.0, "stop": 9800.0, "t1": 10200.0}
    run.track.on_event(run.track, t, "매수발생")
    assert sent == [("adm", sent[0][1])] and "매수발생" in sent[0][1]
