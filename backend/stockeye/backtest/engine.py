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
    risk: float = 0.0        # 진입가 - 처음 손절가 (1R)
    peak: float = 0.0        # 보유 중 최고 종가 (추적 손절용)


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

        # ---- 실험 옵션 (기본값 = 꺼짐 → 예전과 같은 결과) ----
        regime_ma = int(bt.get("regime_ma", 0) or 0)            # 지수가 N일선 아래면 신규 매수 쉼
        regime_index = bt.get("regime_index", "KOSPI")         # KOSPI | KOSDAQ | own(종목의 시장 지수)
        trail_r = float(bt.get("trail_r", 0) or 0)              # 최고 종가 - trail_r × 1R 로 손절 끌어올림
        breakeven_r = float(bt.get("breakeven_r", 0) or 0)      # 종가가 +breakeven_r × 1R 넘으면 손절 = 본전
        target_r = bt.get("target_r")                           # None = 전략 목표가 / 0 = 목표가 없음 / k = 진입가 + k×1R
        max_new = int(bt.get("max_new_per_day", 0) or 0)        # 하루 신규 매수 최대 개수 (0 = 제한 없음)
        min_sig = float(bt.get("min_signal_score", 0) or 0)     # 신호 점수 하한
        regime_ok = self._regime(regime_ma, regime_index) if regime_ma > 0 else None
        market_of = {}
        if regime_ok is not None and regime_index == "own" and not self.data.listing.empty:
            market_of = dict(zip(self.data.listing["code"], self.data.listing["market"]))

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
                risk = max(op - o["stop"], op * 0.01)
                target = o["target"]
                if target_r is not None:
                    target = float("inf") if float(target_r) <= 0 else op + float(target_r) * risk
                positions[code] = Position(code, o["signal_date"], d, px, shares, cost,
                                           o["stop"], target, o["score"], o["value_ma20"], risk=risk, peak=op)
            pending = []

            # ---------- ② 장중 손절/목표, ③ 종가 ----------
            for code in list(positions):
                p = positions[code]
                split_r = 1.0
                if prev is not None and p.entry_date != d:
                    c0, c1 = bars.get("split_factor", prev, code), bars.get("split_factor", d, code)
                    if c0 and c1 and not math.isnan(c0) and not math.isnan(c1) and abs(c1 / c0 - 1) > 1e-6:
                        r = c1 / c0
                        split_r = r          # 액면분할 등: 가격 × r, 주식수 ÷ r
                        p.entry_px *= r
                        p.stop *= r
                        p.target *= r
                        p.peak *= r
                        p.risk *= r
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
                # 가격 불연속: 하루 가격제한(±30%)을 넘는 변화인데 분할 정보가 없음 = 병합·감자·재상장 등
                # → 실제 손익을 알 수 없으므로 직전 종가로 청산 (가짜 대박/쪽박 방지)
                if prev is not None and p.entry_date != d:
                    pcl = bars.get("close_ff", prev, code)
                    if pcl and not math.isnan(pcl) and pcl > 0 and abs(op / (pcl * split_r) - 1) > 0.35:
                        close_pos(p, d, pcl * split_r, "가격 불연속(병합·감자 추정)")
                        warnings.add("가격제한폭을 넘는 가격 불연속(병합·감자 등)은 직전 종가로 청산")
                        del positions[code]
                        continue
                p.days += 1
                exit_px, reason = None, None
                if p.entry_date != d and op <= p.stop:
                    exit_px, reason = op, "갭하락 손절"
                elif p.entry_date != d and op >= p.target:
                    exit_px, reason = op, "갭상승 목표"
                elif lo <= p.stop and hi >= p.target:
                    exit_px, reason = (p.stop, "손절(동시터치)") if bt["same_bar_rule"] == "stop_first" else (p.target, "목표")
                elif lo <= p.stop:
                    exit_px, reason = p.stop, ("추적 손절" if p.stop > p.entry_px else "손절")
                elif hi >= p.target:
                    exit_px, reason = p.target, "목표가"
                elif p.days >= bt["max_hold_days"]:
                    exit_px, reason = cl, "기간만료"
                if exit_px is not None:
                    close_pos(p, d, exit_px, reason)
                    del positions[code]
                    continue
                # 종가 기준으로 다음 날 손절선 끌어올리기 (오늘 종가까지만 사용 → 미래참조 없음)
                if trail_r > 0 or breakeven_r > 0:
                    p.peak = max(p.peak, cl)
                    entry_raw = p.entry_px / (1 + self.costs.slip(p.value_ma20))
                    if breakeven_r > 0 and cl >= entry_raw + breakeven_r * p.risk:
                        p.stop = max(p.stop, entry_raw)
                    if trail_r > 0:
                        p.stop = max(p.stop, p.peak - trail_r * p.risk)

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
                if max_new > 0:
                    slots = min(slots, max_new)
                market_ok = True if regime_ok is None or regime_index == "own" else bool(regime_ok.get(regime_index, {}).get(d, True))
                if slots > 0 and market_ok:
                    sigs = [s for s in strategy.signals(x, view) if s["code"] not in positions and s["score"] >= min_sig]
                    if regime_ok is not None and regime_index == "own":
                        sigs = [s for s in sigs if regime_ok.get(market_of.get(s["code"], "KOSPI"), {}).get(d, True)]
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

    def _regime(self, ma: int, which: str) -> dict:
        """{지수: {날짜: 종가 >= N일선}} — 그날 종가까지로 계산 (18:00 신호 시점에 알 수 있음)"""
        ix = self.data.index
        out = {}
        if ix.empty:
            return out
        for name, g in ix.groupby("code"):
            c = g.sort_values("date").set_index("date")["close"]
            m = c.rolling(ma, min_periods=ma).mean()
            out[name] = ((c >= m) | m.isna()).to_dict()
        return out

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
