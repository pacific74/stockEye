"""추천 기록 검증 — 저녁 배치가 매일 recommendations 의 결과 칸(res_*)을 채우고, 통계를 backtests 'RECS' 에 올림
→ 앱 '검증 > 추천주' 탭 (일별 추천주 결과 · 승률·손익 통계)

  관심 탭 (V3·유망주·상승초기·추세전환·상파)
    추천 유효기간은 다음 거래일 하루 (2026-10-15): 그날 1차 매수구간에서 체결됐으면 그 뒤 최대 20거래일 동안
    2·3차 매수·분할 매도 계속, 그날 못 샀으면 '미체결'로 끝 (hitrate.simulate(first_day_only=True))
      매수  1·2·3차 매수구간 (구간 상단까지 내려오면 체결, 시가가 낮으면 시가) · 1차 목표 뒤엔 더 안 삼
      매도  1차 목표 50% · 2차 30% · 3차 20% · 1차 뒤 남은 몫은 본전 이탈 시 · 1차 전 손절가 · 20일째 종가
      비용 0.25% 뺀 손익 (산 금액 기준). 20일이 안 지났으면 '진행중' (손익은 마지막 종가 기준 평가)
  결과 칸 res_status = 결과 구분 (1차 목표 · 2차 목표 · 3차 목표 · 매수가매도 · 손절 · 기간 만료 · 미체결, 진행중이면 ' · 보유중')
           res_days = 보유 기간 (체결일 포함 거래일 수, 끝났으면 다 판 날까지)
  장중 탭 (당일단타·종가배팅·상한가포착): 당일매매 추적 기록(Storage track/<탭>/<날짜>.json)의 결과 — 없으면 */results.json
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
LABEL = {"t1": "1차 목표", "t2": "2차 목표", "t3": "3차 목표", "stop": "손절", "flat": "기간 만료", "even": "매수가매도"}
REGRADE_BEFORE = "2026-10-15T09:00:00Z"   # 이 전에 매긴 결과는 새 규칙(추천 다음 날 하루만 매수)으로 다시 매김
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
    r = simulate(o, h, lo, c, zones, t, stop, first_day_only=True)
    full = n >= H
    ext = {"last": float(c[-1]), "max_up": round((float(h.max()) / entry - 1) * 100, 2),
           "max_dn": round((float(lo.min()) / entry - 1) * 100, 2)}
    if r["outcome"] is None:                                           # 추천 다음 날 1차 매수구간에서 못 삼 → 끝
        return _res(row, status="미체결", done=True, filled=0, days=1, **ext)
    out = r["outcome"]
    done = full or r["exit_day"] is not None
    cat = category(out, r)
    status = LABEL[cat] if done else ("보유중" if cat == "flat" else LABEL[cat] + " · 보유중")
    fd = r["first"]
    hold = (r["exit_day"] or n) - (r["fill_day"] or 1) + 1
    return _res(row, status=status, done=done, pnl=round(float(r["pnl"]), 3), filled=r["filled"],
                fill_day=r["fill_day"], d_t1=fd.get("t1"), d_t2=fd.get("t2"), d_t3=fd.get("t3"),
                d_stop=fd.get("stop"), days=hold, **ext)


def category(out: str, r: dict) -> str:
    """결과 구분: 1차·2차 뒤 매수가로 돌아와 판 것 = 매수가매도 · 3차 = 전량 · 그 밖은 닿은 가장 높은 목표 / 손절 / 기간 만료"""
    if r.get("even"):
        return "even"
    return out


def track_result(t: dict) -> dict | None:
    """당일매매 추적 1종목 → 결과 칸 (끝난 것만)"""
    if not t or not t.get("done"):
        return None
    if t.get("bought") is False or t.get("result") == "미체결":
        return {"status": "미체결", "done": True, "filled": 0, "days": 1}
    states = [str(e.get("state")) for e in t.get("events") or []]
    hits = t.get("hits") or {}
    if "매수가매도" in states or "본전 매도" in states or t.get("result") == "매수가매도":
        st = "매수가매도"
    elif hits:
        st = LABEL[max(hits)]                                          # t1 < t2 < t3
    elif t.get("result") == "손절":
        st = "손절"
    else:
        st = "장 마감 청산"
    d0, d1 = str(t.get("date") or "")[:10], str(t.get("exit_time") or "")[:10]
    try:
        hold = int(np.busday_count(d0, d1)) + 1 if d0 and d1 else 1
    except Exception:  # noqa: BLE001
        hold = 1
    return {"status": st, "done": True, "filled": 100, "pnl": _f(t.get("pnl")), "days": max(hold, 1),
            "d_t1": 1 if "t1" in hits else None, "d_t2": 1 if "t2" in hits else None, "d_t3": 1 if "t3" in hits else None}


def grade_intraday(row: dict, results: dict, today: str, tracks: dict | None = None) -> dict | None:
    t = (tracks or {}).get(row["code"])
    if t:
        tr = track_result(t)
        if tr:
            return _res(row, **tr)
        if not t.get("done") and (pd.Timestamp(today) - pd.Timestamp(row["rec_date"])).days <= 7:
            return None
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
    rows = select_all(sb, {"select": SEL, "rec_date": f"gte.{since}",
                           "or": f"(res_done.is.null,res_done.eq.false,res_updated.lt.{REGRADE_BEFORE})"})
    if not rows:
        return 0
    intra = _intra_results(sb)
    tracks: dict[tuple, dict] = {}                                     # (구분, 날짜) → 당일매매 추적 기록

    def track_of(kind: str, day: str) -> dict:
        if (kind, day) not in tracks:
            try:
                b = sb.download(f"track/{kind}/{day}.json")
                tracks[(kind, day)] = (json.loads(b) if b else {}).get("tracks") or {}
            except Exception:  # noqa: BLE001
                tracks[(kind, day)] = {}
        return tracks[(kind, day)]
    codes = {r["code"] for r in rows if r["kind"] in DAILY_KINDS}
    oh = ohlcv[ohlcv["code"].isin(codes) & (ohlcv["date"] > pd.Timestamp(since))]
    by = {c: g for c, g in oh.groupby("code")}
    ups = []
    for r in rows:
        if r["kind"] in DAILY_KINDS:
            g = by.get(r["code"])
            u = grade_daily(r, g) if g is not None else None
        else:
            u = grade_intraday(r, intra.get(r["kind"], {}), today, track_of(r["kind"], str(r["rec_date"])[:10]))
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
            "grid": grid(rows),
            "dt_time": grid_time(rows),
            "by_day": {d: stats([r for r in rows if str(r["rec_date"])[:10] == d]) for d in dates[-60:]}}


# ---------------------------------------------------------------- 통계 > 전체현황 표 (2026-10-15)
GRID_KINDS = ("v3", "nextday", "early", "reversal", "uplimit", "closingbet", "daytrade", "limitcatch")
SKIP = ("계획 없음", "데이터 이상", "결과 없음")


def cat_of(status: str | None) -> str | None:
    """res_status → 표 칸: t1 · t2 · t3 · even(매수가매도) · stop · other(기간 만료·장 마감 등) · unfilled · wait(매수 대기)"""
    s = (status or "").split(" · ")[0].strip()
    if not s or s in SKIP:
        return None
    if s in ("미체결",):
        return "unfilled"
    if s == "매수 대기":
        return "wait"
    if s == "매수가매도":
        return "even"
    if s.startswith("손절") or s == "갭 손절":
        return "stop"
    for k in ("1", "2", "3"):
        if s == f"{k}차 목표":
            return f"t{k}"
    return "other"


def band_of(score) -> int | None:
    s = _f(score)
    if s is None or s < 60:
        return None
    return min(90, int(s // 10) * 10)


def grid(rows: list[dict]) -> dict:
    """날짜 × 점수대 × 구분 묶음 → 앱이 기간으로 더해서 표를 만듦
    {날짜: {"90|v3": {"d": 매매 완료, "h": 보유중(진행중)}}} · 각 {n 추천, f 체결, p 손익 합, t1·t2·t3·even·stop·other: [건수, 보유일 합]}"""
    out: dict[str, dict] = {}
    for r in rows:
        b, k = band_of(r.get("score")), r.get("kind")
        c = cat_of(r.get("res_status"))
        if b is None or k not in GRID_KINDS or c is None:
            continue
        _add(out.setdefault(str(r["rec_date"])[:10], {}).setdefault(f"{b}|{k}", {}), r, c)
    return out


def _add(cell: dict, r: dict, c: str) -> None:
    """한 추천을 칸에 더함: 완료(d) / 보유중(h)"""
    m = cell.setdefault("d" if r.get("res_done") else "h", {"n": 0, "f": 0, "p": 0.0})
    m["n"] += 1
    pnl = _f(r.get("res_pnl"))
    if c in ("unfilled", "wait") or pnl is None:
        return
    m["f"] += 1
    m["p"] = round(m["p"] + pnl, 3)
    x = m.setdefault(c, [0, 0])
    x[0] += 1
    x[1] += int(_f(r.get("res_days")) or 1)


def time_bucket(t) -> str | None:
    """매수(포착) 시각 → 10분 단위 '09:10' (09:00 전은 없음 · 10:00 넘으면 '10:00')"""
    s = str(t or "").strip()
    if len(s) < 5 or s[2] != ":" or s[:5] < "09:00":
        return None
    return "10:00" if s[:5] >= "10:00" else s[:4] + "0"


def grid_time(rows: list[dict], kind: str = "daytrade") -> dict:
    """당일단타 매수시간별: {날짜: {"09:10|90": {"d": …, "h": …}}} (칸 모양은 grid 와 같음)"""
    out: dict[str, dict] = {}
    for r in rows:
        if r.get("kind") != kind:
            continue
        b, c, tb = band_of(r.get("score")), cat_of(r.get("res_status")), time_bucket(r.get("rec_time"))
        if b is None or c is None or tb is None:
            continue
        _add(out.setdefault(str(r["rec_date"])[:10], {}).setdefault(f"{tb}|{b}", {}), r, c)
    return out


def _group(rows, f):
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(f(r), []).append(r)
    return out


def publish(sb) -> dict:
    from ..cloud import publish as pub
    rows = select_all(sb, {"select": "rec_date,kind,code,score,rec_time," + ",".join(RES_COLS)})
    out = summarize(rows)
    pub.publish_backtest(sb, KEY, "추천주 검증", out)
    return out


def run(sb, ohlcv: pd.DataFrame, today: str) -> int:
    n = grade_open(sb, ohlcv, today)
    publish(sb)
    return n
