"""상한가포착 (LC-0.1) — 장중에 '오늘 상한가로 끝까지 잠길' 종목을 골라 당일 매수 → 다음 날 시초 갭에서 매도

근거: 상파 검증(2021~2026)에서 상한가 '종가' 종목은 다음 날 시가 갭 평균 +6~7%, 장중 도달 후 풀린 종목은 갭 0% 안팎.
     다음 날 시가 이후로는 평균 하락 → 다음 날 시초에 판다.
원칙: +27% 이상은 '상한가에 가까운' 종목을 찾는 조건일 뿐 유지를 보장하지 않는다. 남은 여력과 실제 체결 흐름
     (상한가 매수잔량이 유지되는지 · 상한가에서 실제로 팔리는 물량)을 함께 본다.

1단계 — 상한가 강세 후보: 보통주 · 오늘 +20% 이상 · 판정 시점 누적 거래대금 100억 이상 · 종합 점수 75 이상
2단계 — 매수 검토 후보 (1단계 + 모두)
  · 상한가 도달 또는 +27% 이상 (도달 / 미도달은 따로 표시·평가)
  · 풀림 0~1회. 1회 풀렸으면 '바로 다시 잠기고(3분 안) 잔량이 회복' 된 경우만 (풀린 뒤 매도세 지속 → 탈락)
  · 위험 신호 없음: 잔량 급감 · 지금 풀려 있음 · 거래량 급감 + 잔량 감소 · (미도달) 매도 잔량 우위
  · 매수 가격 · 손실 위험을 계산할 수 있을 것

100점 (초기 가설 — 분봉 되돌려 보기·실전 기록으로 조정)
  잔량 두께·유지 25  두께 13 = 상한가 매수잔량 ÷ 오늘 거래대금(금액) 7 + ÷ 상장주식 수 6
                     유지 12 = 최근 1분 잔량 변화 7 + 상한가 체결(팔린) 물량 ÷ 잔량 5 (적을수록)
                     미도달: 총 매수잔량 ÷ 총 매도잔량 13 + 최근 5분 상승 봉 거래량 비중·가격 12
                     호가 없음(되돌려 보기) → 이 몫을 빼고 75점 만점을 100점으로 환산
  도달 시각     15  처음엔 모든 시간 같은 7.5 (중립). 분봉 검증에서 시간대별 유지율·다음 날 수익률을 보고 정함
  풀림 이력     15  0회 15 · 1회 9 · 2회 4 · 3회↑ 0, 풀린 시간이 짧고 바로 다시 잠기면 +, 지금 풀려 있으면 −
  재료          15  뉴스 호재 9 · 없음/중립 4.5 · 악재 0 + 오늘 처음 나온 재료 3 + 공시·계약 등 확인되는 재료 3
  업종 동반     10  같은 업종 상승 종목 비율 5 + 업종 등락률(거래대금 가중) 5 — 1시간마다 올라오는 업종 강도 결과 사용
                     (전 종목 시세를 1분마다 받지 않음 · 업종 강도가 아직 없으면 5 중립)
  첫 상한가     10  최근 20일 상한가 없음 10 · 어제 상한가(연속) 2 · 그 외 이력 5
  과열·추격 위험 10  감점형: 기본 10. 상승률이 높다는 이유만으로는 깎지 않음.
                     거래량 급감 + 잔량 감소가 겹치면 −6 · 20일 +80%↑ 급등 −3 · 거래량 급감만 −2
매매 계획 (주문 없음 · 알림·관찰용)
  매수: 상한가 가격 대기 (미도달이면 현재가). 잔량이 두꺼우면 체결 안 될 수 있음
  당일 '조건 무효' 가격 = 전일 종가 +20% (여기 아래로 밀리면 무효) → 손실 위험 %
  다음 날: 시가에 절반 → 나머지는 09:30 까지 고점 대비 −3% 이탈 시 매도 · 09:30 시간 청산
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .daytrade import ramp, rt
from .uplimit import limit_price

VERSION = "LC-0.1"
COST = 0.0025                 # 왕복 비용 (비율)
MIN_CHG = 20.0                # 대상: +20% 이상
NEAR_CHG = 27.0               # 2단계: 상한가 도달 또는 +27% 이상
MIN_VALUE = 100e8             # 판정 시점 누적 거래대금 100억
STAGE1 = 75.0                 # 1단계 점수
RELOCK_FAST = 3               # 풀린 뒤 3분 안에 다시 잠기면 '즉시 재잠금'
TRAIL = 0.03                  # 다음 날 나머지: 고점 대비 −3%
EXIT_TIME = "09:30"
LAST_NEW = "15:20"            # 15:20 이후(단일가)는 새로 잡지 않음
PARTS = {"bid25": ("잔량 두께·유지", 25), "time15": ("도달 시각", 15), "rel15": ("풀림 이력", 15),
         "news15": ("재료", 15), "sec10": ("업종 동반", 10), "first10": ("첫 상한가", 10),
         "heat10": ("과열·추격 위험", 10)}
EXIT_RULES = ["다음 날 시가에 절반 매도",
              f"나머지는 {EXIT_TIME} 까지 그날 고점 대비 −3% 밀리면 매도",
              f"{EXIT_TIME} 까지 남은 몫은 전량 매도 (시간 청산)",
              "오늘 상한가가 풀려 +20% 아래로 밀리면 '조건 무효' — 들고 가지 않음"]
OFFICIAL = re.compile(r"공시|계약|수주|체결|승인|허가|특허|인수|합병|임상|선정|최대주주")


def is_limit(price: float, limit: float) -> bool:
    return bool(limit and price and price >= limit - 1e-9)


# ---------------------------------------------------------------- 상한가 잠김·풀림
def lock_profile(bars: pd.DataFrame | None, limit: float) -> dict:
    """오늘 1분봉으로 상한가 도달·풀림 재구성. 잠김 = 그 분 종가가 상한가.
    풀림 = 도달 뒤 종가가 상한가 아래인 구간 (도달한 분에 종가가 아래면 그것도 1회)
    상한가에 잠겨 체결이 없던 분은 봉이 없음 → 빠진 분은 앞 상태가 이어진 것으로 봄 (풀림 횟수에 영향 없음)"""
    out = {"reached": False, "reach_time": None, "releases": 0, "release_min": 0, "max_release": 0,
           "last_release": 0, "locked_now": False, "locked_min": 0, "relocked": False, "hold_pct": None}
    if bars is None or len(bars) == 0 or not limit:
        return out
    b = bars.sort_values("time")
    hit = np.flatnonzero(b["high"].to_numpy(float) >= limit - 1e-9)
    if len(hit) == 0:
        return out
    seq = b["close"].to_numpy(float)[hit[0]:] >= limit - 1e-9
    runs, cur = [], 0                                # 풀린 구간 길이(분)
    for s in seq:
        if not s:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    open_run = cur                                   # 지금 풀려 있는 중이면 그 길이
    allr = runs + ([open_run] if open_run else [])
    out.update({"reached": True, "reach_time": pd.Timestamp(b["time"].iloc[hit[0]]).strftime("%H:%M"),
                "releases": len(allr), "release_min": int(sum(allr)), "max_release": int(max(allr) if allr else 0),
                "last_release": int(allr[-1]) if allr else 0, "locked_now": bool(seq[-1]),
                "locked_min": int(seq.sum()), "relocked": bool(runs) and bool(seq[-1]),
                "hold_pct": round(float(seq.mean()) * 100, 1)})
    return out


def time_bucket(hm: str | None) -> str:
    if not hm:
        return "-"
    return "09시" if hm < "10:00" else ("10시" if hm < "11:00" else ("11~12시" if hm < "13:00" else "13시 이후"))


# ---------------------------------------------------------------- 호가 잔량
def book_metrics(book: dict | None, hist: list[dict] | None, value: float, limit: float, listed: float | None,
                 last_vol: float | None, locked_now: bool) -> dict | None:
    """book = {bid1, bid_qty(1호가 매수잔량), ask1, ask_qty, total_bid, total_ask} · hist = 이전 기록 [{bid_qty, locked}]
    상한가에 잠겨 있으면 1호가 매수 = 상한가 · 매도 잔량 0. last_vol = 마지막 1분 거래량 (잠겨 있으면 상한가에서 팔린 물량)"""
    if not book:
        return None
    bq = float(book.get("bid_qty") or 0)
    at_limit = locked_now and is_limit(float(book.get("bid1") or 0), limit)
    out = {"at_limit": at_limit, "bid_qty": bq, "total_bid": float(book.get("total_bid") or 0),
           "total_ask": float(book.get("total_ask") or 0)}
    if at_limit and bq > 0:
        out["bid_value_ratio"] = round(bq * limit / value, 4) if value > 0 else None   # 잔량 금액 ÷ 오늘 거래대금
        out["bid_float_pct"] = round(bq / listed * 100, 3) if listed else None          # ÷ 상장주식 수 (%)
        prev = [h for h in (hist or []) if h.get("locked") and h.get("bid_qty")]
        if prev:
            out["chg1"] = round(bq / float(prev[-1]["bid_qty"]) - 1, 3)                  # 최근 1분 변화율
            base = prev[-5] if len(prev) >= 5 else prev[0]
            out["chg5"] = round(bq / float(base["bid_qty"]) - 1, 3)                      # 최근 약 5분
        if last_vol is not None:
            out["sold_ratio"] = round(float(last_vol) / bq, 3)                            # 1분 동안 팔린 물량 ÷ 잔량
    return out


def bid_score(bm: dict | None, bars: pd.DataFrame | None, locked_now: bool) -> float | None:
    """잔량 두께·유지 25. 호가가 없으면 None (환산)"""
    if bm is None:
        return None
    if locked_now and bm.get("at_limit"):
        thick = ramp(bm.get("bid_value_ratio"), [(0, 0), (0.05, 2), (0.15, 4.5), (0.4, 7)]) \
            + ramp(bm.get("bid_float_pct"), [(0, 0), (0.2, 2), (0.7, 4.5), (2.0, 6)])
        c1 = bm.get("chg1")
        keep = (ramp(c1, [(-0.3, 0), (-0.1, 3), (0, 5), (0.05, 7)]) if c1 is not None else 4.0) \
            + (ramp(-bm["sold_ratio"], [(-0.5, 0), (-0.2, 2), (-0.05, 4), (0, 5)]) if bm.get("sold_ratio") is not None else 3.0)
        return round(min(thick + keep, 25.0), 2)
    # 아직 상한가가 아님(또는 풀려 있음): 매수 우위 · 최근 5분 흐름
    tb, ta = bm.get("total_bid") or 0, bm.get("total_ask") or 0
    pres = ramp(tb / ta if ta > 0 else (3 if tb > 0 else 0), [(0.5, 0), (1.0, 5), (2.0, 10), (3.0, 13)])
    flow = 0.0
    if bars is not None and len(bars) >= 6:
        last = bars.iloc[-5:]
        up = float(last.loc[last["close"] >= last["open"], "volume"].sum() / max(last["volume"].sum(), 1))
        mom = float(last["close"].iloc[-1] / bars["close"].iloc[-6] - 1)
        flow = ramp(up, [(0.4, 0), (0.7, 6)]) + ramp(mom, [(-0.01, 0), (0, 3), (0.02, 6)])
    return round(min(pres + flow, 25.0), 2)


# ---------------------------------------------------------------- 나머지 항목
def release_score(lp: dict) -> float:
    if not lp["reached"]:
        return 7.5                                                     # 아직 도달 전 — 이력 없음 (중간값)
    n = lp["releases"]
    if n == 0:
        return 15.0
    s = {1: 9.0, 2: 4.0}.get(n, 0.0)
    s += 3 if lp["max_release"] <= 2 else (1.5 if lp["max_release"] <= 5 else 0)       # 풀린 시간 짧음 · 재잠금 빠름
    s += 2 if lp["relocked"] and lp["last_release"] <= RELOCK_FAST else 0
    s -= 0 if lp["locked_now"] else 5                                                    # 지금 풀려 있음
    return float(max(0.0, min(s, 15.0)))


def news_detail(items: list[dict] | None, level: str | None, today: str) -> dict:
    """재료: 수준(호재/중립/악재) + 오늘 처음 나온 재료인지 + 공시·계약 등 확인 가능한 재료인지 (제목 기준)"""
    items = items or []
    from ..analysis.news_flags import _tone
    pos = [it for it in items if _tone(it.get("title", "")) > 0]
    fresh = bool(pos) and all(str(it.get("time", ""))[:10] >= today for it in pos)
    official = any(OFFICIAL.search(it.get("title", "")) for it in pos)
    return {"level": level, "fresh": fresh, "official": official, "pos": [it["title"] for it in pos[:2]]}


def news_score(nd: dict | None) -> float:
    if not nd:
        return 4.5
    s = {"pos": 9.0, "neg": 0.0, "severe": 0.0}.get(nd.get("level"), 4.5)
    if nd.get("level") == "pos":
        s += (3 if nd.get("fresh") else 0) + (3 if nd.get("official") else 0)
    return min(s, 15.0)


def sector_score(sec: dict | None) -> float:
    """sec = {up_ratio: 같은 업종 상승 종목 비율, chg_pct: 업종 거래대금 가중 등락률} — 1시간마다 올라오는 업종 강도에서"""
    if not sec:
        return 5.0
    return ramp(sec.get("up_ratio"), [(0.3, 0), (0.5, 2.5), (0.8, 5)]) + ramp(sec.get("chg_pct"), [(0, 0), (1, 2.5), (3, 5)])


def first_limit(daily: pd.DataFrame) -> dict:
    """최근 20일 상한가 이력 (종가 기준 +29.5% 이상)"""
    c = daily["close"].to_numpy(float)
    r = c[1:] / c[:-1] - 1 if len(c) > 1 else np.array([])
    r20 = r[-20:]
    hits = int((r20 >= 0.295).sum())
    yday = bool(len(r) and r[-1] >= 0.295)
    run20 = float(c[-1] / c[-21] - 1) if len(c) >= 21 and c[-21] > 0 else None
    return {"hits20": hits, "consecutive": yday, "run20": run20,
            "score": 10.0 if hits == 0 else (2.0 if yday else 5.0)}


def heat_score(bars: pd.DataFrame | None, bm: dict | None, run20: float | None, chg_now: float) -> tuple[float, list[str]]:
    """과열·추격 위험 (감점형). 상승률이 높다는 이유만으로는 깎지 않는다"""
    s, why = 10.0, []
    dying = False
    if bars is not None and len(bars) >= 25:
        v5 = float(bars["volume"].iloc[-5:].mean())
        v20 = float(bars["volume"].iloc[-25:-5].mean())
        dying = v20 > 0 and v5 / v20 < 0.3
    falling = bool(bm and ((bm.get("chg1") is not None and bm["chg1"] <= -0.15) or (bm.get("chg5") is not None and bm["chg5"] <= -0.3)))
    if dying and falling:
        s -= 6; why.append("거래량 급감 + 잔량 감소")
    elif dying and chg_now < 29:
        s -= 2; why.append("거래량 급감")
    if run20 is not None and run20 >= 0.8:
        s -= 3; why.append(f"20일 +{run20 * 100:.0f}% 급등")
    return max(s, 0.0), why


def plan(entry: float, prev: float, bm: dict | None) -> dict:
    stop = rt(prev * 1.2, "down")
    loss = (stop / entry - 1) * 100 if entry > 0 else None
    warn = None
    if bm and bm.get("at_limit") and (bm.get("bid_value_ratio") or 0) >= 0.3:
        warn = "상한가 매수잔량이 두꺼워 주문해도 체결되지 않을 수 있어요"
    return {"entry": rt(entry), "stop": stop, "loss_pct": round(loss, 1) if loss is not None else None, "fill_warn": warn}


# ---------------------------------------------------------------- 종합
def evaluate(daily: pd.DataFrame, today: dict, bars: pd.DataFrame | None, book: dict | None, ctx: dict) -> dict:
    """daily: 어제까지 일봉 (open·high·low·close·volume) · today: {open, high, low, close, volume, value, prev_close,
    listed_shares, upper_limit} · bars: 오늘 1분봉 (time·open·high·low·close·volume) · book: 호가 (없으면 None → 환산)
    ctx: news (news_detail 결과) · sector {up_ratio, chg_pct} · danger · book_hist · now · rescale_missing"""
    c = float(today["close"])
    prev = float(today.get("prev_close") or (daily["close"].iloc[-1] if len(daily) else c))
    chg = (c / prev - 1) * 100 if prev > 0 else 0.0
    value = float(today.get("value") or 0)
    lim = float(today.get("upper_limit") or 0) or limit_price(prev)          # KIS 상한가 (권리락 등 반영) 없으면 계산
    lp = lock_profile(bars, lim)
    if not lp["reached"] and is_limit(float(today.get("high") or 0), lim):     # 분봉이 없거나 늦을 때 고가로 보완
        lp.update({"reached": True, "locked_now": is_limit(c, lim)})
    last_vol = float(bars["volume"].iloc[-1]) if bars is not None and len(bars) and lp["locked_now"] else None
    bm = book_metrics(book, ctx.get("book_hist"), value, lim, today.get("listed_shares"), last_vol, lp["locked_now"])
    fl = first_limit(daily) if len(daily) else {"hits20": 0, "consecutive": False, "run20": None, "score": 10.0}
    nd = ctx.get("news")
    heat, heat_why = heat_score(bars, bm, fl["run20"], chg)
    bscore = bid_score(bm, bars, lp["locked_now"])
    parts = {"bid25": bscore if bscore is not None else 12.5, "time15": 7.5, "rel15": release_score(lp),
             "news15": news_score(nd), "sec10": sector_score(ctx.get("sector")), "first10": fl["score"], "heat10": heat}
    parts = {k: round(max(0.0, min(float(v), PARTS[k][1])), 2) for k, v in parts.items()}
    score = round(sum(parts.values()), 1)
    if bscore is None and ctx.get("rescale_missing", True):
        score = round((score - parts["bid25"]) * 100 / 75, 1)                  # 호가 없음 → 75점 만점을 100점으로

    ex = []
    if ctx.get("danger"):
        ex.append(str(ctx["danger"]))
    if nd and nd.get("level") == "severe":
        ex.append("심각 악재 뉴스")
    risk = []
    if lp["reached"] and not lp["locked_now"] and chg >= MIN_CHG:
        risk.append(f"지금 상한가 풀림 ({lp['last_release']}분째)")
    if bm and bm.get("at_limit") and ((bm.get("chg1") is not None and bm["chg1"] <= -0.3)
                                      or (bm.get("chg5") is not None and bm["chg5"] <= -0.5)):
        risk.append("상한가 매수잔량 급감")
    if "거래량 급감 + 잔량 감소" in heat_why:
        risk.append("거래량 급감 + 잔량 감소")
    if bm and not lp["locked_now"] and chg >= NEAR_CHG and (bm.get("total_ask") or 0) > (bm.get("total_bid") or 0) * 1.5:
        risk.append("매도 잔량 우위")
    one_ok = lp["releases"] == 1 and lp["relocked"] and lp["last_release"] <= RELOCK_FAST \
        and not (bm and bm.get("chg1") is not None and bm["chg1"] < -0.1)
    pl = plan(lim if lp["reached"] else c, prev, bm)
    hm = pd.Timestamp(ctx["now"]).strftime("%H:%M") if ctx.get("now") is not None else "14:00"

    stage1 = not ex and chg >= MIN_CHG and value >= MIN_VALUE and score >= STAGE1
    near = lp["locked_now"] or (chg >= NEAR_CHG and not lp["reached"])
    stage2 = stage1 and near and (lp["releases"] == 0 or one_ok) and not risk and pl["loss_pct"] is not None \
        and hm < LAST_NEW
    if ex:
        status = "제외"
    elif lp["reached"] and chg < MIN_CHG:
        status = "조건 무효"
    elif stage2:
        status = "매수 검토"
    elif stage1:
        status = "강세 후보"
    elif chg >= MIN_CHG and value >= MIN_VALUE:
        status = "관찰"
    else:
        status = "대상 아님"

    reasons = [f"오늘 {chg:+.1f}% · 거래대금 {value / 1e8:,.0f}억 · 상한가 {lim:,.0f}"]
    if lp["reached"]:
        reasons.append(f"{lp['reach_time'] or '-'} 도달 · 풀림 {lp['releases']}회 ({lp['release_min']}분)"
                       + (" · 지금 잠김" if lp["locked_now"] else " · 지금 풀림"))
    if bm and bm.get("at_limit"):
        reasons.append(f"잔량 {bm['bid_qty']:,.0f}주 (거래대금의 {(bm.get('bid_value_ratio') or 0) * 100:.0f}%"
                       + (f" · 1분 {bm['chg1'] * 100:+.0f}%" if bm.get("chg1") is not None else "") + ")")
    if fl["consecutive"]:
        reasons.append("어제도 상한가 (연속)")
    if nd and nd.get("pos"):
        reasons.append("재료: " + nd["pos"][0][:40])
    return {"version": VERSION, "status": status, "score": score, "parts": parts,
            "group": "도달" if lp["reached"] else "미도달", "stage1": stage1, "stage2": stage2,
            "price": c, "chg_pct": round(chg, 2), "value": round(value), "limit": lim, "prev_close": prev,
            "lock": lp, "time_bucket": time_bucket(lp["reach_time"]), "book": bm, "first": fl,
            "news_level": (nd or {}).get("level"), "excluded": ex, "risks": risk, "heat_why": heat_why,
            "reasons": reasons, "exit_rules": EXIT_RULES, "exit_time": EXIT_TIME, **pl,
            "labels": {k: v for k, (v, _) in PARTS.items()}, "maxes": {k: m for k, (_, m) in PARTS.items()}}


# ---------------------------------------------------------------- 다음 날 청산
def simulate_next(m: pd.DataFrame, entry: float, exit_time: str = EXIT_TIME) -> dict:
    """다음 날 1분봉: 시가 절반 → 나머지는 고점 대비 −3% 이탈 시 (이탈 가격에 체결 가정, 봉 시가가 더 낮으면 시가) → 09:30 청산"""
    m = m[m["time"].dt.strftime("%H:%M") <= exit_time].sort_values("time")
    if m.empty or not entry:
        return {"outcome": "none", "pnl": None}
    o = float(m["open"].iloc[0])
    peak, px, out = o, None, "time"
    for r in m.iloc[0:].itertuples():
        stop = peak * (1 - TRAIL)
        if r.low <= stop:
            px, out = min(float(r.open), stop), "trail"
            break
        peak = max(peak, float(r.high))
    if px is None:
        px = float(m["close"].iloc[-1])
    val = 0.5 * o + 0.5 * px
    return {"outcome": out, "pnl": round((val / entry - 1 - COST) * 100, 3),
            "open_pnl": round((o / entry - 1 - COST) * 100, 3), "gap_pct": round((o / entry - 1) * 100, 2)}


def simulate_daily(nxt: dict, entry: float) -> dict:
    """일봉만 있을 때: 다음 날 시가 매도 (참고)"""
    o = float(nxt["open"])
    return {"open_pnl": round((o / entry - 1 - COST) * 100, 3), "gap_pct": round((o / entry - 1) * 100, 2)}
