"""추세전환 탭 → 리포트 strategies['reversal'] + 종목 상세 candidate['reversal']"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from . import reversal as rv
from .v2_report import candidate_dict

log = logging.getLogger(__name__)
TOP = 30          # 앱에 보낼 최대 개수
NEAR = 60.0       # 70점 이상이 너무 적을 때 '근접'으로 같이 보여줄 하한
DESC = ("바닥에서 하락이 멈추고 20일선이 수평 → 상승으로 도는 종목 (100점: 하락·바닥 15 · 바닥 횡보 25 · "
        "이평 전환 35 · 초기 반등 15 · 거래량·변동성 10). 70점 이상 후보 · 80점 이상 우선 관찰.")
LIMIT = "실험용 관찰 목록 — 매매 규칙·검증 전. V3 기준 전략(모의 운용)과 별개입니다."


def _n(v, nd=1):
    return None if v is None or v != v else round(float(v), nd)


def build_section(view, x: pd.DataFrame, ev: pd.DataFrame, name_of: dict, theme_of: dict, as_of) -> dict:
    """오늘 추세전환 점수 (1차 필터 통과 + 매수 차단 아님) → {'list', 'meta', 'scores'}"""
    oh = view.ohlcv()
    O, H, L, C, V = rv.wide(oh, days=120)
    d = C.index[-1]
    f = rv.raw_features(O, H, L, C, V, dates=[d])
    sc = rv.score_today(f, d)
    elig = ev["stage1"] & ~ev["blocked"].astype(bool)
    sc["eligible"] = elig.astype(bool).reindex(sc.index, fill_value=False)
    value = x["value_ma20"] if "value_ma20" in x else pd.Series(dtype=float)
    ranked = rv.rank(sc, sc["eligible"], value, rv.CANDIDATE)
    n70, n80 = len(ranked), int((ranked["total"] >= rv.PRIORITY).sum())
    show = ranked
    if len(show) < 10:                                # 후보가 적은 날은 60점대도 '근접'으로 같이
        near = rv.rank(sc, sc["eligible"], value, NEAR)
        show = pd.concat([show, near[~near.index.isin(show.index)]]).head(10)
    show = show.head(TOP)
    sc["rank"] = np.nan
    order = rv.rank(sc, sc["eligible"], value, -1)
    sc.loc[order.index, "rank"] = range(1, len(order) + 1)
    cands = []
    for i, code in enumerate(show.index, 1):
        if code not in ev.index or code not in x.index:
            continue
        c = candidate_dict(code, ev.loc[code], x.loc[code], name_of.get(code, code), i, theme_of.get(code))
        cands.append(apply(c, sc.loc[code]))
    lst = {"name": "추세전환", "short": "추세전환", "description": DESC, "limitation": LIMIT, "count": n70,
           "candidates": cands}
    meta = {"version": rv.VERSION, "rules": rv.RULES_TEXT, "candidates": n70, "priority": n80,
            "eligible": int(sc["eligible"].sum())}
    return {"list": lst, "meta": meta, "scores": sc}


def label(total: float) -> str:
    return "우선 관찰" if total >= rv.PRIORITY else "후보" if total >= rv.CANDIDATE else \
        "근접" if total >= NEAR else "해당 없음"


def apply(c: dict, row: pd.Series) -> dict:
    """추세전환 목록용 후보 dict: 점수·판정·근거를 추세전환 기준으로 (V3·V2 점수는 v2_score 로만 남김)"""
    ri = info(row)
    c = {**c, "v2_score": c.get("score"), "score": ri["score"], "max_score": 100, "stars": None, "tags": [],
         "reasons": ri["reasons"], "warnings": ri["warnings"], "reversal": ri}
    c["plan"] = {**(c.get("plan") or {}), "verdict": f"추세전환 {ri['label']}",
                 "verdict_reason": "관찰용 (매매 규칙 없음)", "reference_only": True}
    return c


def reasons(row: pd.Series) -> tuple[list[str], list[str]]:
    g = lambda k: row.get("rv_" + k)  # noqa: E731
    s = lambda k: float(row.get(k) or 0)  # noqa: E731
    R, W = [], []

    def add(ok, text):
        (R if ok else W).append(text)

    D = g("D")
    if D == D and D is not None:
        add(s("d60") >= 10, f"60일 고점 대비 {D:+.1f}% → 하락·바닥 {s('bottom15'):.1f}/15")
    r20, lo, run = g("R20"), g("L"), g("RUN")
    if r20 == r20 and r20 is not None:
        bits = [f"20일 종가 폭 {r20:.1f}%"]
        if lo == lo and lo is not None:
            bits.append(f"최근 10일 저점 {'+' if lo >= 0 else ''}{lo:.1f}% (이전 10일 대비)")
        if run == run and run is not None:
            bits.append(f"바닥권 {int(run)}일")
        add(s("base25") >= 15, " · ".join(bits) + f" → 바닥 횡보 {s('base25'):.1f}/25")
    s20, a20, s60 = g("S20"), g("A20"), g("S60")
    if s20 == s20 and s20 is not None:
        bits = [f"20일선 5일 {s20:+.2f}%"]
        if a20 == a20 and a20 is not None:
            bits.append(f"기울기 변화 {a20:+.2f}%p")
        if s60 == s60 and s60 is not None:
            bits.append(f"60일선 10일 {s60:+.2f}%")
        add(s("ma35") >= 21, " · ".join(bits) + f" → 이평 전환 {s('ma35'):.1f}/35")
    g20, r5 = g("G20"), g("R5")
    if g20 == g20 and g20 is not None:
        bar = "양봉" if bool(row.get("rv_UP_BAR")) else "음봉·보합"
        p = g("P")
        bits = [f"20일선 대비 {g20:+.1f}%", f"5일 {r5:+.1f}%" if r5 == r5 and r5 is not None else None,
                f"오늘 {bar}" + (f" (고저 범위 {p * 100:.0f}% 위치)" if p == p and p is not None else "")]
        add(s("rebound15") >= 9, " · ".join(b for b in bits if b) + f" → 초기 반등 {s('rebound15'):.1f}/15")
    vr, at = g("VRATIO"), g("ATRCHG")
    bits = []
    if at == at and at is not None:
        bits.append(f"변동폭 {at:+.0f}%")
    if vr == vr and vr is not None:
        bits.append(f"거래량 {vr:.2f}배 (최근 10일/이전 20일)")
    up, dn = g("UPV"), g("DNV")
    if up == up and dn == dn and up is not None and dn is not None:
        bits.append("하락일 없음" if dn == 0 else f"상승일/하락일 거래량 {up / dn:.2f}배")
    v20 = g("V20")
    if v20 == v20 and v20 is not None:
        bits.append(f"오늘 거래량 20일 평균의 {v20:.1f}배")
    if bits:
        add(s("volume10") >= 6, " · ".join(bits) + f" → 거래량·변동성 {s('volume10'):.1f}/10")
    if s20 == s20 and s20 is not None and s20 > 1.5:
        W.append("20일선이 이미 가파르게 오름 (반등이 진행됐을 수 있음)")
    if D == D and D is not None and D < -40:
        W.append("60일 고점 대비 40% 넘게 급락")
    if v20 == v20 and v20 is not None and v20 > 1.5:
        W.append("오늘 거래량 급증 (추격·단기 과열 주의)")
    return R, W


def info(row: pd.Series) -> dict:
    """종목 상세용 추세전환 점수: 총점·5항목·세부 14개(소수점)·근거"""
    tot = _n(row.get("total"))
    R, W = reasons(row)
    rk = row.get("rank")
    return {"version": rv.VERSION, "score": tot, "max": 100, "label": label(tot or 0),
            "eligible": bool(row.get("eligible")), "rank": int(rk) if rk == rk and rk is not None else None,
            "parts": {k: _n(row.get(k)) for k in rv.PARTS}, "labels": {k: v for k, (v, _) in rv.PARTS.items()},
            "maxes": {k: m for k, (_, m) in rv.PARTS.items()},
            "subs": [{"key": k, "part": p, "label": lab, "max": m, "score": _n(row.get(k), 2)}
                     for k, (p, lab, m) in rv.SUBS.items()],
            "reasons": R, "warnings": W}
