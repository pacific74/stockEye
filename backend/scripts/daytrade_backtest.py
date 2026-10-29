"""당일단타 되돌려 보기 (과거 1분봉) — PC 에서 가끔 (scripts_win/15_daytrade_backtest.bat)

  python -m scripts.daytrade_backtest --check            # KIS 과거 분봉 API 가 되는지 먼저 확인 (삼성전자 어제)
  python -m scripts.daytrade_backtest --days 20 --top 80 # 최근 20거래일 · 전날 거래대금 상위 80종목

날마다: 전날 거래대금 상위 top 종목(보통주)의 그날 1분봉(09:00~15:30)을 받아 09:05~10:30 을 1분씩 다시 계산
→ 종목마다 첫 '진입 조건 충족' 에서 진입 → 그 뒤 분봉으로 1·2차 익절 / 손절 / 장 마감 청산 → 결과를 '검증' 에 올림
받은 분봉은 data/minute_cache/날짜/종목.parquet 로 저장 → 다음 실행부터는 KIS 를 안 부르고 파일에서 (몇 분) — 규칙만 바꿔 다시 비교할 때 빠름
(처음 받을 때 호출 수: 종목×날짜마다 약 13번. 20일×80종목 ≈ 2만 번 → 초당 15번이면 20~25분)
⚠ 과거 분봉은 KIS 실전 계좌 키로만, 보관 기간 안에서만 받을 수 있음. 호가·뉴스·지수는 없어 중립으로 계산.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

import pandas as pd

log = logging.getLogger("stockeye.daytrade_bt")

# 규칙별 비교: 같은 분봉으로 규칙을 하나씩 켜 보며 (신고가 제외 · 반등장 · 유형 한정)
VARIANTS = [("규칙 넣기 전 (기준 80)", False, False, None), ("+ 신고가 돌파 제외", True, False, None),
            ("+ 반등장 규칙", False, True, None), ("+ 둘 다 (지금 DT-0.4)", True, True, None),
            ("  └ 돌파형만", True, True, "돌파"), ("  └ 눌림목형만", True, True, "눌림목")]
NOW = 3                                                               # 앱 '검증' 에 올리는 건 지금 규칙(DT-0.4)
SHORT_AT, SHORT_N = "09:10", (5, 10, 15)


def work(a: dict) -> dict:
    """종목 하나·하루: 규칙 조합(신고가·반등장)마다 분 단위 계산을 한 번씩만 하고, 진입 시점·유형·점수 기준은 그 결과에서 골라냄
    (예전엔 비교마다 다시 계산해 느렸음 · 별도 프로세스에서도 돌 수 있게 맨 위 함수)"""
    from stockeye.analysis import daytrade_eval as de
    bars, pc, adr, hi, reb, ident, compare = a["bars"], a["prev_close"], a["adr"], a["hi"], a["reb"], a["ident"], a["compare"]
    scans = {}

    def sc(uh, ur):
        k = (bool(uh), bool(ur))
        if k not in scans:
            scans[k] = de.scan_day(bars, pc, adr=adr, extra={"hi_n": hi if uh else None, "rebound": reb if ur else None})
        return scans[k]

    def entry(uh, ur, start="09:05", min_score=None, only=None):
        s = de.first_entry(sc(uh, ur), start, min_score, only)
        if not s:
            return None
        return de.grade({**s, **ident}, bars)
    out = {"v": [entry(uh, ur, only=ot) for _, uh, ur, ot in VARIANTS],
           "rank": de.rank_from_scan(sc(True, True), SHORT_AT), "short": entry(True, True, SHORT_AT),
           "low": entry(True, True, min_score=compare) if compare else None}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--top", type=int, default=80)
    ap.add_argument("--compare", type=float, default=75.0,
                    help="기준을 이 점수까지 낮췄다면 어땠나도 같이 비교 (기본 75, 0 이면 비교 안 함). 앱에 올리는 건 지금 기준(80)만")
    ap.add_argument("--no-cache", action="store_true", help="받은 분봉을 파일(data/minute_cache)에 저장·재사용하지 않음")
    ap.add_argument("--workers", type=int, default=0, help="계산에 쓸 프로세스 수 (기본 0 = CPU 코어 수 − 1, 1 이면 한 프로세스)")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.workers <= 0:
        import os
        args.workers = max(1, min(6, (os.cpu_count() or 2) - 1))
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)

    from stockeye.config import load_config, data_dir
    from stockeye.data.store import DataStore
    from stockeye.data.sources.kis_source import KISClient
    from stockeye.engine.nextday import common_stock
    from stockeye.analysis import daytrade_eval as de
    from stockeye.analysis import regime
    from stockeye.engine import daytrade as dt

    cfg = load_config()
    kc = cfg.get("kis", {})
    kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
    store = DataStore(data_dir(cfg))
    oh = store.load("ohlcv")
    if oh is None or oh.empty:
        sys.exit("일봉 데이터가 없습니다 — 먼저 4_daily.bat")
    dates = sorted(oh["date"].unique())
    if args.check:
        d = pd.Timestamp(dates[-1]).strftime("%Y%m%d")
        b = kis.minute_bars_day("005930", "090000", "153000", day=d)
        print(f"삼성전자 {d} 1분봉 {len(b)}개" + (f" ({b['time'].iloc[0]:%H:%M}~{b['time'].iloc[-1]:%H:%M})" if len(b) else ""))
        print("→ 되돌려 보기 가능" if len(b) > 300 else "→ 과거 분봉을 받지 못함 (실전 계좌 키인지·보관 기간 확인)")
        return
    names = store.load("listing")
    nm = dict(zip(names["code"], names["name"])) if names is not None else {}
    mk = dict(zip(names["code"], names["market"])) if names is not None and "market" in names else {}
    idx_days = regime.from_frame(store.load("index"), keep=400)        # {날짜: {KOSPI: %, KOSDAQ: %}}
    res = {v[0]: [] for v in VARIANTS}
    cache_dir = data_dir(cfg) / "minute_cache"
    rows, low_rows, t0, reb_days = [], [], time.time(), []
    short = {"09:10 이후 진입 (전체 종목)": [], **{f"09:10 점수 상위 {n}개만": [] for n in SHORT_N}}
    ex = None
    if args.workers > 1:                                               # 계산(CPU)을 여러 프로세스로 — 분봉 받기·읽기는 그대로 한 줄
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor
        ex = ProcessPoolExecutor(args.workers, mp_context=mp.get_context("spawn"))
    for di in range(max(1, len(dates) - args.days), len(dates)):
        day, prev = pd.Timestamp(dates[di]), pd.Timestamp(dates[di - 1])
        p = oh[oh["date"] == prev]
        p = p[[common_stock(c, nm.get(c, "")) for c in p["code"]]]
        val = p["value"] if "value" in p else p["close"] * p["volume"]
        top = p.assign(_v=val).sort_values("_v", ascending=False).head(args.top)
        prev_close = dict(zip(top["code"], top["close"]))
        hist = oh[(oh["date"] <= prev) & (oh["date"] > prev - pd.Timedelta(days=45)) & oh["code"].isin(top["code"])]
        adrs = {c: dt.adr(g) for c, g in hist.groupby("code")}
        ds = day.strftime("%Y%m%d")
        n_sig = 0
        dkey = day.strftime("%Y-%m-%d")
        rebs = {m: regime.rebound(regime.prev_chg(idx_days, dkey, m), (idx_days.get(dkey) or {}).get(m)) for m in ("KOSPI", "KOSDAQ")}
        if any(rebs.values()):
            reb_days.append(dkey)
        win30 = oh[(oh["date"] < day) & oh["code"].isin(top["code"])]
        win30 = win30[win30["date"].isin(dates[max(0, di - 30):di])]    # 앱과 같게 직전 30거래일 고가
        hi30 = {c: (float(g["high"].max()) if len(g) >= 10 else None) for c, g in win30.groupby("code")}
        jobs = []
        for code in top["code"]:
            cf = cache_dir / ds / f"{code}.parquet"
            bars = None
            if not args.no_cache and cf.exists():                     # 과거 분봉은 안 바뀜 → 한 번 받은 건 파일에서
                try:
                    bars = pd.read_parquet(cf)
                except Exception:  # noqa: BLE001
                    bars = None
            if bars is None:
                try:
                    bars = kis.minute_bars_day(code, "090000", "153000", day=ds)
                except Exception as e:  # noqa: BLE001
                    log.debug("%s %s 분봉 실패: %s", ds, code, e)
                    continue
                if len(bars) > 300 and not args.no_cache:             # 장 전체가 온 것만 저장 (중간에 끊긴 건 저장 안 함)
                    try:
                        cf.parent.mkdir(parents=True, exist_ok=True)
                        bars.to_parquet(cf, index=False)
                    except Exception as e:  # noqa: BLE001
                        log.warning("분봉 캐시 저장 실패 %s: %s", cf, e)
            if bars.empty:
                continue
            reb = rebs.get(mk.get(code) if mk.get(code) in rebs else "KOSPI")
            jobs.append({"bars": bars, "prev_close": prev_close.get(code), "adr": adrs.get(code), "hi": hi30.get(code), "reb": reb,
                         "ident": {"date": dkey, "code": code, "name": nm.get(code, code)}, "compare": args.compare})
        outs = list(ex.map(work, jobs, chunksize=4)) if ex else [work(j) for j in jobs]
        pool = []
        for o in outs:
            for vi, ((vn, _, _, _), g) in enumerate(zip(VARIANTS, o["v"])):
                if g:
                    res[vn].append(g)
                    if vi == NOW:
                        rows.append(g)
                        n_sig += 1
            pool.append((o["rank"], o["short"]))
            if o["low"]:
                low_rows.append(o["low"])
        ranked = sorted([p for p in pool if p[0] is not None], key=lambda p: -p[0])
        short["09:10 이후 진입 (전체 종목)"].extend(g for _, g in pool if g)
        for n in SHORT_N:
            short[f"09:10 점수 상위 {n}개만"].extend(g for _, g in ranked[:n] if g)
        print(f"{day:%Y-%m-%d}: 신호 {n_sig}건 (누적 {len(rows)} · {(time.time() - t0) / 60:.0f}분)")
    if ex:
        ex.shutdown()
    rep = de.report(rows)
    rep.update({"universe": f"전날 거래대금 상위 {args.top}", "note": "호가·뉴스·지수 없이 중립으로 계산한 되돌려 보기 (신고가 제외·반등장 규칙 적용)",
                "version": dt.VERSION})
    t = rep["total"]
    print(f"\n합계 {t.get('n', 0)}건 · 승률 {t.get('win')}% · 평균 손익 {t.get('pnl')}%")
    for k, v in rep["by_type"].items():
        print(f"  {k}: {v.get('n')}건 · 승률 {v.get('win')}% · 평균 {v.get('pnl')}% · 2차 {v.get('t2')}% 1차 {v.get('t1')}%"
              f" 손절 {v.get('stop')}% 마감 {v.get('close')}%")
    if args.compare:
        def line(name, rs):
            m = de.summary(rs)
            return (f"  {name:<22} {m.get('n', 0):>4}건 · 승률 {m.get('win')}% · 평균 {m.get('pnl')}% · 합계 {m.get('pnl_sum')}%"
                    f" · 2차 {m.get('t2')}% 1차 {m.get('t1')}% 손절 {m.get('stop')}% 마감 {m.get('close')}%") if m.get("n") else f"  {name:<22}    0건"
        mid = [r for r in low_rows if (r.get("score") or 0) < 80]
        print(f"\n점수 기준 비교 (같은 기간·종목 · 호가·뉴스·지수 없이 환산한 점수)")
        print(line("기준 80 (현재)", rows))
        print(line(f"기준 {args.compare:g} (낮춤)", low_rows))
        print(line(f"  └ 진입 시점 점수 {args.compare:g}~80 미만", mid))
        print("  ※ 낮춘 기준은 80 보다 일찍 진입할 수 있어 80↑ 구간 결과도 달라질 수 있음 · 건수가 적으면 우연일 수 있음")
    print(f"\n규칙별 비교 (같은 기간·종목 · 80점 기준 · 반등장으로 본 날 {len(reb_days)}일: {', '.join(reb_days) or '없음'})")
    for vn, _, _, _ in VARIANTS:
        m = de.summary(res[vn])
        print((f"  {vn:<24} {m['n']:>4}건 · 승률 {m.get('win')}% · 평균 {m.get('pnl')}% · 합계 {m.get('pnl_sum')}%"
               f" · 2차 {m.get('t2')}% 1차 {m.get('t1')}% 손절 {m.get('stop')}% 마감 {m.get('close')}%") if m.get("n") else f"  {vn:<24}    0건")
    print("  ※ 반등장 판정은 그날 종가 등락률 기준(실전은 장중 등락·갭) · 신고가는 직전 30거래일 고가 · 같은 달 한 장세라 우연 가능")
    print(f"\n후보 추리기 비교 (09:10 까지 점수 순위 → 상위 N개만 09:10 이후 진입 · 지금 규칙 · 80점 기준)")
    for vn, rs in [("지금 방식 (09:05부터 전체)", res[VARIANTS[NOW][0]]), *short.items()]:
        m = de.summary(rs)
        print((f"  {vn:<26} {m['n']:>4}건 · 승률 {m.get('win')}% · 평균 {m.get('pnl')}% · 합계 {m.get('pnl_sum')}%"
               f" · 2차 {m.get('t2')}% 1차 {m.get('t1')}% 손절 {m.get('stop')}% 마감 {m.get('close')}%") if m.get("n") else f"  {vn:<26}    0건")
    print("\n  후보 추리기 × 유형 (돌파형 / 눌림목형)")
    for vn, rs in short.items():
        for ty in ("돌파", "눌림목"):
            m = de.summary([r for r in rs if r.get("type") == ty])
            print(f"    {vn:<24} {ty:<3} {m['n']:>3}건 · 승률 {m.get('win')}% · 평균 {m.get('pnl')}% · 합계 {m.get('pnl_sum')}% · 손절 {m.get('stop')}%"
                  if m.get("n") else f"    {vn:<24} {ty:<3}   0건")
    print("  ※ 수급은 과거 분봉에 없어 가격·거래량·거래대금 점수로만 순위를 매김 (실전은 수급이 더해짐)")
    rep["shortlist"] = {vn: de.summary(rs) for vn, rs in short.items()}
    rep["rules"] = {vn: de.summary(res[vn]) for vn, _, _, _ in VARIANTS}
    rep["reb_days"] = reb_days
    if not args.dry_run:
        from stockeye.cloud.client import Supabase, enabled
        if enabled():
            de.publish(Supabase(), backtest=rep)
            print("→ 앱 '검증' 에 올림")


if __name__ == "__main__":
    main()
