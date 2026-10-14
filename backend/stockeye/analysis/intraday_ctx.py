"""당일매매 시장·업종 관계 기록 (2026-10-14) — 고정 종목마다 매수 → 청산 구간의 시장·업종 흐름을 쌓아 '시장 필터·진입 시간' 조절 근거로

종목 1건 (당일단타 · 같은 날 끝난 것)
  종목% (비용 전) · 손익%(비용 후) · 시장% (같은 구간) · 업종% · 종목−시장 · 종목−업종
  1분 수익률 상관 (업종 / 시장) · 진입 전 30분 시장·업종% · 진입 전 10분 시장% · 장 시작(09:00)~진입 시장%
  진입 시각 구간 (~09:30 · 09:30~10:00 · 10:00~)
  시장 = ETF 1분봉 (코스피 KODEX 200 069500 · 코스닥 KODEX 코스닥150 229200)
  업종 = KRX 업종 전체 시가총액 가중 (시총 큰 순 90% · 최대 60종목 · 그 종목 제외)
통계 (검증 > 시장·업종): 보유 중 시장 상승/보합/하락 · 진입 전 30분 시장 · 진입 시각 · 시장 상관 높/낮 → 건수·승률·평균 손익
저장: Storage ctx/intraday/<날짜>.json · system_status 'intraday_ctx' (최근 40거래일 행 + 통계)
실행: 저녁 배치 "당일매매 시장·업종 기록" · PC 23_index_compare.bat (오늘 것 바로 보기)
"""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)
ETF = {"KOSPI": ("069500", "KODEX200"), "KOSDAQ": ("229200", "KODEX코스닥150")}
CAP_SHARE, MAX_MEMBERS = 0.90, 60
KEEP_DAYS = 40
COST = 0.25


def px_at(b: pd.DataFrame | None, ts: pd.Timestamp) -> float | None:
    if b is None or b.empty:
        return None
    a = b[b["time"] <= ts]
    return float(a["close"].iloc[-1]) if len(a) else None


def ret(b, t0, t1) -> float | None:
    p0, p1 = px_at(b, t0), px_at(b, t1)
    return (p1 / p0 - 1) * 100 if p0 and p1 else None


def series(b: pd.DataFrame | None, t0, t1) -> pd.Series:
    if b is None or b.empty:
        return pd.Series(dtype=float)
    s = b.set_index(b["time"].dt.floor("min"))["close"]
    s = s[~s.index.duplicated(keep="last")]
    idx = pd.date_range(t0.floor("min"), t1.floor("min"), freq="1min")
    return s.reindex(s.index.union(idx)).ffill().reindex(idx)


def sector_series(bars: dict[str, pd.DataFrame], caps: dict[str, float], t0, t1) -> tuple[pd.Series, int]:
    rows, ws = [], []
    for c, b in bars.items():
        s = series(b, t0, t1)
        if s.empty or not np.isfinite(s.iloc[0]) or s.iloc[0] <= 0:
            continue
        rows.append(s / s.iloc[0] * 100)
        ws.append(caps.get(c, 1.0))
    if not rows:
        return pd.Series(dtype=float), 0
    m = pd.concat(rows, axis=1)
    w = np.array(ws) / np.sum(ws)
    return (m.fillna(100) * w).sum(axis=1), len(rows)


def corr(a: pd.Series, b: pd.Series) -> float | None:
    ra, rb = a.pct_change(), b.pct_change()
    d = pd.concat([ra, rb], axis=1).dropna()
    if len(d) < 5 or d.iloc[:, 0].std() == 0 or d.iloc[:, 1].std() == 0:
        return None
    return float(d.iloc[:, 0].corr(d.iloc[:, 1]))


def bucket(hm: str) -> str:
    return "~09:30" if hm < "09:30" else ("09:30~10:00" if hm < "10:00" else "10:00~")


def _r(v, d=2):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else round(float(v), d)


def ctx_rows(bars_fn, tracks: list[dict], listing: pd.DataFrame, sectors: pd.DataFrame | None, end: pd.Timestamp,
             kind: str = "daytrade") -> list[dict]:
    """bars_fn(code) → 오늘 1분봉(time·close). tracks = Tracker 추적 dict (산 것)"""
    market = dict(zip(listing["code"], listing["market"])) if "market" in listing else {}
    names = dict(zip(listing["code"], listing["name"]))
    sec_of = dict(zip(sectors["code"], sectors["sector"])) if sectors is not None and len(sectors) else {}
    caps = ({c: float(v) for c, v in zip(sectors["code"], sectors["marcap"]) if pd.notna(v) and v > 0}
            if sectors is not None and "marcap" in sectors else {})
    out = []
    for t in sorted(tracks, key=lambda x: x.get("buy_time") or x["time"]):
        code = t["code"]
        t0 = pd.Timestamp(f"{t['date']} {t.get('buy_time') or t['time']}")
        t1 = pd.Timestamp(t["exit_time"]) if t.get("exit_time") else end
        if t1.strftime("%Y-%m-%d") != t0.strftime("%Y-%m-%d"):          # 날을 넘긴 것(상한가포착·종가배팅)은 아직 안 봄
            continue
        open_ = pd.Timestamp(f"{t['date']} 09:00")
        pre30, pre10 = max(t0 - pd.Timedelta(minutes=30), open_), max(t0 - pd.Timedelta(minutes=10), open_)
        mk = market.get(code, "KOSPI")
        etf, etf_name = ETF.get(mk, ETF["KOSPI"])
        sec = sec_of.get(code)
        mem = sorted([c for c, s in sec_of.items() if s == sec and c != code], key=lambda c: -caps.get(c, 0)) if sec else []
        tot, pick, acc = sum(caps.get(c, 0) for c in mem), [], 0.0
        for c in mem:
            pick.append(c)
            acc += caps.get(c, 0)
            if (tot and acc >= tot * CAP_SHARE) or len(pick) >= MAX_MEMBERS:
                break
        sb_, mb = bars_fn(code), bars_fn(etf)
        secb = {c: bars_fn(c) for c in pick}
        s_stock, s_mkt = series(sb_, t0, t1), series(mb, t0, t1)
        s_sec, n_sec = sector_series(secb, caps, t0, t1)
        s_pre, _ = sector_series(secb, caps, pre30, t0)
        done = bool(t.get("done"))
        r_stock = (t["pnl"] + COST) if done and t.get("pnl") is not None else ret(sb_, t0, t1)
        r_mkt = ret(mb, t0, t1)
        r_sec = float(s_sec.iloc[-1] - 100) if len(s_sec) else None
        out.append({
            "date": t["date"], "kind": kind, "code": code, "name": t.get("name") or names.get(code, code),
            "market": mk, "etf": etf_name, "sector": sec, "sector_n": n_sec,
            "entry": t0.strftime("%H:%M"), "exit": t1.strftime("%H:%M"), "bucket": bucket(t0.strftime("%H:%M")),
            "result": t.get("result") or "진행중", "done": done,
            "pnl": _r(t.get("pnl")) if done else None, "stock": _r(r_stock), "mkt": _r(r_mkt), "sec": _r(r_sec),
            "vs_mkt": _r(None if r_stock is None or r_mkt is None else r_stock - r_mkt),
            "vs_sec": _r(None if r_stock is None or r_sec is None else r_stock - r_sec),
            "corr_sec": _r(corr(s_stock, s_sec) if len(s_sec) else None), "corr_mkt": _r(corr(s_stock, s_mkt)),
            "mkt_pre30": _r(ret(mb, pre30, t0)), "mkt_pre10": _r(ret(mb, pre10, t0)),
            "mkt_open": _r(ret(mb, open_, t0)), "sec_pre30": _r(float(s_pre.iloc[-1] - 100) if len(s_pre) else None),
            "hold_min": int((t1 - t0).total_seconds() // 60), "score": t.get("score"),
            "nxt_pre": (t.get("nxt_pre") or [None, None])[1] if isinstance(t.get("nxt_pre"), list) else None})
    return out


GROUPS = [
    ("보유 중 시장", "mkt", [("상승 (+0.3%↑)", 0.3, None), ("보합", -0.3, 0.3), ("하락 (−0.3%↓)", None, -0.3)]),
    ("진입 전 30분 시장", "mkt_pre30", [("하락 (0 미만)", None, 0), ("0 ~ +1%", 0, 1), ("+1% 이상 (추격)", 1, None)]),
    ("진입 전 10분 시장", "mkt_pre10", [("하락 (−0.2%↓)", None, -0.2), ("보합", -0.2, 0.2), ("상승 (+0.2%↑)", 0.2, None)]),
    ("장 시작~진입 시장", "mkt_open", [("하락", None, 0), ("0 ~ +1%", 0, 1), ("+1% 이상", 1, None)]),
    ("시장 상관", "corr_mkt", [("낮음 (0.4 미만)", None, 0.4), ("높음 (0.4 이상)", 0.4, None)]),
    ("진입 전 30분 업종", "sec_pre30", [("하락 (0 미만)", None, 0), ("0 ~ +1%", 0, 1), ("+1% 이상", 1, None)]),
    ("NXT 프리마켓 (08:00~08:50, 전일 종가 대비)", "nxt_pre",
     [("하락 (0 미만)", None, 0), ("0 ~ +3%", 0, 3), ("+3 ~ +7%", 3, 7), ("+7% 이상", 7, None)]),
]


def _agg(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    pn = [r["pnl"] for r in rows if r.get("pnl") is not None]
    win = sum(r["result"] == "이익실현" for r in rows)
    return {"n": n, "win": round(win / n * 100, 1), "pnl": round(float(np.mean(pn)), 2) if pn else None,
            "sum": round(float(np.sum(pn)), 2) if pn else None}


def stats(rows: list[dict]) -> dict:
    """끝난 건만: 전체 · 진입 시각 · 시장/업종 흐름 구간별 건수·승률(이익실현 비율)·평균 손익(비용 후)"""
    rows = [r for r in rows if r.get("done")]
    out = {"all": _agg(rows), "groups": []}
    out["groups"].append({"title": "진입 시각", "rows": [
        {"label": b, **_agg([r for r in rows if r["bucket"] == b])} for b in ("~09:30", "09:30~10:00", "10:00~")]})
    for title, key, cuts in GROUPS:
        g = []
        for lab, lo, hi in cuts:
            sel = [r for r in rows if r.get(key) is not None and (lo is None or r[key] >= lo) and (hi is None or r[key] < hi)]
            g.append({"label": lab, **_agg(sel)})
        out["groups"].append({"title": title, "rows": g})
    return out


def run(sb, kis, listing: pd.DataFrame, sectors: pd.DataFrame | None, day: str) -> dict:
    """저녁 배치: 오늘 당일단타(산 것 · 같은 날 끝난 것) → 행 계산 → 누적(최근 40거래일) → system_status 'intraday_ctx'"""
    from ..trading.intraday_track import Tracker
    from ..cloud import publish as pub
    day = pd.Timestamp(day).strftime("%Y-%m-%d")
    tracks = [t for t in Tracker(sb, "daytrade", day, user_id="").tracks.values() if t.get("bought", True)]
    cache: dict[str, pd.DataFrame] = {}

    def bars(code):
        if code not in cache:
            try:
                cache[code] = kis.minute_bars_day(code, "090000", "153000")
            except Exception as e:  # noqa: BLE001
                log.debug("1분봉 실패 %s: %s", code, e)
                cache[code] = pd.DataFrame(columns=["time", "close"])
        return cache[code]

    rows = ctx_rows(bars, tracks, listing, sectors, pd.Timestamp(f"{day} 15:30")) if tracks else []
    if rows:
        sb.upload(f"ctx/intraday/{day}.json", json.dumps(rows, ensure_ascii=False).encode("utf-8"), "application/json")
    try:
        old = (sb.select("system_status", {"select": "payload", "key": "eq.intraday_ctx"}) or [{}])[0].get("payload") or {}
    except Exception:  # noqa: BLE001
        old = {}
    allr = [r for r in (old.get("rows") or []) if r.get("date") != day] + rows
    keep = sorted({r["date"] for r in allr})[-KEEP_DAYS:]
    allr = [r for r in allr if r["date"] in keep]
    pub.publish_status(sb, "intraday_ctx", {"updated": day, "days": len(keep), "rows": allr, "stats": stats(allr)})
    return {"today": len(rows), "rows": len(allr), "days": len(keep)}
