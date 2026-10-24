"""업종/테마 '오늘' 강도 — 장중 1시간마다 (GitHub sector_live 작업, PC 필요 없음)

  최근 저녁 리포트의 업종·테마별 '전체 종목'과 가중치(시가총액 — HTS 업종지수와 같은 방식, 없으면 같은 비중)
  → 네이버 지금 시세로 업종마다 가중 등락률 + 단순 평균 + 상승/하락 종목 수 → Supabase system_status 'sectors_live'
  → 앱 메인 '업종/테마 강도' 왼쪽(오늘). 저녁 리포트의 업종 등락과 같은 계산 방식 (2026-10-13 전체 종목으로 바꿈).

  python -m scripts.sector_live                       # 한 번
  python -m scripts.sector_live --dry-run             # 발행 없이 화면에만
  python -m scripts.sector_live --skip-if-recent 30   # 30분 안에 이미 발행됐으면 건너뜀 (GitHub — PC 가 정시에 했으면)
  (2026-10-14) PC 22_intraday 가 09:10 부터 매시 10분에 직접 돌림 — GitHub 예약은 첫 회가 10시 넘어 도는 일이 많아서
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
        sw = sr = se = 0.0
        n = up = down = 0
        for code, w in ms:
            c = chg.get(code)
            if c is None or w <= 0:
                continue
            sw += w
            sr += w * c
            se += c
            n += 1
            up += c > 0
            down += c < 0
        if n >= 3 and sw > 0:
            rows.append({"group": grp, "type": types.get(grp), "chg_pct": round(sr / sw, 2), "eq_pct": round(se / n, 2),
                         "n": n, "up": up, "down": down, "members": len(ms)})
    return sorted(rows, key=lambda r: -r["chg_pct"])


def run(sb=None, publish: bool = True, skip_if_recent: int | None = None, quiet: bool = False) -> dict | None:
    """한 번 계산 · 발행. skip_if_recent 분 안에 오늘 것이 이미 있으면 건너뜀(None)"""
    from stockeye.cloud.client import Supabase
    from stockeye.data.sources import naver_live
    now = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)
    sb = sb or Supabase()
    if skip_if_recent:
        try:
            cur = (sb.select("system_status", {"select": "payload", "key": "eq.sectors_live"}) or [{}])[0].get("payload") or {}
            if cur.get("date") == now.strftime("%Y-%m-%d") and cur.get("time"):
                age = (now - pd.Timestamp(f"{cur['date']} {cur['time']}")).total_seconds() / 60
                if 0 <= age < skip_if_recent:
                    print(f"{cur['time']} 에 이미 발행됨 ({age:.0f}분 전) → 건너뜀")
                    return None
        except Exception:  # noqa: BLE001
            pass
    reps = sb.select("daily_reports", {"select": "date,sectors", "order": "date.desc", "limit": "3"})
    rep = next((r for r in reps if any(g.get("live") for g in r.get("sectors") or [])), reps[0] if reps else None)
    if not rep:
        raise RuntimeError("리포트가 없습니다")
    members = members_of(rep["sectors"])
    types = {g["group"]: g.get("type") for g in rep["sectors"]}
    codes = sorted({c for ms in members.values() for c, _ in ms})
    snap = naver_live.stocks(codes)
    if snap.empty:
        raise RuntimeError("네이버 시세를 받지 못함")
    chg = {r["code"]: float(r["chg_pct"]) for _, r in snap.iterrows() if pd.notna(r.get("chg_pct"))}
    groups = compute(members, chg, types)
    payload = {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"), "basis": rep["date"],
               "coverage": round(len(chg) / max(len(codes), 1), 3), "stocks": len(chg), "groups": groups}
    if not quiet:
        print(f"{payload['time']} 업종 {len(groups)}개 · 종목 {len(chg)}/{len(codes)}")
        for g in groups[:6]:
            print(f"   {g['group']:<10} {g['chg_pct']:+.2f}% ({g['up']}/{g['n']} 상승)")
    if publish:
        from stockeye.cloud import publish as pub
        pub.publish_status(sb, "sectors_live", payload)
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-if-recent", type=int, default=None, help="이 분 안에 발행됐으면 건너뜀")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", stream=sys.stdout)
    from stockeye.data.sources import naver_live
    if naver_live.is_trading_day() is False:
        print("오늘은 장이 열리지 않음 → 종료"); return
    try:
        run(publish=not args.dry_run, skip_if_recent=args.skip_if_recent)
    except RuntimeError as e:
        sys.exit(str(e))
    if not args.dry_run:        # 종합지수 ±3% 이상이면 뉴스와 함께 관리자 알림 (PC 22번이 이미 보냈으면 중복 없음)
        try:
            from stockeye.cloud.client import Supabase
            from stockeye.analysis.market_shock import all_topics, check
            from scripts.intraday_live import admin_topics
            sb = Supabase()
            check(sb, all_topics(sb, admin_topics(sb)))
        except Exception as e:  # noqa: BLE001
            print(f"⚠ 시장 급변 확인 실패: {e}")
        try:                    # Supabase 가 ntfy 한도(429)로 못 보낸 가입·테스트 알림을 대신 보냄 (2026-10-24)
            from stockeye.cloud.pending_notify import run as pend_run
            pend_run(sb, admin_topics(sb))
        except Exception as e:  # noqa: BLE001
            print(f"⚠ 가입·테스트 알림 대신 보내기 실패: {e}")


if __name__ == "__main__":
    main()
