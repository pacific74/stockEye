"""DART 재무·공시 백필 (네트워크 없이 가짜 응답으로)."""
import pandas as pd

from stockeye.data.sources.dart_fin import parse_multi, _match
from stockeye.data.store import DataStore


def _it(code, fs, acc, amt, add=None, rn="20240515000123"):
    return {"stock_code": code, "fs_div": fs, "account_nm": acc, "thstrm_amount": amt,
            "thstrm_add_amount": add, "rcept_no": rn}


def test_parse_multi_prefers_cfs_and_cumulative():
    items = [
        _it("005930", "OFS", "매출액", "1,000", "2,000"),
        _it("005930", "CFS", "매출액", "3,000", "6,000"),
        _it("005930", "CFS", "영업이익", "500", "900"),
        _it("005930", "CFS", "당기순이익(손실)", "-", "700"),
        _it("005930", "CFS", "자산총계", "10,000"),
        _it("005930", "CFS", "부채총계", "4,000"),
        _it("005930", "CFS", "자본총계", "6,000"),
        _it("005930", "CFS", "매출원가", "999"),
        _it("000660", "OFS", "매출액", "50", None, rn="20240514000001"),
    ]
    rows = {r["code"]: r for r in parse_multi(items, 2024, "11012")}
    s = rows["005930"]
    assert s["fs"] == "CFS" and s["revenue"] == 6000 and s["op_income"] == 900 and s["net_income"] == 700
    assert s["assets"] == 10000 and s["liabilities"] == 4000 and s["reprt"] == "H1"
    assert s["date"] == pd.Timestamp("2024-05-15 23:59")
    assert rows["000660"]["revenue"] == 50 and rows["000660"]["fs"] == "OFS"
    assert _match("매출원가") is None and _match("매출총이익") is None


def test_backfill_resume(tmp_path, monkeypatch):
    from scripts import dart_backfill as bf
    from stockeye.data.sources import dart_fin
    store = DataStore(tmp_path)
    store.save("ohlcv", pd.DataFrame({"date": pd.to_datetime(["2024-01-02"] * 2), "code": ["005930", "000660"],
                                      "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0, "value": 1.0}))
    calls = []

    class Fake(dart_fin.DartFinancials):
        def corp_codes(self):
            return {"005930": "00126380", "000660": "00164779"}

        def _multi(self, corp_codes, year, reprt_code):
            calls.append((year, reprt_code))
            self.calls += 1
            return [{"code": c, "fs": "CFS", "year": year, "reprt": dart_fin.REPRT[reprt_code], "revenue": 1.0,
                     "date": pd.Timestamp(f"{year}-06-01")} for c in ("005930", "000660")]

    monkeypatch.setattr(dart_fin, "DartFinancials", Fake)
    monkeypatch.setenv("DART_API_KEY", "x")
    assert bf.backfill_financials(store, [2023, 2024])
    f = store.load("financials")
    assert len(f) == 2 * 2 * 4 and set(f["reprt"]) == {"Q1", "H1", "Q3", "FY"}
    assert len(calls) == 8
