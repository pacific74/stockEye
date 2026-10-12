"""당일단타 — 평일 아침 PC 에서 실행 (scripts_win/14_daytrade.bat). 09:00~10:30 동안 1분마다:

  1) 네이버 지금 시세로 전 종목 → 오전 누적 거래대금 상위 TOP + 관심 탭 종목 (보통주만)
  2) 후보마다 KIS 1분봉(처음엔 09:00부터, 그다음엔 최근 30개만) · 점수가 될 만한 종목은 호가(스프레드)
  3) engine.daytrade 로 점수·필수 제외·돌파/눌림목 신호·손절·목표 → 상위 20개를 Supabase system_status 'daytrade' 에 발행
     (앱 '관심 > 당일단타' 탭과 메인이 1분마다 읽음)
  4) '진입 조건 충족' 이 처음 뜬 종목은 신호로 기록 → Storage daytrade/signals/YYYY-MM-DD.json
     → 저녁 배치(cloud_daily)가 그날 1분봉으로 결과(1·2차 익절·손절·장 마감 청산)를 매겨 '검증' 에 누적

  python -m scripts.daytrade                 # 기본: 지금부터 10:30 까지
  python -m scripts.daytrade --until 11:00 --every 60 --top 100
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
    def __init__(self, sb, kis, listing: pd.DataFrame, top: int = 100):
        from stockeye.engine.nextday import common_stock
        self.sb, self.kis, self.top = sb, kis, top
        lst = listing.drop_duplicates("code", keep="last")
        self.names = dict(zip(lst["code"], lst["name"]))
        self.market = dict(zip(lst["code"], lst["market"])) if "market" in lst else {}
        self.admin = set(lst.loc[lst["is_admin"].astype(bool), "code"]) if "is_admin" in lst else set()
        self.codes = [c for c in lst["code"] if common_stock(c, self.names.get(c, ""))]
        self.watch = watch_codes(sb) if sb else set()
        self.bars: dict[str, pd.DataFrame] = {}
        self.news: dict[str, str | None] = {}
        self.spread: dict[str, tuple[float, float | None]] = {}     # code → (받은 시각, 스프레드)
        self.adr: dict[str, float | None] = {}                       # code → 평소 하루 변동폭 (하루 한 번)
        self.signals: dict[tuple, dict] = {}
        self.day = _now().strftime("%Y-%m-%d")

    def _news(self, code: str) -> str | None:
        if code not in self.news:
            from stockeye.data import naver_news
            from stockeye.analysis.news_flags import judge
            self.news[code] = judge(naver_news.fetch(self.names.get(code, code), days=2))["level"] if naver_news.enabled() else None
        return self.news[code]

    def _adr(self, code: str) -> float | None:
        if code not in self.adr:
            from stockeye.engine import daytrade as dt
            try:
                d = self.kis.daily(code)
                d = d[d["date"] < pd.Timestamp(self.day)]                 # 오늘(장중) 봉 제외
                self.adr[code] = dt.adr(d)
            except Exception as e:  # noqa: BLE001
                log.debug("일봉 실패 %s: %s", code, e)
                self.adr[code] = None
        return self.adr[code]

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
        snap = naver_live.stocks(self.codes)
        if snap.empty:
            raise RuntimeError("네이버 시세를 받지 못함")
        snap = snap.set_index("code")
        idx = naver_live.indices()
        idx_chg = {r["code"]: float(r["chg_pct"]) for _, r in idx.iterrows()} if not idx.empty else {}
        top = snap.sort_values("value", ascending=False).head(self.top).index.tolist()
        cands = list(dict.fromkeys(top + [c for c in self.watch if c in snap.index]))
        res = []
        for code in cands:
            b = self._bars(code, hhmmss)
            if b is None or b.empty:
                continue
            q = snap.loc[code]
            prev = q["close"] / (1 + q["chg_pct"] / 100) if q["chg_pct"] > -100 else None
            market = self.market.get(code)
            ctx = {"name": self.names.get(code, code), "prev_close": prev, "now": now,
                   "idx_chg": idx_chg.get(market or "KOSPI", idx_chg.get("KOSPI", 0.0)),
                   "value": float(b["value"].iloc[-1]) if "value" in b and b["value"].iloc[-1] > 0 else float(q["value"]),
                   "danger": "관리종목" if code in self.admin else None,
                   "spread": (self.spread.get(code) or (0, None))[1], "news_level": None}
            r = dt.evaluate(b, ctx)
            # 점수가 될 만한 종목만 호가·뉴스 (API 아끼기) → 다시 계산
            if r["score"] >= 60 and not r["excluded"]:
                t0, sp = self.spread.get(code) or (0, None)
                if time.time() - t0 > 120:
                    try:
                        sp = self.kis.asking(code)["spread"]
                    except Exception:  # noqa: BLE001
                        sp = None
                    self.spread[code] = (time.time(), sp)
                ctx.update({"spread": sp, "news_level": self._news(code), "adr": self._adr(code)})
                r = dt.evaluate(b, ctx)
            r.update({"code": code, "name": self.names.get(code, code)})
            res.append(r)
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
        return {"date": self.day, "time": now.strftime("%H:%M"), "version": dt.VERSION, "scanned": len(res),
                "counts": counts, "items": keep, "signals": list(self.signals.values()), "idx_chg": idx_chg}

    def publish(self, payload: dict) -> None:
        if not self.sb:
            return
        from stockeye.cloud import publish as pub
        pub.publish_status(self.sb, "daytrade", payload)

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
    ap.add_argument("--until", default="10:30")
    ap.add_argument("--every", type=int, default=60, help="초")
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="발행하지 않고 화면에만")
    args = ap.parse_args()
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
    if not args.once and now.strftime("%H:%M") >= args.until:
        # 작업 스케줄러가 놓친 실행을 늦게 돌린 경우 (PC 를 10:30 넘어 켬) → 아무것도 안 함
        print(f"이미 {args.until} 이 지나 오늘 당일단타는 끝 → 종료"); return
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
    kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
    run = Runner(sb, kis, listing, args.top)
    while _now().strftime("%H:%M") < "09:00" and not args.once:
        print(f"{_now():%H:%M:%S} 장 시작 대기..."); time.sleep(20)
    p = None
    while True:
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
