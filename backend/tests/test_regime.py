import numpy as np
import pandas as pd

from stockeye.analysis import regime
from stockeye.engine import closingbet as cb
from stockeye.engine import daytrade as dt


def _idx():
    d = pd.bdate_range("2026-10-19", periods=6)
    k = [100, 101, 102, 103, 98, 101]           # 10/23 -4.9% → 10/26 +3.1%
    return pd.DataFrame({"date": list(d) * 2, "code": ["KOSPI"] * 6 + ["KOSDAQ"] * 6, "close": k + k})


def test_from_frame_and_rebound():
    days = regime.from_frame(_idx())
    assert days["2026-10-23"]["KOSPI"] < -4 and days["2026-10-26"]["KOSPI"] > 3
    assert regime.prev_chg(days, "2026-10-26", "KOSPI") < -4
    r = regime.rebound(regime.prev_chg(days, "2026-10-26", "KOSPI"), 3.1)
    assert r and "반등장" in r["why"]
    assert regime.rebound(-0.5, 3.0) is None and regime.rebound(-3.0, 0.2) is None
    assert regime.rebound(None, 3.0) is None                     # 기록 없으면 판정 안 함 = 예전 동작
    assert regime.rebound(-3.0, 0.2, gap=1.4)                    # 갭만으로도


def test_for_market_uses_open_gap():
    days = {"2026-10-26": {"KOSPI": -3.5}}
    ix = pd.DataFrame([{"code": "KOSPI", "chg_pct": 0.5, "open": 102.0, "close": 100.5}])   # prev=100.0 → 갭 +2%
    assert regime.for_market(days, "2026-10-27", ix, "KOSPI")


def _daily(closes):
    n = len(closes)
    c = np.array(closes, float)
    return pd.DataFrame({"date": pd.bdate_range(end="2026-10-26", periods=n), "open": c, "high": c * 1.01, "low": c * 0.99,
                         "close": c, "volume": np.full(n, 1e6)})


def test_closingbet_bounce_rules():
    flat = [100] * 20
    assert cb.bounce(_daily(flat + [93]), 6.0)                               # 어제 -7% → 오늘 +6%
    assert cb.bounce(_daily(flat + [91]), 6.0)                               # 5일 고점 대비 -9%... 어제 -9% 급락
    assert cb.bounce(_daily(flat[:-5] + [100, 100, 100, 96, 90]), 6.0)       # 이틀 연속 빠진 뒤 (고점 대비 -10%)
    assert cb.bounce(_daily(flat + [93]), 3.0) is None                       # 오늘 상승이 작으면 해당 없음
    assert cb.bounce(_daily(flat + [100]), 8.0) is None                      # 전날 급락 없던 정상 급등
    reb = {"why": "전날 지수 -3.0% → 오늘 +2.0% (반등장)"}
    assert cb.bounce(_daily(flat + [100]), 3.5, reb) and cb.bounce(_daily(flat + [100]), 2.0, reb) is None


def _bars(n=30, start=1000.0, step=4.0):
    t = pd.date_range("2026-10-27 09:00", periods=n, freq="min")
    c = start + np.arange(n) * step
    return pd.DataFrame({"time": t, "open": c - 1, "high": c + 2, "low": c - 2, "close": c, "volume": np.full(n, 50000.0)})


def test_daytrade_rebound_blocks_late_entry():
    b = _bars(45)
    ctx = {"prev_close": 950.0, "now": b["time"].iloc[-1], "value": 5e9, "idx_chg": 2.0, "adr": 0.07}
    base = dt.evaluate(b, ctx)
    reb = dt.evaluate(b, {**ctx, "rebound": {"prev": -3.0, "chg": 2.0, "why": "전날 지수 -3.0% → 오늘 +2.0% (반등장)"}})
    assert reb["rebound"] and not base["rebound"]
    assert any("09:40 이후" in w for w in reb["warnings"]) and reb["status"] != "진입 조건 충족"
    early = dt.evaluate(b.iloc[:25], {**ctx, "now": b["time"].iloc[24], "rebound": {"prev": -3.0, "chg": 2.0, "why": "x"}})
    assert not any("이후 신규 진입" in w for w in early["warnings"])


def test_daytrade_excludes_new_high_breakout():
    b = _bars(30, start=1000.0, step=4.0)                         # 꾸준히 오르는 돌파형 (마지막 ≈ 1116)
    ctx = {"prev_close": 950.0, "now": b["time"].iloc[-1], "value": 5e9, "idx_chg": 1.0, "adr": 0.07}
    near = dt.evaluate(b, {**ctx, "hi_n": 1110.0})                 # 최근 고점 바로 아래 → 신고가 돌파 시도
    assert any("신고가 돌파 시도" in e for e in near["excluded"]) and near["status"] == "진입 금지"
    far = dt.evaluate(b, {**ctx, "hi_n": 1500.0})                  # 고점이 한참 위 → 해당 없음
    assert not any("신고가" in e for e in far["excluded"])
    assert not any("신고가" in e for e in dt.evaluate(b, ctx)["excluded"])   # 일봉 정보 없으면 예전 동작
