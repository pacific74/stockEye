"""한국투자증권(KIS) Open API.

준비:
  1. 한국투자증권 계좌 → KIS Developers(https://apiportal.koreainvestment.com) 에서 앱키 신청
  2. 환경변수:  setx KIS_APP_KEY 앱키   /   setx KIS_APP_SECRET 앱시크릿
     (모의투자 앱키를 쓰면 settings.yaml 의 kis.env 를 vps 로)

여기서 쓰는 것 (모두 '조회' API, 주문 기능은 넣지 않음):
  - 접근토큰 발급  POST /oauth2/tokenP           (하루 1회 정도로 재사용: data/.kis_token.json 에 캐시)
  - 현재가         FHKST01010100  /uapi/domestic-stock/v1/quotations/inquire-price
  - 종목별 프로그램매매추이(일별)  FHPPG04650201  /uapi/domestic-stock/v1/quotations/program-trade-by-stock-daily
  - 당일 1분봉     FHKST03010200  /uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice   (당일단타)
  - 과거 1분봉     FHKST03010230  /uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice  (당일단타 검증)
  - 호가           FHKST01010200  /uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn  (스프레드)

※ 본인 투자 목적의 개인 사용 기준. 시세를 타인에게 제공하는 서비스로 확장하면 별도 이용계약이 필요할 수 있음.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

BASE = {"prod": "https://openapi.koreainvestment.com:9443",
        "vps": "https://openapivts.koreainvestment.com:29443"}


class KISClient:
    def __init__(self, env: str = "prod", token_path: str | Path = "data/.kis_token.json",
                 calls_per_sec: float = 15):
        import requests
        self.s = requests.Session()
        self.env = env
        self.base = BASE[env]
        self.key = os.getenv("KIS_APP_KEY")
        self.secret = os.getenv("KIS_APP_SECRET")
        if not (self.key and self.secret):
            raise RuntimeError("KIS_APP_KEY / KIS_APP_SECRET 환경변수가 없습니다")
        self.token_path = Path(token_path)
        self.min_gap = 1.0 / calls_per_sec
        self._last = 0.0
        import threading
        self._lock = threading.Lock()          # 여러 종목을 동시에 받을 때도 초당 한도를 지키도록 (호출 시각 예약)
        self._next = 0.0
        self.token = self._token()

    # ---------------- 토큰 ----------------
    def _token(self) -> str:
        if self.token_path.exists():
            t = json.loads(self.token_path.read_text(encoding="utf-8"))
            if t.get("env") == self.env and pd.Timestamp(t["expires"]) > pd.Timestamp.now() + pd.Timedelta(hours=1):
                return t["token"]
        r = self.s.post(f"{self.base}/oauth2/tokenP", timeout=10, data=json.dumps(
            {"grant_type": "client_credentials", "appkey": self.key, "appsecret": self.secret}),
            headers={"content-type": "application/json"})
        if r.status_code != 200:
            raise RuntimeError(f"KIS 토큰 발급 실패 {r.status_code}: {r.text[:200]}")
        js = r.json()
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps({"env": self.env, "token": js["access_token"],
                                               "expires": js.get("access_token_token_expired")}), encoding="utf-8")
        return js["access_token"]

    def _get(self, path: str, tr_id: str, params: dict) -> dict:
        with self._lock:
            now = time.time()
            slot = max(now, self._next)
            self._next = slot + self.min_gap
        if slot > now:
            time.sleep(slot - now)
        if self.env == "vps" and tr_id[0] in "TJC":
            tr_id = "V" + tr_id[1:]
        headers = {"content-type": "application/json; charset=utf-8", "authorization": f"Bearer {self.token}",
                   "appkey": self.key, "appsecret": self.secret, "tr_id": tr_id, "custtype": "P"}
        for attempt in range(3):
            r = self.s.get(self.base + path, headers=headers, params=params, timeout=10)
            self._last = time.time()
            if r.status_code == 200:
                js = r.json()
                if js.get("rt_cd") == "0":
                    return js
                if "초당" in js.get("msg1", "") or js.get("msg_cd") == "EGW00201":   # 초당 거래건수 초과
                    time.sleep(1.0)
                    continue
                raise RuntimeError(f"KIS 오류 {js.get('msg_cd')}: {js.get('msg1')}")
            time.sleep(1.0)
        raise RuntimeError(f"KIS 요청 실패 {r.status_code}: {r.text[:200]}")

    def _post(self, path: str, tr_id: str, body: dict) -> dict:
        """주문용 POST. (주문은 재시도하지 않는다 — 중복 주문 방지)"""
        wait = self.min_gap - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        if self.env == "vps" and tr_id[0] in "TJC":
            tr_id = "V" + tr_id[1:]
        headers = {"content-type": "application/json; charset=utf-8", "authorization": f"Bearer {self.token}",
                   "appkey": self.key, "appsecret": self.secret, "tr_id": tr_id, "custtype": "P"}
        r = self.s.post(self.base + path, headers=headers, data=json.dumps(body), timeout=10)
        self._last = time.time()
        js = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200 or js.get("rt_cd") != "0":
            raise RuntimeError(f"KIS 주문 오류 {js.get('msg_cd')}: {js.get('msg1') or r.text[:200]}")
        return js

    # ---------------- 조회 ----------------
    def price(self, code: str) -> dict:
        js = self._get("/uapi/domestic-stock/v1/quotations/inquire-price", "FHKST01010100",
                       {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
        o = js["output"]
        num = lambda k: float(o.get(k) or 0)  # noqa: E731
        return {"code": code, "price": num("stck_prpr"), "change_pct": num("prdy_ctrt"),
                "open": num("stck_oprc"), "high": num("stck_hgpr"), "low": num("stck_lwpr"),
                "prev_close": num("stck_sdpr"),
                "volume": num("acml_vol"), "value": num("acml_tr_pbmn"), "sector": o.get("bstp_kor_isnm"),
                "per": num("per"), "pbr": num("pbr"), "time": pd.Timestamp.now().isoformat(timespec="seconds")}

    # ---------------- 당일단타용: 1분봉 · 호가 ----------------
    @staticmethod
    def _bars(rows, day: str | None = None) -> pd.DataFrame:
        df = pd.DataFrame(rows or [])
        if df.empty or "stck_cntg_hour" not in df:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume", "value"])
        f = lambda c: pd.to_numeric(df.get(c), errors="coerce")  # noqa: E731
        d = df["stck_bsop_date"] if "stck_bsop_date" in df else pd.Series([day] * len(df))
        out = pd.DataFrame({"time": pd.to_datetime(d.astype(str) + df["stck_cntg_hour"].astype(str).str.zfill(6),
                                                   format="%Y%m%d%H%M%S", errors="coerce"),
                            "open": f("stck_oprc"), "high": f("stck_hgpr"), "low": f("stck_lwpr"),
                            "close": f("stck_prpr"), "volume": f("cntg_vol"), "value": f("acml_tr_pbmn")})
        return out.dropna(subset=["time", "close"]).sort_values("time").reset_index(drop=True)

    def minute_bars(self, code: str, until: str = "153000") -> pd.DataFrame:
        """당일 1분봉 (until 시각부터 거꾸로 30개) — 주식당일분봉조회 FHKST03010200"""
        js = self._get("/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice", "FHKST03010200",
                       {"FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                        "FID_INPUT_HOUR_1": until, "FID_PW_DATA_INCU_YN": "Y"})
        return self._bars(js.get("output2"))

    def minute_bars_day(self, code: str, start: str = "090000", end: str = "153000", day: str | None = None,
                        max_calls: int = 14) -> pd.DataFrame:
        """start~end 1분봉 전부 (30개씩 거꾸로 이어 받기). day=YYYYMMDD 면 과거 날짜 (주식일별분봉조회 FHKST03010230 —
        실전 계좌 전용·보관 기간 제한. 안 되면 빈 표)"""
        parts, until = [], end
        for _ in range(max_calls):
            if day:
                js = self._get("/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice", "FHKST03010230",
                               {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code, "FID_INPUT_HOUR_1": until,
                                "FID_INPUT_DATE_1": day, "FID_PW_DATA_INCU_YN": "Y", "FID_FAKE_TICK_INCU_YN": ""})
                b = self._bars(js.get("output2"), day)
                b = b[b["time"].dt.strftime("%Y%m%d") == day]
            else:
                b = self.minute_bars(code, until)
            if b.empty:
                break
            parts.append(b)
            first = b["time"].iloc[0]
            if first.strftime("%H%M%S") <= start:
                break
            until = (first - pd.Timedelta(minutes=1)).strftime("%H%M%S")
        if not parts:
            return self._bars([])
        out = pd.concat(parts).drop_duplicates("time").sort_values("time")
        hm = out["time"].dt.strftime("%H%M%S")
        return out[(hm >= start) & (hm <= end)].reset_index(drop=True)

    def daily(self, code: str) -> pd.DataFrame:
        """최근 30거래일 일봉 (수정주가) — 주식현재가 일자별 FHKST01010400. 오늘(장중) 포함될 수 있음"""
        js = self._get("/uapi/domestic-stock/v1/quotations/inquire-daily-price", "FHKST01010400",
                       {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code, "FID_PERIOD_DIV_CODE": "D",
                        "FID_ORG_ADJ_PRC": "0"})
        df = pd.DataFrame(js.get("output") or [])
        if df.empty or "stck_bsop_date" not in df:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        f = lambda c: pd.to_numeric(df.get(c), errors="coerce")  # noqa: E731
        out = pd.DataFrame({"date": pd.to_datetime(df["stck_bsop_date"], format="%Y%m%d", errors="coerce"),
                            "open": f("stck_oprc"), "high": f("stck_hgpr"), "low": f("stck_lwpr"),
                            "close": f("stck_clpr"), "volume": f("acml_vol")})
        return out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)

    def asking(self, code: str) -> dict:
        """1호가 매도·매수 → 스프레드 (주식현재가 호가 FHKST01010200)"""
        js = self._get("/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn", "FHKST01010200",
                       {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
        o = js.get("output1") or {}
        ask, bid = float(o.get("askp1") or 0), float(o.get("bidp1") or 0)
        mid = (ask + bid) / 2
        return {"ask": ask, "bid": bid, "spread": (ask - bid) / mid if ask > 0 and bid > 0 and mid > 0 else None}

    def program_daily(self, code: str) -> pd.DataFrame:
        """종목별 프로그램 순매수 금액(일별, 최근 약 30영업일)."""
        js = self._get("/uapi/domestic-stock/v1/quotations/program-trade-by-stock-daily", "FHPPG04650201",
                       {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code, "FID_INPUT_DATE_1": ""})
        rows = js.get("output") or js.get("output1") or []
        if isinstance(rows, dict):
            rows = [rows]
        df = pd.DataFrame(rows)
        if df.empty or "stck_bsop_date" not in df:
            return pd.DataFrame()
        f = lambda c: pd.to_numeric(df.get(c), errors="coerce")  # noqa: E731
        out = pd.DataFrame({"date": pd.to_datetime(df["stck_bsop_date"]), "code": code,
                            "program_raw": f("whol_smtn_ntby_tr_pbmn"),
                            "gross_raw": f("whol_smtn_shnu_tr_pbmn") + f("whol_smtn_seln_tr_pbmn"),
                            "value_raw": f("acml_tr_pbmn")})
        return out.dropna(subset=["program_raw"])


def _unit_scale(df: pd.DataFrame) -> float:
    """금액 단위 자동 판별: 프로그램 매수+매도 대금이 전체 거래대금의 0.01%~200% 범위가 되도록 1/천/백만 배."""
    d = df[(df["value_raw"] > 0) & (df["gross_raw"] > 0)]
    if d.empty:
        return 1.0
    ratio = float((d["gross_raw"] / d["value_raw"]).median())
    for scale in (1.0, 1e3, 1e6):
        if 1e-4 <= ratio * scale <= 2:
            return scale
    return 1.0


def collect_program(store, cfg: dict) -> pd.DataFrame:
    """1차 필터 통과 종목(최근일 기준)의 프로그램매매를 받아 program.parquet 에 저장."""
    from ...config import data_dir
    from ..pit import PointInTimeData
    from ...engine.filters import stage1
    from ...indicators import compute_features
    from ...engine.screener import default_as_of

    kc = cfg.get("kis", {})
    client = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
    pit = PointInTimeData.from_store(store)
    last = pit.trading_dates()[-1]
    view = pit.view(default_as_of(last))
    oh = view.ohlcv()
    oh = oh[oh["date"] >= last - pd.Timedelta(days=120)]
    x = compute_features(oh).xs(last, level="date")
    s1, _ = stage1(x, view.listing(), cfg)
    codes = list(s1.index)
    log.info("프로그램매매 수집 대상 %d종목 (1차 필터 통과)", len(codes))
    parts = []
    for i, c in enumerate(codes, 1):
        try:
            d = client.program_daily(c)
            if not d.empty:
                parts.append(d)
        except Exception as e:  # noqa: BLE001
            log.warning("%s 프로그램매매 실패: %s", c, e)
        if i % 100 == 0:
            log.info("  %d/%d", i, len(codes))
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True)
    scale = _unit_scale(df)
    log.info("프로그램매매 금액 단위 배율: x%g", scale)
    df["program"] = df["program_raw"] * scale
    store.upsert("program", df[["date", "code", "program"]])
    return df
