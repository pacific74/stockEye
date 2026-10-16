"""상한가포착 — 평일 장중 PC 에서 실행 (scripts_win/19_limitcatch.bat). 09:05~15:20 동안 1분마다:

  1) KIS 등락률 순위 (상승률 상위 30, 한 번 호출) → 오늘 +20% 이상 보통주
     (순위 조회가 안 되면 네이버 전 종목 시세로 대신 — 요청이 많아서 5분에 한 번만)
     업종 동반은 1시간마다 올라오는 업종 강도(system_status 'sectors_live')를 10분마다 읽어 씀 (전 종목 시세를 따로 받지 않음)
  2) 대상마다 KIS 현재가(상한가·상장주식 수·종목 상태) + 호가(상한가 매수잔량·총 잔량) + 오늘 1분봉(도달·풀림)
     + 어제까지 일봉(PC 데이터) + 뉴스(거래대금 100억↑만, 하루 한 번)
  3) engine.limitcatch 로 1단계(강세 후보)·2단계(매수 검토) 판정 → Supabase system_status 'limitcatch'
     (앱 메인 '상한가포착' · '관심 > 상한가포착' 탭)
  4) 1분마다 대상 종목의 호가·체결을 기록 (data/limitcatch/ticks_날짜.jsonl) — 과거 잔량 데이터가 없어서 이 기록으로만
     잔량 항목을 검증할 수 있음. 장 마감 뒤 Storage limitcatch/ticks/날짜.jsonl.gz 로 올림
  5) 15:20 이후 마지막 회차 → Storage limitcatch/signals/날짜.json (그날 처음 '매수 검토'가 된 시각·가격 + 마지막 목록)
     → 다음 날 저녁 배치가 다음 날 시가 매도·09:30 청산 결과를 매겨 '검증' 에 누적

  python -m scripts.limitcatch                    # 기본: 지금부터 15:21 까지
  python -m scripts.limitcatch --once             # 한 번만
  python -m scripts.limitcatch --cloud --once     # 앱 [종목찾기] → GitHub 에서 한 번 (PC 꺼져도)
필요한 환경변수: KIS_APP_KEY · KIS_APP_SECRET · SUPABASE_URL · SUPABASE_SERVICE_KEY (선택 NAVER_HUB_ID · NAVER_HUB_SECRET)
⚠ 주문은 하지 않는다.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd

log = logging.getLogger("stockeye.limitcatch")

BANNER = """==============================================================
 StockEye [상한가포착 단독]  (19_limitcatch.bat · 매일 자동은 22_intraday.bat 통합 실행)
  09:05~15:20  1분마다 +20% 이상 종목의 상한가 잠김·풀림·잔량 계산 → 앱 하단 '당일매매'
  '매수 검토' 종목은 고정 → 다음 날 09:30 까지 목표·손절 추적 (전날 종목도 이어서)
  1분 호가 기록을 남기고 장 마감 뒤 올림 · 주문은 하지 않음
  창을 닫으면 멈춤 (닫아도 되는 때: 15:21 이후)
=============================================================="""
SHOW = 30
PRE_MAX_CODES = 20         # 상한가 예비: 1분에 자세히 보는 +10~20% 종목 수 (등락률 높은 순)
PRE_SHOW = 10              # 앱에 보이는 상한가 예비·관찰 수
PRE_VALUE = 50e8          # 근사 거래대금(가격×거래량) 50억 미만은 자세히 안 봄 (100억 기준은 KIS 값으로 다시 확인)
DANGER_STATUS = {"51": "관리종목", "52": "투자위험", "53": "투자경고", "58": "거래정지", "59": "단기과열"}
DANGER_WARN = {"02": "투자경고", "03": "투자위험"}


def _now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)


def danger_of(q: dict, admin: bool) -> str | None:
    """종목 상태 → 제외 사유 (투자주의는 +20% 종목에 흔해서 제외하지 않음)"""
    if admin:
        return "관리종목"
    if q.get("halted"):
        return "거래정지"
    return DANGER_STATUS.get(str(q.get("status_code") or "")) or DANGER_WARN.get(str(q.get("warn_code") or ""))


def sector_of(live: dict | None, name: str | None) -> dict | None:
    """1시간마다 올라오는 업종 강도(sectors_live) → 그 업종의 상승 종목 비율 · 거래대금 가중 등락률"""
    if not live or not name:
        return None
    g = next((x for x in live.get("groups") or [] if x.get("group") == name), None)
    if not g or not g.get("n"):
        return None
    return {"up_ratio": round(g.get("up", 0) / g["n"], 3), "chg_pct": g.get("chg_pct"), "n": g["n"],
            "at": live.get("time")}


class Runner:
    def __init__(self, sb, kis, listing: pd.DataFrame, ohlcv: pd.DataFrame, sectors: pd.DataFrame | None,
                 workers: int = 8, runner: str = "pc", log_dir: Path | None = None):
        from stockeye.engine.nextday import common_stock
        self.sb, self.kis, self.workers, self.runner = sb, kis, workers, runner
        lst = listing.drop_duplicates("code", keep="last")
        self.names = dict(zip(lst["code"], lst["name"]))
        self.admin = set(lst.loc[lst["is_admin"].astype(bool), "code"]) if "is_admin" in lst else set()
        self.codes = [c for c in lst["code"] if common_stock(c, self.names.get(c, ""))]
        self.sector = dict(zip(sectors["code"], sectors["sector"])) if sectors is not None and len(sectors) else {}
        self.day = _now().strftime("%Y-%m-%d")
        oh = ohlcv[ohlcv["date"] < pd.Timestamp(self.day)]
        last = sorted(oh["date"].unique())[-70:]
        oh = oh[oh["date"].isin(last)]
        self.hist = {c: g.sort_values("date").reset_index(drop=True) for c, g in oh.groupby("code")}
        self.bars: dict[str, pd.DataFrame] = {}
        self.book_hist: dict[str, list[dict]] = {}
        self.news: dict[str, dict | None] = {}
        self.first_buy: dict[str, dict] = {}       # 그날 처음 '매수 검토'가 된 시각·가격
        self.pre_first: dict[str, dict] = {}       # 상한가 예비 (2026-10-16): 그날 처음 '상한가 예비'가 된 시각·가격 (검증 기록)
        self.ever: set[str] = set()                # 한 번이라도 +20% 이상이었던 종목 (밀려도 '조건 무효' 로 계속 보여줌)
        self.ticks: list[dict] = []
        from stockeye.cloud.recommend import IntradayRecorder
        self.rec = IntradayRecorder(sb, "limitcatch", runner)        # 검증용 추천 기록 ('매수 검토' 첫 시점)
        from stockeye.trading.intraday_track import Tracker
        self.track = Tracker(sb, "limitcatch", self.day)             # 당일매매: 매수 검토 종목 고정 → 다음 날 09:30 까지 추적
        self.sec_live, self._sec_at = None, 0.0           # 업종 강도 (10분마다 다시 읽음)
        self._snap_at, self._snap = 0.0, None             # 네이버 전 종목 시세 (순위 조회 실패 때만 · 5분에 한 번)
        self.log_path = (log_dir / f"ticks_{self.day}.jsonl") if log_dir else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _sectors(self) -> dict | None:
        if self.sb and time.time() - self._sec_at > 600:
            try:
                rows = self.sb.select("system_status", {"select": "payload", "key": "eq.sectors_live"})
                p = rows[0]["payload"] if rows else None
                self.sec_live = p if p and p.get("date") == self.day else None
            except Exception as e:  # noqa: BLE001
                log.debug("업종 강도 읽기 실패: %s", e)
            self._sec_at = time.time()
        return self.sec_live

    def discover(self) -> pd.DataFrame:
        """오늘 +20% 이상 후보: KIS 등락률 순위 1번 → 실패하면 네이버 전 종목 (5분에 한 번)"""
        try:
            r = self.kis.fluctuation_rank()
            if r is not None and len(r):
                return r[r["code"].isin(set(self.codes))].set_index("code")
        except Exception as e:  # noqa: BLE001
            log.warning("KIS 등락률 순위 실패 → 네이버 시세로 대신: %s", e)
        if self._snap is None or time.time() - self._snap_at > 300:
            from stockeye.data.sources import naver_live
            snap = naver_live.stocks(self.codes)
            if snap.empty:
                raise RuntimeError("등락률 순위·네이버 시세 모두 받지 못함")
            self._snap, self._snap_at = snap.set_index("code"), time.time()
        return self._snap

    def _news(self, code: str) -> dict | None:
        if code not in self.news:
            from stockeye.data import naver_news
            from stockeye.analysis.news_flags import judge
            from stockeye.engine.limitcatch import news_detail
            if not naver_news.enabled():
                self.news[code] = None
            else:
                items = naver_news.fetch(self.names.get(code, code), days=3)
                self.news[code] = news_detail(items, judge(items)["level"], self.day)
        return self.news[code]

    def _bars(self, code: str, hhmmss: str) -> pd.DataFrame | None:
        old = self.bars.get(code)
        try:
            new = self.kis.minute_bars_day(code, "090000", hhmmss) if old is None or old.empty else self.kis.minute_bars(code, hhmmss)
        except Exception:  # noqa: BLE001
            return old
        b = new if old is None or old.empty else pd.concat([old, new]).drop_duplicates("time", keep="last")
        b = b[b["time"].dt.strftime("%H%M%S") >= "090000"].sort_values("time").reset_index(drop=True)
        self.bars[code] = b
        return b

    def one(self, code: str, now: pd.Timestamp, sec: dict | None) -> dict | None:
        from stockeye.engine import limitcatch as lc
        daily = self.hist.get(code)
        if daily is None or len(daily) < 20:
            return None
        try:
            q = self.kis.price(code)
        except Exception:  # noqa: BLE001
            return None
        try:
            book = self.kis.asking(code)
        except Exception:  # noqa: BLE001
            book = None
        bars = self._bars(code, now.strftime("%H%M%S"))
        today = {"open": q["open"], "high": q["high"], "low": q["low"], "close": q["price"], "volume": q["volume"],
                 "value": q["value"], "prev_close": q["prev_close"] or None, "listed_shares": q.get("listed_shares"),
                 "upper_limit": q.get("upper_limit")}
        nd = None
        if q["value"] >= lc.MIN_VALUE and q["change_pct"] >= lc.MIN_CHG:
            try:
                nd = self._news(code)
            except Exception:  # noqa: BLE001
                nd = None
        ctx = {"news": nd, "sector": sector_of(sec, self.sector.get(code)), "danger": danger_of(q, code in self.admin),
               "book_hist": self.book_hist.get(code), "now": now}
        r = lc.evaluate(daily, today, bars, book, ctx)
        bm = r.get("book") or {}
        tick = {"t": now.strftime("%H:%M"), "code": code, "price": q["price"], "chg": r["chg_pct"],
                "value": round(q["value"]), "locked": r["lock"]["locked_now"], "bid_qty": bm.get("bid_qty"),
                "total_bid": bm.get("total_bid"), "total_ask": bm.get("total_ask"),
                "vol1": float(bars["volume"].iloc[-1]) if bars is not None and len(bars) else None,
                "releases": r["lock"]["releases"], "score": r["score"]}
        self.book_hist.setdefault(code, []).append({"bid_qty": bm.get("bid_qty"), "locked": r["lock"]["locked_now"]})
        self.book_hist[code] = self.book_hist[code][-10:]
        self.ticks.append(tick)
        r.update({"code": code, "name": self.names.get(code, code), "sector": self.sector.get(code), "time": now.strftime("%H:%M")})
        if r["status"] == "매수 검토" and code not in self.first_buy:
            self.first_buy[code] = {k: r.get(k) for k in ("code", "name", "time", "score", "group", "entry", "stop",
                                                           "loss_pct", "limit", "prev_close", "chg_pct", "value")} \
                | {"date": self.day, "releases_at": r["lock"]["releases"], "reach_time": r["lock"]["reach_time"],
                   "bid_value_ratio": bm.get("bid_value_ratio"), "parts": r["parts"]}
            log.info("★ 매수 검토 %s %s %s %s원 (점수 %.1f)", r["time"], r["name"], r["group"], f"{r['entry']:,.0f}", r["score"])
        return r

    def discover_pre(self, found: pd.DataFrame) -> pd.DataFrame:
        """상한가 예비 대상 찾기: 전체 순위(상위 30)는 +20%↑ 가 채우는 날이 많아 코스피·코스닥 순위를 따로 더 받음 (1분에 2번)"""
        parts = [found]
        for mk in ("0001", "1001"):
            try:
                r = self.kis.fluctuation_rank(mk)
                if r is not None and len(r):
                    parts.append(r[r["code"].isin(set(self.codes))].set_index("code"))
            except Exception as e:  # noqa: BLE001
                log.debug("등락률 순위(%s) 실패: %s", mk, e)
        df = pd.concat(parts)
        return df[~df.index.duplicated(keep="first")]

    def one_pre(self, code: str, now: pd.Timestamp, sec: dict | None) -> dict | None:
        """상한가 예비 1종목 (+10~20%): 지금 시세 · 호가 · 1분봉 → LP 점수"""
        from stockeye.engine import limit_pre as lp
        from stockeye.engine.uplimit import limit_price
        daily = self.hist.get(code)
        if daily is None or len(daily) < 20:
            return None
        try:
            q = self.kis.price(code)
        except Exception:  # noqa: BLE001
            return None
        try:
            book = self.kis.asking(code)
        except Exception:  # noqa: BLE001
            book = None
        bars = self._bars(code, now.strftime("%H%M%S"))
        hm = now.strftime("%H:%M")
        nd = None
        if lp.PRE_MIN <= q["change_pct"] < lp.PRE_MAX and q["value"] >= lp.min_value(hm):
            try:
                nd = self._news(code)
            except Exception:  # noqa: BLE001
                nd = None
        ctx = {"news": nd, "sector": sector_of(sec, self.sector.get(code)), "danger": danger_of(q, code in self.admin),
               "now": now}
        r = lp.evaluate(daily, q, bars, book, ctx)
        if r["status"] not in ("상한가 예비", "관찰"):
            return None
        lim = q.get("upper_limit") or limit_price(q.get("prev_close") or 0)
        r.update({"code": code, "name": self.names.get(code, code), "sector": self.sector.get(code), "time": hm,
                  "prev_close": q.get("prev_close"), "limit": lim,
                  "news": (nd or {}).get("items") or []})
        if r["status"] == "상한가 예비":
            if code not in self.pre_first:
                self.pre_first[code] = {k: r.get(k) for k in ("code", "name", "time", "price", "chg_pct", "value", "score",
                                                               "parts", "limit", "prev_close", "accel", "vwap_gap",
                                                               "book_ratio", "limit_hits60")} | {"date": self.day}
                log.info("☆ 상한가 예비 %s %s %+.1f%% %s원 (점수 %.1f)", hm, r["name"], r["chg_pct"], f"{r['price']:,.0f}", r["score"])
            r["first_time"] = self.pre_first[code]["time"]
        return r

    def step(self) -> dict:
        from concurrent.futures import ThreadPoolExecutor
        from stockeye.engine import limitcatch as lc
        from stockeye.engine import limit_pre as lp
        now = _now()
        found = self.discover()
        sec = self._sectors()
        val = found["value"] if "value" in found else found["close"] * found["volume"]
        hot = found[(found["chg_pct"] >= lc.MIN_CHG) & (val >= PRE_VALUE)].index.tolist()
        self.ever |= set(hot)
        cands = list(dict.fromkeys(hot + sorted(self.ever) + self.track.codes()))  # 한 번 잡힌 종목은 밀려도 계속
        with ThreadPoolExecutor(self.workers) as ex:                   # 여러 종목 동시에 (KIS 초당 한도 안에서)
            res = [r for r in ex.map(lambda c: self.one(c, now, sec), cands) if r is not None]
        # 상한가 예비 (+10~20% 급등 초입 · 09:05~14:30 · 표시+기록만)
        pre = []
        if lp.in_window(now.strftime("%H:%M")):
            try:
                allf = self.discover_pre(found)
                v2 = allf["value"] if "value" in allf else allf["close"] * allf["volume"]
                pc = allf[(allf["chg_pct"] >= lp.PRE_MIN) & (allf["chg_pct"] < lp.PRE_MAX)
                          & (v2 >= lp.VALUE_AM * 0.8)].sort_values("chg_pct", ascending=False).index.tolist()[:PRE_MAX_CODES]
                with ThreadPoolExecutor(self.workers) as ex:
                    pre = [r for r in ex.map(lambda c: self.one_pre(c, now, sec), pc) if r is not None]
            except Exception as e:  # noqa: BLE001
                log.warning("상한가 예비 실패: %s", e)
        pre.sort(key=lambda r: (r["status"] != "상한가 예비", -r["score"]))
        self._write_ticks()
        order = {"매수 검토": 0, "강세 후보": 1, "관찰": 2, "조건 무효": 3, "대상 아님": 4, "제외": 5}
        res.sort(key=lambda r: (order.get(r["status"], 6), -r["score"]))
        keep = [r for r in res if r["status"] != "대상 아님"][:SHOW]
        for i, r in enumerate(keep, 1):
            r["rank"] = i
        counts = {s: sum(r["status"] == s for r in res) for s in order}
        final = now.strftime("%H:%M") >= lc.LAST_NEW
        # 당일매매: 처음 '매수 검토' 종목 고정 → 1분봉으로 상태·결과 갱신 (전날 잡힌 종목은 오늘 09:30 까지)
        self.track.add(res, now)
        score = {r["code"]: r["score"] for r in res}
        price = {r["code"]: r["price"] for r in res}
        for code in self.track.codes():
            b = self.bars.get(code)
            if b is None:
                b = self._bars(code, now.strftime("%H%M%S"))
            px = price.get(code) or (float(b["close"].iloc[-1]) if b is not None and len(b) else None)
            self.track.update(code, b, px, score.get(code), now)
        self.track.save()
        return {"date": self.day, "time": now.strftime("%H:%M"), "version": lc.VERSION, "scanned": len(res),
                "counts": counts, "groups": {"도달": sum(r["group"] == "도달" for r in keep),
                                             "미도달": sum(r["group"] == "미도달" for r in keep)},
                "items": keep, "final": final, "runner": self.runner,
                "first_buy": list(self.first_buy.values()), "tracked": self.track.view(),
                "pre": pre[:PRE_SHOW], "pre_version": lp.VERSION, "pre_first": list(self.pre_first.values())}

    def _write_ticks(self):
        if not self.log_path or not self.ticks:
            return
        with self.log_path.open("a", encoding="utf-8") as f:
            for t in self.ticks:
                f.write(json.dumps(t, ensure_ascii=False, default=str) + "\n")
        self.ticks = []

    def publish(self, p):
        if self.sb:
            from stockeye.cloud import publish as pub
            pub.publish_status(self.sb, "limitcatch", p)
            self.rec(self.day, p.get("items") or [], p.get("version"), p.get("time"))
            if len(p.get("pre_first") or []) != getattr(self, "_pre_saved", 0):   # 상한가 예비 새로 생기면 바로 저장
                try:
                    self.save_pre(p)
                    self._pre_saved = len(p.get("pre_first") or [])
                except Exception as e:  # noqa: BLE001
                    log.debug("상한가 예비 기록 저장 실패: %s", e)

    def save_signals(self, p):
        """마지막 회차: 처음 '매수 검토' 기록 + 마지막 목록(점수 구간별 검증용) → 다음 날 저녁 배치가 결과를 매김"""
        if not self.sb or not p:
            return
        key = f"limitcatch/signals/{self.day}.json"
        try:                                                   # 같은 날 여러 번 돌렸으면 (버튼·PC) 합침
            old = json.loads(self.sb.download(key) or b"{}")
        except Exception:  # noqa: BLE001
            old = {}
        fb = {r["code"]: r for r in old.get("first_buy", [])}
        for r in p.get("first_buy", []):
            fb.setdefault(r["code"], r)
        fields = ("code", "name", "status", "score", "group", "price", "chg_pct", "value", "limit", "prev_close",
                  "time_bucket", "stage1", "stage2", "parts")
        items = [{k: r.get(k) for k in fields} | {"lock": r.get("lock"), "date": self.day} for r in p.get("items", [])
                 if r["status"] in ("매수 검토", "강세 후보", "관찰", "조건 무효")]
        if old.get("is_final") and not p.get("final"):                # 마지막 회차 목록은 낮 버튼 실행으로 덮지 않음
            items = old.get("final", [])
        out = {"date": self.day, "time": p.get("time"), "first_buy": list(fb.values()), "final": items,
               "is_final": bool(p.get("final") or old.get("is_final"))}
        self.sb.upload(key, json.dumps(out, ensure_ascii=False, default=str).encode("utf-8"), "application/json")
        self.save_pre(p)

    def save_pre(self, p):
        """상한가 예비 첫 기록 → Storage limitcatch/pre/날짜.json (저녁 배치가 그날 일봉으로 도달·잠김을 매김)"""
        if not self.sb or not p.get("pre_first"):
            return
        key = f"limitcatch/pre/{self.day}.json"
        try:
            old = json.loads(self.sb.download(key) or b"{}")
        except Exception:  # noqa: BLE001
            old = {}
        rows = {r["code"]: r for r in old.get("rows", [])}
        for r in p["pre_first"]:
            rows.setdefault(r["code"], r)
        self.sb.upload(key, json.dumps({"date": self.day, "version": p.get("pre_version"), "rows": list(rows.values())},
                                       ensure_ascii=False, default=str).encode("utf-8"), "application/json")

    def upload_ticks(self):
        """1분 호가 기록 → Storage (gzip, 하루 수백 KB)"""
        if not self.sb or not self.log_path or not self.log_path.exists():
            return
        self.sb.upload(f"limitcatch/ticks/{self.day}.jsonl.gz", gzip.compress(self.log_path.read_bytes()), "application/gzip")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", default="15:21")
    ap.add_argument("--every", type=int, default=60)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cloud", action="store_true", help="GitHub: Supabase Storage 에서 일봉·종목 목록·업종을 받아 씀")
    args = ap.parse_args()
    print(BANNER, flush=True)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)
    from stockeye.config import load_config, data_dir
    from stockeye.data.store import DataStore
    from stockeye.data.sources.kis_source import KISClient
    from stockeye.data.sources import naver_live
    from stockeye.cloud.client import Supabase, enabled
    from scripts.closingbet import cloud_data
    if _now().weekday() >= 5 or naver_live.is_trading_day() is False:
        print("오늘은 장이 열리지 않음 → 종료"); return
    if not args.once and _now().strftime("%H:%M") >= "15:40":
        print("이미 장이 끝나 오늘 상한가포착은 끝 → 종료"); return
    cfg = load_config()
    store = DataStore(data_dir(cfg))
    if args.cloud:
        listing, ohlcv, sectors = cloud_data(Supabase())
    else:
        listing, ohlcv, sectors = store.load("listing"), store.load("ohlcv"), store.load("sectors")
    if listing is None or listing.empty or ohlcv is None or ohlcv.empty:
        sys.exit("종목 목록·일봉이 없습니다 — 먼저 4_daily.bat 로 데이터를 받아 두세요")
    sb = Supabase() if enabled() and not args.dry_run else None

    def job(**kw):                                                     # 앱 [종목찾기] 진행 상태
        if sb and args.once:
            try:
                from stockeye.cloud import publish as pub
                pub.publish_status(sb, "limitcatch_job", kw)
            except Exception:  # noqa: BLE001
                pass
    job(status="running", started=_now().strftime("%H:%M"))
    kc = cfg.get("kis", {})
    try:
        kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
        run = Runner(sb, kis, listing, ohlcv, sectors, args.workers, runner="github" if args.once else "pc",
                     log_dir=None if args.cloud else data_dir(cfg) / "limitcatch")
    except Exception as e:  # noqa: BLE001 — 앱 [종목찾기] 에 실패 이유를 보여줌
        job(status="failed", finished=_now().strftime("%H:%M"), error=str(e)[:200])
        raise
    while _now().strftime("%H:%M") < "09:05" and not args.once:
        print(f"{_now():%H:%M:%S} 09:05 대기..."); time.sleep(30)
    p = None
    while True:
        t0 = time.time()
        try:
            p = run.step()
            run.publish(p)
            c = p["counts"]
            print(f"{p['time']} 대상 {p['scanned']} · 매수 검토 {c['매수 검토']} · 강세 후보 {c['강세 후보']} · 관찰 {c['관찰']}"
                  f" · 조건 무효 {c['조건 무효']} ({time.time() - t0:.0f}초)")
            for r in p["items"][:5]:
                lk = r["lock"]
                print(f"   {r['rank']:>2}. {r['name']:<12} {r['score']:5.1f}점 {r['status']:<5} {r['group']}"
                      f" {r['chg_pct']:+.1f}% 풀림 {lk['releases']}회{' 잠김' if lk['locked_now'] else ''}")
        except Exception as e:  # noqa: BLE001
            print(f"⚠ 이번 회차 실패: {e}")
        if args.once or _now().strftime("%H:%M") >= args.until:
            break
        time.sleep(max(5, args.every - (time.time() - t0)))
    if p and (p.get("final") or p.get("first_buy")):
        try:
            run.save_signals(p)
            print(f"오늘 상한가포착 기록 저장 (매수 검토 {len(p['first_buy'])}개 · 다음 날 저녁 배치가 결과를 매깁니다)")
        except Exception as e:  # noqa: BLE001
            print(f"⚠ 기록 저장 실패: {e}")
    if not args.once:
        try:
            run.upload_ticks()
        except Exception as e:  # noqa: BLE001
            print(f"⚠ 호가 기록 올리기 실패: {e}")
    job(status="done" if p else "failed", finished=_now().strftime("%H:%M"), found=len((p or {}).get("items") or []))


if __name__ == "__main__":
    main()
