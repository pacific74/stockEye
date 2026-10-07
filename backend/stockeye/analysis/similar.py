"""비슷한 차트 패턴 찾기.

현재 종목의 최근 N일(기본 20일) 가격 흐름과 '모양'이 비슷했던 과거 구간을
전 종목·전 기간에서 찾아, 그 뒤 5/10/20일 동안 어떻게 움직였는지 보여준다.

⚠ 참고자료일 뿐이다. "과거에 비슷했으니 이번에도 오른다"는 근거가 되지 않는다.
   그래서 상위 몇 개가 아니라 '비슷한 구간 전체의 결과 분포'(상승 비율, 중앙값)를 함께 보여준다.

미래참조 방지:
  - 과거 구간은 '구간 끝 + 보유기간(20일)'이 기준일(as_of) 이전에 끝난 것만 사용
  - 같은 종목의 최근 구간(기준일 이전 60일 내)은 제외
가격은 KRX 등락률(chg_pct)로 만든 수익률을 써서 액면분할의 영향을 받지 않는다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view


class PatternIndex:
    def __init__(self, ohlcv: pd.DataFrame, window: int = 20, step: int = 2, horizons=(5, 10, 20),
                 min_value: float = 1e9):
        self.window, self.step, self.horizons = window, step, tuple(horizons)
        df = ohlcv[["date", "code", "close", "value"] + (["chg_pct"] if "chg_pct" in ohlcv else [])].copy()
        if "chg_pct" in df:
            df["r"] = df["chg_pct"] / 100.0
        else:
            df = df.sort_values(["code", "date"])
            df["r"] = df.groupby("code")["close"].pct_change(fill_method=None)
        self.r = df.pivot(index="date", columns="code", values="r").sort_index().astype("float32")
        self.val = df.pivot(index="date", columns="code", values="value").reindex_like(self.r).astype("float32")
        self.dates = self.r.index
        self.codes = np.array(self.r.columns)
        self.min_value = min_value
        # 누적 로그수익 (NaN = 0 처리 후 유효성 마스크 별도)
        lr = np.log1p(self.r.fillna(0).to_numpy()).astype("float32")
        self.valid = self.r.notna().to_numpy()
        self.cum = np.vstack([np.zeros((1, lr.shape[1]), dtype="float32"), np.cumsum(lr, axis=0)])  # (T+1, N)

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
            d = np.sqrt(((self._z(paths) - qz) ** 2).mean(axis=-1))
            dist[b:b + 100] = np.where(ok, d, np.inf)

        flat = np.argsort(dist, axis=None)
        res, seen = [], set()
        for k in flat:
            if not np.isfinite(dist.flat[k]) or len(res) >= pool:
                break
            ei, ci = np.unravel_index(k, dist.shape)
            c = self.codes[ci]
            if one_per_code and c in seen:
                continue
            seen.add(c)
            e = int(ends[ei])
            fwd = {f"ret{h}": float(np.expm1(self.cum[e + 1 + h, ci] - self.cum[e + 1, ci])) for h in self.horizons}
            res.append({"code": c, "start": str(self.dates[e + 1 - W].date()), "end": str(self.dates[e].date()),
                        "similarity": round(float(max(0.0, 1 - dist.flat[k] / 1.5)) * 100, 1),
                        "path": [round(float(v), 4) for v in
                                 np.expm1(self.cum[e + 2 - W:e + 2, ci] - self.cum[e + 1 - W, ci])],
                        # 패턴 이후 H일 (같은 기준점에서의 누적 수익률) — 화면에서 '그 뒤' 점선으로 비교
                        "future": [round(float(v), 4) for v in
                                   np.expm1(self.cum[e + 2:e + 2 + H, ci] - self.cum[e + 1 - W, ci])],
                        **{k2: round(v * 100, 2) for k2, v in fwd.items()}})
        if not res:
            return {"error": "비슷한 구간 없음"}
        stats = {}
        for h in self.horizons:
            arr = np.array([r[f"ret{h}"] for r in res])
            stats[f"{h}d"] = {"up_ratio": round(float((arr > 0).mean()) * 100, 1),
                              "median": round(float(np.median(arr)), 2),
                              "p25": round(float(np.percentile(arr, 25)), 2),
                              "p75": round(float(np.percentile(arr, 75)), 2)}
        return {"code": code, "as_of": str(as_of.date()), "window": W,
                "query_path": [round(float(v), 4) for v in np.expm1(q)],
                "matches": res[:top], "sample_size": len(res), "stats": stats,
                "disclaimer": "과거 유사 패턴의 결과일 뿐이며 미래 수익을 예측하지 않습니다. 참고자료로만 사용하세요."}
