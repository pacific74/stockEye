import pandas as pd

from stockeye.analysis import stock_fin as sf


def _fin():
    r = lambda code, y, rp, rev, op, fs="CFS": {"code": code, "year": y, "reprt": rp, "fs": fs, "revenue": rev, "op_income": op}  # noqa: E731
    return pd.DataFrame([
        r("000010", 2024, "FY", 1.0e12, 5.0e10), r("000010", 2025, "FY", 2.1e12, 1.234e11),
        r("000010", 2025, "FY", 9.9e12, 9.9e11, fs="OFS"),                     # 별도는 연결에 밀림
        r("000010", 2026, "Q3", 1.8e12, -2.0e10),                                  # 더 새로운 분기 누적
        r("000020", 2025, "FY", 3.0e11, 1.0e10), r("000020", 2025, "Q3", 2.0e11, 8.0e9),   # 분기가 연간보다 오래됨 → ② 없음
        r("000030", 2026, "H1", 5.0e10, 1.0e9),                                    # 연간 없음, 분기만
    ])


def test_fin_rows_latest_fy_and_newer_quarter():
    rows = sf.fin_rows(_fin())
    assert rows["000010"] == [21000, 1234, "2025 연간", 18000, -200, "2026 3분기 누적"]
    assert rows["000020"] == [3000, 100, "2025 연간", None, None, None]
    assert rows["000030"] == [None, None, None, 500, 10, "2026 반기 누적"]
    assert sf.fin_rows(None) == {} and sf.fin_rows(pd.DataFrame()) == {}


def test_build_adds_foreign_ratio_even_without_financials():
    rows = sf.build(_fin(), {"000010": 12.34, "999999": 5.5})
    assert rows["000010"][-1] == 12.34 and len(rows["000010"]) == 7
    assert rows["999999"] == [None] * 6 + [5.5]
    assert sf.build(_fin(), {})["000020"][-1] is None


def test_foreign_ratio_failure_is_silent(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "pykrx", None)                           # import 실패
    assert sf.foreign_ratio("2026-10-28") == {}
