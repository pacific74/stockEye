"""매수후보 선정 엔진 V2.

  ① 시장(A 상승 / B 중립 / C 하락) → ② 업종 강도(필터) → ③ 재무·공시 위험 제거
  → ④ 기술적 분석 → ⑤ 100점 → ⑥ 가격 위치 → ⑦ 과열 검사 → ⑧ 강력 후보 / 매수 후보 / 관심 / 관망 / 제외

100점 = 추세 20 + 거래량 10 + 거래대금 5 + 수급 15 + 가격위치 15 + 변동성·위험 5 + 재무 15 + 공시 15
점수와 별도로 '매수 차단'(관리종목·감사의견·횡령·대규모 증자·거래대금 부족·손절폭 과대·과열 등)이 있으면
점수가 높아도 후보가 되지 않는다.  '매수 후보'(좋은 종목)와 '매수 신호'(지금 살 자리)를 분리한다.

모든 계산은 그날 장 마감(18:00) 시점까지 공개된 정보만 쓴다 (백테스트 미래참조 감사 대상).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..data.financials import FinIndex
from .disclosure_rules import DisclosureIndex
from .trade_plan import round_tick

PARTS_MAX = {"trend": 20, "volume": 10, "value": 5, "flow": 15, "position": 15, "risk": 5, "financial": 15, "news": 15}
PART_LABELS = {"trend": "추세", "volume": "거래량", "value": "거래대금", "flow": "수급", "position": "가격위치",
               "risk": "변동성·위험", "financial": "재무", "news": "공시"}
GRADES = [(85, "강력 후보", "🔥"), (75, "매수 후보", "🟢"), (65, "관심", "🟡"), (55, "관망", "⚪"), (0, "제외", "🔴")]
MARKET_LABEL = {"A": "상승장", "B": "중립", "C": "하락장"}

DEFAULTS = {
    "min_value": 3_000_000_000,       # 20일 평균 거래대금 30억 미만 → 차단
    "max_stop_pct": 0.12,             # 정상 손절폭이 12% 넘게 필요 → 차단
    "signal_max_stop_pct": 0.06,      # 매수 신호는 손절폭 6% 이내
    "min_sector_score": 5,            # 업종 강도 (0~15) 이 값 미만 → 후보 제외
    "signal_min_score": 75,           # 매수 신호가 나는 최소 점수
    "stop_atr": 2.0,                  # 손절 = max(20일 저점 -1%, 종가 - 2ATR)
    "min_stop_pct": 0.03,             # 손절폭 최소 3%
    "target1_pct": 0.08, "target2_pct": 0.15,
    "market_sizing": {"A": 1.0, "B": 0.5, "C": 0.0},
}


def v2_cfg(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("v2") or {})}


# ------------------------------------------------------------------ ① 시장
def market_states(index_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """지수별 날짜 → 상태 계산용 값 (종가·20/60/200일선·20일선 기울기). 그날 종가까지만 사용."""
    out = {}
    if index_df is None or index_df.empty:
        return out
    for code, g in index_df.groupby("code"):
        c = g.sort_values("date").set_index("date")["close"].astype(float)
        d = pd.DataFrame({"close": c, "sma20": c.rolling(20).mean(), "sma60": c.rolling(60).mean(),
                          "sma200": c.rolling(200).mean()})
        d["sma20_up"] = d["sma20"] > d["sma20"].shift(5)
        out[code] = d
    return out


def market_state_at(states: dict, code: str, d: pd.Timestamp, breadth: float | None) -> tuple[str, list[str]]:
    """A 상승장 / B 중립 / C 하락장 (+ 이유)"""
    t = states.get(code)
    if t is None or d not in t.index or pd.isna(t.at[d, "sma200"]):
        return "B", ["지수 데이터 부족 → 중립"]
    r = t.loc[d]
    c1 = r["close"] > r["sma200"]
    c2 = r["sma20"] > r["sma60"]
    c3 = bool(r["sma20_up"])
    c4 = breadth is not None and breadth >= 0.5
    why = [f"지수 {'>' if c1 else '<'} 200일선", f"20일선 {'>' if c2 else '<'} 60일선",
           f"20일선 {'상승' if c3 else '하락'}"] + ([f"20일선 위 종목 {breadth:.0%}"] if breadth is not None else [])
    if c1 and c2 and (c3 or c4):
        return "A", why
    if not c1 and not c2:
        return "C", why
    return "B", why


# ------------------------------------------------------------------ ② 업종
def sector_scores(x: pd.DataFrame, sector_of: dict) -> pd.DataFrame:
    """업종별 강도 0~15: 20일 수익률 상위 30% +5 / 60일 상위 30% +4 / 거래대금 증가 +3 / 대표 종목 상승 +3"""
    if not sector_of:
        return pd.DataFrame(columns=["sector", "score", "rank_pct"])
    df = x[["ret20", "ret60", "ret5", "value_ratio", "value_ma20"]].copy()
    df["sector"] = [sector_of.get(c) for c in df.index]
    df = df.dropna(subset=["sector"])
    g = df.groupby("sector")
    t = pd.DataFrame({"n": g.size(), "r20": g["ret20"].median(), "r60": g["ret60"].median(),
                      "vr": g["value_ratio"].median()})
    lead = df.sort_values("value_ma20", ascending=False).groupby("sector").head(3).groupby("sector")["ret5"].mean()
    t["lead"] = lead
    t = t[t["n"] >= 5]
    if t.empty:
        return pd.DataFrame(columns=["sector", "score", "rank_pct"])
    p20, p60 = t["r20"].rank(pct=True), t["r60"].rank(pct=True)
    t["score"] = 5 * (p20 >= 0.7) + 4 * (p60 >= 0.7) + 3 * (t["vr"] > 1.1) + 3 * (t["lead"] > 0)
    t["rank_pct"] = p20
    return t.reset_index()[["sector", "score", "rank_pct", "r20", "r60"]]


# ------------------------------------------------------------------ ④~⑤ 점수
def _b(s) -> pd.Series:
    return s.fillna(False).astype(float)


def score_parts(x: pd.DataFrame, fin: pd.DataFrame, vc: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """기술·재무 6개 항목 (공시는 따로) → (parts, plan 값)"""
    c = x["close"]
    p = pd.DataFrame(index=x.index)
    # 추세 20
    p["trend"] = (4 * _b(c > x["sma20"]) + 5 * _b(x["sma20"] > x["sma60"]) + 4 * _b(x["sma60"] > x["sma120"])
                  + 3 * _b(x["sma20_slope"] > 0) + 2 * _b(x["sma60_slope"] > 0) + 2 * _b(x["ret20"] > 0))
    # 거래량 10 (단순 폭증은 고득점 금지)
    vt = x["vol5_ratio"]
    base = np.select([vt < 0.8, vt < 1.0, vt < 1.5], [1, 3, 6], default=7)
    base = np.where(vt.isna(), 3, base)
    p["volume"] = np.clip(base + 2 * _b(x["updown_vol20"] > 1.2) + 1 * _b((x["ret5"] > 0) & (vt > 1.0)), 0, 10)
    # 거래대금 5 (매매 편의성)
    v = x["value_ma20"].fillna(0)
    p["value"] = np.select([v < vc["min_value"], v < 5e9, v < 1e10, v < 3e10, v < 1e11], [0, 1, 2, 3, 4], default=5)
    # 수급 15 (5일 + 20일 누적)
    def g(col):
        return x[col] if col in x else pd.Series(np.nan, index=x.index)
    f5, f20, i5, i20 = g("foreign_net5"), g("foreign_net20"), g("institution_net5"), g("institution_net20")
    ind5 = g("individual_net5")
    fl = (2 * _b(f5 > 0) + 2 * _b(f20 > 0) + _b(g("foreign_streak") >= 3)
          + 2 * _b(i5 > 0) + 2 * _b(i20 > 0) + _b(g("institution_streak") >= 3)
          + 1.5 * _b((f5 + i5) > 0) + 1.5 * _b((f20 + i20) > 0) + 2 * _b((ind5 < 0) & ((f5 + i5) > 0)))
    p["flow"] = np.where(f5.isna() & i5.isna(), 7.0, fl)
    # 손절 위치 (스윙 저점 / ATR) → 변동성·위험 5, 가격위치에도 사용
    stop = np.maximum(x["low20"] * 0.99, c - vc["stop_atr"] * x["atr14"])
    stop = np.minimum(stop, c * (1 - vc["min_stop_pct"]))
    sd = (c - stop) / c
    # 가격위치 15: 20일선 부근 / 지지 / 반등 / 거래량 동반 / 돌파
    near20 = (x["dist_sma20"].abs() <= 0.03)
    support = (c <= x["low20"] * 1.05) | (x["touch_sma20_3d"] > 0)
    rebound = x["up_day"].astype(bool) & support
    p["position"] = (5 * _b(near20) + 3 * _b(support & (c > x["sma60"])) + 3 * _b(rebound)
                     + 2 * _b(rebound & (x["vol_ratio"] >= 1.2))
                     + 2 * _b((c > x["high20_prev"]) & (x["vol_ratio"] >= 1.5)))
    # 변동성·위험 5: 손절을 합리적으로 둘 수 있나
    p["risk"] = np.select([sd <= 0.05, sd <= 0.07, sd <= 0.09], [5, 3, 1], default=0) - _b(x["atr_pct"] > 0.08)
    p["risk"] = p["risk"].clip(lower=0)
    # 재무 15
    p["financial"] = financial_score(fin.reindex(x.index))
    plan = pd.DataFrame({"stop": stop, "stop_pct": sd, "near20": near20, "support": support, "rebound": rebound},
                        index=x.index)
    return p, plan


def financial_score(f: pd.DataFrame) -> pd.Series:
    """수익성 5 + 성장성 4 + 건전성 3 + 밸류 3 (밸류는 PER·PBR 이 피처에 있을 때만 → 아래에서 더함). 재무 없음 = 6"""
    if f is None or f.empty or "op_pos" not in f:
        return pd.Series(6.0, index=f.index if f is not None else None)
    def b(s):
        return pd.to_numeric(s, errors="coerce")
    has = f["op_pos"].notna()
    prof = 2 * _b(f["op_pos"] == True) + _b(b(f["roe"]) > 0.08) + _b(b(f["op_margin"]) > 0.05) \
        + _b(f["op_improve"] == True)  # noqa: E712
    grow = _b(b(f["rev_yoy"]) > 0.05) + _b(b(f["op_yoy"]) > 0.10) + _b(b(f["ni_yoy"]) > 0.10) \
        + _b((b(f["rev_yoy"]) > 0) & (b(f["op_yoy"]) > 0))
    health = np.where(b(f["debt_ratio"]) < 1.0, 1.0, np.where(b(f["debt_ratio"]) < 2.0, 0.5, 0.0)) \
        + _b(b(f["current_ratio"]) > 1.0) + _b(f["impaired"] != True)  # noqa: E712
    return pd.Series(np.where(has, prof + grow + health, 6.0), index=f.index)


def valuation_score(x: pd.DataFrame, sector_of: dict, f: pd.DataFrame) -> pd.Series:
    """밸류 3: PER 0~40 +1 / PBR 0.3~3 +1 / 업종 중앙값보다 PER 낮고 이익 성장 +1 (저PER 이라고 무조건 가점 X)"""
    per = x["per"] if "per" in x else pd.Series(np.nan, index=x.index)
    pbr = x["pbr"] if "pbr" in x else pd.Series(np.nan, index=x.index)
    sec = pd.Series([sector_of.get(c) for c in x.index], index=x.index)
    med = per.where(per > 0).groupby(sec).transform("median")
    grow = pd.to_numeric(f.reindex(x.index).get("op_yoy", pd.Series(np.nan, index=x.index)), errors="coerce") > 0
    s = _b((per > 0) & (per < 40)) + _b((pbr >= 0.3) & (pbr <= 3)) + _b((per > 0) & (per < med) & grow)
    return pd.Series(np.where(per.isna() & pbr.isna(), 1.5, s), index=x.index)


def grade_of(score: float) -> tuple[str, str]:
    for th, name, icon in GRADES:
        if score >= th:
            return name, icon
    return "제외", "🔴"


@dataclass
class V2Context:
    as_of: pd.Timestamp
    market_of: dict                      # code -> KOSPI/KOSDAQ
    states: dict                          # market_states() 결과
    sector_of: dict = field(default_factory=dict)
    fin: FinIndex | None = None
    disc: DisclosureIndex | None = None


def evaluate(x: pd.DataFrame, ctx: V2Context, cfg: dict, detail: bool = True) -> pd.DataFrame:
    """그날 단면 x (1차 필터 통과 종목) → V2 결과 (종목별 1행)"""
    vc = v2_cfg(cfg)
    d = pd.Timestamp(ctx.as_of).normalize()
    out = pd.DataFrame(index=x.index)
    if x.empty:
        return out
    # ① 시장 상태 (종목이 속한 시장 기준)
    mk = pd.Series([ctx.market_of.get(c, "KOSPI") for c in x.index], index=x.index)
    states = {}
    for m in ("KOSPI", "KOSDAQ"):
        sel = x[mk == m]
        br = float((sel["close"] > sel["sma20"]).mean()) if len(sel) else None
        states[m] = market_state_at(ctx.states, m, d, br)
    out["market"] = mk
    out["market_state"] = [states.get(m, ("B", []))[0] for m in mk]
    # ② 업종
    sec = sector_scores(x, ctx.sector_of)
    sec_map = dict(zip(sec["sector"], sec["score"])) if len(sec) else {}
    secp = dict(zip(sec["sector"], sec["rank_pct"])) if len(sec) else {}
    out["sector"] = [ctx.sector_of.get(c) for c in x.index]
    out["sector_score"] = [sec_map.get(s, np.nan) for s in out["sector"]]
    out["sector_rank_pct"] = [secp.get(s, np.nan) for s in out["sector"]]
    # ③~⑤ 점수
    fin = ctx.fin.at(x.index, d + pd.Timedelta(hours=18)) if ctx.fin is not None else pd.DataFrame()
    parts, plan = score_parts(x, fin, vc)
    # 재무 15 = 수익성·성장성·건전성(12) + 밸류(3)
    parts["financial"] = np.minimum(parts["financial"] * (12 / 12) + 0, 12) + valuation_score(x, ctx.sector_of, fin)
    parts["financial"] = parts["financial"].clip(0, 15)
    # 공시 15 + 차단
    news, nblock, npos, nneg = [], [], [], []
    for code in x.index:
        r = ctx.disc.at(code, d + pd.Timedelta(hours=18)) if ctx.disc is not None else {"score": 7.0, "block": [], "pos": [], "neg": []}
        news.append(r["score"]); nblock.append(r["block"]); npos.append(r["pos"][:3]); nneg.append(r["neg"][:3])
    parts["news"] = news
    total = parts[list(PARTS_MAX)].sum(axis=1)
    out = out.join(parts)
    out["score"] = total.round(1)
    # ⑦ 과열
    over = (x["ret5"] > 0.25) | (x["ret20"] > 0.5) | ((x["near_high250"] >= 0.98) & (x["rsi14"] > 75) & (x["ret20"] > 0.25))
    out["overheat"] = over.fillna(False)
    # 매수 차단
    blocks = []
    imp = fin.reindex(x.index)["impaired"] if "impaired" in fin else pd.Series(np.nan, index=x.index)
    for i, code in enumerate(x.index):
        b = list(nblock[i])
        if x.at[code, "value_ma20"] < vc["min_value"]:
            b.append("거래대금 부족")
        if plan.at[code, "stop_pct"] > vc["max_stop_pct"]:
            b.append("손절폭이 지나치게 큼")
        if imp.get(code) is True or imp.get(code) == 1.0:
            b.append("자본잠식")
        if pd.isna(x.at[code, "sma120"]) or pd.isna(x.at[code, "atr14"]):
            b.append("데이터 불완전")
        if bool(x.at[code, "halted"]):
            b.append("거래정지")
        blocks.append(b)
    out["blocks"] = blocks
    out["blocked"] = [len(b) > 0 for b in blocks]
    # ⑧ 등급·상태
    g = [grade_of(s) for s in out["score"]]
    out["grade"] = [a for a, _ in g]
    out["grade_icon"] = [b for _, b in g]
    sector_ok = out["sector_score"].fillna(vc["min_sector_score"]) >= vc["min_sector_score"]
    st = []
    for code in x.index:
        if out.at[code, "blocked"]:
            st.append("매수 차단")
        elif out.at[code, "market_state"] == "C" and out.at[code, "grade"] != "강력 후보":
            st.append("시장 하락장 — 관망")      # 하락장: 강력 후보만 남기고 (매수 신호는 아래에서 모두 막음)
        elif out.at[code, "overheat"]:
            st.append("과열 — 관망")
        elif not sector_ok[code]:
            st.append("업종 약세 — 관망")
        else:
            st.append(out.at[code, "grade"])
    out["status"] = st
    # 매수 신호 (후보 중 지금 살 자리)
    cand = out["status"].isin(["강력 후보", "매수 후보"])
    sig = (cand & (out["score"] >= vc["signal_min_score"]) & (out["market_state"] != "C")
           & (plan["near20"] | plan["support"]) & plan["rebound"] & (x["vol_ratio"] >= 1.0)
           & (plan["stop_pct"] <= vc["signal_max_stop_pct"]))
    out["signal"] = sig.fillna(False)
    # 매매 계획
    c = x["close"]
    out["price"] = c
    out["stop"] = [round_tick(s, "down") for s in plan["stop"].fillna(0)]
    out["stop_pct"] = plan["stop_pct"]
    out["entry_low"] = [round_tick(v, "down") for v in np.maximum(plan["stop"] * 1.02, x["sma20"].fillna(c) * 0.98).fillna(c)]
    out["entry_high"] = [round_tick(v, "up") for v in c * 1.01]
    out["target1"] = [round_tick(v, "up") for v in c * (1 + vc["target1_pct"])]
    out["target2"] = [round_tick(v, "up") for v in c * (1 + vc["target2_pct"])]
    out["rr"] = (vc["target1_pct"] / plan["stop_pct"]).round(2)
    out["size_mult"] = [vc["market_sizing"].get(s, 0.5) for s in out["market_state"]]
    out["value_ma20"] = x["value_ma20"]
    if detail:
        out["news_pos"], out["news_neg"] = npos, nneg
        out["market_why"] = [states.get(m, ("B", []))[1] for m in mk]
    return out.sort_values("score", ascending=False)
