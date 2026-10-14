"""넥스트레이드(NXT) 프리·애프터마켓 기록 (2026-10-14) — 정규장 밖 가격이 당일단타·종가배팅 결과와 관계있는지 쌓기

  프리마켓 (08:00~08:50)  PC 22_intraday 가 08:52 쯤 전 종목 네이버 시세 1번 → 각 종목 NXT 가격 · 전일 종가 대비 %
                          → Storage nxt/pre/<날짜>.json · 그날 고정되는 당일단타·상한가포착 추적에 'nxt_pre' (전일 종가 대비 %)
                          · 전날 종가배팅(이월) 추적에도 'nxt_pre' (다음 날 아침 갭을 미리 봄)
  애프터마켓 (15:30~20:00) 저녁 배치(18:40~)가 오늘 산 종가배팅 종목만 네이버 시세 → 'nxt_after' (오늘 KRX 종가 대비 % · 그 시각)
  통계 (검증 > 시장·업종)
    당일단타: 'NXT 프리마켓 등락' 구간별 승률·손익 (intraday_ctx 행의 nxt_pre)
    종가배팅: 애프터마켓 등락 · 다음 날 프리마켓 등락 구간별 결과 → system_status 'closingbet_nxt' (최근 60건)
  네이버 시세의 overMarketPriceInfo (공식 API 아님) — 없으면 비워 둠
"""
from __future__ import annotations

import json
import logging

import pandas as pd

log = logging.getLogger(__name__)
KEEP = 60


def pre_snapshot(snap: pd.DataFrame) -> dict[str, list]:
    """08:50 전후 네이버 시세 → {종목: [NXT 가격, 전일 종가 대비 %]} (장 전이라 price = 전일 종가)"""
    out = {}
    if snap is None or snap.empty or "over_price" not in snap:
        return out
    for r in snap.itertuples():
        op, base = getattr(r, "over_price", None), getattr(r, "close", None)
        if op and base and op > 0 and base > 0:
            out[str(r.code)] = [float(op), round((op / base - 1) * 100, 2)]
    return out


def after_of(q: dict | None, close: float | None) -> dict | None:
    """저녁 시세 1종목 → {price, chg(오늘 KRX 종가 대비 %), status}"""
    if not q or not q.get("over_price") or not close:
        return None
    return {"price": float(q["over_price"]), "chg": round((q["over_price"] / close - 1) * 100, 2),
            "status": q.get("over_status")}


def bucket(v, cuts, labels):
    if v is None:
        return None
    for c, lab in zip(cuts, labels):
        if v < c:
            return lab
    return labels[-1]


def _agg(rows):
    n = len(rows)
    if not n:
        return {"n": 0}
    pn = [r["pnl"] for r in rows if r.get("pnl") is not None]
    return {"n": n, "win": round(sum(r["result"] == "이익실현" for r in rows) / n * 100, 1),
            "pnl": round(sum(pn) / len(pn), 2) if pn else None, "sum": round(sum(pn), 2) if pn else None}


def cb_stats(rows: list[dict]) -> dict:
    done = [r for r in rows if r.get("result") not in (None, "미체결")]
    groups = []
    for title, key, cuts, labels in (
            ("애프터마켓 (매수 날 저녁, 종가 대비)", "after", [-1, 1], ["−1% 아래", "−1 ~ +1%", "+1% 이상"]),
            ("다음 날 프리마켓 (전일 종가 대비)", "pre", [-1, 1, 3], ["−1% 아래", "−1 ~ +1%", "+1 ~ +3%", "+3% 이상"])):
        g = []
        for lab in labels:
            sel = [r for r in done if bucket(r.get(key), cuts, labels) == lab]
            g.append({"label": lab, **_agg(sel)})
        g.append({"label": "기록 없음", **_agg([r for r in done if r.get(key) is None])})
        groups.append({"title": title, "rows": g})
    return {"all": _agg(done), "groups": groups}


def record_after(sb, day: str, quotes_fn) -> int:
    """저녁 배치: 오늘 산 종가배팅(매수됨) → NXT 애프터마켓 가격 기록 (추적 파일에 'nxt_after')"""
    from ..trading.intraday_track import Tracker
    tr = Tracker(sb, "closingbet", day, user_id="")
    codes = [c for c, t in tr.tracks.items() if t.get("bought")]
    if not codes:
        return 0
    snap = quotes_fn(codes)
    q = {r["code"]: r for r in snap.to_dict("records")} if snap is not None and not snap.empty else {}
    n = 0
    for c in codes:
        a = after_of(q.get(c), (q.get(c) or {}).get("close"))
        if a:
            a["time"] = pd.Timestamp.now(tz="Asia/Seoul").strftime("%H:%M")
            tr.tracks[c]["nxt_after"] = a
            n += 1
    tr.save()
    return n


def publish_cb(sb, day: str) -> dict:
    """어제 종가배팅(오늘 끝난 것) → 행 [날짜·종목·결과·손익·애프터%·다음날 프리%] 누적 → system_status 'closingbet_nxt'"""
    from ..trading.intraday_track import Tracker
    from ..cloud import publish as pub
    tr = Tracker(sb, "closingbet", day, user_id="")
    rows = []
    for t in tr.prev.values():
        if not t.get("bought"):
            continue
        rows.append({"date": t["date"], "code": t["code"], "name": t.get("name"), "buy_time": t.get("buy_time"),
                     "entry": t.get("entry"), "result": t.get("result") or "진행중", "pnl": t.get("pnl"),
                     "after": (t.get("nxt_after") or {}).get("chg"), "after_time": (t.get("nxt_after") or {}).get("time"),
                     "pre": (t.get("nxt_pre") or [None, None])[1] if isinstance(t.get("nxt_pre"), list) else None})
    try:
        old = (sb.select("system_status", {"select": "payload", "key": "eq.closingbet_nxt"}) or [{}])[0].get("payload") or {}
    except Exception:  # noqa: BLE001
        old = {}
    dates = {r["date"] for r in rows}
    allr = ([r for r in (old.get("rows") or []) if r.get("date") not in dates] + rows)[-KEEP:]
    pub.publish_status(sb, "closingbet_nxt", {"updated": day, "rows": allr, "stats": cb_stats(allr)})
    return {"rows": len(rows), "total": len(allr)}


def save_pre(sb, day: str, pre: dict) -> None:
    sb.upload(f"nxt/pre/{day}.json", json.dumps(pre, ensure_ascii=False).encode("utf-8"), "application/json")
