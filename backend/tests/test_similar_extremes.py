"""비슷한 패턴 '그 뒤': 그날 종가만이 아니라 기간 중 장중 최고·최저와 그날도 계산"""
import numpy as np
import pandas as pd

from stockeye.analysis.similar import PatternIndex


def test_extremes_catch_intraday_spike():
    d = pd.bdate_range("2025-01-01", periods=80)
    close = np.full(80, 10000.0)
    high, low = close.copy(), close.copy()
    e = 40                                  # 패턴 끝날
    high[e + 2] = 13000.0                   # 2일째 장중 +30% (상한가) → 종가는 그대로
    low[e + 5] = 9000.0                     # 5일째 장중 −10%
    df = pd.DataFrame({"date": d, "code": "000010", "close": close, "high": high, "low": low,
                       "value": 5e9, "chg_pct": 0.0})
    pi = PatternIndex(df, window=20)
    x = pi._extremes(e, 0, 20)
    assert x["max_day"] == 2 and round(x["max20"], 1) == 30.0 and round(x["max5"], 1) == 30.0
    assert x["min_day"] == 5 and round(x["min20"], 1) == -10.0 and round(x["min3"] if "min3" in x else x["min5"], 1) <= 0
    assert x["max_close"] == 0.0            # 종가로만 보면 놓치는 급등


def test_group_candles_robust_to_outliers():
    """30개 중 23개는 1일차 −1%, 몇 개만 +10% 고가 → 그룹 봉 고가는 +10% 가 아니라 가운데 쪽 값"""
    H = 20
    res = []
    for i in range(30):
        o = np.zeros((H, 4))
        o[:, 0], o[:, 3] = -1.0, -1.0
        o[:, 1], o[:, 2] = 0.0, -2.0
        if i in (0, 10, 20):
            o[0, 1] = 10.0                                   # 극단 고가 몇 개
        if i == 3:
            o[0, 2] = -10.0                                  # 극단 저가 하나
        res.append({"similarity": 80 - i, "_ohlc": o})
    pi = PatternIndex.__new__(PatternIndex)
    g = pi._groups(res, H)
    assert [x["name"] for x in g] == ["상위 20%", "중위 30%", "하위 50%"] and [x["n"] for x in g] == [6, 9, 15]
    o_, h_, l_, c_ = g[0]["candles"][0]
    assert c_ == -1.0 and h_ < 10 and l_ > -10                # 극단값에 끌려가지 않음
    assert all("_ohlc" not in r for r in res)
