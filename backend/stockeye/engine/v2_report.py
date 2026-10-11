"""V2 결과 → 리포트·종목 상세·앱에서 쓰는 후보 형식.

앱·매매 엔진과의 호환을 위해 예전 후보 형식(plan.verdict, parts, max_parts, reasons, warnings …)을 그대로 쓰되,
항목은 V2 배점(추세20·거래량10·거래대금5·수급15·가격위치15·위험5·재무15·공시15)으로 채운다.
plan.verdict: '매수 신호' (지금 살 자리) / '강력 후보' / '매수 후보' / '관심' / '관망' / '제외' / '매수 차단' / …
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..data.financials import FinIndex
from .disclosure_rules import DisclosureIndex
from .v2 import MARKET_LABEL, PARTS_MAX, V2Context, evaluate, market_states, v2_cfg

# V2 항목 → 예전 키 (앱 화면·AI 설명이 이 키를 씀)
KEYMAP = {"trend": "trend", "volume": "volume", "value": "trading_value", "flow": "supply",
          "position": "breakout", "risk": "volatility", "financial": "financial", "news": "news"}
LISTS = {
    "signal": ("매수 신호", "후보 중 지금 살 자리: 20일선·지지선 반등 + 거래량 + 손절폭 6% 이내 + 시장 하락장 아님. "
                          "한 번에 사지 말고 1차 30% → 반등 확인 30% → 돌파 40%."),
    "buy": ("강력·매수 후보", "점수 75점 이상이고 매수 차단·과열·업종 약세가 없는 종목. 좋은 종목이지만 지금 바로 사라는 뜻은 아님."),
    "watch": ("관심", "점수 65~74점. 조건이 일부 부족해 지켜보는 종목."),
}


def make_context(pit, view, as_of) -> V2Context:
    lst = pit.listing
    sec = getattr(pit, "sectors", pd.DataFrame())
    fin = getattr(pit, "financials", pd.DataFrame())
    disc = view._disc if hasattr(view, "_disc") else pit.disc
    return V2Context(
        pd.Timestamp(as_of).normalize(),
        dict(zip(lst["code"], lst["market"])) if not lst.empty else {},
        market_states(view.index()),
        dict(zip(sec["code"], sec["sector"])) if not sec.empty else {},
        FinIndex.from_raw(fin) if fin is not None and len(fin) else None,
        DisclosureIndex.build(disc) if disc is not None and len(disc) else None,
    )


def evaluate_all(pit, view, x: pd.DataFrame, universe_codes, cfg: dict, as_of) -> pd.DataFrame:
    """전 종목 V2 평가 (1차 필터 탈락 종목은 '제외' + 사유)"""
    ctx = make_context(pit, view, as_of)
    ev = evaluate(x, ctx, cfg, detail=True)
    uni = set(universe_codes)
    out_uni = ~ev.index.isin(list(uni))
    ev.loc[out_uni, "status"] = "제외"
    ev.loc[out_uni, "signal"] = False
    ev["stage1"] = ~out_uni
    ev.attrs["has_fin"] = ctx.fin is not None
    ev.attrs["has_disc"] = ctx.disc is not None
    return ev


def _stars(score: float) -> int:
    return 5 if score >= 85 else 4 if score >= 75 else 3 if score >= 65 else 2 if score >= 55 else 1


def _lst(v) -> list:
    return list(v) if isinstance(v, (list, tuple)) else []


def _f(v, nd=2):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else round(f, nd)


def reasons_of(r: pd.Series, x: pd.Series) -> list[str]:
    out = []
    if x.get("close", 0) > x.get("sma20", np.inf) > x.get("sma60", np.inf) > x.get("sma120", np.inf):
        out.append("이동평균선 정배열 (20일 > 60일 > 120일)")
    elif x.get("sma20", 0) > x.get("sma60", np.inf):
        out.append("20일선이 60일선 위")
    if x.get("sma20_slope", 0) > 0:
        out.append("20일선 상승")
    vt = x.get("vol5_ratio")
    if vt is not None and not pd.isna(vt) and vt >= 1.0:
        out.append(f"거래량 증가 (최근 5일 / 20일 {vt:.1f}배)")
    if x.get("updown_vol20", 0) > 1.2:
        out.append("오르는 날 거래량이 더 많음")
    f5, i5 = x.get("foreign_net5", np.nan), x.get("institution_net5", np.nan)
    if not pd.isna(f5) and f5 > 0 and not pd.isna(i5) and i5 > 0:
        out.append("외국인·기관 5일 순매수")
    elif not pd.isna(f5) and f5 > 0:
        out.append("외국인 5일 순매수")
    elif not pd.isna(i5) and i5 > 0:
        out.append("기관 5일 순매수")
    d20 = x.get("dist_sma20")
    if d20 is not None and not pd.isna(d20) and abs(d20) <= 0.03:
        out.append(f"20일선 부근 ({d20 * 100:+.1f}%)")
    if bool(x.get("up_day", False)) and (x.get("touch_sma20_3d", 0) > 0 or x.get("close", 0) <= x.get("low20", 0) * 1.05):
        out.append("지지선에서 양봉 반등")
    if x.get("close", 0) > x.get("high20_prev", np.inf) and x.get("vol_ratio", 0) >= 1.5:
        out.append("20일 고점 돌파 + 거래량")
    if r.get("financial", 0) >= 11:
        out.append(f"재무 양호 ({r['financial']:.0f}/15)")
    for t in (r.get("news_pos") or [])[:2]:
        out.append(f"공시: {t}")
    return out


def warnings_of(r: pd.Series, x: pd.Series) -> list[str]:
    w = list(r.get("blocks") or [])
    if r.get("overheat"):
        w.append("단기 급등 과열 (추격 매수 주의)")
    ms = r.get("market_state")
    if ms == "C":
        w.append(f"{_mname(r.get('market'))} 하락장 → 신규 매수 중단")
    elif ms == "B":
        w.append(f"{_mname(r.get('market'))} 중립 → 매수 비중 절반")
    ss = r.get("sector_score")
    if ss is not None and not pd.isna(ss) and ss < 5:
        w.append(f"업종 약세 (업종 점수 {ss:.0f}/15)")
    sp = r.get("stop_pct")
    if sp is not None and not pd.isna(sp) and sp > 0.06:
        w.append(f"손절폭 {sp * 100:.1f}% (6% 초과)")
    for t in (r.get("news_neg") or [])[:2]:
        w.append(f"공시: {t}")
    if x.get("rsi14", 0) > 75:
        w.append(f"RSI {x['rsi14']:.0f} 과열권")
    return w


def _mname(m):
    return {"KOSPI": "코스피", "KOSDAQ": "코스닥"}.get(m, m or "시장")


def verdict_of(r: pd.Series) -> tuple[str, str]:
    st = r.get("status", "제외")
    sp = (r.get("stop_pct") or 0) * 100
    if r.get("signal"):
        return "매수 신호", (f"{r['grade']} + 지지선 반등·거래량 확인, 손절폭 {sp:.1f}% → 1차 30% 분할 매수 검토 "
                         f"(반등 확인 시 30%, 고점 돌파 시 40%)")
    if st in ("강력 후보", "매수 후보"):
        if r.get("market_state") == "C":
            return st, "좋은 종목이지만 시장이 하락장 → 신규 매수는 시장 회복 뒤"
        return st, "좋은 종목이지만 아직 매수 자리는 아님 — 20일선·지지선 반등과 거래량을 기다림"
    if st == "관심":
        return st, "조건이 일부 부족 — 지켜보기"
    if st == "매수 차단":
        return st, "매수 차단: " + ", ".join(r.get("blocks") or [])
    if st.startswith("시장 하락장"):
        return st, f"{_mname(r.get('market'))} 하락장 (지수가 200일선·60일선 아래) → 신규 매수 쉬기"
    if st.startswith("과열"):
        return st, "단기 급등으로 과열 → 조정 뒤 다시 확인"
    if st.startswith("업종 약세"):
        return st, "속한 업종이 약함 → 관망"
    if r.get("stage1") is False:
        return "제외", "1차 필터 미통과 (거래대금·가격·관리종목·급락 등)"
    return st, "점수 부족"


# 탭별 손익비(1차 목표 ÷ 손절, 분석일 종가 기준) 허용 구간 — 2026-10-11, 적중률 5년으로 정함
#   설계(2021~2024)에서 고르고 확인(2025~)에서 점검. 하한 이상 · 상한 미만 (None = 제한 없음). V3 는 개선이 확인되지 않아 없음
RR_BAND = {"nextday": (1.0, 1.3), "early": (0.8, 2.0), "reversal": (1.2, None), "uplimit": (1.0, 1.3)}


def rr_in_band(rr, tab: str) -> bool:
    lo, hi = RR_BAND.get(tab, (None, None))
    if lo is None and hi is None:
        return True
    if rr is None or rr != rr:
        return False
    return (lo is None or rr >= lo) and (hi is None or rr < hi)


def rr_outside(ev: pd.DataFrame, codes, tab: str) -> dict:
    """손익비가 탭 구간 밖인 종목 → {code: '손익비 0.8 (기준 1.0~1.3)'}"""
    lo, hi = RR_BAND.get(tab, (None, None))
    if lo is None and hi is None:
        return {}
    rr = ev["rr"] if "rr" in ev else pd.Series(dtype=float)
    band = f"{lo if lo is not None else ''}~{hi if hi is not None else ''}"
    out = {}
    for c in codes:
        v = rr.get(c) if c in rr.index else None
        v = None if v is None or v != v else float(v)
        if not rr_in_band(v, tab):
            out[c] = f"손익비 {'-' if v is None else f'{v:.1f}'} (기준 {band})"
    return out


def below_ma5(x: pd.DataFrame) -> set:
    """종가가 5일선 아래인 종목 — 관심 탭(익일유망주·상승초기·추세전환·상파) 추천에서 제외 (2026-10-11 사용자 요청)"""
    if "close" not in x or "sma5" not in x:
        return set()
    c, m = x["close"].astype(float), x["sma5"].astype(float)
    return set(x.index[(c < m) & m.notna()])


def candidate_dict(code: str, r: pd.Series, x: pd.Series, name: str, rank: int = 0, theme=None) -> dict:
    verdict, why = verdict_of(r)
    price = _f(r.get("price"), 0) or 0
    stop = int(r.get("stop") or 0)
    t1, t2 = int(r.get("target1") or 0), int(r.get("target2") or 0)
    t3 = r.get("target3")
    t3 = int(t3) if t3 == t3 and t3 else None              # 차트 기반 3차 목표 (없으면 None)
    loss = _f((stop / price - 1) * 100, 1) if price else None
    parts = {KEYMAP[k]: _f(r.get(k), 1) or 0.0 for k in PARTS_MAX}
    return {
        "engine": "v2", "rank": rank, "code": code, "name": name, "market": r.get("market"),
        "score": _f(r.get("score"), 1), "stars": _stars(float(r.get("score") or 0)),
        "grade": r.get("grade"), "grade_icon": r.get("grade_icon"), "status": r.get("status"),
        "signal": bool(r.get("signal")), "blocked": bool(r.get("blocked")), "blocks": list(r.get("blocks") or []),
        "market_state": r.get("market_state"), "market_state_label": MARKET_LABEL.get(r.get("market_state")),
        "sector": r.get("sector"), "sector_score": _f(r.get("sector_score"), 0), "theme": theme,
        "size_mult": _f(r.get("size_mult"), 2),
        "parts": parts, "max_parts": {KEYMAP[k]: v for k, v in PARTS_MAX.items()}, "missing": [],
        "reasons": reasons_of(r, x), "warnings": warnings_of(r, x), "tags": [],
        "news_pos": list(r.get("news_pos") or []), "news_neg": list(r.get("news_neg") or []),
        "plan": {
            "price": int(price), "entry_low": int(r.get("entry_low") or 0), "entry_high": int(r.get("entry_high") or 0),
            "target1": t1, "target2": t2, "stop": stop, "loss_pct": loss,
            "target1_pct": _f((t1 / price - 1) * 100, 1) if price else None,
            "target2_pct": _f((t2 / price - 1) * 100, 1) if price else None,
            "target3": t3, "target3_pct": _f((t3 / price - 1) * 100, 1) if price and t3 else None,
            "rr1": _f(r.get("rr"), 2), "rr2": _f(((t2 / price - 1) / (1 - stop / price)) if price and stop else None, 2),
            "verdict": verdict, "verdict_reason": why,
            # 차트 기반 목표·손절의 근거 (levels.py) — 없으면 예전 % 기준
            "basis": _lst(r.get("level_basis")), "level_warn": _lst(r.get("level_warn")),
            "resistances": _lst(r.get("resistances")), "supports": _lst(r.get("supports")),
            "method": "chart" if _lst(r.get("level_basis")) else "pct",
            "zones": _lst(r.get("zones")), "notes": r.get("notes") if isinstance(r.get("notes"), dict) else {},
        },
    }


def build_lists(ev: pd.DataFrame, x: pd.DataFrame, name_of: dict, theme_of: dict, top: int = 30) -> dict:
    """리포트용: 매수 신호 / 강력·매수 후보 / 관심 + 종합(TOP)"""
    def mk(df):
        out = []
        for i, (code, r) in enumerate(df.head(top).iterrows(), 1):
            out.append(candidate_dict(code, r, x.loc[code], name_of.get(code, code), i, theme_of.get(code)))
        return out
    ok = ev[ev["stage1"] & ~ev["blocked"]]
    sig = ok[ok["signal"]].sort_values("score", ascending=False)
    buy = ok[ok["status"].isin(["강력 후보", "매수 후보"])].sort_values("score", ascending=False)
    watch = ok[ok["status"] == "관심"].sort_values("score", ascending=False)
    overall = pd.concat([sig, buy[~buy.index.isin(sig.index)], watch])
    lists = {k: {"name": LISTS[k][0], "short": LISTS[k][0], "description": LISTS[k][1], "count": len(df),
                 "candidates": mk(df)} for k, df in (("signal", sig), ("buy", buy), ("watch", watch))}
    return {"overall": mk(overall), "lists": lists}


def market_summary(ev: pd.DataFrame, cfg: dict) -> dict:
    out = {}
    for m in ("KOSPI", "KOSDAQ"):
        sel = ev[ev["market"] == m]
        if sel.empty:
            continue
        r = sel.iloc[0]
        st = r["market_state"]
        out[m] = {"state": st, "label": MARKET_LABEL.get(st), "why": list(r.get("market_why") or []),
                  "size_mult": v2_cfg(cfg)["market_sizing"].get(st)}
    return out
