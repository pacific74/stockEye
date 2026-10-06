"""실시간 신호 → 알림 / 모의투자 / 반자동 매매.

단계 (settings.yaml 의 trading.mode):
  alert      3단계: 신호가 나면 휴대폰 알림만
  paper      4단계: 신호가 나면 내부 모의계좌로 자동 체결 + 매매일지 자동 기록 (실제 돈 X)
  semi_auto  5단계: 신호 → 알림 → 앱에서 '승인' → 주문 → 체결 → 매매일지
                    (브로커: kis_vps = KIS 모의투자 계좌, kis_prod = 실전. 실전은 allow_real_orders 필요)

신호 (통계/알고리즘이 결정, AI 는 관여하지 않음):
  진입   전날 리포트의 매수 후보 중 판정이 entry_verdicts 인 종목이 '매수 적정구간'에 들어오면
  손절   보유 종목 현재가 ≤ 손절가
  목표   보유 종목 현재가 ≥ 1차 목표가
  기간   보유 영업일 ≥ max_hold_days 이고 15:10 이후

안전장치: 최대 보유 종목 수, 하루 최대 매수 주문 수, 1회 주문 금액 상한, 하루 손실 한도,
          같은 종목 하루 1번만 진입 신호, 승인 대기 주문 자동 만료, 상한가 근처 매수 금지.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time as dtime

import pandas as pd

from ..backtest.costs import CostModel
from .brokers import PaperBroker, Fill
from .journal import Journal, now_str, business_days
from .notify import Notifier

log = logging.getLogger(__name__)


@dataclass
class Quote:
    code: str
    price: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    time: datetime = field(default_factory=datetime.now)

    @property
    def change_pct(self) -> float:
        return (self.price / self.prev_close - 1) * 100 if self.prev_close else 0.0


def _t(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


class TradingEngine:
    def __init__(self, cfg: dict, journal: Journal, report: dict | None, notifier: Notifier | None = None,
                 broker=None, app_url: str | None = None):
        self.cfg, self.tc = cfg, cfg["trading"]
        self.mode = self.tc["mode"]                         # alert | paper | semi_auto
        self.j, self.report = journal, report or {}
        self.n = notifier or Notifier()
        self.costs = CostModel.from_cfg(cfg)
        self.broker = broker or PaperBroker(self.costs)
        self.app_url = app_url
        bname = getattr(self.broker, "name", "paper")
        # 매매일지 모드: paper(내부 모의) / kis_paper(KIS 모의투자 계좌) / real(실전)
        self.pos_mode = "paper" if self.mode == "paper" or bname == "paper" else ("kis_paper" if bname == "kis_vps" else "real")
        self.watch = self._watchlist()

    # ---------------------------------------------------------------- 감시 목록
    def _watchlist(self) -> dict[str, dict]:
        """전날 리포트에서 진입 대상 후보 (코드 → 후보 dict + list_key)."""
        out = {}
        verdicts = set(self.tc.get("entry_verdicts", ["매수 고려"]))
        rep = self.report
        lists = self.tc.get("signal_lists", ["overall", "A", "B", "D"])
        for key in lists:
            cands = rep.get("candidates", []) if key == "overall" else rep.get("strategies", {}).get(key, {}).get("candidates", [])
            for c in cands:
                if c["plan"]["verdict"] in verdicts and c["code"] not in out:
                    out[c["code"]] = {**c, "list_key": key}
        return out

    def codes_to_watch(self) -> list[str]:
        held = [p["code"] for p in self.j.positions(status="open")]
        return sorted(set(self.watch) | set(held))

    # ---------------------------------------------------------------- 한 번의 시세 갱신 처리
    def tick(self, quotes: dict[str, Quote], now: datetime | None = None) -> list[dict]:
        now = now or datetime.now()
        events = []
        self.j.expire_orders()
        # 보유 포지션: 최고/최저 갱신 + 청산 신호
        for p in self.j.positions(status="open"):
            q = quotes.get(p["code"])
            if not q:
                continue
            self.j.track_price(p["id"], q.low or q.price, q.high or q.price)
            ev = self._exit_signal(p, q, now)
            if ev:
                events.append(ev)
        # 진입 신호
        if _t(self.tc.get("entry_start", "09:05")) <= now.time() <= _t(self.tc.get("entry_end", "15:00")):
            for code, c in self.watch.items():
                q = quotes.get(code)
                if q:
                    ev = self._entry_signal(c, q, now)
                    if ev:
                        events.append(ev)
        return events

    # ---------------------------------------------------------------- 진입
    def _entry_signal(self, c: dict, q: Quote, now: datetime) -> dict | None:
        p = c["plan"]
        if self.j.alerted_today("entry", c["code"]) or self.j.positions(status="open", code=c["code"]):
            return None
        in_zone = p["entry_low"] * 0.995 <= q.price <= p["entry_high"]
        if not in_zone or q.price <= p["stop"] or q.change_pct >= 25:
            return None
        msg = (f"{c['name']} {q.price:,.0f}원 — 매수 적정구간 {p['entry_low']:,}~{p['entry_high']:,}원 진입\n"
               f"점수 {c['score']:.0f} · {self._list_name(c['list_key'])} · 손절 {p['stop']:,} · 1차 {p['target1']:,} "
               f"(손익비 1:{p['rr1']})")
        blocked = self._risk_block(q.price)
        ev = {"type": "entry", "code": c["code"], "name": c["name"], "price": q.price, "message": msg, "blocked": blocked}
        self.j.add_alert("entry", c["code"], c["name"], msg + (f"\n⛔ {blocked}" if blocked else ""), {"price": q.price})

        if self.mode == "alert" or blocked:
            self.n.send("📈 매수 신호" + (" (주문 보류)" if blocked else ""), msg + (f"\n⛔ {blocked}" if blocked else ""))
            return ev
        qty = self._size(q.price)
        if self.mode == "paper":
            ev["fill"] = self._execute_buy(c, q, qty, now, order_status="filled")
            return ev
        # semi_auto: 승인 대기 주문
        oid = self.j.add_order(self.pos_mode, "buy", c["code"], qty, price=q.price, name=c["name"], reason="진입 신호",
                               snapshot={**c, "signal_price": q.price, "signal_time": now_str()},
                               expires_min=self.tc.get("approval_timeout_min", 10))
        ev["order_id"] = oid
        self.n.send("🟢 매수 승인 요청", f"{msg}\n수량 {qty}주 ≈ {qty * q.price:,.0f}원\n"
                    f"{self.tc.get('approval_timeout_min', 10)}분 안에 앱 → 승인 대기에서 승인",
                    priority="high", url=self.app_url)
        return ev

    def _size(self, price: float) -> int:
        krw = min(self.tc.get("position_krw", 1_000_000), self.tc.get("max_order_krw", 1_000_000))
        return max(int(krw // price), 0)

    def _risk_block(self, price: float) -> str | None:
        opens = self.j.positions(status="open", mode=self.pos_mode)
        if len(opens) >= self.tc.get("max_positions", 5):
            return f"보유 {len(opens)}종목 (최대 {self.tc.get('max_positions', 5)})"
        if self.j.orders_today(self.pos_mode, "buy") >= self.tc.get("max_daily_buys", 3):
            return f"오늘 매수 주문 {self.tc.get('max_daily_buys', 3)}회 한도 도달"
        if self._size(price) <= 0:
            return "1회 주문 금액으로 1주도 살 수 없음"
        lim = self.tc.get("daily_loss_limit_pct")
        if lim:
            today = datetime.now().strftime("%Y-%m-%d")
            pnl = sum(p["pnl"] or 0 for p in self.j.positions(status="closed", mode=self.pos_mode)
                      if (p["exit_time"] or "").startswith(today))
            cap = self.tc.get("paper_capital", 10_000_000)
            if pnl / cap * 100 <= -abs(lim):
                return f"오늘 손실 {pnl:,.0f}원 → 하루 손실 한도({lim}%) 도달, 신규 진입 중지"
        if self.pos_mode == "paper" and self.mode == "paper":
            cash = self.j.cash("paper", self.tc.get("paper_capital", 10_000_000))
            if cash < self._size(price) * price * 1.01:
                return f"모의계좌 현금 부족 ({cash:,.0f}원)"
        return None

    def _execute_buy(self, c: dict, q: Quote, qty: int, now: datetime, order_status="filled", oid=None) -> dict:
        fill: Fill = self.broker.buy(c["code"], qty, q.price)
        if oid is None:
            oid = self.j.add_order(self.pos_mode, "buy", c["code"], qty, price=q.price, name=c["name"],
                                   reason="진입 신호", snapshot=c, status="sent")
        if not fill.ok:
            self.j.update_order(oid, status="failed", message=fill.message, broker_order_id=fill.broker_order_id)
            self.n.send("⚠ 매수 실패", f"{c['name']} {fill.message}", priority="high")
            return {"ok": False, "message": fill.message}
        pid = self.j.open_position(self.pos_mode, c["code"], fill.price, fill.qty, cand=c, entry_cost=fill.amount,
                                   entry_time=now.strftime("%Y-%m-%d %H:%M:%S"),
                                   market_mood=self.report.get("market", {}).get("mood"), list_key=c.get("list_key"),
                                   signal_time=c.get("signal_time"))
        self.j.update_order(oid, status="filled", filled_price=fill.price, filled_qty=fill.qty, filled_at=now_str(),
                            broker_order_id=fill.broker_order_id, position_id=pid)
        if self.mode == "paper":
            self.j.add_cash("paper", -fill.amount, self.tc.get("paper_capital", 10_000_000))
        p = c["plan"]
        self.n.send(f"✅ {'모의 ' if self.pos_mode == 'paper' else ''}매수 체결",
                    f"{c['name']} {fill.qty:.0f}주 @ {fill.price:,.0f}원\n손절 {p['stop']:,} · 1차 {p['target1']:,} · 2차 {p['target2']:,}\n"
                    f"매매일지에 자동 기록됨")
        return {"ok": True, "position_id": pid, "price": fill.price, "qty": fill.qty}

    # ---------------------------------------------------------------- 청산
    def _exit_signal(self, p: dict, q: Quote, now: datetime) -> dict | None:
        reason = None
        if p["stop"] and q.price <= p["stop"]:
            reason = "손절"
        elif p["target1"] and q.price >= p["target1"]:
            reason = "목표가"
        elif (business_days(p["entry_time"], now.strftime("%Y-%m-%d")) >= self.cfg["backtest"]["max_hold_days"]
              and now.time() >= _t("15:10")):
            reason = "기간만료"
        if not reason or self.j.alerted_today(f"exit:{reason}", p["code"]):
            return None
        ret = (q.price / p["entry_price"] - 1) * 100
        msg = f"{p['name']} {q.price:,.0f}원 ({ret:+.1f}%) — {reason}" + (
            f" (손절가 {p['stop']:,.0f})" if reason == "손절" else f" (목표 {p['target1']:,.0f})" if reason == "목표가" else "")
        self.j.add_alert(f"exit:{reason}", p["code"], p["name"], msg, {"position_id": p["id"]})
        ev = {"type": "exit", "reason": reason, "code": p["code"], "name": p["name"], "price": q.price,
              "position_id": p["id"], "message": msg}
        icon = "🔴" if reason == "손절" else "🎯" if reason == "목표가" else "⏱"
        auto = (p["mode"] == "paper" and self.mode == "paper") or (
            reason == "손절" and self.tc.get("auto_stop_loss", False) and p["mode"] == self.pos_mode)
        if p["mode"] == "manual" or self.mode == "alert" or p["mode"] != self.pos_mode:
            self.n.send(f"{icon} {reason} 신호", msg, priority="high" if reason == "손절" else "default")
        elif auto:
            ev["fill"] = self._execute_sell(p, q, reason, now)
        else:
            oid = self.j.add_order(self.pos_mode, "sell", p["code"], p["qty"], price=q.price, name=p["name"],
                                   reason=reason, position_id=p["id"], expires_min=self.tc.get("approval_timeout_min", 10))
            ev["order_id"] = oid
            self.n.send(f"{icon} 매도 승인 요청 ({reason})", msg + "\n앱 → 승인 대기에서 승인",
                        priority="urgent" if reason == "손절" else "high", url=self.app_url)
        return ev

    def _execute_sell(self, p: dict, q: Quote, reason: str, now: datetime, oid=None) -> dict:
        fill = self.broker.sell(p["code"], int(p["qty"]), q.price)
        if oid is None:
            oid = self.j.add_order(p["mode"], "sell", p["code"], p["qty"], price=q.price, name=p["name"],
                                   reason=reason, position_id=p["id"], status="sent")
        if not fill.ok:
            self.j.update_order(oid, status="failed", message=fill.message)
            self.n.send("⚠ 매도 실패", f"{p['name']} {fill.message}", priority="urgent")
            return {"ok": False, "message": fill.message}
        closed = self.j.close_position(p["id"], fill.price, reason=reason, proceeds=fill.amount,
                                       exit_time=now.strftime("%Y-%m-%d %H:%M:%S"))
        self.j.update_order(oid, status="filled", filled_price=fill.price, filled_qty=fill.qty, filled_at=now_str(),
                            broker_order_id=fill.broker_order_id)
        if p["mode"] == "paper":
            self.j.add_cash("paper", fill.amount, self.tc.get("paper_capital", 10_000_000))
        self.n.send(f"{'✅' if closed['ret_pct'] > 0 else '❌'} {'모의 ' if p['mode'] == 'paper' else ''}매도 체결",
                    f"{p['name']} @ {fill.price:,.0f}원  수익률 {closed['ret_pct']:+.1f}%  보유 {closed['hold_days']}일\n"
                    f"사유: {reason} · 결과: {closed['result']}")
        return {"ok": True, "ret_pct": closed["ret_pct"]}

    # ---------------------------------------------------------------- 승인 / 거절 (5단계)
    def approve(self, oid: str, quote: Quote) -> dict:
        o = self.j.get_order(oid)
        # approve_requested = 앱(Supabase)에서 승인 버튼을 누른 주문 → 감시 서버가 여기서 실제 처리
        if not o or o["status"] not in ("pending", "approve_requested"):
            return {"ok": False, "message": "승인 대기 주문이 아닙니다 (만료/처리됨)"}
        if o["expires_at"] and o["expires_at"] < now_str():
            self.j.update_order(oid, status="expired")
            return {"ok": False, "message": "승인 시간이 지나 만료됐습니다"}
        self.j.update_order(oid, status="approved")
        now = datetime.now()
        if o["side"] == "buy":
            c = o["snapshot"]
            # 승인 시점 가격이 손절가 이하이거나 매수구간을 크게 벗어났으면 취소
            if quote.price <= c["plan"]["stop"] or quote.price > c["plan"]["entry_high"] * 1.02:
                self.j.update_order(oid, status="rejected", message=f"승인 시점 가격 {quote.price:,.0f}원이 매수구간 이탈")
                return {"ok": False, "message": "가격이 매수구간을 벗어나 주문하지 않았습니다"}
            blocked = self._risk_block(quote.price)
            if blocked:
                self.j.update_order(oid, status="rejected", message=blocked)
                return {"ok": False, "message": blocked}
            self.j.update_order(oid, status="sent")
            return self._execute_buy(c, quote, int(o["qty"]), now, oid=oid)
        p = self.j.get_position(o["position_id"])
        if not p or p["status"] != "open":
            self.j.update_order(oid, status="rejected", message="이미 청산된 포지션")
            return {"ok": False, "message": "이미 청산된 포지션"}
        self.j.update_order(oid, status="sent")
        return self._execute_sell(p, quote, o["reason"] or "수동", now, oid=oid)

    def process_app_approvals(self, quotes_fn) -> list[dict]:
        """앱에서 승인한 주문(approve_requested)을 현재가로 다시 확인해 처리. quotes_fn(codes) → {code: Quote}"""
        reqs = self.j.orders(status="approve_requested")
        if not reqs:
            return []
        qs = quotes_fn([o["code"] for o in reqs])
        out = []
        for o in reqs:
            q = qs.get(o["code"])
            if q is None:
                if o.get("price") and getattr(self.broker, "name", "paper") == "paper":
                    q = Quote(o["code"], float(o["price"]))   # 시세 실패 → 신호가 기준 (내부 모의 브로커만)
                else:
                    self.j.update_order(o["id"], status="failed", message="현재가 조회 실패")
                    continue
            r = self.approve(o["id"], q)
            if not r.get("ok"):
                self.n.send("주문 처리 안 됨", f"{o['name']}: {r.get('message')}")
            out.append({"id": o["id"], **r})
        return out

    def reject(self, oid: str) -> dict:
        o = self.j.get_order(oid)
        if not o or o["status"] != "pending":
            return {"ok": False, "message": "승인 대기 주문이 아닙니다"}
        self.j.update_order(oid, status="rejected", message="사용자 거절")
        return {"ok": True}

    @staticmethod
    def _list_name(k):
        return {"overall": "종합", "A": "돌파", "B": "눌림목", "C": "급등 초기", "D": "수급", "E": "저평가 전환"}.get(k, k)


# ---------------------------------------------------------------- 시세 소스
class KISQuotes:
    def __init__(self, client):
        self.c = client

    def get(self, codes: list[str]) -> dict[str, Quote]:
        out = {}
        for code in codes:
            try:
                p = self.c.price(code)
                out[code] = Quote(code, p["price"], p.get("open"), p.get("high"), p.get("low"), p.get("prev_close"))
            except Exception as e:  # noqa: BLE001
                log.warning("%s 시세 실패: %s", code, e)
        return out


class ReplayQuotes:
    """일봉으로 장중 흐름을 흉내 내는 재생 시세 (시뮬레이션·테스트용).
    양봉: 시가→저가→고가→종가, 음봉: 시가→고가→저가→종가 경로를 잘게 나눠(13단계) 순서대로 갱신.
    → 손절/목표가를 '건너뛰지' 않고 그 근처에서 걸리게 된다."""

    N = 13

    def __init__(self, ohlcv: pd.DataFrame, date):
        d = pd.Timestamp(date).normalize()
        day = ohlcv[ohlcv["date"] == d].set_index("code")
        prev = ohlcv[ohlcv["date"] < d].sort_values("date").groupby("code")["close"].last()
        self.day, self.prev, self.date = day, prev, d
        self.step = 0
        start, end = 9 * 60 + 10, 15 * 60 + 15
        self.times = [start + (end - start) * i // (self.N - 1) for i in range(self.N)]

    def now(self) -> datetime:
        m = self.times[min(self.step, self.N - 1)]
        return datetime.combine(self.date.date(), dtime(m // 60, m % 60))

    def _path(self, r) -> list[float]:
        pts = [r.open, r.low, r.high, r.close] if r.close >= r.open else [r.open, r.high, r.low, r.close]
        out = [float(pts[0])]
        for a, b in zip(pts[:-1], pts[1:]):
            out += [float(a + (b - a) * k / 4) for k in range(1, 5)]
        return out                                           # 13개

    def get(self, codes: list[str]) -> dict[str, Quote]:
        out = {}
        for code in codes:
            if code not in self.day.index:
                continue
            r = self.day.loc[code]
            path = self._path(r)
            i = min(self.step, self.N - 1)
            seen = path[: i + 1]
            out[code] = Quote(code, path[i], float(r.open), max(seen), min(seen),
                              float(self.prev.get(code, r.open)), self.now())
        return out

    def advance(self) -> bool:
        self.step += 1
        return self.step < self.N
