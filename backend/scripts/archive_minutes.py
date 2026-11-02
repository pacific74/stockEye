"""1분봉 보관 — 장이 끝난 뒤 매일 (scripts_win/26_archive_minutes.bat, 작업 스케줄러 15:45)

  python -m scripts.archive_minutes                 # 자동: 장중이 아니면 놓친 날(최근 10거래일, 일봉 기준) + 오늘(15:35 이후, 네이버 시세 기준)을 저장
                                                    #   꺼져 있던 날은 PC 를 켠 뒤 처음 도는 장중 아닌 시각에 이어서 저장 (로그온 때·15:45)
  python -m scripts.archive_minutes --back 20       # 최근 20거래일 중 아직 없는 날을 일봉 기준으로 채움 (KIS 가 아직 주는 만큼)
  python -m scripts.archive_minutes --day 20261030
저장 대상: 거래대금 상위 150 + 등락 ±8% 이상(거래대금 30억↑) + 어제 상한가권 종목. 이미 저장된 파일은 건너뜀.
⚠ 22번과 동시에 돌리면 KIS 키가 겹침 (22번은 보통 15:20 에 끝남).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

log = logging.getLogger("stockeye.archive_minutes")


def fetch_save(kis, cache_dir, ds: str, code: str) -> str:
    cf = cache_dir / ds / f"{code}.parquet"
    if cf.exists():
        return "skip"
    try:
        b = kis.minute_bars_day(code, "090000", "153000", day=ds)
    except Exception as e:  # noqa: BLE001
        log.debug("%s %s: %s", ds, code, e)
        return "fail"
    if len(b) < 300:                     # 거래 거의 없는 종목·못 받은 날은 저장 안 함
        return "short"
    cf.parent.mkdir(parents=True, exist_ok=True)
    b.to_parquet(cf, index=False)
    return "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="", help="YYYYMMDD (없으면 오늘)")
    ap.add_argument("--back", type=int, default=0, help="최근 N거래일 채우기 (일봉 기준으로 종목 선택)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--lookback", type=int, default=10, help="자동 실행 때 놓친 날을 찾아볼 최근 거래일 수")
    a, _ = ap.parse_known_args()                   # 작업 스케줄러가 붙이는 'auto' 같은 인자는 무시
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)

    from stockeye.config import load_config, data_dir
    from stockeye.data.store import DataStore
    from stockeye.data.sources.kis_source import KISClient
    from stockeye.data.sources import naver_live
    from stockeye.engine.nextday import common_stock
    from stockeye.analysis import minute_archive as ma

    cfg = load_config()
    kc = cfg.get("kis", {})
    kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
    cache = data_dir(cfg) / "minute_cache"
    store = DataStore(data_dir(cfg))
    ls = store.load("listing")
    nm = dict(zip(ls["code"], ls["name"]))
    codes = [c for c in ls["code"] if common_stock(c, nm.get(c, ""))]
    state_dir = cache / "_universe"
    state_dir.mkdir(parents=True, exist_ok=True)
    today = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize()

    done_dir = cache / "_done"
    done_dir.mkdir(parents=True, exist_ok=True)
    done = {p.stem for p in done_dir.glob("*.txt")}
    now = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)
    jobs: list[tuple[str, list[str]]] = []                         # (YYYYMMDD, 종목들)

    def from_daily(oh, days, d):
        prev = days[days.index(d) - 1] if d in days and days.index(d) > 0 else None
        snap = oh[oh["date"] == d][["code", "chg_pct", "value"]]
        hot = ma.hot(oh[oh["date"] == prev][["code", "chg_pct"]]) if prev is not None else []
        return ma.pick(snap, hot)

    if a.back or a.day:
        oh = store.load("ohlcv")
        oh = oh[oh["code"].isin(codes)]
        days = sorted(oh["date"].unique())
        want = [pd.Timestamp(a.day)] if a.day else [pd.Timestamp(d) for d in days[-a.back:]]
        jobs += [(d.strftime("%Y%m%d"), from_daily(oh, days, d)) for d in want]
    else:
        if ma.in_market_window(now):
            print("지금은 장중(22번 실행 시간) → KIS 키가 겹치므로 15:35 이후(또는 08:35 이전)에 자동으로 이어서 보관합니다")
            return
        try:                                                      # 꺼져 있던 날의 일봉(종목 고르기용)을 클라우드에서 받아 둠
            from stockeye.cloud.client import Supabase, enabled
            from stockeye.cloud.sync import DataSync
            if enabled():
                DataSync(store, Supabase()).pull(["ohlcv", "listing"])
        except Exception as e:  # noqa: BLE001
            log.warning("일봉 동기화 실패 (있는 데이터로 진행): %s", e)
        oh = store.load("ohlcv")
        oh = oh[oh["code"].isin(codes)]
        days = sorted(oh["date"].unique())
        todo = ma.missing_days(days, done, a.lookback)
        todays = today.strftime("%Y%m%d")
        todo = [d for d in todo if d.strftime("%Y%m%d") != todays]
        jobs += [(d.strftime("%Y%m%d"), from_daily(oh, days, d)) for d in todo]    # 놓친 날 먼저 (일봉 기준)
        if today.weekday() < 5 and now.strftime("%H:%M") >= "15:35" and todays not in done and naver_live.is_trading_day() is not False:
            snap = naver_live.stocks(codes)                          # 오늘 (일봉이 아직 없으니 네이버 시세로)
            if not snap.empty:
                prev_files = sorted(p for p in state_dir.glob("*.json") if p.stem < todays)
                prev_hot = json.loads(prev_files[-1].read_text(encoding="utf-8")) if prev_files else []
                jobs.append((todays, ma.pick(snap, prev_hot)))
                (state_dir / f"{todays}.json").write_text(json.dumps(ma.hot(snap)), encoding="utf-8")
            else:
                print("네이버 시세를 받지 못함 — 오늘 분은 다음 실행 때 일봉으로 보관")
        if not jobs:
            print("보관할 날이 없음 (모두 완료)")
            return

    for ds, cs in jobs:
        t0 = time.time()
        with ThreadPoolExecutor(a.workers) as ex:
            res = list(ex.map(lambda c: fetch_save(kis, cache, ds, c), cs))
        cnt = {k: res.count(k) for k in ("ok", "skip", "short", "fail")}
        print(f"{ds}: 종목 {len(cs)}개 → 저장 {cnt['ok']} · 이미 있음 {cnt['skip']} · 짧음 {cnt['short']} · 실패 {cnt['fail']} ({(time.time() - t0) / 60:.1f}분)")
        if cnt["fail"] + cnt["short"] > len(cs) * 0.8 and cnt["ok"] == 0 and cnt["skip"] == 0:
            print("  ⚠ 거의 못 받음 — KIS 과거 분봉 보관 기간이 지난 날일 수 있음 (완료 표시 안 함)")
            if a.back:
                break
        else:
            (done_dir / f"{ds}.txt").write_text(f"{cnt}", encoding="utf-8")
    n = sum(1 for _ in cache.glob("2*/*.parquet"))
    print(f"보관 중인 분봉 파일 {n:,}개")


if __name__ == "__main__":
    main()
