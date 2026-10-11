"""관심종목 적중률: 목표/손절 판정 순서 · 승률(보합 제외) · 일부 다시 돌리기 합치기"""
import numpy as np
import pandas as pd

from stockeye.analysis import hitrate as hr

T = (110.0, 120.0, 130.0)


def _j(o, h, l):
    return hr.judge(np.array(o, float), np.array(h, float), np.array(l, float), T, 95.0)


def test_judge_orders():
    assert _j([100, 101], [105, 112], [99, 100])[0] == "t1"                       # 2일째 1차
    r, f = _j([100, 101, 115], [105, 121, 131], [99, 100, 90])
    assert r == "t3" and f["t2"] == 2 and f["t3"] == 3                            # 3일째 3차 뒤 손절 → 3차로 분류
    assert _j([100, 100], [112, 105], [94, 99])[0] == "stop"                      # 같은 날 손절·목표 → 손절 먼저
    assert _j([100, 96], [104, 97], [97, 94])[0] == "stop"
    assert _j([100] * 20, [104] * 20, [97] * 20)[0] == "flat"
    assert _j([111, 111], [113, 113], [109, 109])[0] == "t1"                      # 시초가가 목표 위로 뜸 → 그날 목표


def test_summary_win_excludes_flat():
    d = pd.Timestamp("2025-03-03")
    rows = [("t1", 1)] * 20 + [("t2", 3)] * 20 + [("t3", 5)] * 10 + [("stop", None)] * 20 + [("flat", None)] * 30
    df = pd.DataFrame({"date": d, "outcome": [r for r, _ in rows], "d_t1": [x for _, x in rows],
                       "d_t2": None, "d_t3": None, "d_stop": None})
    s = hr._summary(df)
    assert s["t1"] == 20 and s["flat"] == 30 and s["win"] == round(50 / 70 * 100, 1)   # 사용자 예시: 약 70%
    assert sum(s["days"]["t1"]) == 50 and len(s["days"]["t1"]) == 20


def test_merge_partial_years():
    y = lambda n, w: {"n": n, "t1": w, "t2": 0, "t3": 0, "stop": 100 - w, "flat": 0, "win": w, "days": {}, "quarters": {}}  # noqa: E731
    old = {"version": hr.VERSION, "tabs": {"early": {"name": "상승초기", "years": {"2024": y(10, 50), "2025": y(10, 50)}, "total": {}}}}
    new = {"version": hr.VERSION, "partial": {"tabs": ["early"], "years": [2025]},
           "tabs": {"early": {"name": "상승초기", "years": {"2025": y(30, 70)}, "total": {}}}}
    m = hr.merge(old, new)
    assert set(m["tabs"]["early"]["years"]) == {"2024", "2025"} and m["tabs"]["early"]["years"]["2025"]["n"] == 30
    assert m["tabs"]["early"]["total"]["n"] == 40 and m["tabs"]["early"]["total"]["t1"] == 65.0


def _p(o, h, l, c):
    f = lambda v: np.array(v, float)  # noqa: E731
    return hr.pnl(f(o), f(h), f(l), f(c), 100.0, T, 95.0)


def test_pnl_split_sell():
    C = hr.COST
    # 1·2·3차 다 닿음 → 0.5·110 + 0.3·120 + 0.2·130 = 117
    assert abs(_p([100, 101], [105, 131], [99, 101], [101, 125]) - (17 - C)) < 1e-6
    # 1차(50%) 뒤 매수가 100 까지 밀림 → 남은 50% 본전 → 0.5·110 + 0.5·100 = 105
    assert abs(_p([100, 108, 104], [105, 112, 105], [99, 106, 99], [101, 110, 100]) - (5 - C)) < 1e-6
    # 1·2차(80%) 뒤 본전 → 0.5·110 + 0.3·120 + 0.2·100 = 111
    assert abs(_p([100, 101, 118], [105, 121, 119], [99, 101, 99], [101, 119, 100]) - (11 - C)) < 1e-6
    # 목표 전에 손절 → 전부 95, 갭하락이면 시가 90
    assert abs(_p([100, 97], [104, 98], [97, 94], [99, 95]) - (-5 - C)) < 1e-6
    assert abs(_p([90.0], [92.0], [89.0], [91.0]) - (-10 - C)) < 1e-6
    # 아무것도 안 닿음 → 20일째(마지막) 종가
    assert abs(_p([100, 101], [104, 104], [97, 97], [101, 102]) - (2 - C)) < 1e-6
