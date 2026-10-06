"""데이터 수집 서버의 핵심: 날짜별 증분 수집 + 저장.

    python -m scripts.collect --start 2021-01-01          # 최초 5년치
    python -m scripts.collect                             # 매일 장 마감 후 (마지막 날짜 이후만)
"""
from __future__ import annotations

import logging

import pandas as pd

from .store import DataStore

log = logging.getLogger(__name__)


def collect_range(store: DataStore, source, start, end, with_flows=True, with_fund=True,
                  flush_every: int = 20) -> None:
    days = [pd.Timestamp(d) for d in source.trading_days(start, end)]
    # 오늘 데이터는 18:00(수급 확정) 이후에만 '하루치 완성본'으로 저장한다.
    now = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)
    if days and days[-1].normalize() == now.normalize() and now.hour < 18:
        log.info("오늘(%s)은 아직 장중/수급 미확정 → 18:00 이후 다시 실행하세요", now.date())
        days = days[:-1]
    have = set(store.load("ohlcv")["date"].unique()) if store.path("ohlcv").exists() else set()
    # 마지막 저장일은 항상 다시 받는다 (장중에 받아 둔 미완성 데이터 덮어쓰기)
    last = max(have) if have else None
    todo = [d for d in days if d not in have or d == last]
    log.info("수집 대상 영업일 %d일 (이미 있음 %d일)", len(todo), len(days) - len(todo))

    buf = {"ohlcv": [], "flows": [], "fundamentals": []}
    for i, d in enumerate(todo, 1):
        try:
            buf["ohlcv"].append(source.ohlcv_day(d))
            if with_fund:
                buf["fundamentals"].append(source.fundamentals_day(d))
            if with_flows:
                buf["flows"].append(source.flows_day(d))
        except Exception as e:  # noqa: BLE001
            log.error("%s 수집 실패: %s (다음 실행 때 재시도)", pd.Timestamp(d).date(), e)
        if i % flush_every == 0 or i == len(todo):
            for name, parts in buf.items():
                parts = [p for p in parts if p is not None and not p.empty]
                if parts:
                    store.upsert(name, pd.concat(parts, ignore_index=True))
            buf = {k: [] for k in buf}
            log.info("  %d/%d 저장", i, len(todo))

    if days:
        store.upsert("index", source.index_range(start, end))
        store.upsert("listing", source.listing(days[-1]))
        collect_sectors(store, source, days[-1])


def collect_sectors(store: DataStore, source, date) -> None:
    try:
        df = source.sectors(date)
        if not df.empty:
            store.save("sectors", df)   # 최신 분류로 교체
            log.info("업종 분류 %d종목 저장", len(df))
    except Exception as e:  # noqa: BLE001
        log.warning("업종 분류 수집 실패: %s", e)


def collect_disclosures(store: DataStore, dart, start, end) -> None:
    df = dart.disclosures(start, end)
    if not df.empty:
        store.upsert("disclosures", df)


def load_synthetic(store: DataStore, **kw) -> None:
    from .sources.synthetic import generate
    for name, df in generate(**kw).items():
        store.save(name, df)
