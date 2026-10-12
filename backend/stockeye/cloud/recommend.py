"""추천 기록 (검증용, 영구 보관) → Supabase public.recommendations

관심 목록에 나온 종목을 '그때 계획 그대로' 남겨 두고 나중에 실제 결과와 맞춰 본다.
(candidates 표는 60일만 남기고 같은 날 다시 돌리면 덮어쓰므로 검증용으로 따로 둠)

  언제        저녁 배치 (V3·익일유망주·상승초기·추세전환·상파 목록 전부)
              당일단타 '진입 조건 충족' · 종가배팅 '매수 후보' · 상한가포착 '매수 검토' 가 처음 나온 때 (PC·종목찾기 모두)
  중복        추천일 + 구분 + 종목 이 같으면 하루 첫 기록만 (나중 것은 무시 — 덮어쓰지 않음)
              구분이 다르면 따로 저장: 같은 날 V3·익일유망주·당일단타 … 에 겹치면 구분마다 한 줄씩 전부 남음
              (한 종목 한 줄로 보기: DB 뷰 recommendation_overlaps — 겹친 구분 목록 + 구분별 계획)
  매수가      entry = 1차 매수구간 중앙값 ((하단 + 상단) / 2). 장중 탭은 그 탭의 진입·매수가
              entry_avg = 1·2·3차 구간 중앙값을 비중대로 평균 (2·3차는 눌림 때만 사는 구간)
  손익비      rr1 = (1차 목표 − 매수가) ÷ (매수가 − 손절가) · rr2 = 2차 목표 기준
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)
TABLE = "recommendations"
DAILY_KINDS = ("v3", "nextday", "early", "reversal", "uplimit")
COLS = ("rec_date", "kind", "code", "name", "rec_time", "source", "rank", "score", "status", "verdict", "price",
        "zone1_low", "zone1_high", "zone1_w", "zone2_low", "zone2_high", "zone2_w", "zone3_low", "zone3_high", "zone3_w",
        "entry", "entry_avg", "target1", "target2", "target3", "stop", "stop_pct", "target1_pct", "target2_pct",
        "rr1", "rr2", "market", "sector", "version", "payload")


def _n(v, d: int | None = None):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return round(f, d) if d is not None else f


def _pct(a, b):
    a, b = _n(a), _n(b)
    return round((a / b - 1) * 100, 2) if a and b else None


def _rr(t, e, s):
    t, e, s = _n(t), _n(e), _n(s)
    return round((t - e) / (e - s), 2) if t and e and s and e > s else None


def _row(**kw) -> dict:
    """모든 행이 같은 칸을 갖게 (한 번에 여러 행 넣을 때 칸이 다르면 빈칸이 기본값으로 안 채워짐)"""
    r = {c: kw.get(c) for c in COLS}
    e = r["entry"]
    r["stop_pct"] = _pct(r["stop"], e)
    r["target1_pct"] = _pct(r["target1"], e)
    r["target2_pct"] = _pct(r["target2"], e)
    r["rr1"] = _rr(r["target1"], e, r["stop"])
    r["rr2"] = _rr(r["target2"], e, r["stop"])
    return r


def from_candidate(kind: str, date: str, c: dict, source: str = "daily", version: str | None = None) -> dict:
    """저녁 배치 관심 탭 후보 → 행 (plan: price · entry_low/high · zones · target1~3 · stop)"""
    p = c.get("plan") or {}
    zones = [z for z in (p.get("zones") or []) if isinstance(z, dict) and z.get("low")]
    if not zones and p.get("entry_low"):
        zones = [{"low": p.get("entry_low"), "high": p.get("entry_high"), "weight": 100}]
    z = {}
    for i, zz in enumerate(zones[:3], 1):
        z |= {f"zone{i}_low": _n(zz.get("low")), f"zone{i}_high": _n(zz.get("high")), f"zone{i}_w": _n(zz.get("weight"))}
    mids = [((_n(zz.get("low")) or 0) + (_n(zz.get("high")) or 0)) / 2 for zz in zones[:3]]
    ws = [_n(zz.get("weight")) or 0 for zz in zones[:3]]
    entry = round(mids[0]) if mids and mids[0] else _n(p.get("price"))
    avg = round(sum(m * w for m, w in zip(mids, ws)) / sum(ws)) if mids and sum(ws) > 0 else entry
    return _row(rec_date=date, kind=kind, code=c.get("code"), name=c.get("name"), rec_time="마감", source=source,
                rank=c.get("rank"), score=_n(c.get("score"), 2), status=c.get("status") or c.get("grade"),
                verdict=p.get("verdict"), price=_n(p.get("price")), entry=entry, entry_avg=avg,
                target1=_n(p.get("target1")), target2=_n(p.get("target2")), target3=_n(p.get("target3")),
                stop=_n(p.get("stop")), market=c.get("market"), sector=c.get("sector"), version=version, payload=c, **z)


def from_intraday(kind: str, date: str, r: dict, source: str, version: str | None = None, at: str | None = None) -> dict:
    """장중 탭 (당일단타·종가배팅·상한가포착) 후보 → 행"""
    entry = _n(r.get("entry"))
    if kind == "closingbet":
        z = {"zone1_low": _n(r.get("buy_lo")), "zone1_high": _n(r.get("buy_hi")), "zone1_w": 100}
    else:
        z = {"zone1_low": entry, "zone1_high": entry, "zone1_w": 100}
    keep = {k: r.get(k) for k in ("type", "group", "parts", "reasons", "risks", "lock", "book", "gap", "vwap",
                                  "chg_pct", "value", "limit", "exit_rules", "exit_time", "news_level", "time_bucket")
            if r.get(k) is not None}
    return _row(rec_date=date, kind=kind, code=r.get("code"), name=r.get("name"), rec_time=r.get("time") or at, source=source,
                rank=r.get("rank"), score=_n(r.get("score"), 2), status=r.get("status"),
                verdict=r.get("type") or r.get("group"), price=_n(r.get("price")), entry=entry, entry_avg=entry,
                target1=_n(r.get("t1")), target2=_n(r.get("t2")), target3=None, stop=_n(r.get("stop")),
                sector=r.get("sector"), version=version or r.get("version"), payload=keep, **z)


def record(sb, rows: list[dict]) -> int:
    """하루 첫 기록만 남김 (같은 추천일·구분·종목은 무시)"""
    rows = [r for r in rows if r.get("code") and r.get("rec_date") and r.get("kind")]
    if not sb or not rows:
        return 0
    seen, uniq = set(), []
    for r in rows:                                        # 한 번에 넣는 묶음 안의 중복도 정리 (첫 것)
        k = (r["rec_date"], r["kind"], r["code"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    sb.upsert(TABLE, uniq, "rec_date,kind,code", ignore_duplicates=True)
    return len(uniq)


def record_daily(sb, report: dict) -> int:
    """저녁 배치: 리포트의 관심 탭 목록 전부"""
    d = str(report["date"])[:10]
    rows = []
    for k in DAILY_KINDS:
        v = (report.get("strategies") or {}).get(k) or {}
        ver = (report.get(k) or {}).get("version") if isinstance(report.get(k), dict) else None
        rows += [from_candidate(k, d, c, "daily", ver) for c in v.get("candidates") or []]
    n = record(sb, rows)
    log.info("추천 기록: %s %d건 (같은 날 이미 있는 것은 그대로)", d, n)
    return n


class IntradayRecorder:
    """장중 탭: 상태가 처음 '실제 후보'가 된 종목만 한 번씩 (프로세스 안에서도 중복 안 보냄)"""
    STATUS = {"daytrade": ("진입 조건 충족",), "closingbet": ("매수 후보",), "limitcatch": ("매수 검토",)}

    def __init__(self, sb, kind: str, source: str):
        self.sb, self.kind, self.source = sb, kind, source
        self.done: set[str] = set()

    def __call__(self, date: str, items: list[dict], version: str | None = None, at: str | None = None) -> int:
        if not self.sb:
            return 0
        new = [r for r in items if r.get("status") in self.STATUS[self.kind] and r.get("code") not in self.done]
        if not new:
            return 0
        try:
            n = record(self.sb, [from_intraday(self.kind, date, r, self.source, version, at) for r in new])
            self.done |= {r["code"] for r in new}
            return n
        except Exception as e:  # noqa: BLE001 — 기록 실패가 장중 계산을 멈추지 않게
            log.warning("추천 기록 실패 (%s): %s", self.kind, e)
            return 0
