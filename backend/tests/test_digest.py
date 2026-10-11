"""저녁 리포트 알림: 구성(브리핑·예상·탭별 3종목) · 길이 제한"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from stockeye.cloud import digest


def _report(n_tabs=4, per=3):
    cand = lambda i: {"code": f"{i:06d}", "name": f"종목{i}", "score": 80 - i,  # noqa: E731
                      "plan": {"price": 10000, "target1": 10800, "stop": 9500}}
    st = {k: {"short": k, "candidates": [cand(i) for i in range(per)]} for k in ["reversal", "v3", "early", "nextday"][:n_tabs]}
    d = pd.bdate_range("2026-06-01", periods=80)
    ix = pd.DataFrame({"date": list(d) * 2, "code": ["KOSPI"] * 80 + ["KOSDAQ"] * 80,
                       "close": list(np.linspace(3000, 3300, 80)) + list(np.linspace(900, 850, 80))})
    return {"date": "2026-10-09", "market": {"advancers": 900, "decliners": 1500, "breadth_pct": 37.5,
                                             "above_sma20_pct": 45.0, "mood": "약세", "mood_icon": "🔴"},
            "sectors": [{"group": "반도체", "ret1_pct": 2.1}], "strategies": st,
            "brief": digest.market_brief(ix), "nextday": {"grades": {"A": 2, "B": 10}}}


def test_sections_and_order():
    t, b = digest.build(_report())
    assert t.startswith("📊 10/9(금) 장마감 리포트")
    for h in ("■ 금일장 브리핑", "■ 내일장 예상", "■ 내일 관심주"):
        assert h in b
    order = [b.index(f"**[{k}]**") for k in ("V3", "익일유망주", "상승초기", "추세전환")]   # 앱 탭 순서
    assert order == sorted(order)
    nb = "\u00a0" * 4
    assert f"**[V3]**  \n1\\. **종목0** (000000) · 80점  \n{nb}현 10,000 · 목 10,800 · 손 9,500  \n2\\." in b
    assert "\n\n**[익일유망주]**" in b                                   # 탭 사이 한 줄 띄움
    assert "### ■ 내일 관심주" in b and "- **코스피** 3,300.00" in b and "20일선 위" in b


def test_plain_strips_markdown():
    t, b = digest.build(_report())
    p = digest.plain(b)
    assert "**" not in p and "### " not in p and "  \n" not in p
    assert "[V3]\n1. 종목0 (000000) · 80점\n    현 10,000" in p


def test_byte_limit_trims_per_tab():
    r = _report()
    r["strategies"].update({f"tab{i}": {"short": f"새탭{i}", "candidates": r["strategies"]["v3"]["candidates"]}
                            for i in range(30)})
    t, b = digest.build(r)
    assert len(b.encode("utf-8")) <= digest.MAX_BYTES
    assert "**[새탭0]**" in b                                       # 새 탭도 자동 포함


def test_drop_alert_in_digest():
    from stockeye.analysis.market_alert import annotate
    r = _report()
    r["market"]["indices"] = [{"code": "KOSDAQ", "change_pct": -3.4}, {"code": "KOSPI", "change_pct": -1.0}]
    r["sectors"] = [{"group": "반도체", "ret1_pct": -4.2}, {"group": "은행", "ret1_pct": 0.5}]
    c = r["strategies"]["v3"]["candidates"][0]
    c.update({"market": "KOSPI", "sector": "반도체"})
    r["strategies"]["v3"]["candidates"][1]["market"] = "KOSDAQ"
    annotate(r)
    assert c["market_alert"] == "업종 급락 (반도체 -4.2%) · 매수 주의"
    assert r["strategies"]["v3"]["candidates"][1]["market_alert"].startswith("종합지수 급락 (코스닥 -3.4%)")
    assert "market_alert" not in r["strategies"]["v3"]["candidates"][2]
    t, b = digest.build(r)
    assert "⚠ **종합지수 급락 · 매수 주의**" in b and "코스닥 -3.4% · 반도체 -4.2%" in b
    assert "⚠ 업종 급락 (반도체 -4.2%) · 매수 주의" in b
