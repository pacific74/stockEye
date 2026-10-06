"""브로커 (주문 실행).

  PaperBroker  — 내부 모의투자. 실제 돈·증권사 없이 현재가 + 슬리피지 + 수수료/세금으로 즉시 체결.
  KISBroker    — 한국투자증권 주문 API. env=vps(KIS 모의투자 계좌) 또는 prod(실전 계좌).
                 실전(prod)은 settings.yaml 의 trading.allow_real_orders: true 일 때만 동작.

모든 주문은 지정가(현재가 기준 호가 1~2틱 위/아래)로 낸다 — 시장가 급등락 체결 방지.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from ..backtest.costs import CostModel
from ..engine.trade_plan import round_tick, tick_size

log = logging.getLogger(__name__)


@dataclass
class Fill:
    ok: bool
    price: float = 0.0          # 체결 단가 (슬리피지 포함)
    qty: float = 0.0
    amount: float = 0.0         # 매수: 총 지불액(수수료 포함) / 매도: 총 수령액(수수료·세금 차감)
    broker_order_id: str | None = None
    message: str = ""


class PaperBroker:
    name = "paper"

    def __init__(self, costs: CostModel):
        self.costs = costs

    def buy(self, code: str, qty: int, price: float, value_ma20: float | None = None) -> Fill:
        px, paid = self.costs.buy(price, qty, value_ma20)
        return Fill(True, round(px, 2), qty, round(paid), f"paper-{int(time.time() * 1000)}", "모의 체결")

    def sell(self, code: str, qty: int, price: float, value_ma20: float | None = None) -> Fill:
        px, got = self.costs.sell(price, qty, value_ma20)
        return Fill(True, round(px, 2), qty, round(got), f"paper-{int(time.time() * 1000)}", "모의 체결")


class KISBroker:
    """KIS 현금 주문 (지정가). 체결 확인은 일별 주문체결 조회로 폴링."""

    def __init__(self, client, costs: CostModel, allow_real: bool = False, limit_ticks: int = 2):
        self.c, self.costs, self.limit_ticks = client, costs, limit_ticks
        self.name = "kis_" + client.env
        acct = os.getenv("KIS_ACCOUNT", "")            # 예: 12345678-01
        if "-" not in acct:
            raise RuntimeError("KIS_ACCOUNT 환경변수가 필요합니다 (예: 12345678-01)")
        self.cano, self.prdt = acct.split("-", 1)
        if client.env == "prod" and not allow_real:
            raise RuntimeError("실전 주문이 꺼져 있습니다 (settings.yaml trading.allow_real_orders: false)")

    def _order(self, side: str, code: str, qty: int, price: float) -> Fill:
        tick = tick_size(price)
        limit = round_tick(price + self.limit_ticks * tick if side == "buy" else price - self.limit_ticks * tick)
        tr = "TTTC0012U" if side == "buy" else "TTTC0011U"   # 모의(vps)는 KISClient 가 V 로 바꿔 보냄
        body = {"CANO": self.cano, "ACNT_PRDT_CD": self.prdt, "PDNO": code, "ORD_DVSN": "00",
                "ORD_QTY": str(int(qty)), "ORD_UNPR": str(int(limit)), "EXCG_ID_DVSN_CD": "KRX"}
        if side == "sell":
            body["SLL_TYPE"] = "01"
        try:
            js = self.c._post("/uapi/domestic-stock/v1/trading/order-cash", tr, body)
        except Exception as e:  # noqa: BLE001
            return Fill(False, message=f"주문 실패: {e}")
        odno = (js.get("output") or {}).get("ODNO") or (js.get("output") or {}).get("odno")
        filled = self._wait_fill(odno, code)
        if not filled:
            return Fill(False, broker_order_id=odno, message=f"지정가 {int(limit):,}원 주문 접수, 미체결 (HTS/MTS 에서 확인)")
        px, q = filled
        if side == "buy":
            _, amt = self.costs.buy(px, q, 1e12)
        else:
            _, amt = self.costs.sell(px, q, 1e12)
        return Fill(True, px, q, round(amt), odno, "체결")

    def _wait_fill(self, odno: str | None, code: str, tries: int = 6, gap: float = 2.0):
        if not odno:
            return None
        today = time.strftime("%Y%m%d")
        for _ in range(tries):
            time.sleep(gap)
            try:
                js = self.c._get("/uapi/domestic-stock/v1/trading/inquire-daily-ccld", "TTTC0081R", {
                    "CANO": self.cano, "ACNT_PRDT_CD": self.prdt, "INQR_STRT_DT": today, "INQR_END_DT": today,
                    "SLL_BUY_DVSN_CD": "00", "PDNO": code, "CCLD_DVSN": "01", "INQR_DVSN": "00", "INQR_DVSN_3": "00",
                    "ORD_GNO_BRNO": "", "ODNO": odno, "INQR_DVSN_1": "", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""})
            except Exception as e:  # noqa: BLE001
                log.warning("체결 조회 실패: %s", e)
                continue
            for r in js.get("output1") or []:
                if r.get("odno") == odno and float(r.get("tot_ccld_qty") or 0) > 0:
                    return float(r.get("avg_prvs") or 0), float(r["tot_ccld_qty"])
        return None

    def buy(self, code, qty, price, value_ma20=None) -> Fill:
        return self._order("buy", code, qty, price)

    def sell(self, code, qty, price, value_ma20=None) -> Fill:
        return self._order("sell", code, qty, price)


def make_broker(cfg: dict):
    """settings.yaml trading.broker 에 맞는 브로커. semi_auto 가 아니면 항상 내부 모의."""
    from ..config import data_dir
    tc = cfg["trading"]
    costs = CostModel.from_cfg(cfg)
    if tc["mode"] != "semi_auto" or tc.get("broker", "paper") == "paper":
        return PaperBroker(costs)
    from ..data.sources.kis_source import KISClient
    env = "vps" if tc["broker"] == "kis_vps" else "prod"
    client = KISClient(env, data_dir(cfg) / f".kis_token_{env}.json", cfg.get("kis", {}).get("calls_per_sec", 15))
    return KISBroker(client, costs, allow_real=tc.get("allow_real_orders", False))
