"""상한가 예비 (LP-0.1, 2026-10-16) — 상한가포착(+20% 이상) 전에 '상한가 갈 만한' 급등 초입 종목을 미리 표시

사용자 결정: 1단계는 **표시 + 기록만** (알림 없음). 2~3주 기록으로 상한가 도달·종가 잠김 비율을 보고 기준을 다듬는다.
⚠ 기준 숫자는 모두 처음 가설 — 검증 전.

대상 (기본 조건 모두)
  · 보통주 · 오늘 +10% 이상 +20% 미만 (+20% 이상은 기존 상한가포착 단계)
  · 09:05 ~ 14:30 (그 뒤로는 상한가까지 갈 시간이 짧음)
  · 누적 거래대금: 11시 전 30억 이상 · 그 뒤 50억 이상
  · 현재가가 당일 고가에서 1.5% 이내 (밀리는 중이 아니라 고점을 다시 뚫는 중)
점수 100 (60 이상 '상한가 예비', 그 아래는 '관찰')
  거래대금 가속 25  최근 5분 1분 평균 거래대금 ÷ 그 앞 20분 평균: 1배 0 · 2배 12.5 · 3배↑ 25
  고가 근접     15  고가 대비 0% 15 · −1.5% 0
  VWAP 위       15  VWAP 대비 0% 0 · +3%↑ 15 (아래면 0)
  매수잔량 우위  15  총 매수잔량 ÷ 총 매도잔량 0.8 0 · 1.5 7.5 · 2.5↑ 15 (호가 없으면 7.5)
  업종 동반     10  상한가포착과 같은 방식 (1시간마다 업종 강도 · 없으면 5)
  재료          10  상한가포착 재료 점수(15점)를 10점으로 환산 (뉴스 없음·중립 3)
  상한가 성향   10  최근 60일 상한가(종가 +29.5%↑) 이력 있음 10 · 없음 4 (테마성 종목은 다시 갈 확률이 높다는 가설)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .daytrade import ramp

VERSION = "LP-0.1"
PRE_MIN, PRE_MAX = 10.0, 20.0
START, END = "09:05", "14:30"
VALUE_AM, VALUE_PM = 30e8, 50e8           # 11시 전 · 뒤 누적 거래대금 기준
NEAR_HIGH = 1.5                           # 고가 대비 % 이내
SHOW_SCORE = 60.0
PARTS = {"accel25": ("거래대금 가속", 25), "high15": ("고가 근접", 15), "vwap15": ("VWAP 위", 15),
         "book15": ("매수잔량 우위", 15), "sec10": ("업종 동반", 10), "news10": ("재료", 10), "hist10": ("상한가 성향", 10)}


def in_window(hm: str) -> bool:
    return START <= hm <= END


def min_value(hm: str) -> float:
    return VALUE_AM if hm < "11:00" else VALUE_PM


def accel(bars: pd.DataFrame | None) -> float | None:
    """최근 5분 1분 평균 거래대금 ÷ 그 앞 20분 1분 평균 (분봉 25개 미만이면 있는 만큼)"""
    if bars is None or len(bars) < 8:
        return None
    b = bars.sort_values("time")
    v = (b["close"].astype(float) * b["volume"].astype(float)).to_numpy()
    last, prev = v[-5:], v[-25:-5]
    if len(prev) < 3 or prev.mean() <= 0:
        return None
    return float(last.mean() / prev.mean())


def vwap(bars: pd.DataFrame | None) -> float | None:
    if bars is None or not len(bars):
        return None
    vol = bars["volume"].astype(float)
    if vol.sum() <= 0:
        return None
    px = (bars["high"].astype(float) + bars["low"].astype(float) + bars["close"].astype(float)) / 3
    return float((px * vol).sum() / vol.sum())


def limit_hist(daily: pd.DataFrame, days: int = 60) -> int:
    c = daily["close"].to_numpy(float)
    if len(c) < 2:
        return 0
    r = c[1:] / c[:-1] - 1
    return int((r[-days:] >= 0.295).sum())


def evaluate(daily: pd.DataFrame, q: dict, bars: pd.DataFrame | None, book: dict | None, ctx: dict) -> dict:
    """q = 지금 시세 (price · high · prev_close · value · change_pct) → {status, score, parts, reasons, …}"""
    from .limitcatch import news_score, sector_score
    hm = ctx["now"].strftime("%H:%M")
    px, hi, chg, val = float(q["price"]), float(q.get("high") or q["price"]), float(q["change_pct"]), float(q["value"])
    out = {"version": VERSION, "price": px, "chg_pct": round(chg, 2), "value": round(val), "high": hi,
           "status": "대상 아님", "score": 0.0, "parts": {}, "reasons": [], "warn": []}
    gap_hi = (hi / px - 1) * 100 if px > 0 else 99.0
    base = (PRE_MIN <= chg < PRE_MAX) and in_window(hm) and val >= min_value(hm) and gap_hi <= NEAR_HIGH
    if ctx.get("danger"):
        out.update(status="제외", warn=[ctx["danger"]])
        return out
    if not base:
        return out
    a = accel(bars)
    vw = vwap(bars)
    vw_gap = (px / vw - 1) * 100 if vw else None
    bm = book or {}
    ratio = (bm.get("total_bid") / bm.get("total_ask")) if bm.get("total_bid") and bm.get("total_ask") else None
    hits = limit_hist(daily)
    parts = {
        "accel25": round(ramp(a, [(1.0, 0), (2.0, 12.5), (3.0, 25)]) if a is not None else 0.0, 1),
        "high15": round(ramp(-gap_hi, [(-NEAR_HIGH, 0), (0, 15)]), 1),
        "vwap15": round(ramp(vw_gap, [(0, 0), (3, 15)]) if vw_gap is not None else 0.0, 1),
        "book15": round(ramp(ratio, [(0.8, 0), (1.5, 7.5), (2.5, 15)]) if ratio is not None else 7.5, 1),
        "sec10": round(sector_score(ctx.get("sector")), 1),
        "news10": round(news_score(ctx.get("news")) / 15 * 10 if ctx.get("news") else 3.0, 1),
        "hist10": 10.0 if hits else 4.0,
    }
    score = round(sum(parts.values()), 1)
    reasons = []
    if a is not None and a >= 2:
        reasons.append(f"거래대금 가속 {a:.1f}배 (최근 5분)")
    if gap_hi <= 0.3:
        reasons.append("당일 고가 갱신 중")
    if vw_gap is not None and vw_gap >= 1:
        reasons.append(f"VWAP +{vw_gap:.1f}%")
    if ratio is not None and ratio >= 1.5:
        reasons.append(f"매수잔량 {ratio:.1f}배")
    if hits:
        reasons.append(f"최근 60일 상한가 {hits}회")
    nd = ctx.get("news") or {}
    if nd.get("level") == "pos":
        reasons.append("호재 뉴스" + (" (오늘)" if nd.get("fresh") else ""))
    warn = []
    if vw_gap is not None and vw_gap < 0:
        warn.append("VWAP 아래")
    if nd.get("level") in ("neg", "severe"):
        warn.append("악재 뉴스")
    if ratio is not None and ratio < 0.8:
        warn.append("매도잔량 우위")
    out.update(status="상한가 예비" if score >= SHOW_SCORE else "관찰", score=score, parts=parts, reasons=reasons,
               warn=warn, accel=None if a is None else round(a, 2), vwap_gap=None if vw_gap is None else round(vw_gap, 2),
               book_ratio=None if ratio is None else round(ratio, 2), limit_hits60=hits,
               gap_high=round(gap_hi, 2))
    return out


def grade(sig: dict, day: dict, limit: float | None) -> dict:
    """그날 일봉으로 결과: 상한가 도달 · 종가 잠김 · 신호 뒤 고가·종가 수익률"""
    px = float(sig.get("price") or 0)
    hi, cl = float(day.get("high") or 0), float(day.get("close") or 0)
    reached = bool(limit and hi >= limit - 1e-9)
    closed = bool(limit and cl >= limit - 1e-9)
    return {"reached": reached, "closed": closed,
            "high_ret": round((hi / px - 1) * 100, 2) if px > 0 and hi > 0 else None,
            "close_ret": round((cl / px - 1) * 100, 2) if px > 0 and cl > 0 else None}


def stats(rows: list[dict]) -> dict:
    """점수 구간별 도달·잠김 비율 (결과 있는 것만)"""
    done = [r for r in rows if r.get("reached") is not None]

    def agg(sel):
        n = len(sel)
        if not n:
            return {"n": 0}
        cr = [r["close_ret"] for r in sel if r.get("close_ret") is not None]
        return {"n": n, "reached": round(sum(r["reached"] for r in sel) / n * 100, 1),
                "closed": round(sum(r["closed"] for r in sel) / n * 100, 1),
                "close_ret": round(float(np.mean(cr)), 2) if cr else None}
    bands = [("80~", 80, 999), ("70~79", 70, 80), ("60~69", 60, 70)]
    return {"all": agg(done),
            "bands": [{"label": lab, **agg([r for r in done if lo <= (r.get("score") or 0) < hi])} for lab, lo, hi in bands]}
