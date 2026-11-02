from __future__ import annotations

import math

import numpy as np

from llm_trader.eval.windows import contains
from llm_trader.models import Trade, WindowMetrics, utc

Z95 = 1.959963984540054
# Student t 97.5% quantiles for 1-4 degrees of freedom; above that the Cornish-Fisher series is within 3e-4.
T975_SMALL = {1: 12.7062047, 2: 4.3026527, 3: 3.1824463, 4: 2.7764451}


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


def t_quantile_975(dof: int) -> float:
    if dof < 1:
        raise ValueError("t quantile needs at least 1 degree of freedom")
    if dof in T975_SMALL:
        return T975_SMALL[dof]
    z, v = Z95, float(dof)
    return (
        z
        + (z**3 + z) / (4 * v)
        + (5 * z**5 + 16 * z**3 + 3 * z) / (96 * v**2)
        + (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / (384 * v**3)
        + (79 * z**9 + 776 * z**7 + 1482 * z**5 - 1920 * z**3 - 945 * z) / (92160 * v**4)
    )


def clustered_mean_interval(values, clusters) -> tuple[float, float] | None:
    x = np.asarray(values, dtype=float)
    n = len(x)
    if n < 2:
        return None
    _, group = np.unique(np.asarray(clusters), return_inverse=True)
    g = int(group.max()) + 1
    if g < 2:
        return None
    mean = float(x.mean())
    # Cluster-robust (CR1) error: trades on the same day share one draw of luck. One trade per day gives s / sqrt(n).
    sums = np.bincount(group, weights=x - mean, minlength=g)
    half = t_quantile_975(g - 1) * math.sqrt(g / (g - 1) * float(np.sum(sums**2))) / n
    return (mean - half, mean + half)


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
        return WindowMetrics(*bounds, 0, 0, 0, None, (0.0, 1.0), None, None, None, None, 0.0, None, [])
    r = np.array([t.r for t in picked])
    wins = sum(1 for t in picked if t.label == "win")
    gross_loss = -r[r < 0].sum()
    return WindowMetrics(
        start=bounds[0],
        end=bounds[1],
        trades=n,
        wins=wins,
        losses=sum(1 for t in picked if t.label == "loss"),
        win_rate=wins / n,
        win_rate_ci=wilson_interval(wins, n),
        full_stop_rate=sum(1 for t in picked if t.full_stop) / n,
        breakeven_rate=sum(1 for t in picked if t.label == "breakeven") / n,
        expectancy_r=float(r.mean()),
        profit_factor=float(r[r > 0].sum() / gross_loss) if gross_loss > 0 else None,
        max_drawdown_r=max_drawdown(r),
        avg_hold_bars=float(np.mean([t.hold_bars for t in picked])),
        equity_r=[round(v, 4) for v in np.cumsum(r).tolist()],
    )
