from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from llm_trader.costs import CostModel
from llm_trader.data.symbols import SymbolSpec
from llm_trader.models import Signal, Trade, iso, utc

TARGET, STOP, BREAKEVEN, TIME = 0, 1, 2, 3
OUTCOME_NAMES = ("target", "stop", "breakeven", "time")
CHUNK_CELLS = 1_000_000
DEFAULT_BAR_NS = 15 * 60 * 10**9


class SignalRejected(ValueError):
    pass


@dataclass(frozen=True)
class Market:
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    spread: np.ndarray
    times_ns: np.ndarray
    bar_ns: int

    @property
    def bars(self) -> int:
        return len(self.open)


@dataclass
class SimResult:
    valid: np.ndarray
    exit_offset: np.ndarray
    entry: np.ndarray
    exit: np.ndarray
    outcome: np.ndarray
    r: np.ndarray
    costs_r: np.ndarray
    risk: np.ndarray

    @classmethod
    def empty(cls, k: int) -> "SimResult":
        nan = np.full(k, np.nan)
        return cls(np.zeros(k, bool), np.zeros(k, np.int64), nan.copy(), nan.copy(), np.full(k, TIME, np.int8), nan.copy(), nan.copy(), nan.copy())

    def wins(self, win_epsilon_r: float) -> np.ndarray:
        return self.valid & (self.r > win_epsilon_r) & (self.outcome != BREAKEVEN)


def infer_bar_ns(times_ns: np.ndarray) -> int:
    if len(times_ns) < 2:
        return DEFAULT_BAR_NS
    values, counts = np.unique(np.diff(times_ns[:5001]), return_counts=True)
    return int(values[counts.argmax()])


def market_arrays(df: pd.DataFrame, spec: SymbolSpec, cost_model: CostModel) -> Market:
    times_ns = df.index.as_unit("ns").asi8
    return Market(
        open=df["open"].to_numpy(dtype=float),
        high=df["high"].to_numpy(dtype=float),
        low=df["low"].to_numpy(dtype=float),
        close=df["close"].to_numpy(dtype=float),
        spread=cost_model.spread_price(df, spec),
        times_ns=times_ns,
        bar_ns=infer_bar_ns(times_ns),
    )


def _first_true(mask: np.ndarray, default: int) -> np.ndarray:
    return np.where(mask.any(axis=1), mask.argmax(axis=1), default)


def _simulate_chunk(m: Market, e, side, stop, target, hold, slip, comm, be_r, be_off) -> tuple:
    n_bars = m.bars
    in_data = (e >= 0) & (e < n_bars)
    e = np.clip(e, 0, n_bars - 1)
    open_bid = m.open[e]
    open_ask = open_bid + m.spread[e]
    long = side > 0
    entry = np.where(long, open_ask + slip, open_bid - slip)
    has_target = np.isfinite(target)
    # Broker rule: a buy needs stop < bid < target, a sell needs target < ask < stop; otherwise it is rejected.
    ok_long = (stop < open_bid) & (~has_target | (target > open_bid))
    ok_short = (stop > open_ask) & (~has_target | (target < open_ask))
    valid = in_data & (hold >= 1) & np.where(long, ok_long, ok_short)
    risk = np.abs(entry - stop)

    width = max(1, int(hold.max()))
    offsets = np.arange(width)
    idx = e[:, None] + offsets
    active = (idx < n_bars) & (offsets < hold[:, None])
    idx = np.minimum(idx, n_bars - 1)
    high, low, spread = m.high[idx], m.low[idx], m.spread[idx]
    s = side[:, None]
    is_long = long[:, None]
    adverse = np.where(is_long, low, high + spread)
    favorable = np.where(is_long, high, low + spread)
    stop_hit = active & (s * (stop[:, None] - adverse) >= 0)
    target_hit = active & (s * (favorable - target[:, None]) >= 0)

    trigger_at = np.full(len(e), width)
    be_stop = np.full(len(e), np.nan)
    has_be = np.isfinite(be_r)
    if has_be.any():
        trigger_px = entry + side * be_r * risk
        triggered = active & has_be[:, None] & (s * (favorable - trigger_px[:, None]) >= 0)
        trigger_at = _first_true(triggered, width)
        be_stop = entry + side * np.nan_to_num(be_off) * risk
        be_hit = active & (s * (be_stop[:, None] - adverse) >= 0)
        # The stop moves only after the trigger bar has closed.
        stop_hit = np.where(offsets[None, :] > trigger_at[:, None], be_hit, stop_hit)

    first_stop = _first_true(stop_hit, width)
    first_target = _first_true(target_hit, width)
    stopped = (first_stop < width) & (first_stop <= first_target)
    hit_target = ~stopped & (first_target < width)
    timed = ~stopped & ~hit_target
    valid &= ~timed | (e + hold - 1 < n_bars)

    exit_offset = np.clip(np.where(stopped, first_stop, np.where(hit_target, first_target, hold - 1)), 0, width - 1)
    x = np.minimum(e + exit_offset, n_bars - 1)
    exit_open, exit_close, exit_spread = m.open[x], m.close[x], m.spread[x]
    breakeven = stopped & (first_stop > trigger_at)
    level = np.where(breakeven, be_stop, stop)
    stop_fill = np.where(long, np.minimum(level, exit_open) - slip, np.maximum(level, exit_open + exit_spread) + slip)
    time_fill = np.where(long, exit_close - slip, exit_close + exit_spread + slip)
    exit_px = np.where(stopped, stop_fill, np.where(hit_target, target, time_fill))
    with np.errstate(divide="ignore", invalid="ignore"):
        r = side * (exit_px - entry) / risk - comm / risk
        spread_paid = np.where(long, m.spread[e], exit_spread)
        market_fills = 1 + (~hit_target).astype(np.int64)
        costs_r = (spread_paid + slip * market_fills + comm) / risk
    outcome = np.where(stopped, np.where(breakeven, BREAKEVEN, STOP), np.where(hit_target, TARGET, TIME)).astype(np.int8)
    return valid, exit_offset, entry, exit_px, outcome, r, costs_r, risk


def simulate_arrays(
    market: Market, entry_index, side, stop, target, hold, slippage: float, commission: float,
    breakeven_r=None, breakeven_offset_r=None,
) -> SimResult:
    entry_index = np.asarray(entry_index, dtype=np.int64)
    k = len(entry_index)
    out = SimResult.empty(k)
    if k == 0 or market.bars == 0:
        return out
    side = np.asarray(side, dtype=np.int64)
    stop = np.asarray(stop, dtype=float)
    target = np.asarray(target, dtype=float)
    hold = np.asarray(hold, dtype=np.int64)
    be_r = np.full(k, np.nan) if breakeven_r is None else np.asarray(breakeven_r, dtype=float)
    be_off = np.zeros(k) if breakeven_offset_r is None else np.asarray(breakeven_offset_r, dtype=float)
    rows = max(1, CHUNK_CELLS // max(1, int(hold.max())))
    for lo in range(0, k, rows):
        sl = slice(lo, lo + rows)
        parts = _simulate_chunk(market, entry_index[sl], side[sl], stop[sl], target[sl], hold[sl], slippage, commission, be_r[sl], be_off[sl])
        for name, values in zip(("valid", "exit_offset", "entry", "exit", "outcome", "r", "costs_r", "risk"), parts):
            getattr(out, name)[sl] = values
    return out


def check_signal(signal: Signal) -> None:
    where = f"{signal.rule_id} {signal.symbol} {iso(signal.time)}"
    if signal.stop is None or not np.isfinite(signal.stop):
        raise SignalRejected(f"{where}: signal has no stop-loss and is rejected")
    if signal.side not in (1, -1):
        raise SignalRejected(f"{where}: side must be +1 (long) or -1 (short)")
    if int(signal.max_hold_bars) < 1:
        raise SignalRejected(f"{where}: max_hold_bars must be at least 1")
    if signal.target is not None and (not np.isfinite(signal.target) or (signal.target - signal.stop) * signal.side <= 0):
        raise SignalRejected(f"{where}: target must be on the profit side of the stop")


def simulate(df: pd.DataFrame, signals: list[Signal], spec: SymbolSpec, cost_model: CostModel, win_epsilon_r: float = 0.05) -> list[Trade]:
    if not signals:
        return []
    for signal in signals:
        check_signal(signal)
    m = market_arrays(df, spec, cost_model)
    signal_ns = np.array([utc(s.time).as_unit("ns").value for s in signals], dtype=np.int64)
    entry_index = np.searchsorted(m.times_ns, signal_ns, side="left")
    res = simulate_arrays(
        m,
        entry_index,
        side=[s.side for s in signals],
        stop=[s.stop for s in signals],
        target=[np.nan if s.target is None else s.target for s in signals],
        hold=[s.max_hold_bars for s in signals],
        slippage=cost_model.slippage_price(spec),
        commission=cost_model.commission_price(spec),
        breakeven_r=[s.meta.get("breakeven_at_r", np.nan) for s in signals],
        breakeven_offset_r=[s.meta.get("breakeven_offset_r", 0.0) for s in signals],
    )
    wins = res.wins(win_epsilon_r)
    trades = []
    for i in np.flatnonzero(res.valid):
        s = signals[i]
        e = int(entry_index[i])
        x = e + int(res.exit_offset[i])
        trades.append(
            Trade(
                rule_id=s.rule_id,
                symbol=s.symbol,
                signal_time=utc(s.time),
                entry_time=pd.Timestamp(int(m.times_ns[e]), tz="UTC"),
                entry=float(res.entry[i]),
                stop=float(s.stop),
                target=s.target,
                side=int(s.side),
                exit_time=pd.Timestamp(int(m.times_ns[x]) + m.bar_ns, tz="UTC"),
                exit=float(res.exit[i]),
                outcome=OUTCOME_NAMES[int(res.outcome[i])],
                r=float(res.r[i]),
                risk_price=float(res.risk[i]),
                costs_r=float(res.costs_r[i]),
                hold_bars=int(res.exit_offset[i]) + 1,
                max_hold_bars=int(s.max_hold_bars),
                win=bool(wins[i]),
                meta=dict(s.meta),
            )
        )
    return trades
