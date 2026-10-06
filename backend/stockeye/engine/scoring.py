"""종목별 100점 점수.

각 항목은 0~1 의 '달성률'을 계산하고 가중치를 곱한다.
데이터가 없는 항목(예: 프로그램 매매, 공시 데이터 미수집)은 NaN → 나머지 가중치로 100점 환산.
→ 어떤 항목이 빠졌는지 missing 에 기록해서 앱에 표시한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from .news import news_fraction


def _clip01(v: float) -> float:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return float("nan")
    return max(0.0, min(1.0, float(v)))


def _lin(v, lo, hi):
    """lo→0, hi→1 선형"""
    if v is None or pd.isna(v):
        return float("nan")
    return _clip01((v - lo) / (hi - lo))


def _ok(v) -> bool:
    return v is not None and not pd.isna(v)


def _weighted(parts: list[tuple[float, float]]) -> float:
    """[(가중치, 값)] 중 값이 있는 것만 가중평균."""
    av = [(w, v) for w, v in parts if _ok(v)]
    if not av:
        return float("nan")
    return sum(w * v for w, v in av) / sum(w for w, _ in av)


@dataclass
class ScoreResult:
    code: str
    total: float
    parts: dict[str, float]            # 항목별 획득 점수 (가중치 기준)
    max_parts: dict[str, float]        # 항목별 만점
    missing: list[str]
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def stars(self) -> int:
        s = self.total
        return 5 if s >= 90 else 4 if s >= 80 else 3 if s >= 70 else 2 if s >= 60 else 1


def score_row(code: str, r: pd.Series, weights: dict, titles: list[str] | None) -> ScoreResult:
    reasons, warns = [], []
    g = r.get

    # ---- 추세 ----
    trend = _weighted([
        (0.25, float(g("sma5") > g("sma20")) if _ok(g("sma5")) else float("nan")),
        (0.25, float(g("sma20_slope") > 0) if _ok(g("sma20_slope")) else float("nan")),
        (0.20, float(g("close") > g("sma20")) if _ok(g("sma20")) else float("nan")),
        (0.15, float(g("close") > g("sma60")) if _ok(g("sma60")) else float("nan")),
        (0.15, float(g("sma20") > g("sma60")) if _ok(g("sma60")) else float("nan")),
    ])
    if _ok(g("sma20_slope")) and g("sma20_slope") > 0:
        reasons.append("20일 이동평균선 상승")
    if _ok(g("sma60")) and g("close") > g("sma60"):
        reasons.append("60일선 위")
    if _ok(g("sma5")) and g("sma5") > g("sma20"):
        reasons.append("5일선 > 20일선 (정배열 초입)")

    # ---- 거래량 ----
    vr = g("vol_ratio")
    volume = _lin(vr, 1.0, 3.0)
    if _ok(vr) and vr >= 1.5:
        reasons.append(f"거래량 {vr:.1f}배 증가")

    # ---- 거래대금 ----
    vratio, vma = g("value_ratio"), g("value_ma20")
    tv = _weighted([
        (0.6, _lin(vratio, 1.0, 2.0)),
        (0.4, _lin(math.log10(vma) if _ok(vma) and vma > 0 else float("nan"), math.log10(2e9), math.log10(1e11))),
    ])
    if _ok(vratio) and vratio >= 1.3:
        reasons.append(f"거래대금 증가 ({vratio:.1f}배)")

    # ---- 수급 ----
    turnover5 = (vma or 0) * 5
    def inten(x):  # 5일 순매수 / 5일 거래대금
        return _lin(x / turnover5, 0, 0.05) if _ok(x) and turnover5 > 0 else float("nan")
    f5, i5, p5, ind5 = g("foreign_net5"), g("institution_net5"), g("program_net5"), g("individual_net5")
    fst = g("foreign_streak")
    supply = _weighted([
        (0.30, inten(f5)),
        (0.10, _lin(fst, 0, 5)),
        (0.25, inten(i5)),
        (0.15, inten(p5)),
        (0.10, float(ind5 < 0) if _ok(ind5) else float("nan")),
        (0.10, float(_ok(f5) and _ok(i5) and f5 > 0 and i5 > 0) if _ok(f5) else float("nan")),
    ])
    if _ok(fst) and fst >= 2:
        reasons.append(f"외국인 {int(fst)}일 연속 순매수")
    elif _ok(f5) and f5 > 0:
        reasons.append("외국인 5일 순매수")
    if _ok(i5) and i5 > 0:
        reasons.append("기관 5일 순매수")
    if _ok(p5) and p5 > 0:
        reasons.append("프로그램 5일 순매수")
    if _ok(f5) and f5 < 0 and _ok(i5) and i5 < 0:
        warns.append("외국인·기관 동반 순매도")

    # ---- 돌파/가격위치 ----
    c, h20, h60, h250, bbp = g("close"), g("high20_prev"), g("high60_prev"), g("high250"), g("bb_pos")
    breakout = _weighted([
        (0.40, float(c > h20) if _ok(h20) else float("nan")),
        (0.20, float(c > h60) if _ok(h60) else float("nan")),
        (0.20, _lin(c / h250, 0.80, 1.0) if _ok(h250) else float("nan")),
        (0.20, (0.5 if bbp > 1.05 else _lin(bbp, 0.5, 1.0)) if _ok(bbp) else float("nan")),
    ])
    if _ok(h20) and c > h20:
        reasons.append("최근 20일 고점 돌파")
    if _ok(h60) and c > h60:
        reasons.append("최근 60일 고점 돌파")

    # ---- 변동성 ----
    ap = g("atr_pct")
    if not _ok(ap):
        volat = float("nan")
    elif 0.02 <= ap <= 0.06:
        volat = 1.0
    elif ap < 0.02:
        volat = _lin(ap, 0.01, 0.02)
    else:
        volat = 1 - _lin(ap, 0.06, 0.10)
    if _ok(ap) and ap > 0.07:
        warns.append(f"변동성 큼 (ATR {ap * 100:.1f}%)")

    # ---- 재무 ----
    eps, per, pbr = g("eps"), g("per"), g("pbr")
    fin = _weighted([
        (0.5, float(eps > 0) if _ok(eps) else float("nan")),
        (0.25, float(0 < per < 30) if _ok(per) else float("nan")),
        (0.25, float(0 < pbr < 5) if _ok(pbr) else float("nan")),
    ])
    if _ok(eps) and eps <= 0:
        warns.append("적자 기업 (EPS ≤ 0)")

    # ---- 뉴스/공시 ----
    if titles is None:
        news = float("nan")
    else:
        news, pos, neg = news_fraction(titles)
        reasons += [f"공시: {t}" for t in pos[:2]]
        warns += [f"악재성 공시: {t}" for t in neg[:2]]

    # ---- 공통 경고 ----
    rsi = g("rsi14")
    if _ok(rsi) and rsi >= 70:
        warns.append(f"RSI 과열 ({rsi:.0f})")
    r5 = g("ret5")
    if _ok(r5) and r5 >= 0.15:
        warns.append(f"단기 상승폭 큼 (5일 +{r5 * 100:.0f}%)")
    if _ok(g("sma20")) and c / g("sma20") > 1.15:
        warns.append(f"20일선 이격 과다 (+{(c / g('sma20') - 1) * 100:.0f}%)")
    if _ok(vma) and vma < 5e9:
        warns.append("거래대금 작음 → 슬리피지 주의")
    if _ok(g("macd")) and g("macd") > g("macd_signal"):
        reasons.append("MACD 시그널 상향")

    fr = {"trend": trend, "volume": volume, "trading_value": tv, "supply": supply,
          "breakout": breakout, "volatility": volat, "financial": fin, "news": news}
    parts, missing = {}, []
    for k, w in weights.items():
        v = fr.get(k, float("nan"))
        if _ok(v):
            parts[k] = round(w * v, 1)
        else:
            missing.append(k)
    avail_w = sum(w for k, w in weights.items() if k not in missing)
    total = 100 * sum(parts.values()) / avail_w if avail_w else 0.0
    return ScoreResult(code, round(total, 1), parts, dict(weights), missing, reasons, warns)


LABELS = {"trend": "추세", "volume": "거래량", "trading_value": "거래대금", "supply": "수급",
          "breakout": "돌파/가격위치", "volatility": "변동성", "financial": "재무", "news": "뉴스/공시"}
