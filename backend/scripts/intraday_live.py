"""당일매매 통합 실행 — 당일단타 + 상한가포착을 한 프로세스에서 (PC: scripts_win/22_intraday.bat · 작업 스케줄러 월~금 08:50)

  1분마다      당일단타 새 종목 찾기(09:00~10:00) · 상한가포착(09:05~15:20) — 기존 두 실행과 같은 계산
  실시간       진입조건충족으로 고정된 종목은 KIS 웹소켓으로 체결가를 받아 목표·손절을 체결 때마다 바로 판단
               (매도신호포착 = 1분 거래량이라 1분마다). 웹소켓이 끊기면 저절로 1분봉 판단으로 돌아감
  앱 전달      상태가 바뀌면 Supabase intraday_live 에 작은 행 → 앱 '당일매매' 가 바로 받음 (Realtime)
               가격만 바뀐 것은 종목당 10초에 한 번
  휴대폰 알림  매수발생(새로 고정) · 매도발생(매도신호포착) → 관리자 ntfy 토픽에만 (관리자 프로필 토픽 + PC 의 NTFY_TOPIC)
  한 프로세스라 KIS 토큰·초당 한도·웹소켓 연결을 같이 씀 (두 프로그램이 따로 열면 충돌할 수 있음)

  python -m scripts.intraday_live              # 지금부터 15:21 까지
  python -m scripts.intraday_live --no-ws      # 실시간 없이 1분 갱신만
⚠ 주문은 하지 않는다.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import pandas as pd

log = logging.getLogger("stockeye.intraday_live")

BANNER = """==============================================================
 StockEye [당일매매 통합]  (22_intraday.bat · 작업 스케줄러 월~금 08:50)
  당일단타 09:00~10:00 새 종목 찾기 · 상한가포착 09:05~15:20 (1분마다)
  진입조건충족 종목은 고정 → KIS 실시간 체결로 목표·손절 바로 판단 → 앱 '당일매매' 에 바로 표시
  매수발생·매도발생은 관리자 휴대폰(ntfy)으로 · 결과는 관리자 매매일지(당일매매 자동)
  주문은 하지 않음 · 창을 닫으면 멈춤 (닫아도 되는 때: 15:21 이후)
=============================================================="""
PRICE_EVERY = 10          # 가격만 바뀐 실시간 행은 종목당 10초에 한 번


def _now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)


def admin_topics(sb) -> list[str]:
    """관리자에게만: 관리자 프로필의 ntfy 토픽 + 이 PC 의 NTFY_TOPIC (같으면 한 번)"""
    out = []
    env = (os.getenv("NTFY_TOPIC") or "").strip().strip("/")
    if env:
        out.append(env)
    if sb:
        try:
            for r in sb.select("profiles", {"select": "ntfy_topic", "is_admin": "eq.true"}) or []:
                t = (r.get("ntfy_topic") or "").strip().strip("/")
                if t:
                    out.append(t)
        except Exception as e:  # noqa: BLE001
            log.warning("관리자 알림 토픽 읽기 실패: %s", e)
    return list(dict.fromkeys(out))


class Live:
    """추적 상태 → 앱 실시간 행 · 관리자 알림
    보내기는 따로 스레드에서 (웹소켓 체결 처리가 네트워크 때문에 밀리지 않게) — on_event 는 줄에 넣기만 함"""

    def __init__(self, sb, topics: list[str], background: bool = True):
        import queue
        import threading
        from stockeye.trading.notify import Notifier
        self.sb, self.topics, self.nt = sb, topics, Notifier()
        self.last_push: dict[str, float] = {}
        self.q: "queue.Queue" = queue.Queue()
        self.sent = 0
        if background:
            threading.Thread(target=self._worker, name="live-push", daemon=True).start()

    def _worker(self) -> None:
        while True:
            job = self.q.get()
            try:
                job()
            except Exception as e:  # noqa: BLE001
                log.debug("실시간 전달 실패: %s", e)

    def flush(self, timeout: float = 15) -> None:
        end = time.time() + timeout
        while not self.q.empty() and time.time() < end:
            time.sleep(0.2)

    def push(self, tracker, t: dict, force: bool = True) -> None:
        if not self.sb:
            return
        key = f"{tracker.kind}:{t['date']}:{t['code']}"
        if not force and time.time() - self.last_push.get(key, 0) < PRICE_EVERY:
            return
        self.last_push[key] = time.time()
        from datetime import datetime, timezone
        row = tracker.live_row(t) | {"updated_at": datetime.now(timezone.utc).isoformat()}
        self.q.put(lambda: self.sb.upsert("intraday_live", [row], "key"))

    @staticmethod
    def message(tracker, t: dict, state: str) -> tuple[str, str] | None:
        """매수발생(새로 고정) · 매도발생(매도신호포착)만 알림. 그 밖의 상태는 None"""
        name = tracker.cfg["name"]
        if state == "매수발생":
            return (f"매수발생 · {t['name']}",
                    f"{name} {t.get('buy_time') or t['time']} {'매수 범위 매수' if tracker.kind == 'closingbet' else '진입조건충족'}"
                    f"\n매수 {t['entry']:,.0f} · 손절 {t['stop']:,.0f}"
                    + (f" · 1차 {t['t1']:,.0f}" if t.get("t1") else ""))
        if state == "매도신호포착":
            return (f"매도발생 · {t['name']}",
                    f"{name} {t['events'][-1]['time']} 매도신호포착 (매물 급증) · 지금 {t.get('last') or 0:,.0f}")
        return None

    def notify(self, tracker, t: dict, state: str) -> None:
        m = self.message(tracker, t, state)
        if not m:
            return
        for tp in self.topics:
            self.q.put(lambda tp=tp: self.nt.send_topic(tp, m[0], m[1], priority="high"))
        self.sent += 1

    def on_event(self, tracker, t: dict, state: str) -> None:
        self.push(tracker, t)
        self.notify(tracker, t, state)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=int, default=60)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--no-ws", action="store_true", help="실시간 웹소켓 없이 1분 갱신만")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    print(BANNER, flush=True)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)
    from stockeye.config import load_config, data_dir
    from stockeye.data.store import DataStore
    from stockeye.data.sources.kis_source import KISClient
    from stockeye.data.sources import naver_live
    from stockeye.cloud.client import Supabase, enabled
    import scripts.daytrade as sd
    import scripts.limitcatch as sl
    if _now().weekday() >= 5 or naver_live.is_trading_day() is False:
        print("오늘은 장이 열리지 않음 → 종료"); return
    if _now().strftime("%H:%M") >= "15:40":
        print("이미 장이 끝남 → 종료"); return
    cfg = load_config()
    store = DataStore(data_dir(cfg))
    listing, ohlcv, sectors = store.load("listing"), store.load("ohlcv"), store.load("sectors")
    if listing is None or listing.empty or ohlcv is None or ohlcv.empty:
        sys.exit("종목 목록·일봉이 없습니다 — 먼저 4_daily.bat 로 데이터를 받아 두세요")
    sb = Supabase() if enabled() and not args.dry_run else None
    kc = cfg.get("kis", {})
    kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
    dt = sd.Runner(sb, kis, listing, args.top, args.workers, runner="pc")
    dt.until = "10:00"
    lc = sl.Runner(sb, kis, listing, ohlcv, sectors, args.workers, runner="pc", log_dir=data_dir(cfg) / "limitcatch")
    from stockeye.trading.intraday_track import Tracker
    cb = Tracker(sb, "closingbet", _now().strftime("%Y-%m-%d"), carry_only=True)   # 전날 종가배팅 → 오늘 10:30 까지
    live = Live(sb, admin_topics(sb))
    print(f"관리자 알림 토픽 {len(live.topics)}개" + ("" if live.topics else " — 없음 (알림 설정에서 토픽 저장 또는 setx NTFY_TOPIC)"))
    trackers = (dt.track, lc.track, cb)

    def cb_publish(now) -> None:                                       # 앱 '종가배팅' 구역의 전날 내역
        if sb:
            try:
                from stockeye.cloud import publish as pub
                pub.publish_status(sb, "closingbet_track", {"date": cb.day, "time": now.strftime("%H:%M"),
                                                            "tracked": cb.view()})
            except Exception as e:  # noqa: BLE001
                log.debug("종가배팅 내역 발행 실패: %s", e)
    cb_publish(_now())

    def publish_bars(now) -> None:
        """고정 종목(끝난 것 포함) 1분봉 최근 2시간 → system_status 'intraday_bars' (현재가는 앱이 실시간으로 덧그림)"""
        if not sb or now.strftime("%H:%M") < "09:01":
            return
        from stockeye.trading.intraday_track import pack_bars
        hhmmss = now.strftime("%H%M%S")
        out = {}
        for tr, run in ((dt.track, dt), (lc.track, lc), (cb, dt)):
            with tr.lock:
                codes = [c for c in {**tr.carry, **tr.tracks}]
            for code in codes:
                if code in out:
                    continue
                b = run._bars(code, hhmmss)                            # 캐시 + 새 봉만 (종목당 1회 호출)
                out[code] = pack_bars(b)
        from stockeye.cloud import publish as pub
        pub.publish_status(sb, "intraday_bars", {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"),
                                                 "bars": out})
    if cb.carry:
        print(f"전날 종가배팅 {len(cb.carry)}개 → 오늘 10:30 까지 추적")
    for tr in trackers:
        tr.on_event = live.on_event

    def on_tick(tk: dict) -> None:
        code, price = tk.get("code"), tk.get("price")
        if not code or not price:
            return
        now = _now()
        for tr in trackers:
            if code in tr.realtime:
                if tr.on_tick(code, price, now):
                    tr.save()
                else:
                    t = tr.tracks.get(code) or tr.carry.get(code)
                    if t and not t["done"]:
                        live.push(tr, t, force=False)

    feed = None
    if not args.no_ws:
        from stockeye.data.sources.kis_ws import RealtimeFeed
        feed = RealtimeFeed(on_tick, kc.get("env", "prod"))
        if not feed.start():
            feed = None
    while _now().strftime("%H:%M") < "08:59":
        print(f"{_now():%H:%M:%S} 장 시작 대기..."); time.sleep(20)
    dt_closed = False
    sector_done: set[str] = set()                                       # 업종/테마 오늘 강도: 09:10 부터 매시 10분 (한 번씩)

    def sector_slot(hm: str) -> None:
        slot = hm[:2] + ":10"
        if not sb or hm < "09:10" or hm > "15:20" or hm < slot or slot in sector_done:
            return
        sector_done.add(slot)

        def job():
            try:
                import scripts.sector_live as sl_
                p = sl_.run(sb, quiet=True)
                print(f"   업종/테마 강도 발행 {p['time']} · {len(p['groups'])}개")
            except Exception as e:  # noqa: BLE001
                print(f"⚠ 업종/테마 강도 실패: {e}")
        import threading
        threading.Thread(target=job, name="sector-live", daemon=True).start()   # 전 종목 시세 1회 (1시간에 한 번)

    while True:
        t0 = time.time()
        now = _now()
        hm = now.strftime("%H:%M")
        try:
            if "09:00" <= hm < dt.until:
                p = dt.step()
                dt.publish(p)
                print(f"{p['time']} [당일단타] 후보 {p['scanned']} · 고정 {len(p['tracked'])}")
            elif dt.track.any_open() or (hm >= dt.until and not dt_closed):   # 10:00 뒤: 고정 종목만 (없으면 마감 표시 한 번)
                p = dt.track_step()
                dt.publish(p)
                dt_closed = True
            if "09:05" <= hm < "15:21":
                q = lc.step()
                lc.publish(q)
                print(f"{q['time']} [상한가포착] 대상 {q['scanned']} · 고정 {len(q['tracked'])}")
            elif lc.track.any_open():                          # 09:05 전: 전날 상한가포착 종목만 1분봉으로
                for code in lc.track.codes():
                    b = lc._bars(code, now.strftime("%H%M%S"))
                    lc.track.update(code, b, float(b["close"].iloc[-1]) if b is not None and len(b) else None, None, now)
                lc.track.save()
        except Exception as e:  # noqa: BLE001
            print(f"⚠ 이번 회차 실패: {e}")
        try:                                                           # 전날 종가배팅: 09:00~10:30 1분봉으로 (실시간이면 목표·손절은 체결로)
            if cb.any_open() and hm >= "09:00":
                for code in cb.codes():
                    b = dt._bars(code, now.strftime("%H%M%S"))
                    cb.update(code, b, float(b["close"].iloc[-1]) if b is not None and len(b) else None, None, now)
                cb.save()
                cb_publish(now)
        except Exception as e:  # noqa: BLE001
            print(f"⚠ 종가배팅 추적 실패: {e}")
        sector_slot(hm)
        try:                                                           # 앱 카드 1분봉 차트 (오늘 고정 종목 · 1분에 한 번)
            publish_bars(now)
        except Exception as e:  # noqa: BLE001
            log.debug("1분봉 발행 실패: %s", e)
        # 실시간: 고정 종목만 구독 (먼저 잡힌 순, 최대 40). 끊겨 있으면 1분봉으로 목표·손절 판단
        codes = list(dict.fromkeys(cb.codes() + lc.track.codes() + dt.track.codes()))
        if feed:
            feed.set_wanted(codes)
            ok = feed.connected and (feed.last_tick == 0 or time.time() - feed.last_tick < 300)
            for tr in trackers:
                tr.realtime = set(feed.subbed) & set(tr.codes()) if ok else set()
            st = feed.status()
            if codes:
                print(f"   실시간 {'연결' if st['connected'] else '끊김'} · 구독 {st['subscribed']} · 체결 {st['ticks']}")
        if _now().strftime("%H:%M") >= "15:21" and not lc.track.any_open() or _now().strftime("%H:%M") >= "15:31":
            break
        time.sleep(max(5, args.every - (time.time() - t0)))
    if feed:
        feed.stop()
    live.flush()
    try:
        dt.save_signals()
        if dt.last_items:
            dt.publish({**dt.track_step(), "closed": True})
    except Exception as e:  # noqa: BLE001
        print(f"⚠ 당일단타 마무리 실패: {e}")
    try:
        q = lc.step() if _now().strftime("%H:%M") < "15:40" else None
        if q:
            lc.publish(q)
            lc.save_signals(q)
        lc.upload_ticks()
    except Exception as e:  # noqa: BLE001
        print(f"⚠ 상한가포착 마무리 실패: {e}")
    live.flush()
    print("끝 — 남은 결과는 저녁 배치가 1분봉으로 마무리합니다")


if __name__ == "__main__":
    main()
