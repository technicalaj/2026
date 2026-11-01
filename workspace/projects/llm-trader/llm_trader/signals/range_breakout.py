from __future__ import annotations

import numpy as np
import pandas as pd

from llm_trader.models import Signal
from llm_trader.signals.base import SignalRule, atr, column, day_blocks, first_in_block


class RangeBreakout(SignalRule):
    rule_id = "range_breakout"
    name = "Range Breakout (demo)"
    default_symbols = ("XAUUSD", "GBPUSD", "US500")
    description = (
        "Marks the Asian range (00:00-07:00 UTC). The first bar between 07:00 and 11:00 UTC that closes outside "
        "it triggers a trade in that direction at the next bar's open. Stop at the other side of the range "
        "(never more than 1.5x ATR), target 1.5R, exit after 32 bars at most. One trade per day."
    )
    demo_note = "A popular textbook idea. On data without a real edge it should be no better than random entries."
    default_params = {
        "range_start_hour": 0,
        "range_end_hour": 7,
        "entry_end_hour": 11,
        "min_range_bars": 20,
        "stop_cap_atr": 1.5,
        "target_r": 1.5,
        "max_hold_bars": 32,
        "atr_period": 14,
    }

    def generate(self, df: pd.DataFrame, symbol: str) -> list[Signal]:
        p = self.params
        if len(df) == 0:
            return []
        hour = df.index.hour.to_numpy()
        high, low, close = column(df, "high"), column(df, "low"), column(df, "close")
        starts, day = day_blocks(df)
        in_range = (hour >= p["range_start_hour"]) & (hour < p["range_end_hour"])
        range_high = np.maximum.reduceat(np.where(in_range, high, -np.inf), starts)[day]
        range_low = np.minimum.reduceat(np.where(in_range, low, np.inf), starts)[day]
        range_bars = np.add.reduceat(in_range.astype(np.int64), starts)[day]
        # The day's range is only read after range_end_hour, when every bar in it is already closed.
        window = (hour >= p["range_end_hour"]) & (hour < p["entry_end_hour"]) & (range_bars >= p["min_range_bars"])
        a = atr(df, p["atr_period"])
        up = window & (close > range_high)
        down = window & (close < range_low)
        first = first_in_block(up | down, day)
        side = np.where(first & up, 1, np.where(first & down, -1, 0)) * np.isfinite(a)
        distance = np.where(side != 0, np.minimum(np.where(side > 0, close - range_low, range_high - close), p["stop_cap_atr"] * a), np.nan)
        stop = close - side * distance
        target = close + side * p["target_r"] * distance
        return self.signals_from_arrays(df, symbol, side, stop, target, p["max_hold_bars"])
