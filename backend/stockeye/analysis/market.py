"""오늘의 시장 + '돈이 몰리는 곳' (업종/테마 강도).

모든 계산은 그날의 피처 단면(x)과 PIT 뷰의 지수만 사용한다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ..config import BACKEND_DIR

# 강도 점수 구성 (그룹 간 백분위 순위의 가중합 → 0~100)
STRENGTH_WEIGHTS = {
    "ret1": 0.25,          # 당일 등락률 (거래대금 가중)
    "ret5": 0.20,          # 5일 등락률 (중앙값)
    "breadth": 0.15,       # 상승 종목 비율
    "money": 0.20,         # 거래대금 증가 (오늘 / 20일 평균)
    "flow": 0.10,          # 외국인+기관 순매수 / 거래대금
    "breakout": 0.10,      # 20일 고점 돌파 종목 비율
}


def market_overview(index_df: pd.DataFrame, x: pd.DataFrame, filter_ma: int = 60) -> dict:
    out: dict = {"indices": [], "filter_ma": filter_ma}
    for code in ("KOSPI", "KOSDAQ"):
        s = index_df[index_df["code"] == code].sort_values("date")["close"] if not index_df.empty else pd.Series()
        if len(s) >= 2:
            chg = s.iloc[-1] / s.iloc[-2] - 1
            ma20 = s.tail(20).mean()
            maf = float(s.tail(filter_ma).mean()) if len(s) >= filter_ma else None
            out["indices"].append({"code": code, "close": round(float(s.iloc[-1]), 2),
                                   "change_pct": round(float(chg) * 100, 2),
                                   "above_ma20": bool(s.iloc[-1] > ma20),
                                   # 시장 필터: 지수가 N일선 위인지 (앱은 지금 지수와 이 값을 다시 비교)
                                   "ma_filter": round(maf, 2) if maf is not None else None,
                                   "above_ma_filter": bool(s.iloc[-1] >= maf) if maf is not None else True})
    live = x[(x["volume"] > 0) & x["ret1"].notna()]
    adv, dec = int((live["ret1"] > 0).sum()), int((live["ret1"] < 0).sum())
    above20 = float((live["close"] > live["sma20"]).mean()) if len(live) else 0.0
    breadth = adv / max(adv + dec, 1)
    idx_up = np.mean([i["change_pct"] for i in out["indices"]]) if out["indices"] else 0.0
    idx_trend = np.mean([i["above_ma20"] for i in out["indices"]]) if out["indices"] else 0.5

    # 분위기 점수 0~100
    mood_score = 100 * (0.35 * breadth + 0.30 * above20 + 0.20 * idx_trend
                        + 0.15 * float(np.clip((idx_up + 2) / 4, 0, 1)))
    mood = "강세" if mood_score >= 60 else "약세" if mood_score < 40 else "중립"
    out.update({
        "advancers": adv, "decliners": dec, "breadth_pct": round(breadth * 100, 1),
        "above_sma20_pct": round(above20 * 100, 1),
        "limit_up": int((live["ret1"] >= 0.295).sum()), "limit_down": int((live["ret1"] <= -0.295).sum()),
        "mood": mood, "mood_score": round(mood_score, 1),
        "mood_icon": {"강세": "🟢", "중립": "🟡", "약세": "🔴"}[mood],
    })
    return out


def load_themes(path: str | Path | None = None) -> dict[str, list[str]]:
    p = Path(path) if path else BACKEND_DIR / "config" / "themes.yaml"
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_groups(names: pd.DataFrame, sectors: pd.DataFrame, themes: dict[str, list[str]],
                 min_size: int = 4) -> tuple[dict[str, dict], list[str]]:
    """그룹 이름 → {"type": "theme"/"sector", "codes": [...]}. 찾지 못한 테마 종목명도 반환."""
    groups: dict[str, dict] = {}
    unmatched = []
    name2code = dict(zip(names["name"], names["code"])) if not names.empty else {}
    for th, members in themes.items():
        codes = []
        for n in members:
            c = name2code.get(n)
            if c:
                codes.append(c)
            else:
                unmatched.append(f"{th}: {n}")
        if len(codes) >= 3:
            groups[th] = {"type": "theme", "codes": codes}
    if not sectors.empty:
        for sec, g in sectors.groupby("sector"):
            if len(g) >= min_size and sec not in groups:
                groups[str(sec)] = {"type": "sector", "codes": list(g["code"])}
    return groups, unmatched


def _arrows(score: float, direction: float) -> str:
    if direction < 0 and score < 45:
        return "↓↓" if score < 25 else "↓"
    n = 4 if score >= 85 else 3 if score >= 70 else 2 if score >= 55 else 1
    return "↑" * n


def group_strength(x: pd.DataFrame, groups: dict[str, dict], scores: dict[str, float] | None = None,
                   names: pd.DataFrame | None = None, min_value: float = 5e8, top_members: int = 5) -> list[dict]:
    """그룹별 강도 점수와 대표 종목."""
    scores = scores or {}
    nm = dict(zip(names["code"], names["name"])) if names is not None and not names.empty else {}
    rows = []
    live = x[(x["volume"] > 0) & (x["value_ma20"] >= min_value)]
    for gname, g in groups.items():
        m = live[live.index.isin(g["codes"])]
        if len(m) < 3:
            continue
        val = m["value"].astype(float)
        w = val / val.sum() if val.sum() > 0 else pd.Series(1 / len(m), index=m.index)
        flow = (m.get("foreign_net", 0) + m.get("institution_net", 0))
        flow_ratio = float(np.nansum(flow) / val.sum()) if val.sum() > 0 else 0.0
        rows.append({
            "group": gname, "type": g["type"], "members": int(len(m)),
            "ret1": float((m["ret1"] * w).sum()),
            "ret5": float(m["ret5"].median()),
            "breadth": float((m["ret1"] > 0).mean()),
            "money": float(val.sum() / m["value_ma20"].astype(float).sum()) if m["value_ma20"].sum() > 0 else 1.0,
            "flow": flow_ratio,
            "breakout": float((m["close"] > m["high20_prev"]).mean()),
            "codes": list(m.index),
        })
    if not rows:
        return []
    df = pd.DataFrame(rows)
    pct = sum(STRENGTH_WEIGHTS[k] * df[k].rank(pct=True) for k in STRENGTH_WEIGHTS)
    df["score"] = (100 * pct).round(0)
    out = []
    for _, r in df.sort_values("score", ascending=False).iterrows():
        mem = sorted(r["codes"], key=lambda c: scores.get(c, -1), reverse=True)
        top = [{"code": c, "name": nm.get(c, c), "score": scores.get(c),
                "ret1": round(float(x.at[c, "ret1"]) * 100, 2)} for c in mem[:top_members]]
        out.append({
            "group": r["group"], "type": r["type"], "score": int(r["score"]),
            "arrows": _arrows(r["score"], r["ret1"]),
            "ret1_pct": round(r["ret1"] * 100, 2), "ret5_pct": round(r["ret5"] * 100, 2),
            "breadth_pct": round(r["breadth"] * 100, 0), "money_ratio": round(r["money"], 2),
            "members": r["members"], "top": top,
        })
    return out
