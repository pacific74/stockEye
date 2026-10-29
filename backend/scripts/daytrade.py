"""당일단타 — 평일 아침 PC 에서 실행 (scripts_win/14_daytrade.bat). 09:00~10:00 동안 1분마다:

  1) 네이버 지금 시세로 전 종목 → 오전 누적 거래대금 상위 TOP + 관심 탭 종목 (보통주만)
  2) 후보마다 KIS 1분봉(처음엔 09:00부터, 그다음엔 최근 30개만) · 점수가 될 만한 종목은 호가(스프레드)
  3) engine.daytrade 로 점수·필수 제외·돌파/눌림목 신호·손절·목표 → 상위 20개를 Supabase system_status 'daytrade' 에 발행
     (앱 '관심 > 당일단타' 탭과 메인이 1분마다 읽음)
  4) '진입 조건 충족' 이 처음 뜬 종목은 신호로 기록 → Storage daytrade/signals/YYYY-MM-DD.json
     → 저녁 배치(cloud_daily)가 그날 1분봉으로 결과(1·2차 익절·손절·장 마감 청산)를 매겨 '검증' 에 누적

  python -m scripts.daytrade                 # 기본: 지금부터 10:00 까지
  python -m scripts.daytrade --until 10:30 --every 60 --top 100
  python -m scripts.daytrade --once          # 한 번만 계산 (장중) — 앱 '종목찾기' 버튼이 GitHub 에서 이걸 실행

필요한 환경변수 (setx): KIS_APP_KEY · KIS_APP_SECRET · SUPABASE_URL · SUPABASE_SERVICE_KEY
  (선택) NAVER_HUB_ID · NAVER_HUB_SECRET — 뉴스 재료 점수. 없으면 중립 5점
⚠ 주문은 하지 않는다 (알림·관찰용). 매수는 직접 판단.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

import pandas as pd

log = logging.getLogger("stockeye.daytrade")

BANNER = """==============================================================
 StockEye [당일단타 단독]  (14_daytrade.bat · 매일 자동은 22_intraday.bat 통합 실행)
  09:00~10:00  1분마다 새 종목 찾기 → 앱 하단 '당일매매'
  '진입 조건 충족' 종목은 그 시각 계획으로 고정 → 15:20 까지 목표·손절 추적
  결과는 관리자 매매일지(당일매매 자동)에 기록 · 주문은 하지 않음
  창을 닫으면 멈춤 (닫아도 되는 때: 15:20 이후)
=============================================================="""
SHOW = 20


def _now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)


def _job(sb, **payload) -> None:
    """앱 '종목찾기' 버튼 요청 상태 (system_status 'daytrade_job')"""
    try:
        from stockeye.cloud import publish as pub
        pub.publish_status(sb, "daytrade_job", payload)
    except Exception:  # noqa: BLE001
        pass


def watch_codes(sb) -> set[str]:
    """최근 리포트의 관심 탭 종목 (V3·익일·상승초기·추세전환·상파)"""
    try:
        rows = sb.select("daily_reports", {"select": "date", "order": "date.desc", "limit": "1"})
        if not rows:
            return set()
        d = str(rows[0]["date"])[:10]
        cs = sb.select("candidates", {"select": "code", "date": f"eq.{d}",
                                      "list": "in.(v3,nextday,early,reversal,uplimit)", "limit": "1000"})
        return {r["code"] for r in cs}
    except Exception as e:  # noqa: BLE001
        log.warning("관심 탭 종목 읽기 실패: %s", e)
        return set()


class Runner:
    def __init__(self, sb, kis, listing: pd.DataFrame, top: int = 100, workers: int = 8, runner: str = "pc"):
        from stockeye.engine.nextday import common_stock
        self.sb, self.kis, self.top, self.workers, self.runner = sb, kis, top, workers, runner
        self.until = "10:00"
        lst = listing.drop_duplicates("code", keep="last")
        self.names = dict(zip(lst["code"], lst["name"]))
        self.market = dict(zip(lst["code"], lst["market"])) if "market" in lst else {}
        self.admin = set(lst.loc[lst["is_admin"].astype(bool), "code"]) if "is_admin" in lst else set()
        self.codes = [c for c in lst["code"] if common_stock(c, self.names.get(c, ""))]
        self.watch = watch_codes(sb) if sb else set()
        self.bars: dict[str, pd.DataFrame] = {}
        self.news: dict[str, str | None] = {}
        self.news_items: dict[str, list] = {}                     # 앱 상세 화면용 뉴스 제목
        self.spread: dict[str, tuple[float, float | None]] = {}     # code → (받은 시각, 스프레드)
        self.hi_n: dict[str, float | None] = {}                       # code → 최근 일봉(30거래일) 고가 (신고가 돌파 제외용)
        self.adr: dict[str, float | None] = {}                       # code → 평소 하루 변동폭 (하루 한 번)
        self.signals: dict[tuple, dict] = {}
        self.day = _now().strftime("%Y-%m-%d")
        from stockeye.cloud.recommend import IntradayRecorder
        self.rec = IntradayRecorder(sb, "daytrade", runner)          # 검증용 추천 기록 ('진입 조건 충족' 첫 시점)
        from stockeye.trading.intraday_track import Tracker
        self.track = Tracker(sb, "daytrade", self.day)               # 당일매매: 충족 종목 고정 → 상태·결과 추적 → 매매일지
        from stockeye.analysis import regime
        self.reg_days = regime.days_for(sb, self.day) if sb else {}                  # 지수 일별 등락 기록 (반등장 판정용, 2026-10-27)
        self.last_items: list[dict] = []
        from stockeye.analysis import shortlist
        self.sl = shortlist.restore(sb, self.day) if runner == "pc" else shortlist.new_state()   # 오늘의 후보 10 (09:10 고정)

    def discover(self) -> pd.DataFrame:
        """후보 찾기 (2026-10-13): KIS 거래대금 순위 코스피·코스닥 상위 30씩 + 관심 탭 종목만 네이버 시세
        → 실패하면 네이버 전 종목 (5분에 한 번만). 전 종목 시세를 1분마다 받지 않음"""
        from stockeye.data.sources import naver_live
        parts = []
        for mk in ("0001", "1001"):
            try:
                parts.append(self.kis.value_rank(mk))
            except Exception as e:  # noqa: BLE001
                log.warning("KIS 거래대금 순위(%s) 실패: %s", mk, e)
        rank = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        if len(rank):
            rank = rank[rank["code"].isin(set(self.codes))]
            extra = [c for c in self.watch | set(self.track.codes()) if c not in set(rank["code"])]
            if extra:
                try:
                    rank = pd.concat([rank, naver_live.stocks(extra)], ignore_index=True)
                except Exception:  # noqa: BLE001
                    pass
            return rank.drop_duplicates("code").set_index("code")
        if getattr(self, "_snap", None) is None or time.time() - getattr(self, "_snap_at", 0) > 300:
            snap = naver_live.stocks(self.codes)
            if snap.empty:
                raise RuntimeError("거래대금 순위·네이버 시세 모두 받지 못함")
            self._snap, self._snap_at = snap.set_index("code"), time.time()
        return self._snap

    def _news(self, code: str) -> str | None:
        if code not in self.news:
            from stockeye.data import naver_news
            from stockeye.analysis.news_flags import judge
            if naver_news.enabled():
                from stockeye.engine.limitcatch import news_items
                items = naver_news.fetch(self.names.get(code, code), days=2)
                self.news[code] = judge(items)["level"]
                self.news_items[code] = news_items(items)
            else:
                self.news[code] = None
        return self.news[code]

    def _adr(self, code: str) -> float | None:
        if code not in self.adr:
            from stockeye.engine import daytrade as dt
            try:
                d = self.kis.daily(code)
                d = d[d["date"] < pd.Timestamp(self.day)]                 # 오늘(장중) 봉 제외
                self.adr[code] = dt.adr(d)
                self.hi_n[code] = float(d["high"].max()) if len(d) >= 10 else None
            except Exception as e:  # noqa: BLE001
                log.debug("일봉 실패 %s: %s", code, e)
                self.adr[code] = None
                self.hi_n[code] = None
        return self.adr[code]

    def _extras(self, code: str) -> None:
        """호가 스프레드(2분마다) · 뉴스 · 평소 변동폭(하루 한 번)"""
        t0, sp = self.spread.get(code) or (0, None)
        if time.time() - t0 > 120:
            try:
                sp = self.kis.asking(code)["spread"]
            except Exception:  # noqa: BLE001
                sp = None
            self.spread[code] = (time.time(), sp)
        try:
            self._news(code)
        except Exception:  # noqa: BLE001
            self.news[code] = None
        self._adr(code)

    def _bars(self, code: str, hhmmss: str) -> pd.DataFrame:
        old = self.bars.get(code)
        try:
            new = self.kis.minute_bars_day(code, "090000", hhmmss) if old is None or old.empty else self.kis.minute_bars(code, hhmmss)
        except Exception as e:  # noqa: BLE001
            log.debug("분봉 실패 %s: %s", code, e)
            return old if old is not None else pd.DataFrame()
        b = new if old is None or old.empty else pd.concat([old, new]).drop_duplicates("time", keep="last")
        b = b[b["time"].dt.strftime("%H%M%S") >= "090000"].sort_values("time").reset_index(drop=True)
        self.bars[code] = b
        return b

    def step(self) -> dict:
        from stockeye.data.sources import naver_live
        from stockeye.engine import daytrade as dt
        now = _now()
        hhmmss = now.strftime("%H%M%S")
        snap = self.discover()
        idx = naver_live.indices()
        idx_chg = {r["code"]: float(r["chg_pct"]) for _, r in idx.iterrows()} if not idx.empty else {}
        from stockeye.analysis import regime
        reb = {m: regime.for_market(self.reg_days, self.day, idx, m) for m in ("KOSPI", "KOSDAQ")} if not idx.empty else {}
        from concurrent.futures import ThreadPoolExecutor
        live = snap[snap["value"] >= dt.MIN_VALUE]                    # 거래대금 10억 미만은 어차피 제외 → 분봉 안 받음
        top = live.sort_values("value", ascending=False).head(self.top).index.tolist()
        cands = list(dict.fromkeys(top + [c for c in self.watch if c in live.index] + self.track.codes()))
        with ThreadPoolExecutor(self.workers) as ex:                 # 1분봉을 여러 종목 동시에 (KIS 초당 한도 안에서)
            bars = dict(zip(cands, ex.map(lambda c: self._bars(c, hhmmss), cands)))

        def ctx_of(code, b):
            q = snap.loc[code]
            prev = q["close"] / (1 + q["chg_pct"] / 100) if q["chg_pct"] > -100 else None
            market = self.market.get(code)
            return {"name": self.names.get(code, code), "prev_close": prev, "now": now,
                    "idx_chg": idx_chg.get(market or "KOSPI", idx_chg.get("KOSPI", 0.0)),
                    "value": float(b["value"].iloc[-1]) if "value" in b and b["value"].iloc[-1] > 0 else float(q["value"]),
                    "danger": "관리종목" if code in self.admin else None,
                    "spread": (self.spread.get(code) or (0, None))[1], "news_level": None,
                    "rebound": reb.get(market or "KOSPI")}

        first = {}
        for code in cands:
            b = bars.get(code)
            if b is None or b.empty:
                continue
            first[code] = dt.evaluate(b, ctx_of(code, b))
        # 점수가 될 만한 종목만 호가·뉴스·평소 변동폭 (API 아끼기) → 동시에 받고 다시 계산
        need = [c for c, r in first.items() if r["score"] >= 60 and not r["excluded"]]
        with ThreadPoolExecutor(self.workers) as ex:
            list(ex.map(self._extras, need))
        res = []
        for code, r in first.items():
            if code in need:
                ctx = ctx_of(code, bars[code])
                ctx.update({"spread": (self.spread.get(code) or (0, None))[1], "news_level": self.news.get(code),
                            "adr": self.adr.get(code), "hi_n": self.hi_n.get(code)})
                r = dt.evaluate(bars[code], ctx)
            r.update({"code": code, "name": self.names.get(code, code)})
            if self.news_items.get(code):
                r["news"] = self.news_items[code]
            res.append(r)
        # 오늘의 후보: 09:10 뒤 처음 도는 회차에서 점수 상위 10개 고정 → 진입은 후보 안에서만 (PC 실행만, 앱 [종목찾기] 버튼은 그대로)
        from stockeye.analysis import shortlist
        gated = self.runner == "pc"
        if gated and shortlist.freeze(self.sl, res, now.strftime("%H:%M")):
            log.info("★ 오늘의 후보 %d개 확정: %s", len(self.sl["list"]), ", ".join(f"{x['name']}({x['score']})" for x in self.sl["list"]))
        for r in res:
            if gated:
                shortlist.gate(r, self.sl)
                shortlist.tag(r, self.sl)
            code = r["code"]
            if r["status"] == "진입 조건 충족":
                key = (code, r["type"])
                if key not in self.signals:
                    self.signals[key] = {k: r.get(k) for k in ("code", "name", "type", "time", "score", "entry", "stop",
                                                              "t1", "t2", "risk_pct", "t1_pct", "adr_pct", "vwap", "level", "parts")}
                    self.signals[key]["date"] = self.day
                    log.info("★ 진입 조건 충족 %s %s %s %s원 (손절 %s · 1차 %s)", r["time"], r["name"], r["type"],
                             f"{r['entry']:,.0f}", f"{r['stop']:,.0f}", f"{r['t1']:,.0f}")
        order = {"진입 조건 충족": 0, "진입 대기": 1, "관찰": 2, "대상 아님": 3, "진입 금지": 4}
        res.sort(key=lambda r: (order.get(r["status"], 5), -r["score"]))
        keep = [r for r in res if r["status"] in ("진입 조건 충족", "진입 대기", "관찰")][:SHOW]
        if len(keep) < 5:                                  # 조건 맞는 게 적으면 점수 순으로 채워서 보여줌 (상태는 그대로)
            keep += [r for r in sorted(res, key=lambda r: -r["score"]) if r not in keep][:5 - len(keep)]
        for i, r in enumerate(keep, 1):
            r["rank"] = i
        counts = {s: sum(r["status"] == s for r in res) for s in order}
        # 당일매매: 처음 충족된 종목 고정 → 고정 종목은 1분봉·지금 점수로 상태만 갱신
        self.track.add(res, now)
        score = {r["code"]: r["score"] for r in res}
        for code in self.track.codes():
            b = bars.get(code)
            if b is None:
                b = self._bars(code, hhmmss)
            price = float(b["close"].iloc[-1]) if b is not None and len(b) else None
            self.track.update(code, b, price, score.get(code), now)
        self.track.save()
        self.last_items = keep
        return {"date": self.day, "time": now.strftime("%H:%M"), "version": dt.VERSION, "scanned": len(res),
                "counts": counts, "items": keep, "signals": list(self.signals.values()), "idx_chg": idx_chg,
                "runner": self.runner, "until": self.until, "tracked": self.track.view(),
                "shortlist": shortlist.view(self.sl) if gated else None}

    def track_step(self) -> dict:
        """10:00 뒤: 새 종목은 찾지 않고 고정된 종목만 15:20 까지 1분마다 상태·결과 갱신 (종목당 1분봉 1번)"""
        from stockeye.engine import daytrade as dt
        from stockeye.analysis import shortlist
        now = _now()
        hhmmss = now.strftime("%H%M%S")
        for code in self.track.codes():
            b = self._bars(code, hhmmss)
            price = float(b["close"].iloc[-1]) if b is not None and len(b) else None
            self.track.update(code, b, price, None, now)
        self.track.save()
        return {"date": self.day, "time": now.strftime("%H:%M"), "version": dt.VERSION, "scanned": 0,
                "counts": {}, "items": self.last_items, "signals": list(self.signals.values()), "runner": self.runner,
                "until": self.until, "scan_closed": True, "tracked": self.track.view(),
                "shortlist": shortlist.view(self.sl) if self.runner == "pc" else None}

    def publish(self, payload: dict) -> None:
        if not self.sb:
            return
        from stockeye.cloud import publish as pub
        pub.publish_status(self.sb, "daytrade", payload)
        self.rec(self.day, payload.get("items") or [], payload.get("version"), payload.get("time"))

    def save_signals(self) -> None:
        if not self.sb or not self.signals:
            return
        import json
        key = f"daytrade/signals/{self.day}.json"
        try:                                                   # 같은 날 여러 번 돌렸으면 (버튼·PC) 합침
            old = json.loads(self.sb.download(key) or b"[]")
        except Exception:  # noqa: BLE001
            old = []
        seen = {(r["code"], r["type"]) for r in old}
        merged = old + [r for r in self.signals.values() if (r["code"], r["type"]) not in seen]
        self.sb.upload(key, json.dumps(merged, ensure_ascii=False, default=str).encode("utf-8"), "application/json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", default="10:00")
    ap.add_argument("--every", type=int, default=60, help="초")
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--workers", type=int, default=8, help="동시에 받을 종목 수 (KIS 초당 한도 안에서)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="발행하지 않고 화면에만")
    args = ap.parse_args()
    print(BANNER, flush=True)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)

    from stockeye.config import load_config, data_dir
    from stockeye.data.store import DataStore
    from stockeye.data.sources.kis_source import KISClient
    from stockeye.data.sources import naver_live
    from stockeye.cloud.client import Supabase, enabled

    now = _now()
    if now.weekday() >= 5 or naver_live.is_trading_day() is False:
        print("오늘은 장이 열리지 않음 → 종료"); return
    if not args.once and now.strftime("%H:%M") >= "15:21":
        # 작업 스케줄러가 놓친 실행을 늦게 돌린 경우 (장 마감 뒤 PC 를 켬) → 아무것도 안 함
        print("이미 장이 끝나 오늘 당일단타는 끝 → 종료"); return
    cfg = load_config()
    sb = Supabase() if enabled() and not args.dry_run else None
    try:
        listing = DataStore(data_dir(cfg)).load("listing")
    except Exception:  # noqa: BLE001
        listing = None
    if (listing is None or listing.empty) and sb:
        # GitHub(앱 '종목찾기' 버튼)처럼 PC 데이터가 없는 곳: 앱용 종목 상세 표에서 종목 목록만
        rows, off = [], 0
        while True:                                                   # 한 번에 1000행 제한 → 나눠 받기
            part = sb.select("stock_details", {"select": "code,name,market", "order": "code",
                                               "limit": "1000", "offset": str(off)})
            rows += part or []
            if not part or len(part) < 1000:
                break
            off += 1000
        listing = pd.DataFrame(rows)
    if listing is None or listing.empty:
        sys.exit("종목 목록(listing)이 없습니다 — 먼저 4_daily.bat 로 데이터를 받아 두세요")
    job = (lambda **kw: _job(sb, **kw)) if args.once and sb else (lambda **kw: None)
    job(status="running", started=_now().strftime("%H:%M"))
    if sb is None and not args.dry_run:
        print("⚠ SUPABASE_URL / SUPABASE_SERVICE_KEY 가 없어 앱에 발행하지 않고 화면에만 보여줍니다")
    kc = cfg.get("kis", {})
    try:
        kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
        run = Runner(sb, kis, listing, args.top, args.workers, runner="github" if args.once else "pc")
        run.until = args.until
    except Exception as e:  # noqa: BLE001 — 앱 [종목찾기] 에 실패 이유를 보여줌
        job(status="failed", finished=_now().strftime("%H:%M"), error=str(e)[:200])
        raise
    while _now().strftime("%H:%M") < "09:00" and not args.once:
        print(f"{_now():%H:%M:%S} 장 시작 대기..."); time.sleep(20)
    p = None
    late = not args.once and _now().strftime("%H:%M") >= args.until      # 10:00 뒤에 켠 경우: 고정 종목 추적만
    while not late:
        t0 = time.time()
        try:
            p = run.step()
            run.publish(p)
            print(f"{p['time']} 후보 {p['scanned']} · 충족 {p['counts']['진입 조건 충족']} · 대기 {p['counts']['진입 대기']}"
                  f" · 관찰 {p['counts']['관찰']} ({time.time() - t0:.0f}초)")
            for r in p["items"][:5]:
                print(f"   {r['rank']:>2}. {r['name']:<12} {r['score']:5.1f}점 {r['type']:<3} {r['status']:<8}"
                      f" 현재 {r['price']:>9,.0f} 손절 {r['stop']:>9,.0f} 1차 {r['t1']:>9,.0f} (+{r.get('t1_pct', 0)}%)")
        except Exception as e:  # noqa: BLE001
            print(f"⚠ 이번 회차 실패: {e}")
        if args.once or _now().strftime("%H:%M") >= args.until:
            break
        time.sleep(max(5, args.every - (time.time() - t0)))
    # 고정(충족) 종목은 15:20 까지 계속 추적 → 결과가 나오면 매매일지에 기록
    if not args.once and run.track.any_open():
        print(f"새 종목 찾기 끝 → 고정 종목 {len(run.track.codes())}개 15:20 까지 추적")
        while run.track.any_open() and _now().strftime("%H:%M") < "15:21":
            t0 = time.time()
            try:
                p = run.track_step()
                run.publish(p)
            except Exception as e:  # noqa: BLE001
                print(f"⚠ 추적 실패: {e}")
            time.sleep(max(5, args.every - (time.time() - t0)))
    run.save_signals()
    job(status="done" if p else "failed", finished=_now().strftime("%H:%M"), found=len((p or {}).get("items") or []))
    if sb and p and not args.once:
        try:
            p["closed"] = True
            run.publish(p)
        except Exception:  # noqa: BLE001
            pass
    print(f"끝 — 오늘 신호 {len(run.signals)}건 (저녁 배치가 결과를 매겨 '검증' 에 올립니다)")


if __name__ == "__main__":
    main()
