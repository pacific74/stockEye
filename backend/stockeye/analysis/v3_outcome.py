"""V3 성과 측정 전용 (미래 가격을 일부러 씀) — 종목 선정력: 선정일 다음 날 시가 → h거래일째 종가.

⚠ 점수·선정·매매 결정 코드에서 이 모듈을 쓰면 안 된다 (미래참조). 결과를 '나중에 채점'할 때만 쓴다.
   backtest/lookahead.py 의 소스 검사는 이 파일을 '측정 전용'으로 알고 건너뛴다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (5, 10, 20, 40)


def forward(opens: pd.DataFrame, closes: pd.DataFrame, horizons=HORIZONS) -> dict[int, pd.DataFrame]:
    """선정일 기준 다음 날 시가 → h거래일째 종가 수익률 (가격제한폭 넘는 변화가 낀 구간 제외)"""
    jump = (closes.pct_change(fill_method=None).abs() > 0.31).astype(float)
    ent = opens.shift(-1)
    out = {}
    for h in horizons:
        bad = jump.rolling(h + 1, min_periods=1).max().shift(-(h + 1))
        out[h] = (closes.shift(-h) / ent - 1).where((bad == 0) & (ent > 0))
    return out


def selection_power(entries: list[dict], fwd: dict[int, pd.DataFrame], seeds: int = 50) -> dict:
    """entries: [{date, picks:[code..], eligible:[code..]}] → 그룹(상위10 / 전체 후보 / 랜덤10)별 h일 평균·중앙값·승률 + 초과"""
    rng = np.random.default_rng(7)
    vals = {"top": {h: [] for h in HORIZONS}, "all": {h: [] for h in HORIZONS}}
    rnd = {h: [] for h in HORIZONS}
    for e in entries:
        d = pd.Timestamp(e["date"])
        for h in HORIZONS:
            f = fwd[h]
            if d not in f.index:
                continue
            row = f.loc[d]
            tp = row.reindex(e["picks"]).dropna().values
            al = row.reindex(e["eligible"]).dropna().values
            vals["top"][h].append(tp); vals["all"][h].append(al)
            if len(al) >= 10:
                rnd[h].append([rng.choice(al, 10, replace=False) for _ in range(seeds)])
    out = {}
    for h in HORIZONS:
        def st(arrs):
            a = np.concatenate(arrs) if arrs else np.array([])
            a = a[~np.isnan(a)]
            if not len(a):
                return None
            a = np.clip(a, -1, 1)
            return {"n": int(len(a)), "mean": round(float(a.mean()) * 100, 2), "median": round(float(np.median(a)) * 100, 2),
                    "win": round(float((a > 0).mean()) * 100, 1)}
        top_s, all_s = st(vals["top"][h]), st(vals["all"][h])
        r_s = None
        if rnd[h]:
            per_seed = [st([day[k] for day in rnd[h]]) for k in range(seeds)]
            per_seed = [p for p in per_seed if p]
            if per_seed:
                r_s = {k: round(float(np.mean([p[k] for p in per_seed])), 2) for k in ("mean", "median", "win")}
                r_s["n"] = per_seed[0]["n"]
        out[str(h)] = {"top10": top_s, "all": all_s, "random10": r_s,
                       "excess": round(top_s["mean"] - all_s["mean"], 2) if top_s and all_s else None,
                       "days": len(vals["top"][h])}
    return out
