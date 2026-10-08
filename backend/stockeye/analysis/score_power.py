"""점수 예측력 검증 — "높은 점수를 준 종목이 실제로 언제부터 잘 움직이나?"

신호일(점수를 매긴 날) 종가를 기준으로 h = 5/10/20/40 거래일 뒤:
  수익률        r_h  = h일 뒤 종가 / 신호일 종가 - 1
  최대 손실     dd_h = 신호일 다음 날부터 h일 동안 가장 낮은 저가 / 신호일 종가 - 1   (그 사이 가장 깊이 빠진 정도)
점수 구간별로 평균 · 중앙값 · 승률(r_h > 0) · 일평균(단순 = 평균/h, 복리 = (1+평균)^(1/h) - 1) · 최대 손실 평균/중앙값.

※ 점수 항목으로 쓰지 않는다 — 어떤 점수가 미래 수익을 실제로 예측하는지 확인하는 '검증 지표'.
※ 가격제한폭(±30%)을 넘는 하루 변화(액면분할·병합 등)가 낀 구간은 계산에서 뺀다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (5, 10, 20, 40)


def forward_returns(ohlcv: pd.DataFrame, horizons=HORIZONS) -> pd.DataFrame:
    """ohlcv(date, code, low, close) → (date, code, r5.., dd5..) 긴 표"""
    cl = ohlcv.pivot(index="date", columns="code", values="close").astype("float64")
    lo = ohlcv.pivot(index="date", columns="code", values="low").astype("float64")
    cl, lo = cl.where(cl > 0), lo.where(lo > 0)
    jump = (cl.pct_change(fill_method=None).abs() > 0.31).astype(float)
    out = {}
    for h in horizons:
        bad = jump.rolling(h, min_periods=1).max().shift(-h)               # t+1..t+h 사이 불연속
        out[f"r{h}"] = (cl.shift(-h) / cl - 1).where(bad == 0)
        out[f"dd{h}"] = (lo.rolling(h, min_periods=h).min().shift(-h) / cl - 1).clip(upper=0).where(bad == 0)
    f = pd.concat({k: v.stack(future_stack=True) for k, v in out.items()}, axis=1).reset_index()
    f.columns = ["date", "code", *out.keys()]
    return f.dropna(subset=[f"r{horizons[0]}"])


def default_bins(max_points: float, n: int = 4) -> list[float]:
    """0~만점을 n 구간으로 (마지막 구간은 만점 포함)"""
    step = max_points / n
    return [round(step * k, 4) for k in range(n)] + [max_points + 1e-9]


def bucket_table(df: pd.DataFrame, col: str, bins: list[float], horizons=HORIZONS, clip: float = 1.0) -> pd.DataFrame:
    """점수 구간별 5/10/20/40일 평균·중앙값·승률·일평균(단순/복리)·최대 손실 (%)"""
    d = df.dropna(subset=[col])
    n = len(bins) - 1                       # 왼쪽 포함 [a, b) — 마지막 구간은 'a~' (만점 포함)
    labels = [f"{_fmt(bins[k])}~{_fmt(bins[k + 1])}" if k < n - 1 else f"{_fmt(bins[k])}~" for k in range(n)]
    d = d.assign(_b=pd.cut(d[col], bins, right=False, labels=labels, include_lowest=True))
    rows = []
    for lab, g in d.groupby("_b", observed=True):
        row = {"구간": str(lab), "건수": len(g)}
        for h in horizons:
            r = g[f"r{h}"].dropna().clip(-clip, clip)
            if r.empty:
                continue
            m = r.mean()
            row.update({f"{h}일 평균": m * 100, f"{h}일 중앙값": r.median() * 100, f"{h}일 승률": (r > 0).mean() * 100,
                        f"{h}일 일평균(단순)": m / h * 100, f"{h}일 일평균(복리)": ((1 + m) ** (1 / h) - 1) * 100 if m > -1 else np.nan})
            if f"dd{h}" in g:
                dd = g[f"dd{h}"].dropna()
                row.update({f"{h}일 최대손실 평균": dd.mean() * 100, f"{h}일 최대손실 중앙값": dd.median() * 100})
        rows.append(row)
    return pd.DataFrame(rows).set_index("구간").round(2)


def monotonic(tbl: pd.DataFrame, h: int = 20) -> float | None:
    """구간이 올라갈수록 h일 평균 수익률이 오르는가 (구간 순서 vs 평균의 순위상관, +1 완전 증가 / -1 완전 감소)"""
    col = f"{h}일 평균"
    if col not in tbl or len(tbl) < 3:
        return None
    return round(float(pd.Series(range(len(tbl))).corr(tbl[col].reset_index(drop=True), method="spearman")), 2)


def _md(t: pd.DataFrame) -> str:
    """판다스 표 → 마크다운 (추가 패키지 없이)"""
    head = ["구간", *map(str, t.columns)]
    rows = [[str(i), *[("" if pd.isna(v) else (f"{v:,.0f}" if c == "건수" else f"{v:+.2f}" if "승률" not in c else f"{v:.1f}"))
                       for c, v in zip(t.columns, r)]] for i, r in zip(t.index, t.itertuples(index=False))]
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(r) + " |" for r in rows])


def _fmt(x: float) -> str:
    return f"{x:g}" if abs(x - round(x)) > 1e-6 else str(int(round(x)))


def report(df: pd.DataFrame, cols: dict[str, list[float]], horizons=HORIZONS) -> dict:
    """{항목: {table, monotonic20}} — cols = {칸 이름: 구간 경계}"""
    out = {}
    for c, bins in cols.items():
        t = bucket_table(df, c, bins, horizons)
        out[c] = {"table": t, "monotonic20": monotonic(t, 20), "monotonic5": monotonic(t, 5)}
    return out


def to_markdown(rep: dict, title: str, keep=("평균", "중앙값", "승률")) -> str:
    """보기 쉬운 표: 구간 × (5/10/20/40일 평균·중앙값·승률) + 20일 복리 일평균·최대손실"""
    lines = [f"## {title}"]
    for c, r in rep.items():
        t = r["table"]
        cols = [k for k in t.columns if any(k.endswith(s) for s in keep)]
        extra = [k for k in ("20일 일평균(복리)", "20일 일평균(단순)", "20일 최대손실 평균") if k in t]
        lines.append(f"\n### {c}  (점수↑ → 20일 수익↑ 정도: {r['monotonic20']}, -1~+1)")
        lines.append(_md(t[["건수", *cols, *extra]]))
    return "\n".join(lines)
