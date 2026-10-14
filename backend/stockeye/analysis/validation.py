"""관심종목 검증 (VAL-1.0) — 'StockEye 관심종목 검증 알고리즘' 명세서 기준

⚠ 측정 전용: 미래 가격을 일부러 쓴다. 점수·선정·매매 결정 코드에서 쓰면 안 된다 (backtest/lookahead.py 검사 제외).

무엇을 재나
  신호      전략 × 기준일 T × 종목. 그날 그 전략의 '자격 종목 + 점수' 전체(5분위·IC용)와 앱처럼 고른 상위 10(선정 신호).
            같은 전략·종목이 주 평가 기간(예: 상승초기 10거래일) 안에 다시 선정되면 새 신호로 세지 않고 '반복'으로만 센다.
  기준가격  T일 종가(close0) 와 T+1 시가(open1) 를 둘 다 계산하고, 전략별 주 기준을 정한다 (BASE).
            시가 기준에서 T+1 시가가 상한가(전일 종가 +29.5% 이상)면 '미체결'로 뺀다.
  관찰기간  H = 1·3·5·10·20 거래일 (T+1 ~ T+H). 전략별 주 평가 기간은 MAIN_H.
  지표      종가 수익률 · MFE(기간 최고가) · MAE(기간 최저가) · 최고가 도달일
            · 고점일 되돌림 = (최고가 − 그날 종가) ÷ 최고가 · 종료 시 반납폭 = H일째 종가 ÷ 최고가 − 1
            · +5% 도달률(MFE ≥ 5) · −5% 하락률(MAE ≤ −5)
  목표/손절  선정 신호마다 그날까지의 차트로 계산한 1차 목표가·손절가(levels) → 주 평가 기간 안에 어느 쪽이 먼저 닿았나.
            같은 날 둘 다 닿으면 손절 우선(보수적). 시초가가 건너뛰면 시초가 체결.
  실현 매매  T+1 시가 매수 → 목표/손절 또는 주 평가 기간 마지막 날 종가 매도, 비용 매수 0.15% · 매도 0.25%.
  신뢰도    전략 안 5분위(그날 점수 순위) · Rank IC(그날 점수와 수익률의 순위 상관) · 비교군(상위10 / 자격 전체 / 랜덤10 / 지수)
            · 최소 표본(신호일 30일 · 신호 100건) · 날짜 단위 블록 부트스트랩(상위10 − 자격 전체, 95% 구간)
  데이터    기존 일봉 재사용. 하루 ±31% 넘는 변화(액면분할·병합 등 수정주가 이상)가 낀 구간은 계산에서 뺀다.
  기간      설계 2021.7~2024 · 확인 2025~2026.10.8 · 고정 이후 2026.10.9~
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

VERSION = "VAL-1.0"
HORIZONS = (1, 3, 5, 10, 20)
PERIODS = [("설계", "2021-07-01", "2024-12-31"), ("확인", "2025-01-01", "2026-10-08"), ("고정 이후", "2026-10-09", None)]
STRATS = {  # key: (이름, 주 기준가격, 주 평가 기간, 선정 최소 점수)
    "v3": ("V3", "open1", 20, None),
    "nextday": ("유망주", "open1", 1, 60.0),
    "early": ("상승초기", "close0", 10, 60.0),
    "reversal": ("추세전환", "close0", 10, 70.0),
    "uplimit": ("상파", "open1", 3, None),
}
BUY_COST, SELL_COST = 0.0015, 0.0025
TOPN = 10
MIN_DATES, MIN_SIGNALS = 30, 100
JUMP, LIMIT_OPEN = 0.31, 0.295
BOOT, IC_MIN_N = 1000, 8


# ------------------------------------------------------------------ 가격 → 미래 지표 (넓은 표)
def wide(ohlcv: pd.DataFrame) -> dict[str, pd.DataFrame]:
    W = {}
    for c in ("open", "high", "low", "close", "volume", "value"):
        if c not in ohlcv:
            continue
        w = ohlcv.pivot(index="date", columns="code", values=c).astype("float32")
        W[c] = w.where(w > 0) if c in ("open", "high", "low", "close") else w
    return W


def forward(W: dict[str, pd.DataFrame], horizons=HORIZONS) -> dict:
    """기준일 T 마다 T+1..T+h 의 최고가·최저가·최고가 도달일·그날 종가·h일째 종가 + 계산 가능 여부"""
    O, H, L, C = W["open"], W["high"], W["low"], W["close"]
    jump = (C / C.shift(1) - 1).abs() > JUMP
    hmax = lmin = pk_day = pk_close = None
    bad = jump.shift(-1, fill_value=False).astype(bool)
    out = {"open1": O.shift(-1), "close0": C, "limit_open": (O.shift(-1) >= C * (1 + LIMIT_OPEN))}
    for k in range(1, max(horizons) + 1):
        hk, lk, ck = H.shift(-k), L.shift(-k), C.shift(-k)
        if k > 1:
            bad = bad | jump.shift(-k, fill_value=False).astype(bool)
        if hmax is None:
            hmax, lmin = hk.copy(), lk.copy()
            pk_day = pd.DataFrame(np.where(hk.notna(), 1.0, np.nan), index=hk.index, columns=hk.columns)
            pk_close = ck.copy()
        else:
            up = hk > hmax
            hmax = hmax.where(~up, hk)
            pk_day = pk_day.where(~up, float(k))
            pk_close = pk_close.where(~up, ck)
            lmin = lmin.where(~(lk < lmin), lk)
        if k in horizons:
            out[k] = {"hmax": hmax.copy(), "lmin": lmin.copy(), "pk_day": pk_day.copy(), "pk_close": pk_close.copy(),
                      "close": ck, "ok": (~bad) & ck.notna()}
    return out


def _look(df: pd.DataFrame, dates, codes) -> np.ndarray:
    """넓은 표에서 (날짜, 종목) 쌍의 값"""
    r = df.index.get_indexer(pd.DatetimeIndex(dates))
    c = df.columns.get_indexer(pd.Index(codes))
    v = np.full(len(r), np.nan)
    m = (r >= 0) & (c >= 0)
    v[m] = df.to_numpy()[r[m], c[m]]
    return v


def attach(sig: pd.DataFrame, fw: dict, base: str) -> pd.DataFrame:
    """신호 표(date, code, …)에 기준가격·h일 지표(%)를 붙임"""
    d, c = sig["date"].to_numpy(), sig["code"].to_numpy()
    out = sig.copy()
    p0 = _look(fw["close0"], d, c)
    p1 = _look(fw["open1"], d, c)
    out["p_close0"], out["p_open1"] = p0, p1
    out["gap"] = 100 * (p1 / p0 - 1)
    ref = p1 if base == "open1" else p0
    unfill = (_look(fw["limit_open"].astype(float), d, c) == 1) if base == "open1" else np.zeros(len(d), bool)
    out["unfilled"] = unfill
    for h in HORIZONS:
        f = fw[h]
        ok = (_look(f["ok"].astype(float), d, c) == 1) & ~unfill & (ref > 0)
        hm, lm = _look(f["hmax"], d, c), _look(f["lmin"], d, c)
        pc, cl = _look(f["pk_close"], d, c), _look(f["close"], d, c)
        out[f"r{h}"] = np.where(ok, 100 * (cl / ref - 1), np.nan)
        out[f"mfe{h}"] = np.where(ok, 100 * (hm / ref - 1), np.nan)
        out[f"mae{h}"] = np.where(ok, 100 * (lm / ref - 1), np.nan)
        out[f"pkday{h}"] = np.where(ok, _look(f["pk_day"], d, c), np.nan)
        out[f"pkgb{h}"] = np.where(ok, 100 * (hm - pc) / hm, np.nan)            # 고점일 되돌림
        out[f"endgb{h}"] = np.where(ok, 100 * (cl / hm - 1), np.nan)            # 종료 시 반납폭
    return out


# ------------------------------------------------------------------ 목표/손절 먼저 도달 + 실현 매매
def target_stop(picks: pd.DataFrame, ohlcv: pd.DataFrame, W: dict, h: int) -> pd.DataFrame:
    """선정 신호마다 T일까지 차트로 1차 목표·손절 → T+1 시가 매수 후 h일 안에 먼저 닿은 쪽, 비용 뺀 실현 수익률"""
    from ..engine import levels
    O, H, L, C = W["open"], W["high"], W["low"], W["close"]
    idx = C.index
    rows = []
    by_code = {k: g.sort_values("date") for k, g in ohlcv[ohlcv["code"].isin(picks["code"].unique())].groupby("code")}
    for d, code in zip(picks["date"], picks["code"]):
        g = by_code.get(code)
        if g is None or code not in C.columns:
            rows.append((np.nan, np.nan, None, np.nan)); continue
        g = g[g["date"] <= d].tail(260)
        g = g[g["close"] > 0]
        try:
            lv = levels.compute(*levels.prepare(g))
        except Exception:  # noqa: BLE001
            lv = None
        i = idx.get_indexer([pd.Timestamp(d)])[0]
        if not lv or i < 0 or i + h >= len(idx):
            rows.append((np.nan, np.nan, None, np.nan)); continue
        t1, st = float(lv.get("target1") or np.nan), float(lv.get("stop") or np.nan)
        j = C.columns.get_loc(code)
        o = O.iat[i + 1, j]
        c0 = C.iat[i, j]
        if not (o > 0) or not (t1 > 0) or not (st > 0) or o >= c0 * (1 + LIMIT_OPEN):
            rows.append((t1, st, None, np.nan)); continue
        res, px = "기간 종료", np.nan
        for k in range(1, h + 1):
            hk, lk, ok_, ck = H.iat[i + k, j], L.iat[i + k, j], O.iat[i + k, j], C.iat[i + k, j]
            if not (ck > 0):
                break
            if ok_ <= st:
                res, px = "손절", ok_; break                  # 시초가가 손절가를 건너뜀
            if ok_ >= t1 and k > 1:
                res, px = "목표", ok_; break
            if lk <= st:
                res, px = "손절", st; break                   # 같은 날 둘 다 닿으면 손절 우선
            if hk >= t1:
                res, px = "목표", t1; break
            px = ck
        net = 100 * (px * (1 - SELL_COST) / (o * (1 + BUY_COST)) - 1) if px == px and px > 0 else np.nan
        rows.append((t1, st, res, net))
    out = picks.copy()
    out["t1"], out["stop"], out["first"], out["net"] = zip(*rows) if rows else ([], [], [], [])
    return out


# ------------------------------------------------------------------ 통계
def _stats(df: pd.DataFrame, h: int) -> dict | None:
    r = df[f"r{h}"].dropna()
    if not len(r):
        return None
    g = df.loc[r.index]
    q = lambda k: round(float(g[k].mean()), 2)  # noqa: E731
    return {"n": int(len(r)), "mean": round(float(r.mean()), 2), "median": round(float(r.median()), 2),
            "win": round(float((r > 0).mean() * 100), 1), "mfe": q(f"mfe{h}"), "mae": q(f"mae{h}"),
            "up5": round(float((g[f"mfe{h}"] >= 5).mean() * 100), 1), "dn5": round(float((g[f"mae{h}"] <= -5).mean() * 100), 1),
            "pkday": q(f"pkday{h}"), "pk_giveback": q(f"pkgb{h}"), "end_giveback": q(f"endgb{h}")}


def quintiles(univ: pd.DataFrame, h: int) -> list[dict]:
    u = univ.dropna(subset=[f"r{h}", "score"]).copy()
    if not len(u):
        return []
    u["q"] = u.groupby("date")["score"].rank(pct=True, method="first").mul(5).clip(upper=4.9999).astype(int) + 1
    return [{"q": int(q), **(_stats(g, h) or {})} for q, g in sorted(u.groupby("q"))]


def rank_ic(univ: pd.DataFrame, h: int) -> dict | None:
    u = univ.dropna(subset=[f"r{h}", "score"])
    n = u.groupby("date")["code"].transform("size")
    u = u[n >= IC_MIN_N]
    if not len(u):
        return None
    a = u.groupby("date")["score"].rank()
    b = u.groupby("date")[f"r{h}"].rank()
    t = pd.DataFrame({"date": u["date"], "a": a, "b": b})
    ic = t.groupby("date").apply(lambda g: g["a"].corr(g["b"]), include_groups=False).dropna()
    if len(ic) < 2:
        return None
    m, s = float(ic.mean()), float(ic.std())
    return {"mean": round(m, 3), "t": round(float(m / s * np.sqrt(len(ic))), 2) if s > 0 else None,
            "pos": round(float((ic > 0).mean() * 100), 1), "days": int(len(ic))}


def bootstrap(diff: pd.Series, block: int, n: int = BOOT, seed: int = 7) -> dict | None:
    """날짜별 (상위10 − 자격 전체) 평균 차이 → 블록 부트스트랩 평균의 95% 구간"""
    x = diff.dropna().to_numpy()
    if len(x) < MIN_DATES:
        return None
    rng = np.random.default_rng(seed)
    b = max(1, min(block, len(x) // 4))
    k = int(np.ceil(len(x) / b))
    st = rng.integers(0, len(x) - b + 1, size=(n, k))
    means = np.array([np.concatenate([x[s:s + b] for s in row])[:len(x)].mean() for row in st])
    return {"mean": round(float(x.mean()), 2), "lo": round(float(np.percentile(means, 2.5)), 2),
            "hi": round(float(np.percentile(means, 97.5)), 2), "days": int(len(x)), "block": b}


def select(univ: pd.DataFrame, min_score: float | None, topn: int = TOPN) -> pd.DataFrame:
    """앱처럼 날짜마다 자격 종목 중 (최소 점수 이상) 점수 상위 topn"""
    u = univ[univ["eligible"]]
    if min_score is not None:
        u = u[u["score"] >= min_score]
    u = u.sort_values(["date", "score", "value", "code"], ascending=[True, False, False, True])
    return u.groupby("date").head(topn)


def dedupe(picks: pd.DataFrame, trade_dates, days: int) -> pd.DataFrame:
    """같은 종목이 days 거래일 안에 다시 선정되면 repeat=True (새 신호 아님). days = 주 평가 기간"""
    pos = {d: i for i, d in enumerate(pd.DatetimeIndex(trade_dates))}
    p = picks.sort_values(["code", "date"]).copy()
    rep, last = [], {}
    for code, d in zip(p["code"], p["date"]):
        i = pos.get(pd.Timestamp(d))
        j = last.get(code)
        r = i is not None and j is not None and i - j < max(days, 1)   # 마지막 '새 신호'의 평가 기간 안
        rep.append(r)
        if not r:
            last[code] = i
    p["repeat"] = rep
    return p.sort_values(["date", "code"])


def evaluate(key: str, univ: pd.DataFrame, picks: pd.DataFrame, idx_ret: dict[int, pd.Series] | None = None) -> dict:
    """전략 하나: 기간별 비교군·5분위·IC·부트스트랩·목표/손절·실현 매매 → 판정"""
    name, base, mh, _ = STRATS[key]
    periods = []
    for pname, a, b in PERIODS:
        m = lambda df: df[(df["date"] >= a) & ((df["date"] <= b) if b else True)]  # noqa: E731
        U, P = m(univ), m(picks)
        if not len(U):
            continue
        Pn = P[~P["repeat"]]
        el = U[U["eligible"]]
        groups = {"top": Pn, "all": el}
        rnd = []
        rng = np.random.default_rng(11)
        for d, g in el.groupby("date"):
            if len(g) >= TOPN:
                rnd.append(g.iloc[rng.choice(len(g), TOPN, replace=False)])
        if rnd:
            groups["random"] = pd.concat(rnd)
        sel = {}
        for h in HORIZONS:
            sel[str(h)] = {k: _stats(v, h) for k, v in groups.items()}
            if idx_ret and h in idx_ret:
                ir = idx_ret[h].reindex(pd.DatetimeIndex(P["date"].unique())).dropna()
                sel[str(h)]["market"] = {"n": int(len(ir)), "mean": round(float(ir.mean()), 2)} if len(ir) else None
        dd = (Pn.groupby("date")[f"r{mh}"].mean() - el.groupby("date")[f"r{mh}"].mean()).dropna()
        tr = Pn.dropna(subset=["net"]) if "net" in Pn else Pn.iloc[0:0]      # 반복 선정은 매매 1번으로
        trade = None
        if len(tr):
            w, l_ = tr.loc[tr["net"] > 0, "net"].sum(), -tr.loc[tr["net"] <= 0, "net"].sum()
            fc = tr["first"].value_counts(normalize=True) * 100
            trade = {"n": int(len(tr)), "mean": round(float(tr["net"].mean()), 2), "median": round(float(tr["net"].median()), 2),
                     "win": round(float((tr["net"] > 0).mean() * 100), 1), "pf": round(float(w / l_), 2) if l_ > 0 else None,
                     "target_first": round(float(fc.get("목표", 0)), 1), "stop_first": round(float(fc.get("손절", 0)), 1),
                     "neither": round(float(fc.get("기간 종료", 0)), 1)}
        nd_, ns = int(Pn["date"].nunique()), int(len(Pn))
        periods.append({
            "name": pname, "start": a, "end": b or (str(U["date"].max().date()) if len(U) else None),
            "dates": nd_, "signals": ns, "repeats": int(P["repeat"].sum()), "unfilled": int(P["unfilled"].sum()),
            "sufficient": nd_ >= MIN_DATES and ns >= MIN_SIGNALS,
            "selection": sel, "quintiles": quintiles(el, mh), "ic": rank_ic(el, mh), "boot": bootstrap(dd, mh),
            "trade": trade})
    return {"key": key, "name": name, "base": base, "main_h": mh, "periods": periods, "verdict": verdict(periods, mh)}


def verdict(periods: list[dict], mh: int) -> dict:
    """명세서 13절 판정 (기준 고정: VAL-1.0). 설계·확인 두 기간으로 판정
      매매 전략 후보  두 기간 모두 [상위10 평균·중앙 > 자격 전체, Q5 중앙 > Q1 중앙, IC > 0] + 확인 기간 부트스트랩 하한 > 0
                      + 두 기간 비용 뺀 실현 매매 평균 > 0 · PF ≥ 1.2
      선별력 가능성  위 선별력 조건만 충족
      보류/수정      확인 기간 상위10 평균·중앙 모두 자격 전체 이하, 또는 두 기간 모두 IC ≤ 0
      추가 검증      그 밖 (일부만 충족)
      표본 부족      설계·확인 중 신호일 30일·신호 100건 미만"""
    P = {p["name"]: p for p in periods}
    use = [P[k] for k in ("설계", "확인") if k in P]
    why = []
    if len(use) < 2 or not all(p["sufficient"] for p in use):
        return {"label": "표본 부족", "why": ["설계·확인 기간 모두 신호일 30일·신호 100건 이상이어야 판정"]}
    h = str(mh)

    def ok_sel(p):
        s = p["selection"][h]
        q = p["quintiles"]
        top, al = s.get("top") or {}, s.get("all") or {}
        c1 = (top.get("median", -99) > al.get("median", 99)) and (top.get("mean", -99) > al.get("mean", 99))
        c2 = len(q) == 5 and q[-1].get("median", -99) > q[0].get("median", 99)
        c3 = (p["ic"] or {}).get("mean", -1) > 0
        return c1, c2, c3

    res = [ok_sel(p) for p in use]
    conf = use[-1]
    boot_ok = (conf["boot"] or {}).get("lo", -1) > 0
    top_c = conf["selection"][h].get("top") or {}
    all_c = conf["selection"][h].get("all") or {}
    if all(all(r) for r in res) and boot_ok:
        tr = [p["trade"] or {} for p in use]
        if all((t.get("mean") or -1) > 0 and (t.get("pf") or 0) >= 1.2 for t in tr):
            return {"label": "매매 전략 후보", "why": ["두 기간 모두 선별력(상위10 > 자격 전체, 5분위 Q5 > Q1, IC > 0) 확인",
                                                 "확인 기간 부트스트랩 하한 > 0", "비용 뺀 실현 매매 평균 > 0 · PF ≥ 1.2"]}
        return {"label": "선별력 가능성", "why": ["두 기간 모두 선별력 확인 · 확인 기간 부트스트랩 하한 > 0",
                                           "다만 비용 뺀 실현 매매는 기준(평균 > 0, PF ≥ 1.2) 미달"]}
    worse = top_c.get("mean", 0) <= all_c.get("mean", 0) and top_c.get("median", 0) <= all_c.get("median", 0)
    if worse or all(not r[2] for r in res):
        if top_c.get("mfe", 0) > all_c.get("mfe", 0) and worse:
            why.append("장중 고점(MFE)은 높지만 종가 성과가 자격 전체보다 낮음")
        if all(not r[2] for r in res):
            why.append("두 기간 모두 점수와 수익률의 순위 상관(IC) ≤ 0")
        if worse:
            why.append("확인 기간 상위10 평균·중앙값 모두 자격 전체 이하")
        return {"label": "보류/수정", "why": why}
    for nm, r in zip(("설계", "확인"), res):
        miss = [t for t, ok in zip(("상위10 > 자격 전체", "Q5 > Q1", "IC > 0"), r) if not ok]
        if miss:
            why.append(f"{nm}: " + ", ".join(miss) + " 미충족")
    if not boot_ok:
        why.append("확인 기간 부트스트랩 95% 구간이 0을 포함")
    return {"label": "추가 검증", "why": why}


# ------------------------------------------------------------------ 전략별 과거 신호 (자격 종목 + 점수)
def _stack(frames: dict[str, pd.DataFrame], start) -> pd.DataFrame:
    df = pd.concat({k: v[v.index >= pd.Timestamp(start)].stack() for k, v in frames.items()}, axis=1)
    df.index.names = ["date", "code"]
    return df.reset_index()


def universe_tabs(ohlcv: pd.DataFrame, W: dict, listing: pd.DataFrame, index: pd.DataFrame, start: str) -> dict:
    """유망주·상승초기·추세전환·상파: 날짜마다 자격 종목과 점수 (보통주 · 20일 평균 거래대금 10억↑ · 120거래일↑)
    ※ 저녁 배치의 V2 매수 차단(공시 위험 등)은 과거 전 기간으로 다시 계산하지 않아 근사 — 공시 점수는 중립 7."""
    from ..engine import early as up, nextday as nd, reversal as rv, uplimit as ul
    O, H, L, C, V = (W[k] for k in ("open", "high", "low", "close", "volume"))
    VAL = W.get("value")
    if VAL is None:
        VAL = (C * V).astype("float32")
    nm = dict(zip(listing["code"], listing["name"])) if len(listing) else {}
    mk = dict(zip(listing["code"], listing["market"])) if len(listing) and "market" in listing else {}
    common = pd.Series({c: nd.common_stock(c, nm.get(c, "")) for c in C.columns})
    adm = set(listing.loc[listing["is_admin"].astype(bool), "code"]) if "is_admin" in listing else set()
    common[common.index.isin(adm)] = False
    val20 = (VAL.rolling(20, min_periods=10).mean() / 1e8)
    base = (C.notna().cumsum() >= 120) & (val20 >= 10) & pd.DataFrame(
        np.broadcast_to(common.reindex(C.columns).fillna(False).to_numpy(), C.shape), index=C.index, columns=C.columns)
    out = {}
    # 추세전환
    f = rv.raw_features(O, H, L, C, V)
    t = rv.totals(rv.score_frame(f))
    out["reversal"] = _stack({"score": t["total"], "eligible": base.astype(float), "value": val20}, start)
    del f, t
    # 상승초기
    f = up.raw_features(O, H, L, C, V, VAL)
    t = up.totals(up.score_frame(f))
    ex = None
    for v in up.exclusions(f).values():
        ex = v if ex is None else (ex | v)
    out["early"] = _stack({"score": t["total"], "eligible": (base & ~ex).astype(float), "value": val20}, start)
    del f, t, ex
    # 유망주 (공시 점수 중립 7)
    f = nd.raw_features(O, H, L, C, V, VAL, nd.index_returns(index), mk)
    news = pd.DataFrame(7.0, index=C.index, columns=C.columns)
    t = nd.totals(nd.score_frame(f, news, True))
    out["nextday"] = _stack({"score": t["total"], "eligible": base.astype(float), "value": val20}, start)
    del f, t, news
    # 상파 (상한가 도달 A / 상한가 다음 날 거래량 감소 음봉 B, 20일 평균 거래대금 5억↑)
    CHG = W.get("chg_pct")
    f = ul.features(O, H, L, C, V, VAL, CHG)
    cand = (f["REACH"] | f["TYPE_B"]) & (f["VAL20"] >= ul_min()) & pd.DataFrame(
        np.broadcast_to(common.reindex(C.columns).fillna(False).to_numpy(), C.shape), index=C.index, columns=C.columns)
    keys = [k for k in f if isinstance(f[k], pd.DataFrame)]
    S = _stack({k: f[k].where(cand) for k in keys}, start).dropna(subset=["REACH"])
    S = S[S["REACH"].astype(bool) | S["TYPE_B"].astype(bool)]
    sc = [ul.score_row(r, None, False)["total"] for r in S.to_dict("records")]
    out["uplimit"] = pd.DataFrame({"date": S["date"], "code": S["code"], "score": sc, "eligible": 1.0,
                                   "value": S["VAL20"]})
    for k in out:
        u = out[k]
        u["eligible"] = u["eligible"].fillna(0).astype(bool)
        out[k] = u.dropna(subset=["score"])
    return out


def ul_min() -> float:
    from ..engine.uplimit_report import MIN_VALUE
    return MIN_VALUE


def universe_v3(entries: list[dict], val20: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """V3: history_entries(5거래일마다, 그날 V2 차단·과열·추세 필터 반영) → 자격 종목·점수 + 실제 상위 10"""
    rows, picks = [], []
    for e in entries:
        d = pd.Timestamp(e["date"])
        sc = e.get("scores") or {}
        for c in e.get("eligible", []):
            rows.append((d, c, sc.get(c, np.nan)))
        for c in e.get("picks", []):
            picks.append((d, c, sc.get(c, np.nan)))
    U = pd.DataFrame(rows, columns=["date", "code", "score"])
    U["eligible"], U["value"] = True, 0.0
    P = pd.DataFrame(picks, columns=["date", "code", "score"])
    P["eligible"], P["value"] = True, 0.0
    return U, P


def index_forward(index: pd.DataFrame, code: str = "KOSPI") -> dict[int, pd.Series]:
    s = index[index["code"] == code].set_index("date")["close"].sort_index().astype(float)
    return {h: 100 * (s.shift(-h) / s - 1) for h in HORIZONS}


def run(pit, ohlcv: pd.DataFrame | None = None, v3_entries: list[dict] | None = None, start: str = "2021-07-01",
        keys=tuple(STRATS)) -> dict:
    """전체 검증 → 앱 '검증' 화면 payload"""
    import time
    t0 = time.time()
    oh = pit.ohlcv if ohlcv is None else ohlcv
    W = wide(oh)
    if "chg_pct" in oh:
        W["chg_pct"] = oh.pivot(index="date", columns="code", values="chg_pct").astype("float32")
    fw = forward(W)
    idx = pit.index if hasattr(pit, "index") else pd.DataFrame()
    lst = pit.listing if hasattr(pit, "listing") else pd.DataFrame()
    univ = universe_tabs(oh, W, lst, idx, start) if any(k != "v3" for k in keys) else {}
    if "v3" in keys and v3_entries:
        univ["v3"] = universe_v3(v3_entries)
    ir = index_forward(idx) if len(idx) else None
    out = []
    for k in keys:
        if k not in univ:
            continue
        name, base, mh, mins = STRATS[k]
        if k == "v3":
            U, P = univ["v3"]
        else:
            U = univ[k]
            P = select(U, mins)
        U = attach(U, fw, base)
        P = dedupe(attach(P, fw, base), W["close"].index, mh)
        P = target_stop(P, oh, W, mh)
        r = evaluate(k, U, P, ir)
        out.append(r)
        log.info("[검증] %s: %s (%.0f초)", name, r["verdict"]["label"], time.time() - t0)
    return {"version": VERSION, "horizons": list(HORIZONS), "periods": [p[0] for p in PERIODS],
            "settings": {"cost": {"buy": BUY_COST * 100, "sell": SELL_COST * 100}, "top_n": TOPN, "dedupe": "주 평가 기간",
                         "min_dates": MIN_DATES, "min_signals": MIN_SIGNALS, "jump_pct": JUMP * 100,
                         "limit_open_pct": LIMIT_OPEN * 100, "boot": BOOT},
            "strategies": out, "start": start, "end": str(W["close"].index.max().date()),
            "minutes": round((time.time() - t0) / 60, 1)}
