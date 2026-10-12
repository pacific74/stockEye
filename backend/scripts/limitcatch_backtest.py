"""상한가포착 되돌려 보기 — PC 에서 가끔 (scripts_win/20_limitcatch_backtest.bat)

  python -m scripts.limitcatch_backtest --minutes 20     # 최근 20거래일 과거 1분봉 (KIS) · 10~30분
  python -m scripts.limitcatch_backtest --daily          # 5년 일봉 참고 (상한가 도달일 · 종가 잠김별 다음 날 시가) · 1~3분
  python -m scripts.limitcatch_backtest --check          # 과거 1분봉이 받아지는지 한 종목만 확인
  python -m scripts.limitcatch_backtest                  # 둘 다 (--minutes 20 --daily)

과거 1분봉: 날마다 고가 +20% 이상 · 거래대금 100억↑ 보통주 → 그날 분봉으로 도달 시각·풀림 재구성.
  호가 잔량은 과거 데이터가 없어 빼고 환산한 점수 (잔량 항목은 PC 가 매일 남기는 1분 기록으로 따로 검증).
  진입 가정 ① +27% 첫 분 종가 ② 상한가 도달 후 풀렸을 때만 체결 ③ 도달 분 무조건 체결(낙관)
  매수 뒤 +20% 아래로 밀리면 그 분 종가에 매도(조건 무효), 아니면 다음 날 시가 절반 · 09:30 까지 고점 −3% · 09:30 청산
결과 → 앱 '검증 > 상한가포착' (2025~2026 은 한 번만 확인하는 규칙 — 결과를 보고 조건을 바로 바꾸지 않기)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

import pandas as pd

log = logging.getLogger("stockeye.limitcatch_bt")


def candidates(oh: pd.DataFrame, listing: pd.DataFrame, days: int) -> list[tuple[pd.Timestamp, pd.Timestamp, list[str]]]:
    """최근 days 거래일: 그날 고가 +20%↑ · 거래대금 100억↑ 보통주 (다음 거래일이 있는 날만)"""
    from stockeye.engine import limitcatch as lc
    from stockeye.engine.nextday import common_stock
    nm = dict(zip(listing["code"], listing["name"]))
    dates = sorted(oh["date"].unique())
    piv = lambda col: oh.pivot(index="date", columns="code", values=col).sort_index()  # noqa: E731
    H, C, V = piv("high"), piv("close"), piv("volume")
    VAL = piv("value") if "value" in oh else C * V
    P = C.shift(1)
    out = []
    for di in range(max(61, len(dates) - days - 1), len(dates) - 1):
        D, N = pd.Timestamp(dates[di]), pd.Timestamp(dates[di + 1])
        ok = (H.loc[D] / P.loc[D] - 1 >= lc.MIN_CHG / 100) & (VAL.loc[D] >= lc.MIN_VALUE)
        codes = [c for c in ok[ok].index if common_stock(c, nm.get(c, ""))]
        out.append((D, N, codes))
    return out


def run_minutes(kis, oh, listing, sectors, days: int) -> dict[str, list[dict]]:
    from stockeye.analysis import limitcatch_eval as le
    nm = dict(zip(listing["code"], listing["name"]))
    rows: dict[str, list[dict]] = {k: [] for k in le.ASSUME}
    t0 = time.time()
    for D, N, codes in candidates(oh, listing, days):
        hist = oh[(oh["date"] < D) & oh["code"].isin(codes)]
        n = 0
        for code in codes:
            daily = hist[hist["code"] == code].sort_values("date").tail(60)
            if len(daily) < 20:
                continue
            prev = float(daily["close"].iloc[-1])
            try:
                m = kis.minute_bars_day(code, "090000", "153000", day=D.strftime("%Y%m%d"))
            except Exception:  # noqa: BLE001
                continue
            if m.empty:
                continue
            trades = le.replay_day(m, daily, prev)
            if not trades:
                continue
            nb = None
            if any(t.get("filled") and not t.get("invalid_px") for t in trades.values()):
                try:
                    nb = kis.minute_bars_day(code, "090000", "093000", day=N.strftime("%Y%m%d"))
                except Exception:  # noqa: BLE001
                    nb = None
            for k, t in trades.items():
                r = le.finish(t, nb)
                if r:
                    rows[k].append(r | {"date": D.strftime("%Y-%m-%d"), "code": code, "name": nm.get(code, code)})
                    n += 1
            if "a2" in trades and not trades["a2"].get("filled"):
                rows.setdefault("_unfilled", []).append({"date": D.strftime("%Y-%m-%d"), "code": code})
        print(f"{D:%Y-%m-%d}: 대상 {len(codes)} → 기록 {n} (누적 ③ {len(rows['a3'])} · {(time.time() - t0) / 60:.0f}분)")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily", action="store_true")
    ap.add_argument("--minutes", type=int, default=0)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.daily and not args.minutes and not args.check:
        args.daily, args.minutes = True, 20
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)
    from stockeye.config import load_config, data_dir
    from stockeye.data.store import DataStore
    from stockeye.analysis import limitcatch_eval as le
    cfg = load_config()
    store = DataStore(data_dir(cfg))
    oh, listing, sectors = store.load("ohlcv"), store.load("listing"), store.load("sectors")
    if oh is None or oh.empty:
        sys.exit("일봉 데이터가 없습니다 — 먼저 4_daily.bat")
    kis = None
    if args.minutes or args.check:
        from stockeye.data.sources.kis_source import KISClient
        kc = cfg.get("kis", {})
        kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
    if args.check:
        cands = [c for c in candidates(oh, listing, 5) if c[2]]
        if not cands:
            sys.exit("최근 5거래일에 +20% 종목이 없어 확인할 수 없음")
        D, _, codes = cands[-1]
        m = kis.minute_bars_day(codes[0], "090000", "153000", day=D.strftime("%Y%m%d"))
        print(f"{D:%Y-%m-%d} {codes[0]} 1분봉 {len(m)}개 {'OK' if len(m) > 300 else '← 부족 (과거 분봉 보관 기간·계좌 확인)'}")
        return
    minutes = daily = None
    if args.minutes:
        rows = run_minutes(kis, oh, listing, sectors, args.minutes)
        unf = len(rows.pop("_unfilled", []))
        minutes = {"note": f"과거 1분봉 {args.minutes}거래일 · 호가 잔량 없이 환산 점수 · 비용 0.25%",
                   "unfilled_a2": unf, **{k: le.report(v, recent=10) for k, v in rows.items()}}
        for k, name in le.ASSUME.items():
            t = minutes[k]["total"]
            print(f"\n[{name}] {t.get('n', 0)}건 · 승률 {t.get('win')}% · 평균 {t.get('pnl')}% · 시가 {t.get('open_pnl')}%"
                  f" · 종가 잠김 {t.get('hold')}% · 조건 무효 {t.get('invalid')}%")
            for b, v in minutes[k]["by_score"].items():
                print(f"   점수 {b}: {v.get('n')}건 · 평균 {v.get('pnl')}% · 잠김 {v.get('hold')}%")
        print(f"\n② 에서 못 산 날(도달 후 끝까지 잠김): {unf}건")
    if args.daily:
        t0 = time.time()
        daily = le.daily_reference(oh, listing)
        print(f"\n[5년 일봉 참고 · {(time.time() - t0) / 60:.0f}분] 상한가 도달 {daily['n']}건 · 종가 잠김 {daily['hold']}%")
        for k in ("종가 잠김", "도달 후 풀림"):
            if k in daily:
                v = daily[k]
                print(f"   {k}: {v['n']}건 · 상한가 매수→다음 날 시가 {v['lim_pnl']}% · 종가 매수→시가 {v['close_pnl']}%")
    if not args.dry_run:
        from stockeye.cloud.client import Supabase, enabled
        if enabled():
            le.publish(Supabase(), minutes=minutes, daily=daily)
            print("→ 앱 '검증' 에 올림")


if __name__ == "__main__":
    main()
