from __future__ import annotations

import numpy as np
import pandas as pd

from llm_trader.models import Signal
from llm_trader.signals.base import SignalRule, atr, column, first_in_block, previous_day_levels


def sweep_fade_arrays(df: pd.DataFrame, params: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    high, low, close = column(df, "high"), column(df, "low"), column(df, "close")
    prev_high, prev_low, day = previous_day_levels(df, params["min_day_bars"])
    a = atr(df, params["atr_period"])
    swept_high = (high > prev_high) & (close < prev_high)
    swept_low = (low < prev_low) & (close > prev_low)
    short = first_in_block(swept_high, day) & ~swept_low
    long = first_in_block(swept_low, day) & ~swept_high
    side = np.where(short, -1, np.where(long, 1, 0)) * np.isfinite(a)
    buffer = params["stop_buffer_atr"] * a
    stop = np.where(side < 0, high + buffer, low - buffer)
    target = close + side * params["target_r"] * np.abs(close - stop)
    return side, stop, target


class SweepFade(SignalRule):
    rule_id = "sweep_fade"
    name = "Sweep Fade (demo)"
    default_symbols = ("XAUUSD", "EURUSD")
    description = (
        "When a bar pokes above the previous day's high but closes back below it, sell at the next bar's open "
        "(mirror for the previous day's low). Stop a little beyond the sweep's extreme, target 1R, exit after "
        "16 bars at most. One trade per side per day."
    )
    demo_note = (
        "Same logic as the planted self-test, but on symbols with no hidden pattern. It should look like random "
        "entries, and the gate should say so."
    )
    default_params = {"min_day_bars": 16, "stop_buffer_atr": 0.25, "target_r": 1.0, "max_hold_bars": 16, "atr_period": 14}

    def generate(self, df: pd.DataFrame, symbol: str) -> list[Signal]:
        side, stop, target = sweep_fade_arrays(df, self.params)
        return self.signals_from_arrays(df, symbol, side, stop, target, self.params["max_hold_bars"])
