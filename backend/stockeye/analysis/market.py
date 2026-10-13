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
    "ret1": 0.25,          # 당일 등락률 (업종 전체 종목 · 시가총액 가중, 없으면 단순 평균)
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


def cap_map(sectors: pd.DataFrame | None) -> dict[str, float]:
    """업종 분류 데이터의 시가총액 (원). 없으면 빈 dict → 단순 평균"""
    if sectors is None or sectors.empty or "marcap" not in sectors:
        return {}
    s = sectors.dropna(subset=["marcap"])
    return {c: float(v) for c, v in zip(s["code"], s["marcap"]) if v and v > 0}


def group_returns(x: pd.DataFrame, codes: list[str], marcap: dict[str, float] | None = None) -> dict:
    """업종(테마) 전체 종목의 당일 등락. 거래된 종목(거래량 > 0) 전부.
    ret1 = 시가총액 가중 (HTS 업종지수와 같은 방식, 시가총액이 80% 이상 종목에 있을 때) · 아니면 단순 평균
    ret1_eq = 단순 평균 · up/down = 상승/하락 종목 수"""
    a = x[x.index.isin(codes) & (x["volume"] > 0) & x["ret1"].notna()]
    n = len(a)
    if not n:
        return {"n": 0}
    r = a["ret1"].astype(float)
    eq = float(r.mean())
    caps = pd.Series({c: (marcap or {}).get(c) for c in a.index}, dtype=float)
    ok = caps.notna() & (caps > 0)
    if ok.sum() >= max(1, 0.8 * n):
        w = caps[ok] / caps[ok].sum()
        ret, basis = float((r[ok.index[ok]] * w).sum()), "cap"
    else:
        ret, basis = eq, "eq"
    return {"n": n, "ret1": ret, "ret1_eq": eq, "up": int((r > 0).sum()), "down": int((r < 0).sum()), "basis": basis}


def group_strength(x: pd.DataFrame, groups: dict[str, dict], scores: dict[str, float] | None = None,
                   names: pd.DataFrame | None = None, min_value: float = 0, top_members: int = 5,
                   live_members: int | None = None, marcap: dict[str, float] | None = None) -> list[dict]:
    """그룹별 강도 점수와 대표 종목. (2026-10-13) 업종 전체 종목으로 계산 — 예전엔 평소 거래대금 5억↑ 종목만,
    그날 거래대금 가중이라 거래가 터진 급등주 몇 개가 업종 등락을 끌어올렸음"""
    scores = scores or {}
    nm = dict(zip(names["code"], names["name"])) if names is not None and not names.empty else {}
    rows = []
    live = x[(x["volume"] > 0) & (x["value_ma20"].fillna(0) >= min_value)]
    for gname, g in groups.items():
        m = live[live.index.isin(g["codes"])]
        if len(m) < 3:
            continue
        gr = group_returns(x, g["codes"], marcap)
        val = m["value"].astype(float)
        flow = (m.get("foreign_net", 0) + m.get("institution_net", 0))
        flow_ratio = float(np.nansum(flow) / val.sum()) if val.sum() > 0 else 0.0
        rows.append({
            "group": gname, "type": g["type"], "members": int(len(m)), "members_all": len(g["codes"]),
            "ret1": gr["ret1"], "ret1_eq": gr["ret1_eq"], "up": gr["up"], "down": gr["down"], "basis": gr["basis"],
            "ret5": float(m["ret5"].median()),
            "breadth": gr["up"] / max(gr["up"] + gr["down"], 1),
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
        # 앱·sector_live '오늘 지금' 업종 등락용: 업종 전체 종목과 가중치 (시가총액, 없으면 같은 비중) → 지금 시세로 가중 평균
        cs = list(r["codes"])
        caps = pd.Series({c: (marcap or {}).get(c) for c in cs}, dtype=float)
        if caps.notna().sum() >= max(1, 0.8 * len(cs)):
            caps = caps.dropna()
            va = caps.sort_values(ascending=False)
        else:
            va = pd.Series(1.0, index=cs)
        if live_members:
            va = va.head(live_members)
        live_w = [{"code": c, "w": round(float(v / va.sum()), 6)} for c, v in va.items()] if va.sum() > 0 else []
        out.append({
            "group": r["group"], "type": r["type"], "score": int(r["score"]),
            "arrows": _arrows(r["score"], r["ret1"]),
            "ret1_pct": round(r["ret1"] * 100, 2), "ret1_eq_pct": round(r["ret1_eq"] * 100, 2),
            "up": int(r["up"]), "down": int(r["down"]), "basis": r["basis"],
            "ret5_pct": round(r["ret5"] * 100, 2),
            "breadth_pct": round(r["breadth"] * 100, 0), "money_ratio": round(r["money"], 2),
            "members": r["members"], "members_all": int(r["members_all"]), "top": top, "live": live_w,
        })
    return out


def group_members(x: pd.DataFrame, groups: dict[str, dict], names: pd.DataFrame | None = None,
                  marcap: dict[str, float] | None = None) -> dict[str, list]:
    """업종(테마) → 전체 종목 [code, name, 등락%, 거래대금(억), 시가총액(억)] (등락 높은 순) — 앱 업종 상세 '전체 종목'"""
    nm = dict(zip(names["code"], names["name"])) if names is not None and not names.empty else {}
    out = {}
    for gname, g in groups.items():
        a = x[x.index.isin(g["codes"])]
        rows = []
        for c, r in a.iterrows():
            ret = r.get("ret1")
            rows.append([c, nm.get(c, c), round(float(ret) * 100, 2) if pd.notna(ret) and r.get("volume", 0) > 0 else None,
                         round(float(r.get("value") or 0) / 1e8, 1),
                         round((marcap or {}).get(c, 0) / 1e8) if (marcap or {}).get(c) else None])
        rows.sort(key=lambda t: -(t[2] if t[2] is not None else -999))
        out[gname] = rows
    return out
