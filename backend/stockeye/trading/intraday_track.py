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
}
RESULTS = ("이익실현", "매수가매도", "손절")
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
                                       "excluded", "risks", "parts", "labels", "maxes", "lock", "book", "news_level",
                                       "fill_warn", "level") if r.get(k) is not None}
        return {"kind": kind, "date": day, "code": r["code"], "name": r.get("name"), "time": hm,
                "score": _f(r.get("score")), **p, "card": card, "events": [{"state": "매수구간", "time": hm}],
                "state": "매수구간", "hits": {}, "sold": [], "rest": 1.0, "be": False, "result": None, "pnl": None,
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
         cfg: dict) -> bool:
    """새 1분봉·지금 가격으로 상태 갱신. 결과가 나오면 True"""
    if t["done"]:
        return False
    e, stop = t["entry"], t["stop"]
    tg = [t.get("t1"), t.get("t2"), t.get("t3")]
    seen = pd.Timestamp(t["seen"])
    if bars is not None and len(bars):
        b = bars[bars["time"] > seen].sort_values("time").reset_index(drop=True)
        full = bars.sort_values("time").reset_index(drop=True)
        off = len(full) - len(b)
        for i, r in b.iterrows():
            hm = pd.Timestamp(r["time"]).strftime("%H:%M")
            lo, hi, cl = float(r["low"]), float(r["high"]), float(r["close"])
            t["high"], t["low"] = max(t["high"], hi), min(t["low"], lo)
            st = e if t["be"] else stop
            if st and lo <= st:                                        # 손절 (1차 뒤엔 본전)
                _sell(t, st, t["rest"])
                _event(t, "손절" if not t["be"] else "본전 매도", hm)
                return _finish(t, hm, now)
            for k, tp in enumerate(tg):
                key = f"t{k + 1}"
                if tp and key not in t["hits"] and hi >= tp:
                    t["hits"][key] = hm
                    _sell(t, tp, SELL[k] if k < 2 else t["rest"])
                    _event(t, f"{k + 1}차목표달성", hm)
                    t["be"] = True
            if t["rest"] <= 1e-9:
                return _finish(t, hm, now)
            if _sell_signal(full, off + i) and "매도신호포착" not in [x["state"] for x in t["events"]]:
                _event(t, "매도신호포착", hm)
                _sell(t, cl, t["rest"])                                 # 1차 전이면 매수가 부근 매도, 뒤면 나머지 정리
                return _finish(t, hm, now)
            t["last"] = cl
        t["seen"] = pd.Timestamp(b["time"].iloc[-1]).strftime("%Y-%m-%d %H:%M") if len(b) else t["seen"]
    if price:
        t["last"] = price
        inzone = t["buy_lo"] <= price <= t["buy_hi"]
        if inzone and not t.get("inzone", True) and not t["hits"]:      # 매수구간을 벗어났다 다시 들어올 때만
            _event(t, "매수구간", now.strftime("%H:%M"))
        t["inzone"] = inzone
    if score_now is not None:
        t["score_now"] = score_now
        if score_now < cfg["hold"] and "신규진입보류" not in [x["state"] for x in t["events"]]:
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
    def __init__(self, sb, kind: str, day: str, user_id: str | None = None, amount: float = AMOUNT):
        self.sb, self.kind, self.day, self.cfg = sb, kind, day, CFG[kind]
        self.user_id = user_id if user_id is not None else (os.getenv("SUPABASE_USER_ID") or "").strip() or None
        self.amount = amount
        self.tracks: dict[str, dict] = {}
        self.carry: dict[str, dict] = {}            # 상한가포착: 전날 잡혀 오늘 아침까지 추적하는 종목
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
                    self.carry_day = d
                    break

    def save(self) -> None:
        if not self.sb:
            return
        try:
            self.sb.upload(self._key(self.day), json.dumps({"tracks": self.tracks}, ensure_ascii=False, default=str).encode(),
                           "application/json")
            if self.carry:
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
               "entry_time": f"{t['date']} {t['time']}:00", "entry_price": e, "qty": qty, "entry_cost": e * qty,
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
        if not self.sb or not t.get("pos_id"):
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
            self.tracks[r["code"]] = t
            self._open_position(t)
            new.append(r["code"])
            log.info("★ 추적 시작 %s %s %s %s원", t["time"], t["name"], self.cfg["trigger"], f"{t['entry']:,.0f}")
        return new

    def codes(self) -> list[str]:
        return [c for c, t in {**self.carry, **self.tracks}.items() if not t["done"]]

    def update(self, code: str, bars: pd.DataFrame | None, price: float | None, score_now: float | None,
               now: pd.Timestamp) -> None:
        t = self.tracks.get(code) or self.carry.get(code)
        if not t or t["done"]:
            return
        if step(t, bars, price, score_now, now, self.cfg):
            self._close_position(t)
            log.info("■ 결과 %s %s %s %+.2f%%", t["exit_time"], t["name"], t["result"], t["pnl"])

    def view(self) -> list[dict]:
        """앱: 신호 시각 순 (먼저 잡힌 것 위). 전날에서 이어진 것 먼저"""
        rows = list(self.carry.values()) + list(self.tracks.values())
        return sorted(rows, key=lambda t: (t["date"], t["time"]))

    def any_open(self) -> bool:
        return bool(self.codes())
