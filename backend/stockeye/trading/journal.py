"""자동 매매일지 (SQLite: data/journal.db).

매수 체결 시 '그 순간의 판단 근거'를 통째로 저장하고, 매도 체결 시 결과를 채운다.
  매수: 종목 · 매수가 · 매수시각 · 당시 점수 · 전략 · 손절 · 목표1/2 · 매수 근거 · 주의사항 · 시장 분위기 · 테마
  매도: 매도가 · 매도시각 · 매도 사유 · 수익률(비용 반영) · 보유기간 · 결과(성공/실패/본전)
  보유 중: 최대 손실폭(MAE) · 최대 수익폭(MFE) 계속 갱신 → "손절을 늦게 했나", "너무 일찍 팔았나" 분석용

모드: paper(모의) / real(실전) / manual(직접 입력) — 분석할 때 섞지 않고 나눠 볼 수 있다.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

SCHEMA = """
create table if not exists positions (
  id text primary key,
  mode text not null,                 -- paper | real | manual
  code text not null, name text,
  strategy text, list_key text,       -- 전략 키(A~E) / 어느 목록에서 나왔는지(overall, A..)
  score real, strategy_score real,
  entry_time text not null, entry_price real not null, qty real not null, entry_cost real,
  stop real, target1 real, target2 real,
  reasons text, warnings text,        -- JSON 배열
  market_mood text, theme text, verdict text,
  plan text,                          -- JSON (매수구간, 손익비 등 전체)
  signal_time text,                   -- 신호 발생 시각 (승인 지연 측정용)
  exit_time text, exit_price real, exit_proceeds real, exit_reason text,
  ret_pct real, pnl real, hold_days integer, result text,
  min_price real, max_price real,     -- 보유 중 최저/최고가 (MAE/MFE)
  late_stop integer default 0,        -- 손절가보다 1% 넘게 아래서 판 경우
  memo text,
  status text not null default 'open' -- open | closed
);
create index if not exists positions_status on positions(status, mode);

create table if not exists orders (
  id text primary key,
  created_at text not null,
  mode text not null,                 -- paper | real
  side text not null,                 -- buy | sell
  code text not null, name text,
  qty real not null, price real,      -- 지정가 (null = 시장가)
  reason text,                        -- 진입 신호 / 손절 / 목표가 / 기간만료 / 수동
  position_id text,                   -- 매도 주문일 때 대상 포지션
  snapshot text,                      -- JSON: 매수 근거 스냅샷
  status text not null,               -- pending(승인 대기) | approved | sent | filled | rejected | expired | failed
  expires_at text,
  broker_order_id text, filled_price real, filled_qty real, filled_at text,
  message text
);
create index if not exists orders_status on orders(status);

create table if not exists alerts (
  id integer primary key autoincrement,
  time text not null, kind text not null, code text, name text, message text, payload text
);
create index if not exists alerts_key on alerts(kind, code, time);

create table if not exists cash (
  mode text primary key, balance real not null
);
"""


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def classify_result(ret_pct: float, flat_band: float = 0.5) -> str:
    if ret_pct is None:
        return ""
    return "성공" if ret_pct > flat_band else "실패" if ret_pct < -flat_band else "본전"


def business_days(a: str, b: str) -> int:
    try:
        return max(0, len(pd.bdate_range(pd.Timestamp(a).normalize(), pd.Timestamp(b).normalize())) - 1)
    except Exception:  # noqa: BLE001
        return 0


def position_row(mode: str, code: str, price: float, qty: float, *, name=None, cand: dict | None = None,
                 entry_time: str | None = None, entry_cost: float | None = None, market_mood=None,
                 list_key=None, signal_time=None, stop=None, target1=None, target2=None, memo=None) -> dict:
    """매수 체결 시 '그 순간의 판단 근거' 스냅샷 (SQLite / Supabase 공통)."""
    cand = cand or {}
    plan = cand.get("plan", {})
    return {
        "id": uuid.uuid4().hex[:12], "mode": mode, "code": code, "name": name or cand.get("name") or code,
        "strategy": cand.get("strategy") or (list_key if list_key not in (None, "overall") else None),
        "list_key": list_key, "score": cand.get("score"), "strategy_score": cand.get("strategy_score"),
        "entry_time": entry_time or now_str(), "entry_price": float(price), "qty": float(qty),
        "entry_cost": entry_cost if entry_cost is not None else float(price) * float(qty),
        "stop": stop if stop is not None else plan.get("stop"),
        "target1": target1 if target1 is not None else plan.get("target1"),
        "target2": target2 if target2 is not None else plan.get("target2"),
        "reasons": cand.get("reasons", []) + cand.get("strategy_reasons", []),
        "warnings": cand.get("warnings", []),
        "market_mood": market_mood, "theme": cand.get("theme"), "verdict": plan.get("verdict"),
        "plan": plan, "signal_time": signal_time,
        "min_price": float(price), "max_price": float(price), "memo": memo, "status": "open",
    }


def close_update(p: dict, price: float, *, reason: str, exit_time: str | None = None,
                 proceeds: float | None = None) -> dict:
    """매도 체결 시 채우는 값: 수익률(비용 반영) · 보유기간 · 결과 · 손절 지연."""
    exit_time = exit_time or now_str()
    proceeds = proceeds if proceeds is not None else float(price) * p["qty"]
    cost = p["entry_cost"] or p["entry_price"] * p["qty"]
    ret = (proceeds / cost - 1) * 100 if cost else 0.0
    return {"exit_time": exit_time, "exit_price": float(price), "exit_proceeds": proceeds, "exit_reason": reason,
            "ret_pct": round(ret, 2), "pnl": round(proceeds - cost),
            "hold_days": business_days(p["entry_time"], exit_time),
            "result": classify_result(ret), "late_stop": bool(p["stop"] and price < p["stop"] * 0.99),
            "status": "closed",
            "min_price": min(p["min_price"] or price, price), "max_price": max(p["max_price"] or price, price)}


def make_journal(cfg: dict, path=None):
    """SUPABASE_* 환경변수가 있으면 클라우드(Supabase) 매매일지, 없으면 PC 의 SQLite."""
    from ..cloud.client import enabled
    import os
    if path is None and enabled() and os.getenv("SUPABASE_USER_ID") and cfg.get("cloud", {}).get("journal", True):
        from ..cloud.journal import CloudJournal
        return CloudJournal()
    from ..config import data_dir
    return Journal(path or data_dir(cfg) / "journal.db")


class Journal:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------ 포지션 (매매일지)
    def open_position(self, mode: str, code: str, price: float, qty: float, **kw) -> str:
        row = position_row(mode, code, price, qty, **kw)
        for k in ("reasons", "warnings", "plan"):
            row[k] = json.dumps(row[k], ensure_ascii=False)
        cols = ",".join(row)
        with self._conn() as c:
            c.execute(f"insert into positions ({cols}) values ({','.join('?' * len(row))})", list(row.values()))
        return row["id"]

    def close_position(self, pid: str, price: float, *, reason: str, exit_time: str | None = None,
                       proceeds: float | None = None) -> dict:
        p = self.get_position(pid)
        if p is None or p["status"] != "open":
            raise ValueError("열린 포지션이 아닙니다")
        upd = close_update(p, price, reason=reason, exit_time=exit_time, proceeds=proceeds)
        upd["late_stop"] = int(upd["late_stop"])
        with self._conn() as c:
            c.execute(f"update positions set {','.join(k + '=?' for k in upd)} where id=?", [*upd.values(), pid])
        return self.get_position(pid)

    def track_price(self, pid: str, low: float, high: float) -> None:
        with self._conn() as c:
            c.execute("update positions set min_price=min(coalesce(min_price,?),?), max_price=max(coalesce(max_price,?),?) "
                      "where id=? and status='open'", (low, low, high, high, pid))

    def update_position(self, pid: str, patch: dict) -> dict | None:
        allowed = {"stop", "target1", "target2", "memo", "qty", "name"}
        patch = {k: v for k, v in patch.items() if k in allowed}
        if patch:
            with self._conn() as c:
                c.execute(f"update positions set {','.join(k + '=?' for k in patch)} where id=?", [*patch.values(), pid])
        return self.get_position(pid)

    def delete_position(self, pid: str) -> bool:
        with self._conn() as c:
            return c.execute("delete from positions where id=?", (pid,)).rowcount > 0

    def get_position(self, pid: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("select * from positions where id=?", (pid,)).fetchone()
        return _decode(dict(r)) if r else None

    def positions(self, status: str | None = None, mode: str | None = None, code: str | None = None) -> list[dict]:
        q, args = "select * from positions where 1=1", []
        for k, v in (("status", status), ("mode", mode), ("code", code)):
            if v:
                q += f" and {k}=?"
                args.append(v)
        with self._conn() as c:
            rows = c.execute(q + " order by entry_time desc", args).fetchall()
        return [_decode(dict(r)) for r in rows]

    def frame(self, mode: str | None = None) -> pd.DataFrame:
        rows = self.positions(mode=mode)
        return pd.DataFrame(rows)

    # ------------------------------------------------------------ 주문 (승인 흐름)
    def add_order(self, mode, side, code, qty, *, price=None, name=None, reason=None, position_id=None,
                  snapshot=None, status="pending", expires_min: int | None = None) -> str:
        oid = uuid.uuid4().hex[:12]
        exp = (pd.Timestamp.now() + pd.Timedelta(minutes=int(expires_min))).strftime("%Y-%m-%d %H:%M:%S") if expires_min else None
        with self._conn() as c:
            c.execute("insert into orders (id, created_at, mode, side, code, name, qty, price, reason, position_id, "
                      "snapshot, status, expires_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (oid, now_str(), mode, side, code, name, qty, price, reason, position_id,
                       json.dumps(snapshot or {}, ensure_ascii=False, default=str), status, exp))
        return oid

    def update_order(self, oid: str, **kw) -> None:
        with self._conn() as c:
            c.execute(f"update orders set {','.join(k + '=?' for k in kw)} where id=?", [*kw.values(), oid])

    def get_order(self, oid: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("select * from orders where id=?", (oid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["snapshot"] = json.loads(d["snapshot"] or "{}")
        return d

    def orders(self, status: str | None = None, limit: int = 100) -> list[dict]:
        q, args = "select * from orders", []
        if status:
            q += " where status=?"
            args.append(status)
        with self._conn() as c:
            rows = c.execute(q + " order by created_at desc limit ?", [*args, limit]).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["snapshot"] = json.loads(d["snapshot"] or "{}")
            out.append(d)
        return out

    def expire_orders(self) -> int:
        with self._conn() as c:
            return c.execute("update orders set status='expired' where status='pending' and expires_at is not null "
                             "and expires_at < ?", (now_str(),)).rowcount

    def orders_today(self, mode: str, side: str = "buy") -> int:
        with self._conn() as c:
            return c.execute("select count(*) from orders where mode=? and side=? and created_at >= ? "
                             "and status not in ('rejected','expired','failed')",
                             (mode, side, datetime.now().strftime("%Y-%m-%d"))).fetchone()[0]

    # ------------------------------------------------------------ 알림 로그 (중복 방지)
    def add_alert(self, kind, code, name, message, payload=None) -> None:
        with self._conn() as c:
            c.execute("insert into alerts (time, kind, code, name, message, payload) values (?,?,?,?,?,?)",
                      (now_str(), kind, code, name, message, json.dumps(payload or {}, ensure_ascii=False, default=str)))

    def alerted_today(self, kind, code) -> bool:
        with self._conn() as c:
            return c.execute("select 1 from alerts where kind=? and code=? and time >= ? limit 1",
                             (kind, code, datetime.now().strftime("%Y-%m-%d"))).fetchone() is not None

    def alerts(self, limit=100) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("select * from alerts order by id desc limit ?", (limit,)).fetchall()]

    # ------------------------------------------------------------ 모의투자 현금
    def cash(self, mode: str, initial: float) -> float:
        with self._conn() as c:
            r = c.execute("select balance from cash where mode=?", (mode,)).fetchone()
            if r is None:
                c.execute("insert into cash (mode, balance) values (?,?)", (mode, initial))
                return initial
            return r[0]

    def add_cash(self, mode: str, delta: float, initial: float) -> float:
        bal = self.cash(mode, initial) + delta
        with self._conn() as c:
            c.execute("update cash set balance=? where mode=?", (bal, mode))
        return bal


def _decode(d: dict) -> dict:
    for k in ("reasons", "warnings", "plan"):
        if isinstance(d.get(k), str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    ep = d.get("entry_price")
    if ep:
        d["mae_pct"] = round((d["min_price"] / ep - 1) * 100, 2) if d.get("min_price") else None   # 최대 손실폭
        d["mfe_pct"] = round((d["max_price"] / ep - 1) * 100, 2) if d.get("max_price") else None   # 최대 수익폭
    return d
