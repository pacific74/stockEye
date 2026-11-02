"""상한가 다음날 분봉 규칙 비교 — PC 에서 (scripts_win/25_limitup_minute.bat)

  python -m scripts.limitup_minute --days 25

최근 N거래일 사이에 '상한가 마감' 한 종목의 다음날 1분봉(KIS 과거 분봉, 15번과 같은 캐시)을 받아:
  · 진입: 시가 매수 / 시초 3분 고점 돌파(09:10 까지)
  · 청산: 손절 −3%(시초범위 저점) + '진입 후 N분 안에 +x% 안 되면 매도' + 시간 청산(09:40 · 10:30 · 장마감) + (확인 뒤 본전 손절)
을 표로 비교. 시가가 이미 상한가 근처(+29%↑)면 살 수 없으니 제외.
⚠ 분봉은 보관 기간이 짧아 표본이 수십 건. 22번과 동시에 돌리지 마세요 (KIS 키 공유).
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
import time

import numpy as np
import pandas as pd

log = logging.getLogger("stockeye.limitup_minute")

MINS = (3, 5, 10, 15)
PCTS = (0.5, 1.0, 2.0)
UNTILS = ("09:40", "10:30", None)


def stat(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    p = np.array([r["pnl"] for r in rows])
    return {"n": n, "avg": float(p.mean()), "med": float(np.median(p)), "win": float((p > 0).mean() * 100),
            "stop": float(np.mean([r["why"] in ("손절", "본전") for r in rows]) * 100), "sum": float(p.sum())}


def fmt(s: dict) -> str:
    return "     -" if not s["n"] else f"{s['avg']:6.2f}%({s['n']})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=25, help="다음날(D+1)이 최근 몇 거래일 안인 상한가만")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--stops", default="3,5,7,10", help="비교할 손절폭(%)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)
    from stockeye.config import load_config, data_dir
    from stockeye.data.store import DataStore
    from stockeye.data.sources.kis_source import KISClient
    from stockeye.engine.nextday import common_stock
    from stockeye.analysis import limitup_min as lm

    cfg = load_config()
    kc = cfg.get("kis", {})
    kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
    store = DataStore(data_dir(cfg))
    oh = store.load("ohlcv")
    ls = store.load("listing")
    nm = dict(zip(ls["code"], ls["name"]))
    dates = sorted(oh["date"].unique())
    cut = pd.Timestamp(dates[max(0, len(dates) - args.days)])
    oh = oh[oh["date"] >= pd.Timestamp(dates[max(0, len(dates) - args.days - 3)])].sort_values(["code", "date"])
    oh = oh[oh["code"].isin([c for c in oh["code"].unique() if common_stock(c, nm.get(c, ""))])]
    g = oh.groupby("code", sort=False)
    oh["next_date"] = g["date"].shift(-1)
    oh["prev_value"] = g["value"].shift(1)
    ev = oh[(oh.chg_pct >= 29.0) & (oh.chg_pct <= 30.6) & (oh.close >= oh.high * 0.999) & (oh.prev_value >= 1e9)
            & oh.next_date.notna() & (oh.next_date >= cut)]
    print(f"상한가 마감 → 다음날이 {cut:%Y-%m-%d} 이후인 종목 {len(ev)}건")
    cache = data_dir(cfg) / "minute_cache"
    items, miss, t0 = [], 0, time.time()
    for _, r in ev.iterrows():
        ds = pd.Timestamp(r.next_date).strftime("%Y%m%d")
        cf = cache / ds / f"{r.code}.parquet"
        bars = None
        if cf.exists() and not args.no_cache:
            try:
                bars = pd.read_parquet(cf)
            except Exception:  # noqa: BLE001
                bars = None
        if bars is None:
            try:
                bars = kis.minute_bars_day(r.code, "090000", "153000", day=ds)
            except Exception as e:  # noqa: BLE001
                log.warning("%s %s 분봉 실패: %s", ds, r.code, e)
                bars = None
            if bars is not None and len(bars) > 300 and not args.no_cache:
                cf.parent.mkdir(parents=True, exist_ok=True)
                bars.to_parquet(cf, index=False)
        if bars is None or len(bars) < 100:
            miss += 1
            continue
        items.append({"code": r.code, "name": nm.get(r.code, r.code), "date": pd.Timestamp(r.next_date).strftime("%Y-%m-%d"),
                      "prev_close": float(r.close), "bars": bars.reset_index(drop=True)})
    print(f"분봉 받음 {len(items)}건 · 못 받음 {miss}건 ({(time.time() - t0) / 60:.1f}분)")
    if not items:
        sys.exit("분봉을 받지 못했습니다 — 15번 --check 로 KIS 과거 분봉이 되는지 먼저 확인")
    stops = [float(x) for x in args.stops.split(",") if x.strip()]
    rows = []

    def add(item, entry_name, ent, rule, stop, **kw):
        if not ent:
            return
        r = lm.run_exit(item["bars"], ent, **kw)
        gap = (float(item["bars"]["open"].iloc[0]) / item["prev_close"] - 1) * 100
        rows.append({"entry": entry_name, "stop": stop, "rule": rule, "code": item["code"], "name": item["name"], "date": item["date"],
                     "gap": round(gap, 2), "pnl": round(r["pnl"], 3), "why": r["why"], "time": r["time"]})

    RULES = [("기본", {}), ("확인 5분/+1%", dict(confirm_min=5, confirm_pct=1.0)), ("확인 10분/+1%", dict(confirm_min=10, confirm_pct=1.0)),
             ("확인 5분/+0.5%+본전", dict(confirm_min=5, confirm_pct=0.5, be=True)), ("확인 10분/+1%+본전", dict(confirm_min=10, confirm_pct=1.0, be=True))]
    for it in items:
        b, pc = it["bars"], it["prev_close"]
        for st in stops:
            for en, ent in (("시가", lm.entry_open(b, pc, st / 100)), ("돌파", lm.entry_orb(b, pc, stop=st / 100))):
                for u in UNTILS:
                    for rn, kw in RULES:
                        add(it, en, ent, f"{rn}|{u or '장마감'}", st, until=u, **kw)
    df = pd.DataFrame(rows)
    nb = {en: int(((df.entry == en) & (df.stop == stops[0]) & (df.rule == "기본|09:40")).sum()) for en in df.entry.unique()}
    print(f"\n진입 가능 건수: {nb}  (시가가 상한가 근처인 종목은 제외)")
    for en in ("시가", "돌파"):
        d0 = df[df.entry == en]
        if d0.empty:
            continue
        print(f"\n===== 진입: {en} =====  (평균 손익%(건수) · 중앙값 · 손절 비율, 비용 0.2% 포함)")
        for st in stops:
            d = d0[d0.stop == st]
            print(f"  -- 손절 −{st:g}% --          " + "".join(f"{u or '장마감':>13}" for u in UNTILS))
            for rn, _ in RULES:
                cells = ""
                for u in UNTILS:
                    s_ = stat(d[d.rule == f"{rn}|{u or '장마감'}"].to_dict("records"))
                    cells += f"{fmt(s_):>13}"
                print(f"  {rn:<22}" + cells)
            g = d[d.rule == "기본|10:30"]
            if len(g):
                sx = stat(g.to_dict("records"))
                print(f"     (기본·10:30: 중앙 {sx['med']:.2f}% · 승률 {sx['win']:.0f}% · 손절 {sx['stop']:.0f}%)")
        best = []
        for (st, rule), gdf in d0.groupby(["stop", "rule"]):
            s_ = stat(gdf.to_dict("records"))
            if s_["n"] >= 15:
                best.append((s_["avg"], st, rule, s_))
        best.sort(reverse=True)
        print("  상위 (건수 15 이상):")
        for avg, st, rule, s_ in best[:5]:
            print(f"    손절 −{st:g}% · {rule}: {s_['n']}건 · 평균 {avg:.2f}% · 중앙 {s_['med']:.2f}% · 승률 {s_['win']:.0f}% · 손절 {s_['stop']:.0f}%")
        if best:
            top = d0[(d0.stop == best[0][1]) & (d0.rule == best[0][2])]
            bb = pd.cut(top.gap, [-50, 0, 5, 10, 20, 40], labels=["≤0", "0~5", "5~10", "10~20", ">20"])
            print("  └ 1위 규칙의 갭 구간별: " + " | ".join(f"{k} {stat(g.to_dict('records'))['avg']:.2f}%({len(g)})" for k, g in top.groupby(bb, observed=True)))
    print("\n※ 표본이 수십 건이라 우연일 수 있음. 일봉 결과(2021~)에서는 시가 매수 → 종가가 평균 −2.55%였음. 비교 기준으로 보세요.")
    out = data_dir(cfg) / "cases"
    out.mkdir(exist_ok=True)
    f = out / f"limitup_min_{pd.Timestamp.now():%Y%m%d_%H%M}.json"
    f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"→ 거래 목록 저장: {f}")


if __name__ == "__main__":
    main()
