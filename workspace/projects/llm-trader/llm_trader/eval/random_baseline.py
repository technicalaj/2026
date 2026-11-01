from __future__ import annotations

import numpy as np
import pandas as pd

from llm_trader.costs import CostModel
from llm_trader.data.symbols import SymbolSpec
from llm_trader.eval.backtest import Market, market_arrays, simulate_arrays
from llm_trader.eval.windows import contains, in_window
from llm_trader.models import RandomBaseline, Trade, utc
from llm_trader.signals.base import atr

HIST_BINS = 25
MATCH_MINUTES = 60


def empirical_p_value(replicas, observed: float) -> float:
    values = np.asarray(replicas, dtype=float)
    values = values[np.isfinite(values)]
    return float((1 + np.count_nonzero(values >= observed)) / (len(values) + 1))


def empty_baseline() -> RandomBaseline:
    return RandomBaseline(0, 1.0, 1.0, None, None, None, None, {"bin_edges": [], "counts": []})


def atr_at_open(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    # ATR as known when a bar opens: computed through the previous bar's close only.
    return np.r_[np.nan, atr(df, period)[:-1]]


def _minutes_apart(minute_of_day: np.ndarray, minute: int) -> np.ndarray:
    return np.abs((minute_of_day - minute + 720) % 1440 - 720)


def _replicas_for_symbol(
    rng: np.random.Generator, df: pd.DataFrame, spec: SymbolSpec, cost_model: CostModel, trades: list[Trade],
    window, runs: int, win_epsilon_r: float, atr_period: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    m: Market = market_arrays(df, spec, cost_model)
    scale = atr_at_open(df, atr_period)
    minute_of_day = (df.index.hour * 60 + df.index.minute).to_numpy()
    real = np.searchsorted(m.times_ns, [utc(t.entry_time).as_unit("ns").value for t in trades])
    ref = m.open[real]
    with np.errstate(divide="ignore", invalid="ignore"):
        stop_mult = np.abs(ref - np.array([t.stop for t in trades])) / scale[real]
        target_mult = np.abs(np.array([np.nan if t.target is None else t.target for t in trades]) - ref) / scale[real]
    hold = np.array([t.max_hold_bars for t in trades])
    be_r = np.array([t.meta.get("breakeven_at_r", np.nan) for t in trades], dtype=float)
    be_off = np.array([t.meta.get("breakeven_offset_r", 0.0) for t in trades], dtype=float)
    usable = np.isfinite(stop_mult) & (stop_mult > 0)

    eligible = in_window(m.times_ns, *window) & np.isfinite(scale) & (scale > 0) & (np.arange(m.bars) + hold.max() <= m.bars)
    candidates = np.flatnonzero(eligible)
    zeros = np.zeros(runs)
    if len(candidates) == 0 or not usable.any():
        return zeros, zeros.copy(), zeros.copy()
    candidate_minutes = minute_of_day[candidates]
    trade_minutes = minute_of_day[real]
    parts = {k: [] for k in ("entry", "side", "stop", "target", "hold", "be_r", "be_off", "replica")}
    for minute in np.unique(trade_minutes[usable]):
        members = np.flatnonzero(usable & (trade_minutes == minute))
        # Centred on the trade's own time of day, so intraday volatility and spread patterns cancel out.
        near = _minutes_apart(candidate_minutes, minute) <= MATCH_MINUTES
        pool = candidates[near] if near.any() else candidates
        k = len(members)
        entry = pool[rng.integers(0, len(pool), size=(runs, k))]
        side = rng.integers(0, 2, size=(runs, k)) * 2 - 1
        open_px, atr_px = m.open[entry], scale[entry]
        parts["entry"].append(entry.ravel())
        parts["side"].append(side.ravel())
        parts["stop"].append((open_px - side * stop_mult[members] * atr_px).ravel())
        parts["target"].append((open_px + side * target_mult[members] * atr_px).ravel())
        parts["hold"].append(np.broadcast_to(hold[members], (runs, k)).ravel())
        parts["be_r"].append(np.broadcast_to(be_r[members], (runs, k)).ravel())
        parts["be_off"].append(np.broadcast_to(be_off[members], (runs, k)).ravel())
        parts["replica"].append(np.repeat(np.arange(runs), k))
    flat = {k: np.concatenate(v) for k, v in parts.items()}
    res = simulate_arrays(
        m, flat["entry"], flat["side"], flat["stop"], flat["target"], flat["hold"],
        cost_model.slippage_price(spec), cost_model.commission_price(spec), flat["be_r"], flat["be_off"],
    )
    ids = flat["replica"]
    total_r = np.bincount(ids, weights=np.where(res.valid, res.r, 0.0), minlength=runs)
    total_wins = np.bincount(ids, weights=res.wins(win_epsilon_r).astype(float), minlength=runs)
    total_n = np.bincount(ids, weights=res.valid.astype(float), minlength=runs)
    return total_r, total_wins, total_n


def random_baseline(
    df_by_symbol: dict[str, pd.DataFrame], trades: list[Trade], window, spec_by_symbol: dict[str, SymbolSpec],
    cost_model: CostModel, runs: int = 1000, seed: int = 0, win_epsilon_r: float = 0.05, atr_period: int = 14,
) -> RandomBaseline:
    start, end = window
    picked = [t for t in trades if contains(start, end, t.entry_time)]
    if not picked or runs <= 0:
        return empty_baseline()
    observed_expectancy = float(np.mean([t.r for t in picked]))
    observed_win_rate = float(np.mean([t.win for t in picked]))
    rng = np.random.default_rng(seed)
    total_r, total_wins, total_n = np.zeros(runs), np.zeros(runs), np.zeros(runs)
    for symbol in sorted({t.symbol for t in picked}):
        group = [t for t in picked if t.symbol == symbol]
        r, wins, n = _replicas_for_symbol(rng, df_by_symbol[symbol], spec_by_symbol[symbol], cost_model, group, window, runs, win_epsilon_r, atr_period)
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
