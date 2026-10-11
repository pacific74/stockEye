"""상한가 파동 매매전략 V1 — '상파' 탭 (관찰용, 매매 규칙 없음)

  유형 A      : 당일 고가가 상한가 이상 (장중 도달)        → 'A 상한가 도달'
  유형 A-종가 : 당일 종가가 상한가                         → 'A 상한가 종가'
  유형 B      : 전일 종가가 상한가 AND 당일 거래량 < 전일 거래량 AND 당일 종가 < 당일 시가
                → '상한가 후 거래량 감소 음봉' + B1 얕은 조정 / B2 보통 조정 / B3 깊은 조정·훼손 / B4 거래량 급감·작은 음봉

상한가 가격: 기준가(전일 종가) × 1.3 을 그 가격의 호가단위로 내림 (KRX 가격제한 계산 방식).
  권리락·액면변경 등으로 기준가가 전일 종가와 다른 날은 계산이 틀릴 수 있어, KRX 등락률(chg_pct) ≥ 29.5% 도
  상한가로 함께 인정한다 (둘 중 하나).
계산식
  거래량 감소율 = 100 × (1 − 당일 거래량 ÷ 전일 거래량)
  당일 등락률   = 100 × (당일 종가 ÷ 전일 종가 − 1)
  음봉 몸통률   = 100 × (당일 시가 − 당일 종가) ÷ 전일 종가
  종가 위치     = (종가 − 저가) ÷ (고가 − 저가)   (고가 = 저가면 계산 안 함)
전일 거래량 0·결측 → '데이터 확인'. 주요 지지선 = 상한가 당일 저가.
B1~B4 수치는 문서의 초기 실험 기준 (검증된 수익 공식 아님). B3 조건이 있으면 B3 우선.

후보 점수 100 (정렬용 보조 지표 — 이 점수만으로 매수하지 않음)
  상한가 발생 특성 20 · 거래량 감소의 질 25 · 조정 품질 20 · 유동성 15 · 추세·상대강도 10 · 공시·이벤트 위험 10
  유형 A 는 '거래량 감소의 질' 대신 상한가 당일 거래량 강도, '조정 품질' 대신 종가 강도로 매긴다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .reversal import ramp
from .trade_plan import tick_size

VERSION = "UL-1.1"
PARTS = {"limit20": ("상한가 특성", 20), "vol25": ("거래량 질", 25), "pull20": ("조정 품질", 20),
         "liq15": ("유동성", 15), "trend10": ("추세·강도", 10), "risk10": ("공시·뉴스", 10)}
# 뉴스 (2026-10-12): 네이버 뉴스 최근 3일 제목 → 호재 5 · 중립/기사 없음 2.5 · 악재 0 (analysis.news_flags 가 저녁 배치에서 조정).
#   과거 뉴스는 없으므로 점수 계산·백테스트에서는 모두 중립 2.5
NEWS_NEUTRAL = 2.5

RULES_TEXT = [
    "A: 오늘 고가가 상한가 이상(장중 도달) · A-종가: 종가까지 상한가 유지",
    "B: 어제 종가 상한가 + 오늘 거래량 < 어제 + 오늘 음봉(종가 < 시가)",
    "B1 얕은 조정(거래량 -30%↑·등락 -5% 이상·상한가일 저가 지지) · B2 보통 조정 · B3 깊은 조정/지지 이탈(우선) · "
    "B4 거래량 반 이하·작은 음봉·종가 위치 0.5↑",
    "점수 100 = 상한가 특성 20 · 거래량 질 25 · 조정 품질 20 · 유동성 15 · 추세 10 · 공시 위험 10 (정렬용, 매수 신호 아님)",
    "상한가 = 전일 종가 × 1.3 을 호가단위로 내림 (또는 KRX 등락률 29.5% 이상)",
]


def limit_price(base: float) -> float:
    """기준가 → 상한가 (기준가 × 1.3 을 그 가격대 호가단위로 내림)"""
    if not base or base != base or base <= 0:
        return np.nan
    raw = base * 1.3
    t = tick_size(raw)
    return float(np.floor(raw / t + 1e-9) * t)


def _limit_wide(prev_c: pd.DataFrame) -> pd.DataFrame:
    return prev_c.apply(lambda col: col.map(limit_price))


def features(O, H, L, C, V, VAL, CHG=None, dates=None) -> dict:
    """넓은 표(날짜×종목) → 상파 원자료. CHG = KRX 등락률(%) 넓은 표 (있으면 상한가 판정에 같이 씀)"""
    pc = C.shift(1)
    lim = _limit_wide(pc if dates is None else pc.reindex(pc.index))
    hit_px = (H >= lim - 1e-9)
    close_px = (C >= lim - 1e-9)
    if CHG is not None:
        close_lim = close_px | (CHG >= 29.5)
        reach = hit_px | close_lim
    else:
        close_lim, reach = close_px, hit_px
    f = {"LIMIT": lim, "REACH": reach & C.notna(), "CLOSE_LIMIT": close_lim & C.notna()}
    f["PREV_CLOSE_LIMIT"] = f["CLOSE_LIMIT"].shift(1, fill_value=False).astype(bool)
    pv = V.shift(1)
    f["VDROP"] = 100 * (1 - V / pv.where(pv > 0))
    f["CHG"] = 100 * (C / pc - 1)
    f["BODY"] = 100 * (O - C) / pc
    rng = H - L
    f["POS"] = ((C - L) / rng).where(rng > 0)
    f["PREV_POS"] = f["POS"].shift(1)
    f["PREV_LOW"] = L.shift(1)                                # 상한가 당일 저가 (유형 B 의 지지선)
    f["SUPPORT_OK"] = C >= f["PREV_LOW"]
    val = VAL if VAL is not None else C * V
    v20 = val.shift(1).rolling(20, min_periods=10).mean()
    f["VAL20"] = v20 / 1e8                                    # 억원 (오늘 제외 20일 평균)
    f["VAL_TODAY"] = val / 1e8
    f["PREV_VAL"] = val.shift(1) / 1e8
    f["VAL_KEEP"] = val / v20.where(v20 > 0)                  # 오늘 거래대금 / 평소
    vv20 = V.shift(1).rolling(20, min_periods=10).mean()
    f["VOL_SURGE"] = V / vv20.where(vv20 > 0)                 # 유형 A: 오늘 거래량 / 평소
    ma20, ma60 = C.rolling(20, min_periods=20).mean(), C.rolling(60, min_periods=60).mean()
    f["ABOVE20"] = C > ma20
    f["MA20_UP"] = ma20 > ma20.shift(5)
    f["MA60_UP"] = ma60 > ma60.shift(10)
    f["RET20"] = 100 * (C / C.shift(20) - 1)
    f["PV0"] = (pv <= 0) | pv.isna()
    f["TYPE_B"] = f["PREV_CLOSE_LIMIT"] & (V < pv) & (C < O) & ~f["PV0"]
    if dates is not None:
        f = {k: v.reindex(dates) for k, v in f.items()}
    return f


def classify(r) -> tuple[str, list[str]]:
    """한 종목 단면(dict/Series) → (유형, 태그들)"""
    g = r.get
    tags = []
    if bool(g("TYPE_B")):
        chg, vd, body, pos = g("CHG"), g("VDROP"), g("BODY"), g("POS")
        sup = bool(g("SUPPORT_OK"))
        b3 = (chg is not None and chg < -10) or not sup
        if b3:
            tags.append("B3 깊은 조정·지지 이탈")
        elif vd is not None and vd >= 30 and chg >= -5:
            tags.append("B1 얕은 조정")
        elif vd is not None and vd >= 10 and chg >= -10:
            tags.append("B2 보통 조정")
        else:
            tags.append("B2 보통 조정")
        if vd is not None and vd >= 50 and body is not None and body <= 3 and pos == pos and pos is not None and pos >= 0.5:
            tags.append("B4 거래량 급감·작은 음봉")
        return "B", tags
    if bool(g("CLOSE_LIMIT")):
        return "A-종가", ["상한가 종가"]
    if bool(g("REACH")):
        return "A", ["상한가 도달 (종가 미유지)"]
    return "", []


def score_row(r, news: float | None = None, has_news: bool = True) -> dict:
    """후보 점수 (항목별 소수점). 유형 A 와 B 는 일부 항목 기준이 다름"""
    g = lambda k: r.get(k)  # noqa: E731
    ok = lambda v: v is not None and v == v  # noqa: E731
    typ, tags = classify(r)
    s = {}
    if typ == "B":
        lim_close = 12.0                                    # 어제 종가 상한가 (유형 B 정의상 항상)
        pp = g("PREV_POS")
        s["limit20"] = lim_close + (4 * pp if ok(pp) else 2) + float(ramp([np.log10(max(g("PREV_VAL") or 0.01, 0.01))],
                                                                         [(1, 0), (np.log10(300), 4)])[0])
        vd = g("VDROP")
        vq = float(ramp([vd], [(0, 2), (10, 6), (30, 15), (50, 20), (70, 20), (90, 12)])[0]) if ok(vd) else 0
        vk = g("VAL_KEEP")
        vq += float(ramp([vk], [(0.5, 0), (1.0, 3), (2.0, 5)])[0]) if ok(vk) else 0
        s["vol25"] = vq
        body, pos = g("BODY"), g("POS")
        pq = float(ramp([body], [(0, 8), (3, 6), (6, 2), (8, 0)])[0]) if ok(body) else 3
        pq += 6 * pos if ok(pos) else 3
        pq += 6 if bool(g("SUPPORT_OK")) else 0
        s["pull20"] = pq
    elif typ in ("A", "A-종가"):
        pos = g("POS")
        s["limit20"] = (12 if typ == "A-종가" else 5) + (4 * pos if ok(pos) else 4) + float(
            ramp([np.log10(max(g("VAL_TODAY") or 0.01, 0.01))], [(1, 0), (np.log10(300), 4)])[0])
        vs = g("VOL_SURGE")
        s["vol25"] = float(ramp([vs], [(1, 0), (3, 10), (6, 18), (10, 25)])[0]) if ok(vs) else 0
        s["pull20"] = (10 if typ == "A-종가" else 3) + (10 * pos if ok(pos) else 5)
    else:
        return {"type": "", "tags": [], "total": 0.0}
    v20 = g("VAL20")
    s["liq15"] = float(ramp([np.log10(v20)], [(np.log10(5), 3), (1, 6), (np.log10(20), 9), (np.log10(50), 12), (2, 15)])[0]) \
        if ok(v20) and v20 > 0 else 0
    s["trend10"] = 3 * bool(g("ABOVE20")) + 3 * bool(g("MA20_UP")) + 2 * bool(g("MA60_UP")) + (
        2 if ok(g("RET20")) and 0 < g("RET20") <= 80 else 0)
    if not has_news or news is None or news != news:
        disc = 7.0                                          # 공시 정보 미확인 → 중립
    else:
        disc = 10.0 if news >= 7 else max(0.0, 10 * news / 7)
    s["risk10"] = disc * 0.5 + NEWS_NEUTRAL                 # 공시 5 + 뉴스 5 (중립 2.5)
    out = {k: round(min(float(v), PARTS[k][1]), 2) for k, v in s.items()}
    out["total"] = round(sum(out.values()), 1)
    out["type"], out["tags"] = typ, tags
    return out


def warnings_of(r, market_weak: bool = False) -> list[str]:
    g = lambda k: r.get(k)  # noqa: E731
    ok = lambda v: v is not None and v == v  # noqa: E731
    w = []
    if ok(g("VAL20")) and g("VAL20") < 10:
        w.append("유동성 부족 (20일 평균 거래대금 10억 미만)")
    if (ok(g("BODY")) and g("BODY") >= 6) or (ok(g("POS")) and g("POS") <= 0.2 and g("TYPE_B")):
        w.append("큰 음봉·저가 마감 — 매도 압력")
    if g("TYPE_B") and not bool(g("SUPPORT_OK")):
        w.append("상한가 당일 저가 이탈")
    if ok(g("RET20")) and g("RET20") > 80:
        w.append(f"20일 +{g('RET20'):.0f}% 급등 — 추격 위험")
    if bool(g("PV0")) and g("PREV_CLOSE_LIMIT"):
        w.append("데이터 확인 (전일 거래량 0·결측)")
    if market_weak:
        w.append("시장 약세 — 개별 신호가 무효화될 수 있음")
    return w
