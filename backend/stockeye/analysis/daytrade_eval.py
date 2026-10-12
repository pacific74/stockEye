"""당일단타 검증 — 신호 결과 매기기 · 누적 · 과거 분봉 되돌려 보기(백테스트) → backtests 'DAYT' (앱 '검증' 화면)

  실전 기록(forward)  PC 가 아침에 남긴 신호(Storage daytrade/signals/날짜.json) → 그날 1분봉으로 결과
                      (저녁 배치 cloud_daily 가 매일) → daytrade/results.json 에 누적
  되돌려 보기(backtest) 과거 날짜 1분봉(KIS 일별분봉)으로 09:05~10:30 을 1분씩 다시 계산 → 첫 '진입 조건 충족' 에서 진입
                      (scripts.daytrade_backtest — PC 에서 가끔)
  결과   2차 익절(t2) · 1차 익절 뒤 본전/마감(t1) · 손절(stop) · 장 마감 청산(close), 손익은 비용 0.2% 뺀 %
  ⚠ 되돌려 보기에는 호가(스프레드)·뉴스·지수가 없어 그 몫을 빼고 환산 → 실전 기록과 다를 수 있음
"""
from __future__ import annotations

import json
import logging

import pandas as pd

from ..engine import daytrade as dt

log = logging.getLogger(__name__)
KEY = "DAYT"
RESULTS = "daytrade/results.json"


def summary(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    cnt = {k: sum(r["outcome"] == k for r in rows) for k in ("t2", "t1", "stop", "close")}
    win = cnt["t2"] + cnt["t1"]
    pnls = [r["pnl"] for r in rows if r.get("pnl") is not None]
    return {"n": n, **{k: round(v / n * 100, 1) for k, v in cnt.items()},
            "win": round(win / (win + cnt["stop"]) * 100, 1) if win + cnt["stop"] else None,
            "pnl": round(sum(pnls) / len(pnls), 3) if pnls else None,
            "pnl_sum": round(sum(pnls), 2) if pnls else None}


def report(rows: list[dict], recent: int = 30) -> dict:
    by = {}
    for r in rows:
        by.setdefault(r.get("type") or "-", []).append(r)
    days = sorted({r["date"] for r in rows})
    return {"total": summary(rows), "by_type": {k: summary(v) for k, v in by.items()}, "days": len(days),
            "first": days[0] if days else None, "last": days[-1] if days else None,
            "recent": sorted(rows, key=lambda r: (r["date"], r.get("time") or ""), reverse=True)[:recent]}


def grade(sig: dict, bars: pd.DataFrame) -> dict | None:
    """신호 하나 + 그날 1분봉 → 결과 (신호 시각 다음 봉부터)"""
    if bars is None or bars.empty:
        return None
    t = pd.Timestamp(f"{sig['date']} {sig['time']}")
    after = bars[bars["time"] > t]
    if after.empty:
        return None
    r = dt.simulate_exit(after, float(sig["entry"]), float(sig["stop"]), float(sig["t1"]), float(sig["t2"]))
    return {k: sig.get(k) for k in ("date", "time", "code", "name", "type", "score", "entry", "stop", "t1", "t2")} | r


def _load(sb, key: str):
    try:
        b = sb.download(key)
        return json.loads(b) if b else None
    except Exception:  # noqa: BLE001
        return None


def _save(sb, key: str, obj) -> None:
    sb.upload(key, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), "application/json")


def publish(sb, forward: list[dict] | None = None, backtest: dict | None = None) -> dict:
    """DAYT 결과 갱신 (한쪽만 주면 다른 쪽은 이전 값 유지)"""
    from ..cloud import publish as pub
    old = {}
    try:
        rows = sb.select("backtests", {"select": "payload", "key": f"eq.{KEY}"})
        old = rows[0]["payload"] if rows else {}
    except Exception:  # noqa: BLE001
        pass
    out = {"version": dt.VERSION, "updated": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
           "forward": report(forward) if forward is not None else old.get("forward"),
           "backtest": backtest if backtest is not None else old.get("backtest")}
    pub.publish_backtest(sb, KEY, "당일단타", out)
    return out


def evaluate_day(sb, kis, day: str) -> int:
    """그날 신호에 결과를 매겨 누적 (저녁 배치). 반환: 새로 매긴 건수"""
    sigs = _load(sb, f"daytrade/signals/{day}.json") or []
    hist = _load(sb, RESULTS) or []
    done = {(r["date"], r["code"], r["type"]) for r in hist}
    new = []
    for s in sigs:
        if (s["date"], s["code"], s["type"]) in done:
            continue
        try:
            bars = kis.minute_bars_day(s["code"], "090000", "153000")
        except Exception as e:  # noqa: BLE001
            log.warning("당일단타 결과: %s 분봉 실패 %s", s.get("name"), e)
            continue
        g = grade(s, bars)
        if g:
            new.append(g)
    if new or sigs:
        hist = hist + new
        _save(sb, RESULTS, hist)
        publish(sb, forward=hist)
    log.info("당일단타: %s 신호 %d건 → 결과 %d건 (누적 %d)", day, len(sigs), len(new), len(hist))
    return len(new)


def replay_day(bars: pd.DataFrame, prev_close: float | None, start: str = "09:05", end: str = "10:30",
               adr: float | None = None) -> dict | None:
    """과거 하루: start~end 를 1분씩 다시 계산 → 첫 '진입 조건 충족' 신호 (없으면 None).
    호가·뉴스·지수는 없어 그 몫(21점)을 빼고 나머지 79점 만점을 100점으로 환산. 거래대금은 1분봉 누적값"""
    if bars is None or len(bars) < 10:
        return None
    hm = bars["time"].dt.strftime("%H:%M")
    for i in range(len(bars)):
        if hm.iloc[i] < start:
            continue
        if hm.iloc[i] > end:
            break
        b = bars.iloc[:i + 1]
        val = float(b["value"].iloc[-1]) if "value" in b and b["value"].iloc[-1] > 0 else None
        r = dt.evaluate(b, {"prev_close": prev_close, "now": b["time"].iloc[-1], "value": val, "idx_chg": None,
                            "adr": adr, "rescale_missing": True})
        if r["status"] == "진입 조건 충족":
            return {k: r.get(k) for k in ("time", "type", "score", "entry", "stop", "t1", "t2", "parts")}
    return None
