from __future__ import annotations

import numpy as np
import pandas as pd

from llm_trader.costs import CostModel
from llm_trader.data.symbols import SymbolSpec
from llm_trader.eval.backtest import Market, market_arrays, simulate_arrays
from llm_trader.eval.windows import contains, in_window
from llm_trader.models import DEFAULT_LABELS, Labels, RandomBaseline, Trade, utc
from llm_trader.signals.base import atr

HIST_BINS = 25
NS_PER_DAY = 86_400 * 10**9


def empirical_p_value(replicas, observed: float) -> float:
    values = np.asarray(replicas, dtype=float)
    values = values[np.isfinite(values)]
    return float((1 + np.count_nonzero(values >= observed)) / (len(values) + 1))


def empty_baseline() -> RandomBaseline:
    return RandomBaseline(0, 1.0, 1.0, None, None, None, None, {"bin_edges": [], "counts": []})


def atr_at_open(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    # ATR as known when a bar opens: computed through the previous bar's close only.
    return np.r_[np.nan, atr(df, period)[:-1]]


def entry_day(trade: Trade) -> int:
    return utc(trade.entry_time).as_unit("ns").value // NS_PER_DAY


def window_days(df: pd.DataFrame, window) -> np.ndarray:
    times = df.index.as_unit("ns").asi8
    return np.unique(times[in_window(times, *window)] // NS_PER_DAY)


def _replicas_for_symbol(
    df: pd.DataFrame, spec: SymbolSpec, cost_model: CostModel, trades: list[Trade], window, real_days: np.ndarray,
    drawn_days: np.ndarray, labels: Labels, atr_period: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    runs = len(drawn_days)
    zeros = np.zeros(runs)
    m: Market = market_arrays(df, spec, cost_model)
    scale = atr_at_open(df, atr_period)
    entry_ns = np.array([utc(t.entry_time).as_unit("ns").value for t in trades], dtype=np.int64)
    real = np.searchsorted(m.times_ns, entry_ns)
    ref = m.open[real]
    with np.errstate(divide="ignore", invalid="ignore"):
        stop_mult = np.abs(ref - np.array([t.stop for t in trades])) / scale[real]
        target_mult = np.abs(np.array([np.nan if t.target is None else t.target for t in trades]) - ref) / scale[real]
    usable = np.isfinite(stop_mult) & (stop_mult > 0)
    if not usable.any():
        return zeros, zeros.copy(), zeros.copy()
    keep = np.flatnonzero(usable)
    entry_ns, stop_mult, target_mult = entry_ns[keep], stop_mult[keep], target_mult[keep]
    hold = np.array([trades[i].max_hold_bars for i in keep], dtype=np.int64)
    # Same direction as the real trade: only the timing is random, so trend alone cannot look like skill.
    sides = np.array([trades[i].side for i in keep], dtype=np.int64)
    be_r = np.array([trades[i].meta.get("breakeven_at_r", np.nan) for i in keep], dtype=float)
    be_off = np.array([trades[i].meta.get("breakeven_offset_r", 0.0) for i in keep], dtype=float)

    day = entry_ns // NS_PER_DAY
    shift = drawn_days[:, np.searchsorted(real_days, day)] - day[None, :]
    target_ns = entry_ns[None, :] + shift * NS_PER_DAY
    idx = np.minimum(np.searchsorted(m.times_ns, target_ns), m.bars - 1)
    # Same time of day on the drawn day; a time with no bar there (market closed) is left out of that replica.
    ok = (
        (m.times_ns[idx] == target_ns) & in_window(target_ns, *window) & np.isfinite(scale[idx]) & (scale[idx] > 0)
        & (idx + hold[None, :] <= m.bars)
    )
    replica, member = np.nonzero(ok)
    if len(replica) == 0:
        return zeros, zeros.copy(), zeros.copy()
    entry = idx[replica, member]
    side = sides[member]
    open_px, atr_px = m.open[entry], scale[entry]
    res = simulate_arrays(
        m, entry, side, open_px - side * stop_mult[member] * atr_px, open_px + side * target_mult[member] * atr_px,
        hold[member], cost_model.slippage_price(spec), cost_model.commission_price(spec), be_r[member], be_off[member],
    )
    total_r = np.bincount(replica, weights=np.where(res.valid, res.r, 0.0), minlength=runs)
    total_wins = np.bincount(replica, weights=res.wins(labels).astype(float), minlength=runs)
    total_n = np.bincount(replica, weights=res.valid.astype(float), minlength=runs)
    return total_r, total_wins, total_n


def random_baseline(
    df_by_symbol: dict[str, pd.DataFrame], trades: list[Trade], window, spec_by_symbol: dict[str, SymbolSpec],
    cost_model: CostModel, runs: int = 1000, seed: int = 0, labels: Labels | None = None, atr_period: int = 14,
) -> RandomBaseline:
    start, end = window
    picked = [t for t in trades if contains(start, end, t.entry_time)]
    if not picked or runs <= 0:
        return empty_baseline()
    observed_expectancy = float(np.mean([t.r for t in picked]))
    observed_win_rate = float(np.mean([t.win for t in picked]))
    labels = labels or DEFAULT_LABELS
    rng = np.random.default_rng(seed)
    symbols = sorted({t.symbol for t in picked})
    # Each replica maps every real trading day to one random day of the window, shared by all symbols, so trades that
    # bunch up on one day (re-entries, several symbols at once) stay bunched and the replicas are as noisy as the rule.
    real_days = np.unique([entry_day(t) for t in picked])
    pool = np.unique(np.concatenate([window_days(df_by_symbol[s], window) for s in symbols]))
    if len(pool) == 0:
        return empty_baseline()
    drawn_days = pool[rng.integers(0, len(pool), size=(runs, len(real_days)))]
    total_r, total_wins, total_n = np.zeros(runs), np.zeros(runs), np.zeros(runs)
    for symbol in symbols:
        group = [t for t in picked if t.symbol == symbol]
        r, wins, n = _replicas_for_symbol(
            df_by_symbol[symbol], spec_by_symbol[symbol], cost_model, group, window, real_days, drawn_days, labels, atr_period,
        )
        total_r += r
        total_wins += wins
        total_n += n
    ok = total_n > 0
    if not ok.any():
        return empty_baseline()
    expectancy = total_r[ok] / total_n[ok]
    win_rate = total_wins[ok] / total_n[ok]
    counts, edges = np.histogram(expectancy, bins=HIST_BINS)
    return RandomBaseline(
        runs=int(ok.sum()),
        p_value=empirical_p_value(expectancy, observed_expectancy),
        p_value_win_rate=empirical_p_value(win_rate, observed_win_rate),
        expectancy_mean=float(expectancy.mean()),
        expectancy_p95=float(np.percentile(expectancy, 95)),
        win_rate_mean=float(win_rate.mean()),
        win_rate_p95=float(np.percentile(win_rate, 95)),
        hist={"bin_edges": edges.tolist(), "counts": counts.tolist()},
    )
