"""전날 급락 → 오늘 급등 (반등장) 감지 — 당일단타는 더 일찍, 종가배팅은 일시 반등 제외에 씀 (2026-10-27)

  기록  저녁 배치가 종합지수(코스피·코스닥) 일별 등락률을 system_status 'index_daily' {날짜: {KOSPI: %, KOSDAQ: %}} 로 (최근 20거래일)
  판정  전 거래일 지수가 PREV_DROP% 이하로 빠졌고 오늘 지수가 TODAY_UP% 이상 올랐으면(또는 시초 갭 GAP_UP% 이상) 반등장
  기록이 없으면(처음 며칠) 판정 안 함 = 예전과 똑같이 동작
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

KEY = "index_daily"
KEEP = 20
PREV_DROP = -2.0     # 전날 지수 등락 (%) 이하
TODAY_UP = 1.5       # 오늘 지수 등락 (%) 이상
GAP_UP = 1.0         # 또는 시초 갭 (%) 이상


def from_frame(index_df, keep: int = KEEP) -> dict[str, dict[str, float]]:
    """지수 일봉(date·code·close) → {날짜: {코드: 전일 대비 %}} 최근 keep 일"""
    import pandas as pd
    if index_df is None or len(index_df) == 0:
        return {}
    d = index_df[index_df["code"].isin(["KOSPI", "KOSDAQ"])]
    if d.empty:
        return {}
    px = d.pivot_table(index="date", columns="code", values="close").sort_index()
    chg = (px / px.shift(1) - 1) * 100
    out = {}
    for dt, row in chg.tail(keep).iterrows():
        out[pd.Timestamp(dt).strftime("%Y-%m-%d")] = {c: round(float(v), 2) for c, v in row.items() if v == v}
    return out


def record(sb, index_df) -> int:
    """저녁 배치: 지수 일별 등락률 저장 (이미 있는 날짜는 새 값으로 덮어씀). 저장한 날짜 수"""
    from ..cloud import publish as pub
    cur = load(sb)
    cur.update(from_frame(index_df))
    keep = dict(sorted(cur.items())[-KEEP:])
    if keep:
        pub.publish_status(sb, KEY, {"days": keep})
    return len(keep)


def load(sb) -> dict[str, dict[str, float]]:
    if not sb:
        return {}
    try:
        return ((sb.select("system_status", {"select": "payload", "key": f"eq.{KEY}"}) or [{}])[0].get("payload") or {}).get("days") or {}
    except Exception as e:  # noqa: BLE001
        log.warning("지수 일별 기록 읽기 실패: %s", e)
        return {}


def prev_chg(days: dict, today: str, code: str) -> float | None:
    """today(YYYY-MM-DD) 바로 앞 거래일의 그 지수 등락률 — 기록이 없으면 None"""
    prior = [d for d in sorted(days) if d < today]
    if not prior:
        return None
    v = (days[prior[-1]] or {}).get(code)
    return None if v is None else float(v)


def rebound(prev: float | None, chg: float | None, gap: float | None = None) -> dict | None:
    """반등장이면 {prev, chg, why}, 아니면 None. prev = 전날 지수 등락 · chg = 오늘 지수 등락 · gap = 오늘 시초 갭"""
    if prev is None or prev > PREV_DROP:
        return None
    up = (chg is not None and chg >= TODAY_UP) or (gap is not None and gap >= GAP_UP)
    if not up:
        return None
    now = f"+{chg:.1f}%" if chg is not None else f"갭 +{gap:.1f}%"
    return {"prev": round(prev, 2), "chg": None if chg is None else round(chg, 2),
            "why": f"전날 지수 {prev:+.1f}% → 오늘 {now} (반등장)"}


def for_market(days: dict, today: str, indices, market: str = "KOSPI") -> dict | None:
    """지금 시세(indices 표: code·chg_pct·open·close) 로 그 시장의 반등장 여부"""
    if indices is None or len(indices) == 0 or not days:
        return None
    rows = {str(r["code"]): r for r in indices.to_dict("records")}
    r = rows.get(market) or rows.get("KOSPI")
    if not r:
        return None
    code = str(r["code"])
    chg = r.get("chg_pct")
    gap = None
    try:
        c, o = float(r["close"]), float(r["open"])
        prev_close = c / (1 + float(chg) / 100)
        gap = (o / prev_close - 1) * 100
    except Exception:  # noqa: BLE001
        pass
    return rebound(prev_chg(days, today, code), None if chg is None or chg != chg else float(chg), gap)


def days_for(sb, today: str) -> dict[str, dict[str, float]]:
    """읽기: 저장된 기록 → 어제까지가 없으면 Storage 의 지수 일봉(data/index.parquet, 저녁 배치가 올림)에서 바로 계산 (처음 며칠 대비)"""
    days = load(sb)
    if sb and not [d for d in days if d < today]:
        try:
            import io

            import pandas as pd
            b = sb.download("data/index.parquet")
            if b:
                days = {**days, **from_frame(pd.read_parquet(io.BytesIO(b)))}
        except Exception as e:  # noqa: BLE001
            log.warning("지수 일봉 받기 실패: %s", e)
    return days
