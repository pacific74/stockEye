"""이미 지나간 날의 관심주를 추천 기록(recommendations)에 넣기 — 한 번만 쓰는 보충용 (scripts_win/21_record_today.bat)

  python -m scripts.record_recommendations                 # 오늘
  python -m scripts.record_recommendations --date 2026-10-12

  저녁 배치  : candidates 표의 그날 V3·익일유망주·상승초기·추세전환·상파 목록 (60일 안의 날짜만 남아 있음)
  당일단타   : Storage daytrade/signals/날짜.json ('진입 조건 충족' 신호)
  종가배팅   : Storage closingbet/signals/날짜.json (15:20 매수 후보) + 그날 마지막 결과의 '매수 후보'
  상한가포착 : Storage limitcatch/signals/날짜.json (처음 매수 검토)
  이미 있는 기록(같은 추천일·구분·종목)은 그대로 둠. 먼저 Supabase 에서 2026-10-12_recommendations.sql 실행 필요
"""
from __future__ import annotations

import argparse
import json
import sys

import pandas as pd


def _json(sb, key):
    try:
        b = sb.download(key)
        return json.loads(b) if b else None
    except Exception:  # noqa: BLE001
        return None


def collect(sb, day: str) -> list[dict]:
    from stockeye.cloud import recommend as rc
    rows = []
    cands = sb.select("candidates", {"select": "list,payload", "date": f"eq.{day}",
                                     "list": f"in.({','.join(rc.DAILY_KINDS)})", "limit": "5000"})
    rows += [rc.from_candidate(r["list"], day, r["payload"], "daily") for r in cands]
    for s in _json(sb, f"daytrade/signals/{day}.json") or []:
        rows.append(rc.from_intraday("daytrade", day, {**s, "status": "진입 조건 충족"}, "pc"))
    cb = [{**s, "status": "매수 후보"} for s in _json(sb, f"closingbet/signals/{day}.json") or []]
    try:
        st = sb.select("system_status", {"select": "payload", "key": "eq.closingbet"})
        p = st[0]["payload"] if st else {}
        if p.get("date") == day:
            cb += [{**r, "time": r.get("time") or p.get("time")} for r in p.get("items") or [] if r.get("status") == "매수 후보"]
    except Exception:  # noqa: BLE001
        pass
    rows += [rc.from_intraday("closingbet", day, r, "pc") for r in cb]
    lc = _json(sb, f"limitcatch/signals/{day}.json") or {}
    rows += [rc.from_intraday("limitcatch", day, {**r, "status": "매수 검토"}, "pc") for r in lc.get("first_buy") or []]
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    from stockeye.cloud.client import Supabase, enabled
    from stockeye.cloud import recommend as rc
    if not enabled():
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY 환경변수가 없습니다")
    sb = Supabase()
    rows = collect(sb, args.date)
    by = {}
    for r in rows:
        by[r["kind"]] = by.get(r["kind"], 0) + 1
    print(f"{args.date} 추천 {len(rows)}건: " + " · ".join(f"{k} {v}" for k, v in by.items()))
    if not rows:
        print("넣을 것이 없습니다 (그날 저녁 배치 결과가 없거나 60일이 지났을 수 있음)")
        return
    if args.dry_run:
        return
    try:
        n = rc.record(sb, rows)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"저장 실패: {e}\n→ Supabase SQL Editor 에서 2026-10-12_recommendations.sql 을 먼저 실행했는지 확인하세요")
    print(f"→ recommendations 에 {n}건 보냄 (이미 있던 것은 그대로)")


if __name__ == "__main__":
    main()
