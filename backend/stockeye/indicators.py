"""기술적 지표.

규칙: 모든 함수는 '인과적(causal)'이어야 한다.
  - rolling / ewm / shift(양수) 만 사용
  - shift(음수), center=True, 전체기간 min/max/mean 사용 금지
backtest.lookahead 의 감사(audit)가 이 규칙 위반을 자동으로 잡아낸다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    # 하락이 전혀 없으면 RSI=100
    return out.where(avg_loss != 0, 100.0).where(avg_gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return line, sig, line - sig


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    return mid, mid + k * sd, mid - k * sd


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def consecutive_positive(s: pd.Series) -> pd.Series:
    """연속으로 양수인 일수 (예: 외국인 연속 순매수 일수)."""
    pos = (s > 0).astype(int)
    grp = (pos != pos.shift()).cumsum()
    return pos.groupby(grp).cumsum() * pos


# ---------------------------------------------------------------------------
# 종목 1개에 대한 전체 피처 계산
# ---------------------------------------------------------------------------
PRICE_LEVEL_COLS = ["sma5", "sma20", "sma60", "sma120", "high20_prev", "high60_prev", "high250", "low10",
                    "macd", "macd_signal", "macd_hist", "bb_mid", "bb_up", "bb_low", "atr14"]


def split_factor(bars: pd.DataFrame) -> pd.Series:
    """액면분할·무상증자 등 권리락 누적계수 C_t (인과적).

    KRX 등락률(chg_pct)은 '기준가'(권리락 반영 전일가) 대비라서
      기준가_t = 종가_t / (1 + 등락률_t),   r_t = 기준가_t / 종가_{t-1}
    r_t ≠ 1 이면 그날 권리락이 있었던 것. C_t = r_1 × … × r_t (그날까지의 정보만 사용).
    """
    if "chg_pct" not in bars or bars["chg_pct"].isna().all():
        return pd.Series(1.0, index=bars.index)
    base = bars["close"] / (1 + bars["chg_pct"] / 100)
    r = (base / bars["close"].shift(1)).fillna(1.0)
    r = r.where((r - 1).abs() > 0.02, 1.0)     # 반올림 오차 무시
    return r.cumprod()


def features_for_one(bars: pd.DataFrame, flows: pd.DataFrame | None = None,
                     fund: pd.DataFrame | None = None) -> pd.DataFrame:
    """bars: index=date, columns=[open, high, low, close, volume, value, (chg_pct)]

    분할 보정: 가격을 '전진 보정'(과거 기준으로 이후 가격을 나눔)해서 지표를 계산한 뒤,
    가격 수준 지표는 그날의 C_t 를 곱해 '그날 실제 가격' 단위로 되돌린다.
    → 미래의 분할 정보를 쓰지 않으면서도 분할일에 가짜 급락/급등이 생기지 않는다.
    """
    # 입력 자료형(int32/float32 등)과 무관하게 같은 결과가 나오도록 모두 float64 로 계산
    bars = bars.astype({c: "float64" for c in bars.columns if pd.api.types.is_numeric_dtype(bars[c])})
    C = split_factor(bars)
    c, h, l = bars["close"] / C, bars["high"] / C, bars["low"] / C
    v = bars["volume"] * C
    f = pd.DataFrame(index=bars.index)
    f["open"], f["high"], f["low"], f["close"] = bars["open"], bars["high"], bars["low"], bars["close"]
    f["volume"], f["value"] = bars["volume"], bars["value"]
    f["split_factor"] = C

    f["sma5"], f["sma20"], f["sma60"], f["sma120"] = sma(c, 5), sma(c, 20), sma(c, 60), sma(c, 120)
    f["sma20_slope"] = f["sma20"] / f["sma20"].shift(5) - 1          # 20일선 5일 기울기
    f["vol_ma20"] = sma(v, 20)
    f["vol_ratio"] = v / f["vol_ma20"].shift(1)                       # 오늘 거래량 / 직전 20일 평균
    f["value_ma20"] = sma(bars["value"], 20)
    f["value_ma5"] = sma(bars["value"], 5)
    f["value_ratio"] = f["value_ma5"] / f["value_ma20"].shift(5)      # 최근5일 거래대금 / 그 이전 20일

    f["high20_prev"] = h.rolling(20, min_periods=20).max().shift(1)   # 오늘 제외 직전 20일 고점
    f["high60_prev"] = h.rolling(60, min_periods=60).max().shift(1)
    f["high250"] = h.rolling(250, min_periods=60).max()
    f["low10"] = l.rolling(10, min_periods=10).min()

    f["rsi14"] = rsi(c, 14)
    f["macd"], f["macd_signal"], f["macd_hist"] = macd(c)
    f["bb_mid"], f["bb_up"], f["bb_low"] = bollinger(c)
    f["bb_pos"] = (c - f["bb_low"]) / (f["bb_up"] - f["bb_low"])
    f["atr14"] = atr(h, l, c, 14)
    f["atr_pct"] = f["atr14"] / c

    f["ret1"] = c.pct_change(fill_method=None)
    f["ret5"] = c / c.shift(5) - 1
    f["ret20"] = c / c.shift(20) - 1
    f["min_ret_5d"] = f["ret1"].rolling(5, min_periods=1).min()
    f["halted"] = (bars["volume"] <= 0)

    # ---- 전략용 추가 피처 ----
    f["ret60"] = c / c.shift(60) - 1
    f["sma60_slope"] = f["sma60"] / f["sma60"].shift(10) - 1
    f["vol5_ratio"] = sma(v, 5) / f["vol_ma20"].shift(5)                 # 최근 5일 거래량 / 그 전 20일 (눌림 시 감소)
    f["value_ratio1"] = bars["value"] / f["value_ma20"].shift(1)        # 오늘 거래대금 / 직전 20일 평균
    rng_ = (h - l).replace(0, np.nan)
    f["close_pos"] = ((c - l) / rng_).fillna(0.5)                       # 당일 고저 범위 내 종가 위치 (1=고가 마감)
    f["dist_sma20"] = c / sma(c, 20) - 1                                # 20일선 이격
    f["above20_days"] = consecutive_positive((c > sma(c, 20)).astype(float) - 0.5)
    f["below20_recent"] = (c < sma(c, 20)).astype(float).rolling(5, min_periods=1).max()  # 최근 5일 내 20일선 아래 있었나
    f["macd_hist_prev"] = f["macd_hist"].shift(1)
    f["near_high250"] = c / h.rolling(250, min_periods=60).max()
    f["up_day"] = (c > c.shift(1)) & (bars["close"] > bars["open"])

    for col in PRICE_LEVEL_COLS:          # 보정 단위 → 그날 실제 가격 단위
        f[col] = f[col] * C

    if flows is not None:
        fl = flows.reindex(bars.index)
        for col in ("foreign", "institution", "individual", "program"):
            if col in fl:
                x = fl[col].astype("float64")
                f[f"{col}_net"] = x
                f[f"{col}_net5"] = x.rolling(5, min_periods=1).sum()
                # 수급 데이터가 없는 날은 '연속일수'도 모름(NaN) — 0 으로 두면 데이터 유무가 결과를 바꿈
                f[f"{col}_streak"] = consecutive_positive(x.fillna(0)).where(x.notna())
    if fund is not None and len(fund):
        fd = fund.reindex(bars.index).ffill()
        for col in ("eps", "bps", "per", "pbr", "div"):
            if col in fd:
                f[col] = fd[col]
        if "eps" in fd:   # 1년 전 대비 EPS 증가율 (KRX 가 공시 반영 시 갱신 → 그날까지 정보만 사용)
            e0 = fd["eps"].shift(250)
            f["eps_yoy"] = (fd["eps"] / e0 - 1).where((e0 > 0) & (fd["eps"] > 0))
    return f


def compute_features(ohlcv: pd.DataFrame, flows: pd.DataFrame | None = None,
                     fund: pd.DataFrame | None = None) -> pd.DataFrame:
    """긴 형식(date, code, ...) 입력 → MultiIndex(date, code) 피처 프레임.
    메모리: 종목별로 float32 로 줄이고, 중간 복사를 최소화 (4,000종목 × 5년 ≈ 1~2GB)."""
    fl_cols = [c for c in ("foreign", "institution", "individual", "program")
               if flows is not None and len(flows) and c in flows]
    fl_idx = flows.groupby("code").indices if flows is not None and len(flows) else {}
    fd_idx = fund.groupby("code").indices if fund is not None and len(fund) else {}
    out = []
    for code, rows in ohlcv.groupby("code", sort=False).indices.items():
        bars = ohlcv.iloc[rows].set_index("date").sort_index()
        fl = flows.iloc[fl_idx[code]].set_index("date").sort_index() if code in fl_idx else None
        if fl is None and fl_cols:      # 이 종목만 수급이 없으면 빈 표(NaN) → 다른 날짜 데이터 유무와 무관하게 같은 열
            fl = pd.DataFrame(columns=fl_cols, index=pd.DatetimeIndex([], name="date"))
        fd = fund.iloc[fd_idx[code]].set_index("date").sort_index() if code in fd_idx else None
        feat = features_for_one(bars, fl, fd)
        num = feat.select_dtypes("float64").columns
        feat[num] = feat[num].astype("float32")
        feat.index = pd.MultiIndex.from_arrays([feat.index, np.full(len(feat), code, dtype=object)],
                                               names=["date", "code"])
        out.append(feat)
    if not out:
        return pd.DataFrame()
    res = pd.concat(out, copy=False)
    del out
    return res.sort_index()
