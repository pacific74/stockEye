"""'그래서 사도 되냐' — 매수구간 / 목표가 / 손절가 / 손익비.

모든 가격은 ATR(평균 변동폭) 기반으로 계산하고 KRX 호가단위로 맞춘다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import pandas as pd


def tick_size(price: float) -> int:
    """KRX 호가가격단위 (2023.1.25 개편, 코스피·코스닥 동일)."""
    for limit, tick in ((2_000, 1), (5_000, 5), (20_000, 10), (50_000, 50),
                        (200_000, 100), (500_000, 500)):
        if price < limit:
            return tick
    return 1_000


def round_tick(price: float, mode: str = "nearest") -> int:
    t = tick_size(price)
    f = {"nearest": round, "down": math.floor, "up": math.ceil}[mode]
    return int(f(price / t) * t)


@dataclass
class TradePlan:
    price: int
    entry_low: int
    entry_high: int
    target1: int
    target2: int
    stop: int
    loss_pct: float
    target1_pct: float
    target2_pct: float
    rr1: float
    rr2: float
    verdict: str          # 매수 고려 / 눌림 대기 / 관망
    verdict_reason: str

    def to_dict(self):
        return asdict(self)


def make_plan(r: pd.Series, score: float, warnings: list[str], cfg: dict) -> TradePlan:
    p = cfg["trade_plan"]
    c, a = float(r["close"]), float(r["atr14"])

    entry_low = round_tick(c - p["entry_low_atr"] * a, "down")
    entry_high = round_tick(c + p["entry_high_atr"] * a, "up")

    stop_atr = c - p["stop_atr"] * a
    stop_ma = float(r["sma20"]) * 0.985 if pd.notna(r.get("sma20")) else stop_atr
    stop = max(stop_atr, stop_ma)                      # 둘 중 가까운(높은) 쪽
    hi = c - p["stop_min_atr"] * a                     # 최소 1 ATR 은 여유
    lo = c * (1 - p["max_stop_pct"])                   # 최대 8% 손절
    stop = min(stop, hi)
    stop = max(stop, min(lo, hi))
    stop = round_tick(stop, "down")

    t1 = round_tick(c + p["target1_atr"] * a, "down")
    t2 = round_tick(c + p["target2_atr"] * a, "down")

    loss = (stop / c - 1)
    g1, g2 = (t1 / c - 1), (t2 / c - 1)
    rr1 = g1 / -loss if loss < 0 else float("nan")
    rr2 = g2 / -loss if loss < 0 else float("nan")

    # ---- 판정 ----
    hot = any(w.startswith(("RSI 과열", "단기 상승폭", "20일선 이격")) for w in warnings)
    bad = any(w.startswith(("악재성 공시", "적자")) for w in warnings)
    if bad:
        verdict, why = "관망", "악재성 공시/적자 등 리스크 요인"
    elif score >= 80 and rr1 >= 1.5 and not hot:
        verdict, why = "매수 고려", f"점수 {score:.0f}점, 손익비 1:{rr1:.2f}"
    elif score >= 75 and hot:
        verdict, why = "눌림 대기", f"조건은 좋지만 단기 과열 → {entry_low:,}원 근처 눌림에서 접근"
    elif score >= 70 and rr1 >= 1.2:
        verdict, why = "관심", "조건 일부 충족, 추가 확인 필요"
    else:
        verdict, why = "관망", "점수 또는 손익비 부족"

    return TradePlan(int(round(c)), entry_low, entry_high, t1, t2, stop,
                     round(loss * 100, 1), round(g1 * 100, 1), round(g2 * 100, 1),
                     round(rr1, 2), round(rr2, 2), verdict, why)


def strategy_verdict(plan: TradePlan | dict, strategy_key: str, strategy_score: float, total: float,
                     warnings: list[str]) -> tuple[str, str]:
    """전략 후보용 판정. 눌림목(B)·저평가(E)는 종합점수(돌파 성향)가 낮게 나오는 게 정상이라
    전략 점수 위주로 본다."""
    p = plan if isinstance(plan, dict) else plan.to_dict()
    rr = p["rr1"]
    hot = any(w.startswith(("RSI 과열", "단기 상승폭", "20일선 이격")) for w in warnings)
    bad = any(w.startswith(("악재성 공시", "적자")) for w in warnings)
    blend = strategy_score if strategy_key in ("B", "E") else 0.6 * strategy_score + 0.4 * total
    if bad:
        return "관망", "악재성 공시/적자 등 리스크 요인"
    if hot and strategy_key in ("A", "C", "D"):
        return "눌림 대기", f"전략 조건 충족, 단기 과열 → {p['entry_low']:,}원 근처 눌림에서 접근"
    if blend >= 70 and rr >= 1.5:
        return "매수 고려", f"전략 점수 {strategy_score:.0f}점, 손익비 1:{rr:.2f}"
    if blend >= 55 and rr >= 1.2:
        return "관심", f"전략 점수 {strategy_score:.0f}점, 추가 확인 필요"
    return "관망", "전략 점수 또는 손익비 부족"
