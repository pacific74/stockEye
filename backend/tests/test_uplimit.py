"""상파: 상한가 가격 · 유형 A/B · B1~B4 · 점수 상한"""
import numpy as np
import pandas as pd

from stockeye.engine import uplimit as ul


def test_limit_price_tick():
    assert ul.limit_price(10000) == 13000
    assert ul.limit_price(1543) == 2005            # 2,005.9 → 2,000원 이상 호가 5원 → 2,005
    assert ul.limit_price(48000) == 62400          # 62,400 (호가 100원)


def _wide():
    d = pd.bdate_range("2026-08-03", periods=30)
    c = np.full(30, 10000.0)
    c[-2] = 13000.0                                # 어제 상한가
    c[-1] = 12600.0
    o = c.copy(); o[-1] = 12900.0                  # 오늘 음봉
    h = c * 1.01; h[-2] = 13000.0
    l = c * 0.99; l[-2] = 11000.0; l[-1] = 12400.0
    v = np.full(30, 1e5); v[-2] = 2e6; v[-1] = 1.2e6   # 거래량 감소 40%
    mk = lambda a: pd.DataFrame({"X": a}, index=d)  # noqa: E731
    return mk(o), mk(h), mk(l), mk(c), mk(v)


def test_type_b1():
    O, H, L, C, V = _wide()
    f = ul.features(O, H, L, C, V, C * V, dates=[C.index[-1]])
    r = {k: v.iloc[0]["X"] for k, v in f.items()}
    assert r["TYPE_B"] and r["PREV_CLOSE_LIMIT"] and abs(r["VDROP"] - 40) < 1e-6
    t, tags = ul.classify(r)
    assert t == "B" and tags[0].startswith("B1")
    s = ul.score_row(r, 7.0, True)
    for k, (_, mx) in ul.PARTS.items():
        assert 0 <= s[k] <= mx
    f2 = ul.features(O, H, L, C, V, C * V, dates=[C.index[-2]])
    r2 = {k: v.iloc[0]["X"] for k, v in f2.items()}
    assert ul.classify(r2)[0] == "A-종가"
