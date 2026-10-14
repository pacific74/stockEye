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


def build(report: dict, code: str, entry_price: float) -> dict:
    tabs, plan = [], None
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
            break
    mood = (report.get("market") or {}).get("mood")
    bits = [f"{t['label']} {t['rank']}위 {t['score']:.0f}점" + (f"({t['state']})" if t.get("state") else "")
            if t.get("score") is not None else f"{t['label']} {t['rank']}위" for t in tabs]
    z = zone_of(entry_price, plan or {})
    summary = (" · ".join(bits) if bits else "그날 후보 목록에 없던 종목") + (f" · {z}" if z else "") + (
        f" · 시장 {mood}" if mood else "")
    return {"report_date": report.get("date"), "tabs": tabs, "zone": z, "market": mood, "summary": summary,
            "plan": {k: (plan or {}).get(k) for k in ("entry_low", "entry_high", "target1", "stop")} if plan else None}


def annotate_positions(sb, sync, limit: int = 3000) -> int:
    """entry_info 가 없는 포지션에 매수 당시 정보를 붙임. 붙인 개수"""
    rows = sb.select("positions", {"select": "id,code,entry_time,entry_price,plan", "limit": str(limit)})
    todo = [r for r in rows if not (isinstance(r.get("plan"), dict) and r["plan"].get("entry_info"))]
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
        info["at"] = datetime.utcnow().isoformat() + "Z"
        plan = r["plan"] if isinstance(r.get("plan"), dict) else {}
        sb.update("positions", {"id": f"eq.{r['id']}"}, {"plan": {**plan, "entry_info": info}})
        n += 1
    log.info("매매일지 매수 당시 정보 %d건", n)
    return n
