"""익일 유망주 탭 → 리포트 strategies['nextday'] + report['nextday'] + 종목 상세 candidate['nextday']"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import nextday as nd
from .early import wide
from .v2_report import candidate_dict, below_ma5, rr_outside
from .trade_plan import round_tick

TOP = 30
DESC = ("장 마감 데이터로 다음 거래일에 움직임이 나올 만한 종목 (100점: 추세 25 · 거래량 20 · 가격 구조 20 · "
        "변동성 15 · 시장 대비 강도 10 · 재료·위험 10). A 80↑ 우선 관찰 · B 70~79 관심 · C 60~69 보조.")
LIMIT = ("관찰용 — 전날 점수가 높아도 다음 날 갭 상승 추격 매수를 뜻하지 않습니다. 시초가·거래량·지지를 확인하세요. "
         "뉴스 기사는 반영하지 않습니다(공시만).")
# V2 차단 사유 중 '위험'이 아닌 것 (익일 유망주는 자체 거래대금 10억 기준을 씀)
NOT_RISK = ("거래대금 부족", "손절폭이 지나치게 큼")


def _n(v, nd_=1):
    return None if v is None or v != v else round(float(v), nd_)


def _risk_blocks(b) -> list[str]:
    return [x for x in (b if isinstance(b, (list, tuple)) else []) if x not in NOT_RISK]


def build_section(pit, view, x: pd.DataFrame, ev: pd.DataFrame, name_of: dict, theme_of: dict, as_of) -> dict:
    O, H, L, C, V, VAL = wide(view.ohlcv(), days=160)
    d = C.index[-1]
    lst = pit.listing if not pit.listing.empty else pd.DataFrame(columns=["code", "name", "market", "is_admin"])
    market_of = dict(zip(lst["code"], lst["market"]))
    admin = set(lst.loc[lst["is_admin"].astype(bool), "code"]) if "is_admin" in lst else set()
    f = nd.raw_features(O, H, L, C, V, VAL, nd.index_returns(view.index()), market_of, dates=[d])
    cs = {k: v.loc[d] for k, v in f.items()}
    has_news = bool(ev.attrs.get("has_disc"))
    news = ev["news"].reindex(C.columns).astype(float) if "news" in ev else None
    s = nd.score_frame(cs, news, has_news)
    t = nd.totals(s)
    sc = pd.DataFrame({**s, **t})
    for k, v in cs.items():
        sc["rv_" + k] = v
    # 데이터 이력: 전체 기록 기준 (160일 창 밖도 셈)
    hist = view.ohlcv().groupby("code")["date"].count()
    sc["ndays"] = hist.reindex(sc.index).fillna(0)
    rb = ev["blocks"].reindex(sc.index) if "blocks" in ev else pd.Series([[]] * len(sc), index=sc.index)
    sc["risk"] = [_risk_blocks(b) for b in rb]
    halted = x["halted"].eq(True).reindex(sc.index, fill_value=False) if "halted" in x else None
    why = []
    for code in sc.index:
        w = []
        if not nd.common_stock(code, name_of.get(code, "")):
            w.append("우선주·스팩 등")
        if sc.at[code, "ndays"] < nd.MIN_DAYS:
            w.append("데이터 부족 (120거래일 미만)")
        v20 = sc.at[code, "rv_VAL20"]
        if not (v20 == v20) or v20 < nd.MIN_VALUE:
            w.append("거래대금 10억 미만")
        if code in admin:
            w.append("관리종목")
        if halted is not None and bool(halted[code]):
            w.append("거래정지")
        w += [b for b in sc.at[code, "risk"] if b not in w]
        why.append(w)
    b5 = below_ma5(x)                                     # 5일선 아래 → 추천 제외
    ro = rr_outside(ev, sc.index, "nextday")              # 손익비 구간 밖 → 제외
    why = [w + (["5일선 아래"] if c in b5 else []) + ([ro[c]] if c in ro else []) for c, w in zip(sc.index, why)]
    sc["why_not"] = why
    sc["has_news"] = has_news
    sc["eligible"] = [len(w) == 0 for w in why]
    ranked = nd.rank(sc, sc["eligible"], sc["rv_VAL20"], nd.GRADE_C)
    sc["rank"] = np.nan
    order = nd.rank(sc, sc["eligible"], sc["rv_VAL20"], -1)
    sc.loc[order.index, "rank"] = range(1, len(order) + 1)
    sc["_ma20"] = C.rolling(20).mean().loc[d]
    sc["_ma60"] = C.rolling(60).mean().loc[d]
    sc["_hi20p"] = H.shift(1).rolling(20).max().loc[d]
    sc["_o"], sc["_h"], sc["_l"], sc["_c"] = O.loc[d], H.loc[d], L.loc[d], C.loc[d]
    cands = []
    for i, code in enumerate(ranked.head(TOP).index, 1):
        if code in ev.index and code in x.index:
            c = candidate_dict(code, ev.loc[code], x.loc[code], name_of.get(code, code), i, theme_of.get(code))
            cands.append(apply(c, sc.loc[code]))
    tot = ranked["total"]
    counts = {"A": int((tot >= nd.GRADE_A).sum()), "B": int(((tot >= nd.GRADE_B) & (tot < nd.GRADE_A)).sum()),
              "C": int((tot < nd.GRADE_B).sum())}
    types = {}
    for c in cands:
        types[c["nextday"]["type"]] = types.get(c["nextday"]["type"], 0) + 1
    lst_ = {"experimental": True, "name": "익일 유망주", "short": "익일유망주", "description": DESC, "limitation": LIMIT,
            "count": len(ranked), "candidates": cands}
    meta = {"version": nd.VERSION, "as_of": d.strftime("%Y-%m-%d"), "rules": nd.RULES_TEXT, "grades": counts,
            "types": types, "eligible": int(sc["eligible"].sum()), "has_disclosures": has_news,
            "top": [{"code": c["code"], "name": c["name"], "score": c["score"], "grade": c["nextday"]["grade"],
                     "type": c["nextday"]["type"]} for c in cands[:10]]}
    return {"list": lst_, "meta": meta, "scores": sc}


def watch_plan(row: pd.Series) -> dict:
    """다음 거래일 관찰 계획: 지지·돌파·무효화·갭 추격 금지 (전날 종가 기준 가격)"""
    c, h, l = float(row["_c"]), float(row["_h"]), float(row["_l"])
    ma20, ma60, hp = row.get("_ma20"), row.get("_ma60"), row.get("_hi20p")
    atr = row.get("rv_ATR")
    atr = float(atr) if atr == atr and atr is not None else 3.0
    near20 = ma20 == ma20 and ma20 is not None and 0 <= c / ma20 - 1 <= 0.05
    support = float(ma20) if near20 else l
    brk = max(h, float(hp)) if hp == hp and hp is not None and c <= hp else h
    gap = c * (1 + max(3.0, atr) / 100)
    inval = min(l, support)
    rt = lambda v, d: int(round_tick(v, d)) if v == v and v else None  # noqa: E731
    return {"close": rt(c, "up"), "high": rt(h, "up"), "low": rt(l, "down"),
            "ma20": rt(ma20, "up") if ma20 == ma20 else None, "ma60": rt(ma60, "up") if ma60 == ma60 else None,
            "box_top": rt(hp, "up") if hp == hp else None,
            "support": rt(support, "down"), "breakout": rt(brk, "up"), "invalid": rt(inval, "down"),
            "no_chase": rt(gap, "up"), "gap_pct": round(max(3.0, atr), 1),
            "lines": [f"지지: {'20일선' if near20 else '전일 저가'} {rt(support, 'down'):,}원 부근 유지 확인",
                      f"돌파: {rt(brk, 'up'):,}원 위로 거래량 동반 시 강세" + (" (20일 박스 상단)" if hp == hp and brk == hp else " (전일 고가)"),
                      f"무효화: 종가가 {rt(inval, 'down'):,}원 아래로 마감하면 후보에서 제외",
                      f"갭 추격 금지: 시초가 {rt(gap, 'up'):,}원(+{max(3.0, atr):.1f}%) 이상이면 따라 사지 않기"]}


def apply(c: dict, row: pd.Series) -> dict:
    ni = info(row)
    c = {**c, "v2_score": c.get("score"), "score": ni["score"], "max_score": 100, "stars": None,
         "tags": ni["tags"], "reasons": ni["reasons"], "warnings": ni["warnings"], "nextday": ni}
    c["plan"] = {**(c.get("plan") or {}), "verdict": f"익일 {ni['grade']} · {ni['grade_label']}",
                 "verdict_reason": f"{ni['type']} — {nd.TYPE_CHECK.get(ni['type'], '')}", "reference_only": True}
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

    add(s("trendA") >= 15, [f"20일선 대비 {g('G20'):+.1f}%" if ok(g("G20")) else None,
                            f"20일선 5일 {g('S20'):+.2f}%" if ok(g("S20")) else None,
                            f"60일선 10일 {g('S60'):+.2f}%" if ok(g("S60")) else None,
                            ("20일선 ≥ 60일선" if bool(g("MA_UP")) else "20일선 < 60일선"),
                            f"20일 고점 대비 {g('DD20'):+.1f}%" if ok(g("DD20")) else None], f" → 추세 {s('trendA'):.1f}/25")
    add(s("volB") >= 12, [f"오늘 거래량 {g('V1'):.1f}배" if ok(g("V1")) else None,
                          f"5일 거래량 {g('V5'):.2f}배" if ok(g("V5")) else None,
                          f"오늘 거래대금 {g('VAL1'):.1f}배" if ok(g("VAL1")) else None,
                          f"20일 평균 거래대금 {g('VAL20'):,.0f}억" if ok(g("VAL20")) else None], f" → 거래 {s('volB'):.1f}/20")
    add(s("priceC") >= 12, [f"종가 위치 {g('P') * 100:.0f}%" if ok(g("P")) else "고가=저가",
                            (f"20일 고점 돌파 ({g('HI20'):+.1f}%)" if g("HI20") > 0 else f"20일 고점까지 {g('HI20'):.1f}%")
                            if ok(g("HI20")) else None,
                            (f"박스 폭 {g('BOXW'):.0f}%로 수축" if bool(g("SQUEEZE")) and ok(g("BOXW")) else None)],
        f" → 가격 구조 {s('priceC'):.1f}/20")
    add(s("movD") >= 9, [f"ATR {g('ATR'):.1f}%" if ok(g("ATR")) else None,
                         f"5일/20일 변동성 {g('RV'):.2f}배" if ok(g("RV")) else None], f" → 변동성 {s('movD'):.1f}/15")
    add(s("rsE") >= 6, [f"오늘 시장 대비 {g('EX1'):+.1f}%p" if ok(g("EX1")) else None,
                        f"5일 시장 대비 {g('EX5'):+.1f}%p" if ok(g("EX5")) else None], f" → 상대 강도 {s('rsE'):.1f}/10")
    if not bool(row.get("has_news", True)):
        W.append("공시 정보 미확인 → 재료 5/10 (중립)")
    elif s("f_news") > 5.5:
        R.append(f"호재 공시 → 재료 {s('newsF'):.1f}/10")
    elif s("f_news") < 4.5:
        W.append(f"악재 공시 → 재료 {s('newsF'):.1f}/10")
    for t in nd.tags_of(row):
        if t != "공시 정보 미확인":
            W.append(t)
    return R, W


def info(row: pd.Series) -> dict:
    tot = _n(row.get("total"))
    gr, gl = nd.grade(tot or 0)
    types = nd.types_of(row)
    R, W = reasons(row)
    rk = row.get("rank")
    el = bool(row.get("eligible"))
    why = list(row.get("why_not") or [])
    return {"version": nd.VERSION, "score": tot, "max": 100, "grade": gr if el else "-",
            "grade_label": gl if el else "제외", "label": (f"{gr} {gl}" if el else "제외"),
            "type": types[0], "types": types, "check": nd.TYPE_CHECK.get(types[0]), "tags": nd.tags_of(row),
            "eligible": el, "why_not": why, "excluded": why, "rank": int(rk) if rk == rk and rk is not None else None,
            "parts": {k: _n(row.get(k)) for k in nd.PARTS}, "labels": {k: v for k, (v, _) in nd.PARTS.items()},
            "maxes": {k: m for k, (_, m) in nd.PARTS.items()},
            "subs": [{"key": k, "part": p, "label": lab, "max": m, "score": _n(row.get(k), 2)}
                     for k, (p, lab, m) in nd.SUBS.items()],
            "watch": watch_plan(row) if row.get("_c") == row.get("_c") and row.get("_c") else None,
            "reasons": R, "warnings": W}


LOG_KEY = "meta/nextday_log.json"


def outcome(entry: dict, ohlcv: pd.DataFrame) -> dict | None:
    """기록된 후보의 다음 거래일 성과 (결과 평가 전용 — 점수 계산에는 쓰지 않음)
    갭 = 시초가/전일 종가, 시가→종가, 종가→종가, 장중 최대 상승(MFE)·하락(MAE) = 시가 기준 고가·저가"""
    d = pd.Timestamp(entry["date"])
    codes = [p["code"] for p in entry["picks"]]
    nxt = ohlcv[(ohlcv["date"] > d) & ohlcv["code"].isin(codes)]
    if nxt.empty:
        return None
    day = nxt["date"].min()
    t = nxt[nxt["date"] == day].set_index("code")
    rows = []
    for p in entry["picks"]:
        if p["code"] not in t.index or not p.get("close"):
            continue
        r = t.loc[p["code"]]
        o, h, l, c, pc = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), float(p["close"])
        if o <= 0 or pc <= 0:
            continue
        rows.append({"code": p["code"], "name": p.get("name"), "grade": p.get("grade"), "type": p.get("type"),
                     "gap": round((o / pc - 1) * 100, 2), "oc": round((c / o - 1) * 100, 2),
                     "cc": round((c / pc - 1) * 100, 2), "mfe": round((h / o - 1) * 100, 2),
                     "mae": round((l / o - 1) * 100, 2),
                     "chased": bool(p.get("no_chase") and o >= p["no_chase"]),
                     "invalid": bool(p.get("invalid") and c < p["invalid"])})
    if not rows:
        return None
    df = pd.DataFrame(rows)
    m = lambda k: round(float(df[k].mean()), 2)  # noqa: E731
    return {"date": entry["date"], "next": day.strftime("%Y-%m-%d"), "n": len(df),
            "avg": {k: m(k) for k in ("gap", "oc", "cc", "mfe", "mae")},
            "win_cc": round(float((df["cc"] > 0).mean()) * 100, 1), "win_oc": round(float((df["oc"] > 0).mean()) * 100, 1),
            "gap_over": int(df["chased"].sum()), "rows": rows}


def attach_log(report: dict, pit, sync=None, record: bool = False, keep: int = 250) -> dict:
    """선정 스냅샷 저장(저녁 배치만) + 직전 후보들의 다음 날 결과를 report['nextday'] 에 붙임"""
    meta = report.get("nextday")
    if not meta:
        return {}
    log = (sync.get_json(LOG_KEY) if sync else None) or {"version": nd.VERSION, "entries": []}
    cands = (report.get("strategies", {}).get("nextday") or {}).get("candidates", [])
    if record:
        snap = {"date": meta["as_of"], "version": nd.VERSION, "picks": [
            {"code": c["code"], "name": c["name"], "score": c["score"], "grade": c["nextday"]["grade"],
             "type": c["nextday"]["type"], **{k: (c["nextday"].get("watch") or {}).get(k)
                                              for k in ("close", "support", "breakout", "invalid", "no_chase")}}
            for c in cands]}
        log["entries"] = [e for e in log["entries"] if e["date"] != snap["date"]] + [snap]
        log["entries"] = sorted(log["entries"], key=lambda e: e["date"])[-keep:]
        if sync:
            sync.put_json(LOG_KEY, log)
    res = []
    for e in log["entries"][-20:]:
        if e["date"] >= meta["as_of"]:
            continue
        o = outcome(e, pit.ohlcv)
        if o:
            res.append(o)
    meta["results"] = res[-10:][::-1]       # 최근 결과 먼저
    meta["logged"] = len(log["entries"])
    return meta


def live_status(w: dict, o: float | None, p: float | None) -> str:
    if not w or not p:
        return "시세 없음"
    if o and w.get("no_chase") and o >= w["no_chase"]:
        return "갭 추격 금지"
    if w.get("invalid") and p < w["invalid"]:
        return "무효화 (지지 이탈)"
    if w.get("breakout") and p >= w["breakout"]:
        return "돌파"
    if w.get("support") and p <= w["support"] * 1.01:
        return "지지선 근처"
    return "관찰 중"


def carry_over(report: dict, prev: dict | None, bars: pd.DataFrame, hm: str) -> bool:
    """장중: 익일 유망주는 '전날 장 마감 점수'를 그대로 두고 지금 시세로 상태만 따로 붙임
    prev = 전날 저녁 리포트(reports/latest.json), bars = 오늘 진행 중 봉 (code, open, high, low, close)"""
    if not prev or not (prev.get("strategies") or {}).get("nextday"):
        report.get("strategies", {}).pop("nextday", None)
        report.pop("nextday", None)
        return False
    lst = dict(prev["strategies"]["nextday"])
    b = bars.set_index("code") if len(bars) else pd.DataFrame()
    out = []
    for c in lst.get("candidates", []):
        ni = dict(c.get("nextday") or {})
        w = ni.get("watch") or {}
        r = b.loc[c["code"]] if c["code"] in b.index else None
        o = float(r["open"]) if r is not None and r["open"] == r["open"] else None
        p = float(r["close"]) if r is not None and r["close"] == r["close"] else None
        pc = w.get("close")
        ni["live"] = {"time": hm, "open": o, "price": p, "status": live_status(w, o, p),
                      "gap": round((o / pc - 1) * 100, 2) if o and pc else None,
                      "chg": round((p / pc - 1) * 100, 2) if p and pc else None}
        out.append({**c, "nextday": ni})
    lst["candidates"] = out
    report.setdefault("strategies", {})["nextday"] = lst
    report["nextday"] = {**(prev.get("nextday") or {}), "live_time": hm}
    return True
