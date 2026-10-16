"""상한가 예비 결과 매기기 (저녁 배치 · 2026-10-16) — limitcatch/pre/<날짜>.json 의 첫 신호를 그날 일봉으로 평가
  reached = 그날 고가가 상한가 · closed = 종가가 상한가 (잠김) · high_ret / close_ret = 신호 가격 대비
  누적 → Storage limitcatch/pre_stats.json (최근 KEEP 건) · system_status 'limit_pre_stats' {rows(최근 60), stats}
"""
from __future__ import annotations

import json
import logging

import pandas as pd

from ..engine import limit_pre as lp
from ..engine.uplimit import limit_price

log = logging.getLogger(__name__)
STATS_FILE = "limitcatch/pre_stats.json"
KEEP = 1000


def grade_day(rows: list[dict], day_bars: dict[str, dict]) -> list[dict]:
    out = []
    for r in rows:
        d = day_bars.get(r.get("code"))
        if not d:
            continue
        lim = r.get("limit") or limit_price(r.get("prev_close") or 0)
        out.append({**{k: r.get(k) for k in ("date", "code", "name", "time", "price", "chg_pct", "score")},
                    **lp.grade(r, d, lim)})
    return out


def run(sb, ohlcv: pd.DataFrame, today: str, days: int = 7) -> dict:
    try:
        b = sb.download(STATS_FILE)
        saved = json.loads(b) if b else {}
    except Exception:  # noqa: BLE001
        saved = {}
    rows = saved.get("rows") or []
    have = {(r["date"], r["code"]) for r in rows}
    added = 0
    for i in range(days):
        d = (pd.Timestamp(today) - pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        try:
            raw = sb.download(f"limitcatch/pre/{d}.json")
        except Exception:  # noqa: BLE001
            continue
        if not raw:
            continue
        sig = [r for r in (json.loads(raw).get("rows") or []) if (d, r.get("code")) not in have]
        if not sig:
            continue
        bars = ohlcv[(ohlcv["date"] == pd.Timestamp(d)) & ohlcv["code"].isin({r["code"] for r in sig})]
        day_bars = {r.code: {"high": r.high, "close": r.close} for r in bars.itertuples()}
        g = grade_day(sig, day_bars)
        rows += g
        added += len(g)
    rows = sorted(rows, key=lambda r: (r["date"], r.get("time") or ""))[-KEEP:]
    st = lp.stats(rows)
    if added:
        sb.upload(STATS_FILE, json.dumps({"rows": rows}, ensure_ascii=False, default=str).encode(), "application/json")
    from ..cloud import publish as pub
    pub.publish_status(sb, "limit_pre_stats", {"updated": today, "version": lp.VERSION, "stats": st, "rows": rows[-60:]})
    return {"added": added, "total": len(rows), **st.get("all", {})}
