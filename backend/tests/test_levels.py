"""차트 기반 목표·손절: 저항·지지 선택, 신고가 영역, 분할 보정"""
import numpy as np
import pandas as pd

from stockeye.engine import levels


def _bars(c, spread=0.01):
    d = pd.bdate_range("2025-01-02", periods=len(c))
    c = np.asarray(c, float)
    return d, c * 0.998, c * (1 + spread), c * (1 - spread), c, np.full(len(c), 1e5)


def test_resistance_and_support_used():
    # 100 → 120 고점 → 95 저점 → 105 (지금): 위에 120·되돌림, 아래 95 지지
    c = np.r_[np.linspace(100, 120, 40), np.linspace(120, 95, 40), np.linspace(95, 105, 30)]
    r = levels.compute(*_bars(c))
    assert r["price"] == 105
    assert 105 < r["target1"] <= r["target2"] <= 125
    assert r["target3"] > r["target2"] and any(b.startswith("3차 목표") for b in r["basis"])
    assert 85 < r["stop"] < 103
    assert any("저항" in b for b in r["basis"]) and any("지지" in b for b in r["basis"])
    assert r["entry_low"] <= r["entry_high"]


def test_new_high_uses_atr_projection():
    c = np.linspace(50, 150, 120)                     # 계속 신고가 → 위 저항 없음
    r = levels.compute(*_bars(c))
    assert any("저항 없음" in b for b in r["basis"]) and r["target2"] > r["target1"] > 150


def test_split_adjust():
    g = pd.DataFrame({"close": [10000.0, 10100.0, 2040.0, 2060.0], "chg_pct": [0.0, 1.0, 1.0, 0.98]})
    adj = levels.adjust(g, "close")
    assert abs(adj[0] - 2000) < 1 and abs(adj[1] - 2020) < 1 and adj[-1] == 2060   # 1/5 분할 전 가격 보정


def test_zones_and_notes():
    c = np.r_[np.linspace(100, 120, 40), np.linspace(120, 95, 40), np.linspace(95, 105, 30)]
    r = levels.compute(*_bars(c))
    z = r["zones"]
    assert 1 <= len(z) <= 3 and sum(x["weight"] for x in z) == 100
    assert all(x["low"] > r["stop"] for x in z) and z[0]["high"] >= r["price"]
    assert all(z[i]["low"] >= z[i + 1]["high"] - 1 for i in range(len(z) - 1))     # 위에서 아래로
    assert {"target1", "target2", "target3", "stop"} <= set(r["notes"])


def test_tech_summary():
    from stockeye.analysis.tech_summary import summarize
    x = {"close": 110.0, "sma5": 108.0, "sma20": 105.0, "sma60": 100.0, "sma120": 95.0, "sma20_slope": 0.01,
         "sma60_slope": 0.005, "rsi14": 62.0, "macd": 1.0, "macd_signal": 0.5, "macd_hist": 0.5, "macd_hist_prev": -0.1,
         "bb_pos": 0.85, "ret5": 0.03, "ret20": 0.08, "vol_ratio": 2.2, "vol5_ratio": 1.3, "updown_vol20": 1.5,
         "ret1": 0.02, "near_high250": 0.98}
    s = summarize(x, {"entry_low": 108, "entry_high": 111, "target1": 118, "stop": 102, "rr1": 1.0})
    assert s["tone"] == "강세" and "정배열" in s["text"] and "골든크로스" in s["text"] and "매수구간" in s["text"]
