"""차트 기반 목표가·손절가 (매수구간·1차/2차 목표·손절 + 근거 문장)

예전: 목표 = 종가 +8% / +15%, 손절 = max(20일 저점 -1%, 종가 - 2ATR) → 종목의 차트와 무관.
지금: 종목마다 지지·저항 후보를 모아 가장 가까운 '의미 있는' 가격을 고른다 (선정일 종가까지만 사용).

  저항(목표) 후보 — 종가 위
    · 스윙 고점: 최근 250일에서 앞뒤 3일보다 높은 고가 (최근 것·여러 번 막힌 것일수록 강함)
    · 20·60·120·250일 최고가
    · 위에 있는 60·120일 이동평균선 (하락 중인 이평선은 저항)
    · 매물대: 최근 120일 '가격대별 거래대금'이 몰린 구간 (위에 있으면 팔려는 물량)
    · 볼린저밴드 상단 (20일, 2σ)
    · 피보나치 되돌림 38.2·50·61.8% (최근 큰 하락 구간을 되돌리는 중일 때)
  지지(손절) 후보 — 종가 아래
    · 스윙 저점 · 20·60일 최저가 · 아래에 있는 20·60일선 · 아래 매물대(거래 집중 구간)

  1차 목표 = 종가 + 1ATR 이상 떨어진 가장 가까운 저항 (가까운 후보는 1.5% 안이면 하나로 묶음)
  2차 목표 = 1차 목표 + 1ATR 이상 위의 다음 저항
    저항이 없으면(신고가 영역) ATR 투영: 1차 = 종가 + 3ATR, 2차 = 종가 + 5ATR
  손절   = 종가 - 0.8ATR 보다 아래에 있는 가장 가까운 지지 - 0.5ATR (지지 바로 밑)
    지지가 너무 멀면(3.5ATR 또는 15% 초과) 종가 - 2.5ATR, 지지가 없으면 종가 - 2ATR
  가격은 수정주가로 바꾸지 않고 실제 가격 그대로 (분할·병합 등이 있으면 그 뒤 구간만) → 앱 차트와 같은 가격
  매수구간 = 손절 위 지지(또는 20일선) ~ 종가 +1%
모든 가격은 호가 단위로 맞춤. 근거(basis)에 어떤 가격을 썼는지 날짜와 함께 남긴다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .trade_plan import round_tick

PIVOT_K = 3
CLUSTER = 0.015
# 손절 규칙 (실험으로 바꿔 볼 수 있게 상수로)
#   2026-10-11 '손절을 지지 바로 밑으로 좁히고 2·3차는 실제 지지가 있을 때만' 안을 적중률(5년)로 비교 →
#   손익이 탭마다 0.4~1.0%p 나빠져서(손절 더 잦음, 눌림 분할 매수 효과 사라짐) 아래 기존 값 유지
STOP_MIN_ATR = 0.8      # 지지는 종가 - 이만큼 ATR 보다 아래
STOP_BUF_ATR, STOP_BUF_PCT = 0.5, 0.0    # 지지 밑 여유 = max(ATR 배수, %)
STOP_MAX_ATR, STOP_MAX_PCT = 3.5, 0.15   # 손절까지 최대 거리
FALLBACK_ATR, FALLBACK_PCT = 2.5, 0.5    # 지지가 멀 때 종가 - ATR 배수 (최대 %)
NONE_ATR = 2.0          # 아래 지지가 아예 없을 때 종가 - ATR 배수
ZONE_FILL = True        # 2·3차 구간: 지지가 모자라면 1차 하단~손절 사이를 고르게 나눔 (눌림 분할 매수)


def _pivots(h: np.ndarray, l: np.ndarray, k: int = PIVOT_K):
    """앞뒤 k일보다 높은 고가 / 낮은 저가 (마지막 k일은 확정 안 됐으므로 제외)"""
    n = len(h)
    ph, pl = [], []
    for i in range(k, n - k):
        if h[i] == h[i - k:i + k + 1].max() and h[i] > h[i - k:i].max():
            ph.append(i)
        if l[i] == l[i - k:i + k + 1].min() and l[i] < l[i - k:i].min():
            pl.append(i)
    return ph, pl


def _volume_nodes(h, l, c, v, last: int = 120, bins: int = 24, top: int = 4):
    """최근 last일 가격대별 거래대금 → 많이 몰린 가격대 중심값 top 개"""
    h, l, c, v = h[-last:], l[-last:], c[-last:], v[-last:]
    lo, hi = np.nanmin(l), np.nanmax(h)
    if not np.isfinite(lo) or hi <= lo:
        return []
    edges = np.linspace(lo, hi, bins + 1)
    tp = (h + l + c) / 3
    w = np.nan_to_num(v * tp)
    hist, _ = np.histogram(tp, bins=edges, weights=w)
    if hist.sum() <= 0:
        return []
    mids = (edges[:-1] + edges[1:]) / 2
    idx = [i for i in np.argsort(hist)[::-1][:top] if hist[i] >= hist.mean() * 1.2]
    return [(float(mids[i]), float(hist[i] / hist.sum())) for i in idx]


def candidates(dates, o, h, l, c, v) -> tuple[list, list, dict]:
    """(저항 후보, 지지 후보, 지표) — 후보 = (가격, 이름, 날짜 or None, 강도)"""
    n = len(c)
    close = c[-1]
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr = float(pd.Series(tr).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().iloc[-1]) if n > 15 else np.nan
    ma = {w: float(np.mean(c[-w:])) if n >= w else np.nan for w in (20, 60, 120)}
    ma_prev = {w: float(np.mean(c[-w - 5:-5])) if n >= w + 5 else np.nan for w in (20, 60, 120)}
    sd20 = float(np.std(c[-20:])) if n >= 20 else np.nan
    res, sup = [], []
    d = lambda i: str(pd.Timestamp(dates[i]).date())  # noqa: E731

    ph, pl = _pivots(h, l)
    for i in ph[-25:]:
        age = n - 1 - i
        res.append((float(h[i]), "스윙 고점", d(i), 1.0 + (0.5 if age <= 60 else 0)))
    for i in pl[-25:]:
        age = n - 1 - i
        sup.append((float(l[i]), "스윙 저점", d(i), 1.0 + (0.5 if age <= 40 else 0)))
    for w in (20, 60, 120, 250):
        if n >= w:
            j = n - w + int(np.argmax(h[-w:]))
            res.append((float(h[j]), f"{w}일 최고가", d(j), 1.0 + w / 250))
    for w in (20, 60):
        if n >= w:
            j = n - w + int(np.argmin(l[-w:]))
            sup.append((float(l[j]), f"{w}일 최저가", d(j), 1.0 + w / 120))
    for w in (20, 60, 120):
        m = ma[w]
        if not np.isfinite(m):
            continue
        falling = np.isfinite(ma_prev[w]) and m < ma_prev[w]
        if m > close * 1.005 and w >= 60:
            res.append((m, f"{w}일선" + (" (하락 중)" if falling else ""), None, 1.0 + (0.5 if falling else 0)))
        elif m < close * 0.995 and w <= 60:
            sup.append((m, f"{w}일선", None, 1.0 + (0.5 if not falling else 0)))
    for p, share in _volume_nodes(h, l, c, v):
        (res if p > close else sup).append((p, f"매물대 (120일 거래 {share * 100:.0f}%)", None, 1.0 + share * 5))
    if np.isfinite(sd20):
        res.append((ma[20] + 2 * sd20, "볼린저 상단", None, 0.8))
    # 피보나치: 최근 120일 최고가 → 그 뒤 최저가 하락 구간을 되돌리는 중이면
    if n >= 60:
        w = min(120, n)
        hi_i = n - w + int(np.argmax(h[-w:]))
        lo_i = hi_i + int(np.argmin(l[hi_i:])) if hi_i < n - 1 else hi_i
        hi, lo = float(h[hi_i]), float(l[lo_i])
        if lo_i > hi_i and hi > lo * 1.15 and close < hi:
            for r in (0.382, 0.5, 0.618):
                res.append((lo + (hi - lo) * r, f"되돌림 {r * 100:.1f}%", None, 0.9))
    rsi = np.nan
    if n > 15:
        dd = np.diff(c)
        g = pd.Series(np.clip(dd, 0, None)).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
        ls = pd.Series(np.clip(-dd, 0, None)).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
        rsi = float(100 - 100 / (1 + g / ls)) if ls > 0 else 100.0
    return res, sup, {"atr": atr, "ma20": ma[20], "ma60": ma[60], "rsi": rsi, "close": float(close)}


def _cluster(cands: list, reverse: bool) -> list:
    """1.5% 안의 후보는 하나로 (강도 합, 이름은 가장 강한 것 + 개수)"""
    cands = sorted(cands, key=lambda x: x[0], reverse=reverse)
    out = []
    for p, name, dt, s in cands:
        if out and abs(p / out[-1]["price"] - 1) <= CLUSTER:
            g = out[-1]
            g["members"].append((p, name, dt, s))
            g["strength"] += s
            continue
        out.append({"price": p, "members": [(p, name, dt, s)], "strength": s})
    for g in out:
        best = max(g["members"], key=lambda m: m[3])
        g["price"] = best[0]
        g["name"], g["date"] = best[1], best[2]
        g["n"] = len(g["members"])
    return out


def _label(g) -> str:
    t = g["name"] + (f" {g['date'][2:].replace('-', '/')}" if g.get("date") else "")
    return t + (f" (후보 {g['n']}개 겹침)" if g["n"] > 1 else "")


def _won(p: float) -> str:
    return f"{int(round(p)):,}원"


def compute(dates, o, h, l, c, v) -> dict | None:
    """한 종목의 일봉 배열(과거→오늘) → 매수구간·목표·손절·근거"""
    c = np.asarray(c, float)
    if len(c) < 30 or not np.isfinite(c[-1]) or c[-1] <= 0:
        return None
    res, sup, ind = candidates(dates, np.asarray(o, float), np.asarray(h, float), np.asarray(l, float), c,
                               np.nan_to_num(np.asarray(v, float)))
    close, atr = ind["close"], ind["atr"]
    if not np.isfinite(atr) or atr <= 0:
        atr = close * 0.03
    R = [g for g in _cluster([r for r in res if r[0] > close * 1.005], reverse=False)]
    S = [g for g in _cluster([s for s in sup if s[0] < close * 0.995], reverse=True)]
    basis = []
    # 1차·2차 목표 (3차는 아래)
    t1g = next((g for g in R if g["price"] >= close + 1.0 * atr), None)
    t2g = None
    if t1g:
        t1 = t1g["price"]
        basis.append(f"1차 목표: {_label(t1g)} 저항")
        t2g = next((g for g in R if g["price"] >= t1 + 1.0 * atr), None)
        if t2g:
            t2 = t2g["price"]
            basis.append(f"2차 목표: {_label(t2g)} 저항")
        else:
            t2 = t1 + 2 * atr
            basis.append("2차 목표: 위에 저항 없음 → 1차 + 2ATR")
    else:
        t1, t2 = close + 3 * atr, close + 5 * atr
        basis.append("목표: 위에 저항 없음(신고가 영역) → 종가 + 3ATR / 5ATR")
    # 3차 목표: 2차보다 1ATR 이상 위의 다음 저항 (없으면 2차 + 2ATR)
    t3g = next((g for g in R if g["price"] >= t2 + 1.0 * atr), None)
    if t3g:
        t3 = t3g["price"]
        basis.append(f"3차 목표: {_label(t3g)} 저항")
    else:
        t3 = t2 + 2 * atr
        basis.append("3차 목표: 위에 저항 없음 → 2차 + 2ATR")
    # 손절: 종가 - 0.8ATR 아래 가장 가까운 지지 - 0.5ATR. 너무 멀면(3.5ATR·15% 초과) 종가 - 2.5ATR, 없으면 - 2ATR
    #   근거 문장에 그 지지의 실제 가격을 같이 씀 (차트에서 바로 확인)
    maxd = min(STOP_MAX_ATR * atr, close * STOP_MAX_PCT)
    sg = next((g for g in S if g["price"] <= close - STOP_MIN_ATR * atr), None)
    stop_lab = None
    buf = (lambda p: max(STOP_BUF_ATR * atr, p * STOP_BUF_PCT))
    if sg and close - (sg["price"] - buf(sg["price"])) <= maxd:
        stop = sg["price"] - buf(sg["price"])
        stop_lab = _label(sg)
        basis.append(f"손절: {_label(sg)} {_won(sg['price'])} 지지 아래 (지지 - 0.5ATR)")
    elif sg:
        stop = max(close - FALLBACK_ATR * atr, close * (1 - FALLBACK_PCT))
        basis.append(f"손절: 가까운 지지({_label(sg)} {_won(sg['price'])})가 멀어 종가 - {FALLBACK_ATR:g}ATR")
    else:
        stop = close - NONE_ATR * atr
        basis.append(f"손절: 아래 지지 없음 → 종가 - {NONE_ATR:g}ATR")
    # 매수구간: 손절 위에서 가장 가까운 지지(또는 20일선) ~ 종가 +1%
    near = next((g["price"] for g in S if g["price"] > stop and g["price"] >= close - 1.5 * atr), None)
    lo = max(stop * 1.02, near if near else min(close, ind["ma20"] if np.isfinite(ind["ma20"]) else close) * 0.99)
    lo = min(lo, close)
    zones = _zones(close, atr, stop, S, lo)
    if zones:
        lo = zones[0]["low"]                                  # 매수구간 = 1차 구간 (하단 ~ 종가 +1%)
    notes = _notes(close, atr, (t1, t1g), (t2, t2g), (t3, t3g), stop, stop_lab, zones)
    warn = []
    if np.isfinite(ind["rsi"]) and ind["rsi"] >= 70:
        warn.append(f"RSI {ind['rsi']:.0f} 과열 — 목표 도달 전 눌림 가능")
    if t1 < close * 1.03:
        warn.append("1차 목표까지 3% 미만 — 위 저항이 가까움")
    rt = lambda x, m: int(round_tick(x, m))  # noqa: E731
    stop_r, t1_r, t2_r, t3_r = rt(stop, "down"), rt(t1, "up"), rt(t2, "up"), rt(t3, "up")
    return {"price": int(round(close)), "entry_low": rt(lo, "down"), "entry_high": rt(close * 1.01, "up"),
            "target1": t1_r, "target2": t2_r, "target3": t3_r, "stop": stop_r,
            "stop_pct": (close - stop_r) / close, "rr": round((t1_r - close) / max(close - stop_r, 1e-9), 2),
            "atr": round(atr, 1), "rsi": None if not np.isfinite(ind["rsi"]) else round(ind["rsi"], 1),
            "basis": basis, "level_warn": warn, "zones": zones, "notes": notes,
            "resistances": [{"price": rt(g["price"], "up"), "label": _label(g)} for g in R[:6]],
            "supports": [{"price": rt(g["price"], "down"), "label": _label(g)} for g in S[:4]]}


def compute_all(ohlcv: pd.DataFrame, codes, days: int = 260) -> dict[str, dict]:
    """여러 종목: 최근 days 거래일로 compute → {code: levels}"""
    codes = set(codes)
    dts = np.sort(ohlcv["date"].unique())[-days:]
    oh = ohlcv[ohlcv["date"].isin(dts) & ohlcv["code"].isin(codes)].sort_values(["code", "date"])
    out = {}
    for code, g in oh.groupby("code", sort=False):
        g = g[g["close"] > 0]
        try:
            r = compute(*prepare(g))
        except Exception:  # noqa: BLE001
            r = None
        if r:
            out[code] = r
    return out


def window(g: pd.DataFrame, min_bars: int = 30) -> pd.DataFrame:
    """계산에 쓸 일봉 구간 — 앱 차트(실제 가격)와 같은 가격으로 근거를 쓰기 위해 '수정'하지 않고 자른다 (2026-10-11).
    액면분할·병합·무상증자처럼 하루 기준가가 15% 넘게 바뀐 날이 있으면 그날부터만 사용.
    그 뒤가 min_bars 일 미만이면 (최근 분할) 예전처럼 수정주가로 맞춘 전체를 씀"""
    if "chg_pct" not in g or len(g) < 2:
        return g
    c = g["close"].to_numpy(float)
    chg = g["chg_pct"].to_numpy(float)
    with np.errstate(all="ignore"):
        ratio = (c[1:] / (1 + chg[1:] / 100)) / c[:-1]
    ev = np.where(np.isfinite(ratio) & (np.abs(ratio - 1) > 0.15))[0]
    if not len(ev):
        return g
    start = int(ev[-1]) + 1
    if len(g) - start >= min_bars:
        return g.iloc[start:]
    g = g.copy()
    for col in ("open", "high", "low", "close"):
        g[col] = adjust(g, col)
    return g


def prepare(g: pd.DataFrame):
    """window → compute 에 넣을 (dates, o, h, l, c, v)"""
    w = window(g)
    return (w["date"].to_numpy(), w["open"].to_numpy(float), w["high"].to_numpy(float), w["low"].to_numpy(float),
            w["close"].to_numpy(float), w["volume"].to_numpy(float))


def adjust(g: pd.DataFrame, col: str) -> np.ndarray:
    """액면분할·병합 보정: KRX 등락률(chg_pct)로 계산한 전일 종가와 실제 전일 종가가 2% 넘게 다르면
    그 이전 가격 전체에 비율을 곱해 지금 가격 기준으로 맞춤 (수정주가)"""
    x = g[col].to_numpy(float)
    if "chg_pct" not in g or len(g) < 2:
        return x
    c = g["close"].to_numpy(float)
    chg = g["chg_pct"].to_numpy(float)
    with np.errstate(all="ignore"):
        exp_prev = c[1:] / (1 + chg[1:] / 100)
        ratio = exp_prev / c[:-1]
    ratio = np.where(np.isfinite(ratio) & (np.abs(ratio - 1) > 0.02), ratio, 1.0)
    f = np.ones(len(x))
    f[:-1] = np.cumprod(ratio[::-1])[::-1]        # t 이전 가격에 곱할 누적 비율
    return x * f


LEVEL_COLS = ("entry_low", "entry_high", "target1", "target2", "target3", "stop", "stop_pct", "rr")


def apply_to_ev(ev: pd.DataFrame, ohlcv: pd.DataFrame) -> int:
    """V2 평가표(ev)의 매매 계획 칸을 차트 기반 값으로 덮어씀 + 근거 칸 추가. 바꾼 종목 수"""
    L = compute_all(ohlcv, ev.index)
    if "target3" not in ev:
        ev["target3"] = np.nan
    for k in ("level_basis", "level_warn", "resistances", "supports", "zones", "notes"):
        ev[k] = pd.Series([None] * len(ev), index=ev.index, dtype=object)
    n = 0
    for code, r in L.items():
        if code not in ev.index:
            continue
        for k in LEVEL_COLS:
            ev.at[code, k] = r[k]
        ev.at[code, "level_basis"] = r["basis"]
        ev.at[code, "level_warn"] = r["level_warn"]
        ev.at[code, "resistances"] = r["resistances"]
        ev.at[code, "supports"] = r["supports"]
        ev.at[code, "zones"] = r["zones"]
        ev.at[code, "notes"] = r["notes"]
        n += 1
    ev.attrs["levels"] = "chart"
    return n


def _zones(close, atr, stop, S, lo1) -> list[dict]:
    """분할 매수 구간 (모두 손절가 위). 1차 = 현재가 +1% ~ 가까운 지지 (폭은 최대 1ATR)
    2·3차 = 1차 하단~손절가 사이 지지(스윙 저점·이평선·매물대) 우선, 모자라면 고르게 나눔 (ZONE_FILL)
    비중: 1개 100% · 2개 50/50 · 3개 30/30/40. 2·3차는 눌림이 올 때만 — 안 와도 1차만으로 계획대로"""
    rt = lambda x, m: int(round_tick(x, m))  # noqa: E731
    floor = stop + 0.3 * atr
    z1_low = min(close, max(lo1, close - 1.0 * atr, floor))
    z = [{"name": "1차", "weight": 100, "low": rt(z1_low, "down"), "high": rt(close * 1.01, "up"),
          "note": "현재가 ~ 가까운 지지 · 지금 가격대"}]
    w = z1_low - floor
    if w < 0.4 * atr:                                       # 손절가가 가까워 아래로 나눌 자리가 없음
        return z
    half = min(0.3 * atr, w / 6)
    picks = []
    for g in S:                                              # 지지만 (위에서 아래로, 0.5ATR 이상 간격)
        p = g["price"]
        if floor + half <= p <= z1_low - half and all(abs(p - q) >= 0.5 * atr for q, _ in picks):
            picks.append((p, f"{_label(g)} {_won(p)} 지지"))
        if len(picks) == 2:
            break
    for k in ((1, 2) if ZONE_FILL else ()):                  # (예전) 모자라면 고르게
        if len(picks) == 2:
            break
        p = z1_low - w * k / 3
        if all(abs(p - q) >= w / 4 for q, _ in picks):
            picks.append((p, "1차 하단과 손절가 사이 (아래 지지 없음)"))
    picks.sort(key=lambda t: -t[0])
    for (p, why), name in zip(picks, ("2차", "3차")):
        z.append({"name": name, "weight": 0, "low": rt(max(p - half, floor), "down"),
                  "high": rt(min(p + half, z1_low), "up"), "note": why + " · 눌림 때 추가 (안 와도 됨)"})
    for zz, wt in zip(z, {1: (100,), 2: (50, 50), 3: (30, 30, 40)}[len(z)]):
        zz["weight"] = wt
    return z


def _notes(close, atr, t1, t2, t3, stop, stop_lab, zones) -> dict:
    """목표·손절 설명 문장"""
    def tn(i, t, g, after):
        pct = (t / close - 1) * 100
        src = f"{_label(g)} 저항" if g else "위 저항 없음 → ATR 투영"
        return f"{i}차 목표 +{pct:.1f}% — {src}. {after}"
    out = {"target1": tn(1, *t1, "첫 저항이라 매물이 나오기 쉬운 자리 — 도달 시 일부 차익 실현 고려"),
           "target2": tn(2, *t2, "1차 돌파 후 다음 저항 — 남은 물량의 추가 차익 구간"),
           "target3": tn(3, *t3, "추세가 강할 때의 확장 목표 — 거래량이 붙을 때만 기대")}
    sp = (stop / close - 1) * 100
    out["stop"] = (f"손절 {sp:.1f}% — " + (f"{stop_lab} 지지 아래(지지 - 0.5ATR)" if stop_lab else "하루 변동폭(ATR) 기준")
                   + ". 종가가 이 아래로 마감하면 지지 붕괴로 보고 정리")
    if len(zones) > 1:
        out["zones"] = "분할 매수 " + " / ".join(f"{z['name']} {z['weight']}%" for z in zones) + " — 아래 구간은 눌림이 올 때만"
    return out
