"""저녁 추천주(V3·유망주·상승초기·추세전환·상파)의 장중 체결 시각 기록 (2026-10-22)

추천은 저녁 배치에서 나오고 유효기간은 다음 거래일 하루. 그날 1차 매수구간에 처음 닿은 분(分)을 1분봉에서 찾아
Storage stats/fill_times.json 에 {"추천일|구분|종목": "HH:MM"} 으로 모아 둠 (통계 '시간대별' 의 매수시간).
  - 시가가 구간 상단 이하면 09:00 (시가에 삼) · 아니면 저가가 상단 이하가 된 첫 분
  - 과거 1분봉은 KIS 보관 기간이 짧아 매일 저녁 방금 끝난 날만 채움 → 기록은 오늘부터 쌓임
"""
from __future__ import annotations

import json
import logging

import pandas as pd

from ..cloud.recommend import DAILY_KINDS

log = logging.getLogger(__name__)
FILE = "stats/fill_times.json"


def key(r: dict) -> str:
    return f"{str(r['rec_date'])[:10]}|{r['kind']}|{r['code']}"


def load(sb) -> dict:
    try:
        b = sb.download(FILE)
        return json.loads(b) if b else {}
    except Exception:  # noqa: BLE001
        return {}


def first_touch(m: pd.DataFrame, top: float) -> str | None:
    """1분봉 m (time·open·low) 에서 1차 구간 상단 top 에 처음 닿은 시각 'HH:MM'"""
    if m is None or m.empty or not top:
        return None
    m = m.sort_values("time")
    if float(m["open"].iloc[0]) <= top:
        return m["time"].iloc[0].strftime("%H:%M")
    hit = m[m["low"] <= top]
    return None if hit.empty else hit["time"].iloc[0].strftime("%H:%M")


def next_day(ohlcv: pd.DataFrame, code: str, rec_date: str) -> pd.Timestamp | None:
    g = ohlcv[(ohlcv["code"] == code) & (ohlcv["date"] > pd.Timestamp(rec_date))]
    return None if g.empty else pd.Timestamp(g["date"].min())


def resolve(sb, kis, ohlcv: pd.DataFrame, today: str, lookback: int = 5) -> int:
    """최근 lookback 일 저녁 추천 중 다음 날 체결된 것의 체결 시각을 채움 (이미 있는 것은 건너뜀)"""
    from .rec_eval import select_all
    since = (pd.Timestamp(today) - pd.Timedelta(days=lookback + 3)).strftime("%Y-%m-%d")
    rows = select_all(sb, {"select": "rec_date,kind,code,zone1_high,entry,res_fill_day,res_status",
                           "rec_date": f"gte.{since}", "kind": "in.(" + ",".join(DAILY_KINDS) + ")"})
    fills = load(sb)
    new = 0
    for r in rows:
        k = key(r)
        if k in fills or r.get("res_fill_day") != 1:
            continue
        day = next_day(ohlcv, r["code"], str(r["rec_date"])[:10])
        if day is None or (pd.Timestamp(today) - day).days > lookback:
            continue
        top = float(r.get("zone1_high") or r.get("entry") or 0)
        try:
            ds = day.strftime("%Y%m%d")
            m = kis.minute_bars_day(r["code"], "090000", "153000", day=None if day == pd.Timestamp(today) else ds)
            t = first_touch(m, top)
        except Exception as e:  # noqa: BLE001
            log.warning("체결 시각 조회 실패 %s: %s", k, e)
            continue
        if t:
            fills[k] = t
            new += 1
    if new:
        try:
            sb.upload(FILE, json.dumps(fills, ensure_ascii=False).encode(), "application/json")
        except Exception as e:  # noqa: BLE001
            log.warning("체결 시각 저장 실패: %s", e)
    log.info("체결 시각 기록: 새로 %d건 (누적 %d)", new, len(fills))
    return new
