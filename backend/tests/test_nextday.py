"""유망주 V1: 기준점·배점 상한·등급·제외·관찰 계획·다음 날 결과"""
import numpy as np
import pandas as pd

from stockeye.engine import nextday as nd
from stockeye.engine import nextday_report as ndr


def test_anchors_and_grade():
    assert nd.ramp([3.5], nd.K["a_g20"])[0] == 6 and nd.ramp([1.0], nd.K["a_s20"])[0] == 7
    assert nd.ramp([1.75], nd.K["b_v"])[0] == 6 and nd.ramp([3.0], nd.K["b_v"])[0] == 4     # 폭증은 감점
    assert nd.ramp([0.8], nd.K["c_pos"])[0] == 6 and nd.ramp([3.0], nd.K["d_atr"])[0] == 5
    assert nd.grade(85)[0] == "A" and nd.grade(72)[0] == "B" and nd.grade(61)[0] == "C" and nd.grade(50)[0] == "-"
    assert nd.common_stock("005930", "삼성전자") and not nd.common_stock("005935", "삼성전자우")
    assert not nd.common_stock("123450", "하나스팩1호")


def _wide(n=150):
    d = pd.bdate_range("2026-01-02", periods=n)
    up = np.r_[np.linspace(10000, 9000, 100), np.full(40, 9000.0) + 50 * np.sin(np.arange(40)), np.linspace(9100, 9600, 10)]
    C = pd.DataFrame({"A00000": up, "B00000": np.linspace(10000, 7000, n)}, index=d)
    O, H, L = C * 0.99, C * 1.01, C * 0.985
    H.iloc[-1] = C.iloc[-1] * 1.003
    V = pd.DataFrame({"A00000": np.r_[np.full(n - 1, 1e6), 2e6], "B00000": np.full(n, 1e6)}, index=d)
    ix = pd.DataFrame({"date": list(d) * 2, "code": ["KOSPI"] * n + ["KOSDAQ"] * n, "close": [1000.0] * (2 * n)})
    return O, H, L, C, V, ix


def test_score_caps_and_plan():
    O, H, L, C, V, ix = _wide()
    d = C.index[-1]
    f = nd.raw_features(O, H, L, C, V, C * V, nd.index_returns(ix), {}, dates=[d])
    cs = {k: v.loc[d] for k, v in f.items()}
    s = nd.score_frame(cs, None, False)
    t = nd.totals(s)
    for p, (_, mx) in nd.PARTS.items():
        assert (t[p] <= mx + 1e-9).all() and (t[p] >= 0).all()
    assert (s["f_news"] == 5).all()                              # 공시 정보 없음 → 중립 5
    assert t["total"]["A00000"] > t["total"]["B00000"]
    row = pd.Series({"_c": 9600.0, "_h": 9630.0, "_l": 9450.0, "_ma20": 9300.0, "_ma60": 9100.0, "_hi20p": 9700.0, "rv_ATR": 2.0})
    w = ndr.watch_plan(row)
    assert w["breakout"] >= 9700 and w["no_chase"] >= 9600 * 1.03 and w["invalid"] <= w["support"]


def test_outcome_next_day():
    oh = pd.DataFrame({"date": pd.to_datetime(["2026-10-08", "2026-10-08"]), "code": ["A", "B"],
                       "open": [1050.0, 990.0], "high": [1100.0, 1000.0], "low": [1000.0, 950.0], "close": [1080.0, 960.0]})
    e = {"date": "2026-10-07", "picks": [{"code": "A", "close": 1000, "no_chase": 1030, "invalid": 980},
                                         {"code": "B", "close": 1000, "no_chase": 1030, "invalid": 970}]}
    o = ndr.outcome(e, oh)
    r = {x["code"]: x for x in o["rows"]}
    assert r["A"]["gap"] == 5.0 and r["A"]["chased"] and r["B"]["invalid"] and o["n"] == 2
    assert ndr.live_status({"no_chase": 1030, "invalid": 980, "breakout": 1060, "support": 990}, 1040, 1050) == "갭 추격 금지"
