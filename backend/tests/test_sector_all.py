"""업종 등락: 전체 종목 · 시가총액 가중 (거래 폭발 급등주 몇 개가 업종을 끌어올리지 않게)"""
import numpy as np
import pandas as pd

from stockeye.analysis.market import group_members, group_returns, group_strength


def _x():
    codes = [f"{i:06d}" for i in range(10)]
    ret = [0.30] + [0.0] * 9                                    # 1개만 상한가, 나머지 보합
    value = [500e8] + [2e8] * 9                                  # 급등주에 거래대금 몰림 · 나머지는 거래대금 5억 미만
    return pd.DataFrame({"ret1": ret, "value": value, "value_ma20": [3e8] * 10, "volume": [1e5] * 10,
                         "ret5": [0.01] * 10, "close": [1000] * 10, "high20_prev": [1100] * 10}, index=codes)


def test_all_members_cap_weighted():
    x = _x()
    codes = list(x.index)
    caps = {c: (100e8 if c == "000000" else 900e8) for c in codes}   # 급등주는 작은 회사
    r = group_returns(x, codes, caps)
    assert r["n"] == 10 and r["basis"] == "cap" and r["up"] == 1 and r["down"] == 0
    assert abs(r["ret1"] - 0.30 * 100 / (100 + 900 * 9)) < 1e-9          # 시총 가중 ≈ +0.37%
    assert abs(r["ret1_eq"] - 0.03) < 1e-9                               # 단순 평균 +3%
    assert group_returns(x, codes, {})["basis"] == "eq"                  # 시가총액 없으면 단순 평균
    out = group_strength(x, {"비금속": {"type": "sector", "codes": codes}}, marcap=caps)
    g = out[0]
    assert g["members"] == 10 and g["ret1_pct"] < 1 and g["ret1_eq_pct"] == 3.0 and len(g["live"]) == 10
    assert abs(sum(m["w"] for m in g["live"]) - 1) < 1e-3
    mem = group_members(x, {"비금속": {"type": "sector", "codes": codes}}, None, caps)["비금속"]
    assert len(mem) == 10 and mem[0][0] == "000000" and mem[0][2] == 30.0 and mem[0][4] == 100
