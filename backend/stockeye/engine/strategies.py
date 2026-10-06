"""매수 후보를 '여러 전략'으로 나눠서 뽑는다.

하나의 알고리즘으로 모든 종목을 판단하지 않는다.
각 전략은 (1) 조건 마스크 (2) 전략 고유 점수 (3) 근거 문장 을 가진다.
1차 필터(거래대금·가격·관리/정지·급락)는 모든 전략에 공통으로 먼저 적용된다.

  A. 돌파         신고가 · 거래량 증가 · 거래대금 증가 · 추세 상승
  B. 눌림목       강한 상승추세 · 단기 조정 · 20일선 근접 · 거래량 감소 · 재상승 신호
  C. 거래량 폭발  거래량 급증 · 거래대금 급증 · 가격 상승 (급등 초기)
  D. 수급         외국인/기관 지속 매수 · 가격 상승
  E. 저평가+전환  낮은 PER/PBR · EPS 증가 · 기술적 반전
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd


def _s(x: pd.DataFrame, col: str, default=np.nan) -> pd.Series:
    return x[col] if col in x else pd.Series(default, index=x.index, dtype="float64")


def _clip01(s: pd.Series) -> pd.Series:
    return s.clip(0, 1).fillna(0)


def _lin(s: pd.Series, lo: float, hi: float) -> pd.Series:
    return _clip01((s - lo) / (hi - lo))


@dataclass
class StrategyDef:
    key: str
    name: str
    short: str
    description: str
    mask: Callable[[pd.DataFrame], pd.Series]
    score: Callable[[pd.DataFrame], pd.Series]          # 0~100
    reasons: Callable[[pd.Series], list[str]]


# ---------------------------------------------------------------- A. 돌파
def _a_mask(x):
    return ((x["close"] > x["high60_prev"]) & (x["vol_ratio"] >= 1.5) & (x["value_ratio1"] >= 1.5)
            & (x["sma20_slope"] > 0) & (x["close"] > x["sma20"]) & (x["rsi14"] < 85))


def _a_score(x):
    return 100 * (0.30 * _lin(x["near_high250"], 0.85, 1.0) + 0.25 * _lin(x["vol_ratio"], 1.5, 4)
                  + 0.20 * _lin(x["value_ratio1"], 1.5, 4) + 0.15 * _lin(x["sma20_slope"], 0, 0.05)
                  + 0.10 * _lin(x["close_pos"], 0.5, 1.0))


def _a_reasons(r):
    out = ["최근 60일 고점 돌파"]
    if r.get("near_high250", 0) >= 0.98:
        out.append("52주 신고가 근접/돌파")
    out += [f"거래량 {r['vol_ratio']:.1f}배", f"거래대금 {r['value_ratio1']:.1f}배", "20일선 상승 추세"]
    return out


# ---------------------------------------------------------------- B. 눌림목
def _b_mask(x):
    return ((x["sma20"] > x["sma60"]) & (x["sma60_slope"] > 0) & (x["ret60"] > 0.15)        # 강한 상승추세
            & x["ret5"].between(-0.12, -0.01)                                                # 단기 조정
            & x["dist_sma20"].between(-0.03, 0.04)                                           # 20일선 근접
            & (x["vol5_ratio"] < 0.9)                                                        # 거래량 감소
            & x["up_day"].astype(bool))                                                      # 재상승 신호 (양봉+상승)


def _b_score(x):
    return 100 * (0.30 * _lin(x["ret60"], 0.15, 0.6) + 0.25 * (1 - _lin(x["dist_sma20"].abs(), 0, 0.04))
                  + 0.20 * (1 - _lin(x["vol5_ratio"], 0.4, 0.9)) + 0.15 * _lin(x["sma60_slope"], 0, 0.05)
                  + 0.10 * _lin(x["close_pos"], 0.5, 1.0))


def _b_reasons(r):
    return [f"60일 상승률 +{r['ret60'] * 100:.0f}% (강한 추세)", f"최근 5일 {r['ret5'] * 100:.1f}% 조정",
            f"20일선 이격 {r['dist_sma20'] * 100:+.1f}% (근접)", f"조정 중 거래량 감소 ({r['vol5_ratio']:.2f}배)",
            "오늘 양봉으로 재상승 시도"]


# ---------------------------------------------------------------- C. 거래량 폭발 (급등 초기)
def _c_mask(x):
    return ((x["vol_ratio"] >= 3) & (x["value_ratio1"] >= 3) & x["ret1"].between(0.03, 0.20)
            & (x["close_pos"] >= 0.6) & (x["ret20"] < 0.35) & (x["value"] >= 3e9))


def _c_score(x):
    return 100 * (0.35 * _lin(x["vol_ratio"], 3, 10) + 0.25 * _lin(x["value_ratio1"], 3, 10)
                  + 0.20 * _lin(x["close_pos"], 0.6, 1.0) + 0.20 * (1 - _lin(x["ret20"], 0.0, 0.35)))


def _c_reasons(r):
    return [f"거래량 {r['vol_ratio']:.1f}배 폭발", f"거래대금 {r['value_ratio1']:.1f}배",
            f"당일 +{r['ret1'] * 100:.1f}%, 고가권 마감", f"20일 상승률 {r['ret20'] * 100:+.0f}% (초기 구간)"]


# ---------------------------------------------------------------- D. 수급
def _d_mask(x):
    fs, is_ = _s(x, "foreign_streak", 0), _s(x, "institution_streak", 0)
    f5, i5 = _s(x, "foreign_net5"), _s(x, "institution_net5")
    return (((fs >= 3) | (is_ >= 3)) & (f5 > 0) & (i5 > 0) & (x["ret5"] > 0) & (x["close"] > x["sma20"]))


def _d_score(x):
    turn = (x["value_ma20"] * 5).replace(0, np.nan)
    f5, i5 = _s(x, "foreign_net5"), _s(x, "institution_net5")
    return 100 * (0.30 * _lin((f5 + i5) / turn, 0, 0.10) + 0.25 * _lin(_s(x, "foreign_streak", 0), 2, 8)
                  + 0.20 * _lin(_s(x, "institution_streak", 0), 2, 8) + 0.15 * _lin(x["ret5"], 0, 0.1)
                  + 0.10 * _lin(-_s(x, "individual_net5", 0) / turn, 0, 0.1))


def _d_reasons(r):
    out = []
    if r.get("foreign_streak", 0) >= 2:
        out.append(f"외국인 {int(r['foreign_streak'])}일 연속 순매수")
    if r.get("institution_streak", 0) >= 2:
        out.append(f"기관 {int(r['institution_streak'])}일 연속 순매수")
    out.append("외국인·기관 5일 동반 순매수")
    out.append(f"5일 주가 {r['ret5'] * 100:+.1f}%")
    return out


# ---------------------------------------------------------------- E. 저평가 + 추세전환
def _e_mask(x):
    per, pbr, eps_yoy = _s(x, "per"), _s(x, "pbr"), _s(x, "eps_yoy")
    cheap = ((per > 0) & (per < 12)) | ((pbr > 0) & (pbr < 1.0))
    growth = eps_yoy > 0.10
    turn = ((x["close"] > x["sma20"]) & (x["below20_recent"] > 0)                     # 최근 20일선 회복
            & (x["macd_hist"] > 0) & (x["macd_hist_prev"] <= x["macd_hist"]))        # MACD 반전
    return cheap & growth & turn & (_s(x, "eps") > 0)


def _e_score(x):
    per, pbr = _s(x, "per"), _s(x, "pbr")
    return 100 * (0.30 * (1 - _lin(per, 4, 12)) + 0.20 * (1 - _lin(pbr, 0.3, 1.5))
                  + 0.30 * _lin(_s(x, "eps_yoy"), 0.1, 1.0) + 0.20 * _lin(x["vol_ratio"], 1, 3))


def _e_reasons(r):
    out = []
    if 0 < r.get("per", 0) < 12:
        out.append(f"PER {r['per']:.1f}배 (저평가)")
    if 0 < r.get("pbr", 0) < 1:
        out.append(f"PBR {r['pbr']:.2f}배")
    if pd.notna(r.get("eps_yoy")):
        out.append(f"EPS 1년 전 대비 +{r['eps_yoy'] * 100:.0f}%")
    out += ["최근 20일선 회복 (추세 전환)", "MACD 히스토그램 반전"]
    return out


STRATEGIES: dict[str, StrategyDef] = {
    "A": StrategyDef("A", "돌파 전략", "돌파", "신고가 + 거래량·거래대금 증가 + 상승 추세", _a_mask, _a_score, _a_reasons),
    "B": StrategyDef("B", "눌림목 전략", "눌림목", "강한 상승추세 중 20일선까지 거래량 줄며 조정 후 재상승", _b_mask, _b_score, _b_reasons),
    "C": StrategyDef("C", "거래량 폭발 전략", "급등 초기", "거래량·거래대금 급증 + 가격 상승 (아직 초기)", _c_mask, _c_score, _c_reasons),
    "D": StrategyDef("D", "수급 전략", "수급", "외국인·기관 지속 순매수 + 주가 상승", _d_mask, _d_score, _d_reasons),
    "E": StrategyDef("E", "저평가 + 추세전환", "저평가 전환", "낮은 PER/PBR + EPS 증가 + 20일선 회복·MACD 반전", _e_mask, _e_score, _e_reasons),
}

LIMITATIONS = {
    "E": "매출·영업이익 증가는 아직 미반영 (KRX 일별 EPS만 사용). DART 재무제표 연동 시 추가 예정.",
    "D": "프로그램 매매는 KIS 연동 시 반영.",
}


def select(key: str, x: pd.DataFrame) -> pd.DataFrame:
    """1차 필터를 통과한 단면 x 에서 전략 조건을 만족하는 종목 + strategy_score."""
    st = STRATEGIES[key]
    need = [c for c in ("sma60", "atr14") if c in x]
    base = x.dropna(subset=need)
    m = st.mask(base).fillna(False).astype(bool)
    out = base[m].copy()
    out["strategy_score"] = st.score(out).round(1) if len(out) else pd.Series(dtype=float)
    return out.sort_values("strategy_score", ascending=False)
