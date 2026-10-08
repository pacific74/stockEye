"""장중 재분석: 네이버 시세 해석 + 오늘 봉으로 V2 리포트 (네트워크 없이)."""
import pandas as pd

from stockeye.config import load_config
from stockeye.data.pit import PointInTimeData
from stockeye.data.sources import naver_live
from stockeye.data.sources.synthetic import generate
from stockeye.report import build_report_full

CFG = load_config()


def test_parse_item_sign_and_numbers():
    r = naver_live.parse_item({"itemCode": "005930", "closePrice": "71,200", "openPrice": "70,000",
                               "highPrice": "71,500", "lowPrice": "69,900", "fluctuationsRatio": "1.71",
                               "compareToPreviousPrice": {"code": "5", "name": "FALLING"},
                               "accumulatedTradingVolume": "1,000", "marketStatus": "OPEN",
                               "localTradedAt": "2026-10-08T11:00:03+09:00"})
    assert r["close"] == 71200 and r["chg_pct"] == -1.71 and r["volume"] == 1000 and r["value"] == 71200 * 1000
    assert r["traded_at"] == pd.Timestamp("2026-10-08 11:00:03")
    assert naver_live.parse_item({"itemCode": "X", "closePrice": "-"}) is None


def test_report_with_partial_today_bar():
    from scripts.intraday import today_bars
    g = generate(n_stocks=30, start="2023-01-02", end="2024-12-30", seed=4)
    pit = PointInTimeData(g["ohlcv"], g["flows"], g["fundamentals"], g["disclosures"], g["index"], g["listing"])
    last = pit.ohlcv["date"].max()
    today = last + pd.offsets.BDay(1)
    prev = pit.ohlcv[pit.ohlcv["date"] == last]
    live = pd.DataFrame({"code": prev["code"], "open": prev["close"], "high": prev["close"] * 1.02,
                         "low": prev["close"] * 0.99, "close": prev["close"] * 1.01, "volume": prev["volume"] * 0.4,
                         "value": prev["close"] * prev["volume"] * 0.4, "chg_pct": 1.0})
    bars = today_bars(pit, today, live)
    pit.ohlcv = pd.concat([pit.ohlcv, bars[pit.ohlcv.columns.intersection(bars.columns)]], ignore_index=True)
    rep, res, view = build_report_full(pit, CFG, today + pd.Timedelta(hours=18), with_ai=False)
    assert rep["date"] == str(today.date())
    c = rep["top10"][0] if rep["top10"] else None
    if c:
        code = c["code"]
        assert abs(c["plan"]["price"] - float(live.set_index("code").loc[code, "close"])) <= 1
