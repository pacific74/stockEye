"""급등예상 장중 지켜보기 + 아침 요약 (PC 22_intraday.bat 에서 사용 · 2026-11-02)
  · 저녁 배치가 만든 목록(system_status 'surge')을 다음날 09:00~15:20 1분마다 네이버 시세 한 번(전 종목 묶음)으로 지켜봄
    → system_status 'surge_live' (앱 급등예상 화면) · 처음 +20% / 상한가에 닿으면 관리자 알림
  · 아침 08:50 이후 한 번: 전날 목록 결과 요약을 관리자 ntfy 로 (같은 내용이 앱 화면에도 있음)
⚠ 매수 신호가 아님 — 목록이 얼마나 맞는지 쌓아 보는 관찰용
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)
LIVE_START, LIVE_END = "09:00", "15:21"
LEVELS = (("lu", 29.0, "상한가 도달"), ("h20", 20.0, "+20%"), ("h15", 15.0, "+15%"), ("h10", 10.0, "+10%"))


def stage(chg: float, high: float, lock_tol: float = 0.2) -> str:
    """현재 등락률·고가 등락률(%) → 한 줄 상태"""
    if chg >= 29.0:
        return "상한가"
    if high >= 29.0:
        return "상한가 풀림"
    if high >= 20.0:
        return "+20% 돌파"
    if high >= 15.0:
        return "+15% 돌파"
    if high >= 10.0:
        return "+10% 돌파"
    if chg <= -3.0:
        return "하락"
    return "상승 중" if chg >= 3.0 else "대기"


class SurgeWatch:
    def __init__(self, items: list[dict], list_date: str, day: str):
        self.items = items
        self.list_date, self.day = list_date, day
        self.first: dict[str, dict[str, str]] = {}          # code → {레벨: 처음 닿은 시각}
        self.rows: list[dict] = []

    @classmethod
    def load(cls, sb, day: str):
        """오늘보다 앞선 날짜의 목록이 있으면 SurgeWatch, 없으면 None"""
        try:
            rows = sb.select("system_status", {"select": "payload", "key": "eq.surge"}) or []
        except Exception as e:  # noqa: BLE001
            log.warning("급등예상 목록 읽기 실패: %s", e)
            return None
        p = (rows[0].get("payload") if rows else None) or {}
        if not p.get("items") or not p.get("date") or str(p["date"]) >= day:
            return None
        return cls(p["items"], str(p["date"]), day), p

    def codes(self) -> list[str]:
        return [i["code"] for i in self.items]

    def update(self, quotes: list[dict], hm: str) -> list[tuple[dict, str]]:
        """시세(코드별 open/high/low/close) 반영 → 새로 닿은 레벨 [(item, 레벨이름)] (알림 대상은 호출쪽이 고름)"""
        q = {str(r["code"]): r for r in quotes}
        new, rows = [], []
        for it in self.items:
            r = q.get(it["code"])
            pc = it.get("close")
            if not r or not pc:
                rows.append({"code": it["code"], "name": it.get("name"), "rank": it.get("rank"), "score": it.get("score"),
                             "status": "시세 없음"})
                continue
            chg, hi = (r["close"] / pc - 1) * 100, (r["high"] / pc - 1) * 100
            lo, gap = (r["low"] / pc - 1) * 100, (r["open"] / pc - 1) * 100
            f = self.first.setdefault(it["code"], {})
            for key, th, label in LEVELS:
                if hi >= th and key not in f:
                    f[key] = hm
                    new.append((it, label))
            rows.append({"code": it["code"], "name": it.get("name"), "rank": it.get("rank"), "score": it.get("score"),
                         "price": r["close"], "chg": round(chg, 2), "high": round(hi, 2), "low": round(lo, 2), "gap": round(gap, 2),
                         "status": stage(chg, hi), "first": dict(f), "reasons": it.get("reasons")})
        self.rows = rows
        return new

    def payload(self, hm: str) -> dict:
        n = len(self.rows)
        cnt = lambda k: sum(1 for r in self.rows if k in (r.get("first") or {}))  # noqa: E731
        return {"date": self.day, "time": hm, "list_date": self.list_date, "n": n,
                "reached": cnt("lu"), "h20": cnt("h20"), "h15": cnt("h15"), "h10": cnt("h10"),
                "locked": sum(1 for r in self.rows if r.get("status") == "상한가"), "rows": self.rows}


def alert_text(it: dict, label: str, hm: str, row: dict | None = None) -> tuple[str, str]:
    r = row or {}
    return (f"급등예상 {label} · {it.get('name')}",
            f"{hm} · 목록 {it.get('rank')}위(점수 {it.get('score')}) · 지금 {r.get('chg', 0):+.1f}% · 고가 {r.get('high', 0):+.1f}%\n"
            + " · ".join(it.get("reasons") or []))


def morning_text(p: dict) -> tuple[str, str]:
    """저녁 배치 'surge' 상태 → 아침 요약 (제목, 본문)"""
    prev = p.get("prev") or {}
    st = (p.get("stats") or {}).get("all") or {}
    lines = []
    if prev:
        lines.append(f"어제({prev.get('next', '?')}) 결과 — {prev.get('date')} 저녁 목록 {prev.get('n')}종목")
        lines.append(f"상한가 닿음 {prev.get('reached')}% · 종가 잠김 {prev.get('closed')}% · +15% {prev.get('h15')}% · +20% {prev.get('h20')}%")
        lines.append(f"종가 평균 {prev.get('close_avg'):+.2f}% (전체 종목 평균 {prev.get('base_close'):+.2f}%) · "
                     f"상한가 확률 기준선 {prev.get('base_lu')}%" if prev.get("close_avg") is not None and prev.get("base_close") is not None
                     else f"상한가 확률 기준선 {prev.get('base_lu')}%")
        lines.append(f"어제 상한가 마감 {prev.get('lu_total')}종목 중 목록(20) {prev.get('lu_in20')} · 점수 상위 100 {prev.get('lu_in100')}")
        miss = [m for m in (prev.get("missed") or []) if not m.get("rank") or m["rank"] > 20][:3]
        if miss:
            lines.append("놓친 예: " + " / ".join(f"{m['name']}({m['rank'] or '100위 밖'})" for m in miss))
    else:
        lines.append("지난 결과 아직 없음 — 오늘 저녁부터 쌓입니다")
    if st.get("n"):
        lines.append(f"누적 {(p.get('stats') or {}).get('days')}일 {st['n']}건 · 상한가 닿음 {st['reached']}% · 종가 잠김 {st['closed']}% "
                     f"(기준선 {(p.get('stats') or {}).get('base_lu')}%)")
    top = (p.get("items") or [])[:5]
    if top:
        lines.append("오늘 관찰 상위: " + ", ".join(f"{i['rank']}.{i['name']}" for i in top))
    return "급등예상 아침 요약", "\n".join(lines)


def save_day(sb, w: SurgeWatch) -> None:
    sb.upload(f"surge/live/{w.day}.json", json.dumps(w.payload("마감"), ensure_ascii=False, default=str).encode(), "application/json")
