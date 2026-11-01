import numpy as np
import pytest

from llm_trader.eval.leakcheck import leak_check
from llm_trader.signals.base import SignalRule, atr, column
from llm_trader.signals.registry import all_rules, get_rule


class WholeSampleZScore(SignalRule):
    rule_id = "zscore_leak"
    default_symbols = ("EURUSD",)

    def generate(self, df, symbol):
        close = column(df, "close")
        z = (close - close.mean()) / close.std()
        a = atr(df)
        side = np.where(z > 1.5, -1, np.where(z < -1.5, 1, 0)) * np.isfinite(a) * (df.index.minute == 0)
        return self.signals_from_arrays(df, symbol, side, close - side * a, close + side * a, 8)


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
    passed, detail = leak_check(get_rule("sweep_fade"), demo["XAUUSD"][0].iloc[:2], "XAUUSD")
    assert passed and "Not enough" in detail
