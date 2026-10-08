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


def build_section(pit, x: pd.DataFrame, ev: pd.DataFrame, name_of: dict, theme_of: dict, as_of) -> dict:
    """오늘 V3B 점수 (1차 필터 통과 종목) → {'list': strategies 항목, 'meta': report['v3']}"""
    s1 = ev[ev["stage1"]].index
    xs = x.loc[x.index.intersection(s1)]
    sec = getattr(pit, "sectors", pd.DataFrame())
    sector_of = dict(zip(sec["code"], sec["sector"])) if not sec.empty else {}
    sc = v3.score(xs, ev["blocked"], _fin_at(pit, xs.index, as_of), sector_of)
    t = v3.top(sc, x=xs)
    cands = []
    for i, (code, r) in enumerate(t.iterrows(), 1):
        c = candidate_dict(code, ev.loc[code], x.loc[code], name_of.get(code, code), i, theme_of.get(code))
        c["v3"] = {"score": round(float(r["v3b"]), 1), "max": 60,
                   "parts": {k: round(float(r[k]), 1) for k in v3.PARTS}, "labels": {k: v for k, (v, _) in v3.PARTS.items()},
                   "maxes": {k: m for k, (_, m) in v3.PARTS.items()}}
        cands.append(c)
    lst = {"name": "V3 기준 전략", "short": "V3 기준", "description": DESC, "count": int(sc["eligible"].sum()),
           "candidates": cands}
    meta = {"version": v3.VERSION, "locked_at": v3.LOCKED_AT, "rules": v3.RULES_TEXT, "eligible": int(sc["eligible"].sum()),
            "top": [{"code": c["code"], "name": c["name"], "score": c["v3"]["score"]} for c in cands]}
    return {"list": lst, "meta": meta, "eligible": list(sc.index[sc["eligible"]])}


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
