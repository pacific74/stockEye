"""한국투자증권(KIS) 실시간 체결가 웹소켓 — 당일매매 고정 종목을 체결이 올 때마다 바로 판단 (PC 전용)

  접속키   POST /oauth2/Approval {grant_type, appkey, secretkey} → approval_key (웹소켓 전용)
  주소     실전 ws://ops.koreainvestment.com:21000 · 모의 ws://ops.koreainvestment.com:31000
  구독     {"header": {approval_key, custtype: "P", tr_type: "1"(등록)/"2"(해제), content-type},
            "body": {"input": {"tr_id": "H0STCNT0", "tr_key": 종목코드}}}
  받는 글  "0|H0STCNT0|건수|값^값^..." (건수 × 46칸) · JSON(등록 결과·PINGPONG — PINGPONG 은 그대로 돌려보내야 끊기지 않음)
  H0STCNT0(주식체결) 쓰는 칸: 0 종목 · 1 체결시각 · 2 현재가 · 5 등락률 · 7 시가 · 8 고가 · 9 저가 · 10 매도호가1 · 11 매수호가1 ·
                              12 체결량 · 13 누적거래량 · 14 누적거래대금 · 36 매도호가잔량1 · 37 매수호가잔량1 · 38 총매도잔량 · 39 총매수잔량
  실시간 등록은 기본 최대 41건 → 고정 종목 40개까지만 (넘으면 먼저 잡힌 순)
필요 패키지: websocket-client (22_intraday.bat 이 없으면 설치)
⚠ 시세만 받음 — 주문 기능 없음
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

log = logging.getLogger(__name__)
WS = {"prod": "ws://ops.koreainvestment.com:21000/tryitout/H0STCNT0",
      "vps": "ws://ops.koreainvestment.com:31000/tryitout/H0STCNT0"}
REST = {"prod": "https://openapi.koreainvestment.com:9443", "vps": "https://openapivts.koreainvestment.com:29443"}
TR = "H0STCNT0"
NFIELD = 46
MAX_SUB = 40


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse(msg: str) -> list[dict]:
    """'0|H0STCNT0|002|a^b^...' → [{code, time, price, chg_pct, ...}, ...] (건수만큼)"""
    parts = msg.split("|")
    if len(parts) < 4 or parts[1] != TR:
        return []
    try:
        n = int(parts[2])
    except ValueError:
        n = 1
    vals = parts[3].split("^")
    out = []
    for k in range(n):
        f = vals[k * NFIELD:(k + 1) * NFIELD]
        if len(f) < 40:
            break
        out.append({"code": f[0], "time": f[1], "price": _num(f[2]), "chg_pct": _num(f[5]), "open": _num(f[7]),
                    "high": _num(f[8]), "low": _num(f[9]), "ask1": _num(f[10]), "bid1": _num(f[11]),
                    "vol": _num(f[12]), "acml_vol": _num(f[13]), "acml_value": _num(f[14]),
                    "ask_qty": _num(f[36]), "bid_qty": _num(f[37]), "total_ask": _num(f[38]), "total_bid": _num(f[39])})
    return out


class RealtimeFeed:
    """백그라운드 스레드에서 웹소켓 유지 (끊기면 다시 연결) · set_wanted(codes) 로 구독 종목을 맞춤 · on_tick(dict) 호출"""

    def __init__(self, on_tick, env: str = "prod"):
        self.on_tick, self.env = on_tick, env
        self.key, self.secret = os.getenv("KIS_APP_KEY"), os.getenv("KIS_APP_SECRET")
        self.wanted: list[str] = []
        self.subbed: set[str] = set()
        self.ws = None
        self.connected = False
        self.last_tick = 0.0
        self.ticks = 0
        self._stop = False
        self._lock = threading.Lock()
        self._approval = None
        self.thread = None

    # ------------------------------------------------ 연결
    def _approval_key(self) -> str:
        import requests
        r = requests.post(f"{REST[self.env]}/oauth2/Approval", timeout=10,
                          json={"grant_type": "client_credentials", "appkey": self.key, "secretkey": self.secret})
        r.raise_for_status()
        return r.json()["approval_key"]

    def start(self) -> bool:
        try:
            import websocket  # noqa: F401
        except ImportError:
            log.warning("websocket-client 가 없어 실시간 없이 1분 갱신만 합니다 (pip install websocket-client)")
            return False
        if not (self.key and self.secret):
            return False
        self.thread = threading.Thread(target=self._run, name="kis-ws", daemon=True)
        self.thread.start()
        return True

    def stop(self) -> None:
        self._stop = True
        try:
            if self.ws:
                self.ws.close()
        except Exception:  # noqa: BLE001
            pass

    def _run(self) -> None:
        import websocket
        backoff = 3
        while not self._stop:
            try:
                if not self._approval:
                    self._approval = self._approval_key()
                self.ws = websocket.WebSocketApp(WS[self.env], on_open=self._on_open, on_message=self._on_message,
                                                 on_close=self._on_close, on_error=self._on_error)
                self.ws.run_forever(ping_interval=60, ping_timeout=10)
            except Exception as e:  # noqa: BLE001
                log.warning("실시간 연결 실패: %s", e)
                self._approval = None
            self.connected = False
            with self._lock:
                self.subbed.clear()
            if self._stop:
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)

    def _on_open(self, ws) -> None:
        self.connected = True
        log.info("실시간 연결됨 (KIS 웹소켓)")
        self._sync()

    def _on_close(self, ws, *a) -> None:
        self.connected = False

    def _on_error(self, ws, err) -> None:
        log.debug("실시간 오류: %s", err)

    def _send(self, code: str, add: bool) -> None:
        msg = {"header": {"approval_key": self._approval, "custtype": "P", "tr_type": "1" if add else "2",
                          "content-type": "utf-8"},
               "body": {"input": {"tr_id": TR, "tr_key": code}}}
        self.ws.send(json.dumps(msg))

    def _on_message(self, ws, msg: str) -> None:
        if not msg:
            return
        if msg[0] in "01":
            for t in parse(msg):
                self.last_tick = time.time()
                self.ticks += 1
                try:
                    self.on_tick(t)
                except Exception as e:  # noqa: BLE001
                    log.warning("실시간 처리 실패 %s: %s", t.get("code"), e)
            return
        try:
            js = json.loads(msg)
        except ValueError:
            return
        if (js.get("header") or {}).get("tr_id") == "PINGPONG":
            ws.send(msg)                                             # 받은 그대로 돌려보내야 연결 유지
            return
        body = js.get("body") or {}
        if body.get("rt_cd") not in (None, "0"):
            log.warning("실시간 등록 응답: %s %s", body.get("msg_cd"), body.get("msg1"))

    # ------------------------------------------------ 구독
    def set_wanted(self, codes: list[str]) -> None:
        with self._lock:
            self.wanted = list(dict.fromkeys(codes))[:MAX_SUB]
        self._sync()

    def _sync(self) -> None:
        if not (self.connected and self.ws):
            return
        with self._lock:
            want = set(self.wanted)
            add, drop = want - self.subbed, self.subbed - want
            try:
                for c in drop:
                    self._send(c, False)
                    self.subbed.discard(c)
                for c in add:
                    self._send(c, True)
                    self.subbed.add(c)
            except Exception as e:  # noqa: BLE001
                log.warning("실시간 등록 실패: %s", e)

    def status(self) -> dict:
        return {"connected": self.connected, "subscribed": len(self.subbed), "ticks": self.ticks,
                "last_tick_sec": round(time.time() - self.last_tick) if self.last_tick else None}
