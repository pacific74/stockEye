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
