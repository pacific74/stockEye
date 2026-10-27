"""시장 급변 알림 — 종합지수(코스피·코스닥)가 하루 등락 ±3% 이상이면 그때 나온 뉴스로 '어떤 이슈인지' 같이 알림 (관리자 + 알림 토픽을 등록하고 '일일 리포트 알림'을 켠 승인 회원)

  단계    3% → 5% → 7% 로 더 벌어질 때마다 한 번씩 (같은 단계는 하루 한 번, 위·아래 방향 따로)
  뉴스    '<지수> 급락/급등' 검색 → 제목에 지수·증시가 들어간 최근 하루 기사 · 비슷한 제목 하나로
  키워드  제목에서 자주 나온 이슈 단어(환율·금리·미국·관세·전쟁·실적 …) 상위 3개 — 원인을 단정하는 게 아니라 '뉴스에서 많이 언급된 것'
  상태    system_status 'market_shock' {date, lv: {"KOSPI|-": 3}} — PC(22번 창)와 GitHub 가 같이 써도 중복 알림 없음
뉴스 키(NAVER_HUB_*)가 없으면 지수 수치만 보냄. 주문·매매와 무관.
"""
from __future__ import annotations

import logging
import re

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
    "반도체·AI": ["반도체", "엔비디아", "삼성전자", "SK하이닉스", "AI", "HBM", "앤트로픽", "엔트로픽", "Anthropic"],
    "외국인·기관 매매": ["외국인", "기관", "순매도", "순매수", "프로그램"],
    "정치·정책": ["정치", "탄핵", "대통령", "계엄", "정책", "세제", "공매도"],
    "실적": ["실적", "어닝", "영업이익"],
    "돌발 사건·소문": ["사망", "사망설", "건강이상", "쿠데타", "테러", "폭발", "핵", "도발", "공습", "피격", "화재", "붕괴", "파산", "디폴트"],
}
PRICE_ONLY = ("마감", "장중", "종가", "시황", "지수", "급락", "폭락", "하락", "약세", "내림세", "하락세", "급등", "상승", "강세")
CAUSE_Q = ("속보", "긴급", "충격", "원인 배경", "왜 떨어")        # 가격 얘기 말고 '무슨 일이 있었나' 기사를 찾는 검색어


STOP = set("코스피 코스닥 증시 지수 주가 시장 오늘 장중 마감 개장 상승 하락 급등 급락 폭락 폭등 이유 배경 속보 긴급 충격 원인 서울 한국 국내 투자자 전망 영향 대비 이상 이하 이번 지난 최대 최고 최저 사상 기록 돌파 안팎 이후 이전 관련 기대 우려 발표 공개 정부 시장에서 종목 업종 거래 거래일 외국인 기관 개인 순매수 순매도 매수 매도 전일 전날 하루".split())


def hot_terms(titles: list[str], top: int = 2, min_docs: int = 2) -> list[str]:
    """그날 기사 제목들에서 서로 다른 제목 2개 이상에 반복해 나오는 고유 단어 (예: 앤트로픽, 엔비디아) — 미리 정해 둔 주제 없이 '오늘의 이슈'를 따라감"""
    cnt: dict[str, int] = {}
    for t in titles:
        seen = set()
        for w in re.findall(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9]{2,}", t):
            w = re.sub(r"(은|는|이|가|을|를|의|에|도|만|과|와|로|으로|에서|발)$", "", w) if re.fullmatch(r"[가-힣]{3,}", w) else w
            if len(w) < 2 or w in STOP or w.isdigit():
                continue
            seen.add(w)
        for w in seen:
            cnt[w] = cnt.get(w, 0) + 1
    return [w for w, n in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0])) if n >= min_docs][:top]



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


def is_price_only(title: str) -> bool:
    """'코스피 3% 급락 마감' 처럼 오른 내렸다만 말하고 이유가 없는 제목 (이슈 단어가 하나도 없으면)"""
    has_issue = any(w in title for ws in ISSUES.values() for w in ws)
    return (not has_issue) and any(w in title for w in PRICE_ONLY)


CAUSE_WORDS = ("이유", "배경", "때문", "영향", "호재", "악재", "촉발", "덕분", "힘입", "기대", "우려", "발표", "공개", "수혜", "여파", "계기", "급등한", "뛴", "쏠린")
SHOW_N = 5                                                    # 알림에 싣는 기사 수 (2026-10-27: 3→5, 원인 기사 위주)


def cause_score(title: str) -> int:
    """높을수록 '왜 움직였나'에 가까운 제목: 원인 표현 +2 · 이슈 단어 +1 · 숫자만 전하는 시황 -3"""
    sc = 2 if any(w in title for w in CAUSE_WORDS) else 0
    if any(w in title for ws in ISSUES.values() for w in ws):
        sc += 1
    if is_price_only(title):
        sc -= 3
    return sc


def news_for(code: str, down: bool, fetch=None) -> list[dict]:
    """'지수가 몇 % 올랐다' 기사보다 '왜 움직였나' 기사를 앞에.
    1) 지수 급등락·이유 검색 + 속보류  2) 거기서 많이 나온 이슈로 '<이슈> 급등/급락 이유' 재검색 (오늘 같은 날 반도체·AI 이슈가 잡힘)
    3) 그날 기사 제목에 반복해 나온 단어(hot_terms)로 재검색 → 원인 점수(cause_score) 순, 같으면 최신순"""
    from ..data import naver_news
    fetch = fetch or naver_news.fetch_query
    name = NAME.get(code, code)
    up_dn = "급락" if down else "급등"
    words = (name, "증시", "코스피", "코스닥", "주가", "시장")
    out = []
    for q in (f"{name} {up_dn}", f"증시 {'폭락' if down else '급등'} 이유", f"증시 {'하락' if down else '상승'} 배경"):
        out += fetch(q, days=1, must=words)
    for q in CAUSE_Q:                                              # 시장 단어 없이도 큰 사건 기사 (예: 속보 사망설)
        out += fetch(f"{q} {'증시 하락' if down else '증시 상승'}", days=1, must=())
    for tag in issue_tags([x["title"] for x in out], top=2):       # 많이 나온 이슈로 원인 재검색
        kw = ISSUES[tag][0] if tag != "반도체·AI" else "반도체"
        out += fetch(f"{kw} {up_dn} 이유", days=1, must=())
    for w in hot_terms([x["title"] for x in out]):                  # 오늘 기사에 반복해 나온 단어(앤트로픽 등)로 한 번 더 — 고정 주제 없이
        out += fetch(f"{w} {'증시 하락' if down else '증시 상승'}", days=1, must=(w,))
    out.sort(key=lambda x: x["time"], reverse=True)
    out = naver_news.dedupe(out)
    out.sort(key=lambda x: -cause_score(x["title"]))               # 안정 정렬: 원인 기사 먼저, 같은 점수 안에서는 최신순
    return out


SYS = ("당신은 증시 알림에 붙일 한 줄 해설을 쓴다. 입력은 지수가 크게 움직인 시각 전후의 뉴스 제목들이다. "
       "제목에 나온 내용만 근거로, 무슨 일이 시장에 영향을 줬을 수 있는지 1~2문장(180자 이내)으로 쓴다. "
       "확인되지 않은 소문·단독은 '~라는 보도' '~는 소문'으로 표현하고 사실로 단정하지 않는다. "
       "제목에 없는 사실·숫자를 지어내지 않는다. 단순 시황(오르내림)만 있으면 '뚜렷한 원인 기사는 아직 없음'이라고 쓴다. "
       "매수·매도 권유는 하지 않는다.")


def ai_comment(code: str, chg: float, news: list[dict], model: str | None = None) -> str | None:
    """ANTHROPIC_API_KEY 가 있을 때만 — 이슈 제목 위주로 최대 25개를 한 번 요약 (급변 단계마다 1회, 하루 몇 번 안팎)"""
    import os
    if not os.getenv("ANTHROPIC_API_KEY") or not news:
        return None
    try:
        import requests          # SDK 없이 직접 호출 — GitHub 가벼운 작업(requirements-live)에 패키지를 더하지 않으려고
        titles = "\n".join(f"- {n['title']} ({n['time'][11:]})" for n in news[:25])
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=30,
                          headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"},
                          json={"model": model or os.getenv("MARKET_SHOCK_MODEL") or "claude-haiku-5-5", "max_tokens": 300,
                                "system": SYS,
                                "messages": [{"role": "user", "content":
                                              f"{NAME.get(code, code)} {chg:+.1f}% {'하락' if chg < 0 else '상승'} 중. 뉴스 제목:\n{titles}"}]})
        if r.status_code != 200:
            log.warning("시장 급변 AI 해설: HTTP %s %s", r.status_code, r.text[:120])
            return None
        text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text").strip()
        return text[:260] or None
    except Exception as e:  # noqa: BLE001
        log.warning("시장 급변 AI 해설 실패: %s", e)
        return None


def message(rows: list[dict], news: list[dict], now_hm: str, comment: str | None = None,
            new_codes: list[str] | None = None) -> tuple[str, str]:
    """rows: 알릴 지수들 [{code, chg}] + 같은 시각 다른 지수는 body 에 · new_codes: 이번에 새 단계에 들어간 지수 (제목은 이쪽 기준)"""
    pool = [r for r in rows if new_codes and r["code"] in new_codes] or rows
    main = max(pool, key=lambda r: abs(r["chg"]))
    rows = sorted(rows, key=lambda r: r["code"] != main["code"])      # 제목의 지수를 본문 맨 앞에
    down = main["chg"] < 0
    title = f"🚨 {NAME.get(main['code'], main['code'])} {main['chg']:+.1f}% {'급락' if down else '급등'} ({now_hm})"
    lines = [" · ".join(f"{NAME.get(r['code'], r['code'])} {r['chg']:+.2f}%" for r in rows)]
    if comment:
        lines.append("🧭 " + comment + " (AI가 기사 제목만 보고 정리 · 사실 확인 아님)")
    tags = issue_tags([n["title"] for n in news])
    if tags:
        lines.append("뉴스에서 많이 나온 이슈: " + " · ".join(tags))
    if news:
        lines.append("왜 움직였나 (원인·배경 기사 우선)")
        lines += [f"· {n['title'][:60]} ({n['time'][11:]})" for n in news[:SHOW_N]]
    else:
        lines.append("관련 기사를 찾지 못했어요 (뉴스 키 없음 또는 아직 기사 전)")
    lines.append("※ 기사 제목을 모아 본 참고이며 원인을 확정하는 것이 아닙니다.")
    return title, "\n".join(lines)


def all_topics(sb, admin: list[str]) -> list[str]:
    """관리자 토픽 + 승인 회원 중 알림 토픽이 있고 일일 리포트 알림(notify_daily)을 끄지 않은 사람 (중복 제거)"""
    out = list(admin)
    if sb:
        try:
            for u in sb.select("profiles", {"select": "ntfy_topic,notify_daily", "status": "eq.approved",
                                            "ntfy_topic": "not.is.null"}) or []:
                t = (u.get("ntfy_topic") or "").strip().strip("/")
                if t and u.get("notify_daily", True):
                    out.append(t)
        except Exception as e:  # noqa: BLE001
            log.warning("회원 알림 토픽 읽기 실패: %s", e)
    return list(dict.fromkeys(out))


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
    comment = ai_comment(main["code"], main["chg"], news)
    title, body = message([{"code": h["code"], "chg": h["chg"]} for h in hit] +
                          [{"code": str(r["code"]), "chg": float(r["chg_pct"])} for r in indices.to_dict("records")
                           if str(r["code"]) not in {h["code"] for h in hit} and r.get("chg_pct") == r.get("chg_pct")],
                          news, now.strftime("%H:%M"), comment, new_codes=[h["code"] for h in hit])
    if send is None:
        from ..trading.notify import Notifier
        nt = Notifier()
        send = lambda tp, t, b: nt.send_topic(tp, t, b, priority="high")  # noqa: E731  (urgent 는 폰 ntfy 앱 "최대 우선순위" 채널이 꺼져 있으면 안 울림 — 매수 알림과 같은 high, 2026-10-22)
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
