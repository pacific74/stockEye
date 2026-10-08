"""종목 상세(차트 이평선 · 비슷한 패턴 봉) 생성 점검."""
import json

import pandas as pd

from stockeye.cloud.client import _dumps, clean
from stockeye.config import load_config
from stockeye.data.pit import PointInTimeData
from stockeye.data.sources.synthetic import generate
from stockeye.details import build_details
from stockeye.report import build_report_full

CFG = load_config()


def test_details_chart_has_moving_averages():
    g = generate(n_stocks=40, start="2022-01-03", end="2024-12-30", seed=5)
    pit = PointInTimeData(g["ohlcv"], g["flows"], g["fundamentals"], g["disclosures"], g["index"], g["listing"])
    report, res, view = build_report_full(pit, CFG, None)
    rows = build_details(pit, CFG, report, res, view)
    assert rows
    r = next(r for r in rows if len(r["chart"]) == 120)
    bars = r["chart"]
    # 120일 차트의 첫 봉부터 120일선까지 채워져 있어야 (앞 119일을 더 읽어 계산)
    assert all(b[f"ma{n}"] is not None for b in bars for n in (5, 20, 60, 120))
    oh = g["ohlcv"][g["ohlcv"]["code"] == r["code"]].sort_values("date")
    oh = oh[oh["date"] <= pd.Timestamp(bars[-1]["date"])]
    assert abs(bars[-1]["ma20"] - oh["close"].tail(20).mean()) < 0.11
    assert abs(bars[-1]["ma120"] - oh["close"].tail(120).mean()) < 0.11
    # 비슷한 패턴 봉에도 이평선
    sims = [r["similar_patterns"] for r in rows if r["similar_patterns"] and "matches" in r["similar_patterns"]]
    assert sims
    mb = [m for s in sims for m in s["matches"] if m.get("bars")]
    assert mb and all("ma60" in b for b in mb[0]["bars"])
    json.loads(_dumps(clean(rows[:5])))  # JSON 으로 올릴 수 있어야
