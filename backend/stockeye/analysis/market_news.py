"""메인화면 '시장 뉴스' — 오늘 시장이 왜 움직였나 기사 5개 (2026-10-27)

  시장 급변 알림(market_shock)과 같은 방식으로 고름: 지수 등락·이유 검색 + 그날 기사에 반복된 단어(앤트로픽 등)로 재검색 →
  원인 점수(cause_score)순. 급변(±3%)이 아니어도 장중 매시 갱신 → Supabase system_status 'market_news' → 앱 업종/테마 강도 아래.
  실시간이 아니라 sector_live(PC 22번 / GitHub, 매시 10분) 때 같이 돔. 뉴스 키(NAVER_HUB_*)가 없으면 아무것도 안 함.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

N = 5


def pick(code: str, down: bool, fetch=None, n: int = N) -> list[dict]:
    from .market_shock import news_for
    return [{"title": x["title"], "link": x.get("link"), "time": x["time"]} for x in news_for(code, down, fetch)[:n]]


def run(sb, indices=None, fetch=None, now=None, skip_if_recent: int | None = 25) -> dict | None:
    import pandas as pd
    from ..data import naver_news
    if fetch is None and not naver_news.enabled():
        return None
    now = now or pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)
    day = now.strftime("%Y-%m-%d")
    if skip_if_recent and sb:
        try:
            cur = (sb.select("system_status", {"select": "payload", "key": "eq.market_news"}) or [{}])[0].get("payload") or {}
            if cur.get("date") == day and cur.get("time"):
                if 0 <= (now - pd.Timestamp(f"{day} {cur['time']}")).total_seconds() / 60 < skip_if_recent:
                    return None                                    # PC 와 GitHub 가 같이 돌아도 한 번만
        except Exception as e:  # noqa: BLE001
            log.warning("시장 뉴스 상태 읽기 실패: %s", e)
    if indices is None:
        from ..data.sources import naver_live
        indices = naver_live.indices()
    code, chg = "KOSPI", 0.0
    if indices is not None and len(indices):
        rows = [r for r in indices.to_dict("records") if r.get("chg_pct") == r.get("chg_pct") and r.get("chg_pct") is not None]
        if rows:
            m = max(rows, key=lambda r: abs(float(r["chg_pct"])))     # 더 크게 움직인 지수 기준
            code, chg = str(m["code"]), float(m["chg_pct"])
    items = pick(code, chg < 0, fetch)
    if not items:
        return None
    payload = {"date": day, "time": now.strftime("%H:%M"), "index": code, "chg": round(chg, 2), "items": items}
    if sb:
        from ..cloud import publish as pub
        pub.publish_status(sb, "market_news", payload)
    return payload
