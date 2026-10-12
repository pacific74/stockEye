"""추천 기록 검증 — 저녁 배치가 매일 recommendations 의 결과 칸(res_*)을 채우고, 통계를 backtests 'RECS' 에 올림
→ 앱 '검증 > 추천주' 탭 (일별 추천주 결과 · 승률·손익 통계)

  관심 탭 (V3·익일유망주·상승초기·추세전환·상파)
    추천 다음 날부터 최대 20거래일, 그때 저장한 매매 계획 그대로 (관심종목 적중률과 같은 hitrate.simulate)
      매수  1·2·3차 매수구간 (구간 상단까지 내려오면 체결, 시가가 낮으면 시가) · 1차 목표 뒤엔 더 안 삼
      매도  1차 목표 50% · 2차 30% · 3차 20% · 1차 뒤 남은 몫은 본전 이탈 시 · 1차 전 손절가 · 20일째 종가
      비용 0.25% 뺀 손익 (산 금액 기준). 20일이 안 지났으면 '진행중' (손익은 마지막 종가 기준 평가)
  장중 탭 (당일단타·종가배팅·상한가포착): 각 탭 실전 기록(Storage */results.json)의 결과를 그대로 가져옴
    (그 탭의 청산 규칙 — 장 마감·다음 날 오전 — 으로 이미 매긴 결과. 7일 지나도 없으면 '결과 없음')
  결과 칸: res_status · res_done · res_pnl · res_filled · res_fill_day · res_days · res_d_t1~3 · res_d_stop ·
           res_max_up · res_max_dn · res_last · res_updated
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

import numpy as np
import pandas as pd

from ..cloud.recommend import DAILY_KINDS, TABLE
from .daytrade_eval import win_loss
from .hitrate import COST, H, JUMP, simulate

log = logging.getLogger(__name__)
KEY = "RECS"
LABEL = {"t1": "1차 목표", "t2": "2차 목표", "t3": "3차 목표", "stop": "손절", "flat": "기간 만료"}
INTRA_RESULTS = {"daytrade": "daytrade/results.json", "closingbet": "closingbet/results.json",
                 "limitcatch": "limitcatch/results.json"}
INTRA_LABEL = {"t2": "2차 목표", "t1": "1차 목표", "stop": "손절", "gap_stop": "갭 손절", "close": "장 마감 청산",
               "time": "시간 청산", "open": "시가 매도", "trail": "고점 −3% 매도", "invalid": "조건 무효"}
RES_COLS = ("res_status", "res_done", "res_pnl", "res_filled", "res_fill_day", "res_days", "res_d_t1", "res_d_t2",
            "res_d_t3", "res_d_stop", "res_max_up", "res_max_dn", "res_last", "res_updated")
SEL = ("rec_date,kind,code,name,score,entry,stop,target1,target2,target3,zone1_high,zone1_w,zone2_high,zone2_w,"
       "zone3_high,zone3_w," + ",".join(RES_COLS))


def select_all(sb, params: dict, page: int = 1000) -> list[dict]:
    """Supabase 는 한 번에 최대 1000행 → 나눠서 전부"""
    out, off = [], 0
    while True:
        rows = sb.select(TABLE, params | {"order": "rec_date,kind,code", "limit": str(page), "offset": str(off)})
        out += rows
        if len(rows) < page:
            return out
        off += page


def _f(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _res(row: dict, **kw) -> dict:
    out = {"rec_date": row["rec_date"], "kind": row["kind"], "code": row["code"]}
    out |= {c: kw.get(c[4:]) for c in RES_COLS}
    out["res_updated"] = datetime.utcnow().isoformat() + "Z"
    return out


def grade_daily(row: dict, g: pd.DataFrame) -> dict | None:
    """g = 그 종목 일봉 (date, open, high, low, close) 추천일 다음 날부터 (오름차순)"""
    g = g[g["date"] > pd.Timestamp(row["rec_date"])].sort_values("date").head(H)
    if g.empty:
        return None                                                    # 아직 다음 거래일 전
    o, h, lo, c = (g[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(g)
    stop, entry = _f(row.get("stop")), _f(row.get("entry"))
    if not stop or not entry:
        return _res(row, status="계획 없음", done=True, days=n)
    prev = np.concatenate([[c[0]], c[:-1]])
    if (np.abs(c / prev - 1) > JUMP)[1:].any():
        return _res(row, status="데이터 이상", done=True, days=n)
    zones = [(_f(row.get(f"zone{i}_high")), _f(row.get(f"zone{i}_w")) or 0) for i in (1, 2, 3)]
    zones = [(t, w) for t, w in zones if t and w > 0] or [(entry, 100.0)]
    t = tuple(_f(row.get(f"target{i}")) or 0.0 for i in (1, 2, 3))
    r = simulate(o, h, lo, c, zones, t, stop)
    full = n >= H
    ext = {"days": n, "last": float(c[-1]), "max_up": round((float(h.max()) / entry - 1) * 100, 2),
           "max_dn": round((float(lo.min()) / entry - 1) * 100, 2)}
    if r["outcome"] is None:
        return _res(row, status="미체결" if full else "매수 대기", done=full, filled=0, **ext)
    out = r["outcome"]
    done = full or out == "stop" or (out == "t3")
    status = LABEL.get(out, out) if done else ("보유중" if out == "flat" else LABEL[out] + " · 보유중")
    fd = r["first"]
    return _res(row, status=status, done=done, pnl=round(float(r["pnl"]), 3), filled=r["filled"],
                fill_day=r["fill_day"], d_t1=fd.get("t1"), d_t2=fd.get("t2"), d_t3=fd.get("t3"),
                d_stop=fd.get("stop"), **ext)


def grade_intraday(row: dict, results: dict, today: str) -> dict | None:
    r = results.get((str(row["rec_date"])[:10], row["code"]))
    if not r:
        old = (pd.Timestamp(today) - pd.Timestamp(row["rec_date"])).days > 7
        return _res(row, status="결과 없음", done=True) if old else None
    return _res(row, status=INTRA_LABEL.get(r.get("outcome"), r.get("outcome")), done=True,
                pnl=_f(r.get("pnl")), filled=100 if r.get("pnl") is not None else 0, days=1 if row["kind"] == "daytrade" else 2)


def _intra_results(sb) -> dict:
    out = {}
    for kind, key in INTRA_RESULTS.items():
        try:
            b = sb.download(key)
            rows = json.loads(b) if b else []
        except Exception:  # noqa: BLE001
            rows = []
        out[kind] = {(str(r.get("date"))[:10], r.get("code")): r for r in rows if r.get("code")}
    return out


def grade_open(sb, ohlcv: pd.DataFrame, today: str, lookback: int = 60) -> int:
    """아직 끝나지 않은 추천(res_done 이 참 아님 · 최근 lookback 일)의 결과 칸을 채움"""
    since = (pd.Timestamp(today) - pd.Timedelta(days=lookback)).strftime("%Y-%m-%d")
    rows = select_all(sb, {"select": SEL, "rec_date": f"gte.{since}", "or": "(res_done.is.null,res_done.eq.false)"})
    if not rows:
        return 0
    intra = _intra_results(sb)
    codes = {r["code"] for r in rows if r["kind"] in DAILY_KINDS}
    oh = ohlcv[ohlcv["code"].isin(codes) & (ohlcv["date"] > pd.Timestamp(since))]
    by = {c: g for c, g in oh.groupby("code")}
    ups = []
    for r in rows:
        if r["kind"] in DAILY_KINDS:
            g = by.get(r["code"])
            u = grade_daily(r, g) if g is not None else None
        else:
            u = grade_intraday(r, intra.get(r["kind"], {}), today)
        if u:
            ups.append(u)
    if ups:
        sb.upsert(TABLE, ups, "rec_date,kind,code")                    # 결과 칸만 덮어씀 (추천 내용은 그대로)
    log.info("추천 검증: 대상 %d · 갱신 %d (끝남 %d)", len(rows), len(ups), sum(bool(u["res_done"]) for u in ups))
    return len(ups)


# ---------------------------------------------------------------- 통계
def score_bucket(s) -> str:
    s = _f(s)
    if s is None:
        return "-"
    return "60 미만" if s < 60 else ("60~69" if s < 70 else ("70~79" if s < 80 else "80 이상"))


def stats(rows: list[dict]) -> dict:
    """승률·손익: 실제로 산(체결) 추천만. 끝난 것과 진행중(평가 손익)은 따로도"""
    n = len(rows)
    if not n:
        return {"n": 0}
    filled = [r for r in rows if _f(r.get("res_pnl")) is not None]
    done = [r for r in filled if r.get("res_done")]
    pn = [float(r["res_pnl"]) for r in done]
    allp = [float(r["res_pnl"]) for r in filled]
    t1 = [r for r in done if r.get("res_d_t1") is not None]
    st = [r for r in done if (r.get("res_status") or "").startswith("손절") or r.get("res_status") == "갭 손절"]
    return {"n": n, "filled": len(filled), "done": len(done),
            "unfilled": sum(r.get("res_status") == "미체결" for r in rows),
            "open": sum(not r.get("res_done") for r in rows),
            "win": round(sum(p > 0 for p in pn) / len(pn) * 100, 1) if pn else None,
            "pnl": round(float(np.mean(pn)), 2) if pn else None,
            "pnl_sum": round(float(np.sum(pn)), 1) if pn else None,
            "pnl_all": round(float(np.mean(allp)), 2) if allp else None,          # 진행중 평가 손익 포함
            "t1_rate": round(len(t1) / len(done) * 100, 1) if done else None,
            "stop_rate": round(len(st) / len(done) * 100, 1) if done else None,
            "max_up": round(float(np.mean([r["res_max_up"] for r in filled if _f(r.get("res_max_up")) is not None])), 2)
            if any(_f(r.get("res_max_up")) is not None for r in filled) else None,
            "max_dn": round(float(np.mean([r["res_max_dn"] for r in filled if _f(r.get("res_max_dn")) is not None])), 2)
            if any(_f(r.get("res_max_dn")) is not None for r in filled) else None,
            **win_loss(pn)}


def summarize(rows: list[dict]) -> dict:
    cnt: dict[tuple, int] = {}
    for r in rows:
        k = (str(r["rec_date"])[:10], r["code"])
        cnt[k] = cnt.get(k, 0) + 1
    grp = lambda f: {k: stats(v) for k, v in sorted(_group(rows, f).items())}  # noqa: E731
    dates = sorted({str(r["rec_date"])[:10] for r in rows})
    return {"updated": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"), "cost": COST, "hold_days": H,
            "first": dates[0] if dates else None, "last": dates[-1] if dates else None, "days": len(dates),
            "total": stats(rows), "by_kind": grp(lambda r: r["kind"]),
            "by_month": grp(lambda r: str(r["rec_date"])[:7]),
            "by_overlap": grp(lambda r: "여러 구분 겹침" if cnt[(str(r["rec_date"])[:10], r["code"])] > 1 else "한 구분만"),
            "by_score": grp(lambda r: score_bucket(r.get("score"))),
            "by_day": {d: stats([r for r in rows if str(r["rec_date"])[:10] == d]) for d in dates[-60:]}}


def _group(rows, f):
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(f(r), []).append(r)
    return out


def publish(sb) -> dict:
    from ..cloud import publish as pub
    rows = select_all(sb, {"select": "rec_date,kind,code,score," + ",".join(RES_COLS)})
    out = summarize(rows)
    pub.publish_backtest(sb, KEY, "추천주 검증", out)
    return out


def run(sb, ohlcv: pd.DataFrame, today: str) -> int:
    n = grade_open(sb, ohlcv, today)
    publish(sb)
    return n
