"""당일단타 검증 — 신호 결과 매기기 · 누적 · 과거 분봉 되돌려 보기(백테스트) → backtests 'DAYT' (앱 '검증' 화면)

  실전 기록(forward)  PC 가 아침에 남긴 신호(Storage daytrade/signals/날짜.json) → 그날 1분봉으로 결과
                      (저녁 배치 cloud_daily 가 매일) → daytrade/results.json 에 누적
  되돌려 보기(backtest) 과거 날짜 1분봉(KIS 일별분봉)으로 09:05~10:00 을 1분씩 다시 계산 → 첫 '진입 조건 충족' 에서 진입
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
            "pnl_sum": round(sum(pnls), 2) if pnls else None, **win_loss(pnls)}


def win_loss(pnls: list[float]) -> dict:
    """이긴 거래 평균 손익 · 진 거래 평균 손익 (%, 비용 뺀 뒤)"""
    w = [p for p in pnls if p > 0]
    lo = [p for p in pnls if p <= 0]
    return {"avg_win": round(sum(w) / len(w), 3) if w else None, "avg_loss": round(sum(lo) / len(lo), 3) if lo else None}


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


def scan_day(bars: pd.DataFrame, prev_close: float | None, start: str = "09:05", end: str = "10:00",
             adr: float | None = None, extra: dict | None = None) -> list[dict]:
    """과거 하루: start~end 를 1분씩 다시 계산한 결과 목록 [{hm, r}] — 같은 분봉·같은 ctx 로 한 번만 계산해 두고
    진입 시점·점수 기준·유형만 달리해 여러 번 비교할 때 재사용 (first_entry). 호가·뉴스·지수는 없어 그 몫(21점)을 빼고
    나머지 79점 만점을 100점으로 환산. 거래대금은 1분봉 누적값. extra: 엔진 ctx 에 더할 값 (hi_n 신고가 · rebound 반등장)"""
    if bars is None or len(bars) < 10:
        return []
    hm = bars["time"].dt.strftime("%H:%M")
    out = []
    for i in range(len(bars)):
        if hm.iloc[i] < start:
            continue
        if hm.iloc[i] > end:
            break
        b = bars.iloc[:i + 1]
        val = float(b["value"].iloc[-1]) if "value" in b and b["value"].iloc[-1] > 0 else None
        r = dt.evaluate(b, {"prev_close": prev_close, "now": b["time"].iloc[-1], "value": val, "idx_chg": None,
                            "adr": adr, "rescale_missing": True, **(extra or {})})
        out.append({"hm": hm.iloc[i], "r": {k: r.get(k) for k in ("status", "signal", "excluded", "score", "warnings", "time",
                                                                  "type", "entry", "stop", "t1", "t2", "parts")}})
    return out


def first_entry(scan: list[dict], start: str = "09:05", min_score: float | None = None, only_type: str | None = None) -> dict | None:
    """scan_day 결과에서 start 이후 첫 진입. min_score: 80 미만 점수로도 진입했다면 어땠나 비교용 — 진입 신호가 떴고 제외 사유·
    진입 보류 경고가 없고 점수가 min_score 이상이면 진입. only_type: '돌파'/'눌림목' 만 진입"""
    for x in scan:
        if x["hm"] < start:
            continue
        r = x["r"]
        ok = (r["status"] == "진입 조건 충족") if min_score is None else (
            r["signal"] and not r["excluded"] and r["score"] >= min_score and not any("진입 보류" in w for w in r["warnings"]))
        if ok and only_type and r.get("type") != only_type:
            ok = False
        if ok:
            return {k: r.get(k) for k in ("time", "type", "score", "entry", "stop", "t1", "t2", "parts")}
    return None


def rank_from_scan(scan: list[dict], at: str = "09:10") -> float | None:
    """at 시각(까지 마지막 봉)의 점수 — 후보 10개 순위용. 제외 사유가 있으면 None"""
    cur = [x for x in scan if x["hm"] <= at]
    if not cur or len(cur) < 1:
        return None
    r = cur[-1]["r"]
    return None if r["excluded"] else float(r["score"])


def replay_day(bars: pd.DataFrame, prev_close: float | None, start: str = "09:05", end: str = "10:00",
               adr: float | None = None, min_score: float | None = None, extra: dict | None = None,
               only_type: str | None = None) -> dict | None:
    """과거 하루: start~end 를 1분씩 다시 계산 → 첫 '진입 조건 충족' 신호 (없으면 None)"""
    return first_entry(scan_day(bars, prev_close, start, end, adr, extra), start, min_score, only_type)


def rank_score(bars: pd.DataFrame, prev_close: float | None, at: str = "09:10", adr: float | None = None,
               extra: dict | None = None) -> float | None:
    """at 시각까지의 분봉으로 종목 점수 (후보 10개 추릴 때 순위용) — 진입 신호와 상관없이 점수만. 제외 사유가 있으면 None"""
    if bars is None or len(bars) < 10:
        return None
    b = bars[bars["time"].dt.strftime("%H:%M") <= at]
    if len(b) < 5:
        return None
    val = float(b["value"].iloc[-1]) if "value" in b and b["value"].iloc[-1] > 0 else None
    r = dt.evaluate(b, {"prev_close": prev_close, "now": b["time"].iloc[-1], "value": val, "idx_chg": None,
                        "adr": adr, "rescale_missing": True, **(extra or {})})
    return None if r["excluded"] else float(r["score"])
