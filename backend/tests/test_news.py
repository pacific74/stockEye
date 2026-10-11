"""네이버 뉴스: 정리·중복 제거·악재 분류·탭 점수 반영"""
from datetime import datetime

from stockeye.analysis import news_flags as nf
from stockeye.data import naver_news as nn

NOW = datetime(2026, 10, 12, 18, 0, tzinfo=nn.KST)


def _it(title, day=12, hh=9):
    return {"title": title, "originallink": "https://a", "link": "https://n", "description": "<b>x</b>",
            "pubDate": f"Mon, {day:02d} Oct 2026 {hh:02d}:00:00 +0900"}


def test_parse_filters_and_dedupes():
    raw = {"items": [
        _it("<b>삼성전자</b>, 3분기 영업이익 10조 돌파", hh=10),
        _it("[단독] 삼성전자 3분기 영업이익 10조 돌파", hh=9),            # 머리말만 다름 → 중복
        _it("삼성전자, 3분기 영업익 10조 돌파…시장 기대 웃돌아", hh=8),    # 비슷한 제목 → 중복
        _it("SK하이닉스 HBM 공급 확대", hh=11),                           # 종목명 없음 → 제외
        _it("삼성전자 노조 파업 예고", day=5),                             # 3일 지남 → 제외
        _it("삼성 전자 &quot;미국 공장&quot; 투자 확대", hh=7),             # 띄어쓰기 달라도 종목명 인정
    ]}
    got = nn.parse(raw, "삼성전자", days=3, now=NOW)
    assert [g["title"] for g in got] == ["삼성전자, 3분기 영업이익 10조 돌파", '삼성 전자 "미국 공장" 투자 확대']
    assert got[0]["time"] == "2026-10-12 10:00"


def test_annotate_scores_and_excludes():
    rep = {"strategies": {
        "nextday": {"candidates": [
            {"code": "A", "name": "가", "score": 70.0, "rank": 1, "nextday": {"score": 70.0}},
            {"code": "B", "name": "나", "score": 68.0, "rank": 2, "nextday": {"score": 68.0}},
            {"code": "C", "name": "다", "score": 66.0, "rank": 3, "nextday": {"score": 66.0}}]},
        "v3": {"candidates": [{"code": "A", "name": "가", "score": 80, "rank": 1}]}}}
    titles = {"가": ["가, 유상증자 결정"], "나": ["나 대표 횡령 혐의"], "다": ["다, 대규모 수주"]}
    nf.annotate(rep, {"H": "보유"}, fetch=lambda name: [{"title": t, "time": "", "link": ""} for t in titles.get(name, [])])
    nd = rep["strategies"]["nextday"]["candidates"]
    assert [c["code"] for c in nd] == ["A", "C"] and nd[0]["score"] == 67.0 and nd[0]["nextday"]["score"] == 67.0
    assert nd[1]["rank"] == 2 and rep["strategies"]["nextday"]["news_excluded"][0]["word"] == "횡령"
    assert rep["strategies"]["v3"]["candidates"][0]["score"] == 80                  # V3 점수는 그대로
    assert rep["strategies"]["v3"]["candidates"][0]["news"]["level"] == "neg"       # 경고만
    assert "H" in rep["news_by_code"]
