"""추세전환 점수: 기준점 보간·배점 상한·예외 처리·정렬"""
import numpy as np
import pandas as pd

from stockeye.engine import reversal as rv


def test_ramp_matches_spec_anchors():
    assert rv.ramp([-35], rv.K["d60"])[0] == 15 and rv.ramp([-5], rv.K["d60"])[0] == 0
    assert rv.ramp([8], rv.K["r20"])[0] == 10 and rv.ramp([40], rv.K["r20"])[0] == 0
    assert 7 < rv.ramp([12.5], rv.K["r20"])[0] < 10           # 계단이 아니라 중간값
    assert rv.ramp([1.0], rv.K["s20"])[0] == 15 and rv.ramp([3.0], rv.K["s20"])[0] == 10   # 너무 가파르면 감점
    assert np.isnan(rv.ramp([np.nan], rv.K["s20"])[0])
    for k, kn in rv.K.items():                                 # 배점 범위 안
        ys = [y for _, y in kn]
        assert min(ys) >= 0


def _bars(n=90, seed=0):
    d = pd.bdate_range("2026-01-02", periods=n)
    # 60일 하락 → 25일 횡보 → 5일 완만한 반등
    c = np.r_[np.linspace(10000, 6500, 60), 6500 + 80 * np.sin(np.arange(25)), np.linspace(6550, 6750, 5)]
    C = pd.DataFrame({"A": c, "B": c[::-1].copy()}, index=d)
    O = C * 0.995
    H, L = C * 1.01, C * 0.985
    V = pd.DataFrame({"A": np.r_[np.full(60, 2e5), np.full(25, 1e5), np.full(5, 1.3e5)],
                      "B": np.full(n, 1e5)}, index=d)
    return O, H, L, C, V


def test_score_today_caps_and_order():
    O, H, L, C, V = _bars()
    f = rv.raw_features(O, H, L, C, V, dates=[C.index[-1]])
    sc = rv.score_today(f, C.index[-1])
    for p, (_, mx) in rv.PARTS.items():
        assert (sc[p] <= mx + 1e-9).all() and (sc[p] >= 0).all()
    assert abs(sc.loc["A", "total"] - sc.loc["A", list(rv.PARTS)].sum()) < 1e-9
    assert sc.loc["A", "total"] > sc.loc["B", "total"]          # 바닥 전환형 > 고점에서 막 꺾인 종목
    assert sc.loc["A", "total"] != round(sc.loc["A", "total"])  # 소수점 점수


def test_updown_zero_down_volume_exception():
    f = {k: pd.Series([np.nan]) for k in ["D", "R20", "L", "RUN", "S20", "A20", "S60", "G20", "R5", "P",
                                          "ATRCHG", "VRATIO", "V5", "V20"]}
    f["UP_BAR"] = pd.Series([False])
    f["UPV"], f["DNV"] = pd.Series([5e5]), pd.Series([0.0])
    assert rv.score_frame(f)["updown"].iloc[0] == 1.0           # 하락일 거래량 0 → 2점이 아니라 중립 1점


def test_rank_tiebreak():
    sc = pd.DataFrame({"total": [75, 75, 75, 60], "ma35": [20, 25, 25, 30], "base25": [20, 10, 20, 20]},
                      index=["a", "b", "c", "d"])
    el = pd.Series(True, index=sc.index)
    out = rv.rank(sc, el, pd.Series({"a": 1, "b": 9, "c": 1, "d": 1}))
    assert list(out.index) == ["c", "b", "a"]                   # ③ → ② → 거래대금, 70점 미만 제외
