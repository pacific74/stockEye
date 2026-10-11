"""관심 탭 상위 · 보유종목의 최근 뉴스 → 종목 상세 '최근 뉴스' + 악재 경고 + (4개 탭) 점수 반영

  가져오기  탭마다 상위 TOP_PER_TAB 종목 + 보유종목, 최근 3일, 비슷한 제목 하나로 (data.naver_news)
  분류      제목 키워드 (engine.news 의 호재·악재 규칙 + 아래 '심각')
  점수      ⚠ 과거 뉴스로 검증할 수 없어(검색 API 는 최근 기사만) 작게, 나중에 실적으로 다시 정함
            · 심각 악재(횡령·배임·거래정지·상장폐지·감사의견·회생·부도·상장적격성) → 4개 탭 추천에서 제외
            · 일반 악재(유상증자·CB·소송 등) → 4개 탭 점수 -NEG_PENALTY
            · 호재 → 점수 변화 없음 (표시만)
            · V3 는 고정 규칙이라 점수·선정은 그대로, 경고 칩만
"""
from __future__ import annotations

import logging

from ..engine.news import NEGATIVE, classify

log = logging.getLogger(__name__)

TOP_PER_TAB = 15
SHOW = 5
NEG_PENALTY = 3.0
SEVERE = ["횡령", "배임", "거래정지", "상장폐지", "상장적격성", "감사의견", "회생", "부도"]
SCORED_TABS = ("nextday", "early", "reversal", "uplimit")


def _tone(title: str) -> int:
    """공시 키워드(engine.news) + 심각 단어 (상장폐지 등은 공시 규칙엔 없어서 여기서만 추가 — V3 점수엔 영향 없음)"""
    if any(k in title.replace(" ", "") for k in SEVERE):
        return -1
    return classify(title)


def judge(items: list[dict]) -> dict:
    neg = [it["title"] for it in items if _tone(it["title"]) < 0]
    pos = [it["title"] for it in items if _tone(it["title"]) > 0]
    severe = [t for t in neg if any(k in t.replace(" ", "") for k in SEVERE)]
    level = "severe" if severe else ("neg" if neg else ("pos" if pos else None))
    word = None
    if neg:
        t = (severe or neg)[0].replace(" ", "")
        word = next((k for k in SEVERE + NEGATIVE if k.replace(" ", "") in t), None)
    return {"items": items[:SHOW], "count": len(items), "level": level, "word": word,
            "neg": neg[:3], "pos": pos[:3]}


def annotate(report: dict, holdings: dict[str, str] | None = None, fetch=None) -> dict:
    """report 의 탭 후보에 c['news'] 를 붙이고 4개 탭 점수·순위를 조정. report['news_by_code'] 도 채움.
    holdings = {code: name}. fetch(name) -> [items] (기본: 네이버 API HUB)"""
    if fetch is None:
        from ..data import naver_news
        if not naver_news.enabled():
            log.info("뉴스: NAVER_HUB_ID/SECRET 없음 → 건너뜀")
            return {}
        fetch = naver_news.fetch
    strategies = report.get("strategies") or {}
    want: dict[str, str] = {}
    for k, v in strategies.items():
        for c in (v or {}).get("candidates", [])[:TOP_PER_TAB]:
            want.setdefault(c["code"], c.get("name") or c["code"])
    for code, name in (holdings or {}).items():
        want.setdefault(code, name)
    news = {}
    for code, name in want.items():
        items = fetch(name)
        news[code] = judge(items)
    log.info("뉴스: %d종목 · 악재 %d · 심각 %d", len(news), sum(v["level"] == "neg" for v in news.values()),
             sum(v["level"] == "severe" for v in news.values()))
    report["news_by_code"] = news
    for k, v in strategies.items():
        cands = (v or {}).get("candidates", [])
        for c in cands:
            if c["code"] in news:
                c["news"] = news[c["code"]]
        if k not in SCORED_TABS:
            continue
        keep, dropped = [], []
        for c in cands:
            n = c.get("news") or {}
            if n.get("level") == "severe":
                dropped.append({"code": c["code"], "name": c.get("name"), "word": n.get("word")})
                continue
            if n.get("level") == "neg":
                c["news_penalty"] = NEG_PENALTY
                if isinstance(c.get("score"), (int, float)):
                    c["score"] = round(c["score"] - NEG_PENALTY, 2)
                if isinstance(c.get(k), dict) and isinstance(c[k].get("score"), (int, float)):
                    c[k] = {**c[k], "score": round(c[k]["score"] - NEG_PENALTY, 2)}
            keep.append(c)
        keep.sort(key=lambda c: -(c.get("score") if isinstance(c.get("score"), (int, float)) else -1e9))
        for i, c in enumerate(keep, 1):
            c["rank"] = i
        v["candidates"] = keep
        if dropped:
            v["news_excluded"] = dropped
    return news
