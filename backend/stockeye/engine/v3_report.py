"""V3 기준 전략 → 리포트·앱·검증

- build_section: 오늘 V3B 상위 10 (리포트의 strategies['v3'] + report['v3'])
- attach_portfolio: 고정 이후 기록(Storage meta/v3_log.json)으로 모의 운용을 그대로 다시 계산 → 보유·매도 예정일·성과
  (선정일에만 상위 10·후보 전체를 기록. 기록은 저녁 배치만 하고, 장중 재분석은 읽기만)
- history_entries / validate: 과거 전 기간 '종목 선정력'과 '실제 매매'를 따로 계산 (주간 백테스트)
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from . import v3
from ..analysis import v3_outcome
from .v2_report import candidate_dict

log = logging.getLogger(__name__)
LOG_KEY = "meta/v3_log.json"
DESC = ("변동성·재무·가격위치(60점)로 고른 상위 10개. 5거래일마다 선정 → 다음 거래일 시가 매수 → "
        "20거래일 보유 (손절·익절 없음, 다시 선정되면 연장). 규칙 고정: " + v3.VERSION)
PERIODS = [("설정 기간", "2021-07-01", "2024-12-31"), ("확인 기간 (1회)", "2025-01-01", v3.LOCKED_AT)]


def _fin_at(pit, codes, as_of):
    from ..data.financials import FinIndex
    fin = getattr(pit, "financials", None)
    if fin is None or not len(fin):
        return pd.DataFrame()
    fi = getattr(pit, "_v3_fin", None)
    if fi is None:
        fi = FinIndex.from_raw(fin)
        pit._v3_fin = fi
    return fi.at(list(codes), pd.Timestamp(as_of))


RAW_X = ["close", "atr_pct", "dist_sma20", "sma60", "low20", "high20_prev", "ret5", "ret20", "per", "pbr"]
RAW_F = ["op_pos", "roe", "op_margin", "debt_ratio", "current_ratio", "rev_yoy", "op_yoy", "impaired"]


def to100(v) -> float | None:
    """V3B 원점수(60점 만점) → 100점 환산 (표시용 — 순위·규칙은 원점수 그대로)"""
    return None if v is None or v != v else round(float(v) * 100 / 60, 1)


def build_section(pit, x: pd.DataFrame, ev: pd.DataFrame, name_of: dict, theme_of: dict, as_of) -> dict:
    """오늘 V3B 점수 (1차 필터 통과 종목) → {'list': strategies 항목, 'meta': report['v3']}"""
    s1 = ev[ev["stage1"]].index
    xs = x.loc[x.index.intersection(s1)]
    sec = getattr(pit, "sectors", pd.DataFrame())
    sector_of = dict(zip(sec["code"], sec["sector"])) if not sec.empty else {}
    fin = _fin_at(pit, xs.index, as_of)
    sc = v3.score(xs, ev["blocked"], fin, sector_of)
    t = v3.top(sc, x=xs)
    # 근거 문장용 원자료 (점수 계산에는 쓰지 않음)
    sc = sc.copy()
    sc["blocks"] = ev["blocks"].reindex(sc.index) if "blocks" in ev else None
    for c_ in RAW_X:
        sc["x_" + c_] = xs[c_] if c_ in xs else np.nan
    for c_ in RAW_F:
        sc["f_" + c_] = fin[c_].reindex(sc.index) if len(fin) and c_ in fin else np.nan
    # 표시용 참고 항목 (V3 표 배점, V3B 점수에는 들어가지 않음)
    c_ = xs["close"]
    sc["ref_trend5"] = (2 * (c_ > xs["sma60"]).astype(float) + 2 * (xs["sma60_slope"] > 0).astype(float)
                        + (xs["sma20"] > xs["sma60"]).astype(float))
    v5 = xs["vol5_ratio"]
    sc["ref_vol5"] = np.select([v5.isna(), v5 > 2, v5 > 1.3, v5 < 0.6], [2.5, 0, 3, 3], default=5)
    for k_, src, mul in (("ref_value5", "value", 1.0), ("ref_flow10", "flow", 10 / 15), ("ref_news15", "news", 1.0)):
        sc[k_] = ev[src].reindex(sc.index).astype(float) * mul if src in ev else np.nan
    sc["rank"] = np.nan
    sc.loc[t.index, "rank"] = range(1, len(t) + 1)
    cands = []
    for i, code in enumerate(t.index, 1):
        c = candidate_dict(code, ev.loc[code], x.loc[code], name_of.get(code, code), i, theme_of.get(code))
        c = apply(c, sc.loc[code])
        cands.append(c)
    lst = {"name": "V3 기준 전략", "short": "V3 기준", "description": DESC, "count": int(sc["eligible"].sum()),
           "candidates": cands}
    meta = {"version": v3.VERSION, "locked_at": v3.LOCKED_AT, "rules": v3.RULES_TEXT, "eligible": int(sc["eligible"].sum()),
            "top": [{"code": c["code"], "name": c["name"], "score": c["score"], "raw": c["v3"]["raw"]} for c in cands]}
    return {"list": lst, "meta": meta, "eligible": list(sc.index[sc["eligible"]]), "scores": sc}


def apply(c: dict, row: pd.Series) -> dict:
    """후보 dict 를 V3 로: 점수(100점 환산)·판정·근거·주의·설명. 매수구간·목표·손절은 '참고'로 남김"""
    vi = info(row)
    rank = vi["rank"]
    c = {**c, "v2_score": c.get("score"), "score": vi["score"], "max_score": 100, "stars": None, "tags": [],
         "reasons": vi["reasons"], "warnings": vi["warnings"], "v3": {**(c.get("v3") or {}), **vi}}
    verdict = f"V3 선정 {rank}위" if rank else ("V3 자격 있음" if vi["eligible"] else "V3 자격 없음")
    why = "V3B 상위 10 — 다음 거래일 시가 매수 · 20거래일 보유" if rank else (
        "상위 10 에 들면 매수 (5거래일마다 선정)" if vi["eligible"] else " · ".join(vi["why_not"]) or "조건 미달")
    c["plan"] = {**(c.get("plan") or {}), "verdict": verdict, "verdict_reason": why, "reference_only": True}
    return c


def _pct(v, nd=1):
    return None if v is None or v != v else round(float(v) * 100, nd)


def reasons_v3(row: pd.Series) -> tuple[list[str], list[str]]:
    """V3B 근거(✓)와 주의(⚠) 문장 — 점수를 매긴 실제 값으로"""
    g = row.get
    R, W = [], []
    atr = g("x_atr_pct")
    if atr == atr and atr is not None:
        (R if g("vola15", 0) >= 9 else W).append(
            f"{'변동성 낮음' if g('vola15', 0) >= 9 else '변동성 큼'} (하루 평균 변동폭 {_pct(atr)}%) → 변동성 {g('vola15'):.0f}/15")
    if g("f_op_pos") == g("f_op_pos") and g("f_op_pos") is not None:
        bits = ["영업이익 흑자" if bool(g("f_op_pos")) else "영업적자"]
        for k, lab, cut in (("f_roe", "ROE", 0.08), ("f_op_margin", "영업이익률", 0.05)):
            v = g(k)
            if v == v and v is not None:
                bits.append(f"{lab} {_pct(v)}%")
        dr = g("f_debt_ratio")
        if dr == dr and dr is not None:
            bits.append(f"부채비율 {_pct(dr, 0)}%")
        for k, lab in (("f_rev_yoy", "매출"), ("f_op_yoy", "영업이익")):
            v = g(k)
            if v == v and v is not None:
                bits.append(f"{lab} {'+' if v >= 0 else ''}{_pct(v)}% (전년 대비)")
        (R if g("fin25", 0) >= 15 else W).append(" · ".join(bits) + f" → 재무 {g('fin25'):.1f}/25")
        if dr == dr and dr is not None and dr >= 2:
            W.append(f"부채비율 높음 ({_pct(dr, 0)}%)")
        if bool(g("f_impaired")):
            W.append("자본잠식")
    else:
        W.append("재무 자료 없음 → 재무 중립 10/25")
    pos = []
    d20 = g("x_dist_sma20")
    if d20 == d20 and d20 is not None and abs(d20) <= 0.03:
        pos.append(f"20일선 근처 (이격 {'+' if d20 >= 0 else ''}{_pct(d20)}%)")
    c, s60 = g("x_close"), g("x_sma60")
    if c and s60 and s60 == s60 and abs(c / s60 - 1) <= 0.03:
        pos.append(f"60일선 근처 ({'+' if c >= s60 else ''}{_pct(c / s60 - 1)}%)")
    h20 = g("x_high20_prev")
    if c and h20 and h20 == h20 and -0.15 <= c / h20 - 1 <= -0.04:
        pos.append(f"최근 20일 고점 대비 {_pct(c / h20 - 1)}% 조정")
    l20 = g("x_low20")
    if c and l20 and l20 == l20 and c <= l20 * 1.05:
        pos.append("20일 저점(지지선) 근처")
    if pos:
        R.append(" · ".join(pos) + f" → 가격위치 {g('pos20'):.0f}/20")
    r5, r20 = g("x_ret5"), g("x_ret20")
    if (r5 == r5 and r5 is not None and r5 > 0.10) or (r20 == r20 and r20 is not None and r20 > 0.20):
        W.append(f"최근 급등 (5일 {_pct(r5)}% · 20일 {_pct(r20)}%) → 가격위치 최대 5점")
    elif not pos:
        W.append(f"좋은 매수 위치 아님 (이평선·지지선에서 멂) → 가격위치 {g('pos20'):.0f}/20")
    return R, W


def info(row: pd.Series) -> dict:
    """종목 상세용: V3B 점수(100점 환산 + 원점수) · 구성 · 오늘 상태 · 근거/주의 · 설명"""
    why = []
    if bool(row.get("blocked")):
        b = row.get("blocks")
        why.append("매수 차단: " + (", ".join(b) if isinstance(b, (list, tuple)) and len(b) else "위험 사유"))
    if bool(row.get("hot")):
        why.append("과열 (5일 +20% / 20일 +30% / RSI 75 초과 / 거래량 급증+급등)")
    if not bool(row.get("trend_ok")):
        why.append("추세 필터 (60일선 아래 + 60일선 하락)")
    rank = row.get("rank")
    rank = int(rank) if rank == rank and rank is not None else None
    status = f"V3 상위 10 ({rank}위)" if rank else ("자격 있음 · 상위 10 밖" if bool(row.get("eligible")) else "자격 없음")
    R, W = reasons_v3(row)
    raw = round(float(row["v3b"]), 1)
    s100 = to100(raw)
    text = (f"V3B {s100:.0f}점 (원점수 {raw}/60) · {status}. "
            + ("근거: " + "; ".join(R) + ". " if R else "")
            + ("주의: " + "; ".join(W + why) + ". " if (W or why) else "")
            + ("V3 규칙: 선정 다음 거래일 시가 매수 → 20거래일째 종가 매도 (손절·익절 없음, 다시 선정되면 연장)."
               if rank else "V3B 상위 10 에 들 때만 매수합니다."))
    return {"score": s100, "raw": raw, "max": 100, "raw_max": 60, "rank": rank, "eligible": bool(row.get("eligible")),
            "status": status, "why_not": why, "version": v3.VERSION, "reasons": R, "warnings": W, "text": text,
            "parts": {k: round(float(row[k]), 1) for k in v3.PARTS}, "labels": {k: v for k, (v, _) in v3.PARTS.items()},
            "maxes": {k: m for k, (_, m) in v3.PARTS.items()},
            # 점수 미반영 참고 항목 (V3 표 배점): 추세·거래량·거래대금·수급·공시
            "ref_parts": {k: (None if row.get("ref_" + k) != row.get("ref_" + k) or row.get("ref_" + k) is None
                              else round(float(row["ref_" + k]), 1)) for k in REF},
            "ref_labels": {k: v for k, (v, _) in REF.items()}, "ref_maxes": {k: m for k, (_, m) in REF.items()}}


REF = {"trend5": ("추세", 5), "vol5": ("거래량", 5), "value5": ("거래대금", 5), "flow10": ("수급", 10), "news15": ("공시", 15)}


def _prices(pit, since: pd.Timestamp):
    oh = pit.ohlcv
    oh = oh[oh["date"] >= since - pd.Timedelta(days=10)]
    O = oh.pivot(index="date", columns="code", values="open").astype(float)
    C = oh.pivot(index="date", columns="code", values="close").astype(float)
    return O.where(O > 0), C.where(C > 0)


def attach_portfolio(report: dict, pit, sync=None, record: bool = False, eligible: list | None = None) -> dict:
    """report['v3'] 에 선정일 여부·매수/매도 예정일·모의 보유·고정 이후 성과를 붙임. 기록(record)은 저녁 배치만."""
    meta = report.get("v3")
    if not meta:
        return {}
    date = report["date"]
    td = pit.trading_dates()
    logd = None
    if sync is not None:
        try:
            logd = sync.get_json(LOG_KEY)
        except Exception as e:  # noqa: BLE001
            log.warning("V3 기록 읽기 실패: %s", e)
    logd = logd or {"version": v3.VERSION, "anchor": date, "entries": []}
    if logd.get("version") != v3.VERSION:
        log.warning("V3 규칙 버전이 바뀜 (%s → %s): 새 기록 시작", logd.get("version"), v3.VERSION)
        logd = {"version": v3.VERSION, "anchor": date, "entries": [], "previous": logd}
    anchor = logd["anchor"]
    entry = v3.is_entry_day(td, anchor, date)
    elig = list(eligible or [])
    if entry and record and not any(e["date"] == date for e in logd["entries"]):
        logd["entries"].append({"date": date, "picks": [t["code"] for t in meta["top"]],
                                "names": {t["code"]: t["name"] for t in meta["top"]},
                                "scores": {t["code"]: t["score"] for t in meta["top"]}, "eligible": elig})
        if sync is not None:
            try:
                sync.put_json(LOG_KEY, logd)
                log.info("V3 선정 기록: %s (%d종목)", date, len(meta["top"]))
            except Exception as e:  # noqa: BLE001
                log.warning("V3 기록 저장 실패: %s", e)
    cal = v3.calendar(td)
    buy = v3.future_days(pd.Timestamp(date), 1)[0].strftime("%Y-%m-%d")
    meta.update({"anchor": anchor, "entry_day": bool(entry),
                 "next_entry": date if entry else v3.next_entry_day(td, anchor, date),
                 "buy_date": buy if entry else None, "sell_date": v3.nth_day(cal, buy, v3.RULES["hold"]) if entry else None,
                 "calendar": cal, "entries_logged": len(logd["entries"])})
    # 고정 이후 모의 운용 (기록된 선정만으로)
    names = {}
    for e in logd["entries"]:
        names.update(e.get("names", {}))
    if logd["entries"]:
        O, C = _prices(pit, pd.Timestamp(anchor))
        picks = {pd.Timestamp(e["date"]): e["picks"] for e in logd["entries"]}
        sim = v3.simulate(picks, O, C, start=anchor)
        future = [d for d in cal if d > date]
        hold = []
        for h in sim.holdings:
            left = v3.RULES["hold"] - h["days"]
            hold.append({**h, "name": names.get(h["code"], h["code"]), "ret": round(h["ret"] * 100, 2),
                         "weight": round(h["weight"] * 100, 1), "days_left": left,
                         "sell_date": future[left - 1] if 0 < left <= len(future) else date})
        hold.sort(key=lambda h: h["sell_date"])
        trades = [{**t, "name": names.get(t["code"], t["code"]), "ret": round(t["ret"] * 100, 2)} for t in sim.trades[-30:]]
        fwd = v3_outcome.forward(O, C)
        meta["portfolio"] = {"since": anchor, "holdings": hold, "recent_trades": trades[::-1],
                             "trading": v3.metrics(sim),
                             "selection": v3_outcome.selection_power(logd["entries"], fwd)}
    else:
        meta["portfolio"] = {"since": anchor, "holdings": [], "recent_trades": [], "trading": {"trades": 0}}
    # 오늘 상위 10 각각: 매수·매도 예정일
    for c in report.get("strategies", {}).get("v3", {}).get("candidates", []):
        c["v3"]["buy_date"] = meta["buy_date"]
        c["v3"]["sell_date"] = meta["sell_date"]
        c["v3"]["entry_day"] = meta["entry_day"]
        c["v3"]["next_entry"] = meta["next_entry"]
    return meta


# ------------------------------------------------------------------ 과거 전 기간 검증 (주간)
def history_entries(pit, cfg: dict, feat: pd.DataFrame, start: str = "2021-07-01", every: int = v3.RULES["every"]) -> list[dict]:
    """과거 선정일마다 (그날 18:00 까지 알 수 있던 정보로) V3B 상위 10 · 후보 전체"""
    from ..data.pit import at, DECISION_TIME
    from ..data.financials import FinIndex
    from .disclosure_rules import DisclosureIndex
    from .filters import stage1
    from .v2 import V2Context, evaluate, market_states
    lst = pit.listing
    sec = getattr(pit, "sectors", pd.DataFrame())
    fin = getattr(pit, "financials", pd.DataFrame())
    fi = FinIndex.from_raw(fin) if fin is not None and len(fin) else None
    di = DisclosureIndex.build(pit.disc) if len(pit.disc) else None
    states = market_states(pit.index)
    market_of = dict(zip(lst["code"], lst["market"])) if not lst.empty else {}
    sector_of = dict(zip(sec["code"], sec["sector"])) if not sec.empty else {}
    dates = feat.index.get_level_values("date").unique().sort_values()
    dates = dates[dates >= pd.Timestamp(start)][::every]
    out = []
    for d in dates:
        x = feat.xs(d, level="date")
        s1, _ = stage1(x, pit.view(at(d, DECISION_TIME)).listing(), cfg)
        if s1.empty:
            continue
        ev = evaluate(s1, V2Context(d, market_of, states, sector_of, fi, di), cfg, detail=False)
        f = fi.at(list(s1.index), d + pd.Timedelta(hours=18)) if fi is not None else pd.DataFrame()
        sc = v3.score(s1, ev["blocked"], f, sector_of)
        t = v3.top(sc, x=s1)
        out.append({"date": d.strftime("%Y-%m-%d"), "picks": list(t.index), "eligible": list(sc.index[sc["eligible"]])})
    return out


def validate(pit, entries: list[dict], forward_log: dict | None = None) -> dict:
    """기간별 ① 종목 선정력 (상위10 / 후보 전체 / 랜덤10 × 5·10·20·40일) ② 실제 매매 (규칙 그대로, 비용 포함)"""
    first = pd.Timestamp(entries[0]["date"]) if entries else pd.Timestamp("2021-07-01")
    O, C = _prices(pit, first)
    fwd = v3_outcome.forward(O, C)
    periods = []
    spans = list(PERIODS)
    if forward_log and forward_log.get("entries"):
        spans.append(("고정 이후 (진짜 OOS)", forward_log["anchor"], None))
    for name, s, e in spans:
        if name.startswith("고정 이후"):
            ent = forward_log["entries"]
        else:
            ent = [x for x in entries if s <= x["date"] <= e]
        if not ent:
            continue
        picks = {pd.Timestamp(x["date"]): x["picks"] for x in ent}
        sim = v3.simulate(picks, O, C, start=s, end=e)
        periods.append({"name": name, "start": s, "end": e or str(C.index.max().date()), "entries": len(ent),
                        "selection": v3_outcome.selection_power(ent, fwd), "trading": v3.metrics(sim),
                        "equity": [{"date": str(d.date()), "equity": round(float(v))} for d, v in sim.equity.iloc[::5].items()]})
    ix = pit.index
    bench = {}
    for name, s, e in spans:
        for code in ("KOSPI", "KOSDAQ"):
            g = ix[ix["code"] == code].set_index("date")["close"].sort_index()
            if len(g):
                a, b = g.asof(pd.Timestamp(s)), g.asof(pd.Timestamp(e) if e else g.index.max())
                bench.setdefault(name, {})[code] = round((b / a - 1) * 100, 1) if a and b else None
    return {"version": v3.VERSION, "locked_at": v3.LOCKED_AT, "rules": v3.RULES_TEXT, "periods": periods, "benchmark": bench,
            "note": "종목 선정력 = 선정일 다음 날 시가 → h거래일째 종가 (거래비용 없음). 실제 매매 = 규칙 그대로 모의 운용 (왕복 약 0.4%)."}
