"""DART 공시·재무 5년치 한 번에 채우기 (매수후보 V2 의 재무 15점 · 공시 15점 · 매수 차단용).

  python -m scripts.dart_backfill                     # 공시 + 재무, 2020년부터
  python -m scripts.dart_backfill --what financials   # 재무만
  python -m scripts.dart_backfill --start-year 2021

- 클라우드(SUPABASE_* 환경변수)면 Storage 에서 받아서 채우고, 중간중간 다시 올린다 (중단돼도 이어서 가능).
- 이미 채운 달(공시) / 연도·보고서(재무)는 건너뛴다 → 하루 호출 한도(2만 회)에 걸리면 다음 날 다시 실행.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

import pandas as pd

from stockeye.config import load_config, data_dir
from stockeye.data.store import DataStore

log = logging.getLogger("stockeye.dart_backfill")


def _push(sync, names):
    if sync is not None:
        try:
            sync.push(datasets=names)
        except Exception as e:  # noqa: BLE001
            log.warning("Storage 올리기 실패 (다음에 다시): %s", e)


def backfill_disclosures(store: DataStore, start: pd.Timestamp, end: pd.Timestamp, sync=None, force=False):
    from stockeye.data.sources.dart_source import DartSource
    src = DartSource()
    have = store.load("disclosures")
    done = set()
    if not have.empty and not force:
        m = have["published_at"].dt.to_period("M").value_counts()
        done = {p for p, n in m.items() if n >= 1000}     # 한 달에 1,000건 넘게 있으면 채운 달로 봄
    s = start.to_period("M")
    months = 0
    while s <= end.to_period("M"):
        if s in done:
            s += 1
            continue
        ms, me = s.start_time, min(s.end_time.normalize(), end)
        df = src.disclosures(ms, me)
        if not df.empty:
            store.upsert("disclosures", df)
        log.info("공시 %s: %d건", s, len(df))
        if src.limit_hit:
            log.warning("DART 하루 호출 한도 → 여기까지 저장. 내일 다시 실행하면 이어서 받습니다.")
            break
        months += 1
        if months % 6 == 0:
            _push(sync, ["disclosures"])
        s += 1
    _push(sync, ["disclosures"])
    return not src.limit_hit


def backfill_financials(store: DataStore, years: list[int], sync=None, force=False, reprts=None):
    from stockeye.data.sources.dart_fin import DartFinancials, REPRT
    src = DartFinancials()
    codes = sorted(set(store.load("ohlcv")["code"].unique()))
    corp = src.corp_codes()
    log.info("재무 대상: 시세가 있는 %d종목 중 DART 코드가 있는 %d종목", len(codes), sum(c in corp for c in codes))
    have = store.load("financials")
    done = set()
    if not have.empty and not force:
        cnt = have.groupby(["year", "reprt"]).size()
        done = {k for k, n in cnt.items() if n >= 1000}
    for y in years:
        for rc, name in REPRT.items():
            if reprts and rc not in reprts:
                continue
            if (y, name) in done:
                continue
            df = src.fetch(codes, [y], reprts=(rc,), corp_map=corp)
            if not df.empty:
                store.upsert("financials", df)
            log.info("재무 %d %s: %d건 (호출 누적 %d)", y, name, len(df), src.calls)
            if src.limit_hit:
                log.warning("DART 하루 호출 한도 → 내일 다시 실행하면 이어서 받습니다.")
                _push(sync, ["financials"])
                return False
        _push(sync, ["financials"])
    return True


def update_financials_recent(store: DataStore, today: pd.Timestamp | None = None) -> int:
    """일일 배치용: 올해·작년 보고서만 다시 받음 (정정·새 분기 반영, 약 220회 호출)"""
    today = today or pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)
    from stockeye.data.sources.dart_fin import DartFinancials
    src = DartFinancials()
    codes = sorted(set(store.load("ohlcv")["code"].unique()))
    df = src.fetch(codes, [today.year - 1, today.year])
    if not df.empty:
        store.upsert("financials", df)
    return len(df)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", default="all", choices=["all", "disclosures", "financials"])
    ap.add_argument("--start-year", type=int, default=2020)
    ap.add_argument("--force", action="store_true", help="이미 받은 기간도 다시")
    ap.add_argument("--local", action="store_true", help="Storage 를 쓰지 않고 이 PC 의 data/ 만")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)

    import os
    if not os.getenv("DART_API_KEY"):
        sys.exit("DART_API_KEY 가 없습니다")
    t0 = time.time()
    cfg = load_config()
    store = DataStore(data_dir(cfg))
    sync = None
    from stockeye.cloud.client import enabled
    if enabled() and not args.local:
        from stockeye.cloud.sync import DataSync
        sync = DataSync(store)
        sync.pull()
    today = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize()
    ok = True
    if args.what in ("all", "financials"):
        ok &= backfill_financials(store, list(range(args.start_year, today.year + 1)), sync, args.force)
    if args.what in ("all", "disclosures"):
        ok &= backfill_disclosures(store, pd.Timestamp(f"{args.start_year}-01-01"), today, sync, args.force)

    d, f = store.load("disclosures"), store.load("financials")
    print("=" * 60)
    print(f"공시 {len(d):,}건 ({d['published_at'].min() if len(d) else '-'} ~ {d['published_at'].max() if len(d) else '-'})")
    if len(f):
        print(f"재무 {len(f):,}건 / {f['code'].nunique():,}종목 / 연도·보고서별:")
        print(f.groupby(["year", "reprt"]).size().unstack().fillna(0).astype(int).to_string())
    print(f"{'완료' if ok else '한도 초과로 일부만 — 내일 다시 실행하세요'} ({(time.time() - t0) / 60:.0f}분)")


if __name__ == "__main__":
    main()
