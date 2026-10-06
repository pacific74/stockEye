"""성과 지표."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def max_consecutive(flags: list[bool]) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def compute_metrics(trades, equity: pd.Series, bench: pd.Series | None = None) -> dict:
    n = len(trades)
    rets = np.array([t.net_ret for t in trades]) if n else np.array([])
    wins, losses = rets[rets > 0], rets[rets <= 0]
    m = {
        "trades": n,
        "win_rate": round(len(wins) / n * 100, 1) if n else None,
        "avg_win_pct": round(wins.mean() * 100, 2) if len(wins) else None,
        "avg_loss_pct": round(losses.mean() * 100, 2) if len(losses) else None,
        "expectancy_pct": round(rets.mean() * 100, 2) if n else None,     # 1회 매매 기대수익
        "profit_factor": round(wins.sum() / -losses.sum(), 2) if len(losses) and losses.sum() < 0 else None,
        "max_consec_losses": max_consecutive([r <= 0 for r in rets]),
        "avg_hold_days": round(float(np.mean([t.hold_days for t in trades])), 1) if n else None,
    }
    if n:
        reasons = pd.Series([t.reason for t in trades]).value_counts()
        m["exit_reasons"] = {k: int(v) for k, v in reasons.items()}
    if equity is not None and len(equity) > 1:
        e = equity.astype(float)
        dd = e / e.cummax() - 1
        daily = e.pct_change().dropna()
        years = max((e.index[-1] - e.index[0]).days / 365.25, 1e-9)
        total = e.iloc[-1] / e.iloc[0] - 1
        m.update({
            "total_return_pct": round(total * 100, 1),
            "cagr_pct": round(((1 + total) ** (1 / years) - 1) * 100, 1) if total > -1 else -100.0,
            "mdd_pct": round(dd.min() * 100, 1),
            "sharpe": round(daily.mean() / daily.std() * math.sqrt(252), 2) if daily.std() > 0 else None,
        })
        if bench is not None:
            b = bench.reindex(e.index).dropna()
            if len(b) > 1:
                m["benchmark_return_pct"] = round((b.iloc[-1] / b.iloc[0] - 1) * 100, 1)
    return {k: (float(v) if isinstance(v, np.floating) else int(v) if isinstance(v, np.integer) else v)
            for k, v in m.items()}
