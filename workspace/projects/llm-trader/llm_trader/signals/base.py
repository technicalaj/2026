from __future__ import annotations

import copy

import numpy as np
import pandas as pd

from llm_trader.models import Signal, timeframe_delta

NS_PER_DAY = 86_400 * 10**9


def index_ns(df: pd.DataFrame) -> np.ndarray:
    return df.index.as_unit("ns").asi8


def day_codes(df: pd.DataFrame) -> np.ndarray:
    return index_ns(df) // NS_PER_DAY


def column(df: pd.DataFrame, name: str) -> np.ndarray:
    return df[name].to_numpy(dtype=float)


def ema(values: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(values).ewm(span=span, adjust=False, min_periods=span).mean().to_numpy()


def wilder(values: np.ndarray, period: int, min_periods: int | None = None) -> np.ndarray:
    return pd.Series(values).ewm(alpha=1.0 / period, adjust=False, min_periods=min_periods or period).mean().to_numpy()


def atr(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    high, low, close = column(df, "high"), column(df, "low"), column(df, "close")
    prev = np.r_[np.nan, close[:-1]]
    true_range = np.fmax(high - low, np.fmax(np.abs(high - prev), np.abs(low - prev)))
    return wilder(true_range, period)


def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    delta = np.diff(close, prepend=np.nan)
    gain = wilder(np.where(delta > 0, delta, 0.0), period, period + 1)
    loss = wilder(np.where(delta < 0, -delta, 0.0), period, period + 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        value = 100.0 - 100.0 / (1.0 + gain / loss)
    return np.where(loss == 0, np.where(gain > 0, 100.0, 50.0), value)


def day_blocks(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    days = day_codes(df)
    starts = np.flatnonzero(np.r_[True, days[1:] != days[:-1]])
    bar_block = np.repeat(np.arange(len(starts)), np.diff(np.r_[starts, len(days)]))
    return starts, bar_block


def previous_day_levels(df: pd.DataFrame, min_bars: int = 16) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    starts, bar_block = day_blocks(df)
    if len(df) == 0:
        empty = np.array([], dtype=float)
        return empty, empty, bar_block
    high, low = column(df, "high"), column(df, "low")
    day_high = np.maximum.reduceat(high, starts)
    day_low = np.minimum.reduceat(low, starts)
    full_days = np.flatnonzero(np.diff(np.r_[starts, len(df)]) >= min_bars)
    prev = np.searchsorted(full_days, np.arange(len(starts)), side="left") - 1
    has_prev = prev >= 0
    pick = full_days[np.clip(prev, 0, None)] if len(full_days) else np.zeros(len(starts), dtype=int)
    prev_high = np.where(has_prev, day_high[pick], np.nan)
    prev_low = np.where(has_prev, day_low[pick], np.nan)
    return prev_high[bar_block], prev_low[bar_block], bar_block


def first_in_block(mask: np.ndarray, block: np.ndarray) -> np.ndarray:
    counts = pd.Series(mask.astype(np.int64)).groupby(block).cumsum().to_numpy()
    return mask & (counts == 1)


def apply_cooldown(mask: np.ndarray, bars: int) -> np.ndarray:
    out = np.zeros_like(mask)
    last = -bars - 1
    for i in np.flatnonzero(mask):
        if i - last > bars:
            out[i] = True
            last = i
    return out


class SignalRule:
    rule_id = ""
    name = ""
    version = "1"
    timeframe = "M15"
    description = ""
    demo_note = ""
    control = False
    default_symbols: tuple[str, ...] = ()
    default_params: dict = {}

    def __init__(self, params: dict | None = None, symbols: list[str] | None = None):
        self.params = {**copy.deepcopy(self.default_params), **(params or {})}
        self.symbols = list(symbols if symbols is not None else self.default_symbols)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(rule_id={self.rule_id!r}, version={self.version!r})"

    def generate(self, df: pd.DataFrame, symbol: str) -> list[Signal]:
        raise NotImplementedError

    def signals_from_arrays(
        self, df: pd.DataFrame, symbol: str, side: np.ndarray, stop: np.ndarray, target: np.ndarray,
        max_hold_bars: int, meta: dict | None = None,
    ) -> list[Signal]:
        side = np.asarray(side)
        ok = (side != 0) & np.isfinite(stop)
        rows = np.flatnonzero(ok)
        close_times = df.index[rows] + timeframe_delta(self.timeframe)
        out = []
        for i, t in zip(rows, close_times):
            tgt = float(target[i])
            out.append(
                Signal(
                    rule_id=self.rule_id,
                    symbol=symbol,
                    time=t,
                    side=int(side[i]),
                    stop=float(stop[i]),
                    target=tgt if np.isfinite(tgt) else None,
                    max_hold_bars=int(max_hold_bars),
                    meta=dict(meta or {}),
                )
            )
        return out
