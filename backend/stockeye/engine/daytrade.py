"""당일단타 (DT-0.1) — 장 시작 후 09:00~10:30 1분봉·호가로 '오늘 안에 사고 파는' 후보

세 가지를 따로 본다 (점수가 높아도 진입 신호가 없으면 사지 않는다)
  선별 점수   지금 관찰할 가치가 있나 (100점)
  진입 신호   실제 매수 조건이 맞았나 (A 돌파형 / B 눌림목형)
  위험 관리   손절 거리·기대 보상이 맞나 (손절 1.5% 이내, 비용 뺀 손익비 1.5 이상이 되도록 목표)

100점 (초기 가설 — 검증 후 조정)
  거래대금·유동성 20  오전 누적 거래대금 14 + 호가 스프레드 6
  거래량·매수세   15  최근 5분 거래량 / 그 전 20분 평균 10 + 상승 봉 거래량 비중 5
  가격 구조·패턴  25  돌파형 또는 눌림목형 (둘 중 높은 쪽)
  단기 추세       15  VWAP 위 5 · 최근 5분 상승 4 · 1분 EMA5 > EMA20 3 · 시초 범위 위 3
  뉴스·공시 재료  10  최근 뉴스 호재 10 · 중립/없음 5 · 악재 0 (심각 악재는 제외)
  시장·업종 동조  10  지수 등락 5 + 지수 대비 강도 5  (업종 동조는 아직 없음)
  손익비·위험 여유  5  손절 거리 짧을수록 · 눌림목은 위 고점까지 공간

필수 제외 (점수와 상관없이)
  오전 누적 거래대금 10억 미만 · 스프레드 0.3% 초과 · 최근 1분 체결 없음 · 손절 거리 1.5% 초과
  거래정지·투자경고 등 위험 상태 · 심각 악재 뉴스 · 시세 지연(마지막 봉이 3분 넘게 지남)
  VWAP 대비 3% 이상 위 → 신규 진입 보류 (추격 금지) · 09:05 전 → 후보 수집만

상태: 진입 금지 / 관찰(70↑) / 진입 대기(80↑, 신호 없음) / 진입 조건 충족(80↑ + 신호)
주문: 1차 익절 = 위험의 1.5배, 2차 = 2배 (비용 0.2% 반영), 손절 = 패턴 무효화 가격, 장 마감 전 청산
"""
from __future__ import annotations

import numpy as np
import pandas as pd

VERSION = "DT-0.2"   # 0.2: 1차 목표 +3%↑ · 2차 +5%↑ · 평소 하루 변동폭 5% 미만 제외
COST = 0.002                 # 왕복 수수료·세금 (비율)
MIN_VALUE = 10e8             # 오전 누적 거래대금 10억
MAX_SPREAD = 0.003           # 0.3%
MAX_STOP = 0.015             # 손절 거리 1.5%
MIN_T1 = 0.03               # 1차 목표 최소 +3% (작게 먹고 위험만 지는 자리 제외)
MIN_T2 = 0.05               # 2차 목표 최소 +5%
MIN_ADR = 0.05              # 최근 20일 평균 하루 변동폭(고가-저가)/전일종가 5% 미만 → 3% 먹기 어려움
LIMIT_UP = 0.30             # 상한가
VWAP_CHASE = 0.03            # VWAP 대비 3%
WARMUP = "09:05"             # 이 전에는 신규 진입 신호 없음
WATCH, PRIORITY = 70.0, 80.0
PARTS = {"liq20": ("거래대금·유동성", 20), "vol15": ("거래량·매수세", 15), "pat25": ("가격 구조·진입 패턴", 25),
         "trend15": ("단기 추세", 15), "news10": ("뉴스·공시 재료", 10), "mkt10": ("시장·업종 동조", 10),
         "risk5": ("손익비·위험 여유", 5)}
SEVERE = ["횡령", "배임", "거래정지", "상장폐지", "상장적격성", "감사의견", "회생", "부도"]


def ramp(x, pts) -> float:
    """구간 직선 보간 (pts = [(x, y), ...] 오름차순)"""
    if x is None or not np.isfinite(x):
        return 0.0
    xs, ys = zip(*pts)
    return float(np.interp(x, xs, ys))


def tick(p: float) -> float:
    """호가 단위 (2023~ KRX)"""
    for lim, t in ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)):
        if p < lim:
            return t
    return 1000


def rt(p: float, mode: str = "near") -> float:
    t = tick(p)
    f = {"down": np.floor, "up": np.ceil}.get(mode, np.round)
    return float(f(p / t) * t)


def vwap(b: pd.DataFrame) -> float:
    v = b["volume"].sum()
    return float(((b["high"] + b["low"] + b["close"]) / 3 * b["volume"]).sum() / v) if v > 0 else float(b["close"].iloc[-1])


def plan(entry: float, stop: float) -> dict:
    """목표가: 비용 뺀 손익비 1.5 / 2.0 과 최소 +3% / +5% 중 큰 쪽"""
    c = entry * COST
    r = entry - stop
    t1 = max(entry + 1.5 * (r + c) + c, entry * (1 + MIN_T1))
    t2 = max(entry + 2.0 * (r + c) + c, entry * (1 + MIN_T2))
    return {"entry": rt(entry), "stop": rt(stop, "down"), "t1": rt(t1, "up"), "t2": rt(t2, "up"),
            "risk_pct": round(r / entry * 100, 2), "t1_pct": round((t1 / entry - 1) * 100, 1),
            "t2_pct": round((t2 / entry - 1) * 100, 1)}


def adr(daily: pd.DataFrame, n: int = 20) -> float | None:
    """최근 n일 평균 하루 변동폭 (고가-저가)/전일 종가 — daily: date·high·low·close (오늘 제외)"""
    if daily is None or len(daily) < 6:
        return None
    d = daily.sort_values("date").tail(n + 1)
    pc = d["close"].shift(1)
    r = ((d["high"] - d["low"]) / pc).dropna()
    r = r[(r >= 0) & (r < 0.6)]
    return float(r.mean()) if len(r) else None


def breakout(b: pd.DataFrame) -> dict:
    """A 돌파형: 직전까지의 당일 고점(저항)을 1분봉 종가로 넘기고 거래량 1.5배↑"""
    if len(b) < 6:
        return {"score": 0.0}
    last = b.iloc[-1]
    R = float(b["high"].iloc[:-1].max())
    vavg = float(b["volume"].iloc[-21:-1].mean()) if len(b) > 1 else 0
    vr = last["volume"] / vavg if vavg > 0 else 0
    rng = last["high"] - last["low"]
    pos = (last["close"] - last["low"]) / rng if rng > 0 else 0.5
    over = last["close"] / R - 1
    s = 0.0
    s += 10 if over > 0 else ramp(over, [(-0.01, 0), (0, 6)])            # 저항 위 마감 (가까우면 일부)
    s += ramp(vr, [(1, 0), (1.5, 5), (3, 8)])                             # 돌파 거래량
    s += ramp(pos, [(0.3, 0), (0.6, 4)])                                  # 봉 위쪽 마감
    s += 3 if 0 < over <= 0.007 else (1 if over <= 0 else 0)              # 너무 멀리 가지 않음
    sig = bool(over > 0 and vr >= 1.5 and over <= 0.007)
    stop = R * (1 - 0.002)
    return {"score": round(min(s, 25), 2), "signal": sig, "level": R, "stop": stop, "vol_ratio": round(vr, 2),
            "over_pct": round(over * 100, 2)}


def pullback(b: pd.DataFrame, vw: float, or_high: float) -> dict:
    """B 눌림목형: 거래 동반 상승 → 거래 줄며 조정 → 지지(VWAP·시초 고점) 유지 → 저점 높이며 재상승"""
    if len(b) < 12:
        return {"score": 0.0}
    body = b.iloc[:-1]
    ih = int(body["high"].values.argmax())
    H = float(body["high"].iloc[ih])
    if ih < 3 or ih > len(b) - 4:
        return {"score": 0.0}
    up = b.iloc[:ih + 1]
    start = float(up["low"].min())
    gain = H / start - 1
    after = b.iloc[ih + 1:]
    L = float(after["low"].min())
    depth = (H - L) / (H - start) if H > start else 1
    v_up = float(up["volume"].iloc[-min(len(up), 10):].mean())
    v_pb = float(after["volume"].iloc[:-1].mean()) if len(after) > 1 else float(after["volume"].mean())
    last = b.iloc[-1]
    lows = after["low"].values[-3:]
    higher_low = len(lows) >= 3 and lows[-1] >= lows[-2] >= lows[-3] * 0.999
    rebreak = last["close"] > float(after["high"].iloc[-4:-1].max()) if len(after) >= 4 else False
    hold = L >= min(vw, or_high) * 0.997
    s = 0.0
    s += ramp(gain, [(0.01, 0), (0.03, 6)])                               # 거래 동반 상승
    s += 5 if v_pb < v_up * 0.8 else (2 if v_pb < v_up else 0)            # 조정 때 거래 감소
    s += 6 if hold and 0.2 <= depth <= 0.62 else (2 if hold else 0)       # 지지 유지 · 적당한 깊이
    s += (4 if higher_low else 0) + (4 if rebreak else 0)                 # 재상승
    sig = bool(gain >= 0.03 and v_pb < v_up and hold and 0.2 <= depth <= 0.62 and higher_low and rebreak
               and last["close"] < H)
    stop = L * (1 - 0.001)
    return {"score": round(min(s, 25), 2), "signal": sig, "level": H, "stop": stop, "gain_pct": round(gain * 100, 1),
            "depth": round(depth, 2), "low": L}


def evaluate(bars: pd.DataFrame, ctx: dict) -> dict:
    """bars: 오늘 1분봉 (time, open, high, low, close, volume) 오래된 → 최근. ctx: 아래 키
    name, prev_close, spread(비율|None), idx_chg(지수 등락 %), news_level(pos|neg|severe|None), danger(위험 상태 문자열|None),
    now(Timestamp), value(오전 누적 거래대금, 없으면 봉으로 계산)"""
    out = {"version": VERSION, "time": None, "status": "진입 금지", "score": 0.0, "parts": {}, "type": None,
           "signal": False, "reasons": [], "warnings": [], "excluded": []}
    if bars is None or len(bars) < 3:
        out["excluded"].append("분봉 부족")
        return out
    b = bars.sort_values("time").reset_index(drop=True)
    now = pd.Timestamp(ctx.get("now") or b["time"].iloc[-1])
    hm = now.strftime("%H:%M")
    last = b.iloc[-1]
    p = float(last["close"])
    out["time"] = pd.Timestamp(last["time"]).strftime("%H:%M")
    vw = vwap(b)
    or_bars = b[b["time"].dt.strftime("%H:%M") < "09:05"]
    or_high = float(or_bars["high"].max()) if len(or_bars) else float(b["high"].iloc[0])
    value = float(ctx.get("value") or (b["close"] * b["volume"]).sum())
    spread = ctx.get("spread")
    prev = float(ctx.get("prev_close") or b["open"].iloc[0])
    chg = (p / prev - 1) * 100 if prev > 0 else 0.0
    idx_chg = float(ctx.get("idx_chg") or 0.0)            # 없으면 0 (되돌려 보기는 rescale_missing 으로 빼고 환산)

    # ---- 필수 제외 ----
    ex = out["excluded"]
    if value < MIN_VALUE:
        ex.append(f"오전 거래대금 {value / 1e8:.0f}억 (10억 미만)")
    if spread is not None and spread > MAX_SPREAD:
        ex.append(f"호가 스프레드 {spread * 100:.2f}% (0.3% 초과)")
    if float(last["volume"]) <= 0:
        ex.append("최근 1분 체결 없음")
    if ctx.get("danger"):
        ex.append(str(ctx["danger"]))
    if ctx.get("news_level") == "severe":
        ex.append("심각 악재 뉴스")
    if (now - pd.Timestamp(last["time"])).total_seconds() > 180:
        ex.append("시세 지연 (마지막 봉 3분 넘게 지남)")
    a = ctx.get("adr")
    if a is not None and a < MIN_ADR:
        ex.append(f"평소 하루 변동폭 {a * 100:.1f}% (5% 미만 — +3% 먹기 어려움)")
    if prev > 0 and p * (1 + MIN_T1) > prev * (1 + LIMIT_UP) * 0.995:
        ex.append("상한가까지 +3% 여유 없음")

    # ---- 패턴 ----
    A = breakout(b)
    B = pullback(b, vw, or_high)
    use = A if A["score"] >= B["score"] else B
    typ = "돌파" if use is A else "눌림목"
    sig = bool(use.get("signal"))
    stop = float(use.get("stop") or p * (1 - MAX_STOP))
    pl = plan(p, min(stop, p - tick(p)))
    stop_pct = (p - pl["stop"]) / p
    if sig and stop_pct > MAX_STOP:
        ex.append(f"손절 거리 {stop_pct * 100:.1f}% (1.5% 초과)")

    # ---- 점수 ----
    vavg = float(b["volume"].iloc[-25:-5].mean()) if len(b) > 6 else float(b["volume"].mean())
    v5 = float(b["volume"].iloc[-5:].mean())
    upv = b.iloc[-10:]
    upshare = float(upv.loc[upv["close"] >= upv["open"], "volume"].sum() / max(upv["volume"].sum(), 1))
    ema = lambda n: b["close"].ewm(span=n, adjust=False).mean().iloc[-1]  # noqa: E731
    slope5 = p / float(b["close"].iloc[-6]) - 1 if len(b) > 5 else 0.0
    sp_pts = 3.0 if spread is None else ramp(spread, [(0.0005, 6), (0.001, 5), (0.002, 3), (0.003, 0)])
    room = (use["level"] - p) / max(p - pl["stop"], 1e-9) if typ == "눌림목" and use.get("level") else None
    parts = {
        "liq20": ramp(value / 1e8, [(10, 4), (30, 8), (100, 12), (300, 14)]) + sp_pts,
        "vol15": ramp(v5 / vavg if vavg > 0 else 0, [(1, 3), (1.5, 6), (2.5, 10)]) + ramp(upshare, [(0.4, 0), (0.7, 5)]),
        "pat25": float(use["score"]),
        "trend15": (5 if p > vw else 0) + (4 if slope5 > 0 else 0) + (3 if ema(5) > ema(20) else 0) + (3 if p > or_high else 0),
        "news10": {"pos": 10.0, "neg": 0.0, "severe": 0.0}.get(ctx.get("news_level"), 5.0),
        "mkt10": ramp(idx_chg, [(-1, 0), (0, 3), (1, 5)]) + ramp(chg - idx_chg, [(0, 1), (3, 3), (8, 5)]),
        "risk5": ramp(stop_pct, [(0.004, 5), (0.007, 5), (0.01, 4), (0.015, 2), (0.02, 0)]) - (2 if room is not None and room < 1.5 else 0),
    }
    parts = {k: round(max(0.0, min(v, PARTS[k][1])), 2) for k, v in parts.items()}
    score = round(sum(parts.values()), 1)
    if ctx.get("rescale_missing"):
        # 되돌려 보기: 과거엔 호가·뉴스·지수가 없음 → 그 몫을 빼고 나머지 만점 기준 100점으로 환산 (중립값이 점수를 깎지 않게)
        idx_pts = ramp(idx_chg, [(-1, 0), (0, 3), (1, 5)]) if ctx.get("idx_chg") is None else 0.0
        removed = (sp_pts if spread is None else 0) + (parts["news10"] if ctx.get("news_level") is None else 0) + idx_pts
        maxrem = (6 if spread is None else 0) + (10 if ctx.get("news_level") is None else 0) + (5 if ctx.get("idx_chg") is None else 0)
        score = round((score - removed) * 100 / (100 - maxrem), 1)

    # ---- 상태 ----
    gap = p / vw - 1
    w = out["warnings"]
    if gap >= VWAP_CHASE:
        w.append(f"VWAP 대비 +{gap * 100:.1f}% — 추격 금지 (신규 진입 보류)")
    if hm < WARMUP:
        w.append("장 시작 5분 — 후보 수집만 (신규 진입 보류)")
    can_enter = sig and gap < VWAP_CHASE and hm >= WARMUP
    if ex:
        status = "진입 금지"
    elif score >= PRIORITY and can_enter:
        status = "진입 조건 충족"
    elif score >= PRIORITY:
        status = "진입 대기"
    elif score >= WATCH:
        status = "관찰"
    else:
        status = "대상 아님"
    r = out["reasons"]
    if typ == "돌파":
        r.append(f"당일 고점 {rt(use.get('level') or p):,.0f}원 {'돌파' if use.get('over_pct', 0) > 0 else '근접'}"
                 f" · 거래량 {use.get('vol_ratio', 0):.1f}배")
    else:
        r.append(f"오전 상승 +{use.get('gain_pct', 0):.1f}% 뒤 눌림 (깊이 {use.get('depth', 0):.0%})"
                 f" · 고점 {rt(use.get('level') or p):,.0f}원")
    r.append(f"VWAP {rt(vw):,.0f}원 {'위' if p > vw else '아래'} · 오전 거래대금 {value / 1e8:,.0f}억")
    out.update({"status": status, "score": score, "parts": parts, "type": typ, "signal": sig,
                "price": p, "chg_pct": round(chg, 2), "vwap": rt(vw), "vwap_gap_pct": round(gap * 100, 2),
                "value": round(value), "adr_pct": None if a is None else round(a * 100, 1), "spread_pct": None if spread is None else round(spread * 100, 3),
                "or_high": rt(or_high), "level": rt(use.get("level") or p), **pl,
                "labels": {k: v for k, (v, _) in PARTS.items()}, "maxes": {k: m for k, (_, m) in PARTS.items()}})
    return out


def simulate_exit(bars_after: pd.DataFrame, entry: float, stop: float, t1: float, t2: float) -> dict:
    """진입 뒤 1분봉 → 결과 (같은 봉에서 손절·목표가 모두 닿으면 손절 먼저). 1차에서 절반, 2차에서 나머지,
    1차 뒤 남은 몫은 본전 손절, 끝까지 남으면 마지막 봉 종가 (장 마감 전 청산)"""
    pos, val, st, hit1 = 1.0, 0.0, stop, False
    first = {}
    for i, r in enumerate(bars_after.itertuples(), 1):
        if r.low <= st:
            val += pos * min(r.open, st) if r.open > 0 else pos * st
            first.setdefault("stop" if not hit1 else "even", i)
            pos = 0.0
            break
        if not hit1 and r.high >= t1:
            val += 0.5 * t1
            pos -= 0.5
            hit1 = True
            st = max(st, entry)
            first["t1"] = i
        if hit1 and r.high >= t2:
            val += pos * t2
            pos = 0.0
            first["t2"] = i
            break
    if pos > 0:
        last = float(bars_after["close"].iloc[-1]) if len(bars_after) else entry
        val += pos * last
    pnl = (val / entry - 1 - COST) * 100
    outcome = "t2" if "t2" in first else ("t1" if "t1" in first else ("stop" if "stop" in first else "close"))
    return {"outcome": outcome, "pnl": round(pnl, 3), "minutes": first}
