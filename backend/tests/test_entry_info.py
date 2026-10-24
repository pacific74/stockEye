"""매매일지 매수 당시 정보: 리포트 날짜 고르기 · 후보 탭/점수/상태 · 매수구간 위치"""
from stockeye.cloud.entry_info import build, report_for


def test_report_for():
    dates = ["2026-10-06", "2026-10-07", "2026-10-08"]
    assert report_for("2026-10-08 10:52:00", dates) == "2026-10-07"    # 장중 매수 → 전날 저녁 리포트
    assert report_for("2026-10-08 19:00:00", dates) == "2026-10-08"
    assert report_for("2026-10-08", dates) == "2026-10-07"             # 날짜만 입력


def test_build():
    rep = {"date": "2026-10-07", "market": {"mood": "약세"}, "strategies": {
        "v3": {"short": "V3", "candidates": [{"code": "A", "score": 70}, {"code": "B", "score": 86.4,
               "plan": {"verdict": "V3 선정 2위", "entry_low": 100, "entry_high": 110, "stop": 90}}]},
        "nextday": {"short": "유망주", "candidates": [{"code": "B", "score": 74.2, "nextday": {"label": "B 관심 후보"}}]}}}
    i = build(rep, "B", 105)
    assert [t["label"] for t in i["tabs"]] == ["V3", "유망주"] and i["tabs"][0]["rank"] == 2
    assert "V3 2위 86점(V3 선정 2위)" in i["summary"] and "유망주 1위 74점(B 관심 후보)" in i["summary"]
    assert "매수구간 안" in i["summary"] and "시장 약세" in i["summary"]
    assert build(rep, "Z", 1)["summary"].startswith("그날 후보 목록에 없던 종목")


def test_comments():
    rep = {"date": "2026-10-07", "market": {"mood": "약세"}, "sectors": [{"group": "반도체", "ret1_pct": -2.5}],
           "sector_members": {"groups": {"반도체": [["B", "x"]]}},
           "strategies": {"v3": {"short": "V3", "candidates": [
               {"code": "B", "score": 80, "reasons": ["거래량 급증", "20일선 돌파"], "warnings": ["단기 과열"],
                "market_alert": "종합지수 급락 · 매수 주의"}]}}}
    i = build(rep, "B", 105)
    assert i["comments"] == [{"tab": "V3", "why": ["거래량 급증", "20일선 돌파"], "warn": ["단기 과열", "종합지수 급락 · 매수 주의"]}]
    assert i["sector"] == "반도체 -2.5%"
    assert build(rep, "Z", 1)["comments"] == []


def test_needs_backfill():
    from stockeye.cloud.entry_info import _needs
    assert _needs({"plan": None})
    assert _needs({"plan": {"entry_info": {"summary": "x"}}})
    assert not _needs({"plan": {"entry_info": {"summary": "x", "comments": []}}})
