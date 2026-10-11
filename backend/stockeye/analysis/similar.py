"""비슷한 차트 패턴 찾기.

현재 종목의 최근 N일(기본 20일) 가격 흐름과 '모양'이 비슷했던 과거 구간을
전 종목·전 기간에서 찾아, 그 뒤 5/10/20일 동안 어떻게 움직였는지 보여준다.

⚠ 참고자료일 뿐이다. "과거에 비슷했으니 이번에도 오른다"는 근거가 되지 않는다.
   그래서 상위 몇 개가 아니라 '비슷한 구간 전체의 결과 분포'(상승 비율, 중앙값)를 함께 보여준다.

미래참조 방지:
  - 과거 구간은 '구간 끝 + 보유기간(20일)'이 기준일(as_of) 이전에 끝난 것만 사용
  - 같은 종목의 최근 구간(기준일 이전 60일 내)은 제외
가격은 KRX 등락률(chg_pct)로 만든 수익률을 써서 액면분할의 영향을 받지 않는다.

비교 기준 (2026-10-09~): 가격 모양 50% + 이동평균선 30% + 거래량 20%
  - 가격: 20일 누적 수익 경로의 모양 (z 정규화 거리)
  - 이평선: 같은 기간 20일선·60일선 경로를 '가격과 같은 기준'으로 정규화해 비교
           → 주가가 이평선 위/아래 어디에 있었는지, 이평선이 오르는지/내리는지까지 비슷해야 함
  - 거래량: 거래대금(분할 영향 없음)의 20일 모양 + 직전 20일 대비 늘었는지/줄었는지
  1단계로 가격 모양이 비슷한 구간 4,000개를 고른 뒤, 2단계에서 세 가지를 합친 거리로 다시 정렬한다.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view


class PatternIndex:
    WEIGHTS = {"price": 0.45, "ma": 0.40, "volume": 0.15}
    MA_N = (20, 60, 120)
    MIN_N, MAX_N, GOOD_SIM = 30, 200, 60.0       # 비교 표본: 유사도 60 이상 개수 (최소 30, 최대 200)
    GROUPS = (("상위 20%", 0.2), ("중위 30%", 0.3), ("하위 50%", 0.5))

    def __init__(self, ohlcv: pd.DataFrame, window: int = 20, step: int = 2, horizons=(5, 10, 20),
                 min_value: float = 1e9, prefilter: int = 4000):
        self.window, self.step, self.horizons = window, step, tuple(horizons)
        extra = [c for c in ("chg_pct", "open", "high", "low") if c in ohlcv]
        df = ohlcv[["date", "code", "close", "value"] + extra].copy()
        if "chg_pct" in df:
            df["r"] = df["chg_pct"] / 100.0
        else:
            df = df.sort_values(["code", "date"])
            df["r"] = df.groupby("code")["close"].pct_change(fill_method=None)
        self.r = df.pivot(index="date", columns="code", values="r").sort_index().astype("float32")
        self.val = df.pivot(index="date", columns="code", values="value").reindex_like(self.r).astype("float32")
        # 장중 고가·저가 ÷ 그날 종가 (분할 영향 없는 비율) → 패턴 이후 '기간 중 최고·최저' 계산용
        cl = df.pivot(index="date", columns="code", values="close").reindex_like(self.r).astype("float32")
        cl = cl.where(cl > 0)
        for nm_ in ("open", "high", "low"):
            if nm_ in df:
                x = df.pivot(index="date", columns="code", values=nm_).reindex_like(self.r).astype("float32")
                ratio = (x.where(x > 0) / cl).to_numpy()
                ratio = np.where(np.isfinite(ratio) & (ratio > 0.5) & (ratio < 2.0), ratio, 1.0)
            else:
                ratio = np.ones(self.r.shape, dtype="float32")
            setattr(self, nm_ + "_r", ratio.astype("float32"))
        self.dates = self.r.index
        self.codes = np.array(self.r.columns)
        self.min_value = min_value
        # 누적 로그수익 (NaN = 0 처리 후 유효성 마스크 별도)
        lr = np.log1p(self.r.fillna(0).to_numpy()).astype("float32")
        self.valid = self.r.notna().to_numpy()
        self.cum = np.vstack([np.zeros((1, lr.shape[1]), dtype="float32"), np.cumsum(lr, axis=0)])  # (T+1, N)
        self.prefilter = prefilter
        # 이동평균선: 수익률로 만든 가격(분할 영향 없음)의 20·60일 평균 → log. 거래일이 부족하면 NaN
        px = pd.DataFrame(np.exp(self.cum[1:]))
        vcnt = pd.DataFrame(self.valid.astype("float32"))
        self.lma = {}
        for n in self.MA_N:
            ma = px.rolling(n, min_periods=n).mean().to_numpy()
            okn = vcnt.rolling(n, min_periods=n).sum().to_numpy() >= n * 0.9
            self.lma[n] = np.where(okn, np.log(ma), np.nan).astype("float32")
        # 거래량: 거래대금 log (거래 없는 날·결측 = NaN)
        v = self.val.to_numpy()
        self.lv = np.where(self.valid & (v > 0), np.log1p(np.where(v > 0, v, 0)), np.nan).astype("float32")

    def _path(self, end_idx: int, col: int) -> np.ndarray | None:
        s = end_idx + 1 - self.window
        if s < 0 or not self.valid[s:end_idx + 1, col].all():
            return None
        p = self.cum[s + 1:end_idx + 2, col] - self.cum[s, col]       # 0에서 시작하는 누적 로그수익
        return p

    @staticmethod
    def _z(p: np.ndarray) -> np.ndarray:
        sd = p.std(axis=-1, keepdims=True)
        return (p - p.mean(axis=-1, keepdims=True)) / np.where(sd < 1e-6, 1, sd)

    def search(self, code: str, as_of, top: int = 10, pool: int = 200, one_per_code: bool = True) -> dict:
        as_of = pd.Timestamp(as_of).normalize()
        T = int(self.dates.searchsorted(as_of, side="right")) - 1        # as_of 이하 마지막 인덱스
        if T < self.window or code not in set(self.codes):
            return {"error": "데이터 부족"}
        col = int(np.where(self.codes == code)[0][0])
        q = self._path(T, col)
        if q is None:
            return {"error": "최근 구간에 거래정지/결측 있음"}
        H = max(self.horizons)
        qz, q_amp = self._z(q[None, :])[0], float(q[-1] - q.min() + 1e-9)
        qside = self._ma_side(np.array([T]), np.array([col]))[0]

        last_end = T - H                         # 결과(+H일)까지 as_of 이전에 끝난 구간만
        ends = np.arange(self.window - 1, last_end + 1, self.step)
        if len(ends) == 0:
            return {"error": "과거 데이터 부족"}
        W = self.window
        N = len(self.codes)
        dist = np.full((len(ends), N), np.inf, dtype="float32")
        cumw = sliding_window_view(self.cum, W + 1, axis=0)          # (T+1-W, N, W+1) 뷰 (복사 없음)
        validw = sliding_window_view(self.valid, W, axis=0)
        valnp = np.nan_to_num(self.val.to_numpy())
        for b in range(0, len(ends), 100):                            # 메모리 절약: 100구간씩
            e = ends[b:b + 100]
            win = cumw[e + 1 - W]
            paths = win[..., 1:] - win[..., :1]                       # (e, N, W)
            ok = validw[e + 1 - W].all(axis=-1) & (valnp[e] >= self.min_value)
            ok[e >= T - 60, col] = False                              # 자기 자신의 최근 구간 제외
            amp = paths[..., -1] - paths.min(axis=-1) + 1e-9
            ok &= (amp / q_amp > 0.5) & (amp / q_amp < 2.0)           # 크기도 비슷한 것만
            for j, n in ((0, 60), (1, 120)):                          # 가격이 60·120일선 위/아래가 지금과 같은 것만
                if np.isfinite(qside[j]):
                    sd_ = self.cum[e + 1, :] - self.lma[n][e, :]
                    ok &= np.isfinite(sd_) & (np.sign(sd_) == np.sign(qside[j]))
            d = np.sqrt(((self._z(paths) - qz) ** 2).mean(axis=-1))
            dist[b:b + 100] = np.where(ok, d, np.inf)

        # 1단계: 가격 모양이 비슷한 구간 prefilter 개 → 2단계: 가격·이평선·거래량 합친 거리로 재정렬
        nfin = int(np.isfinite(dist).sum())
        k1 = min(self.prefilter, nfin)
        if k1 == 0:
            return {"error": "비슷한 구간 없음"}
        flat = np.argpartition(dist, k1 - 1, axis=None)[:k1] if k1 < dist.size else np.arange(dist.size)
        flat = flat[np.isfinite(dist.flat[flat])]
        ei_all, ci_all = np.unravel_index(flat, dist.shape)
        e_all = ends[ei_all]
        d_p = dist.flat[flat].astype("float32")
        d_m = self._ma_dist(T, col, e_all, ci_all)
        d_v = self._vol_dist(T, col, e_all, ci_all)
        wt = self.WEIGHTS
        comb = wt["price"] * d_p + wt["ma"] * d_m + wt["volume"] * d_v
        order = np.argsort(comb)
        order = order[np.isfinite(comb[order])]                       # 이평선 위치가 다른 구간은 제외
        sim = lambda d: round(float(max(0.0, 1 - d / 1.5)) * 100, 1)  # noqa: E731
        res, seen = [], set()
        for j in order:
            if len(res) >= pool:
                break
            ci = int(ci_all[j])
            c = self.codes[ci]
            if one_per_code and c in seen:
                continue
            seen.add(c)
            e = int(e_all[j])
            extra = {"sim_price": sim(d_p[j]), "sim_ma": sim(d_m[j]), "sim_volume": sim(d_v[j])}
            if len(res) < top:
                extra["ma"] = self._ma_state(e, ci)
            fwd = {f"ret{h}": float(np.expm1(self.cum[e + 1 + h, ci] - self.cum[e + 1, ci])) for h in self.horizons}
            ext = self._extremes(e, ci, H)
            res.append({"code": c, "start": str(self.dates[e + 1 - W].date()), "end": str(self.dates[e].date()),
                        "similarity": sim(comb[j]), **extra,
                        "path": [round(float(v), 4) for v in
                                 np.expm1(self.cum[e + 2 - W:e + 2, ci] - self.cum[e + 1 - W, ci])],
                        # 패턴 이후 H일 (같은 기준점에서의 누적 수익률) — 화면에서 '그 뒤' 점선으로 비교
                        "future": [round(float(v), 4) for v in
                                   np.expm1(self.cum[e + 2:e + 2 + H, ci] - self.cum[e + 1 - W, ci])],
                        **{k2: round(v * 100, 2) for k2, v in fwd.items()}, **ext})
        if not res:
            return {"error": "비슷한 구간 없음"}
        # 표본 수: 유사도 60 이상인 구간 수 (최소 30, 최대 200) — 유사도 낮은 구간까지 끌어오지 않게
        sims = np.array([r["similarity"] for r in res])
        buckets = {f"{b}": int(((sims >= b) & (sims < b + 10)).sum()) for b in (80, 70, 60, 50)}
        buckets["80"] += int((sims >= 90).sum())
        buckets["<50"] = int((sims < 50).sum())
        n_use = int(min(self.MAX_N, max(self.MIN_N, (sims >= self.GOOD_SIM).sum())))
        res = res[:n_use]
        groups = self._groups(res, H)
        stats = {}
        for h in self.horizons:
            arr = np.array([r[f"ret{h}"] for r in res])
            hi = np.array([r.get(f"max{h}", np.nan) for r in res], dtype=float)
            lo = np.array([r.get(f"min{h}", np.nan) for r in res], dtype=float)
            stats[f"{h}d"] = {"up_ratio": round(float((arr > 0).mean()) * 100, 1),
                              "median": round(float(np.median(arr)), 2),
                              "p25": round(float(np.percentile(arr, 25)), 2),
                              "p75": round(float(np.percentile(arr, 75)), 2),
                              # 그 h일 동안 장중 최고·최저 (그날 종가만 보면 놓치는 급등·급락)
                              "max_median": round(float(np.nanmedian(hi)), 2),
                              "min_median": round(float(np.nanmedian(lo)), 2),
                              "hit_up10": round(float(np.nanmean(hi >= 10)) * 100, 1),
                              "hit_dn10": round(float(np.nanmean(lo <= -10)) * 100, 1)}
        return {"code": code, "as_of": str(as_of.date()), "window": W, "weights": dict(self.WEIGHTS),
                "basis": "가격 모양 50% · 이동평균선(20·60일) 30% · 거래량 20%",
                "query_ma": self._ma_state(T, col),
                "query_path": [round(float(v), 4) for v in np.expm1(q)],
                "matches": res[:top], "sample_size": len(res), "stats": stats,
                "sim_buckets": buckets, "groups": groups,
                "disclaimer": "과거 유사 패턴의 결과일 뿐이며 미래 수익을 예측하지 않습니다. 참고자료로만 사용하세요."}

    def _groups(self, res: list[dict], H: int) -> list[dict]:
        """유사도 순서로 상위 20% / 중위 30% / 하위 50% → 날마다 그룹 대표 봉 (시가·종가 = 중앙값,
        고가 = 고가들의 75% 지점, 저가 = 저가들의 25% 지점: 극단값 몇 개에 끌려가지 않게) + 요약"""
        n = len(res)
        out, start = [], 0
        for i, (name, frac) in enumerate(self.GROUPS):
            end = n if i == len(self.GROUPS) - 1 else start + max(1, int(round(n * frac)))
            g = [r for r in res[start:end] if r.get("_ohlc") is not None and len(r["_ohlc"]) == H]
            start = end
            if not g:
                continue
            a = np.stack([r["_ohlc"] for r in g])                       # (m, H, 4)
            with np.errstate(all="ignore"), warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                o, cl = np.nanmedian(a[:, :, 0], axis=0), np.nanmedian(a[:, :, 3], axis=0)
                hi, lo = np.nanpercentile(a[:, :, 1], 75, axis=0), np.nanpercentile(a[:, :, 2], 25, axis=0)
            hi, lo = np.maximum(hi, np.maximum(o, cl)), np.minimum(lo, np.minimum(o, cl))
            candles = [[round(float(x), 2) for x in (o[k], hi[k], lo[k], cl[k])] for k in range(H)]
            close_end = a[:, -1, 3]
            mx, mn = np.nanmax(a[:, :, 1], axis=1), np.nanmin(a[:, :, 2], axis=1)
            sims = [r["similarity"] for r in g]
            out.append({"name": name, "n": len(g), "sim_max": max(sims), "sim_min": min(sims), "candles": candles,
                        "close_median": round(float(np.nanmedian(close_end)), 2),
                        "up_ratio": round(float((close_end > 0).mean()) * 100, 1),
                        "max_median": round(float(np.nanmedian(mx)), 2), "min_median": round(float(np.nanmedian(mn)), 2),
                        "max_day": int(np.nanmedian(np.nanargmax(a[:, :, 1], axis=1)) + 1),
                        "min_day": int(np.nanmedian(np.nanargmin(a[:, :, 2], axis=1)) + 1),
                        "hit_up10": round(float((mx >= 10).mean()) * 100, 1),
                        "hit_dn10": round(float((mn <= -10).mean()) * 100, 1)})
        for r in res:                                                  # 내부용 경로는 결과에서 뺌
            r.pop("_ohlc", None)
        return out

    def _extremes(self, e: int, ci: int, H: int) -> dict:
        """패턴 끝날(e) 종가 기준 1~H일 동안 장중 최고가·최저가(%)와 그날(몇 일째) + h일별 최고·최저, 최고 종가"""
        rel = np.expm1(self.cum[e + 2:e + 2 + H, ci] - self.cum[e + 1, ci])          # k=1..H 종가 (기준 대비)
        c = 1.0 + rel
        hi = c * self.high_r[e + 1:e + 1 + H, ci] - 1.0
        lo = c * self.low_r[e + 1:e + 1 + H, ci] - 1.0
        out = {}
        if len(hi) == 0:
            return out
        for h in self.horizons:
            if h <= len(hi):
                out[f"max{h}"] = round(float(hi[:h].max()) * 100, 2)
                out[f"min{h}"] = round(float(lo[:h].min()) * 100, 2)
        out["max_day"] = int(np.argmax(hi)) + 1
        out["min_day"] = int(np.argmin(lo)) + 1
        op = c * self.open_r[e + 1:e + 1 + H, ci] - 1.0
        out["_ohlc"] = np.stack([op, hi, lo, rel], axis=1) * 100          # (H, 4) %, 그룹 차트용 (화면에는 안 보냄)
        out["max_close"] = round(float(rel.max()) * 100, 2)
        out["max_close_day"] = int(np.argmax(rel)) + 1
        return out

    # ---------------------------------------------------------------- 이평선·거래량 비교
    def _rows(self, e: np.ndarray) -> np.ndarray:
        return (e - self.window + 1)[:, None] + np.arange(self.window)[None, :]          # (K, W) 날짜 인덱스

    def _norm(self, e: np.ndarray, c: np.ndarray):
        """구간별 가격 경로의 평균·표준편차 (이평선 경로를 같은 기준으로 정규화하려고)"""
        s = e - self.window + 1
        rows = self._rows(e)
        base = self.cum[s, c]                                                            # 구간 시작 전날 log 가격
        p = self.cum[rows + 1, c[:, None]] - base[:, None]
        sd = p.std(axis=1)
        return rows, base, p.mean(axis=1), np.where(sd < 1e-6, 1, sd)

    def _ma_paths(self, e, c):
        rows, base, mu, sd = self._norm(e, c)
        out = []
        for n in self.MA_N:
            m = (self.lma[n][rows, c[:, None]] - base[:, None] - mu[:, None]) / sd[:, None]
            out.append(np.clip(m, -6, 6))
        return out

    def _ma_side(self, e, c) -> np.ndarray:
        """구간 끝날: 가격−60일선, 가격−120일선, 20−60일선, 60−120일선 (log 차이). (K, 4)"""
        lp = self.cum[e + 1, c]
        m20, m60, m120 = (self.lma[n][e, c] for n in self.MA_N)
        return np.stack([lp - m60, lp - m120, m20 - m60, m60 - m120], axis=1)

    def _ma_dist(self, T, col, e, c) -> np.ndarray:
        """이평선 거리 = 20·60·120일선 경로 모양 + 끝날 위치 관계(가격이 60·120일선 위/아래, 정배열/역배열, 120일선과의 거리).
        가격이 60일선·120일선의 어느 쪽에 있는지가 지금과 다르면 inf (비교 대상에서 뺌)"""
        qs = self._ma_paths(np.array([T]), np.array([col]))
        ms = self._ma_paths(e, c)
        parts = []
        for q, m in list(zip(qs, ms))[:2]:                             # 모양은 20·60일선 (120일선은 아래 위치 관계로)
            if np.isnan(q[0]).any():
                continue
            parts.append(((m - q[0]) ** 2).mean(axis=1))
        if not parts:                                                  # 지금 종목 이평선을 못 구하면 비교 안 함
            return np.zeros(len(e), dtype="float32")
        d = np.sqrt(np.mean(parts, axis=0))
        d = np.where(np.isfinite(d), d, 1.5)
        qside = self._ma_side(np.array([T]), np.array([col]))[0]
        side = self._ma_side(e, c)
        for j in (0, 1):                                               # 가격 vs 60·120일선: 같은 쪽이어야
            if np.isfinite(qside[j]):
                bad = ~np.isfinite(side[:, j]) | (np.sign(side[:, j]) != np.sign(qside[j]))
                d = np.where(bad, np.inf, d)
        for j in (2, 3):                                               # 정배열/역배열 다르면 감점
            if np.isfinite(qside[j]):
                d = d + np.where(np.sign(side[:, j]) != np.sign(qside[j]), 0.3, 0.0)
        if np.isfinite(qside[1]):                                      # 120일선과의 거리 차이 (10% 차이 = +0.3)
            gap = np.abs(np.nan_to_num(side[:, 1], nan=9) - qside[1])
            d = d + np.minimum(gap / 0.10 * 0.3, 1.0)
        return d.astype("float32")

    def _vol_feat(self, e, c):
        rows = self._rows(e)
        lv = self.lv[rows, c[:, None]]
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            m = np.nanmean(lv, axis=1)
            shape = lv - m[:, None]
            prev_rows = np.clip(rows - self.window, 0, None)
            prev = np.nanmean(self.lv[prev_rows, c[:, None]], axis=1)
        return shape, m - prev

    def _vol_dist(self, T, col, e, c) -> np.ndarray:
        qs, ql = self._vol_feat(np.array([T]), np.array([col]))
        sh, lvl = self._vol_feat(e, c)
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            d_shape = np.sqrt(np.nanmean((sh - qs) ** 2, axis=1))
            d = 0.6 * d_shape / 0.8 + 0.4 * np.abs(lvl - ql[0]) / 0.5
        return np.where(np.isfinite(d), np.minimum(d, 3.0), 1.5).astype("float32")

    def _ma_state(self, T: int, col: int) -> dict:
        """지금 종목의 이평선 상태 (화면 설명용)"""
        lp = self.cum[T + 1, col]
        out = {}
        for n in self.MA_N:
            m = self.lma[n][T, col]
            m5 = self.lma[n][T - 5, col] if T >= 5 else np.nan
            out[f"dist{n}"] = None if np.isnan(m) else round(float(np.expm1(lp - m)) * 100, 1)
            out[f"slope{n}"] = None if np.isnan(m) or np.isnan(m5) else round(float(np.expm1(m - m5)) * 100, 2)
        lv = self.lv[max(0, T - 19):T + 1, col]
        pv = self.lv[max(0, T - 39):max(0, T - 19), col]
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            out["vol_change"] = None if np.isnan(lv).all() or np.isnan(pv).all() else \
                round(float(np.expm1(np.nanmean(lv) - np.nanmean(pv))) * 100, 0)
        return out
