"""시장 급변 알림 — 종합지수(코스피·코스닥)가 하루 등락 ±3% 이상이면 그때 나온 뉴스로 '어떤 이슈인지' 같이 알림 (관리자)

  단계    3% → 5% → 7% 로 더 벌어질 때마다 한 번씩 (같은 단계는 하루 한 번, 위·아래 방향 따로)
  뉴스    '<지수> 급락/급등' 검색 → 제목에 지수·증시가 들어간 최근 하루 기사 · 비슷한 제목 하나로
  키워드  제목에서 자주 나온 이슈 단어(환율·금리·미국·관세·전쟁·실적 …) 상위 3개 — 원인을 단정하는 게 아니라 '뉴스에서 많이 언급된 것'
  상태    system_status 'market_shock' {date, lv: {"KOSPI|-": 3}} — PC(22번 창)와 GitHub 가 같이 써도 중복 알림 없음
뉴스 키(NAVER_HUB_*)가 없으면 지수 수치만 보냄. 주문·매매와 무관.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

THRESH = 3.0
STEPS = (3.0, 5.0, 7.0)
NAME = {"KOSPI": "코스피", "KOSDAQ": "코스닥"}
ISSUES = {                                   # 이슈 이름 → 제목에 나오는 단어
    "미국·연준·금리": ["연준", "Fed", "FOMC", "금리", "기준금리", "파월", "국채"],
    "환율": ["환율", "원·달러", "원달러", "달러"],
    "관세·무역": ["관세", "무역", "트럼프", "수출 규제", "제재"],
    "전쟁·지정학": ["전쟁", "중동", "이스라엘", "이란", "러시아", "우크라이나", "북한", "미사일", "지정학"],
    "물가·경기": ["물가", "CPI", "고용", "경기침체", "침체", "소비"],
    "유가·원자재": ["유가", "원유", "WTI", "금값", "원자재"],
    "반도체·AI": ["반도체", "엔비디아", "삼성전자", "SK하이닉스", "AI", "HBM"],
    "외국인·기관 매매": ["외국인", "기관", "순매도", "순매수", "프로그램"],
    "정치·정책": ["정치", "탄핵", "대통령", "계엄", "정책", "세제", "공매도"],
    "실적": ["실적", "어닝", "영업이익"],
}


def level(chg: float | None) -> int:
    """등락률 → 알릴 단계(0 이면 알림 없음)"""
    if chg is None or chg != chg:
        return 0
    a = abs(float(chg))
    return int(max([s for s in STEPS if a >= s] or [0]))


def issue_tags(titles: list[str], top: int = 3) -> list[str]:
    cnt = {}
    for name, words in ISSUES.items():
        n = sum(any(w in t for w in words) for t in titles)
        if n:
            cnt[name] = n
    return [k for k, _ in sorted(cnt.items(), key=lambda kv: -kv[1])[:top]]


def news_for(code: str, down: bool, fetch=None) -> list[dict]:
    from ..data import naver_news
    fetch = fetch or naver_news.fetch_query
    name = NAME.get(code, code)
    words = (name, "증시", "코스피", "코스닥")
    out = []
    for q in (f"{name} {'급락' if down else '급등'}", f"증시 {'폭락' if down else '급등'} 이유"):
        out += fetch(q, days=1, must=words)
    out.sort(key=lambda x: x["time"], reverse=True)
    from ..data.naver_news import dedupe
    return dedupe(out)


def message(rows: list[dict], news: list[dict], now_hm: str) -> tuple[str, str]:
    """rows: 알릴 지수들 [{code, chg}] + 같은 시각 다른 지수는 body 에"""
    main = max(rows, key=lambda r: abs(r["chg"]))
    down = main["chg"] < 0
    title = f"🚨 {NAME.get(main['code'], main['code'])} {main['chg']:+.1f}% {'급락' if down else '급등'} ({now_hm})"
    lines = [" · ".join(f"{NAME.get(r['code'], r['code'])} {r['chg']:+.2f}%" for r in rows)]
    tags = issue_tags([n["title"] for n in news])
    if tags:
        lines.append("뉴스에서 많이 나온 이슈: " + " · ".join(tags))
    if news:
        lines.append("관련 기사")
        lines += [f"· {n['title'][:60]} ({n['time'][11:]})" for n in news[:3]]
    else:
        lines.append("관련 기사를 찾지 못했어요 (뉴스 키 없음 또는 아직 기사 전)")
    lines.append("※ 기사 제목을 모아 본 참고이며 원인을 확정하는 것이 아닙니다.")
    return title, "\n".join(lines)


def check(sb, topics: list[str], indices=None, send=None, fetch=None, now=None) -> list[str]:
    """한 번 확인 → 새 단계에 들어간 지수가 있으면 알림. 보낸 지수 코드 목록 반환"""
    import pandas as pd
    now = now or pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)
    day = now.strftime("%Y-%m-%d")
    if indices is None:
        from ..data.sources import naver_live
        indices = naver_live.indices()
    if indices is None or len(indices) == 0:
        return []
    cur = {}
    if sb:
        try:
            cur = (sb.select("system_status", {"select": "payload", "key": "eq.market_shock"}) or [{}])[0].get("payload") or {}
        except Exception as e:  # noqa: BLE001
            log.warning("시장 급변 상태 읽기 실패: %s", e)
    lv = dict(cur.get("lv") or {}) if cur.get("date") == day else {}
    hit = []
    for r in indices.to_dict("records"):
        code, chg = str(r.get("code")), r.get("chg_pct")
        L = level(chg)
        key = f"{code}|{'-' if (chg or 0) < 0 else '+'}"
        if L and L > int(lv.get(key, 0)):
            hit.append({"code": code, "chg": float(chg), "key": key, "lv": L})
    if not hit:
        return []
    main = max(hit, key=lambda h: abs(h["chg"]))
    news = news_for(main["code"], main["chg"] < 0, fetch)
    title, body = message([{"code": h["code"], "chg": h["chg"]} for h in hit] +
                          [{"code": str(r["code"]), "chg": float(r["chg_pct"])} for r in indices.to_dict("records")
                           if str(r["code"]) not in {h["code"] for h in hit} and r.get("chg_pct") == r.get("chg_pct")],
                          news, now.strftime("%H:%M"))
    if send is None:
        from ..trading.notify import Notifier
        nt = Notifier()
        send = lambda tp, t, b: nt.send_topic(tp, t, b, priority="urgent")  # noqa: E731
    ok = False
    for tp in topics:
        ok = bool(send(tp, title, body)) or ok
    print(f"   시장 급변 알림 {'보냄' if ok else '⚠ 못 보냄'} · {title}", flush=True)
    if ok or not topics:                                           # 보낸 단계만 기록 (못 보냈으면 다음 확인 때 다시)
        for h in hit:
            lv[h["key"]] = h["lv"]
        if sb:
            try:
                from ..cloud import publish as pub
                pub.publish_status(sb, "market_shock", {"date": day, "lv": lv, "last": title, "at": now.strftime("%H:%M")})
            except Exception as e:  # noqa: BLE001
                log.warning("시장 급변 상태 저장 실패: %s", e)
    return [h["code"] for h in hit] if ok else []
