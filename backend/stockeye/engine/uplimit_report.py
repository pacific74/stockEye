"""상파 탭 → 리포트 strategies['uplimit'] + report['uplimit'] + 종목 상세 candidate['uplimit']"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import uplimit as ul
from .early import wide
from .nextday import common_stock
from .trade_plan import round_tick
from .v2_report import candidate_dict, below_ma5

TOP = 30
MIN_VALUE = 5.0          # 억원: 20일 평균 거래대금이 이보다 작으면 제외 (10억 미만은 경고)
NOT_RISK = ("거래대금 부족", "손절폭이 지나치게 큼")
DESC = ("상한가 도달·종가 상한가(A)와, 어제 상한가 뒤 오늘 거래량이 줄며 음봉으로 마감한 종목(B)을 찾습니다. "
        "점수는 정렬용 보조 지표입니다.")
LIMIT = "관찰용 — 거래량 감소·조정은 재상승을 검토할 단서일 뿐 매수 신호가 아닙니다. 다음 날 지지·거래량을 확인하세요."


def _n(v, nd=1):
    return None if v is None or v != v else round(float(v), nd)


def build_section(pit, view, x: pd.DataFrame, ev: pd.DataFrame, name_of: dict, theme_of: dict, as_of,
                  market: dict | None = None) -> dict:
    oh = view.ohlcv()
    O, H, L, C, V, VAL = wide(oh, days=90)
    CHG = None
    if "chg_pct" in oh:
        dts = C.index
        CHG = oh[oh["date"].isin(dts)].pivot(index="date", columns="code", values="chg_pct").reindex_like(C).astype(float)
    d = C.index[-1]
    f = ul.features(O, H, L, C, V, VAL, CHG, dates=[d])
    cs = pd.DataFrame({k: v.loc[d] for k, v in f.items()})
    cand = cs[cs["REACH"].astype(bool) | cs["TYPE_B"].astype(bool)].copy()
    lst = pit.listing if not pit.listing.empty else pd.DataFrame(columns=["code", "name", "is_admin"])
    admin = set(lst.loc[lst["is_admin"].astype(bool), "code"]) if "is_admin" in lst else set()
    has_news = bool(ev.attrs.get("has_disc"))
    weak = (market or {}).get("mood") == "약세"
    rows = []
    b5 = below_ma5(x)                                     # 5일선 아래 → 추천 제외
    for code, r in cand.iterrows():
        rr = r.to_dict()
        why = ["5일선 아래"] if code in b5 else []
        if not common_stock(code, name_of.get(code, "")):
            why.append("우선주·스팩 등")
        if code in admin:
            why.append("관리종목")
        if code in ev.index:
            why += [b for b in (ev.at[code, "blocks"] if "blocks" in ev and isinstance(ev.at[code, "blocks"], list) else [])
                    if b not in NOT_RISK]
        v20 = rr.get("VAL20")
        if v20 is None or v20 != v20 or v20 < MIN_VALUE:
            why.append("거래대금 5억 미만")
        news = float(ev.at[code, "news"]) if code in ev.index and "news" in ev else None
        sc = ul.score_row(rr, news, has_news)
        rows.append({"code": code, **{f"rv_{k}": v for k, v in rr.items()}, **{k: sc.get(k) for k in ul.PARTS},
                     "total": sc["total"], "type": sc["type"], "tags": sc["tags"],
                     "warns": ul.warnings_of(rr, weak), "why_not": why, "eligible": not why, "has_news": has_news})
    sc = pd.DataFrame(rows).set_index("code") if rows else pd.DataFrame(columns=["total", "eligible"])
    sc["_v"] = cs["VAL20"].reindex(sc.index).fillna(0) if len(sc) else []
    ok = sc[sc["eligible"].astype(bool)] if len(sc) else sc
    order = ok.sort_values(["total", "_v"], ascending=[False, False]) if len(ok) else ok
    sc["rank"] = np.nan
    if len(order):
        sc.loc[order.index, "rank"] = range(1, len(order) + 1)
    cands = []
    for i, code in enumerate(order.head(TOP).index, 1):
        if code in ev.index and code in x.index:
            c = candidate_dict(code, ev.loc[code], x.loc[code], name_of.get(code, code), i, theme_of.get(code))
            cands.append(apply(c, sc.loc[code]))
    cnt = {t: int((ok["type"] == t).sum()) if len(ok) else 0 for t in ("A", "A-종가", "B")}
    lst_ = {"experimental": True, "name": "상파", "short": "상파", "description": DESC, "limitation": LIMIT,
            "count": len(order), "candidates": cands}
    meta = {"version": ul.VERSION, "as_of": d.strftime("%Y-%m-%d"), "rules": ul.RULES_TEXT, "counts": cnt}
    return {"list": lst_, "meta": meta, "scores": sc}


def label(row) -> str:
    t = row.get("type") or ""
    tags = list(row.get("tags") or [])
    if t == "B":
        return "B " + (tags[0].split(" ", 1)[0] if tags else "") + (" +B4" if any(x.startswith("B4") for x in tags) else "")
    return {"A-종가": "A 상한가 종가", "A": "A 상한가 도달"}.get(t, "-")


def watch(row) -> dict | None:
    """다음 거래일 확인: 지지(B=상한가일 저가, A=오늘 저가)·무효화·갭 추격 주의"""
    g = lambda k: row.get("rv_" + k)  # noqa: E731
    lim = g("LIMIT")
    t = row.get("type")
    pl = g("PREV_LOW")
    if t == "B" and pl == pl and pl:
        sup, sup_lab = float(pl), "상한가 당일 저가"
    else:
        return None
    return {"support": int(round_tick(sup, "down")), "support_label": sup_lab,
            "limit": None if lim != lim or lim is None else int(lim),
            "lines": [f"지지: {sup_lab} {int(round_tick(sup, 'down')):,}원 — 종가 이탈 시 조건 무효",
                      "시초가 갭 +5% 이상이면 추격 위험 · 거래량 급증에 가격이 밀리면 매도 압력",
                      "재상승 확인은 시초가만 보지 말고 가격 회복과 거래량을 같이 확인"]}


def apply(c: dict, row: pd.Series) -> dict:
    ui = info(row)
    c = {**c, "v2_score": c.get("score"), "score": ui["score"], "max_score": 100, "stars": None, "tags": [],
         "reasons": ui["reasons"], "warnings": ui["warnings"], "uplimit": ui}
    c["plan"] = {**(c.get("plan") or {}), "verdict": f"상파 {ui['label']}",
                 "verdict_reason": "관찰용 (매매 규칙 없음)", "reference_only": True}
    return c


def reasons(row) -> tuple[list[str], list[str]]:
    g = lambda k: row.get("rv_" + k)  # noqa: E731
    ok = lambda v: v is not None and v == v  # noqa: E731
    R = []
    t = row.get("type")
    if t == "B":
        R.append("어제 종가 상한가" + (f" (종가 위치 {g('PREV_POS') * 100:.0f}%)" if ok(g("PREV_POS")) else ""))
        R.append(" · ".join(x for x in [
            f"거래량 감소율 {g('VDROP'):.0f}%" if ok(g("VDROP")) else None,
            f"등락 {g('CHG'):+.1f}%" if ok(g("CHG")) else None,
            f"음봉 몸통 {g('BODY'):.1f}%" if ok(g("BODY")) else None,
            f"종가 위치 {g('POS') * 100:.0f}%" if ok(g("POS")) else "고가=저가"] if x))
        R.append(("상한가 당일 저가 지지" if bool(g("SUPPORT_OK")) else "상한가 당일 저가 이탈")
                 + (f" ({int(g('PREV_LOW')):,}원)" if ok(g("PREV_LOW")) else ""))
    elif t in ("A", "A-종가"):
        R.append(("종가까지 상한가 유지" if t == "A-종가" else "장중 상한가 도달, 종가는 밀림")
                 + (f" · 상한가 {int(g('LIMIT')):,}원" if ok(g("LIMIT")) else ""))
        if ok(g("VOL_SURGE")):
            R.append(f"거래량 평소의 {g('VOL_SURGE'):.1f}배 · 거래대금 {g('VAL_TODAY'):,.0f}억")
    if ok(g("VAL20")):
        R.append(f"20일 평균 거래대금 {g('VAL20'):,.0f}억")
    W = list(row.get("warns") or [])
    if not bool(row.get("has_news", True)):
        W.append("공시 정보 미확인 (위험 점수 중립)")
    return R, W


def info(row) -> dict:
    tot = _n(row.get("total"))
    R, W = reasons(row)
    rk = row.get("rank")
    el = bool(row.get("eligible"))
    return {"version": ul.VERSION, "score": tot, "max": 100, "label": label(row) if el else "제외",
            "type": row.get("type"), "tags": list(row.get("tags") or []), "eligible": el,
            "why_not": list(row.get("why_not") or []), "excluded": list(row.get("why_not") or []),
            "rank": int(rk) if rk == rk and rk is not None else None,
            "parts": {k: _n(row.get(k)) for k in ul.PARTS}, "labels": {k: v for k, (v, _) in ul.PARTS.items()},
            "maxes": {k: m for k, (_, m) in ul.PARTS.items()}, "subs": [],
            "raw": {k: _n(row.get("rv_" + k), 2) for k in ("LIMIT", "VDROP", "CHG", "BODY", "POS", "VAL20", "PREV_LOW")},
            "watch": watch(row), "status": "미확인", "reasons": R, "warnings": W}


def carry_over(report: dict, prev: dict | None, bars: pd.DataFrame, hm: str) -> bool:
    """장중: 상파 후보는 전날 장 마감 판정을 그대로 두고, 지금 시세로 다음 날 확인 상태만 붙임"""
    if not prev or not (prev.get("strategies") or {}).get("uplimit"):
        (report.get("strategies") or {}).pop("uplimit", None)
        report.pop("uplimit", None)
        return False
    lst = dict(prev["strategies"]["uplimit"])
    b = bars.set_index("code") if len(bars) else pd.DataFrame()
    out = []
    for c in lst.get("candidates", []):
        ui = dict(c.get("uplimit") or {})
        r = b.loc[c["code"]] if c["code"] in b.index else None
        pc = (c.get("plan") or {}).get("price")
        o = float(r["open"]) if r is not None else None
        p = float(r["close"]) if r is not None else None
        sup = (ui.get("watch") or {}).get("support")
        if p is None or not pc:
            st = "미확인"
        elif sup and p < sup:
            st = "조건 무효 (지지 이탈)"
        elif o and o >= pc * 1.05:
            st = "확인 중 · 갭 추격 주의"
        else:
            st = "확인 중" + (" (전일 종가 회복)" if p >= pc else "")
        ui["status"] = st
        ui["live"] = {"time": hm, "open": o, "price": p, "status": st,
                      "gap": round((o / pc - 1) * 100, 2) if o and pc else None,
                      "chg": round((p / pc - 1) * 100, 2) if p and pc else None}
        out.append({**c, "uplimit": ui})
    lst["candidates"] = out
    report.setdefault("strategies", {})["uplimit"] = lst
    report["uplimit"] = {**(prev.get("uplimit") or {}), "live_time": hm, "provisional": False}
    return True
