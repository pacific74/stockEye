"""Supabase 가 ntfy.sh 로 직접 못 보낸 알림을 배치(PC 22번 창 · GitHub)가 대신 보냄 (2026-10-24)

Supabase 서버 IP 는 다른 프로젝트와 공유라 ntfy.sh 하루 한도(429)에 자주 걸림 → 보내는 쪽을 PC·GitHub 로 옮김.
  가입 승인 요청 : profiles.status='pending' · signup_notified=false · 알림 시도(signup_at) 후 6분이 지났는데 안 접수됨
                   → 관리자 토픽(앱 설정 토픽 · profiles 관리자 토픽 · 이 PC 의 NTFY_TOPIC)으로 보내고 signup_notified=true
  테스트 알림    : profiles.test_notify_at 이 있으면 그 사람 토픽으로 보내고 비움 (앱 '테스트 알림 보내기' 가 요청만 걸어 둠)
PC 와 GitHub 가 같이 돌아도 보낸 뒤 바로 표시를 바꿔서 거의 중복되지 않음.
"""
from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)
GRACE_MIN = 6                                  # Supabase 자체 시도(+5분 주기 확인)가 끝나길 기다리는 시간


def admin_topic_list(sb, base: list[str] | None = None) -> list[str]:
    out = list(base or [])
    try:
        for r in sb.select("app_config", {"select": "value", "key": "eq.ntfy_topic"}) or []:
            t = (r.get("value") or "").strip().strip("/")
            if t:
                out.append(t)
    except Exception as e:  # noqa: BLE001
        log.debug("앱 설정 토픽 읽기 실패: %s", e)
    return list(dict.fromkeys(out))


def run(sb, admin: list[str] | None = None, send=None, now=None) -> int:
    """대기 중인 가입 알림 · 테스트 알림을 보냄. 보낸 건수"""
    if not sb:
        return 0
    if send is None:
        from ..trading.notify import Notifier
        nt = Notifier()
        send = lambda tp, t, b: nt.send_topic(tp, t, b, priority="high")  # noqa: E731
    now = now or pd.Timestamp.utcnow()
    cut = (now - pd.Timedelta(minutes=GRACE_MIN)).strftime("%Y-%m-%dT%H:%M:%SZ")
    n = 0
    try:
        rows = sb.select("profiles", {"select": "user_id,email", "status": "eq.pending", "signup_notified": "eq.false",
                                      "or": f"(signup_at.is.null,signup_at.lt.{cut})"}) or []
    except Exception as e:  # noqa: BLE001
        log.warning("가입 알림 대기 조회 실패: %s", e)
        rows = []
    topics = admin_topic_list(sb, admin) if rows else []
    for r in rows:
        body = f"{r.get('email') or ''} 님이 가입했습니다. 앱 → 회원 관리에서 승인하세요."
        ok = False
        for tp in topics:
            ok = bool(send(tp, "StockEye 가입 승인 요청", body)) or ok
        if ok:
            sb.update("profiles", {"user_id": f"eq.{r['user_id']}"}, {"signup_notified": True, "signup_tries": 99})
            n += 1
        print(f"   가입 알림 {'보냄' if ok else '⚠ 못 보냄'} · {r.get('email')}", flush=True)
    try:
        tests = sb.select("profiles", {"select": "user_id,ntfy_topic", "test_notify_at": "not.is.null"}) or []
    except Exception as e:  # noqa: BLE001
        log.info("테스트 알림 대기 조회 실패(칸 없음?): %s", e)
        tests = []
    for r in tests:
        tp = (r.get("ntfy_topic") or "").strip()
        ok = bool(tp) and bool(send(tp, "StockEye 테스트", "알림이 잘 옵니다 👍"))
        sb.update("profiles", {"user_id": f"eq.{r['user_id']}"}, {"test_notify_at": None})   # 성공·실패 모두 한 번만
        n += int(ok)
        print(f"   테스트 알림 {'보냄' if ok else '⚠ 못 보냄'}", flush=True)
    return n
