import numpy as np
import pandas as pd

from stockeye.analysis.score_power import forward_returns, bucket_table, default_bins, monotonic, report, to_markdown


def _ohlcv():
    dates = pd.bdate_range("2024-01-01", periods=80)
    rows = []
    for code, g in (("A", 0.01), ("B", -0.005), ("C", 0.0)):
        px = 1000 * (1 + g) ** np.arange(80)
        for d, p in zip(dates, px):
            rows.append({"date": d, "code": code, "low": p * 0.99, "close": p})
    return pd.DataFrame(rows)


def test_forward_and_buckets():
    f = forward_returns(_ohlcv())
    a = f[(f.code == "A")].iloc[0]
    assert abs(a.r5 - (1.01 ** 5 - 1)) < 1e-9 and abs(a.r20 - (1.01 ** 20 - 1)) < 1e-9
    b = f[(f.code == "B")].iloc[0]
    assert b.dd5 < 0 and b.r40 < 0                        # 하락 종목: 최대 손실 음수
    score = {"A": 90, "B": 10, "C": 50}
    f["score"] = f.code.map(score)
    t = bucket_table(f, "score", [0, 40, 80, 101])
    assert list(t.index) == ["0~40", "40~80", "80~"]
    assert t.loc["80~", "20일 승률"] == 100 and t.loc["0~40", "20일 승률"] == 0
    m = t.loc["80~", "20일 평균"] / 100
    assert abs(t.loc["80~", "20일 일평균(복리)"] - ((1 + m) ** (1 / 20) - 1) * 100) < 0.01   # 복리 일평균 ≈ 1%
    assert monotonic(t, 20) == 1.0
    md = to_markdown(report(f, {"score": default_bins(100, 4)}), "시험")
    assert "20일 평균" in md and "| 구간 |" in md


def test_jump_excluded():
    df = _ohlcv()
    df.loc[(df.code == "C") & (df.date == df.date.unique()[30]), "close"] *= 2   # 하루 +100% (분할 등)
    f = forward_returns(df)
    d0 = df.date.unique()
    row = f[(f.code == "C") & (f.date == d0[25])]
    assert row.empty or pd.isna(row.iloc[0].r10)          # 불연속이 낀 구간은 제외
