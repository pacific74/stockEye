"""1분봉 보관 — 그날 어떤 종목의 분봉을 저장할지 고르는 규칙.
KIS 과거 분봉은 보관 기간이 짧아 나중엔 못 받으므로, 장이 끝나면 매일 저장해 둔다 (data/minute_cache/YYYYMMDD/종목.parquet,
15번·24번·25번이 같은 캐시를 읽음)."""
from __future__ import annotations

import pandas as pd

TOP_VALUE = 150      # 거래대금 상위
MOVE_UP = 8.0        # +8% 이상 오른 종목 (상한가 후보·급등)
MOVE_DOWN = -8.0     # −8% 이하 (급락 후 반등 연구용)
MIN_VALUE = 3e9      # 위 두 가지는 거래대금 30억 이상만
MAX_MOVERS = 120
CARRY = 25.0         # 어제 +25% 이상(상한가 마감)이면 오늘도 저장 (상한가 다음날 연구)


def pick(snap: pd.DataFrame, prev_hot: list[str] | None = None, top: int = TOP_VALUE) -> list[str]:
    """snap: code · chg_pct · value (그날 종가 기준). prev_hot: 전 거래일에 +CARRY% 이상이던 종목"""
    if snap is None or snap.empty:
        return list(prev_hot or [])
    s = snap.dropna(subset=["value"]).copy()
    by_val = s.sort_values("value", ascending=False).head(top)["code"].tolist()
    mv = s[(s.value >= MIN_VALUE) & ((s.chg_pct >= MOVE_UP) | (s.chg_pct <= MOVE_DOWN))]
    movers = mv.sort_values("value", ascending=False).head(MAX_MOVERS)["code"].tolist()
    return list(dict.fromkeys(by_val + movers + list(prev_hot or [])))


def hot(snap: pd.DataFrame) -> list[str]:
    if snap is None or snap.empty:
        return []
    return snap.loc[snap.chg_pct >= CARRY, "code"].tolist()


def in_market_window(now: pd.Timestamp, start: str = "08:35", end: str = "15:35") -> bool:
    """평일 장중(22번 실시간 실행 시간대)이면 True — 이때는 KIS 키가 겹치므로 분봉 보관을 하지 않는다"""
    return now.weekday() < 5 and start <= now.strftime("%H:%M") < end


def missing_days(days: list, done: set[str], lookback: int = 10) -> list[pd.Timestamp]:
    """일봉에 있는 최근 lookback 거래일 중 아직 보관 완료 표시가 없는 날 (오래된 날 먼저)"""
    ds = [pd.Timestamp(d) for d in sorted(days)[-lookback:]]
    return [d for d in ds if d.strftime("%Y%m%d") not in done]
