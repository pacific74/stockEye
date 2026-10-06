"""일일 리포트를 Supabase 에 발행 (선택).

환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY  (service_role 키 — 절대 앱에 넣지 말 것, 서버 PC 에만)
없으면 아무것도 하지 않는다.
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY"))


def _upsert(session, url, key, table, rows, on_conflict):
    if not rows:
        return
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
         "Prefer": "resolution=merge-duplicates,return=minimal"}
    for i in range(0, len(rows), 500):
        r = session.post(f"{url}/rest/v1/{table}", headers=h, params={"on_conflict": on_conflict},
                         data=json.dumps(rows[i:i + 500], ensure_ascii=False, default=str), timeout=30)
        if r.status_code >= 300:
            raise RuntimeError(f"Supabase {table} 업로드 실패 {r.status_code}: {r.text[:300]}")


def publish_report(report: dict) -> bool:
    if not enabled():
        return False
    import requests
    url, key = os.getenv("SUPABASE_URL").rstrip("/"), os.getenv("SUPABASE_SERVICE_KEY")
    s = requests.Session()
    d = report["date"]
    _upsert(s, url, key, "daily_reports", [{
        "date": d, "as_of": report["as_of"], "market": report["market"], "sectors": report["sectors"][:30],
        "top10": report["top10"], "funnel": report["funnel"]}], "date")

    rows = []
    for lst, cands in [("overall", report["candidates"])] + [(k, v["candidates"]) for k, v in report["strategies"].items()]:
        for c in cands:
            rows.append({"date": d, "list": lst, "rank": c["rank"], "code": c["code"], "name": c["name"],
                         "score": c["score"], "strategy_score": c.get("strategy_score"),
                         "verdict": c["plan"]["verdict"], "payload": c})
    _upsert(s, url, key, "candidates", rows, "date,list,code")
    _upsert(s, url, key, "sector_strength",
            [{"date": d, "group": g["group"], "type": g["type"], "score": g["score"], "payload": g}
             for g in report["sectors"]], "date,group")
    ex = [{"date": d, "code": code, "list": "overall", "text": e["text"], "source": e["source"], "model": e.get("model")}
          for code, e in report.get("explanations", {}).items()]
    _upsert(s, url, key, "ai_explanations", ex, "date,code,list")
    log.info("Supabase 발행 완료: 후보 %d, 업종 %d, 설명 %d", len(rows), len(report["sectors"]), len(ex))
    return True


JOURNAL_COLS = ["id", "mode", "code", "name", "strategy", "list_key", "score", "strategy_score", "entry_time",
                "entry_price", "qty", "stop", "target1", "target2", "reasons", "warnings", "market_mood", "theme",
                "verdict", "exit_time", "exit_price", "exit_reason", "ret_pct", "pnl", "hold_days", "result",
                "mae_pct", "mfe_pct", "late_stop", "memo", "status"]


def publish_journal(positions: list[dict]) -> bool:
    """매매일지를 Supabase journal 테이블로 동기화 (SUPABASE_USER_ID 필요)."""
    uid = os.getenv("SUPABASE_USER_ID")
    if not (enabled() and uid and positions):
        return False
    import requests
    url, key = os.getenv("SUPABASE_URL").rstrip("/"), os.getenv("SUPABASE_SERVICE_KEY")
    rows = []
    for p in positions:
        r = {k: p.get(k) for k in JOURNAL_COLS}
        r["late_stop"] = bool(r.get("late_stop"))
        r["user_id"] = uid
        rows.append(r)
    _upsert(requests.Session(), url, key, "journal", rows, "id")
    return True
