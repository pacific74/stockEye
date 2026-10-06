"""합성(가짜) 시장 데이터 생성기.

인터넷/KRX 없이 전체 파이프라인과 백테스트를 시험하기 위한 용도.
실제 수익률 예측력은 없으며, 결과 숫자는 의미가 없다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

POS_TITLES = ["단일판매ㆍ공급계약체결", "자기주식취득결정", "무상증자결정", "특허권취득"]
NEG_TITLES = ["유상증자결정", "전환사채권발행결정", "소송등의제기", "횡령ㆍ배임혐의발생"]
NEU_TITLES = ["임원ㆍ주요주주특정증권등소유상황보고서", "기업설명회(IR)개최", "주주총회소집공고"]


def generate(n_stocks: int = 300, start="2021-01-04", end="2026-09-30", seed: int = 7) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, end)
    T = len(dates)
    market = rng.normal(0.0003, 0.011, T)  # 시장 공통 요인

    ohlcv, flows, fund, disc, listing = [], [], [], [], []
    for i in range(n_stocks):
        code = f"{100000 + i * 7:06d}"
        beta = rng.uniform(0.6, 1.5)
        vol = rng.uniform(0.015, 0.045)
        # 추세 국면(regime): 60~250일마다 드리프트가 바뀜
        drift = np.zeros(T)
        t = 0
        while t < T:
            L = rng.integers(60, 250)
            drift[t:t + L] = rng.normal(0.0002, 0.0015)
            t += L
        ret = drift + beta * market + rng.normal(0, vol, T)
        ret = np.clip(ret, -0.29, 0.29)
        p0 = float(np.exp(rng.uniform(np.log(800), np.log(300_000))))
        close = p0 * np.cumprod(1 + ret)
        close = np.maximum(close, 50)
        prev = np.concatenate([[p0], close[:-1]])
        open_ = prev * (1 + rng.normal(0, vol / 3, T))
        hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2, T)))
        lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2, T)))
        base_shares = 10 ** rng.uniform(4.0, 6.7)
        volume = base_shares * np.exp(rng.normal(0, 0.4, T)) * (1 + 8 * np.abs(ret))
        halted = rng.random(T) < 0.001
        volume[halted] = 0
        value = volume * close

        chg = ret * 100
        if i % 50 == 7:   # 일부 종목에 1:5 액면분할 (분할 보정 로직 시험용)
            k = int(rng.integers(T // 3, 2 * T // 3))
            open_[k:], hi[k:], lo[k:], close[k:] = open_[k:] / 5, hi[k:] / 5, lo[k:] / 5, close[k:] / 5
            volume[k:] *= 5
        ohlcv.append(pd.DataFrame({"date": dates, "code": code, "open": open_, "high": hi, "low": lo,
                                   "close": close, "volume": volume.round(), "value": value.round(),
                                   "chg_pct": chg}))
        # 수급: '당일' 수익률과 상관 (미래 수익률과는 무관하게 생성)
        f_scale = value * 0.05
        flows.append(pd.DataFrame({
            "date": dates, "code": code,
            "foreign": f_scale * (rng.normal(0, 1, T) + 6 * ret),
            "institution": f_scale * (rng.normal(0, 1, T) + 4 * ret),
            "individual": f_scale * (rng.normal(0, 1, T) - 8 * ret),
            "program": f_scale * rng.normal(0, 0.5, T),
        }))
        eps = rng.normal(1, 1.5) * close[0] / 15
        fund.append(pd.DataFrame({"date": dates, "code": code, "eps": eps, "bps": close[0] / rng.uniform(0.5, 3),
                                  "per": np.where(eps > 0, close / eps, 0), "pbr": close / (close[0] / 1.2),
                                  "div": rng.uniform(0, 4)}))
        n_disc = rng.poisson(T / 60)
        for d in rng.choice(T, n_disc, replace=False):
            pool = POS_TITLES if rng.random() < 0.3 else NEG_TITLES if rng.random() < 0.3 else NEU_TITLES
            disc.append({"code": code, "published_at": dates[d] + pd.Timedelta(hours=int(rng.integers(8, 20))),
                         "title": str(rng.choice(pool)), "source": "SYN"})
        listing.append({"code": code, "name": f"합성기업{i:03d}", "market": "KOSPI" if i % 3 else "KOSDAQ",
                        "is_admin": bool(rng.random() < 0.02), "as_of": dates[0]})

    oh = pd.concat(ohlcv, ignore_index=True)
    idx = (oh.assign(r=oh.groupby("code")["close"].pct_change(fill_method=None))
             .groupby("date")["r"].mean().fillna(0).add(1).cumprod().mul(1000).rename("close").reset_index())
    idx["code"] = "KOSPI"
    return {
        "ohlcv": oh, "flows": pd.concat(flows, ignore_index=True), "fundamentals": pd.concat(fund, ignore_index=True),
        "disclosures": pd.DataFrame(disc), "listing": pd.DataFrame(listing), "index": idx,
    }
