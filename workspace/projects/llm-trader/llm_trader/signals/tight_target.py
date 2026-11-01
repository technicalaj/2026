from __future__ import annotations

import numpy as np
import pandas as pd

from llm_trader.models import Signal
from llm_trader.signals.base import SignalRule, atr, column


class TightTarget(SignalRule):
    rule_id = "tight_target"
    name = "Tight Target (trap demo)"
    default_symbols = ("XAUUSD", "BTCUSD")
    description = (
        "At 11:00 and 16:00 UTC, trades in the direction of the last hour's move. Stop 2x ATR away, but the "
        "target is only a quarter of that (0.25R). Exit after 32 bars at most."
    )
    demo_note = (
        "The classic trap: a tiny target with a wide stop wins most trades by construction, yet the rare full "
        "stops cost more than all the small wins. A high win rate alone proves nothing."
    )
    default_params = {"entry_hours": [11, 16], "momentum_bars": 4, "stop_atr": 2.0, "target_r": 0.25, "max_hold_bars": 32, "atr_period": 14}

    def generate(self, df: pd.DataFrame, symbol: str) -> list[Signal]:
        p = self.params
        close = column(df, "close")
        lag = p["momentum_bars"]
        past = np.r_[np.full(min(lag, len(close)), np.nan), close[:-lag]] if lag else close
        a = atr(df, p["atr_period"])
        at_hour = np.isin(df.index.hour, p["entry_hours"]) & (df.index.minute == 0)
        side = np.nan_to_num(np.sign(close - past)).astype(int) * (at_hour & np.isfinite(a))
        stop = close - side * p["stop_atr"] * a
        target = close + side * p["target_r"] * p["stop_atr"] * a
        return self.signals_from_arrays(df, symbol, side, stop, target, p["max_hold_bars"])
