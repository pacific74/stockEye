"""V2 백테스트: 분할 진입(30/30/40) + 분할 익절(+8% 50% / +15% 25% / 나머지 추세 추종) + 시장 단계별 비중.

하루 순서 (T일)
  ① 09:00  전날 결정한 매수(1·2·3차)·매도(추세 이탈)를 T일 시가에 체결 (상한가 근처 갭상승은 매수 불가)
  ② 장중    손절 → 1차 익절(+8%) → 2차 익절(+15%) 순서로 확인 (같은 날 손절·익절 모두 닿으면 손절 우선)
  ③ 15:30  종가: 1차 익절 뒤 20일선 이탈 → 다음 날 시가 전량 매도 / 보유 기간 초과 → 다음 날 시가 매도
  ④ 18:00  그날까지 공개된 정보로 V2 평가 → 매수 신호 종목 1차 매수 예약,
           보유 종목: 반등 확인 → 2차 / 고점 돌파 + 거래량 → 3차 예약

체결 단위: 1차 30%, 2차 30%, 3차 40% (종목당 예산 = 자산 × position_pct × 시장 단계 비중)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

import pandas as pd

from ..data.pit import PointInTimeData, at, DECISION_TIME
from ..data.financials import FinIndex
from ..engine.filters import stage1
from ..engine.disclosure_rules import DisclosureIndex
from ..engine.v2 import V2Context, evaluate, market_states, v2_cfg
from .costs import CostModel
from .engine import BacktestResult, Trade, _yearly
from .metrics import compute_metrics

TRANCHES = (0.3, 0.3, 0.4)


@dataclass
class Pos:
    code: str
    signal_date: pd.Timestamp
    budget: float
    stop: float
    value_ma20: float
    score: float
    first_date: pd.Timestamp | None = None
    shares: int = 0
    cost: float = 0.0            # 누적 매수 지불액
    proceeds: float = 0.0        # 누적 매도 수령액
    bought_shares: int = 0
    tranche: int = 0             # 체결된 분할 매수 수
    tp1: bool = False
    tp2: bool = False
    days: int = 0
    peak: float = 0.0
    reasons: list = field(default_factory=list)

    @property
    def avg_raw(self) -> float:
        return self.cost / self.bought_shares if self.bought_shares else 0.0


class BacktesterV2:
    def __init__(self, data: PointInTimeData, cfg: dict, features: pd.DataFrame, fin: pd.DataFrame | None = None):
        self.data, self.cfg, self.features = data, cfg, features
        self.costs = CostModel.from_cfg(cfg)
        self.states = market_states(data.index)
        fin = fin if fin is not None else getattr(data, "financials", None)
        self.fin = FinIndex.from_raw(fin) if fin is not None and len(fin) else None
        self.disc = DisclosureIndex.build(data.disc) if len(data.disc) else None
        lst = data.listing
        self.market_of = dict(zip(lst["code"], lst["market"])) if not lst.empty else {}
        sec = getattr(data, "sectors", pd.DataFrame())
        self.sector_of = dict(zip(sec["code"], sec["sector"])) if not sec.empty else {}

    def run(self, start=None, end=None, prefilter: float = 55.0) -> BacktestResult:
        bt, vc = self.cfg["backtest"], v2_cfg(self.cfg)
        F = self.features
        dates = F.index.get_level_values("date").unique().sort_values()
        if start:
            dates = dates[dates >= pd.Timestamp(start)]
        if end:
            dates = dates[dates <= pd.Timestamp(end)]
        all_dates = list(F.index.get_level_values("date").unique().sort_values())
        gi = {d: k for k, d in enumerate(all_dates)}
        wide = {c: F[c].unstack("code") for c in ("open", "high", "low", "close", "volume", "sma20")}
        close_ff = wide["close"].ffill()

        def px(f, d, code):
            try:
                v = wide[f].at[d, code]
            except KeyError:
                return float("nan")
            return float(v)

        cash = float(bt["initial_capital"])
        pos: dict[str, Pos] = {}
        orders: list[dict] = []          # 내일 시가 주문 {code, kind: buy1/buy2/buy3/sell, ...}
        trades: list[Trade] = []
        equity = {}
        warns = set()
        n_signals = n_missed = 0
        max_pos = int(bt.get("max_positions", 5))
        max_hold = int((self.cfg.get("v2") or {}).get("max_hold_days", 40))

        def sell(p: Pos, d, raw, frac, reason):
            nonlocal cash
            n = p.shares if frac >= 1 else max(1, int(p.shares * frac))
            n = min(n, p.shares)
            if n <= 0:
                return
            _, got = self.costs.sell(raw, n, p.value_ma20)
            cash += got
            p.proceeds += got
            p.shares -= n
            p.reasons.append(reason)
            if p.shares == 0:
                close_trade(p, d, reason)

        def close_trade(p: Pos, d, reason):
            ret = p.proceeds / p.cost - 1 if p.cost else 0.0
            trades.append(Trade(p.code, str(p.signal_date.date()), str(p.first_date.date()), str(pd.Timestamp(d).date()),
                                round(p.avg_raw, 2), round(p.proceeds / max(p.bought_shares, 1), 2), p.bought_shares,
                                " → ".join(dict.fromkeys(p.reasons)), round(ret, 5), round(ret, 5),
                                round(p.proceeds - p.cost), p.days, p.score))
            pos.pop(p.code, None)

        def buy(p: Pos, d, raw, frac):
            nonlocal cash
            budget = min(cash, p.budget * frac)
            est = raw * (1 + self.costs.slip(p.value_ma20)) * (1 + self.costs.commission_rate)
            n = int(budget // est)
            if n <= 0:
                return False
            _, cost = self.costs.buy(raw, n, p.value_ma20)
            cash -= cost
            p.cost += cost
            p.shares += n
            p.bought_shares += n
            p.tranche += 1
            p.peak = max(p.peak, raw)
            if p.first_date is None:
                p.first_date = d
            return True

        for i, d in enumerate(dates):
            k = gi[d]
            prev = all_dates[k - 1] if k > 0 else None
            # ---------- ① 시가 체결 ----------
            for o in orders:
                code = o["code"]
                op = px("open", d, code)
                vol = px("volume", d, code)
                if math.isnan(op) or vol <= 0:
                    continue
                if o["kind"] == "sell":
                    if code in pos:
                        sell(pos[code], d, op, 1.0, o["reason"])
                    continue
                pc = px("close", prev, code) if prev is not None else op
                if pc and op >= pc * (1 + bt.get("limit_up_skip", 0.29)):
                    warns.add("상한가 근처 갭상승은 매수 불가로 처리")
                    continue
                if o["kind"] == "buy1":
                    if code in pos or len(pos) >= max_pos:
                        continue
                    if op <= o["stop"] or op > o["entry_high"] * 1.02:
                        n_missed += 1        # 매수구간을 벗어나 시작 → 체결 안 함
                        continue
                    eq_now = cash + sum(p.shares * close_ff.at[prev or d, p.code] for p in pos.values())
                    p = Pos(code, o["signal_date"], eq_now * bt["position_pct"] * o["size"], o["stop"],
                            o["value_ma20"], o["score"])
                    if buy(p, d, op, TRANCHES[0]):
                        pos[code] = p
                elif code in pos and pos[code].tranche == o["tranche"] - 1 and op > pos[code].stop:
                    buy(pos[code], d, op, TRANCHES[o["tranche"] - 1])
            orders = []

            # ---------- ② 장중 손절 / 분할 익절 ----------
            for code in list(pos):
                p = pos[code]
                op, hi, lo, cl = (px(f, d, code) for f in ("open", "high", "low", "close"))
                if math.isnan(cl):
                    last = close_ff[code].loc[:d].dropna()
                    sell(p, d, float(last.iloc[-1]) if len(last) else p.avg_raw, 1.0, "데이터 종료")
                    warns.add("데이터가 끊긴 종목은 마지막 종가로 청산")
                    continue
                if px("volume", d, code) <= 0:
                    p.days += 1
                    continue
                if prev is not None and p.first_date != d:
                    pcl = close_ff.at[prev, code]
                    if pcl > 0 and abs(op / pcl - 1) > 0.35:
                        sell(p, d, pcl, 1.0, "가격 불연속(병합·감자 추정)")
                        warns.add("가격제한폭을 넘는 가격 불연속은 직전 종가로 청산")
                        continue
                p.days += 1
                avg = p.avg_raw
                t1, t2 = avg * (1 + bt.get("tp1_pct", vc["target1_pct"])), avg * (1 + bt.get("tp2_pct", vc["target2_pct"]))
                if p.first_date != d and op <= p.stop:
                    sell(p, d, op, 1.0, "갭하락 손절")
                    continue
                if lo <= p.stop:
                    sell(p, d, p.stop, 1.0, "손절" if p.stop < avg else "본전·추적 손절")
                    continue
                if not p.tp1 and hi >= t1:
                    p.tp1 = True
                    sell(p, d, max(op, t1) if p.first_date != d else t1, 0.5, "1차 익절 +8%")
                    if bt.get("breakeven_after_tp1", True):
                        p.stop = max(p.stop, avg)          # 1차 익절 뒤 손절선 = 매수가
                if code in pos and p.tp1 and not p.tp2 and hi >= t2:
                    p.tp2 = True
                    sell(p, d, t2, 0.5, "2차 익절 +15%")
                if code not in pos:
                    continue
                p.peak = max(p.peak, cl)
                # ③ 종가: 1차 익절 뒤 20일선 이탈 / 기간 초과 → 내일 시가 매도
                s20 = px("sma20", d, code)
                if p.tp1 and not math.isnan(s20) and cl < s20:
                    orders.append({"code": code, "kind": "sell", "reason": "20일선 이탈"})
                elif p.days >= max_hold:
                    orders.append({"code": code, "kind": "sell", "reason": "기간만료"})

            equity[d] = cash + sum(p.shares * close_ff.at[d, p.code] for p in pos.values())

            # ---------- ④ 18:00 V2 평가 ----------
            if i >= len(dates) - 1:
                continue
            view = self.data.view(at(d, DECISION_TIME))
            try:
                x = F.xs(d, level="date")
            except KeyError:
                continue
            s1, _ = stage1(x, view.listing(), self.cfg)
            if s1.empty:
                continue
            ctx = V2Context(d, self.market_of, self.states, self.sector_of, self.fin, None)
            pre = evaluate(s1, ctx, self.cfg, detail=False)                # 공시 빼고 먼저 (빠르게)
            keep = pre.index[(pre["score"] + 8 >= prefilter) | pre.index.isin(list(pos))]
            if len(keep) == 0:
                continue
            ctx.disc = self.disc
            ev = evaluate(s1.loc[keep], ctx, self.cfg, detail=False)
            sells = {o["code"] for o in orders if o["kind"] == "sell"}
            # 보유 종목: 2차(반등 확인) / 3차(고점 돌파 + 거래량)
            for code, p in pos.items():
                if code in sells or code not in x.index or p.tp1:
                    continue
                r = x.loc[code]
                blocked = code in ev.index and bool(ev.at[code, "blocked"])
                if blocked:
                    continue
                if p.tranche == 1 and p.days <= 5 and bool(r["up_day"]) and r["close"] > p.avg_raw * 0.98:
                    orders.append({"code": code, "kind": "buy2", "tranche": 2})
                elif p.tranche == 2 and p.days <= 15 and r["close"] > r["high20_prev"] and r["vol_ratio"] >= 1.5:
                    orders.append({"code": code, "kind": "buy3", "tranche": 3})
            # 새 매수 신호
            sig = ev[ev["signal"] & (ev["size_mult"] > 0) & ~ev.index.isin(list(pos))]
            n_signals += len(sig)
            slots = max_pos - len(pos)
            for code, r in sig.head(max(slots, 0)).iterrows():
                orders.append({"code": code, "kind": "buy1", "signal_date": d, "stop": float(r["stop"]),
                               "entry_high": float(r["entry_high"]), "value_ma20": float(r["value_ma20"]),
                               "score": float(r["score"]), "size": float(r["size_mult"])})

        last = dates[-1]
        for code in list(pos):
            p = pos[code]
            sell(p, last, float(close_ff.at[last, code]), 1.0, "백테스트 종료")
        equity[last] = cash
        eq = pd.Series(equity).sort_index()
        bench = self._benchmark(eq.index)
        res = BacktestResult("V2 매수후보 엔진 (시장→업종→재무·공시→기술→가격위치→과열)", str(dates[0].date()),
                             str(dates[-1].date()), {"costs": asdict(self.costs), "backtest": bt, "v2": vc},
                             trades, eq, bench)
        res.metrics = compute_metrics(trades, eq, bench)
        split = eq.index[int(len(eq) * (1 - bt.get("oos_ratio", 0.3)))]
        is_tr = [t for t in trades if pd.Timestamp(t.entry_date) < split]
        oos_tr = [t for t in trades if pd.Timestamp(t.entry_date) >= split]
        res.metrics_is = compute_metrics(is_tr, eq[eq.index < split], bench) | {"period": f"{eq.index[0].date()} ~ {split.date()}"}
        res.metrics_oos = compute_metrics(oos_tr, eq[eq.index >= split], bench) | {"period": f"{split.date()} ~ {eq.index[-1].date()}"}
        res.yearly = _yearly(trades, eq)
        if self.fin is None:
            warns.add("재무 데이터 없음 → 재무 점수는 중립(6+1.5점)으로 계산")
        if self.disc is None:
            warns.add("공시 데이터 없음 → 공시 점수는 중립(7점), 공시 차단 없음")
        warns.add(f"매수 신호 {n_signals}건 중 매수구간을 벗어나 시작해 체결 안 된 것 {n_missed}건")
        res.warnings = sorted(warns)
        return res

    def _benchmark(self, idx):
        ix = self.data.index
        if ix.empty:
            return None
        k = ix[ix["code"] == "KOSPI"].set_index("date")["close"].reindex(idx).ffill()
        return k / k.dropna().iloc[0] if k.notna().any() else None
