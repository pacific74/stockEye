"""종가배팅 되돌려 보기 — PC 에서 가끔 (scripts_win/17_closingbet_backtest.bat)

  python -m scripts.closingbet_backtest --daily          # 5년 일봉 (장 후반 매수세·뉴스 없이 환산) · 5~10분
  python -m scripts.closingbet_backtest --minutes 20     # 최근 20거래일 과거 1분봉 (KIS) · 30분 안팎
  python -m scripts.closingbet_backtest                  # 둘 다
날마다 '매수 후보' 점수 상위 3 → 그날 종가 매수 → 다음 날 오전(10:30 까지) 청산 규칙 → 결과를 '검증' 에 올림
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

import pandas as pd

log = logging.getLogger("stockeye.closingbet_bt")


def run_minutes(kis, oh, listing, index, sectors, days: int, top: int) -> list[dict]:
    from stockeye.engine import closingbet as cb
    from stockeye.engine.nextday import common_stock
    from stockeye.analysis.closingbet_eval import PICK
    nm = dict(zip(listing["code"], listing["name"]))
    mk = dict(zip(listing["code"], listing["market"])) if "market" in listing else {}
    sec = dict(zip(sectors["code"], sectors["sector"])) if sectors is not None and len(sectors) else {}
    dates = sorted(oh["date"].unique())
    ki = index[index["code"].isin(["KOSPI", "KOSDAQ"])].pivot(index="date", columns="code", values="close").sort_index()
    kchg = (ki / ki.shift(1) - 1) * 100
    rows, t0 = [], time.time()
    for di in range(max(61, len(dates) - days - 1), len(dates) - 1):
        D, N = pd.Timestamp(dates[di]), pd.Timestamp(dates[di + 1])
        day = oh[oh["date"] == D].copy()
        day = day[[common_stock(c, nm.get(c, "")) for c in day["code"]]]
        day["chg"] = day["chg_pct"] if "chg_pct" in day else 0.0
        day["sector"] = day["code"].map(sec)
        sec_mean = day.groupby("sector")["chg"].mean().to_dict()
        val = day["value"] if "value" in day else day["close"] * day["volume"]
        top_codes = day.assign(_v=val).sort_values("_v", ascending=False).head(top)["code"].tolist()
        hist = oh[(oh["date"] < D) & oh["code"].isin(top_codes)]
        res = []
        for code in top_codes:
            daily = hist[hist["code"] == code].sort_values("date").tail(60)
            if len(daily) < 30:
                continue
            try:
                m = kis.minute_bars_day(code, "090000", "153000", day=D.strftime("%Y%m%d"))
            except Exception:  # noqa: BLE001
                continue
            if m.empty:
                continue
            vol = float(m["volume"].sum())
            value = float(m["value"].iloc[-1]) if "value" in m and m["value"].iloc[-1] > 0 else float((m["close"] * m["volume"]).sum())
            today = {"open": float(m["open"].iloc[0]), "high": float(m["high"].max()), "low": float(m["low"].min()),
                     "close": float(m["close"].iloc[-1]), "volume": vol, "value": value,
                     "vwap": value / vol if vol > 0 else None, "prev_close": float(daily["close"].iloc[-1])}
            mkt = mk.get(code, "KOSPI")
            ic = float(kchg.at[D, mkt]) if D in kchg.index and mkt in kchg and pd.notna(kchg.at[D, mkt]) else None
            r = cb.evaluate(daily, today, m, {"idx_chg": ic, "sector_chg": sec_mean.get(sec.get(code)),
                                               "now": pd.Timestamp(f"{D:%Y-%m-%d} 15:20"), "rescale_missing": True})
            if r["status"] == "매수 후보":
                res.append((r["score"], code, r))
        n = 0
        for sc, code, r in sorted(res, key=lambda x: -x[0])[:PICK]:
            try:
                nb = kis.minute_bars_day(code, "090000", "103000", day=N.strftime("%Y%m%d"))
            except Exception:  # noqa: BLE001
                continue
            if nb.empty:
                continue
            s = cb.simulate_next(nb, r["entry"], r["stop"], r["t1"], r["t2"])
            o = float(nb["open"].iloc[0])
            rows.append({"date": D.strftime("%Y-%m-%d"), "code": code, "name": nm.get(code, code), "score": sc,
                         "type": r["type"], "gap_grade": r["gap"]["grade"], "chg_pct": r["chg_pct"],
                         "open_pnl": round((o / r["entry"] - 1 - cb.COST) * 100, 3), **s})
            n += 1
        print(f"{D:%Y-%m-%d}: 매수 후보 {len(res)} → {n}건 (누적 {len(rows)} · {(time.time() - t0) / 60:.0f}분)")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily", action="store_true")
    ap.add_argument("--minutes", type=int, default=0)
    ap.add_argument("--top", type=int, default=80)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.daily and not args.minutes:
        args.daily, args.minutes = True, 20
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)
    from stockeye.config import load_config, data_dir
    from stockeye.data.store import DataStore
    from stockeye.analysis import closingbet_eval as ce
    cfg = load_config()
    store = DataStore(data_dir(cfg))
    oh, listing, index, sectors = store.load("ohlcv"), store.load("listing"), store.load("index"), store.load("sectors")
    if oh is None or oh.empty:
        sys.exit("일봉 데이터가 없습니다 — 먼저 4_daily.bat")
    daily = minutes = None

    def show(title, rep):
        t = rep["total"]
        print(f"\n[{title}] {t.get('n', 0)}건 · 이긴 비율 {t.get('win')}% · 평균 {t.get('pnl')}% · 시가 매도 평균 {t.get('open_pnl')}%"
              f" · 갭 하락 {t.get('gap_down')}%")
        for k, v in (rep.get("by_year") or {}).items():
            print(f"   {k}: {v.get('n')}건 · 평균 {v.get('pnl')}% · 시가 매도 {v.get('open_pnl')}%")

    if args.daily:
        t0 = time.time()
        rows = ce.daily_backtest(oh, index, listing, sectors)
        daily = ce.report(rows)
        daily["note"] = "일봉 근사: 장 후반 매수세·뉴스 없이 환산 · 다음 날 일봉으로 청산 근사 (손절이 하루 중 언제 닿았는지 몰라 보수적)"
        show(f"일봉 5년 ({(time.time() - t0) / 60:.0f}분)", daily)
    if args.minutes:
        from stockeye.data.sources.kis_source import KISClient
        kc = cfg.get("kis", {})
        kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
        rows = run_minutes(kis, oh, listing, index, sectors, args.minutes, args.top)
        minutes = ce.report(rows)
        minutes["note"] = f"과거 1분봉 {args.minutes}거래일 · 전날이 아닌 그날 거래대금 상위 {args.top} · 뉴스 없이 환산"
        show("과거 분봉", minutes)
    if not args.dry_run:
        from stockeye.cloud.client import Supabase, enabled
        if enabled():
            ce.publish(Supabase(), daily=daily, minutes=minutes)
            print("→ 앱 '검증' 에 올림")


if __name__ == "__main__":
    main()
