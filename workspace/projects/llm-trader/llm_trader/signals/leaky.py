from __future__ import annotations

import numpy as np
import pandas as pd

from llm_trader.models import Signal
from llm_trader.signals.base import SignalRule, atr, column


class Leaky(SignalRule):
    rule_id = "leaky"
    name = "Leaky Rule (demo)"
    version = "2"
    self_test = True
    expected = "must be blocked"
    default_symbols = ("EURUSD",)
    description = (
        "At 08:00, 12:00 and 16:00 UTC, trades in the direction the market is 'about to' move. Stop 1× ATR, "
        "target 0.5R, exit after 16 bars at most."
    )
    demo_note = (
        "Planted bug: it secretly reads the NEXT bar's close to pick a direction, which no live system can do. "
        "The backtest looks great; the supervisor's leak check must catch it and block it."
    )
    default_params = {"entry_hours": [8, 12, 16], "stop_atr": 1.0, "target_r": 0.5, "max_hold_bars": 16, "atr_period": 14}

    def generate(self, df: pd.DataFrame, symbol: str) -> list[Signal]:
        p = self.params
        close = column(df, "close")
        next_close = np.r_[close[1:], np.nan]
        a = atr(df, p["atr_period"])
        at_hour = np.isin(df.index.hour, p["entry_hours"]) & (df.index.minute == 0)
        side = np.nan_to_num(np.sign(next_close - close)).astype(int) * (at_hour & np.isfinite(a))
        stop = close - side * p["stop_atr"] * a
        target = close + side * p["target_r"] * p["stop_atr"] * a
        return self.signals_from_arrays(df, symbol, side, stop, target, p["max_hold_bars"])
