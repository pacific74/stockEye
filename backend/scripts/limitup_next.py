"""상한가 다음날(D+1) 행동 — 일봉 기준. 상한가 마감(전일比 +29%↑, 종가≈고가)한 날 D 의 다음 거래일을 본다.
  python -m scripts.limitup_next --data ../data
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

COST = 0.2   # 왕복 수수료·세금 %


def events(dd: Path, since="2021-01-01") -> pd.DataFrame:
    from stockeye.engine.nextday import common_stock
    oh = pd.read_parquet(dd / "ohlcv.parquet", filters=[("date", ">=", pd.Timestamp(since))])
    ls = pd.read_parquet(dd / "listing.parquet")
    nm = dict(zip(ls.code, ls.name))
    ok = {c for c in oh.code.unique() if common_stock(c, nm.get(c, ""))}
    oh = oh[oh.code.isin(ok) & (oh.volume > 0)].sort_values(["code", "date"]).reset_index(drop=True)
    g = oh.groupby("code", sort=False)
    for k in (1, 2, 3):
        for c in ("open", "high", "low", "close", "chg_pct", "date", "value"):
            oh[f"{c}{k}"] = g[c].shift(-k)
    oh["prev_value"] = g["value"].shift(1)
    oh["lu"] = ((oh.chg_pct >= 29.0) & (oh.chg_pct <= 30.6) & (oh.close >= oh.high * 0.999)).astype(int)
    oh["nlu60"] = oh.groupby("code", sort=False)["lu"].transform(lambda s: s.shift(1).rolling(60, min_periods=1).sum())
    oh["streak"] = oh.groupby("code", sort=False)["lu"].shift(1).fillna(0)       # 전날도 상한가였나
    e = oh[(oh.lu == 1) & oh.open1.notna() & (oh.prev_value >= 1e9)].copy()
    e["gap"] = (e.open1 / e.close - 1) * 100
    e["o2c"] = (e.close1 / e.open1 - 1) * 100
    e["o2h"] = (e.high1 / e.open1 - 1) * 100
    e["o2l"] = (e.low1 / e.open1 - 1) * 100
    e["c2c"] = (e.close1 / e.close - 1) * 100
    e["lu1"] = ((e.chg_pct1 >= 29.0) & (e.chg_pct1 <= 30.6)).astype(int)
    e["neg1"] = (e.close1 < e.open1).astype(int)
    e["n2o"] = (e.open2 / e.close1 - 1) * 100         # D+1 종가 → D+2 시가
    e["n2c"] = (e.close2 / e.close1 - 1) * 100        # D+1 종가 → D+2 종가
    e["n2h"] = (e.high2 / e.close1 - 1) * 100
    e["year"] = e.date.dt.year
    return e


def stats(x: pd.Series) -> str:
    x = x.dropna()
    if len(x) == 0:
        return "-"
    return f"n={len(x):>4} 평균 {x.mean():6.2f}% 중앙 {x.median():6.2f}% 승률 {(x > 0).mean() * 100:4.0f}%"


def sim_open_stop(e: pd.DataFrame, stop: float, tgt: float | None) -> pd.Series:
    """D+1 시가 매수 → 손절 stop%(음수) · 목표 tgt% 중 먼저 닿는 쪽(같은 날 둘 다 닿으면 손절로 — 보수적), 없으면 종가. 시가가 이미 상한가면 못 산다고 보고 제외"""
    x = e[e.open1 < e.close * 1.299]
    r = pd.Series(np.where(x.o2l <= stop, stop, np.where((tgt is not None) & (x.o2h >= (tgt if tgt else 999)), tgt if tgt else 0, x.o2c)), index=x.index)
    return r - COST


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    e = events(Path(a.data))
    print(f"상한가 마감 {len(e)}건 (2021~, 전일 거래대금 10억↑, 다음날 있음)  최근 월별: {e.groupby(e.date.dt.to_period('M')).size().tail(6).to_dict()}")
    print(f"\n[다음날 기본] 다음날도 상한가(연상) {e.lu1.mean() * 100:.1f}% · 시가 갭 중앙 {e.gap.median():.1f}% · 갭 상승 비율 {(e.gap > 0).mean() * 100:.0f}% · 시가→종가 {stats(e.o2c)}")
    print("[연도별 연상 비율 / 시가→종가 평균]")
    for y, g in e.groupby("year"):
        print(f"  {y}: n={len(g):>4} 연상 {g.lu1.mean() * 100:4.1f}%  갭 중앙 {g.gap.median():5.1f}%  시가→종가 평균 {g.o2c.mean():5.2f}%  종가→종가 {g.c2c.mean():5.2f}%")
    b = pd.cut(e.gap, [-50, -3, 0, 3, 7, 12, 20, 40], labels=["≤-3", "-3~0", "0~3", "3~7", "7~12", "12~20", ">20"])
    print("\n[시가 갭 구간별: 시가 매수 → 종가 / 고가 도달 / 연상]  (비용 0.2% 빼기 전)")
    for k, g in e.groupby(b, observed=True):
        print(f"  갭 {k:>6}: n={len(g):>4} 연상 {g.lu1.mean() * 100:5.1f}% | 시가→종가 {stats(g.o2c)} | 시가→고가 평균 {g.o2h.mean():5.2f}% 시가→저가 평균 {g.o2l.mean():6.2f}%")
    print("\n[전략 A: D+1 시가 매수 → 손절 −3% / 목표 +5%(없으면 종가), 비용 포함]")
    for k, g in e.groupby(b, observed=True):
        for stop, tgt in ((-3.0, 5.0), (-3.0, None), (-2.0, 3.0)):
            r = sim_open_stop(g, stop, tgt)
            print(f"  갭 {k:>6} 손절{stop:.0f}%/목표{tgt if tgt else '종가'}: {stats(r)}")
    print("\n[전략 B: 음봉(종가<시가)으로 끝난 D+1 종가 매수 → D+2]  비용 포함")
    for nm, g in (("음봉 전체", e[e.neg1 == 1]), ("양봉 전체", e[e.neg1 == 0]),
                  ("음봉 & 갭상승", e[(e.neg1 == 1) & (e.gap > 0)]), ("음봉 & 종가 −5%↓(D 종가比)", e[(e.neg1 == 1) & (e.c2c < -5)]),
                  ("음봉 & 연상 아님 & 갭 3%↑", e[(e.neg1 == 1) & (e.gap >= 3)])):
        print(f"  {nm:<26} D+2 시가 매도 {stats(g.n2o - COST)} | D+2 종가 매도 {stats(g.n2c - COST)} | D+2 고가까지 평균 {g.n2h.mean():.2f}%")
    print("\n[전략 C: 모든 D+1 종가 매수 → D+2 시가 (밤샘)]  " + stats(e.n2o - COST) + "  | 연상 아닌 날만 " + stats(e[e.lu1 == 0].n2o - COST))
    print("\n[첫 상한가 vs 연속]")
    for nm, g in (("최근 60일 첫 상한가", e[e.nlu60 == 0]), ("60일 내 상한가 있음", e[e.nlu60 >= 1]), ("전날도 상한가(2연속째)", e[e.streak == 1])):
        print(f"  {nm:<22} n={len(g):>4} 연상 {g.lu1.mean() * 100:5.1f}% 갭 중앙 {g.gap.median():5.1f}% 시가→종가 {g.o2c.mean():5.2f}%")
    out = Path(a.data) / "limitup"
    out.mkdir(exist_ok=True)
    e.to_parquet(out / "next_events.parquet")


if __name__ == "__main__":
    main()
