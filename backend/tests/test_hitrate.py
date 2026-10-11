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


Z = [(101.0, 30.0), (98.0, 30.0), (96.0, 40.0)]       # 1·2·3차 매수구간 상단 · 비중


def _s(o, h, l, c, zones=Z):
    f = lambda v: np.array(v, float)  # noqa: E731
    return hr.simulate(f(o), f(h), f(l), f(c), zones, T, 95.0)


def test_simulate_split_buy_sell():
    C = hr.COST
    # 시가 100 (1차 구간) 30% 매수 → 같은 날 1차·2차·3차 다 닿음: 0.5·110 + 0.3·120 + 0.2·130 = 117
    r = _s([100], [131], [99.5], [125])
    assert r["outcome"] == "t3" and r["filled"] == 30 and abs(r["pnl"] - (17 - C)) < 1e-6
    # 1일째 시가 100 에 30%, 2일째 98 까지 내려 30% 더 → 평균 99 · 3일째 1차(50%) 110 → 4일째 본전 99 로 밀림
    r = _s([100, 99, 105, 108], [100, 100, 111, 108], [99.5, 97, 104, 98], [100, 99, 110, 99])
    avg = 60 / (30 / 100 + 30 / 98)
    exp = (0.5 * 110 + 0.5 * avg) / avg - 1
    assert r["outcome"] == "t1" and r["filled"] == 60 and abs(r["pnl"] - (exp * 100 - C)) < 1e-6
    # 1·2·3차 다 사고 손절 95 → 산 금액 기준 손실
    r = _s([100, 97, 96], [101, 98, 97], [99, 96.5, 94], [100, 97, 95])
    cost, qty = 100, 30 / 100 + 30 / 97 + 40 / 96         # 2일째 시가 97 이 2차 상단 98 보다 낮아 시가에 삼
    assert r["outcome"] == "stop" and r["filled"] == 100 and abs(r["pnl"] - ((qty * 95 / cost - 1) * 100 - C)) < 1e-6
    # 시가가 1차 구간 위(103)에서 놀다 끝 → 하나도 못 삼 = 미체결
    assert _s([103, 104], [105, 106], [102, 103], [104, 105])["outcome"] is None
    # 시가 103 → 그날 101 까지 내려오면 1차 상단 101 에 삼
    r = _s([103], [104], [100.5], [102])
    assert r["filled"] == 30 and r["outcome"] == "flat" and abs(r["pnl"] - ((102 / 101 - 1) * 100 - C)) < 1e-6
