"""당일단타 '케이스 비교' (2026-11-02 사용자 제안) — 수정하고 다음날 확인하는 대신 여러 전략(케이스)을 과거 데이터로 한꺼번에 돌려 비교

  케이스마다: 그날 후보를 최대 10개 고르고(전날 거래대금 상위 풀 안에서) → 진입 규칙 → 같은 청산 규칙(손절 −2.5% · 1차 +3% 절반 · 2차 +5%)
  청산 시각 변형 (장마감까지 · 10:30 · 10:00 · 09:40 에 정리) 도 같이 — 단타는 빨리 끝내는 게 낫다는 가설 검증
  ⚠ 과거 분봉엔 호가·뉴스·장중 수급이 없음 → 수급은 '전일 외국인·기관 순매수(일별)' 와 'NXT 프리마켓 등락(저장된 날만)' 으로 대신

  케이스 (CASES) — 각자 select(day) → [신호 dict] 를 돌려줌
    B0 지금 방식     09:10 점수 상위 10 중 눌림목형 (현재 실전 규칙)
    B1 지금 + 수급   B0 중 전일 외국인 순매수 > 0
    F1 외국인 전일   전일 외국인 순매수(거래대금 대비) 상위 10 → 09:01 바로
    F2 쌍끌이 전일   전일 외국인·기관 동반 순매수 상위 10 → 09:01 바로
    F5 외국인 5일    최근 5일 외국인 순매수 합(거래대금 대비) 상위 10 → 09:01 바로
    G1 갭상승+수급   시초 갭 +1~+6% 이고 전일 외국인 순매수 > 0 (갭 큰 순 10) → 09:01 바로
    S1 전일 급등     전일 +10% 이상 급등 다음날 시가 직후 (전일 거래대금 큰 순 10)
    M1 시초 거래대금 09:00~09:04 누적 거래대금 상위 10 중 상승 중 → 09:05
    O1 시초범위 돌파 09:00~09:09 거래대금 상위 10 중 시초 고가 돌파 (09:10~09:39 첫 돌파)
    V1 급락 뒤 반등  09:20 안에 시가 대비 −2% 급락 → 저점 +1.5% 반등 확인 (09:30 까지) 낙폭 큰 순 10
    N1 NXT 프리마켓  08시대 NXT 등락 +1% 이상 상위 10 → 09:01 바로 (기록 있는 날만)
"""
from __future__ import annotations

import pandas as pd

from ..engine import daytrade as dt

STOP, T1, T2 = 0.025, 0.03, 0.05           # 고정 청산 규칙 (손절 · 1차 절반 · 2차)
MIN_STOP, MAX_STOP = 0.008, 0.03            # 구조적 손절(시초범위 저가·반등 저점)도 이 폭 안으로
PICK = 10
EXITS = [("장마감까지", None), ("10:30 청산", "10:30"), ("10:00 청산", "10:00"), ("09:40 청산", "09:40")]


def hm(bars: pd.DataFrame) -> pd.Series:
    return bars["time"].dt.strftime("%H:%M")


def idx_at_or_before(bars: pd.DataFrame, t: str) -> int | None:
    """t 시각(분) 이하 마지막 봉의 위치 — 없으면 None"""
    ok = (hm(bars) <= t).to_numpy().nonzero()[0]
    return int(ok[-1]) if len(ok) else None


def cum_value(bars: pd.DataFrame, i: int) -> float:
    b = bars.iloc[:i + 1]
    if "value" in b and float(b["value"].iloc[-1]) > 0:
        return float(b["value"].iloc[-1])
    return float((b["close"] * b["volume"]).sum())


def entry_after(bars: pd.DataFrame, i: int, stop: float | None = None, stop_pct: float = STOP) -> dict | None:
    """신호 봉 i 가 끝난 뒤(= 다음 봉 시가)에 진입. stop 가격을 주면 진입가의 MIN_STOP~MAX_STOP 안으로 맞춤"""
    if i + 1 >= len(bars):
        return None
    px = float(bars["open"].iloc[i + 1])
    if px <= 0:
        return None
    sp = px * (1 - stop_pct) if stop is None else min(max(stop, px * (1 - MAX_STOP)), px * (1 - MIN_STOP))
    return {"idx": i + 1, "time": pd.Timestamp(bars["time"].iloc[i + 1]).strftime("%H:%M"), "entry": px, "stop": sp,
            "t1": px * (1 + T1), "t2": px * (1 + T2)}


def grade_sig(sig: dict, bars: pd.DataFrame, until: str | None = None) -> dict | None:
    """진입 신호 + 그날 1분봉 → 결과. until 이 있으면 그 시각(분)까지만 보고 남은 건 그 봉 종가로 정리 (진입이 until 이후면 거래 없음)"""
    after = bars.iloc[sig["idx"]:]
    if until:
        if sig["time"] >= until:
            return None
        after = after[hm(after) <= until]
    if after.empty:
        return None
    r = dt.simulate_exit(after, sig["entry"], sig["stop"], sig["t1"], sig["t2"])
    return {**r, "time": sig["time"], "entry": round(sig["entry"], 1)}


def top(scores: dict[str, float], n: int = PICK) -> list[str]:
    return [c for c, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:n]]


# ---------- 케이스: select(d) → [{code, idx, time, entry, stop, t1, t2, ...}] ----------
#  d: {codes, bars{code: DF}, prev_close, f1, i1, f5, gap, prev_chg, nxt, base{code: 신호|None}, rank{code: 점수}}

def _open_entry(d: dict, codes: list[str]) -> list[dict]:
    out = []
    for c in codes:
        s = entry_after(d["bars"][c], 0)
        if s:
            out.append({"code": c, **s})
    return out


def sel_f1(d):
    return _open_entry(d, top({c: v for c, v in d["f1"].items() if v > 0 and c in d["bars"]}))


def sel_f2(d):
    return _open_entry(d, top({c: d["f1"][c] + d["i1"][c] for c in d["f1"]
                               if c in d["bars"] and d["f1"][c] > 0 and d["i1"].get(c, 0) > 0}))


def sel_f5(d):
    return _open_entry(d, top({c: v for c, v in d["f5"].items() if v > 0 and c in d["bars"]}))


def sel_g1(d):
    return _open_entry(d, top({c: g for c, g in d["gap"].items() if 1.0 <= g <= 6.0 and d["f1"].get(c, 0) > 0 and c in d["bars"]}))


def sel_s1(d):
    return _open_entry(d, top({c: d["prev_value"].get(c, 0) for c, v in d["prev_chg"].items() if v >= 10.0 and c in d["bars"]}))


def sel_m1(d):
    sc = {}
    for c, b in d["bars"].items():
        i = idx_at_or_before(b, "09:04")
        if i is None or i < 3:
            continue
        px, op = float(b["close"].iloc[i]), float(b["open"].iloc[0])
        pc = d["prev_close"].get(c)
        if op > 0 and px > op and pc and px > pc:
            sc[c] = cum_value(b, i)
    out = []
    for c in top(sc):
        s = entry_after(d["bars"][c], idx_at_or_before(d["bars"][c], "09:04"))
        if s:
            out.append({"code": c, **s})
    return out


def sel_o1(d):
    sc, orr = {}, {}
    for c, b in d["bars"].items():
        i = idx_at_or_before(b, "09:09")
        if i is None or i < 5:
            continue
        pc = d["prev_close"].get(c)
        if pc and float(b["close"].iloc[i]) > pc:
            sc[c] = cum_value(b, i)
            orr[c] = (i, float(b["high"].iloc[:i + 1].max()), float(b["low"].iloc[:i + 1].min()))
    out = []
    for c in top(sc):
        b, (i0, hi, lo) = d["bars"][c], orr[c]
        h = hm(b)
        for j in range(i0 + 1, len(b)):
            if h.iloc[j] > "09:39":
                break
            if float(b["close"].iloc[j]) > hi:
                s = entry_after(b, j, stop=lo)
                if s:
                    out.append({"code": c, **s})
                break
    return out


def make_v1(dip: float = -2.0, reb: float = 1.5, end: str = "09:30", low_end: str = "09:19", keep=None, pick: int = PICK):
    """급락 뒤 반등: low_end 까지의 최저가가 시가 대비 dip% 이하로 떨어진 뒤, 그 저점 +reb% 를 end 까지 회복하면 다음 봉 시가에 진입.
    keep(d, code) 가 있으면 그 조건을 통과한 종목만 (수급·갭·NXT 결합용)"""
    def sel(d):
        found = {}
        for c, b in d["bars"].items():
            if len(b) < 15 or (keep and not keep(d, c)):
                continue
            h = hm(b)
            op = float(b["open"].iloc[0])
            if op <= 0:
                continue
            w = b[h <= low_end]
            if w.empty:
                continue
            li = int(w["low"].to_numpy().argmin())
            low = float(w["low"].iloc[li])
            dp = (low / op - 1) * 100
            if dp > dip:
                continue
            for j in range(li + 1, len(b)):
                if h.iloc[j] > end:
                    break
                if float(b["close"].iloc[j]) >= low * (1 + reb / 100):
                    s = entry_after(b, j, stop=low * 0.997)
                    if s:
                        found[c] = (dp, {"code": c, **s})
                    break
        return [v for _, v in sorted(found.values(), key=lambda x: x[0])[:pick]]
    return sel


sel_v1 = make_v1()


def sel_n1(d):
    nx = d.get("nxt")
    if not nx:
        return []
    return _open_entry(d, top({c: v for c, v in nx.items() if v >= 1.0 and c in d["bars"]}))


def _base(d, need_flow=False):
    """지금 방식: 09:10 점수 상위 10 중 눌림목형 진입 (신호는 엔진이 낸 진입가 · 손절 · 목표 그대로)"""
    out = []
    for c in top({c: v for c, v in d["rank"].items() if v is not None}):
        s = d["base"].get(c)
        if not s or s.get("type") != "눌림목":
            continue
        if need_flow and d["f1"].get(c, 0) <= 0:
            continue
        b = d["bars"][c]
        after = (b["time"] > pd.Timestamp(f"{d['day']} {s['time']}")).to_numpy().nonzero()[0]
        if len(after):
            out.append({"code": c, "idx": int(after[0]), "time": s["time"], "entry": float(s["entry"]), "stop": float(s["stop"]),
                        "t1": float(s["t1"]), "t2": float(s["t2"])})
    return out


CASES = [
    ("B0", "지금 방식 (09:10 상위10 눌림목)", lambda d: _base(d)),
    ("B1", "지금 방식 + 전일 외국인 순매수", lambda d: _base(d, True)),
    ("F1", "전일 외국인 순매수 상위10 · 09:01", sel_f1),
    ("F2", "전일 외국인·기관 쌍끌이 · 09:01", sel_f2),
    ("F5", "5일 외국인 누적 순매수 · 09:01", sel_f5),
    ("G1", "갭상승+전일 외국인 순매수 · 09:01", sel_g1),
    ("S1", "전일 급등(+10%) 다음날 · 09:01", sel_s1),
    ("M1", "시초 5분 거래대금 상위 · 09:05", sel_m1),
    ("O1", "시초범위(10분) 돌파", sel_o1),
    ("V1", "급락(−2%) 뒤 반등 확인", sel_v1),
    ("N1", "NXT 프리마켓 강세 · 09:01", sel_n1),
]


def flow_features(flows: pd.DataFrame | None, ohlcv: pd.DataFrame, dates: list, di: int, codes: list[str]) -> dict:
    """전 거래일(dates[di-1]) 기준 수급 특징: f1·i1 = 전일 외국인·기관 순매수 / 전일 거래대금, f5 = 최근 5거래일 외국인 순매수 합 / 같은 기간 거래대금 합"""
    out = {"f1": {}, "i1": {}, "f5": {}, "prev_value": {}, "prev_chg": {}}
    if di < 2:
        return out
    p, pp = pd.Timestamp(dates[di - 1]), pd.Timestamp(dates[di - 2])
    o = ohlcv[ohlcv["date"].isin([p, pp]) & ohlcv["code"].isin(codes)]
    pv = o[o["date"] == p].set_index("code")
    pb = o[o["date"] == pp].set_index("code")
    for c in codes:
        if c in pv.index:
            v = float(pv.loc[c, "value"]) if "value" in pv else float(pv.loc[c, "close"] * pv.loc[c, "volume"])
            out["prev_value"][c] = v
            if c in pb.index and float(pb.loc[c, "close"]) > 0:
                out["prev_chg"][c] = (float(pv.loc[c, "close"]) / float(pb.loc[c, "close"]) - 1) * 100
    if flows is None or flows.empty:
        return out
    d5 = [pd.Timestamp(x) for x in dates[max(0, di - 5):di]]
    f = flows[flows["date"].isin(d5) & flows["code"].isin(codes)]
    f1 = f[f["date"] == p].set_index("code")
    for c in codes:
        v = out["prev_value"].get(c)
        if v and c in f1.index:
            out["f1"][c] = float(f1.loc[c, "foreign"]) / v
            out["i1"][c] = float(f1.loc[c, "institution"]) / v
    o5 = ohlcv[ohlcv["date"].isin(d5) & ohlcv["code"].isin(codes)]
    vs = (o5["value"] if "value" in o5 else o5["close"] * o5["volume"]).groupby(o5["code"]).sum()
    fs = f.groupby("code")["foreign"].sum()
    for c in codes:
        if c in fs.index and vs.get(c, 0) > 0:
            out["f5"][c] = float(fs[c]) / float(vs[c])
    return out


# ---------- 2라운드: V1 다듬기 + 결합 ----------
def _f(d, c):
    return d["f1"].get(c, 0) > 0


def _gap(d, c):
    return d["gap"].get(c, -99) >= 1.0


def _nxt(d, c):
    return (d.get("nxt") or {}).get(c, -99) >= 1.0


ROUND2 = [
    ("V1", "기준 V1 (−2% · +1.5% · ~09:30)", sel_v1),
    ("V2", "낙폭 −1.5%", make_v1(dip=-1.5)),
    ("V3", "낙폭 −3%", make_v1(dip=-3.0)),
    ("V4", "반등 +1%", make_v1(reb=1.0)),
    ("V5", "반등 +2%", make_v1(reb=2.0)),
    ("V6", "진입 마감 09:20", make_v1(end="09:20", low_end="09:12")),
    ("V7", "진입 마감 09:39", make_v1(end="09:39", low_end="09:30")),
    ("V8", "V1 + 전일 외국인 순매수", make_v1(keep=_f)),
    ("V9", "V1 + 갭상승(+1%↑)", make_v1(keep=_gap)),
    ("VA", "V1 + NXT 강세", make_v1(keep=_nxt)),
    ("VB", "V1 상위 5개만", make_v1(pick=5)),
    ("G1", "참고: 갭상승+외국인 · 09:01", sel_g1),
    ("N1", "참고: NXT 프리마켓 강세 · 09:01", sel_n1),
]


# ---------- 3라운드: 09:39 마감 V7 을 기본으로 결합 ----------
def _gapn(th):
    return lambda d, c: d["gap"].get(c, -99) >= th


def _and(*fs):
    return lambda d, c: all(f(d, c) for f in fs)


_E = dict(end="09:39", low_end="09:30")
ROUND3 = [
    ("W0", "기준 V7 (~09:39 · +1.5%)", make_v1(**_E)),
    ("W1", "V7 + 반등 +1%", make_v1(reb=1.0, **_E)),
    ("W2", "V7 + 낙폭 −1.5%", make_v1(dip=-1.5, **_E)),
    ("W3", "V7 + 갭상승 +1%↑", make_v1(keep=_gapn(1.0), **_E)),
    ("W4", "V7 + 갭상승 +0.5%↑", make_v1(keep=_gapn(0.5), **_E)),
    ("W5", "V7 + 갭상승 +2%↑", make_v1(keep=_gapn(2.0), **_E)),
    ("W6", "V7 + 반등 +1% + 갭 +1%↑", make_v1(reb=1.0, keep=_gapn(1.0), **_E)),
    ("W7", "V7 + 갭 +1%↑ + 낙폭 −1.5%", make_v1(dip=-1.5, keep=_gapn(1.0), **_E)),
    ("W8", "V7 상위 5개만", make_v1(pick=5, **_E)),
    ("W9", "V7 상위 15개", make_v1(pick=15, **_E)),
    ("WA", "참고: 마감 09:45 (범위 밖)", make_v1(end="09:45", low_end="09:35")),
    ("WB", "참고: 마감 09:30 (V1)", sel_v1),
]


# ---------- 4라운드: 미래 정보를 쓰지 않는 (실시간과 같은) V1 ----------
# 앞 라운드(make_v1)는 "09:30 까지의 최저가" 를 통째로 미리 보고 그 뒤 신호를 골랐다 → 09:30 전에 난 신호는
# '그 뒤로 더 낮은 저점이 안 나온다' 는 미래 정보를 쓴 셈. 여기서는 봉마다 '그때까지의 최저가' 만 쓰고,
# 종목은 신호가 먼저 난 순서(같은 시각이면 낙폭 큰 순)로 pick 개까지 → 장중에 그대로 따라 할 수 있는 규칙.
def make_v1c(dip: float = -2.0, reb: float = 1.0, end: str = "09:39", keep=None, pick: int = PICK):
    def sel(d):
        found = []
        for c, b in d["bars"].items():
            if len(b) < 15 or (keep and not keep(d, c)):
                continue
            op = float(b["open"].iloc[0])
            if op <= 0:
                continue
            h = hm(b)
            lows = b["low"].to_numpy(dtype=float)
            closes = b["close"].to_numpy(dtype=float)
            run_low, run_i = float("inf"), -1
            for j in range(len(b)):
                if h.iloc[j] > end:
                    break
                if lows[j] < run_low:
                    run_low, run_i = lows[j], j
                if j == run_i or (run_low / op - 1) * 100 > dip:
                    continue
                if closes[j] >= run_low * (1 + reb / 100):
                    s = entry_after(b, j, stop=run_low * 0.997)
                    if s:
                        found.append((s["time"], (run_low / op - 1) * 100, {"code": c, **s}))
                    break
        found.sort(key=lambda x: (x[0], x[1]))
        return [x[2] for x in found[:pick]]
    return sel


ROUND4 = [
    ("C0", "기준 V7 (예전 방식·미래 정보 포함)", make_v1(reb=1.0, end="09:39", low_end="09:30")),
    ("C1", "실시간 방식 · 반등 +1% · ~09:39", make_v1c()),
    ("C2", "실시간 · 반등 +1.5%", make_v1c(reb=1.5)),
    ("C3", "실시간 · 낙폭 −1.5%", make_v1c(dip=-1.5)),
    ("C4", "실시간 · 낙폭 −3%", make_v1c(dip=-3.0)),
    ("C5", "실시간 · 갭상승 +1%↑", make_v1c(keep=_gapn(1.0))),
    ("C6", "실시간 · 갭 +1%↑ · 반등 +1.5%", make_v1c(reb=1.5, keep=_gapn(1.0))),
    ("C7", "실시간 · 갭 +2%↑", make_v1c(keep=_gapn(2.0))),
    ("C8", "실시간 · 마감 09:30", make_v1c(end="09:30")),
    ("C9", "실시간 · 상위 20개", make_v1c(pick=20)),
]


# ---------- 5라운드: 지지·저항으로 손절·목표 정하기 (갭상승 종목) ----------
#  고정 % (손절 2.5 / +3 / +5) 대신, 진입 순간까지 알 수 있는 가격대에서 고른다.
#   지지(손절) 후보: 전일 종가(갭 메우기) · 전일 저가 · 전일 고가(돌파했다면) · VWAP · 시초 5분 저점·고점 · 당일 저가 · 1분봉 스윙 저점
#   저항(목표) 후보: 전일 고가 · 5·20·60일 최고가 · 당일 고가(그보다 아래일 때) · 시초 5분 고점
#   손절 = 진입가보다 SR_MIN_RISK 이상 아래에 있는 가장 가까운 지지 − 0.3%  (SR_MAX_RISK 보다 멀면 그 거래는 안 함)
#   1차 = 진입가 +1.5% 이상인 가장 가까운 저항, 2차 = 그 위 다음 저항(없으면 같은 폭만큼 더). 저항이 없으면 +3% / +5%
SR_MIN_RISK, SR_MAX_RISK, SR_BUF = 0.006, 0.035, 0.003
SR_T1_MIN, SR_T1_MAX = 0.015, 0.06


def daily_levels(ohlcv: pd.DataFrame, dates: list, di: int, codes: list[str]) -> dict:
    """전 거래일까지의 일봉 가격대: ph·pl = 전일 고가·저가, h5·h20·h60 = 최근 5·20·60거래일 최고가"""
    out: dict[str, dict] = {}
    if di < 2:
        return out
    ds = [pd.Timestamp(x) for x in dates[max(0, di - 60):di]]
    o = ohlcv[ohlcv["date"].isin(ds) & ohlcv["code"].isin(codes)].sort_values("date")
    for c, g in o.groupby("code"):
        hi = g["high"].to_numpy(float)
        out[c] = {"ph": float(hi[-1]), "pl": float(g["low"].iloc[-1]),
                  "h5": float(hi[-5:].max()), "h20": float(hi[-20:].max()), "h60": float(hi.max())}
    return out


def sr_plan(info: pd.DataFrame, p: float, lv: dict, pc: float | None) -> dict | None:
    """info = 진입 직전까지의 1분봉, p = 진입가 → {stop, t1, t2, basis...} 또는 None(지지가 없거나 너무 멀다)"""
    if p <= 0 or info is None or info.empty:
        return None
    sup = {"전일 종가": pc, "전일 저가": lv.get("pl"), "전일 고가": lv.get("ph")}
    pairs = list(sup.items())
    orh = dh = 0.0
    if len(info) >= 3:                       # 분봉이 3개 미만(= 09:01 시가 진입)이면 전일 가격대만
        vw = dt.vwap(info)
        head = info.iloc[:5]
        orl, orh = float(head["low"].min()), float(head["high"].max())
        dl, dh = float(info["low"].min()), float(info["high"].max())
        pairs += [("VWAP", vw), ("시초 저점", orl), ("시초 고점", orh), ("당일 저가", dl)] + [("스윙 저점", v) for v in dt.swing_lows(info)]
    below = [(float(v), k) for k, v in pairs if v and v <= p * (1 - SR_MIN_RISK)]
    if not below:
        return None
    s_px, s_name = max(below)
    stop = s_px * (1 - SR_BUF)
    risk = 1 - stop / p
    if risk > SR_MAX_RISK:
        return None
    res = sorted({round(float(v), 2) for v in (lv.get("ph"), lv.get("h5"), lv.get("h20"), lv.get("h60"), dh, orh)
                  if v and v >= p * (1 + SR_T1_MIN)})
    merged: list[float] = []
    for v in res:                                   # 0.5% 안에 모인 가격대는 하나로
        if not merged or v > merged[-1] * 1.005:
            merged.append(v)
    if merged:
        t1 = min(merged[0], p * (1 + SR_T1_MAX))
        nxt = [v for v in merged if v >= t1 * 1.01]
        t2 = min(nxt[0], p * 1.10) if nxt else t1 + (t1 - p)
    else:
        t1, t2 = p * 1.03, p * 1.05
    return {"stop": stop, "t1": t1, "t2": t2, "risk": round(risk * 100, 2), "t1pct": round((t1 / p - 1) * 100, 2),
            "rr": round((t1 - p) / (p - stop), 2), "basis": s_name}


def with_sr(sel, rr_min: float | None = None):
    def f(d):
        out = []
        for s in sel(d):
            c = s["code"]
            plan = sr_plan(d["bars"][c].iloc[:s["idx"]], s["entry"], d.get("lvl", {}).get(c, {}), d["prev_close"].get(c))
            if not plan or (rr_min and plan["rr"] < rr_min):
                continue
            out.append({**s, **plan})
        return out
    return f


def sel_gap_open(d):
    """갭 +1%~+6% 종목 중 전일 거래대금 상위 10개를 09:01 시가에"""
    return _open_entry(d, top({c: d["prev_value"].get(c, 0) for c, g in d["gap"].items() if 1.0 <= g <= 6.0 and c in d["bars"]}))


def sel_gap_orb(d):
    """갭상승 + 시초 5분 고점 돌파: 09:05 까지 고점을 09:06~09:39 사이 종가로 넘으면 다음 봉 시가 (먼저 난 순서 10개)"""
    found = []
    for c, g in d["gap"].items():
        b = d["bars"].get(c)
        if b is None or len(b) < 12 or not 1.0 <= g <= 8.0:
            continue
        h = hm(b)
        orh = float(b["high"].iloc[:5].max())
        for j in range(5, len(b)):
            if h.iloc[j] > "09:39":
                break
            if float(b["close"].iloc[j]) > orh:
                s = entry_after(b, j)
                if s:
                    found.append((s["time"], -g, {"code": c, **s}))
                break
    found.sort(key=lambda x: (x[0], x[1]))
    return [x[2] for x in found[:PICK]]


def sel_gap_vwap(d):
    """갭상승 + VWAP 눌림 재상승: VWAP 위에 있다가 VWAP 근처(+0.3%)까지 내려온 뒤 다시 VWAP 위로 마감하며 직전 봉 고가를 넘으면 진입"""
    found = []
    for c, g in d["gap"].items():
        b = d["bars"].get(c)
        if b is None or len(b) < 12 or not 1.0 <= g <= 8.0:
            continue
        h = hm(b)
        touched = False
        for j in range(5, len(b)):
            if h.iloc[j] > "09:39":
                break
            vw = dt.vwap(b.iloc[:j + 1])
            lo, cl = float(b["low"].iloc[j]), float(b["close"].iloc[j])
            if lo <= vw * 1.003:
                touched = True
            if touched and cl > vw * 1.002 and cl > float(b["high"].iloc[j - 1]) and float(b["close"].iloc[j - 1]) > 0:
                s = entry_after(b, j)
                if s:
                    found.append((s["time"], -g, {"code": c, **s}))
                break
    found.sort(key=lambda x: (x[0], x[1]))
    return [x[2] for x in found[:PICK]]


_ENTRIES = [("1", "갭상승 시가 진입", sel_gap_open), ("2", "갭+급락 뒤 반등(C5)", make_v1c(keep=_gapn(1.0))),
            ("3", "갭+시초고점 돌파", sel_gap_orb), ("4", "갭+VWAP 눌림 재상승", sel_gap_vwap)]
ROUND5 = []
for _k, _n, _fn in _ENTRIES:
    ROUND5 += [(f"S{_k}a", f"{_n} · 고정 2.5/3/5", _fn), (f"S{_k}b", f"{_n} · 지지저항", with_sr(_fn)),
               (f"S{_k}c", f"{_n} · 지지저항 + 손익비≥1.2", with_sr(_fn, 1.2))]
