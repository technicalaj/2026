from __future__ import annotations

import math

import numpy as np

from llm_trader.eval.windows import contains
from llm_trader.models import Trade, WindowMetrics, utc

Z95 = 1.959963984540054


def wilson_interval(wins: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lo = 0.0 if wins <= 0 else max(0.0, center - half)
    hi = 1.0 if wins >= n else min(1.0, center + half)
    return (lo, hi)


def max_drawdown(r_values) -> float:
    curve = np.concatenate([[0.0], np.cumsum(np.asarray(r_values, dtype=float))])
    return float((np.maximum.accumulate(curve) - curve).max())


def window_trades(trades: list[Trade], start, end) -> list[Trade]:
    return [t for t in trades if contains(start, end, t.entry_time)]


def window_metrics(trades: list[Trade], start, end) -> WindowMetrics:
    picked = sorted(window_trades(trades, start, end), key=lambda t: (t.exit_time, t.entry_time))
    n = len(picked)
    bounds = (None if start is None else utc(start), None if end is None else utc(end))
    if n == 0:
        return WindowMetrics(*bounds, 0, 0, None, (0.0, 1.0), None, None, None, None, 0.0, None, [])
    r = np.array([t.r for t in picked])
    wins = sum(1 for t in picked if t.win)
    losses = -r[r < 0].sum()
    return WindowMetrics(
        start=bounds[0],
        end=bounds[1],
        trades=n,
        wins=wins,
        win_rate=wins / n,
        win_rate_ci=wilson_interval(wins, n),
        full_stop_rate=sum(1 for t in picked if t.outcome == "stop") / n,
        breakeven_rate=sum(1 for t in picked if t.outcome == "breakeven") / n,
        expectancy_r=float(r.mean()),
        profit_factor=float(r[r > 0].sum() / losses) if losses > 0 else None,
        max_drawdown_r=max_drawdown(r),
        avg_hold_bars=float(np.mean([t.hold_bars for t in picked])),
        equity_r=[round(v, 4) for v in np.cumsum(r).tolist()],
    )
