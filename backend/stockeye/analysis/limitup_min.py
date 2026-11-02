"""상한가 다음날 분봉 규칙 — 진입(시가 / 시초범위 돌파) + 청산(손절 · '몇 분 안에 +x% 안 되면 매도' · 시간 청산).
모든 판단은 그 봉까지의 정보만 쓴다. 한 봉 안에서 손절가와 목표가가 같이 닿으면 손절이 먼저 (보수적).
"""
from __future__ import annotations

import pandas as pd

COST = 0.2        # 왕복 %
STOP = 0.03       # 기본 손절 −3%
LIMIT_SKIP = 0.29  # 시가가 전일(상한가 종가) +29% 이상이면 이미 상한가 → 살 수 없음


def hm(bars: pd.DataFrame) -> pd.Series:
    return bars["time"].dt.strftime("%H:%M")


def entry_open(bars: pd.DataFrame, prev_close: float, stop: float = STOP) -> dict | None:
    """09:00 첫 봉 시가 매수 (시가가 상한가 근처면 못 삼)"""
    if bars is None or len(bars) < 10 or prev_close <= 0:
        return None
    px = float(bars["open"].iloc[0])
    if px <= 0 or px / prev_close - 1 >= LIMIT_SKIP:
        return None
    return {"idx": 0, "px": px, "stop_px": px * (1 - stop), "kind": "시가"}


def entry_orb(bars: pd.DataFrame, prev_close: float, n: int = 3, until: str = "09:10", stop: float = STOP) -> dict | None:
    """시초 n분 고점 돌파: n분 봉이 끝난 뒤 until 까지 종가가 그 고점을 넘으면 다음 봉 시가 매수, 손절은 시초 n분 저점(최대 −3%)"""
    if bars is None or len(bars) < n + 5 or prev_close <= 0:
        return None
    hi, lo = float(bars["high"].iloc[:n].max()), float(bars["low"].iloc[:n].min())
    if hi / prev_close - 1 >= LIMIT_SKIP:
        return None
    h = hm(bars)
    for j in range(n, len(bars) - 1):
        if h.iloc[j] > until:
            break
        if float(bars["close"].iloc[j]) > hi:
            px = float(bars["open"].iloc[j + 1])
            if px / prev_close - 1 >= LIMIT_SKIP:
                return None
            return {"idx": j + 1, "px": px, "stop_px": max(lo, px * (1 - stop)), "kind": "돌파"}
    return None


def run_exit(bars: pd.DataFrame, ent: dict, confirm_min: int | None = None, confirm_pct: float = 1.0,
             until: str | None = None, be: bool = False, target: float | None = None) -> dict:
    """진입 이후 청산 시뮬레이션 → {pnl(비용 포함 %), why, time}
      confirm_min : 진입 후 이 분 안에 고가가 진입가 +confirm_pct% 에 못 닿으면 그 분 종가에 매도
      until       : 'HH:MM' 이 되면 그 봉 종가에 매도 (없으면 장마감)
      be          : 확인(+confirm_pct% 도달) 뒤에는 손절을 본전(진입가 −0.2%)으로 올림
      target      : +target% 에 닿으면 매도"""
    px, stop = ent["px"], ent["stop_px"]
    h = hm(bars)
    thr = px * (1 + confirm_pct / 100)
    hi_max, confirmed = 0.0, confirm_min is None
    for j in range(ent["idx"], len(bars)):
        row = bars.iloc[j]
        lo, hi, cl = float(row["low"]), float(row["high"]), float(row["close"])
        elapsed = j - ent["idx"] + 1
        cur_stop = stop
        if be and confirmed and confirm_min is not None:
            cur_stop = max(stop, px * 0.998)
        if lo <= cur_stop:                                           # 손절 먼저
            return {"pnl": (cur_stop / px - 1) * 100 - COST, "why": "손절" if cur_stop == stop else "본전", "time": h.iloc[j]}
        hi_max = max(hi_max, hi)
        if confirm_min is not None and not confirmed and hi_max >= thr:
            confirmed = True
        if target and hi >= px * (1 + target / 100):
            return {"pnl": target - COST, "why": "목표", "time": h.iloc[j]}
        if confirm_min is not None and not confirmed and elapsed >= confirm_min:
            return {"pnl": (cl / px - 1) * 100 - COST, "why": "확인실패", "time": h.iloc[j]}
        if until and h.iloc[j] >= until:
            return {"pnl": (cl / px - 1) * 100 - COST, "why": "시간", "time": h.iloc[j]}
    return {"pnl": (float(bars["close"].iloc[-1]) / px - 1) * 100 - COST, "why": "장마감", "time": h.iloc[-1]}
