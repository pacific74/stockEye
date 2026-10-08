"""상승초기형 V1: 구간표 기준점·제외 필터·배점 상한·예외 처리"""
import numpy as np
import pandas as pd

from stockeye.engine import early as up


def test_anchors():
    assert up.ramp([2.0], up.K["g20"])[0] == 5 and up.ramp([1.0], up.K["s20"])[0] == 10
    assert up.ramp([3.0], up.K["r5"])[0] == 8 and up.ramp([10.0], up.K["r20"])[0] == 7
    assert up.ramp([55], up.K["rsi"])[0] == 5 and up.ramp([75], up.K["rsi"])[0] == 0
    assert up.ramp([2], up.K["value"])[0] == 5 and abs(up.ramp([1], up.K["value"])[0] - 2) < 1e-9   # 100억 / 10억
    assert 4 < up.ramp([0.6], up.K["s20"])[0] < 10                  # 계단 사이 값


def _bars(n=90):
    d = pd.bdate_range("2026-01-02", periods=n)
    c = np.r_[np.linspace(10000, 9000, 60), np.full(20, 9000.0) + 30 * np.sin(np.arange(20)), np.linspace(9050, 9500, 10)]
    C = pd.DataFrame({"A": c, "B": np.linspace(10000, 8000, n)}, index=d)
    V = pd.DataFrame({"A": np.r_[np.full(80, 1e6), np.full(10, 1.3e6)], "B": np.full(n, 1e6)}, index=d)
    return C * 0.997, C * 1.01, C * 0.99, C, V


def test_score_and_exclusions():
    O, H, L, C, V = _bars()
    f = up.raw_features(O, H, L, C, V, dates=[C.index[-1]])
    sc = up.score_today(f, C.index[-1])
    for p, (_, mx) in up.PARTS.items():
        assert (sc[p] <= mx + 1e-9).all() and (sc[p] >= 0).all()
    assert not sc.loc["A", "excluded"]                             # 20일선 회복 + 상승 시작
    assert sc.loc["B", "excluded"] and sc.loc["B", "ex_below20"]   # 하락 중 → 20일선 아래 제외
    assert sc.loc["A", "total"] >= 60


def test_updown_zero_down_volume():
    keys = ["G20", "S20", "S5", "R5", "R20", "B20", "S60", "DG", "V5R", "VNOW", "VAL20", "ATR", "RSI"]
    f = {k: pd.Series([np.nan]) for k in keys}
    f["MA5_GT"] = pd.Series([False])
    f["UPV"], f["DNV"] = pd.Series([1e6]), pd.Series([0.0])
    assert up.score_frame(f)["updown"].iloc[0] == 3.0
