"""관심 탭 상위 · 보유종목의 최근 뉴스 → 종목 상세 '최근 뉴스' + 악재 경고 + 탭 점수의 뉴스 5점 반영

  가져오기  탭마다 상위 TOP_PER_TAB 종목 + 보유종목, 최근 3일, 비슷한 제목 하나로 (data.naver_news)
  분류      제목 키워드 (engine.news 의 호재·악재 규칙 + 아래 '심각')
  점수      탭마다 뉴스 5점 (2026-10-12): 호재 5 · 중립/기사 없음 2.5 · 악재 0
              V3 = 뉴스 5 (공시 10 과 별도) · 익일 = 재료·위험 15 안 · 상승초기 = 과열·변동성·뉴스 15 안
              추세전환 = 뉴스 5 · 상파 = 공시·뉴스 10 안
            점수 계산 때는 모두 중립 2.5 → 여기서 뉴스를 가져온 종목만 (점수 - 2.5) 만큼 조정하고 순위를 다시 매김
            심각 악재(횡령·배임·거래정지·상장폐지·감사의견·회생·부도·상장적격성) → 4개 탭 추천에서 제외 (V3 는 0점만)
            ⚠ 과거 뉴스는 없어 백테스트·적중률에서는 모두 중립 — 실제 효과는 쌓이는 기록으로 다시 확인
"""
from __future__ import annotations

import logging

from ..engine.news import NEGATIVE, classify

log = logging.getLogger(__name__)

TOP_PER_TAB = 15
SHOW = 5
NEWS_MAX, NEWS_NEUTRAL = 5.0, 2.5
NEWS_PTS = {"pos": 5.0, None: 2.5, "neg": 0.0, "severe": 0.0}
NEWS_PART = {"v3": "news5", "nextday": "newsF", "early": "risk15", "reversal": "news5", "uplimit": "risk10"}
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
        part = NEWS_PART.get(k)
        keep, dropped = [], []
        for c in cands:
            n = news.get(c["code"])
            if n is None:
                keep.append(c)
                continue
            c["news"] = n
            if k in SCORED_TABS and n.get("level") == "severe":
                dropped.append({"code": c["code"], "name": c.get("name"), "word": n.get("word")})
                continue
            delta = NEWS_PTS.get(n.get("level"), NEWS_NEUTRAL) - NEWS_NEUTRAL
            if part and delta:
                c["news_delta"] = delta
                if isinstance(c.get("score"), (int, float)):
                    c["score"] = round(c["score"] + delta, 2)
                sub = c.get(k)
                if isinstance(sub, dict):
                    sub = {**sub}
                    if isinstance(sub.get("score"), (int, float)):
                        sub["score"] = round(sub["score"] + delta, 2)
                    if isinstance(sub.get("parts"), dict) and isinstance(sub["parts"].get(part), (int, float)):
                        sub["parts"] = {**sub["parts"], part: round(sub["parts"][part] + delta, 2)}
                    c[k] = sub
            keep.append(c)
        if part:
            keep.sort(key=lambda c: -(c.get("score") if isinstance(c.get("score"), (int, float)) else -1e9))
            for i, c in enumerate(keep, 1):
                c["rank"] = i
        cands[:] = keep                                       # 같은 목록 객체 유지 (report top10 등이 같이 바뀜)
        if dropped:
            v["news_excluded"] = dropped
    return news
