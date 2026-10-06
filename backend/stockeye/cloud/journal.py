"""Supabase 매매일지 — trading.journal.Journal(SQLite) 과 같은 메서드.

앱(휴대폰)과 배치/감시 서버가 같은 표(positions, orders, alerts, paper_cash)를 본다.
  - 앱: 직접 산 종목 기록, 매도 기록, 손절/목표 수정, 주문 승인/거절
  - 서버: 신호 → 주문 생성, 체결 → 매매일지 기록, 최고/최저가(MAE/MFE) 갱신
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pandas as pd

from ..trading.journal import position_row, close_update, now_str, _decode
from .client import Supabase

_TS = ("entry_time", "exit_time", "signal_time", "created_at", "expires_at", "filled_at", "time")


def _norm(d: dict) -> dict:
    for k in _TS:
        v = d.get(k)
        if isinstance(v, str):
            d[k] = v.replace("T", " ")[:19]
    for k in ("entry_price", "qty", "entry_cost", "stop", "target1", "target2", "exit_price", "exit_proceeds",
              "ret_pct", "pnl", "min_price", "max_price", "score", "strategy_score", "price", "filled_price",
              "filled_qty"):
        if d.get(k) is not None:
            d[k] = float(d[k])
    return d


class CloudJournal:
    def __init__(self, sb: Supabase | None = None, user_id: str | None = None):
        self.sb = sb or Supabase()
        self.uid = user_id or self.sb.user_id
        if not self.uid:
            raise RuntimeError("SUPABASE_USER_ID 환경변수가 없습니다 (Supabase → Authentication → Users 의 User UID)")
        self.path = f"supabase:{self.sb.url}"

    def _f(self, **kw) -> dict:
        f = {"user_id": f"eq.{self.uid}"}
        for k, v in kw.items():
            if v is not None:
                f[k] = f"eq.{v}"
        return f

    # ------------------------------------------------------------ 포지션
    def open_position(self, mode: str, code: str, price: float, qty: float, **kw) -> str:
        row = position_row(mode, code, price, qty, **kw)
        row["user_id"] = self.uid
        self.sb.insert("positions", row, returning=False)
        return row["id"]

    def close_position(self, pid: str, price: float, *, reason: str, exit_time: str | None = None,
                       proceeds: float | None = None) -> dict:
        p = self.get_position(pid)
        if p is None or p["status"] != "open":
            raise ValueError("열린 포지션이 아닙니다")
        upd = close_update(p, price, reason=reason, exit_time=exit_time, proceeds=proceeds)
        self.sb.update("positions", {**self._f(), "id": f"eq.{pid}"}, upd)
        return self.get_position(pid)

    def track_price(self, pid: str, low: float, high: float) -> None:
        p = self.get_position(pid)
        if not p or p["status"] != "open":
            return
        mn = min(p["min_price"] if p.get("min_price") is not None else low, low)
        mx = max(p["max_price"] if p.get("max_price") is not None else high, high)
        if mn != p.get("min_price") or mx != p.get("max_price"):
            self.sb.update("positions", {**self._f(), "id": f"eq.{pid}"}, {"min_price": mn, "max_price": mx})

    def update_position(self, pid: str, patch: dict) -> dict | None:
        allowed = {"stop", "target1", "target2", "memo", "qty", "name"}
        patch = {k: v for k, v in patch.items() if k in allowed}
        if patch:
            self.sb.update("positions", {**self._f(), "id": f"eq.{pid}"}, patch)
        return self.get_position(pid)

    def delete_position(self, pid: str) -> bool:
        return bool(self.sb.delete("positions", {**self._f(), "id": f"eq.{pid}"}, returning=True))

    def get_position(self, pid: str) -> dict | None:
        rows = self.sb.select("positions", {**self._f(), "id": f"eq.{pid}"})
        return _decode(_norm(rows[0])) if rows else None

    def positions(self, status: str | None = None, mode: str | None = None, code: str | None = None) -> list[dict]:
        rows = self.sb.select("positions", {**self._f(status=status, mode=mode, code=code), "order": "entry_time.desc"})
        return [_decode(_norm(r)) for r in rows]

    def frame(self, mode: str | None = None) -> pd.DataFrame:
        return pd.DataFrame(self.positions(mode=mode))

    # ------------------------------------------------------------ 주문
    def add_order(self, mode, side, code, qty, *, price=None, name=None, reason=None, position_id=None,
                  snapshot=None, status="pending", expires_min: int | None = None) -> str:
        oid = uuid.uuid4().hex[:12]
        exp = (pd.Timestamp.now() + pd.Timedelta(minutes=int(expires_min))).strftime("%Y-%m-%d %H:%M:%S") if expires_min else None
        self.sb.insert("orders", {"id": oid, "user_id": self.uid, "created_at": now_str(), "mode": mode, "side": side,
                                  "code": code, "name": name, "qty": qty, "price": price, "reason": reason,
                                  "position_id": position_id, "snapshot": snapshot or {}, "status": status,
                                  "expires_at": exp}, returning=False)
        return oid

    def update_order(self, oid: str, **kw) -> None:
        self.sb.update("orders", {**self._f(), "id": f"eq.{oid}"}, kw)

    def get_order(self, oid: str) -> dict | None:
        rows = self.sb.select("orders", {**self._f(), "id": f"eq.{oid}"})
        if not rows:
            return None
        d = _norm(rows[0])
        d["snapshot"] = d.get("snapshot") or {}
        return d

    def orders(self, status: str | None = None, limit: int = 100) -> list[dict]:
        rows = self.sb.select("orders", {**self._f(status=status), "order": "created_at.desc", "limit": str(limit)})
        out = []
        for r in rows:
            d = _norm(r)
            d["snapshot"] = d.get("snapshot") or {}
            out.append(d)
        return out

    def expire_orders(self) -> int:
        rows = self.sb.update("orders", {**self._f(status="pending"), "expires_at": f"lt.{now_str()}"},
                              {"status": "expired"}, returning=True)
        return len(rows)

    def orders_today(self, mode: str, side: str = "buy") -> int:
        return self.sb.count("orders", {**self._f(mode=mode, side=side),
                                        "created_at": f"gte.{datetime.now():%Y-%m-%d}",
                                        "status": "not.in.(rejected,expired,failed)"})

    # ------------------------------------------------------------ 알림 로그
    def add_alert(self, kind, code, name, message, payload=None) -> None:
        self.sb.insert("alerts", {"user_id": self.uid, "time": now_str(), "kind": kind, "code": code, "name": name,
                                  "message": message, "payload": payload or {}}, returning=False)

    def alerted_today(self, kind, code) -> bool:
        rows = self.sb.select("alerts", {**self._f(kind=kind, code=code), "time": f"gte.{datetime.now():%Y-%m-%d}",
                                         "select": "id", "limit": "1"})
        return bool(rows)

    def alerts(self, limit=100) -> list[dict]:
        return [_norm(r) for r in self.sb.select("alerts", {**self._f(), "order": "id.desc", "limit": str(limit)})]

    # ------------------------------------------------------------ 모의투자 현금
    def cash(self, mode: str, initial: float) -> float:
        rows = self.sb.select("paper_cash", self._f(mode=mode))
        if rows:
            return float(rows[0]["balance"])
        self.sb.upsert("paper_cash", [{"user_id": self.uid, "mode": mode, "balance": initial}], "user_id,mode")
        return float(initial)

    def add_cash(self, mode: str, delta: float, initial: float) -> float:
        bal = self.cash(mode, initial) + delta
        self.sb.upsert("paper_cash", [{"user_id": self.uid, "mode": mode, "balance": bal}], "user_id,mode")
        return bal
