"""상승초기 탭 → 리포트 strategies['early'] + 종목 상세 candidate['early']"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import early as up
from .v2_report import candidate_dict, below_ma5, rr_outside

TOP = 30
DESC = ("종가가 20일선을 회복하고 단기 상승이 막 시작되는 종목 (100점: 단기 추세 회복 25 · 상승 모멘텀 20 · "
        "중기 추세 개선 20 · 거래량 확인 20 · 과열·변동성 15). 80↑ 우선 관찰 · 70~79 관찰 후보 · 60~69 보류.")
LIMIT = "실험용 관찰 목록 — 매매 규칙·검증 전. V3 기준 전략(모의 운용)과 별개입니다."


def _n(v, nd=1):
    return None if v is None or v != v else round(float(v), nd)


def build_section(view, x: pd.DataFrame, ev: pd.DataFrame, name_of: dict, theme_of: dict, as_of) -> dict:
    O, H, L, C, V, VAL = up.wide(view.ohlcv(), days=120)
    d = C.index[-1]
    f = up.raw_features(O, H, L, C, V, VAL, dates=[d])
    sc = up.score_today(f, d)
    risk_ok = (ev["stage1"] & ~ev["blocked"].astype(bool)).astype(bool).reindex(sc.index, fill_value=False)
    sc["risk_ok"] = risk_ok
    sc["eligible"] = risk_ok & ~sc["excluded"] & ~sc.index.isin(below_ma5(x))   # 5일선 아래 제외
    sc["eligible"] &= ~sc.index.isin(list(rr_outside(ev, sc.index, "early")))     # 손익비 구간 밖 제외
    value = x["value_ma20"] if "value_ma20" in x else pd.Series(dtype=float)
    ranked = up.rank(sc, sc["eligible"], value, up.HOLD)
    show = ranked.head(TOP)
    sc["rank"] = np.nan
    order = up.rank(sc, sc["eligible"], value, -1)
    sc.loc[order.index, "rank"] = range(1, len(order) + 1)
    cands = []
    for i, code in enumerate(show.index, 1):
        if code in ev.index and code in x.index:
            c = candidate_dict(code, ev.loc[code], x.loc[code], name_of.get(code, code), i, theme_of.get(code))
            cands.append(apply(c, sc.loc[code]))
    tot = ranked["total"]
    lst = {"experimental": True, "name": "상승초기", "short": "상승초기", "description": DESC, "limitation": LIMIT,
           "count": int((tot >= up.WATCH).sum()), "candidates": cands}
    meta = {"version": up.VERSION, "rules": up.RULES_TEXT, "priority": int((tot >= up.PRIORITY).sum()),
            "watch": int(((tot >= up.WATCH) & (tot < up.PRIORITY)).sum()), "hold": int((tot < up.WATCH).sum()),
            "eligible": int(sc["eligible"].sum())}
    return {"list": lst, "meta": meta, "scores": sc}


def apply(c: dict, row: pd.Series) -> dict:
    ei = info(row)
    c = {**c, "v2_score": c.get("score"), "score": ei["score"], "max_score": 100, "stars": None, "tags": [],
         "reasons": ei["reasons"], "warnings": ei["warnings"], "early": ei}
    c["plan"] = {**(c.get("plan") or {}), "verdict": f"상승초기 {ei['label']}",
                 "verdict_reason": "관찰용 (매매 규칙 없음)", "reference_only": True}
    return c


def reasons(row: pd.Series) -> tuple[list[str], list[str]]:
    g = lambda k: row.get("rv_" + k)  # noqa: E731
    s = lambda k: float(row.get(k) or 0)  # noqa: E731
    ok = lambda v: v is not None and v == v  # noqa: E731
    R, W = [], []

    def add(good, bits, tail):
        bits = [b for b in bits if b]
        if bits:
            (R if good else W).append(" · ".join(bits) + tail)

    g20, s20, s5 = g("G20"), g("S20"), g("S5")
    add(s("trend25") >= 15, [f"20일선 대비 {g20:+.1f}%" if ok(g20) else None, f"20일선 5일 {s20:+.2f}%" if ok(s20) else None,
                             ("5일선 > 20일선" + (" · 5일선 상승" if ok(s5) and s5 > 0 else "")) if bool(g("MA5_GT")) else "5일선 ≤ 20일선"],
        f" → 단기 추세 {s('trend25'):.1f}/25")
    r5, r20, b20 = g("R5"), g("R20"), g("B20")
    add(s("mom20") >= 12, [f"5일 {r5:+.1f}%" if ok(r5) else None, f"20일 {r20:+.1f}%" if ok(r20) else None,
                           f"20일 저점 대비 {b20:+.1f}%" if ok(b20) else None], f" → 상승 모멘텀 {s('mom20'):.1f}/20")
    s60, dg, gp = g("S60"), g("DG"), g("GAP2060")
    add(s("mid20") >= 12, [f"60일선 10일 {s60:+.2f}%" if ok(s60) else None,
                           f"20·60일선 간격 {gp:+.1f}% ({dg:+.2f}%p 변화)" if ok(gp) and ok(dg) else None],
        f" → 중기 추세 {s('mid20'):.1f}/20")
    v5, vn, val, up_, dn = g("V5R"), g("VNOW"), g("VAL20"), g("UPV"), g("DNV")
    add(s("vol20") >= 12, [f"거래량 5일/20일 {v5:.2f}배" if ok(v5) else None, f"오늘 {vn:.1f}배" if ok(vn) else None,
                           ("하락일 없음" if dn == 0 else f"상승/하락일 거래량 {up_ / dn:.2f}배") if ok(up_) and ok(dn) else None,
                           f"거래대금 {val:,.0f}억" if ok(val) else None], f" → 거래량 {s('vol20'):.1f}/20")
    atr, rsi = g("ATR"), g("RSI")
    add(s("risk15") >= 9, [f"ATR {atr:.1f}%" if ok(atr) else None, f"RSI {rsi:.0f}" if ok(rsi) else None],
        f" → 과열·변동성 {s('risk15'):.1f}/15")
    ex = [up.EXCLUDE[k] for k in up.EXCLUDE if bool(row.get("ex_" + k))]
    if ex:
        W.append("진입 제외: " + ", ".join(ex))
    if not bool(row.get("risk_ok", True)):
        W.append("진입 제외: 위험 종목 (1차 필터·매수 차단)")
    if ok(rsi) and rsi > 70:
        W.append("RSI 70 초과 (과열)")
    return R, W


def info(row: pd.Series) -> dict:
    tot = _n(row.get("total"))
    R, W = reasons(row)
    rk = row.get("rank")
    el = bool(row.get("eligible"))
    return {"version": up.VERSION, "score": tot, "max": 100, "label": up.label(tot or 0) if el else "진입 제외",
            "eligible": el, "rank": int(rk) if rk == rk and rk is not None else None,
            "excluded": [up.EXCLUDE[k] for k in up.EXCLUDE if bool(row.get("ex_" + k))]
                        + ([] if bool(row.get("risk_ok", True)) else ["위험 종목"]),
            "parts": {k: _n(row.get(k)) for k in up.PARTS}, "labels": {k: v for k, (v, _) in up.PARTS.items()},
            "maxes": {k: m for k, (_, m) in up.PARTS.items()},
            "subs": [{"key": k, "part": p, "label": lab, "max": m, "score": _n(row.get(k), 2)}
                     for k, (p, lab, m) in up.SUBS.items()],
            "reasons": R, "warnings": W}
