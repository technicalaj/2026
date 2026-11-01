from __future__ import annotations

import numpy as np
import pandas as pd

from llm_trader.models import Signal
from llm_trader.signals.base import SignalRule, apply_cooldown, atr, column, ema, rsi


class TrendPullback(SignalRule):
    rule_id = "trend_pullback"
    name = "Trend Pullback (demo)"
    default_symbols = ("EURUSD", "USDJPY")
    description = (
        "Buys a deep pullback in an uptrend: EMA50 above EMA200, price still above EMA200, the bar dips to EMA20 "
        "and RSI(14) is below 25 (mirror for downtrends). Stop 1.5x ATR, target 2R, exit after 48 bars at most."
    )
    demo_note = (
        "Deliberately strict. It fires so rarely that there are too few trades to judge, so the gate answers "
        "'not enough evidence' instead of guessing."
    )
    default_params = {
        "ema_fast": 20,
        "ema_mid": 50,
        "ema_slow": 200,
        "rsi_period": 14,
        "rsi_low": 25,
        "rsi_high": 75,
        "stop_atr": 1.5,
        "target_r": 2.0,
        "max_hold_bars": 48,
        "cooldown_bars": 16,
        "atr_period": 14,
    }

    def generate(self, df: pd.DataFrame, symbol: str) -> list[Signal]:
        p = self.params
        high, low, close = column(df, "high"), column(df, "low"), column(df, "close")
        fast, mid, slow = ema(close, p["ema_fast"]), ema(close, p["ema_mid"]), ema(close, p["ema_slow"])
        strength = rsi(close, p["rsi_period"])
        a = atr(df, p["atr_period"])
        up = (mid > slow) & (close > slow) & (low <= fast) & (strength < p["rsi_low"]) & np.isfinite(a)
        down = (mid < slow) & (close < slow) & (high >= fast) & (strength > p["rsi_high"]) & np.isfinite(a)
        long = apply_cooldown(up, p["cooldown_bars"])
        short = apply_cooldown(down, p["cooldown_bars"])
        side = np.where(long, 1, np.where(short, -1, 0))
        stop = close - side * p["stop_atr"] * a
        target = close + side * p["target_r"] * p["stop_atr"] * a
        return self.signals_from_arrays(df, symbol, side, stop, target, p["max_hold_bars"])
