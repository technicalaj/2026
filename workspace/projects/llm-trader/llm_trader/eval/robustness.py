from __future__ import annotations

import numpy as np
import pandas as pd

from llm_trader.eval.metrics import clustered_mean_interval
from llm_trader.eval.random_baseline import atr_at_open, entry_day
from llm_trader.eval.windows import in_window
from llm_trader.models import Trade, WindowExtra

TERCILE_NAMES = ("low", "mid", "high")
STRESS_COSTS = 1.5
DISPLAY_COSTS = 2.0
# Below this many development trades on a symbol, its cut points come from every development bar instead.
MIN_CUT_TRADES = 30
Cuts = tuple[float, float] | None


def _mean(values) -> float | None:
    return float(np.mean(values)) if len(values) else None


def side_summary(trades: list[Trade]) -> dict:
    n = len(trades)
    return {
        "trades": n,
        "win_rate": sum(t.win for t in trades) / n if n else None,
        "expectancy_r": _mean([t.r for t in trades]),
    }


def tercile_cuts(values) -> Cuts:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 3:
        return None
    lo, hi = np.quantile(x, [1 / 3, 2 / 3])
    return float(lo), float(hi)


def volatility_cuts(dev_trades: list[Trade], frames: dict[str, pd.DataFrame], dev_window) -> dict[str, Cuts]:
    cuts = {}
    for symbol, df in frames.items():
        values = [t.entry_atr for t in dev_trades if t.symbol == symbol and t.entry_atr is not None]
        if np.isfinite(values).sum() < MIN_CUT_TRADES:
            values = atr_at_open(df)[in_window(df.index.as_unit("ns").asi8, *dev_window)]
        cuts[symbol] = tercile_cuts(values)
    return cuts


def tercile_of(value: float | None, cuts: Cuts) -> int | None:
    if cuts is None or value is None or not np.isfinite(value):
        return None
    return int(np.searchsorted(cuts, value, side="right"))


def tercile_results(trades: list[Trade], cuts: dict[str, Cuts]) -> list[dict]:
    groups: list[list[float]] = [[], [], []]
    for t in trades:
        k = tercile_of(t.entry_atr, cuts.get(t.symbol))
        if k is not None:
            groups[k].append(t.r)
    return [{"name": name, "trades": len(r), "expectancy_r": _mean(r)} for name, r in zip(TERCILE_NAMES, groups)]


def positive_terciles(terciles: list[dict], min_trades: int) -> int:
    return sum(1 for t in terciles if t["trades"] >= min_trades and t["expectancy_r"] is not None and t["expectancy_r"] > 0)


def stop_target_ratio(trades: list[Trade]) -> float | None:
    # Measured from the signal bar's close, where the rule set its stop and target, so costs do not distort it.
    ratios = [
        abs(t.signal_price - t.stop) / abs(t.target - t.signal_price)
        for t in trades
        if t.target is not None and t.signal_price is not None and t.target != t.signal_price
    ]
    return float(np.median(ratios)) if ratios else None


def window_extra(trades: list[Trade], stressed_r: list[float], display_r: list[float], cuts: dict[str, Cuts]) -> WindowExtra:
    return WindowExtra(
        expectancy_ci=clustered_mean_interval([t.r for t in trades], [entry_day(t) for t in trades]) or (None, None),
        expectancy_1_5x_costs=_mean(stressed_r),
        expectancy_2x_costs=_mean(display_r),
        long=side_summary([t for t in trades if t.side > 0]),
        short=side_summary([t for t in trades if t.side < 0]),
        terciles=tercile_results(trades, cuts),
        stop_target_ratio=stop_target_ratio(trades),
    )
