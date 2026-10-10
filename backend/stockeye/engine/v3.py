"""StockEye V3 기준 전략 (Base Strategy) — 🔒 고정 (V3B-2.0, 2026-10-10)

  무엇을 살 것인가   V3B 점수 100 = 변동성 15 + 재무 25 + 가격위치 20
                                 + 추세 5 + 거래량 5 + 거래대금 5 + 수급 10 + 공시 15
                     (V3B-1.0 은 앞 3항목 60점만 썼음. 2026-10-10 사용자 요청으로 뒤 5항목을 다시 점수에 넣음 —
                      추세가 꺾인 종목이 재무·변동성만으로 1위가 되는 것을 막기 위함)
                     자격: V2 매수 차단 없음 · 과열 아님 · 추세 필터(60일선 위 또는 60일선 10일 -2% 이내) · 1차 필터 통과
  언제 살 것인가     5거래일마다 상위 10개 → 다음 거래일 시가
  얼마나 살 것인가   최대 20종목 · 종목당 5% · 시장 비중 고정 100%
  언제 팔 것인가     매수일 포함 20거래일째 종가 (손절·익절 없음)
                     보유 중인 종목이 다시 상위 10에 들면 그날부터 20거래일 연장, 추가매수 없음

⚠ 이 파일의 점수·조건·규칙은 검증 기간 동안 바꾸지 않는다 (바꾸면 VERSION 을 올리고 그때부터 다시 기록).
   근거: 프로젝트 문서 v3-research / v3-exit / v3-market-weight / v3-regime (2026-10-08).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

VERSION = "V3B-2.0"
LOCKED_AT = "2026-10-10"          # V3B-1.0: 2026-10-08 ~ 2026-10-10 (60점, 3항목)
RULES = {"top_n": 10, "every": 5, "hold": 20, "max_positions": 20, "weight": 0.05, "market_weight": 1.0,
         "on_reselect": "extend", "add_buy": False, "buy_cost": 0.0015, "sell_cost": 0.0025}
RULES_TEXT = ["5거래일마다 V3B 상위 10개 선정 → 다음 거래일 시가 매수",
              "최대 20종목 · 종목당 5% · 시장 비중 고정",
              "매수일 포함 20거래일째 종가에 매도 (손절·익절 없음)",
              "보유 중 다시 상위 10에 들면 20거래일 연장, 추가매수 없음"]
PARTS = {"vola15": ("변동성", 15), "fin25": ("재무", 25), "pos20": ("가격위치", 20),
         "trend5": ("추세", 5), "vol5": ("거래량", 5), "value5": ("거래대금", 5), "flow10": ("수급", 10),
         "news15": ("공시", 15)}
MAX_SCORE = sum(m for _, m in PARTS.values())          # 100

# 앞으로의 휴장일 (주말 외) — 매도 예정일 계산용. 실제 휴장일과 다를 수 있어 앱에는 '예정'으로 표시
KRX_HOLIDAYS = {
    "2026-10-09", "2026-12-25", "2026-12-31",
    "2027-01-01", "2027-02-08", "2027-02-09", "2027-03-01", "2027-05-05", "2027-05-13", "2027-08-16",
    "2027-09-14", "2027-09-15", "2027-09-16", "2027-10-04", "2027-10-11", "2027-12-27", "2027-12-31",
}


def _b(s) -> pd.Series:
    return pd.Series(s).fillna(False).astype(bool).astype(float)


def _num(s) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


# ------------------------------------------------------------------ 점수 (고정)
def score(x: pd.DataFrame, blocked: pd.Series, fin: pd.DataFrame, sector_of: dict,
          ev: pd.DataFrame | None = None) -> pd.DataFrame:
    """그날 단면 x (1차 필터 통과 종목, 피처) + V2 매수 차단 여부 + 그날 알 수 있던 재무 지표
    + V2 평가 ev(거래대금 value 0~5 · 수급 flow 0~15 · 공시 news 0~15) → V3B 점수·항목·자격.
    ev 가 없거나 값이 비면 그 항목은 중간값(만점의 절반)"""
    idx = x.index
    f = fin.reindex(idx) if fin is not None and len(fin) else pd.DataFrame(index=idx)
    g = lambda c: f[c] if c in f else pd.Series(np.nan, index=idx)  # noqa: E731
    c = x["close"]
    o = pd.DataFrame(index=idx)
    # 가격위치 20: '얼마나 올랐나'가 아니라 '얼마나 좋은 가격에서 사나'
    near = (x["dist_sma20"].abs() <= 0.03) | ((c / x["sma60"] - 1).abs() <= 0.03)
    support = c <= x["low20"] * 1.05
    pull = (c / x["high20_prev"] - 1).between(-0.15, -0.04)
    pos = (6 * _b(near) + 3 * _b(support) + 4 * _b(pull) + 3 * _b(x["ret5"].between(-0.08, 0.03))
           + 2 * _b(x["dist_sma20"] < 0.08) + 2 * _b(x["up_day"].astype(bool) & ((x["touch_sma20_3d"] > 0) | support)))
    hot = (x["ret5"] > 0.10) | (x["ret20"] > 0.20)
    o["pos20"] = np.where(hot, np.minimum(pos, 5), pos).clip(0, 20)
    # 변동성 15 (ATR% 낮을수록)
    a = x["atr_pct"]
    o["vola15"] = np.select([a <= 0.02, a <= 0.03, a <= 0.04, a <= 0.05, a <= 0.07], [15, 12, 9, 6, 3], default=0)
    # 재무 25 = 수익성 8 + 성장성 7 + 건전성 6 + 밸류 4 (재무 없음 = 10)
    roe, opm = _num(g("roe")), _num(g("op_margin"))
    prof = 3 * _b(g("op_pos") == True) + 2 * _b(roe > 0.08) + _b(roe > 0.15) + 2 * _b(opm > 0.05)  # noqa: E712
    eps_yoy = x["eps_yoy"] if "eps_yoy" in x else pd.Series(np.nan, index=idx)
    grow = (2 * _b(_num(g("rev_yoy")) > 0.05) + 2 * _b(_num(g("op_yoy")) > 0.10) + _b(_num(g("ni_yoy")) > 0.10)
            + _b(g("op_improve") == True) + _b(eps_yoy > 0))  # noqa: E712
    dr = _num(g("debt_ratio"))
    health = (np.where(dr < 1, 3, np.where(dr < 2, 1.5, 0)) + 1.5 * _b(_num(g("current_ratio")) > 1)
              + 1.5 * _b(g("impaired") != True))  # noqa: E712
    per = x["per"] if "per" in x else pd.Series(np.nan, index=idx)
    pbr = x["pbr"] if "pbr" in x else pd.Series(np.nan, index=idx)
    sec = pd.Series([sector_of.get(k) for k in idx], index=idx)
    med = per.where(per > 0).groupby(sec).transform("median")
    val = (1.5 * _b((per > 0) & (per < 40)) + 1.5 * _b((pbr >= 0.3) & (pbr <= 3))
           + _b((per > 0) & (per < med) & (_num(g("op_yoy")) > 0)))
    o["fin25"] = np.where(g("op_pos").notna(), prof + grow + health + val, 10.0)
    # 추세 5 = 60일선 위 2 + 60일선 상승 2 + 20일선 > 60일선 1
    o["trend5"] = (2 * _b(c > x["sma60"]) + 2 * _b(x["sma60_slope"] > 0) + _b(x["sma20"] > x["sma60"]))
    # 거래량 5 = 최근 5일 거래량 / 그 전 20일: 조정 중 적당히 줄거나 늘면 5, 급증(2배↑) 0, 1.3~2배·0.6배 미만 3
    v5 = x["vol5_ratio"] if "vol5_ratio" in x else pd.Series(np.nan, index=idx)
    o["vol5"] = np.select([v5.isna(), v5 > 2, v5 > 1.3, v5 < 0.6], [2.5, 0, 3, 3], default=5)
    e = ev.reindex(idx) if ev is not None else pd.DataFrame(index=idx)
    for k, src, mul, mx in (("value5", "value", 1.0, 5), ("flow10", "flow", 10 / 15, 10), ("news15", "news", 1.0, 15)):
        v = _num(e[src]) * mul if src in e else pd.Series(np.nan, index=idx)
        o[k] = v.fillna(mx / 2).clip(0, mx)
    o["v3b"] = o[list(PARTS)].sum(axis=1)
    # 자격
    o["hot"] = ((x["ret5"] >= 0.20) | (x["ret20"] >= 0.30) | (x["rsi14"] > 75)
                | ((x["vol_ratio"] >= 3) & (x["ret5"] >= 0.10))).fillna(False)
    o["trend_ok"] = ((c > x["sma60"]) | (x["sma60_slope"] > -0.02)).fillna(False)
    o["blocked"] = blocked.reindex(idx).fillna(True).astype(bool)
    o["eligible"] = ~o["blocked"] & ~o["hot"] & o["trend_ok"]
    return o


def top(o: pd.DataFrame, n: int = RULES["top_n"], x: pd.DataFrame | None = None) -> pd.DataFrame:
    """동점 정렬 고정: V3B ↓ → 재무 ↓ → 변동성(ATR%) ↑ → 거래대금 ↓ → 종목코드"""
    e = o[o["eligible"]].copy()
    e["_atr"] = x["atr_pct"].reindex(e.index) if x is not None else 0.0
    e["_val"] = x["value_ma20"].reindex(e.index) if x is not None else 0.0
    e["_code"] = e.index
    e = e.sort_values(["v3b", "fin25", "_atr", "_val", "_code"], ascending=[False, False, True, False, True])
    return e.drop(columns=["_atr", "_val", "_code"]).head(n)


# ------------------------------------------------------------------ 달력
def future_days(last: pd.Timestamp, n: int) -> list[pd.Timestamp]:
    """last 다음 거래일부터 n일 (주말·알려진 휴장일 제외 — 예정)"""
    out, d = [], pd.Timestamp(last).normalize()
    while len(out) < n:
        d += pd.Timedelta(days=1)
        if d.weekday() < 5 and d.strftime("%Y-%m-%d") not in KRX_HOLIDAYS:
            out.append(d)
    return out


def calendar(trading_dates, ahead: int = 60, back: int = 80) -> list[str]:
    """지난 거래일 back 개 + 앞으로 예정 거래일 ahead 개 (앱이 매도 예정일 계산에 씀)"""
    past = list(pd.DatetimeIndex(trading_dates).sort_values()[-back:])
    return [d.strftime("%Y-%m-%d") for d in past + future_days(past[-1], ahead)]


def nth_day(cal: list[str], start: str, n: int) -> str | None:
    """start 거래일을 1일째로 셀 때 n일째 날짜"""
    k = next((i for i, d in enumerate(cal) if d >= start), None)
    return cal[k + n - 1] if k is not None and k + n - 1 < len(cal) else None


def is_entry_day(trading_dates, anchor: str, d) -> bool:
    td = pd.DatetimeIndex(trading_dates).sort_values()
    k = int(((td >= pd.Timestamp(anchor)) & (td <= pd.Timestamp(d))).sum())
    return k >= 1 and (k - 1) % RULES["every"] == 0


def next_entry_day(trading_dates, anchor: str, d) -> str:
    td = pd.DatetimeIndex(trading_dates).sort_values()
    k = int(((td >= pd.Timestamp(anchor)) & (td <= pd.Timestamp(d))).sum())
    left = (RULES["every"] - (k - 1) % RULES["every"]) % RULES["every"] or RULES["every"]
    return future_days(pd.Timestamp(d), left)[-1].strftime("%Y-%m-%d")


# ------------------------------------------------------------------ 모의 운용 (규칙 그대로)
@dataclass
class SimResult:
    trades: list = field(default_factory=list)      # {code, entry, exit, ret, days, extended}
    equity: pd.Series | None = None
    holdings: list = field(default_factory=list)    # 지금 보유 {code, entry, days, extends, entry_px, last, ret}
    invested: float = 0.0
    turnover: float = 0.0


def simulate(picks: dict, opens: pd.DataFrame, closes: pd.DataFrame, start=None, end=None,
             capital: float = 1e8, rules: dict = RULES) -> SimResult:
    """picks: {선정일: [code, ...] (순위순)} → 다음 거래일 시가 매수. opens/closes: 날짜 × 종목 (가격 0·결측 = 거래 없음)"""
    dates = closes.index
    if start is not None:
        dates = dates[dates >= pd.Timestamp(start)]
    if end is not None:
        dates = dates[dates <= pd.Timestamp(end)]
    col = {c: i for i, c in enumerate(closes.columns)}
    O, C = opens.reindex(index=closes.index, columns=closes.columns).values, closes.values
    gi = {d: i for i, d in enumerate(closes.index)}
    bc, sc = rules["buy_cost"], rules["sell_cost"]
    cash, pos, res, eq, inv, buys = capital, {}, SimResult(), [], [], 0.0
    pend: list = []
    for d in dates:
        i = gi[d]
        if pend and i > 0:
            equity = cash + sum(p["sh"] * p["last"] for p in pos.values())
            for code in pend:
                j = col.get(code)
                if j is None:
                    continue
                if code in pos:                                   # 다시 선정 → 기간 연장 (추가매수 없음)
                    pos[code]["days"] = 0; pos[code]["extends"] += 1
                    continue
                if len(pos) >= rules["max_positions"]:
                    continue
                op, pc = O[i, j], C[i - 1, j]
                if not (op > 0) or not (pc > 0) or op >= pc * 1.29:     # 거래 없음 / 상한가 근처 갭
                    continue
                amt = min(rules["weight"] * rules["market_weight"] * equity, cash)
                sh = int(amt / (op * (1 + bc)))
                if sh <= 0:
                    continue
                cost = sh * op * (1 + bc); cash -= cost; buys += cost
                pos[code] = {"sh": sh, "cost": cost, "days": 0, "extends": 0, "last": op, "px": op, "entry": d}
            pend = []
        for code in list(pos):
            p, j = pos[code], col[code]
            cl, pc = C[i, j], (C[i - 1, j] if i > 0 else np.nan)
            if not (cl > 0):
                continue                                          # 거래정지: 그대로 보유
            if p["days"] > 0 and pc > 0 and abs(cl / pc - 1) > 0.31:    # 액면분할 등 가격 불연속 → 전날 종가로 정리
                cl, why = pc, "가격 불연속"
            else:
                why = None
            p["days"] += 1; p["last"] = cl
            if why or p["days"] >= rules["hold"]:
                v = p["sh"] * cl * (1 - sc); cash += v
                res.trades.append({"code": code, "entry": p["entry"].strftime("%Y-%m-%d"), "exit": d.strftime("%Y-%m-%d"),
                                   "ret": v / p["cost"] - 1, "pnl": v - p["cost"], "extends": p["extends"],
                                   "why": why or ("20일 보유" if not p["extends"] else f"20일 보유 (연장 {p['extends']}회)")})
                del pos[code]
        val = sum(p["sh"] * p["last"] for p in pos.values())
        eq.append(cash + val); inv.append(val / (cash + val))
        if d in picks:
            pend = list(picks[d])
    res.equity = pd.Series(eq, index=dates, dtype=float)
    res.invested = float(np.mean(inv)) if inv else 0.0
    yrs = max(len(dates) / 250, 1e-9)
    res.turnover = buys / float(res.equity.mean()) / yrs if len(eq) else 0.0
    res.holdings = [{"code": c, "entry": p["entry"].strftime("%Y-%m-%d"), "days": p["days"], "extends": p["extends"],
                     "entry_px": round(p["px"]), "last": round(p["last"]), "ret": p["last"] * (1 - sc) * p["sh"] / p["cost"] - 1,
                     "weight": p["sh"] * p["last"] / (cash + val) if cash + val else 0} for c, p in pos.items()]
    return res


def metrics(r: SimResult) -> dict:
    t = pd.DataFrame(r.trades)
    eq = r.equity
    out = {"trades": int(len(t)), "invested_pct": round(r.invested * 100), "turnover": round(r.turnover, 1)}
    if eq is not None and len(eq):
        yrs = len(eq) / 250
        out.update({"total_return_pct": round((eq.iloc[-1] / eq.iloc[0] - 1) * 100, 1) if eq.iloc[0] else None,
                    "cagr_pct": round(((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100, 1) if yrs >= 0.25 and eq.iloc[0] else None,
                    "mdd_pct": round(float((eq / eq.cummax() - 1).min()) * 100, 1)})
    if len(t):
        r_ = t.sort_values("exit")["ret"]
        w, l_ = r_[r_ > 0], r_[r_ <= 0]
        streak = mx = 0
        for x in r_:
            streak = streak + 1 if x <= 0 else 0; mx = max(mx, streak)
        out.update({"win_rate": round(len(w) / len(r_) * 100, 1), "avg_win_pct": round(w.mean() * 100, 2) if len(w) else None,
                    "avg_loss_pct": round(l_.mean() * 100, 2) if len(l_) else None,
                    "expectancy_pct": round(r_.mean() * 100, 2), "median_pct": round(r_.median() * 100, 2),
                    "profit_factor": round(w.sum() / -l_.sum(), 2) if len(l_) and l_.sum() < 0 else None,
                    "max_consec_losses": mx})
    return out
