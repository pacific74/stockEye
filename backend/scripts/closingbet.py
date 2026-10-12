"""종가배팅 — 평일 오후 PC 에서 실행 (scripts_win/16_closingbet.bat). 14:50~15:20 동안 1분마다:

  1) 네이버 지금 시세로 전 종목 → 오늘 거래대금 상위 TOP + 관심 탭 종목 (보통주) · 업종 평균 등락
  2) 후보마다 KIS 현재가(오늘 고가·저가·누적 거래량·거래대금 → VWAP) + 오늘 1분봉(장 후반 매수세) + 어제까지 일봉(PC 데이터)
  3) engine.closingbet 로 점수·갭 위험·매수 범위·다음 날 목표·손절 → 상위 20개를 Supabase system_status 'closingbet' 에 발행
     (앱 '관심 > 종가배팅' 탭과 메인)
  4) 15:20 이후 마지막 회차의 '매수 후보' 점수 상위 3 → Storage closingbet/signals/YYYY-MM-DD.json
     → 다음 날 저녁 배치가 그날 종가 매수 · 다음 날 오전 매도 결과를 매겨 '검증' 에 누적

  python -m scripts.closingbet                    # 기본: 지금부터 15:20 까지
  python -m scripts.closingbet --once             # 한 번만 (장중 아무 때나 시험)
  python -m scripts.closingbet --cloud            # GitHub 예약 실행 (PC 꺼져도): Storage 에서 일봉·종목 목록 받아서
필요한 환경변수: KIS_APP_KEY · KIS_APP_SECRET · SUPABASE_URL · SUPABASE_SERVICE_KEY (선택 NAVER_HUB_ID · NAVER_HUB_SECRET)
⚠ 주문은 하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time

import pandas as pd

log = logging.getLogger("stockeye.closingbet")
SHOW, PICK = 20, 3


def _now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)


class Runner:
    def __init__(self, sb, kis, listing: pd.DataFrame, ohlcv: pd.DataFrame, sectors: pd.DataFrame | None, top: int = 80):
        from stockeye.engine.nextday import common_stock
        from scripts.daytrade import watch_codes
        self.sb, self.kis, self.top = sb, kis, top
        lst = listing.drop_duplicates("code", keep="last")
        self.names = dict(zip(lst["code"], lst["name"]))
        self.market = dict(zip(lst["code"], lst["market"])) if "market" in lst else {}
        self.admin = set(lst.loc[lst["is_admin"].astype(bool), "code"]) if "is_admin" in lst else set()
        self.codes = [c for c in lst["code"] if common_stock(c, self.names.get(c, ""))]
        self.sector = dict(zip(sectors["code"], sectors["sector"])) if sectors is not None and len(sectors) else {}
        self.watch = watch_codes(sb) if sb else set()
        self.day = _now().strftime("%Y-%m-%d")
        oh = ohlcv[ohlcv["date"] < pd.Timestamp(self.day)]
        last = sorted(oh["date"].unique())[-70:]
        self.hist = {c: g.sort_values("date").reset_index(drop=True) for c, g in oh[oh["date"].isin(last)].groupby("code")}
        self.bars: dict[str, pd.DataFrame] = {}
        self.news: dict[str, str | None] = {}

    def _news(self, code):
        if code not in self.news:
            from stockeye.data import naver_news
            from stockeye.analysis.news_flags import judge
            self.news[code] = judge(naver_news.fetch(self.names.get(code, code), days=2))["level"] if naver_news.enabled() else None
        return self.news[code]

    def _bars(self, code, hhmmss):
        old = self.bars.get(code)
        try:
            new = self.kis.minute_bars_day(code, "090000", hhmmss) if old is None or old.empty else self.kis.minute_bars(code, hhmmss)
        except Exception:  # noqa: BLE001
            return old
        b = new if old is None or old.empty else pd.concat([old, new]).drop_duplicates("time", keep="last")
        self.bars[code] = b.sort_values("time").reset_index(drop=True)
        return self.bars[code]

    def step(self) -> dict:
        from stockeye.data.sources import naver_live
        from stockeye.engine import closingbet as cb
        now = _now()
        snap = naver_live.stocks(self.codes)
        if snap.empty:
            raise RuntimeError("네이버 시세를 받지 못함")
        snap["sector"] = snap["code"].map(self.sector)
        sec_chg = snap.groupby("sector")["chg_pct"].mean().to_dict()
        snap = snap.set_index("code")
        idx = naver_live.indices()
        idx_chg = {r["code"]: float(r["chg_pct"]) for _, r in idx.iterrows()} if not idx.empty else {}
        top = snap.sort_values("value", ascending=False).head(self.top).index.tolist()
        cands = list(dict.fromkeys(top + [c for c in self.watch if c in snap.index]))
        res = []
        for code in cands:
            daily = self.hist.get(code)
            if daily is None or len(daily) < 30:
                continue
            try:
                q = self.kis.price(code)
            except Exception:  # noqa: BLE001
                continue
            vol, value = q["volume"], q["value"]
            today = {"open": q["open"], "high": q["high"], "low": q["low"], "close": q["price"], "volume": vol,
                     "value": value, "vwap": value / vol if vol > 0 else None, "prev_close": q["prev_close"] or None}
            ctx = {"idx_chg": idx_chg.get(self.market.get(code, "KOSPI")), "sector_chg": sec_chg.get(self.sector.get(code)),
                   "danger": "관리종목" if code in self.admin else None, "now": now, "news_level": None}
            r = cb.evaluate(daily, today, None, ctx)
            if r["score"] >= 60 and not r["excluded"]:                   # 될 만한 종목만 분봉·뉴스 (API 아끼기)
                ctx["news_level"] = self._news(code)
                r = cb.evaluate(daily, today, self._bars(code, now.strftime("%H%M%S")), ctx)
            r.update({"code": code, "name": self.names.get(code, code), "atr": round(cb.atr_pct(daily), 4)})
            res.append(r)
        order = {"매수 후보": 0, "우선 관찰": 1, "관찰": 2, "대상 아님": 3, "진입 금지": 4}
        res.sort(key=lambda r: (order.get(r["status"], 5), -r["score"]))
        keep = [r for r in res if r["status"] in ("매수 후보", "우선 관찰", "관찰")][:SHOW]
        if len(keep) < 5:
            keep += [r for r in sorted(res, key=lambda r: -r["score"]) if r not in keep][:5 - len(keep)]
        for i, r in enumerate(keep, 1):
            r["rank"] = i
        counts = {s: sum(r["status"] == s for r in res) for s in order}
        final = now.strftime("%H:%M") >= "15:20"
        picks = [r for r in res if r["status"] == "매수 후보"][:PICK]
        return {"date": self.day, "time": now.strftime("%H:%M"), "version": cb.VERSION, "scanned": len(res),
                "counts": counts, "items": keep, "final": final, "idx_chg": idx_chg,
                "picks": [{k: r.get(k) for k in ("code", "name", "score", "type", "entry", "stop", "t1", "t2", "atr", "gap")}
                          | {"date": self.day} for r in picks]}

    def publish(self, p):
        if self.sb:
            from stockeye.cloud import publish as pub
            pub.publish_status(self.sb, "closingbet", p)

    def save_picks(self, p):
        if self.sb and p and p.get("picks"):
            self.sb.upload(f"closingbet/signals/{self.day}.json",
                           json.dumps(p["picks"], ensure_ascii=False, default=str).encode("utf-8"), "application/json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", default="15:21")
    ap.add_argument("--every", type=int, default=60)
    ap.add_argument("--top", type=int, default=80)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cloud", action="store_true", help="GitHub: Supabase Storage 에서 일봉·종목 목록·업종을 받아 씀")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)
    from stockeye.config import load_config, data_dir
    from stockeye.data.store import DataStore
    from stockeye.data.sources.kis_source import KISClient
    from stockeye.data.sources import naver_live
    from stockeye.cloud.client import Supabase, enabled
    if _now().weekday() >= 5 or naver_live.is_trading_day() is False:
        print("오늘은 장이 열리지 않음 → 종료"); return
    cfg = load_config()
    store = DataStore(data_dir(cfg))
    if args.cloud:
        # PC 데이터가 없는 곳: 저녁 배치가 올려 둔 원본 데이터 중 필요한 것만 (바뀐 조각만 받음)
        from stockeye.cloud.sync import DataSync
        got = DataSync(store, Supabase()).pull(("listing", "ohlcv", "sectors"))
        print(f"Storage → 데이터 받기: {', '.join(got) or '바뀐 것 없음 (캐시 사용)'}")
    listing, ohlcv = store.load("listing"), store.load("ohlcv")
    if listing is None or listing.empty or ohlcv is None or ohlcv.empty:
        sys.exit("종목 목록·일봉이 없습니다 — 먼저 4_daily.bat 로 데이터를 받아 두세요")
    sb = Supabase() if enabled() and not args.dry_run else None
    kc = cfg.get("kis", {})
    kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
    run = Runner(sb, kis, listing, ohlcv, store.load("sectors"), args.top)
    while _now().strftime("%H:%M") < "14:50" and not args.once:
        print(f"{_now():%H:%M:%S} 14:50 대기..."); time.sleep(30)
    p = None
    while True:
        t0 = time.time()
        try:
            p = run.step()
            run.publish(p)
            c = p["counts"]
            print(f"{p['time']} 후보 {p['scanned']} · 매수 후보 {c['매수 후보']} · 우선 관찰 {c['우선 관찰']} · 관찰 {c['관찰']}"
                  f" ({time.time() - t0:.0f}초)")
            for r in p["items"][:5]:
                print(f"   {r['rank']:>2}. {r['name']:<12} {r['score']:5.1f}점 {r['status']:<6} 갭위험 {r['gap']['grade']}"
                      f" 종가 {r['price']:>9,.0f} 손절 {r['stop']:>9,.0f} 1차 {r['t1']:>9,.0f}")
        except Exception as e:  # noqa: BLE001
            print(f"⚠ 이번 회차 실패: {e}")
        if args.once or _now().strftime("%H:%M") >= args.until:
            break
        time.sleep(max(5, args.every - (time.time() - t0)))
    if p and p.get("final"):
        run.save_picks(p)
        print(f"오늘 종가배팅 매수 후보 {len(p['picks'])}개 저장 (다음 날 저녁 배치가 결과를 매깁니다)")


if __name__ == "__main__":
    main()
