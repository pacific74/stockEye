"""거래 비용: 수수료 + 매도 세금 + 슬리피지.

  매수 실제단가 = 시가 × (1 + 슬리피지)         + 수수료
  매도 실제단가 = 가격 × (1 - 슬리피지)         - 수수료 - 증권거래세(매도만)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CostModel:
    commission_rate: float = 0.00015
    sell_tax_rate: float = 0.0020
    slippage_bps: float = 10
    illiquid_slippage_bps: float = 30
    illiquid_threshold: float = 5e9

    @classmethod
    def from_cfg(cls, cfg: dict) -> "CostModel":
        return cls(**cfg["costs"])

    def slip(self, avg_value: float | None) -> float:
        bps = self.illiquid_slippage_bps if (avg_value or 0) < self.illiquid_threshold else self.slippage_bps
        return bps / 10_000

    def buy(self, price: float, shares: int, avg_value: float | None) -> tuple[float, float]:
        """(체결가, 총 지불액)"""
        px = price * (1 + self.slip(avg_value))
        gross = px * shares
        return px, gross * (1 + self.commission_rate)

    def sell(self, price: float, shares: int, avg_value: float | None) -> tuple[float, float]:
        """(체결가, 총 수령액)"""
        px = price * (1 - self.slip(avg_value))
        gross = px * shares
        return px, gross * (1 - self.commission_rate - self.sell_tax_rate)

    def round_trip_pct(self, avg_value: float | None = 1e11) -> float:
        """왕복 비용 (%) — 참고용"""
        s = self.slip(avg_value)
        return (2 * s + 2 * self.commission_rate + self.sell_tax_rate) * 100
