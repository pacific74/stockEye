"""당일단타 케이스 비교 — PC 에서 (scripts_win/23_daytrade_cases.bat)

  python -m scripts.daytrade_cases --days 20 --top 80

여러 전략(케이스)을 같은 기간·같은 종목풀(전날 거래대금 상위)에서 한꺼번에 돌려 표로 비교한다:
  B0 지금 방식 · B1 지금+수급 · F1 외국인 전일 · F2 쌍끌이 · F5 외국인 5일 · G1 갭상승+수급 · S1 전일급등 ·
  M1 시초 거래대금 · O1 시초범위 돌파 · V1 급락 뒤 반등 · N1 NXT 프리마켓   (설명: stockeye/analysis/daytrade_cases.py)
각 케이스는 청산 시각(장마감 · 10:30 · 10:00 · 09:40)별로도 비교. 분봉은 15번과 같은 캐시(data/minute_cache) 를 씀 → 15번을 돌린 기간이면 KIS 를 안 부르고 몇 분.
결과는 data/cases/날짜시각.json (거래 목록 포함) 에 저장 → 나중에 규칙을 바꿔 다시 집계할 때 재사용
⚠ 과거 분봉엔 장중 수급·호가·뉴스가 없음 — 수급은 전일 일별 외국인·기관 순매수로 대신. 건수가 적으면(20건 미만) 우연일 수 있음
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time

import pandas as pd

log = logging.getLogger("stockeye.daytrade_cases")


def base_work(a: dict) -> dict:
    """지금 방식(B0) 계산 — 종목·하루 한 번 분 단위 계산 (별도 프로세스 가능)"""
    from stockeye.analysis import daytrade_eval as de
    sc = de.scan_day(a["bars"], a["prev_close"], adr=a["adr"], extra={"hi_n": a["hi"], "rebound": a["reb"]})
    return {"rank": de.rank_from_scan(sc, "09:10"), "sig": de.first_entry(sc, "09:10")}


def load_bars(kis, cache_dir, ds: str, code: str, no_cache: bool):
    cf = cache_dir / ds / f"{code}.parquet"
    if not no_cache and cf.exists():
        try:
            return pd.read_parquet(cf)
        except Exception:  # noqa: BLE001
            pass
    try:
        bars = kis.minute_bars_day(code, "090000", "153000", day=ds)
    except Exception as e:  # noqa: BLE001
        log.debug("%s %s 분봉 실패: %s", ds, code, e)
        return None
    if len(bars) > 300 and not no_cache:
        try:
            cf.parent.mkdir(parents=True, exist_ok=True)
            bars.to_parquet(cf, index=False)
        except Exception as e:  # noqa: BLE001
            log.warning("분봉 캐시 저장 실패 %s: %s", cf, e)
    return bars


def summarize(trades: list[dict]) -> dict:
    n = len(trades)
    if not n:
        return {"n": 0}
    pn = [t["pnl"] for t in trades]
    cnt = lambda k: sum(t["outcome"] == k for t in trades)  # noqa: E731
    win, stop = cnt("t2") + cnt("t1"), cnt("stop")
    return {"n": n, "win": round(win / (win + stop) * 100, 1) if win + stop else None, "avg": round(sum(pn) / n, 3),
            "sum": round(sum(pn), 1), "stop": round(stop / n * 100, 1), "t2": round(cnt("t2") / n * 100, 1),
            "days": len({t["date"] for t in trades})}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--top", type=int, default=80)
    ap.add_argument("--workers", type=int, default=0, help="지금 방식 계산에 쓸 프로세스 수 (0 = CPU − 1)")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--set", default="r1", help="r1 = 11개 케이스, r2 = V1 다듬기·결합, r3 = 09:39 마감 V7 결합, r4 = 미래 정보 없는 실시간 방식, r5 = 갭상승 + 지지·저항 손절·목표")
    ap.add_argument("--only", default="", help="쉼표로 구분한 케이스만 (예: F1,V1)")
    args = ap.parse_args()
    if args.workers <= 0:
        import os
        args.workers = max(1, min(6, (os.cpu_count() or 2) - 1))
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)

    from stockeye.config import load_config, data_dir
    from stockeye.data.store import DataStore
    from stockeye.data.sources.kis_source import KISClient
    from stockeye.engine.nextday import common_stock
    from stockeye.engine import daytrade as dt
    from stockeye.analysis import daytrade_cases as dc
    from stockeye.analysis import regime

    cfg = load_config()
    kc = cfg.get("kis", {})
    kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
    store = DataStore(data_dir(cfg))
    oh = store.load("ohlcv")
    if oh is None or oh.empty:
        sys.exit("일봉 데이터가 없습니다 — 먼저 4_daily.bat")
    flows = store.load("flows")
    if flows is None or flows.empty:
        print("⚠ 수급(flows) 데이터가 없어 외국인·기관 케이스는 건너뜀 — 4_daily.bat 로 받아 두세요")
    dates = sorted(oh["date"].unique())
    names = store.load("listing")
    nm = dict(zip(names["code"], names["name"])) if names is not None else {}
    mk = dict(zip(names["code"], names["market"])) if names is not None and "market" in names else {}
    idx_days = regime.from_frame(store.load("index"), keep=400)
    cache_dir = data_dir(cfg) / "minute_cache"
    sb = None
    try:
        from stockeye.cloud.client import Supabase, enabled
        sb = Supabase() if enabled() else None
    except Exception:  # noqa: BLE001
        sb = None
    cases = [c for c in ({"r2": dc.ROUND2, "r3": dc.ROUND3, "r4": dc.ROUND4, "r5": dc.ROUND5}.get(args.set, dc.CASES)) if not args.only or c[0] in {x.strip() for x in args.only.split(",")}]
    ex = None
    if args.workers > 1 and any(c[0].startswith("B") for c in cases):
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor
        ex = ProcessPoolExecutor(args.workers, mp_context=mp.get_context("spawn"))
    trades: list[dict] = []
    t0 = time.time()
    nxt_days = 0
    for di in range(max(2, len(dates) - args.days), len(dates)):
        day, prev = pd.Timestamp(dates[di]), pd.Timestamp(dates[di - 1])
        dkey, ds = day.strftime("%Y-%m-%d"), day.strftime("%Y%m%d")
        p = oh[oh["date"] == prev]
        p = p[[common_stock(c, nm.get(c, "")) for c in p["code"]]]
        val = p["value"] if "value" in p else p["close"] * p["volume"]
        topdf = p.assign(_v=val).sort_values("_v", ascending=False).head(args.top)
        codes = list(topdf["code"])
        prev_close = dict(zip(topdf["code"], topdf["close"]))
        bars = {}
        for c in codes:
            b = load_bars(kis, cache_dir, ds, c, args.no_cache)
            if b is not None and len(b) >= 10:
                bars[c] = b
        gap = {c: (float(b["open"].iloc[0]) / prev_close[c] - 1) * 100 for c, b in bars.items() if prev_close.get(c)}
        d = {"day": dkey, "codes": codes, "bars": bars, "prev_close": prev_close, "gap": gap,
             **dc.flow_features(flows, oh, dates, di, codes), "lvl": dc.daily_levels(oh, dates, di, codes), "nxt": None, "base": {}, "rank": {}}
        if sb:                                                         # NXT 프리마켓 등락 (22번이 매일 08:50 에 저장 — 기록 있는 날만)
            try:
                raw = sb.download(f"nxt/pre/{dkey}.json")
                if raw:
                    d["nxt"] = {c: float(v[1]) for c, v in json.loads(raw).items() if isinstance(v, list) and len(v) > 1}
                    nxt_days += 1
            except Exception:  # noqa: BLE001
                pass
        if any(c[0].startswith("B") for c in cases):                   # 지금 방식: 분 단위 계산 (가장 느린 부분)
            hist = oh[(oh["date"] <= prev) & (oh["date"] > prev - pd.Timedelta(days=45)) & oh["code"].isin(codes)]
            adrs = {c: dt.adr(g) for c, g in hist.groupby("code")}
            rebs = {m: regime.rebound(regime.prev_chg(idx_days, dkey, m), (idx_days.get(dkey) or {}).get(m)) for m in ("KOSPI", "KOSDAQ")}
            win30 = oh[(oh["date"] < day) & oh["code"].isin(codes) & oh["date"].isin(dates[max(0, di - 30):di])]
            hi30 = {c: (float(g["high"].max()) if len(g) >= 10 else None) for c, g in win30.groupby("code")}
            jobs = [{"bars": bars[c], "prev_close": prev_close.get(c), "adr": adrs.get(c), "hi": hi30.get(c),
                     "reb": rebs.get(mk.get(c) if mk.get(c) in rebs else "KOSPI")} for c in bars]
            outs = list(ex.map(base_work, jobs, chunksize=4)) if ex else [base_work(j) for j in jobs]
            for c, o in zip(bars, outs):
                d["rank"][c] = o["rank"]
                d["base"][c] = o["sig"]
        nd = 0
        for key, name, sel in cases:
            try:
                sigs = sel(d)
            except Exception as e:  # noqa: BLE001
                print(f"⚠ {key} {dkey}: {e}")
                continue
            for s in sigs:
                for xn, until in dc.EXITS:
                    g = dc.grade_sig(s, bars[s["code"]], until)
                    if g:
                        trades.append({"case": key, "date": dkey, "code": s["code"], "name": nm.get(s["code"], s["code"]),
                                       "exit": xn, "outcome": g["outcome"], "pnl": g["pnl"], "time": g["time"], "entry": g["entry"],
                                       "risk": s.get("risk"), "t1pct": s.get("t1pct"), "basis": s.get("basis")})
                        nd += xn == "장마감까지"
        print(f"{dkey}: 거래 {nd}건 (누적 {sum(t['exit'] == '장마감까지' for t in trades)} · {(time.time() - t0) / 60:.0f}분)")
    if ex:
        ex.shutdown()
    # ----- 결과 표 -----
    print(f"\n케이스 비교 (최근 {args.days}거래일 · 전날 거래대금 상위 {args.top} 풀 · 손절 2.5%/1차 +3%/2차 +5% (B 는 엔진 값) · NXT 기록 {nxt_days}일)")
    print("① 장마감까지 보유 (청산 규칙만):")
    hdr = f"  {'케이스':<34}{'건수':>5}{'승률':>7}{'평균%':>8}{'합계%':>8}{'손절%':>7}{'2차%':>6}{'일수':>5}"
    print(hdr)
    names_of = {k: n for k, n, _ in cases}
    for key, _, _ in cases:
        m = summarize([t for t in trades if t["case"] == key and t["exit"] == "장마감까지"])
        lab = f"{key} {names_of[key]}"
        print(f"  {lab:<34}" + (f"{m['n']:>5}{m['win'] if m['win'] is not None else '-':>7}{m['avg']:>8}{m['sum']:>8}{m['stop']:>7}{m['t2']:>6}{m['days']:>5}"
                              + ("  ← 건수 부족" if m["n"] < 20 else "") if m["n"] else "    0건"))
    print("\n② 청산 시각별 평균 손익% (건수):")
    print(f"  {'케이스':<34}" + "".join(f"{x[0]:>16}" for x in dc.EXITS))
    for key, _, _ in cases:
        row = ""
        for xn, _u in dc.EXITS:
            m = summarize([t for t in trades if t["case"] == key and t["exit"] == xn])
            row += f"{(str(m['avg']) + ' (' + str(m['n']) + ')') if m['n'] else '-':>16}"
        print(f"  {key + ' ' + names_of[key]:<34}{row}")
    best = sorted(((summarize([t for t in trades if t['case'] == k and t['exit'] == xn]), k, xn)
                   for k, _, _ in cases for xn, _u in dc.EXITS), key=lambda x: -(x[0].get("avg") or -99) if x[0]["n"] >= 20 else 99)
    good = [(m, k, xn) for m, k, xn in best if m["n"] >= 20][:5]
    print("\n상위 (건수 20 이상, 평균 손익 순):")
    for m, k, xn in good:
        print(f"  {k} {names_of[k]} · {xn}: {m['n']}건 · 승률 {m['win']}% · 평균 {m['avg']}% · 합계 {m['sum']}% · 손절 {m['stop']}%")
    print("  ※ 한 달 안팎 한 장세 · 같은 종목풀 · 거래 수가 적으면 우연 · 호가·뉴스·장중 수급 없음 · 비용 0.2% 포함")
    print("\n③ 날짜별 안정성 (10:00 청산 기준): 플러스 날 / 거래한 날 · 최악의 날 · 가장 좋은 하루 빼면 합계")
    for key, _, _ in cases:
        tt = [t for t in trades if t["case"] == key and t["exit"] == "10:00 청산"]
        if not tt:
            continue
        byd: dict[str, float] = {}
        for t in tt:
            byd[t["date"]] = byd.get(t["date"], 0.0) + t["pnl"]
        tot = sum(byd.values())
        print(f"  {key + ' ' + names_of[key]:<34}{sum(v > 0 for v in byd.values()):>3}/{len(byd):<3} 최악 {min(byd.values()):>7.1f}%  최고일 제외 합계 {tot - max(byd.values()):>7.1f}% (전체 {tot:.1f}%)")
    if any(t.get("risk") is not None for t in trades):
        print("\n④ 지지·저항 손절·목표 (장마감까지 기준): 평균 손절폭% · 1차 목표폭% · 손절 근거 상위")
        for key, _, _ in cases:
            tt = [t for t in trades if t["case"] == key and t["exit"] == "장마감까지" and t.get("risk") is not None]
            if not tt:
                continue
            from collections import Counter
            bs = ", ".join(f"{k} {v}" for k, v in Counter(t["basis"] for t in tt).most_common(3))
            print(f"  {key + ' ' + names_of[key]:<34}손절 {sum(t['risk'] for t in tt) / len(tt):.1f}% · 1차 +{sum(t['t1pct'] for t in tt) / len(tt):.1f}% · {bs}")
    out = data_dir(cfg) / "cases"
    out.mkdir(exist_ok=True)
    f = out / f"{pd.Timestamp.now():%Y%m%d_%H%M}.json"
    f.write_text(json.dumps({"days": args.days, "top": args.top, "trades": trades}, ensure_ascii=False), encoding="utf-8")
    print(f"→ 거래 목록 저장: {f}")


if __name__ == "__main__":
    main()
