"""종가배팅 검증 — 실전 기록(매일 저녁 결과) · 되돌려 보기(5년 일봉 / 최근 과거 분봉) → backtests 'CLOSE'

  실전 기록  PC 가 15:20 무렵 남긴 '매수 후보'(Storage closingbet/signals/날짜.json) → 다음 날 저녁 배치가
             그날 종가(매수가)와 다음 날 09:00~10:30 1분봉으로 청산 규칙 적용 → closingbet/results.json 누적
  되돌려 보기
    · 일봉 5년 (scripts.closingbet_backtest --daily): 날마다 거래대금 상위 150 → 장 후반 매수세·뉴스는 없어서
      빼고 환산한 점수로 '매수 후보' 상위 3 → 다음 날 일봉으로 시가 매도 수익률과 보수적 오전 근사
    · 과거 분봉 (--minutes): 그날 1분봉으로 장 후반 매수세까지 계산 → 다음 날 오전 1분봉으로 청산 규칙 그대로
  선정: 날마다 '매수 후보' 점수 상위 3 (메인과 같음)
"""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from ..engine import closingbet as cb

log = logging.getLogger(__name__)
KEY = "CLOSE"
RESULTS = "closingbet/results.json"
PICK = 3


def summary(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    keys = ("t2", "t1", "time", "open", "stop", "gap_stop")
    cnt = {k: sum(r["outcome"] == k for r in rows) for k in keys}
    pn = [r["pnl"] for r in rows if r.get("pnl") is not None]
    op = [r["open_pnl"] for r in rows if r.get("open_pnl") is not None]
    gp = [r["gap_pct"] for r in rows if r.get("gap_pct") is not None]
    win = sum(1 for p in pn if p > 0)
    return {"n": n, **{k: round(v / n * 100, 1) for k, v in cnt.items() if v},
            "win": round(win / len(pn) * 100, 1) if pn else None,
            "pnl": round(float(np.mean(pn)), 3) if pn else None,
            "open_pnl": round(float(np.mean(op)), 3) if op else None,
            "gap_down": round(sum(1 for g in gp if g < 0) / len(gp) * 100, 1) if gp else None,
            "gap_p10": round(float(np.percentile(gp, 10)), 2) if gp else None}


def report(rows: list[dict], recent: int = 30) -> dict:
    by_gap, by_year = {}, {}
    for r in rows:
        by_gap.setdefault(r.get("gap_grade") or "-", []).append(r)
        by_year.setdefault(str(r["date"])[:4], []).append(r)
    days = sorted({r["date"] for r in rows})
    return {"total": summary(rows), "by_gap": {k: summary(v) for k, v in by_gap.items()},
            "by_year": {k: summary(v) for k, v in sorted(by_year.items())}, "days": len(days),
            "first": days[0] if days else None, "last": days[-1] if days else None,
            "recent": sorted(rows, key=lambda r: r["date"], reverse=True)[:recent]}


def _load(sb, key):
    try:
        b = sb.download(key)
        return json.loads(b) if b else None
    except Exception:  # noqa: BLE001
        return None


def _save(sb, key, obj):
    sb.upload(key, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), "application/json")


def publish(sb, forward=None, daily=None, minutes=None) -> dict:
    from ..cloud import publish as pub
    old = {}
    try:
        rows = sb.select("backtests", {"select": "payload", "key": f"eq.{KEY}"})
        old = rows[0]["payload"] if rows else {}
    except Exception:  # noqa: BLE001
        pass
    out = {"version": cb.VERSION, "updated": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
           "forward": report(forward) if forward is not None else old.get("forward"),
           "daily": daily if daily is not None else old.get("daily"),
           "minutes": minutes if minutes is not None else old.get("minutes")}
    pub.publish_backtest(sb, KEY, "종가배팅", out)
    return out


def grade_signal(sig: dict, close: float | None, next_bars: pd.DataFrame) -> dict | None:
    """신호(전날 15:20 무렵) + 그날 실제 종가(매수가) + 다음 날 오전 1분봉 → 결과. 목표·손절은 실제 종가 기준으로 다시 계산"""
    if not close or next_bars is None or next_bars.empty:
        return None
    pl = cb.plan(float(close), float(sig.get("atr") or 0.03))
    r = cb.simulate_next(next_bars, pl["entry"], pl["stop"], pl["t1"], pl["t2"])
    if r.get("pnl") is None:
        return None
    o = float(next_bars["open"].iloc[0])
    return {k: sig.get(k) for k in ("date", "code", "name", "score", "type")} | {
        "gap_grade": (sig.get("gap") or {}).get("grade"), "entry": pl["entry"], "stop": pl["stop"], "t1": pl["t1"],
        "t2": pl["t2"], "open_pnl": round((o / pl["entry"] - 1 - cb.COST) * 100, 3), **r}


def evaluate_prev(sb, kis, today: str, close_of) -> int:
    """오늘 저녁: 지난 거래일 신호 → 그날 종가 매수 · 오늘 오전 매도 결과. close_of(code, date) → 그날 종가"""
    hist = _load(sb, RESULTS) or []
    done = {(r["date"], r["code"]) for r in hist}
    new, prev_day = [], None
    for back in range(1, 6):                                         # 최근 5일 안의 가장 가까운 신호 파일
        d = (pd.Timestamp(today) - pd.Timedelta(days=back)).strftime("%Y-%m-%d")
        sigs = _load(sb, f"closingbet/signals/{d}.json")
        if sigs:
            prev_day = d
            break
    if not prev_day:
        return 0
    for s in sigs:
        if (s["date"], s["code"]) in done:
            continue
        try:
            nb = kis.minute_bars_day(s["code"], "090000", "103000")
        except Exception as e:  # noqa: BLE001
            log.warning("종가배팅 결과: %s 분봉 실패 %s", s.get("name"), e)
            continue
        g = grade_signal(s, close_of(s["code"], prev_day), nb)
        if g:
            new.append(g)
    if new:
        hist += new
        _save(sb, RESULTS, hist)
        publish(sb, forward=hist)
    log.info("종가배팅: %s 신호 %d건 → 결과 %d건 (누적 %d)", prev_day, len(sigs), len(new), len(hist))
    return len(new)


def daily_backtest(oh: pd.DataFrame, index: pd.DataFrame, listing: pd.DataFrame, sectors: pd.DataFrame | None,
                   start: str = "2021-07-01", top: int = 150, pick: int = PICK) -> list[dict]:
    """일봉 5년 되돌려 보기 (장 후반 매수세·뉴스 없이 환산 점수) → 날마다 '매수 후보' 상위 pick → 다음 날 일봉 결과"""
    from ..engine.nextday import common_stock
    nm = dict(zip(listing["code"], listing["name"])) if len(listing) else {}
    mk = dict(zip(listing["code"], listing["market"])) if "market" in listing else {}
    admin = set(listing.loc[listing["is_admin"].astype(bool), "code"]) if "is_admin" in listing else set()
    oh = oh[[common_stock(c, nm.get(c, "")) for c in oh["code"]]] if len(oh) else oh
    piv = lambda col: oh.pivot(index="date", columns="code", values=col).sort_index()  # noqa: E731
    O, H, L, C, V = (piv(k) for k in ("open", "high", "low", "close", "volume"))
    VAL = piv("value") if "value" in oh else C * V
    dates, codes = C.index, C.columns
    o, h, l, c, v, val = (x.to_numpy(float) for x in (O, H, L, C, V, VAL))
    chg = np.full_like(c, np.nan)
    chg[1:] = (c[1:] / c[:-1] - 1) * 100
    ki = index[index["code"].isin(["KOSPI", "KOSDAQ"])].pivot(index="date", columns="code", values="close").sort_index() \
        if len(index) else pd.DataFrame()
        # 지수 등락 (%)
    kchg = (ki / ki.shift(1) - 1) * 100 if len(ki) else pd.DataFrame()
    sec = dict(zip(sectors["code"], sectors["sector"])) if sectors is not None and len(sectors) else {}
    sec_arr = np.array([sec.get(cd) for cd in codes], dtype=object)
    rows = []
    s0 = dates.searchsorted(pd.Timestamp(start))
    for i in range(max(s0, 61), len(dates) - 1):
        vi = np.nan_to_num(val[i], nan=0)
        cand = np.argsort(-vi)[:top]
        sdf = pd.DataFrame({"s": sec_arr, "chg": chg[i]})
        sec_mean = sdf.groupby("s")["chg"].mean().to_dict() if sec else {}
        res = []
        for j in cand:
            if not (c[i, j] > 0 and o[i + 1, j] > 0) or not np.isfinite(chg[i, j]):
                continue
            if abs(c[i + 1, j] / c[i, j] - 1) > 0.31 or abs(o[i + 1, j] / c[i, j] - 1) > 0.31:
                continue                                                     # 수정주가 이상
            sl = slice(i - 60, i)
            daily = pd.DataFrame({"open": o[sl, j], "high": h[sl, j], "low": l[sl, j], "close": c[sl, j], "volume": v[sl, j]}).dropna()
            if len(daily) < 30:
                continue
            today = {"open": o[i, j], "high": h[i, j], "low": l[i, j], "close": c[i, j], "volume": v[i, j],
                     "value": val[i, j], "vwap": (h[i, j] + l[i, j] + c[i, j]) / 3, "prev_close": c[i - 1, j]}
            m = mk.get(codes[j], "KOSPI")
            ic = float(kchg.at[dates[i], m]) if len(kchg) and m in kchg and dates[i] in kchg.index and pd.notna(kchg.at[dates[i], m]) else None
            r = cb.evaluate(daily, today, None, {"idx_chg": ic, "sector_chg": sec_mean.get(sec_arr[j]),
                                                  "danger": "관리종목" if codes[j] in admin else None,
                                                  "now": pd.Timestamp("2026-01-01 15:15"), "rescale_missing": True})
            if r["status"] == "매수 후보":
                res.append((r["score"], j, r))
        for sc, j, r in sorted(res, key=lambda x: -x[0])[:pick]:
            nx = {"open": o[i + 1, j], "high": h[i + 1, j], "low": l[i + 1, j]}
            s = cb.simulate_daily(nx, r["entry"], r["stop"], r["t1"])
            rows.append({"date": dates[i].strftime("%Y-%m-%d"), "code": codes[j], "name": nm.get(codes[j], codes[j]),
                         "score": sc, "type": r["type"], "gap_grade": r["gap"]["grade"], "chg_pct": r["chg_pct"], **s})
    return rows
