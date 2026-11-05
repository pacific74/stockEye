"""저녁 NXT 애프터마켓 기록 (2026-11-05) — 평일 19:30 과 20:05 (두 번 — 20:05 에 값이 비면 19:30 기록 유지)
전 종목 네이버 시세 → {코드: [NXT 가격, 그날 KRX 종가 대비 %]} → Storage nxt/after/<날짜>.json · latest.json
다음날 아침 PC 22_intraday 가 이 값을 당일단타 09:00 선발에 씀 (scripts/daytrade.py _early)
실행: 28_nxt_after.bat (한 번 'register' 로 20:05 예약)
"""
from __future__ import annotations

import sys

import pandas as pd


def main() -> None:
    from stockeye.analysis import nxt_ctx
    from stockeye.cloud.client import Supabase, enabled
    from stockeye.config import data_dir, load_config
    from stockeye.data.sources import naver_live
    from stockeye.data.store import DataStore
    from stockeye.engine.nextday import common_stock
    day = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)
    if day.weekday() >= 5 or naver_live.is_trading_day(day) is False:
        print("오늘은 장이 열리지 않음 -> 종료")
        return
    cfg = load_config()
    ls = DataStore(data_dir(cfg)).load("listing")
    if ls is None or ls.empty:
        sys.exit("종목 목록이 없습니다 - 먼저 4_daily.bat")
    ls = ls.drop_duplicates("code", keep="last")
    names = dict(zip(ls["code"], ls["name"]))
    codes = [c for c in ls["code"] if common_stock(c, names.get(c, ""))]
    rows = nxt_ctx.pre_snapshot(naver_live.stocks(codes))      # 가격 = 그날 KRX 종가, over_price = NXT 마지막 가격
    print(f"애프터마켓 {len(rows)}종목")
    if not (enabled() and rows):
        print("저장 안 함 (Supabase 설정 없음 또는 시세 없음)")
        return
    sb = Supabase()
    d = day.strftime("%Y-%m-%d")
    try:                                                        # 19:30 기록이 있는데 20:05 에 값이 거의 없으면 (NXT 마감 뒤 값이 비는 경우) 19:30 것을 유지
        import json
        old = json.loads(sb.download("nxt/after/latest.json") or b"{}")
    except Exception:  # noqa: BLE001
        old = {}
    if old.get("day") == d and len(old.get("rows") or {}) > 0 and len(rows) < 0.5 * len(old["rows"]):
        print(f"새 값 {len(rows)}종목 < 이전 {len(old['rows'])}종목의 절반 -> 이전 기록 유지")
        return
    nxt_ctx.save_after(sb, d, rows)
    print("저장 완료")


if __name__ == "__main__":
    main()
