"""추세전환 후보 (실험 탭 — V3B 고정 전략과 별개, 매매 규칙 없음)

바닥에서 하락이 멈추고 20일선이 수평 → 상승으로 돌아서는 종목을 100점으로 평가한다.
  ① 이전 하락·바닥 형성 15  ② 바닥 횡보·가격 안정 25  ③ 이동평균선 방향 전환 35
  ④ 초기 반등 확인 15        ⑤ 거래량·변동성 안정 10
- 선정일 종가까지 확정된 데이터만 사용 (t = 선정일). 수정주가 기준.
- 점수는 계단(0·5·10·15)이 아니라 기준점 사이를 직선으로 이어 소수점까지 매긴다 (각 항목 배점 상한).
- 자격: 1차 필터(거래정지·관리종목·거래대금·주가) 통과 + 매수 차단(재무·공시 위험) 아님.
- 70점 이상 = 후보, 80점 이상 = 우선 관찰. 동점이면 ③ → ② → 거래대금 순.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

VERSION = "TR-0.2"
CANDIDATE, PRIORITY = 70.0, 80.0
PARTS = {"bottom15": ("하락·바닥", 15), "base25": ("바닥 횡보", 25), "ma35": ("이평 전환", 30),
         "rebound15": ("초기 반등", 15), "volume10": ("거래량·변동성", 10), "news5": ("뉴스", 5)}
# 뉴스 (2026-10-12): 네이버 뉴스 최근 3일 제목 → 호재 5 · 중립/기사 없음 2.5 · 악재 0 (analysis.news_flags 가 저녁 배치에서 조정).
#   과거 뉴스는 없으므로 점수 계산·백테스트에서는 모두 중립 2.5
NEWS_NEUTRAL = 2.5

SUBS = {  # 세부 항목: (상위 항목, 이름, 배점)
    "d60": ("bottom15", "60일 고점 대비 하락률", 15),
    "r20": ("base25", "20일 종가 횡보폭", 10), "low": ("base25", "저점 유지", 10), "run": ("base25", "바닥권 체류일", 5),
    "s20": ("ma35", "20일선 기울기", 15), "a20": ("ma35", "20일선 기울기 개선", 10), "s60": ("ma35", "60일선 방향", 10),
    "g20": ("rebound15", "20일선과 거리", 5), "r5": ("rebound15", "5일 수익률", 5), "bar": ("rebound15", "오늘 봉 위치", 5),
    "atr": ("volume10", "변동폭 축소", 3), "vshrink": ("volume10", "거래량 수축", 3), "updown": ("volume10", "상승일 거래량", 2),
    "vtoday": ("volume10", "오늘 거래량", 2),
}
RULES_TEXT = [
    "① 60일 고점 대비 30~40% 하락이 만점 (15% 미만 하락 0점, 40% 넘게 급락하면 감점)",
    "② 최근 20일 종가 폭이 좁고(10% 이내 만점), 최근 10일 저점이 이전 10일 저점보다 높고, 바닥권에 오래 머물수록 높음",
    "③ 20일선이 수평 → 상승(5일 +0.5~1.5% 만점, 너무 가파르면 감점), 기울기가 좋아지는 중, 60일선 하락 멈춤",
    "④ 종가가 20일선 바로 위(0~3%), 최근 5일 소폭 상승(0~3%), 오늘 양봉이고 고가 근처 마감",
    "⑤ 변동폭·거래량이 줄었다가, 상승일 거래량이 하락일보다 많고, 오늘 거래량이 적당히 늘어남 (폭증은 감점)",
    "점수는 기준 사이를 직선으로 이어 소수점까지 계산 · 70점 이상 후보 · 80점 이상 우선 관찰",
    "매매 규칙 없음 (관찰용) — V3 기준 전략과 별개",
]


def ramp(v, knots):
    """기준점 [(x, 점수), ...] 사이를 직선으로 잇고 양끝은 그대로 (NaN → NaN)"""
    xs, ys = zip(*knots)
    a = np.asarray(v, dtype=float)
    out = np.interp(a, xs, ys)
    return np.where(np.isnan(a), np.nan, out)


# 기준점: 사용자 표의 구간을 그대로 따르되 경계에서 점수가 뚝 끊기지 않게 이음 (만점 구간은 평평하게 유지)
K = {
    "d60": [(-60, 8), (-45, 10), (-40, 15), (-30, 15), (-25, 10), (-17.5, 5), (-12, 0)],      # D %
    "r20": [(10, 10), (15, 7), (20, 4), (25, 2), (30, 0)],                                   # R20 %
    "low": [(-4, 0), (-2, 3), (0, 7), (2, 10)],                                              # L %
    "run": [(4, 0), (5, 2), (10, 4), (15, 5)],                                               # 일
    "s20": [(-3.5, 0), (-2, 4), (-0.65, 8), (0, 12), (0.5, 15), (1.5, 15), (2.5, 10)],       # S20 %
    "a20": [(-1.5, 0), (-0.5, 2), (0.25, 5), (1, 8), (2, 10)],                               # A20 %p
    "s60": [(-3.5, 0), (-2, 2), (-0.65, 5), (0, 8), (0.6, 10)],                              # S60 %
    "g20": [(-6, 0), (-4, 1), (-1.5, 3), (0.5, 5), (2.5, 5), (5, 3), (8, 0)],                # G20 %
    "r5": [(-6, 0), (-3.5, 1), (-1, 2), (0.5, 5), (2.5, 5), (5, 3), (8, 0)],                 # R5 %
    "bar": [(0, 1), (0.35, 2), (0.65, 4), (0.85, 5)],                                        # P (양봉일 때만)
    "atr": [(-8, 3), (0, 2), (12.5, 1), (22, 0)],                                            # ATR% 변화 %
    "vshrink": [(0.75, 3), (1.0, 2), (1.35, 1), (1.6, 0)],                                   # 거래량 비율
    "updown": [(0.9, 0), (1.1, 1), (1.3, 2)],                                                # 상승/하락 거래량
    "vt5": [(0.8, 0), (1.0, 2)],                                                             # 오늘/5일 평균
    "vt20": [(1.5, 2), (2.0, 1)],                                                            # 오늘/20일 평균 (폭증 감점)
}


def raw_features(O: pd.DataFrame, H: pd.DataFrame, L: pd.DataFrame, C: pd.DataFrame, V: pd.DataFrame,
                 dates=None) -> dict[str, pd.DataFrame]:
    """날짜×종목 넓은 표 → 원자료 지표 (모두 t 이전·당일 값만 사용). dates 를 주면 그 날짜만 남김."""
    f = {}
    f["D"] = 100 * (C / H.rolling(60, min_periods=60).max() - 1)
    c20max, c20min = C.rolling(20, min_periods=20).max(), C.rolling(20, min_periods=20).min()
    f["R20"] = 100 * (c20max / c20min - 1)
    lo_now, lo_prev = L.rolling(10, min_periods=10).min(), L.shift(10).rolling(10, min_periods=10).min()
    f["L"] = 100 * (lo_now / lo_prev - 1)
    # 최근 20일 중 '20일 최저 종가 × 1.15 이하' 에 머문 가장 긴 연속 일수
    lim = c20min * 1.15
    run = pd.DataFrame(0.0, index=C.index, columns=C.columns)
    best = run.copy()
    for k in range(19, -1, -1):
        b = (C.shift(k) <= lim).astype(float)
        run = (run + 1) * b
        best = np.maximum(best, run)
    f["RUN"] = best.where(c20min.notna())
    ma20, ma60 = C.rolling(20, min_periods=20).mean(), C.rolling(60, min_periods=60).mean()
    s20 = 100 * (ma20 / ma20.shift(5) - 1)
    f["S20"], f["A20"] = s20, s20 - s20.shift(5)
    f["S60"] = 100 * (ma60 / ma60.shift(10) - 1)
    f["G20"] = 100 * (C / ma20 - 1)
    f["R5"] = 100 * (C / C.shift(5) - 1)
    rng = H - L
    f["P"] = ((C - L) / rng).where(rng > 0)
    f["UP_BAR"] = (C > O) & (rng > 0)
    prev_c = C.shift(1)
    tr = np.maximum(rng, np.maximum((H - prev_c).abs(), (L - prev_c).abs()))
    trp = tr / C                                      # 하루 변동폭 %(1일 ATR%)
    a10, a20p = trp.rolling(10, min_periods=10).mean(), trp.shift(10).rolling(20, min_periods=20).mean()
    f["ATRCHG"] = 100 * (a10 / a20p - 1)
    v10, v20p = V.rolling(10, min_periods=10).mean(), V.shift(10).rolling(20, min_periods=20).mean()
    f["VRATIO"] = v10 / v20p.where(v20p > 0)
    up, dn = (C > prev_c), (C < prev_c)
    upv = V.where(up, 0).rolling(10, min_periods=10).sum()
    dnv = V.where(dn, 0).rolling(10, min_periods=10).sum()
    f["UPV"], f["DNV"] = upv, dnv
    f["V5"] = V / V.shift(1).rolling(5, min_periods=5).mean()      # 오늘 / 직전 5일 평균
    f["V20"] = V / V.shift(1).rolling(20, min_periods=20).mean()   # 오늘 / 직전 20일 평균
    if dates is not None:
        f = {k: v.reindex(dates) for k, v in f.items()}
    return f


def score_frame(f: dict[str, pd.DataFrame] | dict[str, pd.Series]) -> dict:
    """원자료 → 세부 점수(소수점) dict. 입력은 넓은 표(DataFrame) 또는 한 날짜 단면(Series) 모두 가능."""
    like = f["D"]
    wrap = (lambda a: pd.DataFrame(a, index=like.index, columns=like.columns)) if isinstance(like, pd.DataFrame) \
        else (lambda a: pd.Series(a, index=like.index))
    s = {}
    s["d60"] = wrap(ramp(f["D"], K["d60"]))
    s["r20"] = wrap(ramp(f["R20"], K["r20"]))
    s["low"] = wrap(ramp(f["L"], K["low"]))
    s["run"] = wrap(ramp(f["RUN"], K["run"]))
    s["s20"] = wrap(ramp(f["S20"], K["s20"]))
    s["a20"] = wrap(ramp(f["A20"], K["a20"]))
    s["s60"] = wrap(ramp(f["S60"], K["s60"]))
    s["g20"] = wrap(ramp(f["G20"], K["g20"]))
    s["r5"] = wrap(ramp(f["R5"], K["r5"]))
    bar = ramp(f["P"], K["bar"])                       # 음봉·보합·고가=저가 → 0
    s["bar"] = wrap(np.where(np.asarray(f["UP_BAR"], dtype=bool), np.nan_to_num(bar), 0.0))
    s["atr"] = wrap(ramp(f["ATRCHG"], K["atr"]))
    s["vshrink"] = wrap(ramp(f["VRATIO"], K["vshrink"]))
    upv, dnv = np.asarray(f["UPV"], dtype=float), np.asarray(f["DNV"], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        ud = ramp(upv / dnv, K["updown"])
    # 예외: 10일간 하락일 거래량 0 → 비율을 못 구함. 상승일만 있었으면 1점(중립), 둘 다 0 이면 0점
    ud = np.where(dnv == 0, np.where(upv > 0, 1.0, 0.0), ud)
    s["updown"] = wrap(np.where(np.isnan(upv) | np.isnan(dnv), np.nan, ud))
    s["vtoday"] = wrap(np.minimum(ramp(f["V5"], K["vt5"]), ramp(f["V20"], K["vt20"])))
    return s


def totals(s: dict) -> dict:
    """세부 점수 → 5개 항목 + 총점 (각 항목 배점 상한, 자료 없는 세부 항목은 0점)"""
    out = {}
    for p, (_, mx) in PARTS.items():
        if p == "news5":
            continue
        subs = [s[k].fillna(0) for k, (pp, _, _) in SUBS.items() if pp == p]
        tot = subs[0]
        for v in subs[1:]:
            tot = tot + v
        out[p] = tot.clip(upper=35) * (30 / 35) if p == "ma35" else tot.clip(upper=mx)   # 이평 전환 35 → 30
    out["news5"] = out["bottom15"] * 0 + NEWS_NEUTRAL                                  # 뉴스 5 (중립 2.5)
    t = out["bottom15"] + out["base25"] + out["ma35"] + out["rebound15"] + out["volume10"] + out["news5"]
    out["total"] = t
    return out


def score_today(f: dict[str, pd.DataFrame], date) -> pd.DataFrame:
    """한 날짜 단면: 종목별 세부·항목·총점 + 원자료 (rv_ 접두)"""
    d = pd.Timestamp(date)
    cs = {k: v.loc[d] for k, v in f.items()}
    s = score_frame(cs)
    t = totals(s)
    df = pd.DataFrame({**{k: v for k, v in s.items()}, **t})
    for k, v in cs.items():
        df["rv_" + k] = v
    return df


def rank(sc: pd.DataFrame, eligible: pd.Series, value: pd.Series, min_score: float = CANDIDATE) -> pd.DataFrame:
    """자격 있는 종목 중 min_score 이상 → 총점 ↓, ③ ↓, ② ↓, 거래대금 ↓, 코드 순"""
    o = sc[eligible.astype(bool).reindex(sc.index, fill_value=False) & (sc["total"] >= min_score)].copy()
    o["_v"] = value.reindex(o.index).fillna(0)
    o["_c"] = o.index
    o = o.sort_values(["total", "ma35", "base25", "_v", "_c"], ascending=[False, False, False, False, True])
    return o.drop(columns=["_v", "_c"])


def wide(ohlcv: pd.DataFrame, days: int = 120) -> tuple[pd.DataFrame, ...]:
    """긴 표(date, code, open, high, low, close, volume) → 최근 days 거래일의 넓은 표 5개"""
    dts = np.sort(ohlcv["date"].unique())[-days:]
    oh = ohlcv[ohlcv["date"].isin(dts)]
    out = []
    for col in ("open", "high", "low", "close", "volume"):
        w = oh.pivot(index="date", columns="code", values=col).astype(float)
        out.append(w.where(w > 0) if col != "volume" else w)
    return tuple(out)
