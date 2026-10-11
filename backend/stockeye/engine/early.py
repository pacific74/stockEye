"""상승초기형 V1 (실험 탭 — V3B 고정 전략·추세전환과 별개, 매매 규칙 없음)

종가가 20일선을 회복하고 단기 상승 흐름이 막 시작되는 종목을 100점으로 평가한다.
  ① 단기 추세 회복 25  ② 상승 모멘텀 20  ③ 중기 추세 개선 20  ④ 거래량 확인 20  ⑤ 과열·변동성 관리 15
- 선정일 종가까지 확정된 데이터만 사용 (t = 선정일).
- 점수는 문서의 구간표를 따르되 기준점 사이를 직선으로 이어 소수점까지 매긴다 (각 항목 배점 상한).
- 진입 제외: 종가 ≤ MA20 · MA20 5일 변화율 ≤ 0 · MA60 10일 변화율 < -1.5% · 5일 수익률 < -1% 또는 > 15%
            · 20일 수익률 > 25% · 20일 평균 거래대금 < 5억 · 기존 위험 필터(1차 필터 + 매수 차단) 미통과
- 80점 이상 우선 관찰 · 70~79 관찰 후보 · 60~69 보류 목록 · 60 미만 선별 제외
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .reversal import ramp

VERSION = "UP-1.1"
PRIORITY, WATCH, HOLD = 80.0, 70.0, 60.0
PARTS = {"trend25": ("단기 추세 회복", 25), "mom20": ("상승 모멘텀", 20), "mid20": ("중기 추세 개선", 20),
         "vol20": ("거래량 확인", 20), "risk15": ("과열·변동성·뉴스", 15)}
# 뉴스 (2026-10-12): 네이버 뉴스 최근 3일 제목 → 호재 5 · 중립/기사 없음 2.5 · 악재 0 (analysis.news_flags 가 저녁 배치에서 조정).
#   과거 뉴스는 없으므로 점수 계산·백테스트에서는 모두 중립 2.5
NEWS_NEUTRAL = 2.5

SUBS = {  # 세부 항목: (상위 항목, 이름, 배점)
    "g20": ("trend25", "종가와 20일선", 5), "s20": ("trend25", "20일선 기울기", 10), "ma5": ("trend25", "5일선 > 20일선", 10),
    "r5": ("mom20", "5일 수익률", 8), "r20": ("mom20", "20일 수익률", 7), "b20": ("mom20", "20일 저점 대비 반등", 5),
    "s60": ("mid20", "60일선 기울기", 10), "dg": ("mid20", "20·60일선 간격 변화", 10),
    "v5": ("vol20", "5일/20일 거래량", 5), "updown": ("vol20", "상승일/하락일 거래량", 5),
    "vnow": ("vol20", "오늘/20일 거래량", 5), "value": ("vol20", "20일 평균 거래대금", 5),
    "atr": ("risk15", "ATR 변동성", 5), "rsi": ("risk15", "RSI(14)", 5), "gap": ("risk15", "20일선 이격도", 5),
}
RULES_TEXT = [
    "① 종가가 20일선 바로 위(1~3% 만점), 20일선이 오르기 시작(5일 +0.7~1.5% 만점), 5일선이 20일선 위 + 5일선 상승",
    "② 5일 +2~4% · 20일 +7~12% · 20일 저점 대비 +5~8% 반등이 만점 (너무 크게 오르면 감점)",
    "③ 60일선이 오르기 시작(10일 +0.5~1.5% 만점), 20일선이 60일선 대비 점점 강해지는 중",
    "④ 거래량이 적당히 늘고(5일/20일 1.2~1.5배), 상승일 거래량이 하락일보다 많고, 거래대금이 클수록 높음",
    "⑤ 하루 변동폭(ATR) 2~4% · RSI 50~60 · 20일선과 가까울수록 높음 (과열은 0점)",
    "제외: 20일선 아래 · 20일선 하락 · 60일선 10일 -1.5% 미만 · 5일 -1% 미만/+15% 초과 · 20일 +25% 초과 · 거래대금 5억 미만 · 위험 종목",
    "점수는 기준 사이를 직선으로 이어 소수점까지 · 80↑ 우선 관찰 · 70~79 관찰 후보 · 60~69 보류",
    "매매 규칙 없음 (관찰용) — V3 기준 전략과 별개",
]

# 기준점: 문서 구간표 (구간 가운데 = 그 구간 점수, 만점 구간은 평평). 제외 구간은 별도 필터로 처리
K = {
    "g20": [(0, 2), (0.5, 3), (1.5, 5), (2.5, 5), (4, 4), (6, 2)],                      # 종가/MA20 %
    "s20": [(0, 2), (0.15, 4), (0.5, 7), (0.85, 10), (1.5, 10), (2.5, 7)],              # S20 %
    "ma5s": [(0, 0), (0.3, 4)],                                                          # MA5 1일 기울기 % (MA5>MA20 일 때 +)
    "r5": [(-1, 1), (-0.5, 1), (1, 4), (2.5, 8), (3.5, 8), (5, 6), (7, 4), (10, 2), (13.5, 1), (15, 0.5)],
    "r20": [(-2, 0), (1.5, 2), (5, 4), (8.5, 7), (11, 7), (16, 5), (22.5, 2), (25, 1.5)],
    "b20": [(0, 0.5), (1, 1), (3.5, 3), (5.5, 5), (7.5, 5), (10, 3), (14, 0)],
    "s60": [(-1.5, 2.5), (-1, 3), (-0.25, 5), (0.25, 7), (0.75, 10), (1.5, 10), (2.5, 8)],
    "dg": [(-0.7, 0), (-0.3, 2), (0, 4), (0.3, 7), (0.7, 10)],                          # %p
    "v5": [(0.4, 0), (0.65, 1), (0.9, 2), (1.1, 3), (1.25, 5), (1.45, 5), (1.75, 3), (2.3, 1)],
    "updown": [(0.7, 0), (0.9, 1), (1.1, 3), (1.25, 5), (1.5, 5), (2.0, 4)],
    "vnow": [(0.4, 0), (0.65, 1), (0.9, 3), (1.05, 5), (1.45, 5), (2.0, 3), (3.0, 1)],
    "value": [(np.log10(5), 1), (1, 2), (np.log10(20), 3), (np.log10(50), 4), (2, 5)],  # log10(억원)
    "atr": [(0.5, 2), (1.5, 4), (2.2, 5), (3.8, 5), (4.5, 3), (6, 1), (7.5, 0)],        # ATR14/종가 %
    "rsi": [(38, 0), (42.5, 1), (47.5, 3), (51, 5), (59, 5), (62.5, 4), (67.5, 2), (72, 0)],
    "gap": [(0, 5), (1, 5), (2, 4), (4, 3), (6.5, 1), (9, 0)],                          # 종가/MA20 %
}
EXCLUDE = {"below20": "20일선 아래", "ma20_down": "20일선 하락", "ma60_down": "60일선 급하락",
           "r5_low": "5일 -1% 미만", "r5_hot": "5일 +15% 초과", "r20_hot": "20일 +25% 초과", "value_low": "거래대금 5억 미만"}


def _wilder(s: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def raw_features(O, H, L, C, V, VAL=None, dates=None) -> dict[str, pd.DataFrame]:
    """날짜×종목 넓은 표 → 원자료 (t 이전·당일 값만). VAL = 거래대금 (없으면 종가×거래량)"""
    f = {}
    ma5, ma20, ma60 = (C.rolling(n, min_periods=n).mean() for n in (5, 20, 60))
    f["G20"] = 100 * (C / ma20 - 1)
    f["S20"] = 100 * (ma20 / ma20.shift(5) - 1)
    f["MA5_GT"] = ma5 > ma20
    f["S5"] = 100 * (ma5 / ma5.shift(1) - 1)
    f["R5"] = 100 * (C / C.shift(5) - 1)
    f["R20"] = 100 * (C / C.shift(20) - 1)
    f["B20"] = 100 * (C / L.rolling(20, min_periods=20).min() - 1)
    f["S60"] = 100 * (ma60 / ma60.shift(10) - 1)
    g = 100 * (ma20 / ma60 - 1)
    f["GAP2060"], f["DG"] = g, g - g.shift(5)
    v20 = V.rolling(20, min_periods=20).mean()
    f["V5R"] = V.rolling(5, min_periods=5).mean() / v20.where(v20 > 0)
    prev_c = C.shift(1)
    f["UPV"] = V.where(C > prev_c, 0).rolling(10, min_periods=10).sum()
    f["DNV"] = V.where(C < prev_c, 0).rolling(10, min_periods=10).sum()
    vp20 = V.shift(1).rolling(20, min_periods=20).mean()
    f["VNOW"] = V / vp20.where(vp20 > 0)
    val = VAL if VAL is not None else C * V
    f["VAL20"] = val.rolling(20, min_periods=20).mean() / 1e8                 # 억원
    tr = np.maximum(H - L, np.maximum((H - prev_c).abs(), (L - prev_c).abs()))
    f["ATR"] = 100 * _wilder(tr) / C
    d = C.diff()
    ag, al = _wilder(d.clip(lower=0)), _wilder(-d.clip(upper=0))
    f["RSI"] = 100 - 100 / (1 + ag / al.where(al > 0))
    f["RSI"] = f["RSI"].where(al > 0, 100.0).where(ag.notna())
    if dates is not None:
        f = {k: v.reindex(dates) for k, v in f.items()}
    return f


def score_frame(f: dict) -> dict:
    """원자료 → 세부 점수(소수점). DataFrame(날짜×종목) / Series(한 날짜) 모두 가능"""
    like = f["G20"]
    wrap = (lambda a: pd.DataFrame(a, index=like.index, columns=like.columns)) if isinstance(like, pd.DataFrame) \
        else (lambda a: pd.Series(a, index=like.index))
    a = lambda k: np.asarray(f[k], dtype=float)  # noqa: E731
    s = {"g20": wrap(ramp(a("G20"), K["g20"])), "s20": wrap(ramp(a("S20"), K["s20"]))}
    gt = np.asarray(f["MA5_GT"], dtype=bool)
    s["ma5"] = wrap(np.where(gt, 6 + np.nan_to_num(ramp(a("S5"), K["ma5s"])), 0.0))
    s["r5"] = wrap(ramp(a("R5"), K["r5"]))
    s["r20"] = wrap(ramp(a("R20"), K["r20"]))
    s["b20"] = wrap(ramp(a("B20"), K["b20"]))
    s["s60"] = wrap(ramp(a("S60"), K["s60"]))
    s["dg"] = wrap(ramp(a("DG"), K["dg"]))
    s["v5"] = wrap(ramp(a("V5R"), K["v5"]))
    upv, dnv = a("UPV"), a("DNV")
    with np.errstate(divide="ignore", invalid="ignore"):
        ud = ramp(upv / dnv, K["updown"])
    # 예외: 10일간 하락일 거래량 0 → 비율을 무한대로 보지 않음. 상승일만 있었으면 3점(중간), 둘 다 0 이면 0점
    ud = np.where(dnv == 0, np.where(upv > 0, 3.0, 0.0), ud)
    s["updown"] = wrap(np.where(np.isnan(upv) | np.isnan(dnv), np.nan, ud))
    s["vnow"] = wrap(ramp(a("VNOW"), K["vnow"]))
    with np.errstate(divide="ignore", invalid="ignore"):
        s["value"] = wrap(ramp(np.log10(np.where(a("VAL20") > 0, a("VAL20"), np.nan)), K["value"]))
    s["atr"] = wrap(ramp(a("ATR"), K["atr"]))
    s["rsi"] = wrap(ramp(a("RSI"), K["rsi"]))
    s["gap"] = wrap(ramp(a("G20"), K["gap"]))
    return s


def totals(s: dict) -> dict:
    out = {}
    for p, (_, mx) in PARTS.items():
        tot = None
        for k, (pp, _, _) in SUBS.items():
            if pp == p:
                tot = s[k].fillna(0) if tot is None else tot + s[k].fillna(0)
        out[p] = tot.clip(upper=mx)
    out["risk15"] = out["risk15"] * (10 / 15) + NEWS_NEUTRAL      # 과열·변동성 15 → 10 + 뉴스 5
    out["total"] = sum(out[p] for p in PARTS)
    return out


def exclusions(f: dict) -> dict:
    """진입 제외 조건 (True = 제외). 자료가 없으면 제외"""
    nn = lambda k: pd.notna(f[k])  # noqa: E731
    return {"below20": ~(nn("G20") & (f["G20"] > 0)),
            "ma20_down": ~(nn("S20") & (f["S20"] > 0)),
            "ma60_down": ~(nn("S60") & (f["S60"] >= -1.5)),
            "r5_low": nn("R5") & (f["R5"] < -1),
            "r5_hot": nn("R5") & (f["R5"] > 15),
            "r20_hot": nn("R20") & (f["R20"] > 25),
            "value_low": ~(nn("VAL20") & (f["VAL20"] >= 5))}


def score_today(f: dict, date) -> pd.DataFrame:
    d = pd.Timestamp(date)
    cs = {k: v.loc[d] for k, v in f.items()}
    s = score_frame(cs)
    t = totals(s)
    ex = exclusions(cs)
    df = pd.DataFrame({**s, **t})
    for k, v in ex.items():
        df["ex_" + k] = v.astype(bool)
    df["excluded"] = df[["ex_" + k for k in EXCLUDE]].any(axis=1)
    for k, v in cs.items():
        df["rv_" + k] = v
    return df


def label(total: float) -> str:
    return "우선 관찰" if total >= PRIORITY else "관찰 후보" if total >= WATCH else "보류" if total >= HOLD else "선별 제외"


def rank(sc: pd.DataFrame, ok: pd.Series, value: pd.Series, min_score: float = HOLD) -> pd.DataFrame:
    """제외 조건 통과 + min_score 이상 → 총점 ↓, ① ↓, ② ↓, 거래대금 ↓, 코드"""
    o = sc[ok.astype(bool).reindex(sc.index, fill_value=False) & (sc["total"] >= min_score)].copy()
    o["_v"] = value.reindex(o.index).fillna(0)
    o["_c"] = o.index
    o = o.sort_values(["total", "trend25", "mom20", "_v", "_c"], ascending=[False, False, False, False, True])
    return o.drop(columns=["_v", "_c"])


def wide(ohlcv: pd.DataFrame, days: int = 120):
    """긴 표 → 최근 days 거래일의 O,H,L,C,V,VAL 넓은 표 (VAL 은 value 열이 있을 때)"""
    dts = np.sort(ohlcv["date"].unique())[-days:]
    oh = ohlcv[ohlcv["date"].isin(dts)]
    out = []
    for col in ("open", "high", "low", "close", "volume", "value"):
        if col not in oh:
            out.append(None)
            continue
        w = oh.pivot(index="date", columns="code", values=col).astype(float)
        out.append(w.where(w > 0) if col in ("open", "high", "low", "close") else w)
    return tuple(out)
