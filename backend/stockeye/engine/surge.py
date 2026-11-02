"""급등예상 (SG-1.0, 2026-11-02) — 상한가포착을 대체. 저녁에 '다음 거래일 상한가에 갈 만한 종목'을 학습 모델로 뽑아 두고,
다음날 장중 계속 지켜보며, 다음날 아침 결과를 채점해 조금씩 보완한다.

⚠ 매수 신호가 아니라 '관찰 목록'. (전일 종가 매수·상한가 다음날 매수 모두 검증에서 우위 없음 — 2026-11 연구)
   성공 기준 = 목록 종목이 실제로 상한가/+15%/+20% 에 닿는 비율 (기준선 = 아무 종목이 상한가 갈 확률)

방법
  · 특징 = scripts.limitup_study.features (직전 거래일 종가까지의 값만) + 지수 + 업종 열기. 공시 키워드는 제외(클라우드에 과거 공시가 짧음).
  · 학습 행 = (종목, 날짜 t) / 정답 = 다음 거래일 상한가(+29%↑ 종가 마감) · t 가 이미 상한가 마감이면 제외(종가에 못 삼)
  · 모델 = HistGradientBoostingClassifier (정규화 강하게) · 전체 학습 후 가장 최근 날짜 t 에 점수 → 상위 TOP 개
  · 이유 문구 = 모델 해석이 아니라, 연구에서 상한가 전 특징으로 나온 값(거래대금 배수·변동폭·상한가 이력·시총 등)을 그대로 보여줌
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

VERSION = "SG-1.0"
TOP = 20
KEEP_SCORES = 100                 # 목록 파일에 같이 남기는 점수 상위 수 (놓친 상한가가 몇 위였는지 보려고)
MIN_VAL = 1e9                     # 기준일 거래대금 10억 미만 제외
MAX_PREV = 28.5                   # 기준일 +28.5% 이상(상한가 마감)은 종가에 못 삼
LU, LU_MAX = 29.0, 30.6
HISTORY_DAYS = 620                # 특징(250일 고점) 계산에 필요한 기간
FEATS = ["chg_pct", "rng", "loc", "upper", "body", "ma5gap", "ma20gap", "ma60gap", "ma5_20", "ma20_60", "hi60gap", "hi250gap",
         "lo60up", "r3", "r5", "r20", "vr1", "vr3", "adr20", "nlu60", "nlu250", "big10_20", "down5_20", "val_log", "quiet20",
         "f1r", "i1r", "p1r", "f3r", "i3r", "p3r", "f10r", "i10r", "fi3r", "mcap_log", "per", "pbr", "per_pos", "sec_hot",
         "sec_avg", "mkt_lu", "mkt_1", "mkt_3", "mkt_20", "mkt_ma20"]


def _empty_disc() -> pd.DataFrame:
    return pd.DataFrame({"code": pd.Series(dtype=str), "published_at": pd.Series(dtype="datetime64[ns]"),
                         "title": pd.Series(dtype=str)})


def prepare(pit, days: int = HISTORY_DAYS) -> pd.DataFrame:
    """모든 (종목, 날짜) 행: 그날 종가까지의 특징 + lu(그날 상한가) + y(다음 거래일 상한가) + 기준일 후보 여부(ok)"""
    from scripts.limitup_study import features
    from .nextday import common_stock
    oh = pit.ohlcv
    last = oh["date"].max()
    since = last - pd.Timedelta(days=days)
    ls = pit.listing
    nm = dict(zip(ls.code, ls.name)) if len(ls) else {}
    oh = oh[oh["date"] >= since]
    ok = {c for c in oh.code.unique() if common_stock(c, nm.get(c, ""))}
    oh = oh[oh.code.isin(ok)].sort_values(["code", "date"]).reset_index(drop=True)
    fl = pit.flows
    fl = fl[(fl["date"] >= since) & fl.code.isin(ok)] if len(fl) else pd.DataFrame(
        columns=["code", "date", "foreign", "institution", "individual"])
    fu = pit.fund
    fu = fu[(fu["date"] >= since) & fu.code.isin(ok)][["code", "date", "per", "pbr"]] if len(fu) else pd.DataFrame(
        columns=["code", "date", "per", "pbr"])
    o, ixp, _dd, _cols = features(oh, fl, pit.index, pit.sectors, _empty_disc(), fu, ls)
    # 지수 특징 (그날 종가 기준) — 시장별로 연결
    for k in ("1", "3", "20", "ma20"):
        o[f"mkt_{k}"] = np.nan
        for m in ("KOSPI", "KOSDAQ"):
            sel = o.market == m
            if sel.any() and f"{m}_{k}" in ixp:
                o.loc[sel, f"mkt_{k}"] = o.loc[sel, "date"].map(ixp[f"{m}_{k}"])
    # 정답(라벨)만 다음 거래일 값 — 날짜 내림차순으로 뒤집어 shift(1) (특징에는 쓰지 않음 · 미래참조 감사가 shift(음수)를 막아서)
    rv = o[["code", "date", "lu"]].sort_values(["code", "date"], ascending=[True, False])
    rg = rv.groupby("code", sort=False)
    rv["y"], rv["next_date"] = rg["lu"].shift(1), rg["date"].shift(1)
    o = o.merge(rv[["code", "date", "y", "next_date"]], on=["code", "date"], how="left")
    for c in FEATS:
        if c not in o:
            o[c] = np.nan
    o["ok"] = (o.value >= MIN_VAL) & (o.chg_pct < MAX_PREV) & o.adr20.notna() & o.chg_pct.notna()
    o["name"] = o.code.map(nm)
    o["marcap"] = 10 ** o.mcap_log
    return o


def fit(panel: pd.DataFrame):
    """학습: 다음 거래일 결과를 아는 행만 (가장 최근 날짜는 정답이 없어 자동 제외)"""
    from sklearn.ensemble import HistGradientBoostingClassifier
    tr = panel[panel.ok & panel.y.notna()]
    if tr.y.sum() < 50:
        raise ValueError(f"학습할 상한가 사례가 너무 적음 ({int(tr.y.sum())}건)")
    mdl = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.06, max_iter=200, l2_regularization=1.0,
                                         min_samples_leaf=50, random_state=0)
    mdl.fit(tr[FEATS], tr.y.astype(int))
    return mdl, {"rows": int(len(tr)), "pos": int(tr.y.sum()), "base": round(float(tr.y.mean()) * 100, 3),
                 "from": str(tr.date.min().date()), "to": str(tr.date.max().date())}


def reasons(r) -> list[str]:
    """연구에서 상한가 전 특징으로 나온 값 중 이 종목이 해당하는 것만 (모델 설명이 아님)"""
    out = []

    def v(k):
        x = r.get(k) if hasattr(r, "get") else r[k]
        return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)
    if (x := v("vr1")) is not None and x >= 2:
        out.append(f"거래대금 {x:.1f}배")
    if (x := v("adr20")) is not None and x >= 0.07:
        out.append(f"20일 변동폭 {x * 100:.0f}%")
    if (x := v("chg_pct")) is not None and x >= 8:
        out.append(f"당일 +{x:.0f}%")
    if (x := v("r5")) is not None and x >= 0.15:
        out.append(f"5일 +{x * 100:.0f}%")
    if (x := v("nlu60")) is not None and x >= 1:
        out.append(f"60일 내 상한가 {int(x)}회")
    if (x := v("hi60gap")) is not None and x >= -0.05:
        out.append("60일 고점 근처")
    if (x := v("mcap_log")) is not None and x < 11.48:
        out.append(f"시총 {10 ** x / 1e8:,.0f}억")
    if (x := v("sec_hot")) is not None and x >= 1:
        out.append(f"같은 업종 +15% {int(x)}개")
    if (x := v("fi3r")) is not None and x >= 0.05:
        out.append(f"외국인·기관 3일 순매수 {x * 100:.0f}%")
    return out[:6] or ["모델 점수 상위"]


def pick(panel: pd.DataFrame, model, day, top: int = TOP) -> dict:
    """day(마지막 거래일) 종가 기준으로 점수 → 상위 목록"""
    d = panel[(panel.date == pd.Timestamp(day)) & panel.ok].copy()
    if d.empty:
        return {"items": [], "scores": []}
    d["p"] = model.predict_proba(d[FEATS])[:, 1]
    d = d.sort_values("p", ascending=False).reset_index(drop=True)
    d["rank"] = np.arange(1, len(d) + 1)
    items = []
    for r in d.head(top).itertuples(index=False):
        row = r._asdict()
        items.append({"rank": int(r.rank), "code": r.code, "name": r.name, "market": r.market, "sector": r.sector,
                      "close": float(r.close), "chg_pct": round(float(r.chg_pct), 2), "score": round(float(r.p) * 100, 2),
                      "marcap_eok": round(float(r.marcap) / 1e8) if pd.notna(r.marcap) else None,
                      "reasons": reasons(row)})
    scores = [[r.code, round(float(r.p) * 100, 2)] for r in d.head(KEEP_SCORES).itertuples(index=False)]
    return {"items": items, "scores": scores, "n_universe": int(len(d))}


def grade(items: list[dict], bars: dict[str, dict]) -> list[dict]:
    """목록 종목을 '다음 거래일' 일봉으로 채점. bars[code] = {open, high, low, close, chg_pct}
    기준가 = 목록 날짜 종가(item['close'])"""
    out = []
    for it in items:
        b = bars.get(it["code"])
        pc = it.get("close")
        if not b or not pc:
            continue
        gap = (b["open"] / pc - 1) * 100
        hi = (b["high"] / pc - 1) * 100
        cl = (b["close"] / pc - 1) * 100
        lo = (b["low"] / pc - 1) * 100
        reached = hi >= LU
        closed = LU <= cl <= LU_MAX and b["close"] >= b["high"] * 0.999
        out.append({"code": it["code"], "name": it.get("name"), "rank": it.get("rank"), "score": it.get("score"),
                    "gap": round(gap, 2), "high": round(hi, 2), "low": round(lo, 2), "close": round(cl, 2),
                    "h15": bool(hi >= 15), "h20": bool(hi >= 20), "reached": bool(reached), "closed": bool(closed)})
    return out


def missed(panel: pd.DataFrame, list_day, scores: list, top: int = 10) -> list[dict]:
    """목록 날짜 다음 거래일에 실제로 상한가 마감한 종목(기준일 후보 중) — 모델이 몇 위로 봤는지 + 전날 특징"""
    d = panel[(panel.date == pd.Timestamp(list_day)) & panel.ok & (panel.y == 1)]
    rk = {c: i + 1 for i, (c, _s) in enumerate(scores)}
    rows = []
    for r in d.itertuples(index=False):
        rows.append({"code": r.code, "name": r.name, "rank": rk.get(r.code), "reasons": reasons(r._asdict()),
                     "chg_pct": round(float(r.chg_pct), 2)})
    rows.sort(key=lambda x: (x["rank"] is None, x["rank"] or 0))
    return rows[:top] if top else rows


def stats(rows: list[dict]) -> dict:
    """채점 누적 → 비율. rows = grade() 결과 (+ date)"""
    def agg(sel):
        n = len(sel)
        if not n:
            return {"n": 0}
        pct = lambda k: round(sum(1 for r in sel if r[k]) / n * 100, 1)  # noqa: E731
        cl = sorted(r["close"] for r in sel)
        return {"n": n, "reached": pct("reached"), "closed": pct("closed"), "h15": pct("h15"), "h20": pct("h20"),
                "close_avg": round(sum(cl) / n, 2), "close_med": round(cl[n // 2], 2),
                "gap_avg": round(sum(r["gap"] for r in sel) / n, 2),
                "win": round(sum(1 for r in sel if r["close"] > 0) / n * 100, 1)}
    return {"all": agg(rows), "top5": agg([r for r in rows if (r.get("rank") or 99) <= 5]),
            "top10": agg([r for r in rows if (r.get("rank") or 99) <= 10]),
            "days": len({r["date"] for r in rows})}
