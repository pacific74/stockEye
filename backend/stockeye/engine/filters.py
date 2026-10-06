"""1차 / 2차 필터.

입력: 특정 날짜의 단면(cross-section) 피처 DataFrame (index=code)
출력: 통과 종목 DataFrame + 탈락 사유 집계
"""
from __future__ import annotations

import pandas as pd


def stage1(x: pd.DataFrame, listing: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict]:
    c = cfg["stage1"]
    drop = {}
    m = pd.Series(True, index=x.index)

    def apply(name, cond):
        nonlocal m
        cond = cond.reindex(x.index).fillna(False).astype(bool)
        drop[name] = int((m & ~cond).sum())
        m &= cond

    apply("데이터 부족", x["sma60"].notna() & x["atr14"].notna())
    apply(f"거래대금 {c['min_trading_value'] / 1e8:,.0f}억 미만", x["value_ma20"] >= c["min_trading_value"])
    apply(f"주가 {c['min_price']:,}원 미만", x["close"] >= c["min_price"])
    if c.get("exclude_halted", True):
        apply("거래정지", ~x["halted"].astype(bool))
    if c.get("exclude_admin", True) and not listing.empty and "is_admin" in listing:
        admin = set(listing.loc[listing["is_admin"].astype(bool), "code"])
        apply("관리종목", ~x.index.to_series().isin(admin))
    apply("최근 급락", (x["min_ret_5d"] > c["crash_daily_drop"]) & (x["ret5"] > c["crash_period_drop"]))
    return x[m], drop


# 2차 조건 정의: 이름 → (설명, 함수)
def _conditions(cfg):
    s2 = cfg["stage2"]
    return {
        "sma5_gt_sma20": ("5일선 > 20일선", lambda x: x["sma5"] > x["sma20"]),
        "sma20_rising": ("20일선 상승", lambda x: x["sma20_slope"] > 0),
        "close_gt_sma20": ("현재가 > 20일선", lambda x: x["close"] > x["sma20"]),
        "volume_up": ("거래량 증가", lambda x: x["vol_ratio"] >= s2["volume_up_ratio"]),
        "breakout_20d": ("20일 고점 돌파", lambda x: x["close"] > x["high20_prev"]),
        "macd_positive": ("MACD > 시그널", lambda x: x["macd"] > x["macd_signal"]),
        "rsi_in_zone": ("RSI 50~70", lambda x: x["rsi14"].between(50, 70)),
        "bb_upper_half": ("볼린저 중심선 위", lambda x: x["bb_pos"] > 0.5),
    }


def stage2(x: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict]:
    s2 = cfg["stage2"]
    conds = _conditions(cfg)
    drop = {}
    m = pd.Series(True, index=x.index)
    for key in s2["require"]:
        label, fn = conds[key]
        ok = fn(x).fillna(False)
        drop[label] = int((m & ~ok).sum())
        m &= ok
    ok = (x["rsi14"] < s2["rsi_max"]).fillna(False)
    drop[f"RSI {s2['rsi_max']} 이상 과열"] = int((m & ~ok).sum())
    m &= ok

    hits = sum(conds[k][1](x).fillna(False).astype(int) for k in s2["optional"])
    ok = hits >= s2["min_optional_hits"]
    drop[f"선택조건 {s2['min_optional_hits']}개 미만"] = int((m & ~ok).sum())
    m &= ok
    out = x[m].copy()
    out["stage2_hits"] = hits[m]
    return out, drop
