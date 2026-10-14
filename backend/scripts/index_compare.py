"""당일매매 종목 vs 시장·업종 비교 (PC: scripts_win/23_index_compare.bat) — 고정 종목마다 매수 시점 → 이익실현/손절(또는 지금)까지

  종목 등락 · 시장 등락 · 업종 등락 (같은 구간) · 종목−업종 · 1분 수익률 상관계수(업종·시장) · 진입 전 30분 시장·업종 흐름
  시장 = 지수 대신 ETF 1분봉 (코스피 → KODEX 200 069500 · 코스닥 → KODEX 코스닥150 229200) — 지수 1분봉 API 대신 검증된 주식 1분봉 사용
  업종 = 그 종목 업종 전체를 시가총액 가중 (시가총액 큰 순으로 업종 시총 90% 까지 · 최대 60종목 · 그 종목 자신은 뺌)
  결과: 화면 출력 + data/logs/index_compare_<날짜>_<종류>.csv

  python -m scripts.index_compare                    # 오늘 당일단타
  python -m scripts.index_compare --kind limitcatch  # 상한가포착
⚠ 오늘 날짜만 (과거 날짜 1분봉은 KIS 보관 제한)
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

BANNER = """==============================================================
 StockEye [당일매매 vs 시장·업종]  (23_index_compare.bat)
  오늘 고정 종목: 매수 시점 → 이익실현/손절까지 종목·시장·업종 등락 비교
  시장 = KODEX200 / KODEX코스닥150 1분봉 · 업종 = 업종 전체 시가총액 가중 (시총 90%)
=============================================================="""
from stockeye.analysis.intraday_ctx import ctx_rows, stats  # noqa: E402  (계산은 저녁 배치와 같은 코드)


def _now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)


def f(v, d=2, sign=True):
    return "-" if v is None or (isinstance(v, float) and not np.isfinite(v)) else (f"{v:+.{d}f}" if sign else f"{v:.{d}f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="daytrade", choices=["daytrade", "limitcatch", "closingbet"])
    args = ap.parse_args()
    print(BANNER, flush=True)
    from stockeye.config import load_config, data_dir
    from stockeye.data.store import DataStore
    from stockeye.data.sources.kis_source import KISClient
    from stockeye.cloud.client import Supabase, enabled
    from stockeye.trading.intraday_track import Tracker
    if not enabled():
        sys.exit("Supabase 설정이 없습니다 (setx SUPABASE_URL / SUPABASE_SERVICE_KEY)")
    cfg = load_config()
    store = DataStore(data_dir(cfg))
    listing, sectors = store.load("listing"), store.load("sectors")
    kc = cfg.get("kis", {})
    kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
    now = _now()
    day = now.strftime("%Y-%m-%d")
    tr = Tracker(Supabase(), args.kind, day, user_id="")
    tracks = sorted(tr.tracks.values(), key=lambda t: t["time"])
    tracks = [t for t in tracks if t.get("bought", True)]
    if not tracks:
        sys.exit(f"오늘({day}) {args.kind} 고정 종목이 없습니다")
    end_all = min(now, pd.Timestamp(f"{day} 15:30"))
    end_hms = end_all.strftime("%H%M%S")
    cache: dict[str, pd.DataFrame] = {}

    def bars(code: str) -> pd.DataFrame:
        if code not in cache:
            try:
                cache[code] = kis.minute_bars_day(code, "090000", end_hms)
            except Exception as e:  # noqa: BLE001
                print(f"   1분봉 실패 {code}: {e}")
                cache[code] = pd.DataFrame(columns=["time", "close"])
        return cache[code]

    print(f"\n{day} {tr.cfg['name']} {len(tracks)}종목 — 1분봉 받는 중 (업종 종목 수에 따라 1~3분)...", flush=True)
    rows = ctx_rows(bars, tracks, listing, sectors, end_all, args.kind)
    df = pd.DataFrame(rows)
    print("\n종목        진입~청산    결과     종목%   시장%   업종%  종목-시장  상관(업종/시장)  진입전30분(시장/업종)  진입전10분 시장")
    for r in rows:
        print(f"{r['name'][:8]:<10} {r['entry']}~{r['exit']}  {r['result']:<6} {f(r['stock']):>7} {f(r['mkt']):>7} {f(r['sec']):>7}"
              f"  {f(r['vs_mkt']):>7}     {f(r['corr_sec'], 2, False):>5}/{f(r['corr_mkt'], 2, False):<5}"
              f"        {f(r['mkt_pre30'])}/{f(r['sec_pre30'])}        {f(r['mkt_pre10'])}   {r['sector']}({r['sector_n']}) {r['market']}")
    st = stats(rows)
    a = st["all"]
    print(f"\n[끝난 것] {a.get('n', 0)}건 · 승률 {a.get('win', '-')}% · 평균 손익 {a.get('pnl', '-')}%")
    for g in st["groups"]:
        print(f"  {g['title']}: " + " · ".join(f"{x['label']} {x['n']}건" + (f" 승률 {x['win']}% 평균 {x['pnl']}%" if x['n'] else "")
                                             for x in g["rows"]))
    out = data_dir(cfg) / "logs" / f"index_compare_{day}_{args.kind}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n저장: {out}")
    print("이 화면 내용을 그대로 Claude 에게 붙여 주면 시장·업종과의 관계를 분석합니다.")


if __name__ == "__main__":
    main()
