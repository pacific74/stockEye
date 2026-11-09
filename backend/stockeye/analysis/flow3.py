"""전 종목 외국인·기관 최근 3거래일 순매수 비율 (2026-11-09) — 당일단타 09:00 선발의 수급 가산용
  비율 = (외국인 + 기관 순매수대금 3일 합) ÷ (거래대금 3일 합) · 급등예상 엔진의 fi3r 와 같은 뜻 (여기선 전 종목)"""
from __future__ import annotations

import pandas as pd


def flow3_ratio(flows: pd.DataFrame | None, ohlcv: pd.DataFrame | None, days: int = 3) -> dict[str, float]:
    if flows is None or flows.empty or ohlcv is None or ohlcv.empty:
        return {}
    ds = sorted(flows["date"].unique())[-days:]
    f = flows[flows["date"].isin(ds)]
    net = (f.get("foreign", 0) + f.get("institution", 0)) if "foreign" in f else None
    if net is None:
        return {}
    f = f.assign(_net=net.fillna(0) if hasattr(net, "fillna") else net)
    num = f.groupby("code")["_net"].sum()
    o = ohlcv[ohlcv["date"].isin(ds)]
    val = (o["value"] if "value" in o and o["value"].notna().any() else o["close"] * o["volume"])
    den = o.assign(_v=val).groupby("code")["_v"].sum()
    r = (num / den.replace(0, float("nan"))).dropna()
    return {str(c): round(float(v), 4) for c, v in r.items()}
