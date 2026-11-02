import numpy as np
import pandas as pd
import pytest

from llm_trader.eval.leakcheck import detectable_share, leak_check
from llm_trader.signals.base import SignalRule, atr, column
from llm_trader.signals.registry import all_rules, get_rule
from llm_trader.signals.tight_target import TightTarget


class WholeSampleZScore(SignalRule):
    rule_id = "zscore_leak"
    default_symbols = ("EURUSD",)

    def generate(self, df, symbol):
        close = column(df, "close")
        z = (close - close.mean()) / close.std()
        a = atr(df)
        side = np.where(z > 1.5, -1, np.where(z < -1.5, 1, 0)) * np.isfinite(a) * (df.index.minute == 0)
        return self.signals_from_arrays(df, symbol, side, close - side * a, close + side * a, 8)


class FridayPeek(TightTarget):
    rule_id = "friday_peek"

    def generate(self, df, symbol):
        # Honest except at 16:00 on Fridays, where it takes its direction from the next bar's close.
        close = df["close"]
        out = []
        for s in super().generate(df, symbol):
            i = df.index.get_loc(s.time - pd.Timedelta(minutes=15))
            if s.time.day_of_week == 4 and s.time.hour == 16 and i + 1 < len(df):
                if np.sign(close.iloc[i + 1] - close.iloc[i]) == -s.side:
                    s.side, s.stop, s.target = -s.side, s.target, s.stop
            out.append(s)
        return out


def test_a_leak_in_one_signal_in_twenty_is_caught_every_time(demo):
    df = demo["XAUUSD"][0].iloc[:12_000]
    rule = FridayPeek()
    signals = rule.generate(df, "XAUUSD")
    honest = {(s.time, s.side) for s in TightTarget().generate(df, "XAUUSD")}
    altered = sum(1 for s in signals if (s.time, s.side) not in honest)
    assert 0.02 < altered / len(signals) < 0.08
    assert all(not leak_check(rule, df, "XAUUSD", seed=seed)[0] for seed in range(5))


def test_detail_says_how_small_a_leak_would_still_show(demo):
    passed, detail = leak_check(get_rule("tight_target"), demo["XAUUSD"][0].iloc[:12_000], "XAUUSD", seed=1)
    assert passed and "a leak touching 3% or more of its signals would have shown 95% of the time" in detail
    assert detectable_share(100, 1000) == pytest.approx(0.0295, abs=1e-3)
    assert detectable_share(20, 20) == pytest.approx(0.05)


def test_rule_peeking_at_next_bar_is_caught(demo):
    passed, detail = leak_check(get_rule("leaky"), demo["EURUSD"][0], "EURUSD", cuts=12, seed=1)
    assert not passed
    assert detail.startswith("Future-data leak on EURUSD")
    assert "once later bars were removed" in detail


def test_whole_sample_statistics_are_caught(demo):
    passed, detail = leak_check(WholeSampleZScore(), demo["EURUSD"][0], "EURUSD", cuts=12, seed=2)
    assert not passed


@pytest.mark.parametrize("rule", [r for r in all_rules() if r.rule_id != "leaky"], ids=lambda r: r.rule_id)
def test_honest_rules_pass(rule, demo):
    symbol = rule.symbols[0]
    passed, detail = leak_check(rule, demo[symbol][0], symbol, cuts=12, seed=3)
    assert passed, detail
    assert detail.startswith(f"No future-data leak on {symbol}")


def test_leak_check_is_deterministic(demo):
    df = demo["EURUSD"][0]
    assert leak_check(get_rule("leaky"), df, "EURUSD", seed=4) == leak_check(get_rule("leaky"), df, "EURUSD", seed=4)


def test_tiny_data_is_reported_not_crashed(demo):
    passed, detail = leak_check(get_rule("demo_rule_a"), demo["XAUUSD"][0].iloc[:2], "XAUUSD")
    assert passed and "Not enough" in detail
