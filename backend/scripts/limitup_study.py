"""상한가 직전 공통점 분석 — 상한가(전일比 +29%↑ 마감) 종목의 1~3일 전 모습을, 같은 날 상한가가 아니었던 종목과 비교.

  python -m scripts.limitup_study --data ../data --event-from 2026-10-01 --event-to 2026-10-30 --check-from 2026-01-01
  · 발견(discovery): event 기간(10월)  · 검증(check): 그 이전 같은 해 (10월에서 찾은 특징이 다른 달에도 맞는지)
  · 모든 특징은 '상한가 전날 종가까지' 알 수 있는 값만 (당일 공시는 따로 표시) — 미래 정보 없음
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LU = 29.0           # 상한가 판정 (전일比 %)
LU_MAX = 30.6       # 이보다 큰 값은 신규상장·거래재개 등 → 제외
MIN_VAL = 1e9       # 전일 거래대금 10억 미만은 모집단에서 제외 (살 수 없는 종목)

KW = {"수주·공급계약": r"공급계약|수주|단일판매|판매[ㆍ·]?공급", "임상·허가": r"임상|허가|FDA|품목|승인|기술이전|라이선스",
      "유상증자·CB": r"유상증자|전환사채|신주인수권|교환사채|제3자배정", "자사주": r"자기주식|자사주",
      "합병·인수·양수도": r"합병|인수|양수|양도|분할|영업", "최대주주·경영권": r"최대주주|경영권|지분.*(취득|처분)",
      "조회공시·투자주의": r"조회공시|투자주의|투자경고|투자위험|불성실|단기과열", "실적": r"영업\\(잠정\\)실적|잠정|매출액또는손익|손익구조",
      "정정": r"정정", "특허·신사업": r"특허|신규시설|신사업|시설투자|타법인"}


def load(dd: Path, since: str = "2025-01-01"):
    from stockeye.engine.nextday import common_stock
    oh = pd.read_parquet(dd / "ohlcv.parquet", filters=[("date", ">=", pd.Timestamp(since))])
    ls = pd.read_parquet(dd / "listing.parquet")
    nm = dict(zip(ls.code, ls.name))
    ok = {c for c in oh.code.unique() if common_stock(c, nm.get(c, ""))}
    oh = oh[oh.code.isin(ok)].sort_values(["code", "date"]).reset_index(drop=True)
    fl = pd.read_parquet(dd / "flows.parquet", filters=[("date", ">=", pd.Timestamp(since))])
    fl = fl[fl.code.isin(ok)]
    ix = pd.read_parquet(dd / "index.parquet")
    sec = pd.read_parquet(dd / "sectors.parquet")
    ds = pd.read_parquet(dd / "disclosures.parquet")
    ds = ds[pd.to_datetime(ds.published_at) >= pd.Timestamp(since)]
    fu = pd.read_parquet(dd / "fundamentals.parquet", columns=["code", "date", "per", "pbr"], filters=[("date", ">=", pd.Timestamp(since))])
    fu = fu[fu.code.isin(ok)]
    return oh, fl, ix, sec, ds, fu, ls


def features(oh, fl, ix, sec, ds, fu, ls) -> pd.DataFrame:
    o = oh.copy()

    def G():
        return o.groupby("code", sort=False)

    g = G()
    o["lu"] = ((o.chg_pct >= LU) & (o.chg_pct <= LU_MAX)).astype(int)
    pc = G()["close"].shift(1)
    o["rng"] = (o.high - o.low) / pc
    o["loc"] = ((o.close - o.low) / (o.high - o.low).replace(0, np.nan))
    o["upper"] = (o.high - o[["open", "close"]].max(axis=1)) / o.close
    o["body"] = (o.close - o.open) / o.open
    for n in (5, 20, 60):
        o[f"ma{n}"] = G()["close"].transform(lambda s, n=n: s.rolling(n).mean())
        o[f"ma{n}gap"] = o.close / o[f"ma{n}"] - 1
    o["ma5_20"] = o.ma5 / o.ma20 - 1
    o["ma20_60"] = o.ma20 / o.ma60 - 1
    o["hi60gap"] = o.close / G()["high"].transform(lambda s: s.rolling(60, min_periods=30).max()) - 1
    o["hi250gap"] = o.close / G()["high"].transform(lambda s: s.rolling(250, min_periods=60).max()) - 1
    o["lo60up"] = o.close / G()["low"].transform(lambda s: s.rolling(60, min_periods=30).min()) - 1
    o["r3"] = o.close / G()["close"].shift(3) - 1
    o["r5"] = o.close / G()["close"].shift(5) - 1
    o["r20"] = o.close / G()["close"].shift(20) - 1
    o["v20"] = G()["value"].transform(lambda s: s.rolling(20).mean().shift(1))
    o["vr1"] = o.value / o.v20
    o["vr3"] = G()["value"].transform(lambda s: s.rolling(3).mean()) / G()["value"].transform(lambda s: s.rolling(20).mean().shift(3))
    o["adr20"] = G()["rng"].transform(lambda s: s.rolling(20).mean())
    o["nlu60"] = G()["lu"].transform(lambda s: s.rolling(60, min_periods=1).sum())
    o["nlu250"] = G()["lu"].transform(lambda s: s.rolling(250, min_periods=1).sum())
    o["big10_20"] = G()["chg_pct"].transform(lambda s: (s >= 10).rolling(20, min_periods=1).sum())
    o["down5_20"] = G()["chg_pct"].transform(lambda s: (s <= -5).rolling(20, min_periods=1).sum())
    o["val_log"] = np.log10(o.value.clip(lower=1))
    o["quiet20"] = G()["rng"].transform(lambda s: s.rolling(20).std())
    # 수급 (전일)
    f = fl.sort_values(["code", "date"]).copy()
    f["f_n"] = f.foreign
    fg = f.groupby("code", sort=False)
    for k, c in (("f", "foreign"), ("i", "institution"), ("p", "individual")):
        f[f"{k}1"] = f[c]
        f[f"{k}3"] = fg[c].transform(lambda s: s.rolling(3, min_periods=2).sum())
        f[f"{k}10"] = fg[c].transform(lambda s: s.rolling(10, min_periods=5).sum())
    o = o.merge(f[["code", "date", "f1", "i1", "p1", "f3", "i3", "p3", "f10", "i10", "p10"]], on=["code", "date"], how="left")
    o["val3"] = G()["value"].transform(lambda s: s.rolling(3).sum())
    o["val10"] = G()["value"].transform(lambda s: s.rolling(10).sum())
    for k in ("f", "i", "p"):
        o[f"{k}1r"] = o[f"{k}1"] / o.value.replace(0, np.nan)
        o[f"{k}3r"] = o[f"{k}3"] / o.val3.replace(0, np.nan)
        o[f"{k}10r"] = o[f"{k}10"] / o.val10.replace(0, np.nan)
    o["fi3r"] = o.f3r + o.i3r
    # 시총·밸류
    s = sec.drop_duplicates("code", keep="last").set_index("code")
    o["sector"] = o.code.map(s["sector"])
    o["market"] = o.code.map(s["market"])
    o["mcap_log"] = np.log10(o.code.map(s["marcap"]).astype(float))
    fu2 = fu.sort_values(["code", "date"])
    o = o.merge(fu2, on=["code", "date"], how="left")
    o["per_pos"] = (o.per > 0).astype(int)
    # 업종 열기: 같은 날 같은 업종 +15% 이상 개수·평균 등락
    o["hot15"] = (o.chg_pct >= 15).astype(int)
    o["sec_hot"] = o.groupby(["date", "sector"])["hot15"].transform("sum") - o.hot15
    o["sec_avg"] = o.groupby(["date", "sector"])["chg_pct"].transform("mean")
    o["mkt_lu"] = o.groupby("date")["lu"].transform("sum")
    # 지수
    ixp = ix.pivot(index="date", columns="code", values="close").sort_index()
    for m in ("KOSPI", "KOSDAQ"):
        ixp[f"{m}_1"] = ixp[m].pct_change() * 100
        ixp[f"{m}_3"] = ixp[m].pct_change(3) * 100
        ixp[f"{m}_20"] = ixp[m].pct_change(20) * 100
        ixp[f"{m}_ma20"] = (ixp[m] / ixp[m].rolling(20).mean() - 1) * 100
    # 공시 (날짜별 키워드 건수)
    d = ds.copy()
    d["date"] = pd.to_datetime(d.published_at).dt.normalize()
    for name, pat in KW.items():
        d[name] = d.title.str.contains(pat, regex=True, na=False).astype(int)
    d["공시_전체"] = 1
    cols = list(KW) + ["공시_전체"]
    dd = d.groupby(["code", "date"])[cols].sum().reset_index()
    return o, ixp, dd, cols


def build(o, ixp, dd, dcols) -> pd.DataFrame:
    """행 = (종목, 상한가 후보일 D). 특징은 D 의 직전 거래일(t-1) 종가 기준 값"""
    feat = ["chg_pct", "rng", "loc", "upper", "body", "ma5gap", "ma20gap", "ma60gap", "ma5_20", "ma20_60", "hi60gap", "hi250gap", "lo60up",
            "r3", "r5", "r20", "vr1", "vr3", "adr20", "nlu60", "nlu250", "big10_20", "down5_20", "val_log", "quiet20",
            "f1r", "i1r", "p1r", "f3r", "i3r", "p3r", "f10r", "i10r", "fi3r", "mcap_log", "per", "pbr", "per_pos", "sec_hot", "sec_avg"]
    o = o.sort_values(["code", "date"]).reset_index(drop=True)
    base = o[["code", "date", "lu", "chg_pct", "value", "market", "sector", "close", "high", "open"]].rename(
        columns={"chg_pct": "chg_D", "value": "val_D", "close": "close_D", "high": "high_D", "open": "open_D"})
    sh = o.groupby("code", sort=False)[feat].shift(1)
    sh.columns = [c + "_t1" if c in ("chg_pct",) else c for c in sh.columns]
    out = pd.concat([base, sh], axis=1)
    out["val_t1"] = o.groupby("code", sort=False)["value"].shift(1)
    out["gap_D"] = (out.open_D / o.groupby("code", sort=False)["close"].shift(1) - 1) * 100
    out["lu_t1"] = o.groupby("code", sort=False)["lu"].shift(1)
    out["lu_t2"] = o.groupby("code", sort=False)["lu"].shift(2)
    out["lu_t3"] = o.groupby("code", sort=False)["lu"].shift(3)
    out = out.rename(columns={"chg_pct_t1": "r1"})
    # 지수 (D 직전 거래일 기준) + D 당일
    ixs = ixp.shift(1)
    for m in ("KOSPI", "KOSDAQ"):
        mm = out.market == m
        for k in ("1", "3", "20", "ma20"):
            out.loc[mm, f"mkt_{k}"] = out.loc[mm, "date"].map(ixs[f"{m}_{k}"])
        out.loc[mm, "mkt_D"] = out.loc[mm, "date"].map(ixp[f"{m}_1"])
    # 공시: D-3..D-1 와 D 당일
    dd = dd.set_index(["code", "date"])
    days = sorted(o.date.unique())
    prev = {days[i]: days[max(0, i - 1)] for i in range(len(days))}
    p3 = {days[i]: days[max(0, i - 3):i] for i in range(len(days))}
    rows = []
    key = dd.index
    for c in dcols:
        s = dd[c]
        # 날짜별 합 (D-3..D-1)
        piv = s.unstack("date").reindex(columns=days).fillna(0)
        roll = piv.T.rolling(3, min_periods=1).sum().shift(1).T            # D-3..D-1 합
        out[f"d3_{c}"] = [roll.at[cd, dt_] if cd in roll.index else 0.0 for cd, dt_ in zip(out.code, out.date)]
        out[f"d0_{c}"] = [piv.at[cd, dt_] if cd in piv.index else 0.0 for cd, dt_ in zip(out.code, out.date)]
    return out


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    a = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - a) / d, (c + a) / d)


def compare(df: pd.DataFrame, feats: list[str], title: str) -> pd.DataFrame:
    ev, ne = df[df.lu == 1], df[df.lu == 0]
    rows = []
    for f in feats:
        a, b = ev[f].dropna(), ne[f].dropna()
        if len(a) < 5 or len(b) < 50:
            continue
        # 중앙값 차이를 비모집단 분포 안의 분위(percentile) 로 환산: 상한가 종목 중앙값이 전체에서 몇 % 위치인가
        pct = (b < a.median()).mean() * 100
        auc = ((a.values[:, None] > b.sample(min(len(b), 3000), random_state=1).values[None, :]).mean()
               + 0.5 * (a.values[:, None] == b.sample(min(len(b), 3000), random_state=1).values[None, :]).mean())
        rows.append({"특징": f, "상한가_중앙": a.median(), "일반_중앙": b.median(), "위치%": round(pct, 1), "AUC": round(float(auc), 3),
                     "상한가_n": len(a)})
    r = pd.DataFrame(rows)
    r["강도"] = (r.AUC - 0.5).abs()
    return r.sort_values("강도", ascending=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--event-from", default="2026-10-01")
    ap.add_argument("--event-to", default="2026-10-30")
    ap.add_argument("--check-from", default="2026-01-01")
    ap.add_argument("--out", default="")
    ap.add_argument("--since", default="2025-01-01", help="일봉을 읽기 시작할 날짜 (250일 고점 계산용 여유)")
    a = ap.parse_args()
    dd = Path(a.data)
    oh, fl, ix, sec, ds, fu, ls = load(dd, a.since)
    o, ixp, dday, dcols = features(oh, fl, ix, sec, ds, fu, ls)
    df = build(o, ixp, dday, dcols)
    df = df[(df.val_t1 >= MIN_VAL) & (df.chg_D <= LU_MAX)]
    out = Path(a.out) if a.out else Path(a.data) / "limitup"
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / "panel.parquet")
    ef, et = pd.Timestamp(a.event_from), pd.Timestamp(a.event_to)
    disc = df[(df.date >= ef) & (df.date <= et)]
    chk = df[(df.date >= pd.Timestamp(a.check_from)) & (df.date < ef)]
    print(f"발견 구간 {a.event_from}~{a.event_to}: 모집단 {len(disc):,}  상한가 {int(disc.lu.sum())}건 ({disc.lu.mean() * 100:.2f}%)")
    print(f"검증 구간 {a.check_from}~{ef.date()}: 모집단 {len(chk):,}  상한가 {int(chk.lu.sum())}건 ({chk.lu.mean() * 100:.2f}%)")
    disc.to_parquet(out / "disc.parquet")
    chk.to_parquet(out / "chk.parquet")


if __name__ == "__main__":
    main()
