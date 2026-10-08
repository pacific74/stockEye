"""DART 공시·재무 5년치 한 번에 채우기 (매수후보 V2 의 재무 15점 · 공시 15점 · 매수 차단용).

  python -m scripts.dart_backfill                     # 재무 → 공시, 2020년부터
  python -m scripts.dart_backfill --what financials   # 재무만
  python -m scripts.dart_backfill --start-year 2021

- DART 응답이 1건에 수십 초 걸릴 때가 있어 여러 요청을 동시에 보낸다 (재무 8개, 공시 6개월씩).
- 끝낸 구간은 Storage 의 meta/dart_backfill.json 에 기록 → 중단·한도 초과 뒤 다시 실행하면 이어서.
  (실패한 요청이 있던 구간은 '끝냄'으로 기록하지 않아 다음 실행 때 다시 받음)
- --minutes 를 넘기면 받은 데 까지 저장하고 끝냄 (GitHub 작업 시간 제한 대비).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time

import pandas as pd

from stockeye.config import load_config, data_dir
from stockeye.data.store import DataStore

log = logging.getLogger("stockeye.dart_backfill")

STATE_KEY = "meta/dart_backfill.json"
CORP_KEY = "meta/dart_corp.json"


class State:
    """끝낸 구간 기록 (Storage 가 있으면 거기, 없으면 data/ 폴더)"""

    def __init__(self, store: DataStore, sync=None):
        self.sync, self.path = sync, store.root / "dart_backfill.json"
        d = None
        if sync is not None:
            try:
                d = sync.get_json(STATE_KEY)
            except Exception:  # noqa: BLE001
                d = None
        if d is None and self.path.exists():
            d = json.loads(self.path.read_text(encoding="utf-8"))
        d = d or {}
        self.fin = set(d.get("fin_done", []))
        self.disc = set(d.get("disc_done", []))

    def save(self):
        d = {"fin_done": sorted(self.fin), "disc_done": sorted(self.disc),
             "updated": str(pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None))[:19]}
        self.path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        if self.sync is not None:
            try:
                self.sync.put_json(STATE_KEY, d)
            except Exception as e:  # noqa: BLE001
                log.warning("진행 상태 저장 실패: %s", e)


def _push(sync, names):
    if sync is not None:
        try:
            sync.push(datasets=names)
        except Exception as e:  # noqa: BLE001
            log.warning("Storage 올리기 실패 (다음에 다시): %s", e)


def corp_map(src, sync=None, max_age_days: int = 7) -> dict[str, str]:
    """DART 회사 코드 (내려받기가 수 분 걸려 Storage 에 7일 캐시)"""
    if sync is not None:
        try:
            c = sync.get_json(CORP_KEY)
            if c and (pd.Timestamp.now() - pd.Timestamp(c["at"])).days < max_age_days:
                return c["map"]
        except Exception:  # noqa: BLE001
            pass
    m = src.corp_codes()
    if sync is not None and m:
        try:
            sync.put_json(CORP_KEY, {"at": str(pd.Timestamp.now())[:19], "map": m})
        except Exception:  # noqa: BLE001
            pass
    return m


def backfill_financials(store: DataStore, years: list[int], sync=None, force=False, reprts=None,
                        deadline: float | None = None, state: State | None = None) -> bool:
    from stockeye.data.sources.dart_fin import DartFinancials, REPRT
    src = DartFinancials()
    state = state or State(store, sync)
    codes = sorted(set(store.load("ohlcv")["code"].unique()))
    corp = corp_map(src, sync)
    log.info("재무 대상: 시세가 있는 %d종목 중 DART 코드가 있는 %d종목", len(codes), sum(c in corp for c in codes))
    if not force:      # 예전 실행(진행 기록 전)에 받은 구간: 충분히 많으면 끝낸 것으로
        have = store.load("financials")
        if not have.empty:
            for (y, r), n in have.groupby(["year", "reprt"]).size().items():
                if n >= 1500:
                    state.fin.add(f"{y}-{r}")
    complete = True
    for y in years:
        for rc, name in REPRT.items():
            if reprts and rc not in reprts:
                continue
            key = f"{y}-{name}"
            if key in state.fin and not force:
                continue
            if deadline and time.time() > deadline:
                log.warning("시간 제한 → 재무 %s 부터는 다음 실행에서", key)
                complete = False
                break
            df = src.fetch(codes, [y], reprts=(rc,), corp_map=corp, deadline=deadline)
            if not df.empty:
                store.upsert("financials", df)
            if src.failed == 0 and not src.limit_hit:
                state.fin.add(key)
            else:
                complete = False
            log.info("재무 %s: %d건 %s", key, len(df),
                     "✅ 전부 성공" if src.failed == 0 else f"⚠ {src.failed}묶음 실패 → 다시 실행하면 그 부분만 받음")
            if src.limit_hit:
                log.warning("DART 하루 호출 한도 → 내일 다시 실행하면 이어서 받습니다.")
                break
        _push(sync, ["financials"])
        state.save()
        if src.limit_hit or (deadline and time.time() > deadline):
            return False
    return complete


def backfill_disclosures(store: DataStore, start: pd.Timestamp, end: pd.Timestamp, sync=None, force=False,
                         deadline: float | None = None, state: State | None = None, workers: int = 6) -> bool:
    from concurrent.futures import ThreadPoolExecutor
    from stockeye.data.sources.dart_source import DartSource
    state = state or State(store, sync)
    months = [p for p in pd.period_range(start, end, freq="M") if force or str(p) not in state.disc]
    log.info("공시: 받을 달 %d개", len(months))
    complete, limit = True, False

    def one(p):
        src = DartSource()
        if (deadline and time.time() > deadline):
            return p, pd.DataFrame(), 1, False
        try:
            df, failed = src.month(p.start_time, min(p.end_time.normalize(), end))
        except Exception as e:  # noqa: BLE001  한 달이 실패해도 나머지는 계속 (다음 실행 때 이 달만 다시)
            log.warning("공시 %s 받기 실패: %s", p, e)
            return p, pd.DataFrame(), 1, False
        return p, df, failed, getattr(src, "limit_hit", False)

    for i in range(0, len(months), workers):
        batch = months[i:i + workers]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            res = list(ex.map(one, batch))
        frames = [df for _, df, _, _ in res if not df.empty]
        if frames:
            store.upsert("disclosures", pd.concat(frames, ignore_index=True))
        for p, df, failed, lim in res:
            log.info("공시 %s: %d건 %s", p, len(df),
                     "✅" if not failed else f"⚠ {failed}건 실패 → 다시 실행하면 이 달만 다시 받음")
            if failed == 0 and not lim:
                state.disc.add(str(p))
            else:
                complete = False
            limit |= lim
        _push(sync, ["disclosures"])
        state.save()
        if limit:
            log.warning("DART 하루 호출 한도 → 내일 다시 실행하면 이어서 받습니다.")
            return False
        if deadline and time.time() > deadline:
            log.warning("시간 제한 → 남은 달은 다음 실행에서")
            return False
    return complete


def update_financials_recent(store: DataStore, sync=None, days: int = 10, minutes: float = 15) -> int:
    """일일 배치용: 최근 며칠 정기보고서(분기·반기·사업)를 낸 회사만 그 보고서를 새로 받음 (보통 수십 회 호출)"""
    from stockeye.data.sources.dart_fin import DartFinancials, periodic_filings
    disc = store.load("disclosures")
    since = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize() - pd.Timedelta(days=days)
    todo = periodic_filings(disc, since)
    if not todo:
        log.info("최근 %d일 정기보고서 제출 없음 → 재무 갱신 생략", days)
        return 0
    src = DartFinancials()
    corp = corp_map(src, sync)
    deadline = time.time() + minutes * 60
    n = 0
    for (y, rc), codes in sorted(todo.items()):
        df = src.fetch(sorted(codes), [y], reprts=(rc,), corp_map=corp, deadline=deadline)
        if not df.empty:
            store.upsert("financials", df)
            n += len(df)
        if time.time() > deadline:
            log.warning("재무 갱신 시간 제한(%d분) → 나머지는 내일", minutes)
            break
    log.info("재무 갱신: 정기보고서 %d묶음 → %d건", len(todo), n)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", default="all", choices=["all", "disclosures", "financials"])
    ap.add_argument("--start-year", type=int, default=2020)
    ap.add_argument("--force", action="store_true", help="이미 받은 기간도 다시")
    ap.add_argument("--local", action="store_true", help="Storage 를 쓰지 않고 이 PC 의 data/ 만")
    ap.add_argument("--minutes", type=float, default=320, help="이 시간이 지나면 저장하고 끝냄")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)

    import os
    if not os.getenv("DART_API_KEY"):
        sys.exit("DART_API_KEY 가 없습니다")
    t0 = time.time()
    deadline = t0 + args.minutes * 60
    cfg = load_config()
    store = DataStore(data_dir(cfg))
    sync = None
    from stockeye.cloud.client import enabled
    if enabled() and not args.local:
        from stockeye.cloud.sync import DataSync
        sync = DataSync(store)
        sync.pull()
    state = State(store, sync)
    today = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize()
    ok = True
    if args.what in ("all", "financials"):
        ok &= backfill_financials(store, list(range(args.start_year, today.year + 1)), sync, args.force,
                                  deadline=deadline, state=state)
    if args.what in ("all", "disclosures") and time.time() < deadline:
        ok &= backfill_disclosures(store, pd.Timestamp(f"{args.start_year}-01-01"), today, sync, args.force,
                                   deadline=deadline, state=state)

    d, f = store.load("disclosures"), store.load("financials")
    print("=" * 60)
    print(f"공시 {len(d):,}건 ({d['published_at'].min() if len(d) else '-'} ~ {d['published_at'].max() if len(d) else '-'})")
    print(f"공시 끝낸 달 {len(state.disc)}개")
    if len(f):
        print(f"재무 {len(f):,}건 / {f['code'].nunique():,}종목 / 연도·보고서별:")
        print(f.groupby(["year", "reprt"]).size().unstack().fillna(0).astype(int).to_string())
    print(f"{'완료' if ok else '일부만 받음 — 같은 작업을 다시 실행하면 이어서 받습니다'} ({(time.time() - t0) / 60:.0f}분)")


if __name__ == "__main__":
    main()
