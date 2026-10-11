"""관심종목 적중률 (HIT-1.0) — '관심 탭이 고른 종목이 그 뒤 목표가에 닿았나, 손절가에 닿았나'

⚠ 측정 전용: 미래 가격을 일부러 쓴다 (점수·선정 코드에서 쓰지 않음).

  신호     탭마다 매일 점수 상위 3 종목 (V3 도 매일 — history_entries(every=1))
  계획     그날 종가까지의 차트로 계산한 1·2·3차 목표가와 손절가 (앱 종목 상세와 같은 levels)
  매수     다음 거래일 시가 (시초가 상한가면 미체결 → 제외)
  결과     그 뒤 20거래일 동안 매일 고가·저가로 판정. 같은 날 손절가와 목표가가 모두 닿으면 손절 먼저(보수적)
           · 3차 / 2차 / 1차 목표: 손절가에 닿기 전에 닿은 가장 높은 목표
           · 손절: 1차 목표 전에 손절가에 닿음
           · 보합: 20일 동안 1차 목표도 손절도 안 닿음
           승률 = 목표 도달 ÷ (목표 도달 + 손절)  — 보합(20일 동안 아무것도 안 닿음)은 빼고
  평균 손익 1/3씩 나눠 팔았다고 보고 계산: 닿은 목표마다 1/3 을 그 목표가에, 남은 몫은 손절가(시초가가 더 낮으면
           시초가)에, 끝까지 아무것도 안 닿으면 20일째 종가에. 수수료·세금 0.25% 뺌. → '한 번 사면 평균 몇 %'
  일별 분포 목표·손절에 처음 닿은 날(1~20일째) 개수
  묶음     탭 × 연도 × 분기, 분기마다 코스피 등락률과 그때 시장 이슈(market_issues.json, 직접 고칠 수 있음)
  제외     다음 날 시가가 이미 1차 목표가 위(또는 손절가 아래)라 계획대로 살 수 없는 경우
           하루 ±31% 넘는 변화(액면분할·병합 등)가 낀 구간
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

VERSION = "HIT-1.1"
COST = 0.25                                             # 수수료+세금 (%, 왕복)
H = 20
TOP = 3
OUTCOMES = ("t1", "t2", "t3", "stop", "flat")          # 1차 · 2차 · 3차 · 손절 · 보합
LABELS = {"t1": "1차 목표", "t2": "2차 목표", "t3": "3차 목표", "stop": "손절", "flat": "보합"}
TABS = {"v3": "V3", "nextday": "익일유망주", "early": "상승초기", "reversal": "추세전환", "uplimit": "상파"}
MIN_SCORE = {"nextday": 60.0, "early": 60.0, "reversal": 70.0}
JUMP, LIMIT_OPEN = 0.31, 0.295
ISSUES_FILE = Path(__file__).resolve().parents[1] / "data" / "market_issues.json"


def load_issues() -> dict:
    try:
        return json.loads(ISSUES_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


# ------------------------------------------------------------------ 한 신호 판정
def judge(o: np.ndarray, h: np.ndarray, l: np.ndarray, t: tuple, stop: float) -> tuple[str, dict]:
    """o,h,l: 1..H일째 시가·고가·저가. t = (1차, 2차, 3차). → (결과, {목표/손절별 처음 닿은 날})"""
    first = {}
    best = 0
    for k in range(len(h)):
        day = k + 1
        if not (h[k] > 0):
            break
        lo_hit = l[k] <= stop or o[k] <= stop
        # 같은 날 둘 다 닿으면 손절 먼저 (시초가가 목표 위로 뜬 날은 시초가에 목표 먼저)
        gap_up = o[k] >= t[0]
        if lo_hit and not gap_up:
            first.setdefault("stop", day)
            break
        for i, tv in enumerate(t, 1):
            if tv and tv > 0 and h[k] >= tv:
                first.setdefault(f"t{i}", day)
                best = max(best, i)
        if lo_hit:
            first.setdefault("stop", day)
            break
    if best:
        return f"t{best}", first
    return ("stop" if "stop" in first else "flat"), first


def pnl(o: np.ndarray, c: np.ndarray, entry: float, t: tuple, stop: float, first: dict) -> float:
    """1/3씩 분할 매도 손익(%) — 닿은 목표마다 1/3, 남은 몫은 손절 또는 20일째 종가"""
    got = [f"t{i}" in first for i in (1, 2, 3)]
    val = sum(t[i] for i in range(3) if got[i]) / 3
    rest = (3 - sum(got)) / 3
    if rest:
        if "stop" in first:
            k = first["stop"] - 1
            val += rest * (min(o[k], stop) if o[k] > 0 else stop)
        else:
            cc = c[np.isfinite(c) & (c > 0)]
            val += rest * (float(cc[-1]) if len(cc) else entry)
    return (val / entry - 1) * 100 - COST


# ------------------------------------------------------------------ 신호 → 결과
def evaluate(signals: pd.DataFrame, ohlcv: pd.DataFrame, W: dict) -> pd.DataFrame:
    """signals(date, code, tab, score) → 결과 열 추가 (outcome, d_t1, d_t2, d_t3, d_stop)"""
    from ..engine import levels
    O, Hh, L, C = (W[k].to_numpy() for k in ("open", "high", "low", "close"))
    idx, cols = W["close"].index, W["close"].columns
    col_of = {c: i for i, c in enumerate(cols)}
    jump = np.abs(C[1:] / C[:-1] - 1) > JUMP
    jump = np.vstack([np.zeros((1, C.shape[1]), bool), np.nan_to_num(jump, nan=0).astype(bool)])
    need = set(signals["code"])
    by = {}
    for code, g in ohlcv[ohlcv["code"].isin(need)].groupby("code"):
        g = g[g["close"] > 0].sort_values("date")
        by[code] = (g, g["date"].to_numpy())
    out = []
    for d, code in zip(signals["date"], signals["code"]):
        rec = {"outcome": None, "d_t1": None, "d_t2": None, "d_t3": None, "d_stop": None, "skip": None}
        i = idx.get_indexer([pd.Timestamp(d)])[0]
        j = col_of.get(code)
        if i < 0 or j is None or code not in by:
            rec["skip"] = "데이터 없음"; out.append(rec); continue
        if i + H >= len(idx):
            rec["skip"] = "20일 안 지남"; out.append(rec); continue
        if jump[i + 1:i + H + 1, j].any():
            rec["skip"] = "수정주가 이상"; out.append(rec); continue
        o1 = O[i + 1, j]
        if not (o1 > 0) or o1 >= C[i, j] * (1 + LIMIT_OPEN):
            rec["skip"] = "시초가 상한가"; out.append(rec); continue
        g, dts = by[code]
        e = int(np.searchsorted(dts, np.datetime64(pd.Timestamp(d)), side="right"))
        gg = g.iloc[max(0, e - 260):e]
        try:
            o_, h_, l_, c_ = (levels.adjust(gg, col) for col in ("open", "high", "low", "close"))
            lv = levels.compute(gg["date"].to_numpy(), o_, h_, l_, c_, gg["volume"].to_numpy())
        except Exception:  # noqa: BLE001
            lv = None
        if not lv or not lv.get("target1") or not lv.get("stop"):
            rec["skip"] = "목표·손절 계산 불가"; out.append(rec); continue
        t = tuple(float(lv.get(f"target{n}") or 0) for n in (1, 2, 3))
        if t[0] <= o1 or float(lv["stop"]) >= o1:      # 다음 날 시가가 이미 1차 목표 위(또는 손절 아래) → 계획대로 살 수 없음
            rec["skip"] = "시가가 목표 위"; out.append(rec); continue
        res, first = judge(O[i + 1:i + H + 1, j], Hh[i + 1:i + H + 1, j], L[i + 1:i + H + 1, j], t, float(lv["stop"]))
        rec.update({"outcome": res, **{f"d_{k}": v for k, v in first.items()},
                    "pnl": pnl(O[i + 1:i + H + 1, j], C[i + 1:i + H + 1, j], float(o1), t, float(lv["stop"]), first),
                    "entry": float(o1), "t1": t[0], "t2": t[1], "t3": t[2], "stop": float(lv["stop"])})
        out.append(rec)
    return pd.concat([signals.reset_index(drop=True), pd.DataFrame(out)], axis=1)


# ------------------------------------------------------------------ 묶음
def _summary(g: pd.DataFrame) -> dict:
    v = g.dropna(subset=["outcome"])
    n = len(v)
    if not n:
        return {"n": 0}
    cnt = v["outcome"].value_counts()
    pct = {k: round(float(cnt.get(k, 0)) / n * 100, 1) for k in OUTCOMES}
    days = {}
    for k in ("t1", "t2", "t3", "stop"):                              # 처음 닿은 날 분포 (1~20일째 개수)
        dd = v[f"d_{k}"].dropna().astype(int)
        days[k] = [int((dd == x).sum()) for x in range(1, H + 1)]
    hit = pct["t1"] + pct["t2"] + pct["t3"]
    pn = v["pnl"].dropna() if "pnl" in v else pd.Series(dtype=float)
    return {"n": n, **pct, "win": round(hit / (hit + pct["stop"]) * 100, 1) if hit + pct["stop"] else None,
            "pnl": round(float(pn.mean()), 2) if len(pn) else None, "days": days,
            "signal_days": int(v["date"].nunique())}


def _index_q(index: pd.DataFrame) -> dict:
    s = index[index["code"] == "KOSPI"].set_index("date")["close"].sort_index().astype(float) if len(index) else pd.Series(dtype=float)
    if not len(s):
        return {}
    q = s.groupby(s.index.to_period("Q")).agg(["first", "last"])
    prev = s.groupby(s.index.to_period("Q")).last().shift(1)
    r = (q["last"] / prev.fillna(q["first"]) - 1) * 100
    return {str(p): round(float(v), 1) for p, v in r.items()}


def aggregate(res: pd.DataFrame, index: pd.DataFrame | None = None) -> dict:
    """탭 → 연도 → 분기 요약"""
    issues = load_issues()
    kq = _index_q(index) if index is not None else {}
    ky = {}
    if index is not None and len(index):
        k = index[index["code"] == "KOSPI"].set_index("date")["close"].sort_index().astype(float)
        last = k.groupby(k.index.year).last()
        first = k.groupby(k.index.year).first()
        for y in last.index:
            base = last.get(y - 1, first[y])
            ky[str(int(y))] = round(float(last[y] / base - 1) * 100, 1)
    out = {}
    for tab, gt in res.groupby("tab"):
        years = {}
        for y, gy in gt.groupby(gt["date"].dt.year):
            qs = {}
            for q, gq in gy.groupby(gy["date"].dt.quarter):
                key = f"{y}Q{q}"
                qs[f"Q{q}"] = {**_summary(gq), "kospi": kq.get(key), "issue": (issues.get(str(y)) or {}).get(f"Q{q}")}
            years[str(int(y))] = {**_summary(gy), "kospi": ky.get(str(int(y))),
                                  "issue": (issues.get(str(y)) or {}).get("year"), "quarters": qs}
        out[tab] = {"name": TABS.get(tab, tab), "total": _summary(gt), "years": years}
    return out


# ------------------------------------------------------------------ 신호 만들기
def signals_tabs(univ: dict, keys) -> pd.DataFrame:
    from .validation import select
    rows = []
    for k in keys:
        if k == "v3" or k not in univ:
            continue
        p = select(univ[k], MIN_SCORE.get(k), topn=TOP)
        rows.append(pd.DataFrame({"date": p["date"], "code": p["code"], "score": p["score"], "tab": k}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["date", "code", "score", "tab"])


def signals_v3(entries: list[dict]) -> pd.DataFrame:
    rows = []
    for e in entries or []:
        sc = e.get("scores") or {}
        for c in (e.get("picks") or [])[:TOP]:
            rows.append((pd.Timestamp(e["date"]), c, sc.get(c), "v3"))
    return pd.DataFrame(rows, columns=["date", "code", "score", "tab"])


def run(pit, v3_entries: list[dict] | None = None, tabs=tuple(TABS), years=None, start: str = "2021-07-01") -> dict:
    """적중률 계산 → {'version', 'tabs': {tab: {...}}, 'updated'}. tabs·years 로 일부만 (직접 실행용)"""
    import time
    from .validation import universe_tabs, wide
    t0 = time.time()
    oh = pit.ohlcv
    W = wide(oh)
    if "chg_pct" in oh:
        W["chg_pct"] = oh.pivot(index="date", columns="code", values="chg_pct").astype("float32")
    tabs = [t for t in tabs if t in TABS]
    univ = universe_tabs(oh, W, pit.listing, pit.index, start) if any(t != "v3" for t in tabs) else {}
    sig = signals_tabs(univ, tabs)
    if "v3" in tabs and v3_entries:
        sig = pd.concat([sig, signals_v3(v3_entries)], ignore_index=True)
    if years:
        ys = {int(y) for y in years}
        sig = sig[sig["date"].dt.year.isin(ys)]
    log.info("[적중률] 신호 %d건 (%s)", len(sig), ", ".join(tabs))
    res = evaluate(sig, oh, W)
    agg = aggregate(res, pit.index)
    log.info("[적중률] %.1f분", (time.time() - t0) / 60)
    return {"version": VERSION, "tabs": agg, "top": TOP, "horizon": H,
            "updated": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
            "end": str(W["close"].index.max().date()), "partial": {"tabs": tabs, "years": sorted(years) if years else None}}


def merge(old: dict | None, new: dict) -> dict:
    """일부만 다시 돌린 결과를 이전 결과에 덮어쓰기 (탭·연도 단위)"""
    if not old or old.get("version") != new.get("version"):
        return new
    out = {**old, **{k: v for k, v in new.items() if k != "tabs"}}
    tabs = dict(old.get("tabs") or {})
    for t, v in (new.get("tabs") or {}).items():
        if new["partial"].get("years") and t in tabs:
            ys = dict(tabs[t].get("years") or {})
            ys.update(v.get("years") or {})
            tabs[t] = {**tabs[t], "years": ys}
        else:
            tabs[t] = v
    for t, v in tabs.items():                                     # 연도별 결과로 전체 다시 합산
        v["total"] = _combine(list((v.get("years") or {}).values()))
    out["tabs"] = tabs
    return out


def _combine(parts: list[dict]) -> dict:
    parts = [p for p in parts if p.get("n")]
    n = sum(p["n"] for p in parts)
    if not n:
        return {"n": 0}
    pct = {k: round(sum(p["n"] * p.get(k, 0) for p in parts) / n, 1) for k in OUTCOMES}
    days = {k: [sum((p.get("days") or {}).get(k, [0] * H)[i] for p in parts) for i in range(H)]
            for k in ("t1", "t2", "t3", "stop")}
    hit = pct["t1"] + pct["t2"] + pct["t3"]
    pp = [p for p in parts if p.get("pnl") is not None]
    pn = sum(p["n"] for p in pp)
    return {"n": n, **pct, "win": round(hit / (hit + pct["stop"]) * 100, 1) if hit + pct["stop"] else None,
            "pnl": round(sum(p["n"] * p["pnl"] for p in pp) / pn, 2) if pn else None, "days": days,
            "signal_days": sum(p.get("signal_days", 0) for p in parts)}
