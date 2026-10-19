"""종가배팅: 점수·갭 위험·제외·다음 날 청산"""
import numpy as np
import pandas as pd

from stockeye.engine import closingbet as cb


def _daily(n=60, c=10000.0):
    d = pd.bdate_range("2026-07-01", periods=n)
    close = c * (1 + 0.002 * np.arange(n))
    return pd.DataFrame({"date": d, "open": close * 0.998, "high": close * 1.01, "low": close * 0.99, "close": close,
                         "volume": 1e6})


def test_strong_close_scores_high():
    d = _daily()
    prev = float(d["close"].iloc[-1])
    today = {"open": prev * 1.01, "high": prev * 1.06, "low": prev * 1.005, "close": prev * 1.058, "volume": 3e6,
             "value": 300e8, "vwap": prev * 1.04, "prev_close": prev}
    r = cb.evaluate(d, today, None, {"news_level": "pos", "idx_chg": 0.8, "sector_chg": 1.5, "now": pd.Timestamp("2026-10-12 15:15")})
    assert not r["excluded"] and r["type"] == "돌파" and r["score"] >= 80 and r["status"] == "매수 후보"
    assert r["stop"] < r["entry"] < r["t1"] < r["t2"] and r["buy_lo"] <= r["entry"] <= r["buy_hi"]
    assert r["gap"]["grade"] in ("낮음", "보통") and len(r["exit_rules"]) == 4


def test_exclusions_and_gap_risk():
    d = _daily()
    prev = float(d["close"].iloc[-1])
    hot = {"open": prev, "high": prev * 1.25, "low": prev, "close": prev * 1.22, "volume": 5e6, "value": 20e8, "prev_close": prev}
    r = cb.evaluate(d, hot, None, {"news_level": "severe", "idx_chg": -1.5})
    assert r["status"] == "진입 금지" and len(r["excluded"]) == 3
    assert r["gap"]["grade"] == "높음" and any("급등" in w for w in r["gap"]["why"])


def test_simulate_next_rules():
    t = pd.date_range("2026-10-13 09:00", periods=4, freq="1min")
    m = lambda rows: pd.DataFrame([{"time": t[i], "open": o, "high": h, "low": l, "close": c} for i, (o, h, l, c) in enumerate(rows)])  # noqa: E731
    # ① 갭 하락: 시초가 9700 < 손절 9800 → 시초가 전량
    r = cb.simulate_next(m([(9700, 9750, 9650, 9700)]), 10000, 9800, 10200, 10400)
    assert r["outcome"] == "gap_stop" and abs(r["pnl"] - (-3 - cb.COST * 100)) < 1e-6
    # ② 갭 상승 10250 ≥ 1차 → 시초가 절반, 그 뒤 2차 10400 도달 → 나머지
    r = cb.simulate_next(m([(10250, 10300, 10220, 10280), (10280, 10420, 10270, 10400)]), 10000, 9800, 10200, 10400)
    assert r["outcome"] == "t2" and abs(r["pnl"] - ((0.5 * 10250 + 0.5 * 10400) / 10000 - 1 - cb.COST) * 100) < 1e-6
    # ④ 아무것도 안 닿음 → 마지막 봉 종가
    r = cb.simulate_next(m([(10010, 10050, 9950, 10020), (10020, 10060, 9990, 10030)]), 10000, 9800, 10200, 10400)
    assert r["outcome"] == "time"
    d = cb.simulate_daily({"open": 10100, "high": 10300, "low": 10050}, 10000, 9800, 10200)
    assert d["outcome"] == "t1" and d["open_pnl"] > 0


def test_runner_step_and_evaluate_prev(monkeypatch):
    import json
    import scripts.closingbet as sc
    from stockeye.data.sources import naver_live
    from stockeye.analysis import closingbet_eval as ce
    d = _daily()
    oh = pd.concat([d.assign(code="000010"), d.assign(code="000020")])
    prev = float(d["close"].iloc[-1])

    class K:
        def price(self, code):
            c = prev * (1.058 if code == "000010" else 1.0)
            return {"open": prev * 1.01, "high": prev * 1.06, "low": prev * 1.005, "price": c, "prev_close": prev,
                    "volume": 3e6, "value": 300e8}

        def minute_bars_day(self, code, s, e, day=None):
            t = pd.date_range("2026-10-13 09:00", periods=3, freq="1min")
            return pd.DataFrame({"time": t, "open": [prev * 1.07] * 3, "high": [prev * 1.08] * 3,
                                 "low": [prev * 1.06] * 3, "close": [prev * 1.075] * 3, "volume": 1})

        def minute_bars(self, code, e):
            return self.minute_bars_day(code, "", e)

    snap = pd.DataFrame([{"code": "000010", "close": prev * 1.058, "chg_pct": 5.8, "value": 300e8},
                         {"code": "000020", "close": prev, "chg_pct": 0.0, "value": 100e8}])
    monkeypatch.setattr(naver_live, "stocks", lambda codes: snap)
    monkeypatch.setattr(naver_live, "indices", lambda: pd.DataFrame([{"code": "KOSPI", "chg_pct": 1.0}]))
    monkeypatch.setattr(sc, "_now", lambda: pd.Timestamp("2026-10-12 15:20:10"))
    lst = pd.DataFrame({"code": ["000010", "000020"], "name": ["가", "나"], "market": ["KOSPI", "KOSPI"]})
    secs = pd.DataFrame({"code": ["000010", "000020"], "sector": ["반도체", "반도체"]})   # 업종 평균 +2.9%
    run = sc.Runner(None, K(), lst, oh, secs, top=10)
    p = run.step()
    assert p["final"] and p["items"][0]["code"] == "000010" and p["picks"] and p["picks"][0]["code"] == "000010"

    class SB:
        def __init__(self):
            self.files = {"closingbet/signals/2026-10-12.json": json.dumps(p["picks"], default=str).encode()}

        def download(self, k):
            return self.files.get(k)

        def upload(self, k, data, ct):
            self.files[k] = data

        def select(self, *a, **k):
            return []

        def upsert(self, *a, **k):
            pass

    sb = SB()
    n = ce.evaluate_prev(sb, K(), "2026-10-13", lambda code, day: prev * 1.058)
    hist = json.loads(sb.files[ce.RESULTS])
    assert n == 1 and hist[0]["outcome"] in ("t1", "t2") and hist[0]["open_pnl"] > 0


def test_closingbet_buy_alerts_admin(monkeypatch):
    """종가배팅 매수발생 → 관리자 토픽으로 알림 (예전엔 알림 경로가 없었음)"""
    import scripts.closingbet as sc
    import scripts.intraday_live as il
    from stockeye.trading.notify import Notifier
    sent = []
    monkeypatch.setattr(Notifier, "send_topic", lambda self, tp, title, body, priority="default": sent.append((tp, title, body)) or True)
    monkeypatch.setattr(il, "admin_topics", lambda sb: ["adm-topic"])
    lst = pd.DataFrame({"code": ["000010"], "name": ["가"], "market": ["KOSPI"]})
    run = sc.Runner(None, None, lst, _daily().assign(code="000010"), None, top=5)
    assert run.track.on_event is not None
    t = {"name": "가", "code": "000010", "time": "15:05", "buy_time": "15:05", "entry": 10000.0, "stop": 9800.0, "t1": 10200.0}
    run.track.on_event(run.track, t, "매수발생")
    run.track.on_event(run.track, t, "손절")            # 매수발생 말고는 안 보냄
    assert len(sent) == 1 and sent[0][0] == "adm-topic" and "매수발생" in sent[0][1]
