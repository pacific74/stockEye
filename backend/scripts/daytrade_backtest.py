"""당일단타 되돌려 보기 (과거 1분봉) — PC 에서 가끔 (scripts_win/15_daytrade_backtest.bat)

  python -m scripts.daytrade_backtest --check            # KIS 과거 분봉 API 가 되는지 먼저 확인 (삼성전자 어제)
  python -m scripts.daytrade_backtest --days 20 --top 80 # 최근 20거래일 · 전날 거래대금 상위 80종목

날마다: 전날 거래대금 상위 top 종목(보통주)의 그날 1분봉(09:00~15:30)을 받아 09:05~10:30 을 1분씩 다시 계산
→ 종목마다 첫 '진입 조건 충족' 에서 진입 → 그 뒤 분봉으로 1·2차 익절 / 손절 / 장 마감 청산 → 결과를 '검증' 에 올림
(호출 수: 종목×날짜마다 약 13번. 20일×80종목 ≈ 2만 번 → 초당 15번이면 20~25분)
⚠ 과거 분봉은 KIS 실전 계좌 키로만, 보관 기간 안에서만 받을 수 있음. 호가·뉴스·지수는 없어 중립으로 계산.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

import pandas as pd

log = logging.getLogger("stockeye.daytrade_bt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--top", type=int, default=80)
    ap.add_argument("--compare", type=float, default=75.0,
                    help="기준을 이 점수까지 낮췄다면 어땠나도 같이 비교 (기본 75, 0 이면 비교 안 함). 앱에 올리는 건 지금 기준(80)만")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)

    from stockeye.config import load_config, data_dir
    from stockeye.data.store import DataStore
    from stockeye.data.sources.kis_source import KISClient
    from stockeye.engine.nextday import common_stock
    from stockeye.analysis import daytrade_eval as de
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
    rows, low_rows, t0 = [], [], time.time()
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
        for code in top["code"]:
            try:
                bars = kis.minute_bars_day(code, "090000", "153000", day=ds)
            except Exception as e:  # noqa: BLE001
                log.debug("%s %s 분봉 실패: %s", ds, code, e)
                continue
            if bars.empty:
                continue
            s = de.replay_day(bars, prev_close.get(code), adr=adrs.get(code))
            if s:
                s.update({"date": day.strftime("%Y-%m-%d"), "code": code, "name": nm.get(code, code)})
                g = de.grade(s, bars)
                if g:
                    rows.append(g)
                    n_sig += 1
            if args.compare:                                          # 기준을 낮춰 첫 신호를 따로 (같은 분봉으로 한 번 더 계산)
                s2 = de.replay_day(bars, prev_close.get(code), adr=adrs.get(code), min_score=args.compare)
                if s2:
                    s2.update({"date": day.strftime("%Y-%m-%d"), "code": code, "name": nm.get(code, code)})
                    g2 = de.grade(s2, bars)
                    if g2:
                        low_rows.append(g2)
        print(f"{day:%Y-%m-%d}: 신호 {n_sig}건 (누적 {len(rows)} · {(time.time() - t0) / 60:.0f}분)")
    rep = de.report(rows)
    rep.update({"universe": f"전날 거래대금 상위 {args.top}", "note": "호가·뉴스·지수 없이 중립으로 계산한 되돌려 보기",
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
    if not args.dry_run:
        from stockeye.cloud.client import Supabase, enabled
        if enabled():
            de.publish(Supabase(), backtest=rep)
            print("→ 앱 '검증' 에 올림")


if __name__ == "__main__":
    main()
