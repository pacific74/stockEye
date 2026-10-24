"""매매일지: 매수 당시 '어떤 후보였고 몇 점, 어떤 상태였는지'를 포지션에 붙임 (positions.plan.entry_info)

매수 시각 기준으로 그때 앱에 보이던 리포트를 찾는다.
  - 장 마감 리포트(저녁 배치)는 그날 18시 이후부터 보이므로, 18시 이전 매수 → 전 거래일 리포트, 이후 → 당일 리포트
  - 리포트는 Storage reports/YYYY-MM-DD.json
그 리포트의 모든 후보 탭(V3·유망주·상승초기·추세전환…, 예전 V2 목록 포함)에서 종목을 찾아
  탭 이름 · 순위 · 점수 · 판정/등급 · 매수가가 그날 매수구간 안/위/아래였는지 · 시장 분위기 를 기록한다.
한 번 붙이면 다시 계산하지 않는다 (매수 당시 상태를 보존).
"""
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

log = logging.getLogger(__name__)


def _report_dates(sb) -> list[str]:
    try:
        names = sb.list_files("reports/")
    except Exception as e:  # noqa: BLE001
        log.info("리포트 목록 조회 실패: %s", e)
        return []
    out = []
    for n in names:
        b = n.rsplit("/", 1)[-1].replace(".json", "")
        if len(b) == 10 and b[4] == "-" and b[7] == "-":
            out.append(b)
    return sorted(out)


def report_for(entry_time: str, dates: list[str]) -> str | None:
    """매수 시각에 앱에 보이던 장 마감 리포트 날짜"""
    t = pd.Timestamp(entry_time)
    cutoff = t.normalize() if t.hour < 18 else t.normalize() + pd.Timedelta(days=1)
    ok = [d for d in dates if pd.Timestamp(d) < cutoff]
    return ok[-1] if ok else None


def zone_of(price: float, plan: dict) -> str | None:
    lo, hi, st = plan.get("entry_low"), plan.get("entry_high"), plan.get("stop")
    if not price or not lo or not hi:
        return None
    if st and price <= st:
        return "손절가 아래에서 매수"
    if lo <= price <= hi:
        return "매수구간 안에서 매수"
    if price > hi:
        return f"매수구간 위에서 매수 (+{(price / hi - 1) * 100:.1f}%)"
    return f"매수구간 아래에서 매수 ({(price / lo - 1) * 100:.1f}%)"


LABEL = {"v3": "V3", "nextday": "유망주", "early": "상승초기", "reversal": "추세전환",
         "signal": "매수 신호", "buy": "강력·매수 후보", "watch": "관심", "overall": "전체 후보"}


def _lines(x, n: int) -> list[str]:
    return [str(t).strip() for t in (x or []) if isinstance(t, str) and t.strip()][:n]


def comment_of(label: str, c: dict) -> dict | None:
    """후보 1종목의 그때 코멘트: 선정 이유 · 주의 · 시장/업종 급락 경고 (한 탭 = 한 묶음)"""
    why = _lines(c.get("reasons"), 4)
    warn = _lines(c.get("warnings") or c.get("warn") or c.get("risks"), 3)
    if c.get("market_alert"):
        warn.append(str(c["market_alert"]))
    return {"tab": label, "why": why, "warn": warn} if why or warn else None


def build(report: dict, code: str, entry_price: float) -> dict:
    tabs, plan, comments = [], None, []
    for k, v in (report.get("strategies") or {}).items():
        for i, c in enumerate((v or {}).get("candidates") or [], 1):
            if c.get("code") != code:
                continue
            sc = c.get("score")
            grade = None
            for f in ("nextday", "early", "reversal"):
                if isinstance(c.get(f), dict):
                    grade = c[f].get("label") or c[f].get("grade_label")
            tabs.append({"key": k, "label": v.get("short") or LABEL.get(k, k), "rank": i,
                         "score": None if sc is None else round(float(sc), 1),
                         "state": grade or (c.get("plan") or {}).get("verdict")})
            plan = plan or c.get("plan")
            cm = comment_of(v.get("short") or LABEL.get(k, k), c)
            if cm:
                comments.append(cm)
            break
    mood = (report.get("market") or {}).get("mood")
    bits = [f"{t['label']} {t['rank']}위 {t['score']:.0f}점" + (f"({t['state']})" if t.get("state") else "")
            if t.get("score") is not None else f"{t['label']} {t['rank']}위" for t in tabs]
    z = zone_of(entry_price, plan or {})
    summary = (" · ".join(bits) if bits else "그날 후보 목록에 없던 종목") + (f" · {z}" if z else "") + (
        f" · 시장 {mood}" if mood else "")
    sec = None
    try:
        from .holding_note import sector_of
        sc = sector_of(report, code)
        sec = f"{sc[0]} {sc[1]:+.1f}%" if sc else None            # 그날 소속 업종(테마)과 등락
    except Exception:  # noqa: BLE001
        pass
    return {"report_date": report.get("date"), "tabs": tabs, "zone": z, "market": mood, "summary": summary,
            "comments": comments, "sector": sec,
            "plan": {k: (plan or {}).get(k) for k in ("entry_low", "entry_high", "target1", "stop")} if plan else None}


INTRA_LABEL = {"daytrade": "당일단타", "closingbet": "종가배팅", "limitcatch": "상한가포착"}


def intraday_comments(sb, code: str, day: str) -> list[dict]:
    """그날 장중 탭(당일단타·종가배팅·상한가포착)에서 포착된 기록의 이유·위험 (recommendations.payload)"""
    try:
        rows = sb.select("recommendations", {"select": "kind,payload", "rec_date": f"eq.{day}", "code": f"eq.{code}",
                                             "kind": "in.(daytrade,closingbet,limitcatch)"}) or []
    except Exception as e:  # noqa: BLE001
        log.info("장중 코멘트 조회 실패: %s", e)
        return []
    out = []
    for r in rows:
        pl = r.get("payload") or {}
        cm = comment_of(INTRA_LABEL.get(r.get("kind"), r.get("kind")), {"reasons": pl.get("reasons"), "risks": pl.get("risks")})
        if cm:
            out.append(cm)
    return out


def _needs(r: dict) -> bool:
    pl = r.get("plan") if isinstance(r.get("plan"), dict) else {}
    ei = pl.get("entry_info")
    return not ei or "comments" not in ei                   # 코멘트 칸이 생기기 전에 붙인 것도 한 번 채움 (2026-10-24)


def annotate_positions(sb, sync, limit: int = 3000) -> int:
    """entry_info 가 없거나 코멘트 칸이 없는 포지션에 매수 당시 정보를 붙임. 붙인 개수 (이미 있는 요약은 그대로)"""
    rows = sb.select("positions", {"select": "id,code,entry_time,entry_price,plan", "limit": str(limit)})
    todo = [r for r in rows if _needs(r)]
    if not todo:
        return 0
    dates = _report_dates(sb)
    cache, n = {}, 0
    for r in todo:
        d = report_for(r["entry_time"], dates)
        if not d:
            continue
        if d not in cache:
            cache[d] = sync.get_json(f"reports/{d}.json") or {}
        rep = cache[d]
        if not rep:
            continue
        info = build(rep, r["code"], float(r.get("entry_price") or 0))
        info["comments"] += intraday_comments(sb, r["code"], str(r["entry_time"])[:10])
        plan = r["plan"] if isinstance(r.get("plan"), dict) else {}
        old = plan.get("entry_info")
        if old:                                              # 매수 당시 요약은 보존 — 코멘트·업종만 채움
            info = {**old, "comments": info["comments"], "sector": info.get("sector")}
        else:
            info["at"] = datetime.utcnow().isoformat() + "Z"
        sb.update("positions", {"id": f"eq.{r['id']}"}, {"plan": {**plan, "entry_info": info}})
        n += 1
    log.info("매매일지 매수 당시 정보 %d건", n)
    return n
