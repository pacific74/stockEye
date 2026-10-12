"""종가배팅 (CB-0.1) — 오늘 장 마감 무렵(15:20 전후) 사서 내일 오전에 파는 후보

오늘 종가까지 확인되는 정보만 쓴다. 많이 오른 종목을 무조건 사지 않고, 종가까지 매수세가 유지되고
내일 아침에도 오를 여지가 남은 종목을 고른다. 점수와 별도로 '갭 하락 위험' 을 따로 보여준다.

100점 (초기 가설 — 검증 후 조정)
  종가 강도       20  하루 범위에서 종가 위치(고가 부근) · 고가와의 거리 · VWAP 위 마감
  장 후반 매수세  20  13시 이후 분당 거래량 / 오전 · 13시 대비 가격 · 마지막 30분 상승 봉 거래량 비중 · 고점 유지
  거래대금·유동성 15  오늘 거래대금 (내일 아침 팔 수 있을 만큼)
  돌파·눌림 패턴  15  20일 고점 돌파 + 거래량 / 5·20일선 지지 후 양봉
  뉴스·공시       15  최근 뉴스 호재 15 · 중립 7.5 · 악재 0 (오늘 +15%↑ 면 호재도 -5: 이미 반영) · 심각 악재 제외
  시장·업종       10  지수 등락 5 + 업종(같은 업종 종목 평균) 등락 5
  갭 위험·손익비   5  갭 위험 낮음 5 · 보통 3 · 높음 0

갭 위험 (점수와 별도 표시: 낮음 / 보통 / 높음)
  지난 60일 '전일 종가 → 다음 날 시가' 하위 20% 갭 · 오늘 상승률 · 윗꼬리 · 바로 위 60일 고점(저항) · 20일선 이격 · 지수 약세
  예상 갭 범위 = 지난 60일 시가 갭 하위 20% ~ 상위 20%

필수 제외: 오늘 거래대금 30억 미만 · 오늘 +20% 이상(과열·되밀림) · 관리종목 · 심각 악재 뉴스 · 하락 마감(-1% 미만)
상태: 진입 금지 / 관찰(70↑) / 우선 관찰(80↑) / 매수 후보(80↑ + 갭 위험 낮음·보통 + 15:10 이후)

다음 날 매매 (손절가에 정확히 체결된다고 가정하지 않음)
  1차 목표 = 종가 +max(2%, ATR%×0.5) · 2차 = +max(4%, ATR%×1.0) · 손절 = -max(2%, ATR%×0.6) (최대 5%)
  ① 시초가가 손절가 아래(갭 하락) → 시초가 전량 매도 (손절가보다 손실이 클 수 있음)
  ② 시초가가 1차 목표 이상 → 시초가에 절반, 나머지는 매수가 아래로 밀리면 매도
  ③ 오전 중 1차 목표 → 절반, 2차 → 나머지, 1차 뒤 매수가 이탈 → 나머지, 손절가 이탈 → 전량
  ④ 10:30 까지 남은 몫 → 전량 매도 (시간 청산)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .daytrade import ramp, rt

VERSION = "CB-0.1"
COST = 0.0025                # 왕복 비용 (수수료·세금, 비율)
MIN_VALUE = 30e8             # 오늘 거래대금 30억
MAX_CHG = 20.0               # 오늘 +20% 이상 제외
EXIT_TIME = "10:30"
WATCH, PRIORITY = 70.0, 80.0
PARTS = {"close20": ("종가 강도", 20), "late20": ("장 후반 매수세", 20), "liq15": ("거래대금·유동성", 15),
         "pat15": ("돌파·눌림 패턴", 15), "news15": ("뉴스·공시", 15), "mkt10": ("시장·업종 흐름", 10),
         "gap5": ("갭 위험·손익비", 5)}
EXIT_RULES = ["시초가가 손절가 아래(갭 하락)면 시초가 전량 매도 — 손절가보다 손실이 클 수 있음",
              "시초가가 1차 목표 이상이면 시초가에 절반, 나머지는 매수가 아래로 밀리면 매도",
              "오전 중 1차 목표에 절반 · 2차 목표에 나머지 · 1차 뒤 매수가 이탈하면 나머지",
              "손절가 이탈하면 전량 · 10:30 까지 남은 몫은 전량 매도"]


def atr_pct(d: pd.DataFrame, n: int = 14) -> float:
    if len(d) < 3:
        return 0.03
    h, l, c = d["high"].values, d["low"].values, d["close"].values
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return float(np.mean(tr[-n:]) / c[-1]) if c[-1] > 0 else 0.03


def gap_stats(d: pd.DataFrame, n: int = 60) -> tuple[float, float]:
    """지난 n일 '전일 종가 → 다음 날 시가' 갭의 하위 20% · 상위 20% (%)"""
    if len(d) < 10:
        return -1.5, 1.5
    g = (d["open"].values[1:] / d["close"].values[:-1] - 1)[-n:] * 100
    g = g[np.isfinite(g)]
    return (float(np.percentile(g, 20)), float(np.percentile(g, 80))) if len(g) else (-1.5, 1.5)


def gap_risk(today: dict, daily: pd.DataFrame, chg: float, idx_chg: float | None) -> dict:
    h, l, c = today["high"], today["low"], today["close"]
    lo, hi = gap_stats(daily)
    pts, why = 0, []
    if chg >= 15:
        pts += 2; why.append(f"오늘 +{chg:.0f}% 급등 → 시초가 되밀림 위험")
    elif chg >= 10:
        pts += 1; why.append(f"오늘 +{chg:.0f}% → 차익 매물 가능")
    if h > l and (h - c) / (h - l) >= 0.3:
        pts += 1; why.append("윗꼬리 (고가에서 밀림)")
    if len(daily) >= 20:
        h60 = float(daily["high"].iloc[-60:].max())
        if c < h60 <= c * 1.02:
            pts += 1; why.append(f"바로 위 60일 고점 {rt(h60):,.0f}원 저항")
        ma20 = float(pd.concat([daily["close"].iloc[-19:], pd.Series([c])]).mean())
        if c / ma20 >= 1.15:
            pts += 1; why.append(f"20일선보다 +{(c / ma20 - 1) * 100:.0f}% 위 (과열)")
    if idx_chg is not None and idx_chg <= -1:
        pts += 1; why.append("지수 약세")
    if lo <= -2:
        pts += 1; why.append(f"평소 시가 갭 하락이 큼 (하위 20% {lo:.1f}%)")
    grade = "낮음" if pts <= 1 else ("보통" if pts <= 3 else "높음")
    return {"grade": grade, "points": pts, "why": why, "gap_lo": round(lo, 2), "gap_hi": round(hi, 2)}


def plan(c: float, atr: float) -> dict:
    t1 = c * (1 + max(0.02, 0.5 * atr))
    t2 = c * (1 + max(0.04, 1.0 * atr))
    stop = c * (1 - min(0.05, max(0.02, 0.6 * atr)))
    return {"entry": rt(c), "buy_lo": rt(c * 0.995, "down"), "buy_hi": rt(c * 1.005, "up"),
            "t1": rt(t1, "up"), "t2": rt(t2, "up"), "stop": rt(stop, "down"),
            "t1_pct": round((t1 / c - 1) * 100, 1), "stop_pct": round((stop / c - 1) * 100, 1)}


def pattern(daily: pd.DataFrame, today: dict) -> tuple[float, str]:
    c, o, l = today["close"], today["open"], today["low"]
    if len(daily) < 20:
        return 0.0, "-"
    h20 = float(daily["high"].iloc[-20:].max())
    vavg = float(daily["volume"].iloc[-20:].mean())
    vr = today["volume"] / vavg if vavg > 0 else 0
    ma5 = float(pd.concat([daily["close"].iloc[-4:], pd.Series([c])]).mean())
    ma20 = float(pd.concat([daily["close"].iloc[-19:], pd.Series([c])]).mean())
    brk = (9 if c > h20 else ramp(c / h20, [(0.97, 0), (1.0, 5)])) + ramp(vr, [(1, 0), (1.5, 3), (3, 6)])
    pb = 0.0
    if l <= max(ma5, ma20) * 1.01 and c > o and c > ma5:
        pb = 10 + (2 if c > ma20 else 0)
    return (round(min(brk, 15), 2), "돌파") if brk >= pb else (round(min(pb, 15), 2), "눌림 재상승")


def late_flow(m: pd.DataFrame | None) -> float | None:
    """장 후반 매수세 (13시 이후). 분봉 없으면 None"""
    if m is None or len(m) < 30:
        return None
    hm = m["time"].dt.strftime("%H:%M")
    am, pm = m[(hm >= "09:30") & (hm < "13:00")], m[hm >= "13:00"]
    if len(pm) < 10 or len(am) < 10:
        return None
    rate = pm["volume"].mean() / max(am["volume"].mean(), 1)
    p13 = float(pm["open"].iloc[0])
    c = float(m["close"].iloc[-1])
    last = m.iloc[-30:]
    upshare = float(last.loc[last["close"] >= last["open"], "volume"].sum() / max(last["volume"].sum(), 1))
    hold = c >= float(last["high"].max()) * 0.995
    s = ramp(rate, [(0.5, 0), (1, 5), (1.5, 8)]) + ramp(c / p13 - 1, [(-0.01, 0), (0, 3), (0.02, 6)]) \
        + ramp(upshare, [(0.4, 0), (0.7, 4)]) + (2 if hold else 0)
    return min(s, 20.0)


def evaluate(daily: pd.DataFrame, today: dict, mbars: pd.DataFrame | None, ctx: dict) -> dict:
    """daily: 어제까지 일봉 (date, open, high, low, close, volume) · today: 오늘 {open, high, low, close, volume, value,
    vwap, prev_close} · mbars: 오늘 1분봉 (없으면 장 후반 매수세는 빼고 환산) · ctx: news_level, idx_chg, sector_chg,
    danger, now, rescale_missing"""
    c, h, l = float(today["close"]), float(today["high"]), float(today["low"])
    prev = float(today.get("prev_close") or (daily["close"].iloc[-1] if len(daily) else c))
    chg = (c / prev - 1) * 100 if prev > 0 else 0.0
    value = float(today.get("value") or 0)
    vw = today.get("vwap")
    idx_chg, sec_chg = ctx.get("idx_chg"), ctx.get("sector_chg")
    nl = ctx.get("news_level")
    ex = []
    if value < MIN_VALUE:
        ex.append(f"거래대금 {value / 1e8:.0f}억 (30억 미만 — 내일 아침 팔기 어려움)")
    if chg >= MAX_CHG:
        ex.append(f"오늘 +{chg:.0f}% (과열 — 내일 되밀림 위험)")
    if chg < -1:
        ex.append(f"오늘 {chg:.1f}% 하락 마감")
    if ctx.get("danger"):
        ex.append(str(ctx["danger"]))
    if nl == "severe":
        ex.append("심각 악재 뉴스")

    pos = (c - l) / (h - l) if h > l else 0.5
    close20 = ramp(pos, [(0.5, 0), (0.8, 10), (0.95, 14)]) + ramp(c / h if h > 0 else 0, [(0.97, 0), (0.995, 3)]) \
        + (3 if vw and c >= vw else 0)
    late = late_flow(mbars)
    pat, ptype = pattern(daily, today)
    news = {"pos": 15.0, "neg": 0.0, "severe": 0.0}.get(nl, 7.5)
    if nl == "pos" and chg >= 15:
        news -= 5                                             # 호재가 이미 크게 반영
    gr = gap_risk(today, daily, chg, idx_chg)
    parts = {"close20": close20, "late20": late if late is not None else 10.0,
             "liq15": ramp(value / 1e8, [(30, 3), (100, 9), (300, 13), (1000, 15)]),
             "pat15": pat, "news15": news,
             "mkt10": ramp(idx_chg if idx_chg is not None else 0, [(-1, 0), (0, 2.5), (1, 5)])
             + ramp(sec_chg if sec_chg is not None else 0, [(-1, 0), (0, 2.5), (2, 5)]),
             "gap5": {"낮음": 5.0, "보통": 3.0, "높음": 0.0}[gr["grade"]]}
    parts = {k: round(max(0.0, min(v, PARTS[k][1])), 2) for k, v in parts.items()}
    score = round(sum(parts.values()), 1)
    if ctx.get("rescale_missing"):
        # 일봉만으로 되돌려 볼 때: 장 후반 매수세·뉴스·업종이 없으면 그 몫을 빼고 나머지 만점 기준 100점으로 환산
        miss = {"late20": late is None, "news15": nl is None}
        rem = sum(parts[k] for k, m in miss.items() if m) + (ramp(0, [(-1, 0), (0, 2.5), (2, 5)]) if sec_chg is None else 0)
        mx = sum(PARTS[k][1] for k, m in miss.items() if m) + (5 if sec_chg is None else 0)
        score = round((score - rem) * 100 / (100 - mx), 1)
    pl = plan(c, atr_pct(daily))
    hm = pd.Timestamp(ctx["now"]).strftime("%H:%M") if ctx.get("now") is not None else "15:20"
    if ex:
        status = "진입 금지"
    elif score >= PRIORITY and gr["grade"] != "높음" and hm >= "15:10":
        status = "매수 후보"
    elif score >= PRIORITY:
        status = "우선 관찰"
    elif score >= WATCH:
        status = "관찰"
    else:
        status = "대상 아님"
    reasons = [f"종가 위치 {pos:.0%} (고가 대비 {(c / h - 1) * 100:+.1f}%)" if h > 0 else "",
               f"{ptype} · 오늘 {chg:+.1f}% · 거래대금 {value / 1e8:,.0f}억"]
    if late is not None:
        reasons.append(f"장 후반 매수세 {parts['late20']:.0f}/20")
    return {"version": VERSION, "status": status, "score": score, "parts": parts, "type": ptype, "excluded": ex,
            "price": c, "chg_pct": round(chg, 2), "value": round(value), "vwap": rt(vw) if vw else None,
            "close_pos": round(pos, 2), "gap": gr, "news_level": nl, "reasons": [r for r in reasons if r],
            "exit_rules": EXIT_RULES, "exit_time": EXIT_TIME, **pl,
            "labels": {k: v for k, (v, _) in PARTS.items()}, "maxes": {k: m for k, (_, m) in PARTS.items()}}


def simulate_next(m: pd.DataFrame, entry: float, stop: float, t1: float, t2: float, exit_time: str = EXIT_TIME) -> dict:
    """다음 날 오전 1분봉으로 청산 (규칙 ①~④). 같은 봉에서 손절·목표 모두 닿으면 손절 먼저"""
    hm = m["time"].dt.strftime("%H:%M")
    m = m[hm <= exit_time]
    if m.empty:
        return {"outcome": "none", "pnl": None}
    pos, val, st, hit1, first = 1.0, 0.0, stop, False, {}
    o = float(m["open"].iloc[0])
    gap = (o / entry - 1) * 100
    if o <= stop:                                                  # ① 갭 하락
        return {"outcome": "gap_stop", "pnl": round((o / entry - 1 - COST) * 100, 3), "gap_pct": round(gap, 2)}
    if o >= t1:                                                    # ② 갭 상승 → 시초가 절반
        val += 0.5 * o; pos = 0.5; hit1 = True; st = entry; first["t1"] = 1
    for i, r in enumerate(m.itertuples(), 1):
        if r.low <= st:
            val += pos * min(r.open, st); first.setdefault("stop" if not hit1 else "even", i); pos = 0.0
            break
        if not hit1 and r.high >= t1:
            val += 0.5 * t1; pos -= 0.5; hit1 = True; st = max(st, entry); first["t1"] = i
        if hit1 and r.high >= t2:
            val += pos * t2; pos = 0.0; first["t2"] = i
            break
    if pos > 0:
        val += pos * float(m["close"].iloc[-1])                    # ④ 시간 청산
    out = "t2" if "t2" in first else ("t1" if "t1" in first else ("stop" if "stop" in first else "time"))
    return {"outcome": out, "pnl": round((val / entry - 1 - COST) * 100, 3), "gap_pct": round(gap, 2)}


def simulate_daily(nxt: dict, entry: float, stop: float, t1: float) -> dict:
    """일봉만 있을 때 (5년 되돌려 보기): 다음 날 시가 매도 수익률 + 보수적 오전 근사
    시가가 손절 아래 → 시가 · 저가가 손절 이하 → 손절 먼저 · 고가가 1차 이상 → 절반 1차 + 나머지 시가 · 그 외 시가"""
    o, h, l = float(nxt["open"]), float(nxt["high"]), float(nxt["low"])
    gap = (o / entry - 1) * 100
    if o <= stop:
        px, out = o, "gap_stop"
    elif l <= stop:
        px, out = stop, "stop"
    elif h >= t1:
        px, out = 0.5 * max(t1, o) + 0.5 * o, "t1"
    else:
        px, out = o, "open"
    return {"outcome": out, "pnl": round((px / entry - 1 - COST) * 100, 3), "open_pnl": round((o / entry - 1 - COST) * 100, 3),
            "gap_pct": round(gap, 2)}
