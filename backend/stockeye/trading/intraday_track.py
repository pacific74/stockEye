"""당일매매 추적 — 당일단타 '진입 조건 충족' · 상한가포착 '매수 검토' 가 처음 뜬 종목을 그 순간 계획으로 고정하고
1분마다 상태만 갱신 → 결과가 나오면 관리자 매매일지(positions, mode='signal')에 기록 (당일단타·상한가포착 같은 방식)

고정하는 것 (첫 신호 때): 시각 · 점수 · 매수가(진입가) · 매수구간 · 손절 · 1·2·3차 목표 · 그때 카드 내용(기존 상태설명)
현재 상태 (생길 때마다 시각과 함께 쌓음)
  매수구간      지금 가격이 매수구간 안
  신규진입보류  지금 점수가 기준 아래 (당일단타 80 · 상한가포착 75) — 새로 들어가지 말 것 (이미 산 몫은 계속 추적)
  1·2·3차 목표달성
  매도신호포착  산 뒤 매물이 갑자기 쏟아짐: 1분 거래량이 앞 10분 평균의 3배 이상 + 1% 넘는 음봉
  손절          손절가 닿음 (1차 목표 뒤에는 본전)
매매 결과
  이익실현      1차 목표 이상 달성 (1차 50% · 2차 30% · 3차 20% 매도, 1차 뒤 남은 몫은 본전 이탈 시 · 마감 때 종가)
  매수가매도    1차 목표 전에 매도신호포착으로 매수가 부근에서 판 경우 (또는 마감 때 매수가 이상)
  손절          손절가에 닿았거나 마감까지 매수가 아래
  마감 = 당일단타 15:20 · 상한가포착은 다음 날 09:30
  상한가포착 목표: 다음 날 +3% · +6% · +10% · 손절 = 매수가 −4% (2026-10-13: 예전 '전일 종가 +20%'는 상한가에 산 경우
  −7.7% 라 너무 멀어서 바꿈. 엔진 카드의 '조건 무효(+20%)'는 그대로 참고 표시)
매수는 신호가 뜬 그 시각 진입가에 됐다고 봄 (모의 · 주문 없음). 비용 0.25% 뺀 손익. 매매일지 금액은 1건 100만원 기준
상태는 Storage track/<kind>/<날짜>.json 에 저장 (PC 를 다시 켜도 · [종목찾기] 버튼으로 돌려도 이어서)

종가배팅 (2026-10-13): '매수 후보' 가 처음 뜨면 고정(매수대기) → 그날 15:30 까지 가격이 매수 범위(종가 ±0.5%)에 들어오면
그 가격에 매수 (매매일지 기록) · 안 들어오면 미체결(기록 안 함). 산 날은 목표·손절을 보지 않고 다음 날부터:
시초가가 손절 아래면 시초가 전량 · 1차 목표에 절반 · 2차에 나머지 · 1차 뒤 매수가 이탈 시 나머지 · 10:30 남은 몫 전량
"""
from __future__ import annotations

import json
import logging
import os

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)
COST = 0.25                       # %
AMOUNT = 1_000_000                # 매매일지 1건 금액 (원)
SELL = (0.5, 0.3, 0.2)
CFG = {
    "daytrade": {"name": "당일단타", "trigger": "진입 조건 충족", "hold": 80.0, "end": "15:20", "overnight": False},
    "limitcatch": {"name": "상한가포착", "trigger": "매수 검토", "hold": 75.0, "end": "09:30", "overnight": True},
    # 종가배팅: 고정 뒤 매수 범위에 들어와야 매수 · 1차 50% → 2차 나머지 · 매도신호(거래량) 안 봄 · 전날 내역도 화면에
    "closingbet": {"name": "종가배팅", "trigger": "매수 후보", "hold": None, "end": "10:30", "overnight": True,
                   "wait_buy": True, "buy_until": "15:30", "sell": (0.5, 1.0), "sell_signal": False, "show_prev": True},
}
RESULTS = ("이익실현", "매수가매도", "손절", "미체결")
LC_STOP = 0.04                    # 상한가포착 손절 = 매수가 −4%


def _f(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _tick_round(p: float) -> float:
    from ..engine.daytrade import rt
    return rt(p)


def plan_of(kind: str, r: dict) -> dict:
    """신호 카드 → 고정 계획 (매수가 · 매수구간 · 손절 · 1·2·3차 목표)"""
    e = _f(r.get("entry")) or _f(r.get("price"))
    stop = _f(r.get("stop"))
    if kind == "limitcatch":
        from ..engine.daytrade import rt
        stop = rt(e * (1 - LC_STOP), "down")
        t1, t2, t3 = (_tick_round(e * k) for k in (1.03, 1.06, 1.10))
    elif kind == "closingbet":                                         # 엔진 계획 그대로 (1·2차까지)
        t1, t2, t3 = _f(r.get("t1")), _f(r.get("t2")), None
    else:
        t1, t2 = _f(r.get("t1")), _f(r.get("t2"))
        t3 = _tick_round(t2 + (t2 - t1)) if t1 and t2 else None
    lo, hi = _f(r.get("buy_lo")) or e * 0.995, _f(r.get("buy_hi")) or e * 1.005
    return {"entry": e, "buy_lo": _tick_round(lo), "buy_hi": _tick_round(hi), "stop": stop, "t1": t1, "t2": t2, "t3": t3}


class Track:
    """한 종목 추적 상태 (dict 로 저장)"""

    @staticmethod
    def new(kind: str, day: str, r: dict, now: pd.Timestamp) -> dict:
        p = plan_of(kind, r)
        hm = now.strftime("%H:%M")
        card = {k: r.get(k) for k in ("status", "score", "type", "group", "price", "chg_pct", "value", "vwap", "entry",
                                       "stop", "t1", "t2", "t1_pct", "risk_pct", "loss_pct", "limit", "reasons",
                                       "excluded", "risks", "parts", "labels", "maxes", "lock", "book", "news_level", "news",
                                       "fill_warn", "level", "news", "gap", "close_pos", "exit_rules", "exit_time",
                                       "atr") if r.get(k) is not None}
        first = "매수대기" if CFG[kind].get("wait_buy") else "매수구간"
        return {"kind": kind, "date": day, "code": r["code"], "name": r.get("name"), "time": hm,
                "score": _f(r.get("score")), **p, "card": card, "events": [{"state": first, "time": hm}],
                "state": first, "bought": not CFG[kind].get("wait_buy"), "buy_time": None if CFG[kind].get("wait_buy") else hm, "hits": {}, "sold": [], "rest": 1.0, "be": False, "result": None, "pnl": None,
                "exit_price": None, "exit_time": None, "last": _f(r.get("price")) or p["entry"], "score_now": _f(r.get("score")),
                "high": p["entry"], "low": p["entry"], "seen": now.strftime("%Y-%m-%d %H:%M"), "pos_id": None, "done": False}


def _event(t: dict, state: str, hm: str) -> None:
    t["events"].append({"state": state, "time": hm})
    t["state"] = state


def _sell_signal(bars: pd.DataFrame, i: int) -> bool:
    if i < 10:
        return False
    v = bars["volume"].to_numpy(float)
    avg = v[i - 10:i].mean()
    o, c = float(bars["open"].iloc[i]), float(bars["close"].iloc[i])
    return avg > 0 and v[i] >= 3 * avg and c < o * 0.99


def step(t: dict, bars: pd.DataFrame | None, price: float | None, score_now: float | None, now: pd.Timestamp,
         cfg: dict, ticks: bool = False) -> bool:
    """새 1분봉·지금 가격으로 상태 갱신. 결과가 나오면 True
    ticks=True: 실시간 체결로 목표·손절을 이미 보고 있음 → 1분봉으로는 매도신호(거래량)·고가/저가만 봄 (같은 분 순서 모름 → 이중 판단 방지)"""
    if t["done"]:
        return False
    if cfg.get("wait_buy") and not t.get("bought", True):
        return _wait_buy(t, bars, price, now, cfg)
    e, stop = t["entry"], t["stop"]
    tg = [t.get("t1"), t.get("t2"), t.get("t3")]
    sells = cfg.get("sell", SELL[:2])
    seen = pd.Timestamp(t["seen"])
    if bars is not None and len(bars):
        b = bars[bars["time"] > seen].sort_values("time").reset_index(drop=True)
        full = bars.sort_values("time").reset_index(drop=True)
        off = len(full) - len(b)
        for i, r in b.iterrows():
            ts = pd.Timestamp(r["time"])
            hm = ts.strftime("%H:%M")
            if cfg.get("wait_buy") and ts.strftime("%Y-%m-%d") <= t["date"]:   # 종가배팅: 산 날은 목표·손절 안 봄
                t["last"] = float(r["close"])
                continue
            op, lo, hi, cl = float(r["open"]), float(r["low"]), float(r["high"]), float(r["close"])
            t["high"], t["low"] = max(t["high"], hi), min(t["low"], lo)
            st = e if t["be"] else stop
            if ticks:
                pass
            elif st and lo <= st:                                      # 손절 (1차 뒤엔 본전) · 시초가가 이미 아래면 시초가
                _sell(t, min(op, st), t["rest"])
                _event(t, "손절" if not t["be"] else "본전 매도", hm)
                return _finish(t, hm, now)
            for k, tp in enumerate(tg if not ticks else []):
                key = f"t{k + 1}"
                if tp and key not in t["hits"] and hi >= tp:
                    t["hits"][key] = hm
                    _sell(t, max(op, tp), sells[k] if k < len(sells) else t["rest"])   # 갭 상승이면 시초가
                    _event(t, f"{k + 1}차목표달성", hm)
                    t["be"] = True
            if t["rest"] <= 1e-9:
                return _finish(t, hm, now)
            if cfg.get("sell_signal", True) and _sell_signal(full, off + i) \
                    and "매도신호포착" not in [x["state"] for x in t["events"]]:
                _event(t, "매도신호포착", hm)
                _sell(t, cl, t["rest"])                                 # 1차 전이면 매수가 부근 매도, 뒤면 나머지 정리
                return _finish(t, hm, now)
            t["last"] = cl
        t["seen"] = pd.Timestamp(b["time"].iloc[-1]).strftime("%Y-%m-%d %H:%M") if len(b) else t["seen"]
    if price:
        t["last"] = price
        inzone = t["buy_lo"] <= price <= t["buy_hi"]
        if inzone and not t.get("inzone", True) and not t["hits"] and not cfg.get("wait_buy"):  # 벗어났다 다시 들어올 때만
            _event(t, "매수구간", now.strftime("%H:%M"))
        t["inzone"] = inzone
    if score_now is not None:
        t["score_now"] = score_now
        if cfg.get("hold") is not None and score_now < cfg["hold"] \
                and "신규진입보류" not in [x["state"] for x in t["events"]]:
            _event(t, "신규진입보류", now.strftime("%H:%M"))
    today, hm_now = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    if cfg["overnight"]:                                               # 상한가포착: 다음 거래일 09:30
        over = today > t["date"] and hm_now >= cfg["end"]
    else:                                                              # 당일단타: 그날 15:20 (날이 넘어갔으면 바로)
        over = today > t["date"] or hm_now >= cfg["end"]
    if over:
        _sell(t, t["last"], t["rest"])
        _event(t, "마감 청산", now.strftime("%H:%M"))
        return _finish(t, now.strftime("%H:%M"), now)
    return False


def _buy(t: dict, px: float, ts: pd.Timestamp) -> None:
    """종가배팅: 매수 범위 안 가격에 매수 (그 가격이 매수가)"""
    t["entry"], t["bought"], t["buy_time"] = round(px, 2), True, ts.strftime("%H:%M")
    t["high"] = t["low"] = t["last"] = px
    t["seen"] = ts.strftime("%Y-%m-%d %H:%M")
    _event(t, "매수", ts.strftime("%H:%M"))


def _no_fill(t: dict, hm: str, now: pd.Timestamp) -> bool:
    _event(t, "미체결", hm)
    t.update({"done": True, "result": "미체결", "pnl": None, "exit_price": None,
              "exit_time": now.strftime("%Y-%m-%d ") + hm})
    return True


def _wait_buy(t: dict, bars: pd.DataFrame | None, price: float | None, now: pd.Timestamp, cfg: dict) -> bool:
    """매수대기: 고정 뒤 그날 buy_until 까지 매수 범위에 닿으면 매수. 넘기면 미체결 (True)"""
    lo_b, hi_b = t["buy_lo"], t["buy_hi"]
    until = pd.Timestamp(f"{t['date']} {cfg.get('buy_until', '15:30')}")
    if bars is not None and len(bars):
        b = bars[(bars["time"] > pd.Timestamp(t["seen"])) & (bars["time"] <= until)].sort_values("time")
        for _, r in b.iterrows():
            if float(r["low"]) <= hi_b and float(r["high"]) >= lo_b:
                _buy(t, min(max(float(r["close"]), lo_b), hi_b), pd.Timestamp(r["time"]))
                return False
            t["last"] = float(r["close"])
        if len(b):
            t["seen"] = pd.Timestamp(b["time"].iloc[-1]).strftime("%Y-%m-%d %H:%M")
    if price:
        t["last"] = price
        if now <= until and lo_b <= price <= hi_b:
            _buy(t, price, now)
            return False
    if now > until:
        return _no_fill(t, until.strftime("%H:%M") if now.strftime("%Y-%m-%d") == t["date"] else "15:30", now)
    return False


def tick(t: dict, price: float, now: pd.Timestamp, cfg: dict | None = None) -> bool:
    """실시간 체결 하나: 손절(1차 뒤 본전)·1·2·3차 목표를 바로 판단. 상태가 바뀌면 True (결과가 나오면 t['done'])"""
    if t["done"] or not price:
        return False
    cfg = cfg or {}
    hm = now.strftime("%H:%M")
    if cfg.get("wait_buy"):
        if not t.get("bought", True):
            return _wait_buy(t, None, price, now, cfg) or t.get("bought", False)
        if now.strftime("%Y-%m-%d") <= t["date"]:                       # 산 날은 가격만
            t["last"] = price
            return False
    sells = cfg.get("sell", SELL[:2])
    n0 = len(t["events"])
    t["last"] = price
    t["high"], t["low"] = max(t["high"], price), min(t["low"], price)
    st = t["entry"] if t["be"] else t["stop"]
    if st and price <= st:
        _sell(t, price, t["rest"])                                       # 실제 체결가 (손절가보다 낮을 수 있음)
        _event(t, "손절" if not t["be"] else "본전 매도", hm)
        _finish(t, hm, now)
        return True
    for k, tp in enumerate([t.get("t1"), t.get("t2"), t.get("t3")]):
        key = f"t{k + 1}"
        if tp and key not in t["hits"] and price >= tp:
            t["hits"][key] = hm
            _sell(t, tp, sells[k] if k < len(sells) else t["rest"])
            _event(t, f"{k + 1}차목표달성", hm)
            t["be"] = True
    if t["rest"] <= 1e-9:
        _finish(t, hm, now)
        return True
    inzone = t["buy_lo"] <= price <= t["buy_hi"]
    if inzone and not t.get("inzone", True) and not t["hits"] and not cfg.get("wait_buy"):
        _event(t, "매수구간", hm)
    t["inzone"] = inzone
    return len(t["events"]) != n0


def _sell(t: dict, px: float, frac: float) -> None:
    frac = min(frac, t["rest"])
    if frac > 0:
        t["sold"].append([px, frac])
        t["rest"] -= frac


def _finish(t: dict, hm: str, now: pd.Timestamp) -> bool:
    e = t["entry"]
    val = sum(px * fr for px, fr in t["sold"])
    tot = sum(fr for _, fr in t["sold"]) or 1.0
    avg = val / tot
    t["pnl"] = round((avg / e - 1) * 100 - COST, 3)
    t["exit_price"] = round(avg, 2)
    t["exit_time"] = now.strftime("%Y-%m-%d ") + hm
    if t["hits"]:
        t["result"] = "이익실현"
    elif any(x["state"] == "매도신호포착" for x in t["events"]) or (t["state"] == "마감 청산" and avg >= e):
        t["result"] = "매수가매도" if avg >= t["stop"] else "손절"
    else:
        t["result"] = "손절"
    t["done"] = True
    return True


class Tracker:
    def __init__(self, sb, kind: str, day: str, user_id: str | None = None, amount: float = AMOUNT,
                 carry_only: bool = False, write_carry: bool = True):
        """carry_only: 전날 이월분만 관리 (오늘 파일은 안 씀 — 당일매매 통합 실행이 종가배팅 다음 날 오전을 추적할 때)
        write_carry: False 면 전날 파일은 안 씀 (종가배팅 실행은 오늘 후보만 — 다음 날 오전 결과를 덮어쓰지 않게)"""
        self.sb, self.kind, self.day, self.cfg = sb, kind, day, CFG[kind]
        self.carry_only, self.write_carry = carry_only, write_carry
        self.prev: dict[str, dict] = {}             # 전날 추적 전부 (끝난 것 포함 · 화면용, show_prev)
        self.user_id = user_id if user_id is not None else (os.getenv("SUPABASE_USER_ID") or "").strip() or None
        self.amount = amount
        self.tracks: dict[str, dict] = {}
        self.carry: dict[str, dict] = {}            # 상한가포착: 전날 잡혀 오늘 아침까지 추적하는 종목
        import threading
        self.lock = threading.RLock()               # 1분 갱신(본 스레드)과 실시간 체결(웹소켓 스레드)이 같이 씀
        self.on_event = None                        # (track, 상태) → 알림·실시간 행 (통합 프로세스가 연결)
        self.realtime: set[str] = set()             # 실시간 체결을 받는 종목 (1분봉으로는 목표·손절을 다시 안 봄)
        self.load()

    # ------------------------------------------------ 저장
    def _key(self, day: str) -> str:
        return f"track/{self.kind}/{day}.json"

    def _get(self, day: str) -> dict:
        if not self.sb:
            return {}
        try:
            b = self.sb.download(self._key(day))
            return json.loads(b) if b else {}
        except Exception:  # noqa: BLE001
            return {}

    def load(self) -> None:
        self.tracks = self._get(self.day).get("tracks", {})
        if self.cfg["overnight"]:
            for back in range(1, 6):
                d = (pd.Timestamp(self.day) - pd.Timedelta(days=back)).strftime("%Y-%m-%d")
                old = self._get(d).get("tracks", {})
                if old:
                    self.carry = {c: t for c, t in old.items() if not t.get("done")}
                    self.prev = old
                    self.carry_day = d
                    break

    def save(self) -> None:
        if not self.sb:
            return
        with self.lock:
            self._save()

    def _save(self) -> None:
        try:
            if not self.carry_only:
                self.sb.upload(self._key(self.day), json.dumps({"tracks": self.tracks}, ensure_ascii=False,
                                                               default=str).encode(), "application/json")
            if self.carry and self.write_carry:
                self.sb.upload(self._key(self.carry_day), json.dumps({"tracks": {**self._get(self.carry_day).get("tracks", {}),
                                                                                **self.carry}},
                                                                     ensure_ascii=False, default=str).encode(),
                               "application/json")
        except Exception as e:  # noqa: BLE001
            log.warning("추적 상태 저장 실패: %s", e)

    # ------------------------------------------------ 매매일지
    def _open_position(self, t: dict) -> None:
        if not self.sb or not self.user_id or t.get("pos_id"):
            return
        e = t["entry"]
        qty = max(1, int(self.amount // e)) if e else 1
        row = {"user_id": self.user_id, "mode": "signal", "code": t["code"], "name": t["name"],
               "strategy": self.cfg["name"], "list_key": self.kind, "score": t["score"],
               "entry_time": f"{t['date']} {t.get('buy_time') or t['time']}:00", "entry_price": e, "qty": qty, "entry_cost": e * qty,
               "stop": t["stop"], "target1": t.get("t1"), "target2": t.get("t2"),
               "reasons": t["card"].get("reasons") or [], "warnings": t["card"].get("risks") or [],
               "verdict": t["card"].get("type") or t["card"].get("group"),
               "plan": {"kind": self.kind, "target3": t.get("t3"), "buy_lo": t["buy_lo"], "buy_hi": t["buy_hi"],
                        "track": t["events"]},
               "signal_time": f"{t['date']} {t['time']}:00", "min_price": e, "max_price": e, "status": "open"}
        try:
            r = self.sb.insert("positions", row)
            t["pos_id"] = (r[0] if isinstance(r, list) and r else r or {}).get("id")
        except Exception as ex:  # noqa: BLE001
            log.warning("매매일지 기록 실패 %s: %s", t["name"], ex)

    def _close_position(self, t: dict) -> None:
        if not self.sb or not t.get("pos_id") or t.get("exit_price") is None:
            return
        e, px = t["entry"], t["exit_price"]
        qty = max(1, int(self.amount // e)) if e else 1
        cost, proceeds = e * qty, px * qty
        days = int(np.busday_count(t["date"], t["exit_time"][:10])) if t.get("exit_time") else 0
        patch = {"exit_time": t["exit_time"] + ":00", "exit_price": px, "exit_proceeds": proceeds,
                 "exit_reason": t["result"], "ret_pct": t["pnl"], "pnl": round(proceeds * (1 - COST / 100) - cost),
                 "hold_days": days, "result": "성공" if t["pnl"] > 0.5 else ("실패" if t["pnl"] < -0.5 else "본전"),
                 "min_price": t["low"], "max_price": t["high"], "status": "closed",
                 "plan": {"kind": self.kind, "target3": t.get("t3"), "buy_lo": t["buy_lo"], "buy_hi": t["buy_hi"],
                          "track": t["events"], "hits": t["hits"]}}
        try:
            self.sb.update("positions", {"id": f"eq.{t['pos_id']}"}, patch)
        except Exception as ex:  # noqa: BLE001
            log.warning("매매일지 매도 기록 실패 %s: %s", t["name"], ex)

    # ------------------------------------------------ 갱신
    def add(self, items: list[dict], now: pd.Timestamp) -> list[str]:
        """처음 신호가 뜬 종목만 고정 (같은 날 같은 종목은 한 번)"""
        new = []
        for r in items:
            if r.get("status") != self.cfg["trigger"] or r["code"] in self.tracks or r["code"] in self.carry:
                continue
            if not (_f(r.get("entry")) or _f(r.get("price"))) or not _f(r.get("stop")):
                continue
            t = Track.new(self.kind, self.day, r, now)
            with self.lock:
                self.tracks[r["code"]] = t
                if t["bought"]:
                    self._open_position(t)
            new.append(r["code"])
            self._emit(t, "매수발생" if t["bought"] else "후보고정")       # 종가배팅은 매수 범위에 들어올 때 매수발생
            log.info("★ 추적 시작 %s %s %s %s원", t["time"], t["name"], self.cfg["trigger"], f"{t['entry']:,.0f}")
        return new

    def codes(self) -> list[str]:
        with self.lock:
            return [c for c, t in {**self.carry, **self.tracks}.items() if not t["done"]]

    def _emit(self, t: dict, state: str) -> None:
        if self.on_event:
            try:
                self.on_event(self, t, state)
            except Exception as e:  # noqa: BLE001
                log.warning("알림 실패: %s", e)

    def _after(self, t: dict, n0: int) -> None:
        for ev in t["events"][n0:]:
            if ev["state"] == "매수":                       # 종가배팅: 매수 범위 → 매수 · 매매일지
                self._open_position(t)
                log.info("★ 매수 %s %s %s원", t["buy_time"], t["name"], f"{t['entry']:,.0f}")
                self._emit(t, "매수발생")
            else:
                self._emit(t, ev["state"])
        if t["done"]:
            self._close_position(t)
            log.info("■ 결과 %s %s %s %s", t["exit_time"], t["name"], t["result"],
                     "" if t["pnl"] is None else f"{t['pnl']:+.2f}%")
            self._emit(t, "결과")

    def update(self, code: str, bars: pd.DataFrame | None, price: float | None, score_now: float | None,
               now: pd.Timestamp) -> None:
        with self.lock:
            t = self.tracks.get(code) or self.carry.get(code)
            if not t or t["done"]:
                return
            n0 = len(t["events"])
            ticks = code in self.realtime
            step(t, bars, None if ticks else price, score_now, now, self.cfg, ticks=ticks)
            self._after(t, n0)

    def on_tick(self, code: str, price: float, now: pd.Timestamp) -> bool:
        """실시간 체결 (웹소켓 스레드) → 상태가 바뀌면 True"""
        with self.lock:
            t = self.tracks.get(code) or self.carry.get(code)
            if not t or t["done"]:
                return False
            n0 = len(t["events"])
            changed = tick(t, price, now, self.cfg)
            if changed:
                self._after(t, n0)
            return changed

    def live_row(self, t: dict) -> dict:
        """앱 실시간(intraday_live)용 작은 행 — 카드(기존 상태설명)는 빼고"""
        with self.lock:                                 # 실시간 스레드가 바꾸는 중일 수 있어 복사본으로
            pl = json.loads(json.dumps({k: v for k, v in t.items() if k not in ("card", "sold")}, default=str))
        return {"key": f"{self.kind}:{t['date']}:{t['code']}", "kind": self.kind, "date": t["date"], "code": t["code"],
                "payload": pl}

    def view(self) -> list[dict]:
        """앱: 신호 시각 순 (먼저 잡힌 것 위). 전날에서 이어진 것 먼저"""
        with self.lock:                                 # 실시간 스레드가 바꾸는 중일 수 있어 복사본으로
            before = {**self.prev, **self.carry} if self.cfg.get("show_prev") else dict(self.carry)
            rows = json.loads(json.dumps(list(before.values()) + list(self.tracks.values()), default=str))
        return sorted(rows, key=lambda t: (t["date"], t["time"]))

    def any_open(self) -> bool:
        return bool(self.codes())


def finish_day(sb, kis, day: str, kinds=("daytrade", "limitcatch", "closingbet")) -> dict:
    """저녁 배치: PC 가 꺼졌거나 중간에 멈춰 결과가 안 난 추적을 그날 1분봉으로 마무리 (PC 실시간이 없을 때의 대비)
      당일단타    오늘 추적 → 09:00~15:30 1분봉 → 15:20 마감 청산까지
      상한가포착  전날에서 이어진 추적 → 오늘 09:00~09:30 1분봉 → 09:30 청산 · 오늘 잡힌 추적 → 오늘 1분봉까지 반영(내일 09:30 마감)
    결과가 나오면 관리자 매매일지도 매도 기록. 7일 지난 intraday_live 행 정리"""
    out = {}
    day = pd.Timestamp(day).strftime("%Y-%m-%d")
    end = pd.Timestamp(f"{day} 15:31")                                # 장 마감 뒤 (종가배팅 15:30 까지 매수 범위 판단 → 그 뒤 미체결)
    for kind in kinds:
        tr = Tracker(sb, kind, day)
        n_done = 0
        cend = tr.cfg["end"]                                         # 이월분 마감 (상한가포착 09:30 · 종가배팅 10:30)
        groups = [(tr.carry, cend.replace(":", "") + "00", pd.Timestamp(f"{day} {cend}"))] if tr.carry else []
        groups.append((tr.tracks, "153000", end))
        for tracks, until, now in groups:
            for code, t in list(tracks.items()):
                if t["done"]:
                    continue
                try:
                    bars = kis.minute_bars_day(code, "090000", until)
                except Exception as e:  # noqa: BLE001
                    log.warning("1분봉 실패 %s: %s", code, e)
                    continue
                if bars is None or bars.empty:
                    continue
                bars = bars[bars["time"].dt.strftime("%Y-%m-%d") == day]
                last = float(bars["close"].iloc[-1]) if len(bars) else None
                tr.update(code, bars, last, None, now)
                n_done += int(t["done"])
        tr.save()
        out[kind] = {"tracked": len(tr.tracks) + len(tr.carry), "finished_now": n_done,
                     "open": len(tr.codes())}
        if kind == "closingbet":                                      # 앱 '종가배팅' 구역의 전날·오늘 내역
            try:
                from ..cloud import publish as pub
                pub.publish_status(sb, "closingbet_track", {"date": day, "time": "마감", "tracked": tr.view()})
            except Exception as e:  # noqa: BLE001
                log.debug("종가배팅 내역 발행 실패: %s", e)
    try:
        cut = (pd.Timestamp(day) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        sb.delete("intraday_live", {"date": f"lt.{cut}"})
    except Exception as e:  # noqa: BLE001
        log.debug("intraday_live 정리 실패: %s", e)
    return out
