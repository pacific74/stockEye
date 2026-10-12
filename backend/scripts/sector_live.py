"""업종/테마 '오늘' 강도 — 장중 1시간마다 (GitHub sector_live 작업, PC 필요 없음)

  최근 저녁 리포트의 업종·테마별 '전체 종목'(평소 거래대금 5억↑)과 가중치(20일 평균 거래대금)
  → 네이버 지금 시세로 업종마다 거래대금 가중 등락률 → Supabase system_status 'sectors_live'
  → 앱 메인 '업종/테마 강도' 왼쪽(오늘). 저녁 리포트의 업종 등락과 같은 계산 방식.

  python -m scripts.sector_live            # 한 번
  python -m scripts.sector_live --dry-run  # 발행 없이 화면에만
"""
from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

log = logging.getLogger("stockeye.sector_live")


def members_of(sectors: list[dict]) -> dict[str, list[tuple[str, float]]]:
    """업종 → [(종목, 가중치)]. 'live'(전체 종목·가중치)가 없던 예전 리포트면 대표 종목 같은 비중"""
    out = {}
    for g in sectors or []:
        live = g.get("live") or []
        if live:
            out[g["group"]] = [(m["code"], float(m.get("w") or 0)) for m in live]
        elif g.get("top"):
            out[g["group"]] = [(m["code"], 1.0) for m in g["top"]]
    return out


def compute(members: dict[str, list[tuple[str, float]]], chg: dict[str, float], types: dict[str, str]) -> list[dict]:
    rows = []
    for grp, ms in members.items():
        sw = sr = 0.0
        n = up = 0
        for code, w in ms:
            c = chg.get(code)
            if c is None or w <= 0:
                continue
            sw += w
            sr += w * c
            n += 1
            up += c > 0
        if n >= 3 and sw > 0:
            rows.append({"group": grp, "type": types.get(grp), "chg_pct": round(sr / sw, 2), "n": n, "up": up,
                         "members": len(ms)})
    return sorted(rows, key=lambda r: -r["chg_pct"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", stream=sys.stdout)
    from stockeye.cloud.client import Supabase
    from stockeye.data.sources import naver_live
    now = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)
    if naver_live.is_trading_day() is False:
        print("오늘은 장이 열리지 않음 → 종료"); return
    sb = Supabase()
    reps = sb.select("daily_reports", {"select": "date,sectors", "order": "date.desc", "limit": "3"})
    rep = next((r for r in reps if any(g.get("live") for g in r.get("sectors") or [])), reps[0] if reps else None)
    if not rep:
        sys.exit("리포트가 없습니다")
    members = members_of(rep["sectors"])
    types = {g["group"]: g.get("type") for g in rep["sectors"]}
    codes = sorted({c for ms in members.values() for c, _ in ms})
    snap = naver_live.stocks(codes)
    if snap.empty:
        sys.exit("네이버 시세를 받지 못함")
    chg = {r["code"]: float(r["chg_pct"]) for _, r in snap.iterrows() if pd.notna(r.get("chg_pct"))}
    groups = compute(members, chg, types)
    payload = {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"), "basis": rep["date"],
               "coverage": round(len(chg) / max(len(codes), 1), 3), "stocks": len(chg), "groups": groups}
    print(f"{payload['time']} 업종 {len(groups)}개 · 종목 {len(chg)}/{len(codes)}")
    for g in groups[:6]:
        print(f"   {g['group']:<10} {g['chg_pct']:+.2f}% ({g['up']}/{g['n']} 상승)")
    if not args.dry_run:
        from stockeye.cloud import publish as pub
        pub.publish_status(sb, "sectors_live", payload)


if __name__ == "__main__":
    main()
