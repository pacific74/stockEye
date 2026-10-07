"""회원(가입자)에게 장중 알림 — 감시 서버(scripts.monitor)가 돌 때.

  - 장중 매수 신호: 관리자 감시에서 나온 '매수 적정구간 진입' 신호를 알림 켠 회원에게 그대로 전달 (주문은 안 냄)
  - 내 보유종목 장중 경고: 회원 각자의 보유종목(앱의 '보유')이 손절가/1차 목표가에 닿으면 본인에게
회원은 앱 → 알림 설정에서 토픽 저장 + '장중 신호' / '보유종목 경고' 켜기.
주문 승인은 관리자 계좌(KIS) 전용이라 회원에게는 해당 없음.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

log = logging.getLogger(__name__)


class MemberAlerts:
    def __init__(self, sb, notifier, owner_id: str | None = None, refresh_sec: int = 300, app_url: str | None = None):
        self.sb, self.n, self.owner = sb, notifier, owner_id
        self.refresh_sec, self.app_url = refresh_sec, app_url
        self._loaded = 0.0
        self.members: list[dict] = []
        self.positions: list[dict] = []
        self.sent: set[tuple] = set()                 # (날짜, 포지션/코드, 종류) 하루 1번만

    # ------------------------------------------------------------ 회원·보유종목 (5분마다 갱신)
    def refresh(self, force: bool = False) -> None:
        if not force and time.time() - self._loaded < self.refresh_sec:
            return
        self._loaded = time.time()
        try:
            rows = self.sb.select("profiles", {"select": "user_id,ntfy_topic,notify_signals,notify_holdings",
                                              "status": "eq.approved", "ntfy_topic": "not.is.null"})
        except Exception as e:  # noqa: BLE001  (예전 스키마)
            log.info("회원 장중 알림 꺼짐: %s", e)
            self.members, self.positions = [], []
            return
        own = (self.n.ntfy or "").strip()
        self.members = [m for m in rows if (m.get("ntfy_topic") or "").strip() and m["ntfy_topic"].strip() != own
                        and m["user_id"] != self.owner]
        ids = [m["user_id"] for m in self.members if m.get("notify_holdings", True)]
        self.positions = []
        if ids:
            self.positions = self.sb.select("positions", {
                "select": "id,user_id,code,name,stop,target1", "status": "eq.open",
                "user_id": f"in.({','.join(ids)})"})

    def codes(self) -> list[str]:
        return sorted({p["code"] for p in self.positions})

    def _topic(self, uid: str) -> str | None:
        return next((m["ntfy_topic"] for m in self.members if m["user_id"] == uid), None)

    # ------------------------------------------------------------ 보유종목 손절/목표 (장중)
    def check(self, quotes: dict, now: datetime | None = None) -> int:
        today = (now or datetime.now()).strftime("%Y-%m-%d")
        sent = 0
        for p in self.positions:
            q = quotes.get(p["code"])
            if q is None:
                continue
            for kind, hit, title, body in (
                ("stop", p.get("stop") and q.price <= float(p["stop"]), "🔻 손절가 도달",
                 f"{p['name']} 현재 {q.price:,.0f}원 ≤ 손절가 {float(p['stop'] or 0):,.0f}원"),
                ("target", p.get("target1") and q.price >= float(p["target1"]), "🎯 1차 목표가 도달",
                 f"{p['name']} 현재 {q.price:,.0f}원 ≥ 목표가 {float(p['target1'] or 0):,.0f}원"),
            ):
                key = (today, p["id"], kind)
                if hit and key not in self.sent:
                    self.sent.add(key)
                    topic = self._topic(p["user_id"])
                    if topic and self.n.send_topic(topic, title, body + "\n(내 보유종목 · 판단은 본인이)",
                                                   priority="high", url=self.app_url):
                        sent += 1
        return sent

    # ------------------------------------------------------------ 매수 신호 전달
    def broadcast_entry(self, ev: dict, now: datetime | None = None) -> int:
        today = (now or datetime.now()).strftime("%Y-%m-%d")
        key = (today, ev.get("code"), "entry")
        if key in self.sent:
            return 0
        self.sent.add(key)
        sent = 0
        for m in self.members:
            if m.get("notify_signals"):
                if self.n.send_topic(m["ntfy_topic"], "📈 장중 매수 신호",
                                     f"{ev.get('message', ev.get('name'))}\n(참고용 · 매수 권유 아님)", url=self.app_url):
                    sent += 1
        return sent
