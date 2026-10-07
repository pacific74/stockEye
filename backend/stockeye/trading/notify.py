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

    def send(self, title: str, body: str, priority: str = "default", url: str | None = None) -> None:
        print(f"\n🔔 {title}\n{body}")
        try:
            import requests
        except ImportError:
            return
        if self.tg_token and self.tg_chat:
            try:
                text = f"*{title}*\n{body}" + (f"\n{url}" if url else "")
                requests.post(f"https://api.telegram.org/bot{self.tg_token}/sendMessage", timeout=10,
                              json={"chat_id": self.tg_chat, "text": text, "parse_mode": "Markdown"})
            except Exception as e:  # noqa: BLE001
                log.warning("텔레그램 전송 실패: %s", e)
        if self.ntfy:
            try:
                headers = {"Title": title.encode("utf-8"), "Priority": {"high": "4", "urgent": "5"}.get(priority, "3")}
                if url:
                    headers["Click"] = url
                requests.post(f"{self.ntfy_server}/{self.ntfy}", data=body.encode("utf-8"), headers=headers, timeout=10)
            except Exception as e:  # noqa: BLE001
                log.warning("ntfy 전송 실패: %s", e)
