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


def test_company_profile(monkeypatch):
    from stockeye.data import company as co

    html = ("<table><tr><th>회사명</th><th>시장구분</th><th>종목코드</th><th>업종</th><th>주요제품</th>"
            "<th>상장일</th><th>결산월</th><th>대표자명</th><th>홈페이지</th><th>지역</th></tr>"
            "<tr><td>테스트전자</td><td>유가</td><td>100000</td><td>반도체 제조업</td><td>메모리, 파운드리</td>"
            "<td>2001-01-02</td><td>12월</td><td>홍길동</td><td>http://t.co</td><td>경기도</td></tr></table>")

    class R:
        content = html.encode("euc-kr")

        def raise_for_status(self):
            pass

    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    monkeypatch.setattr(co, "fetch_shares", lambda d: {"100000": 1_000_000})
    meta = co.fetch_company_meta("2024-12-30")
    assert meta["rows"]["100000"]["products"] == "메모리, 파운드리"
    assert not co.is_stale(meta)

    g = generate(n_stocks=10, start="2023-01-02", end="2024-12-30", seed=1)
    pit = PointInTimeData(g["ohlcv"], g["flows"], g["fundamentals"], g["disclosures"], g["index"], g["listing"])
    report, res, view = build_report_full(pit, CFG, None)
    rows = build_details(pit, CFG, report, res, view, similar=False, company=meta)
    r = next(r for r in rows if r["code"] == "100000")
    p = r["candidate"]["profile"]
    assert p["industry"] == "반도체 제조업" and p["ceo"] == "홍길동"
    assert p["market_cap"] == int(1_000_000 * r["chart"][-1]["close"])
    json.loads(_dumps(clean(r)))
