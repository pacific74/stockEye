"""휴대폰 알림.

  텔레그램  : TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  (BotFather 로 봇 생성 → 봇에게 말 걸고 chat id 확인)
  ntfy      : NTFY_TOPIC (ntfy 앱 설치 후 같은 토픽 구독. 추측하기 어려운 이름으로!)
둘 다 없으면 콘솔에만 출력.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self):
        self.tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.tg_chat = os.getenv("TELEGRAM_CHAT_ID")
        self.ntfy = (os.getenv("NTFY_TOPIC") or "").strip().strip("/") or None
        self.ntfy_server = (os.getenv("NTFY_SERVER") or "https://ntfy.sh").rstrip("/")   # 비어 있어도 기본 서버

    @property
    def channels(self) -> list[str]:
        return [n for n, ok in (("telegram", self.tg_token and self.tg_chat), ("ntfy", self.ntfy)) if ok] or ["console"]

    def send(self, title: str, body: str, priority: str = "default", url: str | None = None,
             markdown: bool = False) -> None:
        """markdown=True: ntfy 에 'Markdown: yes' (앱 1.17.8 이상이면 굵게·제목 크기 표시), 텔레그램은 기호를 덜어낸 글"""
        print(f"\n🔔 {title}\n{body}")
        try:
            import requests
        except ImportError:
            return
        if self.tg_token and self.tg_chat:
            try:
                if markdown:
                    from ..cloud.digest import plain
                    body_tg = plain(body)
                else:
                    body_tg = body
                text = f"*{title}*\n{body_tg}" + (f"\n{url}" if url else "")
                requests.post(f"https://api.telegram.org/bot{self.tg_token}/sendMessage", timeout=10,
                              json={"chat_id": self.tg_chat, "text": text, "parse_mode": "Markdown"})
            except Exception as e:  # noqa: BLE001
                log.warning("텔레그램 전송 실패: %s", e)
        if self.ntfy:
            try:
                headers = {"Title": title.encode("utf-8"), "Priority": {"high": "4", "urgent": "5"}.get(priority, "3")}
                if url:
                    headers["Click"] = url
                if markdown:
                    headers["Markdown"] = "yes"
                requests.post(f"{self.ntfy_server}/{self.ntfy}", data=body.encode("utf-8"), headers=headers, timeout=10)
            except Exception as e:  # noqa: BLE001
                log.warning("ntfy 전송 실패: %s", e)

    def send_topic(self, topic: str, title: str, body: str, priority: str = "default", url: str | None = None,
                   markdown: bool = False) -> bool:
        """특정 ntfy 토픽으로 보내기 (회원 각자의 알림)."""
        topic = (topic or "").strip().strip("/")
        if not topic:
            return False
        try:
            import requests
            headers = {"Title": title.encode("utf-8"), "Priority": {"high": "4", "urgent": "5"}.get(priority, "3")}
            if url:
                headers["Click"] = url
            if markdown:
                headers["Markdown"] = "yes"
            r = requests.post(f"{self.ntfy_server}/{topic}", data=body.encode("utf-8"), headers=headers, timeout=10)
            return r.status_code < 300
        except Exception as e:  # noqa: BLE001
            log.warning("ntfy(%s) 전송 실패: %s", topic[:6], e)
            return False

