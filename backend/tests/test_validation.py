"""관심종목 검증(VAL-1.0): 가격 경로 지표 · 미체결 · 수정주가 이상 제외 · 목표/손절 순서 · 반복 신호 · 5분위/IC"""
import numpy as np
import pandas as pd

from stockeye.analysis import validation as va


def _W(close, high=None, low=None, open_=None, code="A"):
    d = pd.bdate_range("2026-01-05", periods=len(close))
    mk = lambda v: pd.DataFrame({code: np.asarray(v, float)}, index=d)  # noqa: E731
    c = mk(close)
    return {"close": c, "high": mk(high if high is not None else close), "low": mk(low if low is not None else close),
            "open": mk(open_ if open_ is not None else close), "volume": mk([1000] * len(close))}, d


def test_path_metrics_example():
    # 명세서 추가 설계 4절 예시와 같은 모양: 기준 10,000 → 2일째 고가 +12% · 4일째 고가 +16% · 5일째 종가 +3%
    close = [10000, 10200, 10600, 10400, 10500, 10300] + [10300] * 20
    high = [10000, 10250, 11200, 10500, 11600, 10400] + [10300] * 20
    low = [10000, 10000, 10300, 9600, 10200, 10100] + [10300] * 20
    W, d = _W(close, high, low)
    fw = va.forward(W)
    s = va.attach(pd.DataFrame({"date": [d[0]], "code": ["A"]}), fw, "close0").iloc[0]
    assert round(s["r5"], 2) == 3.0 and round(s["mfe5"], 2) == 16.0 and round(s["mae5"], 2) == -4.0
    assert s["pkday5"] == 4                                       # 최고가 도달일 = 4일째
    assert round(s["pkgb5"], 2) == round(100 * (11600 - 10500) / 11600, 2)   # 고점일 되돌림
    assert round(s["endgb5"], 2) == round(100 * (10300 / 11600 - 1), 2)       # 종료 시 반납폭


def test_limit_up_open_unfilled_and_jump_excluded():
    W, d = _W([10000, 13000, 13100] + [13100] * 22, open_=[10000, 12990, 13000] + [13100] * 22)
    s = va.attach(pd.DataFrame({"date": [d[0]], "code": ["A"]}), va.forward(W), "open1").iloc[0]
    assert s["unfilled"] and np.isnan(s["r1"])                  # 다음 날 시초가 상한가 → 미체결
    W2, d2 = _W([10000, 10100, 5000] + [5000] * 22)              # 2일째 −50% (액면 변경 등) → 그 구간 제외
    s2 = va.attach(pd.DataFrame({"date": [d2[0]], "code": ["A"]}), va.forward(W2), "close0").iloc[0]
    assert not np.isnan(s2["r1"]) and np.isnan(s2["r3"])


def test_dedupe_by_horizon():
    d = pd.bdate_range("2026-01-05", periods=30)
    p = pd.DataFrame({"date": [d[0], d[3], d[12], d[0]], "code": ["A", "A", "A", "B"]})
    r = va.dedupe(p, d, 10).set_index(["date", "code"])["repeat"]
    assert not r[(d[0], "A")] and r[(d[3], "A")] and not r[(d[12], "A")] and not r[(d[0], "B")]


def test_quintiles_and_ic_positive_when_score_predicts():
    rng = np.random.default_rng(0)
    rows = []
    for d in pd.bdate_range("2026-01-05", periods=40):
        sc = rng.uniform(0, 100, 50)
        for i, s in enumerate(sc):
            rows.append({"date": d, "code": f"{i:03d}", "score": s, "r10": s / 10 + rng.normal(0, 2),
                         "mfe10": 5.0, "mae10": -3.0, "pkday10": 3.0, "pkgb10": 1.0, "endgb10": -2.0})
    u = pd.DataFrame(rows)
    q = va.quintiles(u, 10)
    assert len(q) == 5 and q[-1]["median"] > q[0]["median"]
    assert va.rank_ic(u, 10)["mean"] > 0.5


def test_bootstrap_interval():
    x = pd.Series(np.full(60, 1.0) + np.random.default_rng(1).normal(0, 0.1, 60))
    b = va.bootstrap(x, 5)
    assert b["lo"] > 0 and b["lo"] <= b["mean"] <= b["hi"]
    assert va.bootstrap(x.head(10), 5) is None                   # 신호일 30일 미만 → 계산 안 함


def test_verdict_sample_shortage():
    p = {"name": "설계", "sufficient": False}
    assert va.verdict([p, {**p, "name": "확인"}], 10)["label"] == "표본 부족"
