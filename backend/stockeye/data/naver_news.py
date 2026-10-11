"""네이버 뉴스 검색 (NAVER API HUB · 네이버 클라우드) — 종목별 최근 뉴스

  주소   GET https://naverapihub.apigw.ntruss.com/search/v1/news?query=..&display=..&sort=date
  인증   헤더 X-NCP-APIGW-API-KEY-ID / X-NCP-APIGW-API-KEY ← 환경변수 NAVER_HUB_ID / NAVER_HUB_SECRET
         (GitHub Secrets 에만. 코드·앱·채팅에 넣지 않음). 없으면 조용히 건너뜀
  한도   하루 25,000회 (검색 API 공통) — 저녁 배치에서 관심 탭 상위·보유종목만 (하루 100회 안팎)
  정리   제목에 종목명이 들어간 것만 · 최근 days 일 · 같은/비슷한 제목은 하나만 (먼저 나온 최신 기사)
"""
from __future__ import annotations

import html
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime

log = logging.getLogger(__name__)

URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"
KST = timezone(timedelta(hours=9))
SIMILAR = 0.72          # 제목 유사도 이 이상이면 같은 기사로 봄


def enabled() -> bool:
    return bool(os.environ.get("NAVER_HUB_ID") and os.environ.get("NAVER_HUB_SECRET"))


def clean(s: str) -> str:
    """<b> 태그 · &quot; 같은 문자 정리"""
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def norm(title: str) -> str:
    """비교용 제목: [단독]·(종합)·괄호 머리말, 따옴표·기호·공백 제거"""
    t = re.sub(r"\[[^\]]*\]|【[^】]*】|\([^)]*\)", " ", title)
    t = re.sub(r"[\"'“”‘’…·,.!?~\-–—:;|/]", " ", t)
    return re.sub(r"\s+", "", t).lower()


def dedupe(items: list[dict]) -> list[dict]:
    """같거나 비슷한 제목은 하나만 (items 는 최신순 → 먼저 나온 것을 남김)"""
    out, keys = [], []
    for it in items:
        k = norm(it["title"])
        if not k:
            continue
        dup = any(k == q or (len(k) >= 8 and len(q) >= 8 and (k in q or q in k))
                  or SequenceMatcher(None, k, q).ratio() >= SIMILAR for q in keys)
        if dup:
            continue
        keys.append(k)
        out.append(it)
    return out


def parse(raw: dict, name: str, days: int = 3, now: datetime | None = None) -> list[dict]:
    """API 응답 → [{title, link, time, desc}] (종목명이 제목에 있고 최근 days 일, 최신순, 중복 제거)"""
    now = now or datetime.now(KST)
    since = now - timedelta(days=days)
    key = re.sub(r"\s+", "", name or "")
    out = []
    for it in raw.get("items") or []:
        title = clean(it.get("title", ""))
        if not title or (key and key not in re.sub(r"\s+", "", title)):
            continue
        try:
            t = parsedate_to_datetime(it.get("pubDate", "")).astimezone(KST)
        except Exception:  # noqa: BLE001
            continue
        if t < since:
            continue
        out.append({"title": title, "link": it.get("originallink") or it.get("link"),
                    "time": t.strftime("%Y-%m-%d %H:%M"), "desc": clean(it.get("description", ""))[:160]})
    out.sort(key=lambda x: x["time"], reverse=True)
    return dedupe(out)


def fetch(name: str, days: int = 3, display: int = 50, session=None, timeout: float = 8.0) -> list[dict]:
    """종목명으로 최근 뉴스 (실패하면 빈 목록)"""
    if not enabled() or not name:
        return []
    import requests
    s = session or requests
    try:
        r = s.get(URL, params={"query": f'"{name}"', "display": display, "sort": "date"}, timeout=timeout,
                  headers={"X-NCP-APIGW-API-KEY-ID": os.environ["NAVER_HUB_ID"],
                           "X-NCP-APIGW-API-KEY": os.environ["NAVER_HUB_SECRET"]})
        if r.status_code != 200:
            log.warning("뉴스 %s: HTTP %s %s", name, r.status_code, r.text[:120])
            return []
        return parse(r.json(), name, days)
    except Exception as e:  # noqa: BLE001
        log.warning("뉴스 %s 실패: %s", name, e)
        return []
