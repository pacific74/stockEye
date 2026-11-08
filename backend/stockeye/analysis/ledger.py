"""분석 장부 (2026-11-09) — 장 마감 후 '그날 단타 대상이 될 만했던 종목'을 모아 지표와 함께 저장 → 나중에 조건을 바꿔 검증

  대상 = 거래량 상위 + 상승률 상위 (거래대금은 최소 10억만 — 단타는 변동폭이 중요하고 거래대금 상위는 대형주만 나옴)
  종목마다: 당일 일봉 지표(등락·갭·고저 폭·종가 위치·거래량 배수·평균 변동폭·이평선 이격) + 선발 경로(급등목록·NXT 프리/애프터·수급)
  저장: Storage ledger/<날짜>.json  (PC 분봉 보관과 날짜·종목코드로 이어짐 → 주간 최적화가 같이 읽음)
  GitHub Actions 저녁 배치에서 돌아 PC 가 꺼져 있어도 쌓임
"""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)
MIN_VALUE = 10e8
TOP_VOLUME, TOP_RISE, MIN_RISE = 30, 30, 3.0
VERSION = "L-1"


def build(oh: pd.DataFrame, day, names: dict | None = None, extra: dict | None = None) -> list[dict]:
    """oh: 일봉(date·code·open·high·low·close·volume[·value]) — day 이하만 사용. extra: {코드: {키: 값}} 선발 경로 정보"""
    day = pd.Timestamp(day)
    d = oh[oh["date"] <= day]
    today = d[d["date"] == day]
    if today.empty:
        return []
    t = today.copy()
    t["value"] = t["value"] if "value" in t and t["value"].notna().any() else t["close"] * t["volume"]
    t = t[t["value"] >= MIN_VALUE]
    hist = d[(d["date"] < day) & (d["date"] >= day - pd.Timedelta(days=60))]
    g = {c: x.sort_values("date") for c, x in hist.groupby("code")}
    rows = []
    for r in t.itertuples():
        h = g.get(r.code)
        if h is None or len(h) < 10:
            continue
        pc = float(h["close"].iloc[-1])
        if pc <= 0:
            continue
        h20 = h.tail(20)
        adr = float(((h20["high"] - h20["low"]) / h20["close"].shift(1).fillna(h20["close"])).mean())
        av = float(h20["volume"].mean()) or np.nan
        ma5, ma20 = float(h["close"].tail(5).mean()), float(h20["close"].mean())
        hi30 = float(h["high"].tail(30).max())
        rng = float(r.high) - float(r.low)
        rows.append({
            "code": r.code, "name": (names or {}).get(r.code, r.code),
            "close": float(r.close), "chg": round((r.close / pc - 1) * 100, 2), "gap": round((r.open / pc - 1) * 100, 2),
            "range": round(rng / pc * 100, 2), "hi_pct": round((r.high / pc - 1) * 100, 2),
            "close_pos": round((r.close - r.low) / rng, 2) if rng > 0 else None,
            "volume": int(r.volume), "value": float(r.value),
            "vol_x": round(float(r.volume) / av, 2) if av == av and av else None, "adr": round(adr * 100, 2),
            "ma5_gap": round((r.close / ma5 - 1) * 100, 2), "ma20_gap": round((r.close / ma20 - 1) * 100, 2),
            "near_hi30": round((r.close / hi30 - 1) * 100, 2),
            **((extra or {}).get(r.code) or {}),
        })
    if not rows:
        return []
    df = pd.DataFrame(rows)
    vol = df.sort_values("volume", ascending=False).head(TOP_VOLUME)["code"]
    rise = df[df["chg"] >= MIN_RISE].sort_values("chg", ascending=False).head(TOP_RISE)["code"]
    srcs = {}
    for c in vol:
        srcs.setdefault(c, []).append("거래량상위")
    for c in rise:
        srcs.setdefault(c, []).append("상승상위")
    out = [{**r, "src": srcs[r["code"]]} for r in rows if r["code"] in srcs]
    return sorted(out, key=lambda r: -r["value"])


def forward(oh: pd.DataFrame, rows: list[dict], day) -> list[dict]:
    """다음 거래일 시가·고가·종가 (장부에 나중에 채움: 오늘 밤 종목이 내일 어땠나)"""
    day = pd.Timestamp(day)
    nxt = oh[oh["date"] > day]
    if nxt.empty:
        return rows
    nd = nxt["date"].min()
    n = nxt[nxt["date"] == nd].set_index("code")
    for r in rows:
        if r["code"] in n.index and r["close"] > 0:
            x = n.loc[r["code"]]
            r["next"] = {"date": nd.strftime("%Y-%m-%d"), "open": round((x["open"] / r["close"] - 1) * 100, 2),
                         "high": round((x["high"] / r["close"] - 1) * 100, 2), "close": round((x["close"] / r["close"] - 1) * 100, 2)}
    return rows


def run(sb, oh: pd.DataFrame, day: str, names: dict | None = None, extra: dict | None = None) -> dict:
    """오늘 장부 저장 + 직전 장부에 '다음 거래일 결과' 채움"""
    day_ts = pd.Timestamp(day)
    rows = build(oh, day_ts, names, extra)
    if not rows:
        return {"rows": 0}
    key = f"ledger/{day_ts:%Y-%m-%d}.json"
    sb.upload(key, json.dumps({"day": f"{day_ts:%Y-%m-%d}", "version": VERSION, "rows": rows}, ensure_ascii=False).encode("utf-8"),
              "application/json")
    filled = 0
    prev = sorted(oh[oh["date"] < day_ts]["date"].unique())[-1:]
    for pd_ in prev:                                              # 어제 장부에 오늘 결과 채우기
        pk = f"ledger/{pd.Timestamp(pd_):%Y-%m-%d}.json"
        try:
            old = json.loads(sb.download(pk) or b"{}")
        except Exception:  # noqa: BLE001
            old = {}
        if old.get("rows"):
            forward(oh[oh["date"] <= day_ts], old["rows"], pd_)
            sb.upload(pk, json.dumps(old, ensure_ascii=False).encode("utf-8"), "application/json")
            filled = len(old["rows"])
    log.info("분석 장부 %s: %d종목 (어제 장부 %d종목에 결과 채움)", day, len(rows), filled)
    return {"rows": len(rows), "filled": filled}
