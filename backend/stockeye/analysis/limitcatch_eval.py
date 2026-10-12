"""상한가포착 검증 → backtests 'LIMIT'

  실전 기록  PC 가 남긴 Storage limitcatch/signals/날짜.json → 다음 날 저녁 배치가 매김 (limitcatch/results.json 누적)
    · 처음 '매수 검토' 기록: 그때 가격(상한가 또는 현재가) 매수 → 그날 종가가 +20% 아래면 '조건 무효'(+20% 가격에 매도 가정)
      → 아니면 다음 날 시가 절반 · 09:30 까지 고점 −3% · 09:30 청산 (다음 날 1분봉)
      체결 가능성: 그날 종가까지 잠겨 있었고 매수 뒤 풀린 적이 없으면 '체결 불확실' (상한가에 줄을 서도 안 사졌을 수 있음)
    · 마지막 목록(강세 후보·관찰): 점수 구간별 상한가 유지율(종가 잠김) · 종가 매수 → 다음 날 시가 수익률
  되돌려 보기 (scripts.limitcatch_backtest)
    · 과거 1분봉 (--minutes N): 그날 +20% 이상·거래대금 100억↑ 종목의 분봉으로 도달 시각·풀림 재구성, 호가는 없어서 잔량
      항목을 빼고 환산한 점수. 진입 가정 3가지를 따로:
        ① 처음 +27% 넘은 분 종가에 체결
        ② 상한가 도달 → 그 뒤 한 번이라도 풀렸을 때만 체결 (잠겨만 있던 날은 못 산 것으로)  ← 보수적
        ③ 상한가 도달 분에 무조건 체결  ← 참고용 낙관
      매수 뒤 종가가 +20% 아래로 밀리면 그 분 종가에 '조건 무효' 매도
    · 5년 일봉 (--daily): 상한가 도달일 · 종가 잠김 여부별 다음 날 시가 수익률 (참고 상한·하한)
  구간: 점수 75 미만 / 75~79 / 80~89 / 90 이상 · 도달 시각 09시 / 10시 / 11~12시 / 13시 이후 · 도달 / 미도달
"""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from ..engine import limitcatch as lc
from ..engine.uplimit import limit_price
from .daytrade_eval import win_loss

log = logging.getLogger(__name__)
KEY = "LIMIT"
RESULTS = "limitcatch/results.json"
FINALS = "limitcatch/finals.json"
ASSUME = {"a1": "① +27% 첫 분 종가", "a2": "② 도달 후 풀렸을 때만 체결", "a3": "③ 도달 분 무조건 체결 (낙관)"}


def score_bucket(s) -> str:
    if s is None:
        return "-"
    return "75 미만" if s < 75 else ("75~79" if s < 80 else ("80~89" if s < 90 else "90 이상"))


def summary(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    pn = [r["pnl"] for r in rows if r.get("pnl") is not None]
    op = [r["open_pnl"] for r in rows if r.get("open_pnl") is not None]
    lk = [r["locked_close"] for r in rows if r.get("locked_close") is not None]
    dd = [r["max_dd"] for r in rows if r.get("max_dd") is not None]
    inv = sum(r.get("outcome") == "invalid" for r in rows)
    win = sum(1 for p in pn if p > 0)
    return {"n": n, "win": round(win / len(pn) * 100, 1) if pn else None,
            "pnl": round(float(np.mean(pn)), 3) if pn else None,
            "open_pnl": round(float(np.mean(op)), 3) if op else None,
            "hold": round(sum(lk) / len(lk) * 100, 1) if lk else None,
            "max_dd": round(float(np.mean(dd)), 2) if dd else None,
            "invalid": round(inv / n * 100, 1) if inv else 0.0,
            "pnl_sum": round(float(np.sum(pn)), 2) if pn else None, **win_loss(pn)}


def grouped(rows: list[dict], key) -> dict:
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(key(r), []).append(r)
    return {k: summary(v) for k, v in sorted(out.items())}


def report(rows: list[dict], recent: int = 30) -> dict:
    days = sorted({r["date"] for r in rows})
    return {"total": summary(rows), "by_score": grouped(rows, lambda r: score_bucket(r.get("score"))),
            "by_time": grouped(rows, lambda r: lc.time_bucket(r.get("reach_time"))),
            "by_group": grouped(rows, lambda r: r.get("group") or "-"),
            "by_fill": grouped(rows, lambda r: r.get("fill") or "-"),
            "days": len(days), "first": days[0] if days else None, "last": days[-1] if days else None,
            "recent": sorted(rows, key=lambda r: (r["date"], r.get("time") or ""), reverse=True)[:recent]}


def _load(sb, key):
    try:
        b = sb.download(key)
        return json.loads(b) if b else None
    except Exception:  # noqa: BLE001
        return None


def _save(sb, key, obj):
    sb.upload(key, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), "application/json")


def publish(sb, forward=None, finals=None, minutes=None, daily=None) -> dict:
    from ..cloud import publish as pub
    old = {}
    try:
        rows = sb.select("backtests", {"select": "payload", "key": f"eq.{KEY}"})
        old = rows[0]["payload"] if rows else {}
    except Exception:  # noqa: BLE001
        pass
    out = {"version": lc.VERSION, "updated": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
           "forward": report(forward) if forward is not None else old.get("forward"),
           "finals": report(finals) if finals is not None else old.get("finals"),
           "minutes": minutes if minutes is not None else old.get("minutes"),
           "daily": daily if daily is not None else old.get("daily")}
    pub.publish_backtest(sb, KEY, "상한가포착", out)
    return out


# ---------------------------------------------------------------- 실전 기록
def grade_first_buy(sig: dict, day_row: dict | None, next_bars: pd.DataFrame | None, final_lock: dict | None) -> dict | None:
    """처음 '매수 검토' 신호 → 결과. day_row = 그날 일봉 {close, ...}"""
    if not day_row or not sig.get("entry"):
        return None
    entry, stop = float(sig["entry"]), float(sig.get("stop") or lc.rt(float(sig["prev_close"]) * 1.2, "down"))
    lim = float(sig.get("limit") or 0)
    close = float(day_row["close"])
    locked = lc.is_limit(close, lim)
    rel_after = (final_lock or {}).get("releases", 0) - int(sig.get("releases_at") or 0)
    fill = "체결 가능" if (sig.get("group") == "미도달" or not locked or rel_after > 0) else "체결 불확실"
    base = {k: sig.get(k) for k in ("date", "code", "name", "time", "score", "group", "reach_time", "entry")} \
        | {"locked_close": locked, "fill": fill, "close": close}
    if close < stop:                                                  # 그날 +20% 아래로 밀림 → 조건 무효
        return base | {"outcome": "invalid", "pnl": round((stop / entry - 1 - lc.COST) * 100, 3), "open_pnl": None}
    if next_bars is None or next_bars.empty:
        return None
    r = lc.simulate_next(next_bars, entry)
    return base | r if r.get("pnl") is not None else None


def grade_final(item: dict, day_row: dict | None, next_row: dict | None) -> dict | None:
    """마지막 목록 종목: 그날 종가 잠김 여부 · 종가 매수 → 다음 날 시가 수익률 (점수 구간별 비교용)"""
    if not day_row or not next_row:
        return None
    c, o = float(day_row["close"]), float(next_row["open"])
    if c <= 0 or o <= 0:
        return None
    lk = item.get("lock") or {}
    return {k: item.get(k) for k in ("date", "code", "name", "score", "status", "group", "time_bucket")} | {
        "reach_time": lk.get("reach_time"), "locked_close": lc.is_limit(c, float(item.get("limit") or 0)),
        "open_pnl": round((o / c - 1 - lc.COST) * 100, 3), "pnl": round((o / c - 1 - lc.COST) * 100, 3)}


def evaluate_prev(sb, kis, today: str, row_of) -> int:
    """오늘 저녁: 지난 거래일 신호 → 결과. row_of(code, 'YYYY-MM-DD') → 그날 일봉 dict 또는 None"""
    hist = _load(sb, RESULTS) or []
    fin = _load(sb, FINALS) or []
    done = {(r["date"], r["code"]) for r in hist}
    done_f = {(r["date"], r["code"]) for r in fin}
    sig, prev_day = None, None
    for back in range(1, 6):                                          # 최근 5일 안의 가장 가까운 신호 파일
        d = (pd.Timestamp(today) - pd.Timedelta(days=back)).strftime("%Y-%m-%d")
        sig = _load(sb, f"limitcatch/signals/{d}.json")
        if sig:
            prev_day = d
            break
    if not sig:
        return 0
    final_lock = {it["code"]: it.get("lock") for it in sig.get("final", [])}
    new, new_f = [], []
    for s in sig.get("first_buy", []):
        if (s["date"], s["code"]) in done:
            continue
        try:
            nb = kis.minute_bars(s["code"], "093000")
        except Exception as e:  # noqa: BLE001
            log.warning("상한가포착 결과: %s 분봉 실패 %s", s.get("name"), e)
            nb = None
        g = grade_first_buy(s, row_of(s["code"], prev_day), nb, final_lock.get(s["code"]))
        if g:
            new.append(g)
    for it in sig.get("final", []):
        if (it["date"], it["code"]) in done_f:
            continue
        g = grade_final(it, row_of(it["code"], prev_day), row_of(it["code"], today))
        if g:
            new_f.append(g)
    if new:
        hist += new
        _save(sb, RESULTS, hist)
    if new_f:
        fin += new_f
        _save(sb, FINALS, fin)
    if new or new_f:
        publish(sb, forward=hist, finals=fin)
    log.info("상한가포착: %s 매수 검토 %d → 결과 %d · 목록 %d (누적 %d · %d)", prev_day, len(sig.get("first_buy", [])),
             len(new), len(new_f), len(hist), len(fin))
    return len(new) + len(new_f)


# ---------------------------------------------------------------- 과거 1분봉 되돌려 보기
def _today_from(bars: pd.DataFrame, prev: float) -> dict:
    v = float(bars["volume"].sum())
    val = float(bars["value"].iloc[-1]) if "value" in bars and pd.notna(bars["value"].iloc[-1]) and bars["value"].iloc[-1] > 0 \
        else float((bars["close"] * bars["volume"]).sum())
    return {"open": float(bars["open"].iloc[0]), "high": float(bars["high"].max()), "low": float(bars["low"].min()),
            "close": float(bars["close"].iloc[-1]), "volume": v, "value": val, "prev_close": prev}


def _after(bars: pd.DataFrame, i: int, entry: float, stop: float, lim: float) -> dict:
    """매수(i 번째 분) 뒤 그날: 조건 무효(종가 +20% 아래) · 최대 하락 · 종가 잠김 · 매수 뒤 풀림 여부"""
    rest = bars.iloc[i + 1:]
    inv = rest[rest["close"] < stop]
    lows = rest["low"] if len(rest) else bars["low"].iloc[i:i + 1]
    return {"invalid_px": float(inv["close"].iloc[0]) if len(inv) else None,
            "max_dd": round((float(lows.min()) / entry - 1) * 100, 2),
            "locked_close": lc.is_limit(float(bars["close"].iloc[-1]), lim),
            "released_after": bool(len(rest) and (rest["close"] < lim - 1e-9).any())}


def replay_day(bars: pd.DataFrame, daily: pd.DataFrame, prev: float, ctx: dict | None = None) -> dict[str, dict]:
    """그날 1분봉 → 진입 가정별 매수 시점·점수 (호가 없음 → 환산 점수). 반환 {a1|a2|a3: {...}}"""
    ctx = dict(ctx or {})
    lim = limit_price(prev)
    if bars is None or bars.empty or not lim:
        return {}
    b = bars.sort_values("time").reset_index(drop=True)
    cl = b["close"].to_numpy(float)
    hi = b["high"].to_numpy(float)
    stop = lc.rt(prev * 1.2, "down")
    out = {}

    def at(i: int, entry: float, key: str, filled: bool = True):
        part = b.iloc[:i + 1]
        r = lc.evaluate(daily, _today_from(part, prev), part, None,
                        ctx | {"now": part["time"].iloc[-1], "rescale_missing": True})
        a = _after(b, i, entry, stop, lim)
        out[key] = {"time": part["time"].iloc[-1].strftime("%H:%M"), "entry": entry, "score": r["score"],
                    "status": r["status"], "group": r["group"], "reach_time": r["lock"]["reach_time"],
                    "value": r["value"], "filled": filled, **a}

    i27 = np.flatnonzero((cl / prev - 1) * 100 >= lc.NEAR_CHG)
    ilim = np.flatnonzero(hi >= lim - 1e-9)
    if len(i27) and (not len(ilim) or i27[0] <= ilim[0]):
        i = int(i27[0])
        if cl[i] < lim - 1e-9:
            at(i, float(cl[i]), "a1")
    if len(ilim):
        i = int(ilim[0])
        at(i, lim, "a3")
        a2 = dict(out["a3"])
        a2["filled"] = a2["released_after"] or not lc.is_limit(cl[i], lim)
        out["a2"] = a2
    return out


def finish(trade: dict, next_bars: pd.DataFrame | None) -> dict | None:
    """매수 뒤 결과: 그날 조건 무효면 그 가격에 매도, 아니면 다음 날 오전 규칙"""
    if not trade.get("filled"):
        return None
    e = trade["entry"]
    if trade.get("invalid_px"):
        return trade | {"outcome": "invalid", "pnl": round((trade["invalid_px"] / e - 1 - lc.COST) * 100, 3), "open_pnl": None}
    if next_bars is None or next_bars.empty:
        return None
    r = lc.simulate_next(next_bars, e)
    return trade | r if r.get("pnl") is not None else None


def daily_reference(oh: pd.DataFrame, listing: pd.DataFrame, start: str = "2021-07-01") -> dict:
    """5년 일봉: 상한가 도달일(거래대금 100억↑ 보통주) → 종가 잠김 / 풀림별 다음 날 시가 수익률 (상한가 매수 · 종가 매수)"""
    from ..engine.nextday import common_stock
    nm = dict(zip(listing["code"], listing["name"])) if len(listing) else {}
    oh = oh[[common_stock(c, nm.get(c, "")) for c in oh["code"]]]
    piv = lambda col: oh.pivot(index="date", columns="code", values=col).sort_index()  # noqa: E731
    O, H, C, V = (piv(k) for k in ("open", "high", "close", "volume"))
    VAL = piv("value") if "value" in oh else C * V
    P = C.shift(1)
    LIM = P.apply(lambda col: col.map(limit_price))
    rows = []
    s0 = C.index.searchsorted(pd.Timestamp(start))
    for i in range(max(s0, 1), len(C.index) - 1):
        d = C.index[i]
        hit = (H.iloc[i] >= LIM.iloc[i] - 1e-9) & (VAL.iloc[i] >= lc.MIN_VALUE) & (O.iloc[i + 1] > 0)
        for code in hit[hit].index:
            lim, c, o = float(LIM.at[d, code]), float(C.at[d, code]), float(O.iloc[i + 1][code])
            if abs(o / c - 1) > 0.31:
                continue
            rows.append({"date": d.strftime("%Y-%m-%d"), "locked": c >= lim - 1e-9,
                         "lim_pnl": (o / lim - 1 - lc.COST) * 100, "close_pnl": (o / c - 1 - lc.COST) * 100})
    out = {}
    for k, name in ((True, "종가 잠김"), (False, "도달 후 풀림")):
        g = [r for r in rows if r["locked"] is k]
        if g:
            out[name] = {"n": len(g), "lim_pnl": round(float(np.mean([r["lim_pnl"] for r in g])), 3),
                         "close_pnl": round(float(np.mean([r["close_pnl"] for r in g])), 3),
                         "win": round(sum(r["lim_pnl"] > 0 for r in g) / len(g) * 100, 1)}
    n = len(rows)
    out["hold"] = round(sum(r["locked"] for r in rows) / n * 100, 1) if n else None
    out["n"] = n
    out["first"], out["last"] = (rows[0]["date"], rows[-1]["date"]) if rows else (None, None)
    return out
