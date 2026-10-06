"""백테스트용 전략 정의.

두 종류:
  1) RuleStrategy    — 사용자가 조건을 나열 (예: 20일선 위, 거래량 2배, 20일 고점 돌파, 외국인 순매수, RSI 50~70)
  2) ScreenerStrategy — 실전 종목 선정 엔진 그대로 (1·2차 필터 + 100점) 상위 N개

전략은 '그날의 단면 피처(x)'와 PIT 뷰만 받는다 → 그 이후 날짜는 볼 방법이 없다.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from ..data.pit import PITView
from ..engine.screener import screen_cross_section, titles_from_view
from ..engine.scoring import score_row
from ..engine.trade_plan import make_plan
from ..engine.filters import stage1
from ..engine.strategies import STRATEGIES, select as strategy_select

# 조건 레지스트리: 이름 → (설명 생성, 마스크 함수)
RULES: dict[str, Callable] = {
    "close_gt_sma20": lambda x, _: x["close"] > x["sma20"],
    "close_gt_sma60": lambda x, _: x["close"] > x["sma60"],
    "sma5_gt_sma20": lambda x, _: x["sma5"] > x["sma20"],
    "sma20_rising": lambda x, _: x["sma20_slope"] > 0,
    "vol_ratio_gte": lambda x, v: x["vol_ratio"] >= v,
    "value_ma20_gte": lambda x, v: x["value_ma20"] >= v,
    "price_gte": lambda x, v: x["close"] >= v,
    "breakout_20d": lambda x, _: x["close"] > x["high20_prev"],
    "breakout_60d": lambda x, _: x["close"] > x["high60_prev"],
    "foreign_net_positive": lambda x, _: x.get("foreign_net", pd.Series(float("nan"), index=x.index)) > 0,
    "institution_net_positive": lambda x, _: x.get("institution_net", pd.Series(float("nan"), index=x.index)) > 0,
    "foreign_streak_gte": lambda x, v: x.get("foreign_streak", pd.Series(0, index=x.index)) >= v,
    "rsi_between": lambda x, v: x["rsi14"].between(v[0], v[1]),
    "macd_positive": lambda x, _: x["macd"] > x["macd_signal"],
    "not_halted": lambda x, _: ~x["halted"].astype(bool),
}

RULE_LABELS = {
    "close_gt_sma20": "현재가 > 20일선", "close_gt_sma60": "현재가 > 60일선", "sma5_gt_sma20": "5일선 > 20일선",
    "sma20_rising": "20일선 상승", "vol_ratio_gte": "거래량 {v}배 이상", "value_ma20_gte": "거래대금(20일 평균) ≥ {v:,.0f}",
    "price_gte": "주가 ≥ {v:,}", "breakout_20d": "최근 20일 고점 돌파", "breakout_60d": "최근 60일 고점 돌파",
    "foreign_net_positive": "외국인 순매수", "institution_net_positive": "기관 순매수",
    "foreign_streak_gte": "외국인 {v}일 연속 순매수", "rsi_between": "RSI {v[0]}~{v[1]}",
    "macd_positive": "MACD > 시그널", "not_halted": "거래정지 아님",
}


def _parse(rule):
    if isinstance(rule, str):
        return rule, None
    (k, v), = rule.items()
    return k, v


def describe_rules(rules) -> list[str]:
    out = []
    for r in rules:
        k, v = _parse(r)
        out.append(RULE_LABELS.get(k, k).format(v=v))
    return out


class RuleStrategy:
    def __init__(self, rules: list, cfg: dict, rank_by: str = "score"):
        self.rules, self.cfg, self.rank_by = rules, cfg, rank_by
        for r in rules:
            k, _ = _parse(r)
            if k not in RULES:
                raise KeyError(f"알 수 없는 조건: {k}  (사용 가능: {', '.join(RULES)})")

    @property
    def name(self):
        return " + ".join(describe_rules(self.rules))

    def signals(self, x: pd.DataFrame, view: PITView) -> list[dict]:
        need = x["atr14"].notna() & x["sma20"].notna()
        m = need
        for r in self.rules:
            k, v = _parse(r)
            m &= RULES[k](x, v).fillna(False)
        sel = x[m]
        out = []
        for code, r in sel.iterrows():
            sr = score_row(code, r, self.cfg["score_weights"], None)
            plan = make_plan(r, sr.total, sr.warnings, self.cfg)
            out.append({"code": code, "score": sr.total, "stop": plan.stop, "target": plan.target1,
                        "entry_low": plan.entry_low, "entry_high": plan.entry_high, "value_ma20": r["value_ma20"]})
        key = "score" if self.rank_by == "score" else "value_ma20"
        return sorted(out, key=lambda d: d[key], reverse=True)


class ScreenerStrategy:
    """실전 엔진 그대로. min_score 이상 (verdicts 를 주면 해당 판정만, 예: ("매수 고려",))."""
    name = "StockEye 종목 선정 엔진 (1·2차 필터 + 100점)"

    def __init__(self, cfg: dict, min_score: float = 75, verdicts=()):
        self.cfg, self.min_score, self.verdicts = cfg, min_score, set(verdicts)

    def signals(self, x: pd.DataFrame, view: PITView) -> list[dict]:
        titles = titles_from_view(view, x.index)
        res = screen_cross_section(x, view.listing(), titles, self.cfg, view.as_of.normalize(), view.as_of,
                                   names=view._listing, with_strategies=False)
        out = []
        for c in res.candidates:
            if c.score >= self.min_score and (not self.verdicts or c.plan["verdict"] in self.verdicts):
                out.append({"code": c.code, "score": c.score, "stop": c.plan["stop"], "target": c.plan["target1"],
                            "entry_low": c.plan["entry_low"], "entry_high": c.plan["entry_high"],
                            "value_ma20": float(x.at[c.code, "value_ma20"])})
        return out


class NamedStrategy:
    """전략 A~E 를 그대로 백테스트. 1차 필터 → 전략 조건 → (전략점수 60% + 종합점수 40%) 순."""

    def __init__(self, key: str, cfg: dict):
        if key not in STRATEGIES:
            raise KeyError(f"전략 키는 {', '.join(STRATEGIES)} 중 하나")
        self.key, self.cfg = key, cfg
        self.name = f"{key}. {STRATEGIES[key].name} — {STRATEGIES[key].description}"

    def signals(self, x: pd.DataFrame, view: PITView) -> list[dict]:
        s1, _ = stage1(x, view.listing(), self.cfg)
        sel = strategy_select(self.key, s1)
        out = []
        for code, r in sel.head(20).iterrows():
            sr = score_row(code, r, self.cfg["score_weights"], None)
            plan = make_plan(r, sr.total, sr.warnings, self.cfg)
            out.append({"code": code, "score": 0.6 * float(r["strategy_score"]) + 0.4 * sr.total,
                        "stop": plan.stop, "target": plan.target1, "entry_low": plan.entry_low,
                        "entry_high": plan.entry_high, "value_ma20": float(r["value_ma20"])})
        return sorted(out, key=lambda d: d["score"], reverse=True)
