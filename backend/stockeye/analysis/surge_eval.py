"""급등예상 저녁 배치 (2026-11-02) — ① 오늘 종가 기준 다음날 목록 만들기 ② 지난 목록들을 다음 거래일 일봉으로 채점·누적
  Storage  surge/lists/<기준일>.json   목록(기준일 종가 → 다음 거래일 관찰) + 점수 상위 100
           surge/results.json          {rows: 종목별 채점(최근 KEEP), days: 날짜별 요약(최근 120)}
  system_status 'surge'        {date, items(20), model, prev(가장 최근 채점일 요약+종목별+놓친 상한가), stats}
                'surge_stats'  {stats, days(최근 30), rows(최근 80), hist(전체 채점 행 [기준일·종가%·고가%·상한가 닿음·종가 상한가] — 앱 분포 그래프)}   ← 앱 '검증' 화면
"""
from __future__ import annotations

import json
import logging

import pandas as pd

from ..engine import surge as sg

log = logging.getLogger(__name__)
RES_FILE = "surge/results.json"
KEEP_ROWS, KEEP_DAYS = 1500, 120


def _dl(sb, path):
    try:
        b = sb.download(path)
        return json.loads(b) if b else None
    except Exception:  # noqa: BLE001
        return None


def _up(sb, path, obj):
    sb.upload(path, json.dumps(obj, ensure_ascii=False, default=str).encode(), "application/json")


def grade_day(panel: pd.DataFrame, lst: dict) -> tuple[list[dict], dict]:
    """목록 하나를 그 다음 거래일 일봉으로 채점 → (종목별 행, 날짜 요약)"""
    L = pd.Timestamp(lst["date"])
    nxt = panel[(panel.date > L)].date.min()
    if pd.isna(nxt):
        return [], {}
    bars_df = panel[panel.date == nxt].set_index("code")
    bars = {c: {"open": r.open, "high": r.high, "low": r.low, "close": r.close} for c, r in bars_df.iterrows()}
    rows = sg.grade(lst["items"], bars)
    for r in rows:
        r["date"] = lst["date"]
    uni = panel[(panel.date == L) & panel.ok]
    nchg = uni.code.map(bars_df.chg_pct)
    lu_all = uni[uni.y == 1]
    scores = lst.get("scores") or []
    top20 = {i["code"] for i in lst["items"]}
    top100 = {c for c, _ in scores}
    st = sg.stats(rows)["all"]
    day = {"date": lst["date"], "next": str(nxt.date()), "n": st.get("n", 0), "reached": st.get("reached"), "closed": st.get("closed"),
           "h15": st.get("h15"), "h20": st.get("h20"), "close_avg": st.get("close_avg"),
           "base_lu": round(float(uni.y.mean()) * 100, 2) if len(uni) else None,
           "base_close": round(float(nchg.mean()), 2) if len(uni) else None,
           "lu_total": int(len(lu_all)), "lu_in20": int(lu_all.code.isin(top20).sum()), "lu_in100": int(lu_all.code.isin(top100).sum()),
           "missed": sg.missed(panel, L, scores, top=8)}
    return rows, day


def run(sb, pit, today: str) -> dict:
    panel = sg.prepare(pit)
    last = panel.date.max()
    model, info = sg.fit(panel)
    res = sg.pick(panel, model, last)
    lst = {"date": str(last.date()), "version": sg.VERSION, "model": info, "items": res["items"], "scores": res["scores"], "flow": res.get("flow") or {},
           "n_universe": res.get("n_universe")}
    _up(sb, f"surge/lists/{lst['date']}.json", lst)

    saved = _dl(sb, RES_FILE) or {}
    rows, days = saved.get("rows") or [], saved.get("days") or []
    done = {d["date"] for d in days}
    td = sorted(panel.date.unique())
    added = 0
    for L in [pd.Timestamp(x) for x in td[-9:-1]]:                   # 마지막 날 이전 8 거래일 중 채점 안 한 것
        ds = str(L.date())
        if ds in done:
            continue
        lst_l = _dl(sb, f"surge/lists/{ds}.json")
        if not lst_l:
            continue
        r, d = grade_day(panel, lst_l)
        if d:
            rows += r
            days.append(d)
            added += 1
    rows = sorted(rows, key=lambda r: (r["date"], r.get("rank") or 99))[-KEEP_ROWS:]
    days = sorted(days, key=lambda d: d["date"])[-KEEP_DAYS:]
    if added:
        _up(sb, RES_FILE, {"rows": rows, "days": days})
    st = sg.stats(rows)
    st["base_lu"] = round(sum(d["base_lu"] or 0 for d in days) / len(days), 2) if days else None
    st["base_close"] = round(sum(d["base_close"] or 0 for d in days) / len(days), 2) if days else None
    prev = days[-1] if days else None
    prev_rows = [r for r in rows if prev and r["date"] == prev["date"]]
    from ..cloud import publish as pub
    pub.publish_status(sb, "surge", {"updated": today, "version": sg.VERSION, "date": lst["date"], "model": info,
                                     "items": lst["items"], "prev": ({**prev, "rows": prev_rows} if prev else None), "stats": st})
    pub.publish_status(sb, "surge_stats", {"updated": today, "version": sg.VERSION, "stats": st, "days": days[-30:], "rows": rows[-80:],
                                           "hist": [[r["date"], r.get("close"), r.get("high"), bool(r.get("reached")), bool(r.get("closed"))] for r in rows]})
    return {"date": lst["date"], "items": len(lst["items"]), "graded": added, "train": info["rows"], **(st.get("all") or {})}
