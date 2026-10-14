"""당일 잠정 수급 (외국인·기관 장중 추정 순매수) — PC 22_intraday 가 발행 → system_status 'flow_live'

KIS '종목별 외인기관 추정가집계' (HHPTJ04160200) — 증권사 장중 추정치, 하루 5번 갱신
  1: 09:30 · 2: 10:00 · 3: 11:20 · 4: 13:20 · 5: 14:30   (장 마감 후 확정치와 다를 수 있음)
수량(주) × 현재가 → 억원. 대상 = 오늘 고정 종목 + 당일단타·상한가포착 후보 + 관심 탭 종목 (최대 MAX_CODES)
갱신 시각 5분 뒤에 한 번씩만 받음 (종목당 하루 5회) + 새로 고정된 종목은 바로 한 번
payload: {"date", "time", "slot": "11:20", "flows": {code: [외인 억, 기관 억, "11:20"]}}
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)

SLOTS = {"1": "09:30", "2": "10:00", "3": "11:20", "4": "13:20", "5": "14:30"}
DUE = [("09:35", "09:30"), ("10:05", "10:00"), ("11:25", "11:20"), ("13:25", "13:20"), ("14:35", "14:30")]
MAX_CODES = 150


def _f(v) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse(js: dict) -> tuple[float, float, str] | None:
    """KIS 응답 → (외인 순매수 주, 기관 순매수 주, '11:20') — 가장 늦은 시간대. 아직 없으면 None"""
    rows = js.get("output2") or js.get("output") or []
    if isinstance(rows, dict):
        rows = [rows]
    best = None
    for r in rows:
        gb = str(r.get("bsop_hour_gb") or "").strip()
        f, i = _f(r.get("frgn_fake_ntby_qty")), _f(r.get("orgn_fake_ntby_qty"))
        if gb not in SLOTS or f is None or i is None:
            continue
        if best is None or gb > best[0]:
            best = (gb, f, i)
    if best is None:
        return None
    return best[1], best[2], SLOTS[best[0]]


def to_eok(qty: float, price: float | None) -> float | None:
    if not price or price <= 0:
        return None
    return round(qty * price / 1e8, 1)


def due_slot(hm: str) -> str | None:
    """지금 받아야 할 최신 갱신 시각 ('11:20') — 09:35 전이면 None"""
    s = None
    for at, slot in DUE:
        if hm >= at:
            s = slot
    return s


class FlowLive:
    def __init__(self, sb, kis, price_fn, publish: bool = True):
        self.sb, self.kis, self.price_fn, self.publish_on = sb, kis, price_fn, publish
        self.flows: dict[str, list] = {}
        self.got: dict[str, str] = {}          # code → 받은 slot
        self.tries: dict[tuple[str, str], int] = {}
        self.lock = threading.Lock()
        self.busy = False
        self.fail = 0

    def fetch(self, code: str) -> tuple[float, float, str] | None:
        js = self.kis._get("/uapi/domestic-stock/v1/quotations/investor-trend-estimate", "HHPTJ04160200",
                           {"MKSC_SHRN_ISCD": code})
        return parse(js)

    def todo(self, hm: str, codes: list[str]) -> tuple[str | None, list[str]]:
        slot = due_slot(hm)
        if slot is None or hm > "15:40":
            return None, []
        codes = list(dict.fromkeys(codes))[:MAX_CODES]
        return slot, [c for c in codes if self.got.get(c) != slot]

    def run(self, now, codes: list[str]) -> int:
        """받아야 할 종목만 받고 발행 (호출 수 반환)"""
        hm = now.strftime("%H:%M")
        slot, need = self.todo(hm, codes)
        if not need:
            return 0
        try:
            px = self.price_fn(need) or {}
        except Exception as e:  # noqa: BLE001
            log.debug("잠정수급 현재가 실패: %s", e)
            px = {}
        n = 0
        for c in need:
            n += 1
            try:
                r = self.fetch(c)
            except Exception as e:  # noqa: BLE001
                self.fail += 1
                if self.fail <= 3:
                    print(f"⚠ 잠정수급 {c} 실패: {e}")
                continue
            k = (c, slot)
            self.tries[k] = self.tries.get(k, 0) + 1
            if (r is not None and r[2] >= slot) or self.tries[k] >= 3:   # 이번 갱신분이 아직이면 1분 뒤 다시 (최대 3번)
                self.got[c] = slot
            if r is None:
                continue
            fe, ie = to_eok(r[0], px.get(c)), to_eok(r[1], px.get(c))
            if fe is None or ie is None:
                continue
            with self.lock:
                self.flows[c] = [fe, ie, r[2]]
        self.publish(now, slot)
        return n

    def publish(self, now, slot: str) -> None:
        if not self.sb or not self.publish_on:
            return
        from stockeye.cloud import publish as pub
        with self.lock:
            flows = dict(self.flows)
        pub.publish_status(self.sb, "flow_live", {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"),
                                                  "slot": slot, "flows": flows})

    def start(self, now, codes: list[str]) -> None:
        """메인 루프에서 매분 호출 — 받을 게 있으면 스레드로 (루프를 막지 않음)"""
        if self.busy:
            return
        slot, need = self.todo(now.strftime("%H:%M"), codes)
        if not need:
            return
        self.busy = True

        def job():
            try:
                n = self.run(now, codes)
                if n > 1:
                    print(f"   잠정수급({slot}) {n}종목 · 표시 {len(self.flows)}")
            except Exception as e:  # noqa: BLE001
                print(f"⚠ 잠정수급 실패: {e}")
            finally:
                self.busy = False
        threading.Thread(target=job, name="flow-live", daemon=True).start()
