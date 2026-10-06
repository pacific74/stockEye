"""이벤트 기반(하루씩 전진하는) 백테스트 엔진.

하루의 순서 (T일):
  ① 09:00  전날 신호로 만든 주문을 T일 '시가'에 체결  (상한가 근처 갭상승이면 매수 불가)
  ② 장중    보유 종목 손절/목표 체크 (같은 날 둘 다 닿으면 손절 우선 = 보수적)
  ③ 15:30  종가로 평가, 보유기간 초과 시 종가 청산
  ④ 18:00  T일까지 공개된 데이터만으로 신호 계산 → T+1일 주문 예약

시계(Clock)가 '지금'을 들고 있고, 가격 조회가 '지금 이후'를 요청하면 FutureDataError.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

from ..data.pit import PointInTimeData, FutureDataError, at, DECISION_TIME
from ..indicators import compute_features
from .costs import CostModel
from .metrics import compute_metrics

log = logging.getLogger(__name__)


class GuardedBars:
    """가격 테이블 접근을 시계(cursor)로 막는 래퍼."""

    def __init__(self, feat: pd.DataFrame):
        cols = ["open", "high", "low", "close", "volume", "value_ma20", "split_factor"]
        self.wide = {c: feat[c].unstack("code") for c in cols}
        self.wide["close_ff"] = self.wide["close"].ffill()   # 평가용 (거래정지일은 직전 종가)
        self.dates = self.wide["close"].index
        self.cursor = None  # 현재 시각에 '공개된' 마지막 날짜

    def get(self, field_: str, date, code):
        date = pd.Timestamp(date)
        if self.cursor is None or date > self.cursor:
            raise FutureDataError(f"[미래참조 차단] 현재 {self.cursor} 인데 {date.date()} {field_} 조회 시도")
        try:
            v = self.wide[field_].at[date, code]
        except KeyError:
            return float("nan")
        return float(v)


@dataclass
class Position:
    code: str
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    entry_px: float          # 슬리피지 포함 체결가
    shares: int
    cost: float              # 수수료 포함 총 지불액
    stop: float
    target: float
    score: float
    value_ma20: float
    days: int = 0


@dataclass
class Trade:
    code: str
    signal_date: str
    entry_date: str
    exit_date: str
    entry_px: float
    exit_px: float
    shares: int
    reason: str
    gross_ret: float         # 비용 전 수익률
    net_ret: float           # 수수료+세금+슬리피지 반영
    pnl: float
    hold_days: int
    score: float


@dataclass
class BacktestResult:
    strategy: str
    start: str
    end: str
    params: dict
    trades: list = field(default_factory=list)
    equity: pd.Series | None = None
    benchmark: pd.Series | None = None
    metrics: dict = field(default_factory=dict)
    metrics_is: dict = field(default_factory=dict)
    metrics_oos: dict = field(default_factory=dict)
    yearly: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    audit: dict | None = None

    def to_dict(self, with_trades: int = 200):
        eq = self.equity
        return {
            "strategy": self.strategy, "start": self.start, "end": self.end, "params": self.params,
            "metrics": self.metrics, "metrics_is": self.metrics_is, "metrics_oos": self.metrics_oos,
            "yearly": self.yearly, "warnings": self.warnings, "audit": self.audit,
            "equity": [{"date": str(d.date()), "equity": round(float(v))} for d, v in eq.items()] if eq is not None else [],
            "benchmark": [{"date": str(d.date()), "value": float(v)} for d, v in self.benchmark.items()]
            if self.benchmark is not None else [],
            "trades": [asdict(t) for t in self.trades[-with_trades:]],
        }


class Backtester:
    def __init__(self, data: PointInTimeData, cfg: dict, features: pd.DataFrame | None = None):
        self.data, self.cfg = data, cfg
        self.costs = CostModel.from_cfg(cfg)
        self.features = features if features is not None else compute_features(data.ohlcv, data.flows, data.fund)

    def run(self, strategy, start=None, end=None) -> BacktestResult:
        bt = self.cfg["backtest"]
        bars = GuardedBars(self.features)
        dates = bars.dates
        if start:
            dates = dates[dates >= pd.Timestamp(start)]
        if end:
            dates = dates[dates <= pd.Timestamp(end)]
        if len(dates) < 2:
            raise ValueError("백테스트 기간에 데이터가 부족합니다")

        cash = float(bt["initial_capital"])
        positions: dict[str, Position] = {}
        pending: list[dict] = []
        trades: list[Trade] = []
        equity = {}
        warnings = set()
        all_dates = list(bars.dates)
        pos_of = {d: k for k, d in enumerate(all_dates)}
        missed = 0      # 매수구간에 오지 않아 체결 안 된 신호 수

        def close_pos(p: Position, date, raw_px, reason):
            nonlocal cash
            px, proceeds = self.costs.sell(raw_px, p.shares, p.value_ma20)
            cash += proceeds
            trades.append(Trade(
                p.code, str(p.signal_date.date()), str(p.entry_date.date()), str(pd.Timestamp(date).date()),
                round(p.entry_px, 2), round(px, 2), p.shares, reason,
                round(raw_px / (p.entry_px / (1 + self.costs.slip(p.value_ma20))) - 1, 5),
                round(proceeds / p.cost - 1, 5), round(proceeds - p.cost), p.days, p.score))

        for i, d in enumerate(dates):
            # ---------- ① 시가 체결 ----------
            bars.cursor = d   # 장 시작: 오늘 시가까지는 '현재' (고가/저가/종가는 장중 순서대로 사용)
            gi = pos_of[d]
            prev = all_dates[gi - 1] if gi > 0 else None
            for o in pending:
                code = o["code"]
                if code in positions or len(positions) >= bt["max_positions"]:
                    continue
                op = bars.get("open", d, code)
                vol = bars.get("volume", d, code)
                if not op or math.isnan(op) or vol <= 0:
                    continue  # 거래정지/데이터 없음
                pc = bars.get("close", prev, code) if prev is not None else op
                if op >= pc * (1 + bt["limit_up_skip"]):
                    warnings.add("상한가 근처 갭상승 종목은 매수 불가로 처리함")
                    continue
                if op <= o["stop"]:
                    continue  # 시가가 이미 손절가 아래 → 진입 취소
                fill = op
                eh, el = o.get("entry_high"), o.get("entry_low")
                if bt.get("entry_mode", "zone") == "zone" and eh and el:
                    # 실전 감시와 같은 규칙: '매수 적정구간'에 들어올 때만 산다 (지정가 entry_high)
                    hi, lo = bars.get("high", d, code), bars.get("low", d, code)
                    floor = el * 0.995
                    if op > eh:                       # 갭상승 출발 → 장중에 구간 상단까지 내려와야 체결
                        if lo <= eh:
                            fill = eh
                        else:
                            missed += 1
                            continue
                    elif op < floor:                  # 구간 아래 출발 → 구간 하단까지 올라와야 체결
                        if hi >= floor and floor > o["stop"]:
                            fill = floor
                        else:
                            missed += 1
                            continue
                op = fill
                equity_now = cash + sum(p.shares * bars.get("close_ff", prev or d, p.code) for p in positions.values())
                budget = min(cash, equity_now * bt["position_pct"])
                px_est = op * (1 + self.costs.slip(o["value_ma20"])) * (1 + self.costs.commission_rate)
                shares = int(budget // px_est)
                if shares <= 0:
                    continue
                px, cost = self.costs.buy(op, shares, o["value_ma20"])
                cash -= cost
                positions[code] = Position(code, o["signal_date"], d, px, shares, cost,
                                           o["stop"], o["target"], o["score"], o["value_ma20"])
            pending = []

            # ---------- ② 장중 손절/목표, ③ 종가 ----------
            for code in list(positions):
                p = positions[code]
                if prev is not None and p.entry_date != d:
                    c0, c1 = bars.get("split_factor", prev, code), bars.get("split_factor", d, code)
                    if c0 and c1 and not math.isnan(c0) and not math.isnan(c1) and abs(c1 / c0 - 1) > 1e-6:
                        r = c1 / c0          # 액면분할 등: 가격 × r, 주식수 ÷ r
                        p.entry_px *= r
                        p.stop *= r
                        p.target *= r
                        p.shares = int(round(p.shares / r))
                op, hi, lo, cl = (bars.get(f, d, code) for f in ("open", "high", "low", "close"))
                vol = bars.get("volume", d, code)
                if math.isnan(cl):
                    # 데이터가 끊김(상장폐지 등) → 마지막 종가로 청산
                    last = self.features.xs(code, level="code")["close"].loc[:d].dropna()
                    close_pos(p, d, float(last.iloc[-1]) if len(last) else p.entry_px, "데이터 종료")
                    warnings.add("데이터가 끊긴 종목은 마지막 종가로 청산 (상장폐지 위험 과소평가 가능)")
                    del positions[code]
                    continue
                if vol <= 0:
                    p.days += 1
                    continue  # 거래정지: 매도 불가
                p.days += 1
                exit_px, reason = None, None
                if p.entry_date != d and op <= p.stop:
                    exit_px, reason = op, "갭하락 손절"
                elif p.entry_date != d and op >= p.target:
                    exit_px, reason = op, "갭상승 목표"
                elif lo <= p.stop and hi >= p.target:
                    exit_px, reason = (p.stop, "손절(동시터치)") if bt["same_bar_rule"] == "stop_first" else (p.target, "목표")
                elif lo <= p.stop:
                    exit_px, reason = p.stop, "손절"
                elif hi >= p.target:
                    exit_px, reason = p.target, "목표가"
                elif p.days >= bt["max_hold_days"]:
                    exit_px, reason = cl, "기간만료"
                if exit_px is not None:
                    close_pos(p, d, exit_px, reason)
                    del positions[code]

            equity[d] = cash + sum(p.shares * bars.get("close_ff", d, p.code) for p in positions.values())

            # ---------- ④ 장 마감 후 신호 (T일 18:00 기준 PIT) ----------
            if i < len(dates) - 1:
                as_of = at(d, DECISION_TIME)
                view = self.data.view(as_of)
                try:
                    x = self.features.xs(d, level="date")
                except KeyError:
                    continue
                slots = bt["max_positions"] - len(positions)
                if slots > 0:
                    sigs = [s for s in strategy.signals(x, view) if s["code"] not in positions]
                    for s in sigs[:slots]:
                        s["signal_date"] = d
                        pending.append(s)

        # 마지막 날 전량 청산
        last = dates[-1]
        for code, p in list(positions.items()):
            close_pos(p, last, bars.get("close_ff", last, code), "백테스트 종료")
        equity[last] = cash

        eq = pd.Series(equity).sort_index()
        bench = self._benchmark(eq.index)
        res = BacktestResult(getattr(strategy, "name", str(strategy)), str(dates[0].date()), str(dates[-1].date()),
                             {"costs": asdict(self.costs), "backtest": bt}, trades, eq, bench)
        res.metrics = compute_metrics(trades, eq, bench)
        split = eq.index[int(len(eq) * (1 - bt["oos_ratio"]))]
        is_tr = [t for t in trades if pd.Timestamp(t.entry_date) < split]
        oos_tr = [t for t in trades if pd.Timestamp(t.entry_date) >= split]
        res.metrics_is = compute_metrics(is_tr, eq[eq.index < split], bench) | {"period": f"{eq.index[0].date()} ~ {split.date()}"}
        res.metrics_oos = compute_metrics(oos_tr, eq[eq.index >= split], bench) | {"period": f"{split.date()} ~ {eq.index[-1].date()}"}
        res.yearly = _yearly(trades, eq)
        if self.data.listing.empty or "as_of" not in self.data.listing or \
                pd.to_datetime(self.data.listing["as_of"]).min() > dates[0]:
            warnings.add("과거 시점의 관리종목/상장종목 목록이 없음 → 생존편향 가능 (상장폐지 종목 누락)")
        if missed:
            warnings.add(f"매수 적정구간에 오지 않아 체결되지 않은 신호 {missed}건 (실전 감시와 같은 규칙)")
        res.warnings = sorted(warnings)
        return res

    def _benchmark(self, idx) -> pd.Series | None:
        ix = self.data.index
        if ix.empty:
            return None
        k = ix[ix["code"] == "KOSPI"].set_index("date")["close"].reindex(idx).ffill()
        return k / k.dropna().iloc[0] if k.notna().any() else None


def _yearly(trades: list[Trade], eq: pd.Series) -> list[dict]:
    out = []
    for y, s in eq.groupby(eq.index.year):
        prev = eq[eq.index.year < y]
        base = prev.iloc[-1] if len(prev) else s.iloc[0]
        tr = [t for t in trades if t.exit_date[:4] == str(y)]
        wins = [t for t in tr if t.net_ret > 0]
        out.append({"year": int(y), "return_pct": round(float(s.iloc[-1] / base - 1) * 100, 1),
                    "trades": len(tr), "win_rate": round(len(wins) / len(tr) * 100, 1) if tr else None,
                    "mdd_pct": round(float(((s / s.cummax()) - 1).min()) * 100, 1)})
    return out
