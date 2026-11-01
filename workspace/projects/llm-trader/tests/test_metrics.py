import pandas as pd
import pytest

from llm_trader.eval.metrics import max_drawdown, wilson_interval, window_metrics
from llm_trader.eval.windows import split_windows
from llm_trader.models import Trade

T0 = pd.Timestamp("2026-03-02 08:00", tz="UTC")


def trade(minutes: int, r: float, outcome: str, win: bool | None = None, hold: int = 3) -> Trade:
    entry = T0 + pd.Timedelta(minutes=minutes)
    return Trade(
        rule_id="x", symbol="TEST", signal_time=entry, entry_time=entry, entry=100.0, stop=99.0, target=101.0, side=1,
        exit_time=entry + pd.Timedelta(minutes=15 * hold), exit=100.0 + r, outcome=outcome, r=r, risk_price=1.0,
        costs_r=0.0, hold_bars=hold, max_hold_bars=10, win=(r > 0.05 and outcome != "breakeven") if win is None else win,
    )


def test_wilson_interval_matches_textbook_values():
    lo, hi = wilson_interval(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-4)
    assert hi == pytest.approx(0.9433, abs=1e-4)
    assert wilson_interval(0, 10)[0] == 0.0
    assert wilson_interval(0, 10)[1] == pytest.approx(0.2775, abs=1e-4)
    assert wilson_interval(10, 10)[1] == 1.0
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_wilson_interval_narrows_with_more_trades():
    small = wilson_interval(43, 50)
    large = wilson_interval(430, 500)
    assert (large[1] - large[0]) < (small[1] - small[0])


def test_window_is_left_open_right_closed():
    trades = [trade(0, 1.0, "target"), trade(15, 1.0, "target"), trade(30, -1.0, "stop")]
    m = window_metrics(trades, T0, T0 + pd.Timedelta(minutes=30))
    assert m.trades == 2
    assert m.start == T0
    assert window_metrics(trades, None, T0).trades == 1


def test_breakevens_count_neither_as_wins_nor_full_stops():
    trades = [trade(0, 1.0, "target"), trade(15, 0.02, "breakeven"), trade(30, 0.2, "breakeven"), trade(45, -1.0, "stop")]
    m = window_metrics(trades, None, None)
    assert m.wins == 1
    assert m.win_rate == pytest.approx(0.25)
    assert m.breakeven_rate == pytest.approx(0.5)
    assert m.full_stop_rate == pytest.approx(0.25)


def test_expectancy_profit_factor_drawdown_and_equity():
    trades = [trade(0, 1.0, "target"), trade(15, -1.0, "stop"), trade(30, -1.0, "stop"), trade(45, 1.5, "target")]
    m = window_metrics(trades, None, None)
    assert m.expectancy_r == pytest.approx(0.125)
    assert m.profit_factor == pytest.approx(2.5 / 2.0)
    assert m.max_drawdown_r == pytest.approx(2.0)
    assert m.equity_r == [1.0, 0.0, -1.0, 0.5]
    assert m.avg_hold_bars == pytest.approx(3.0)


def test_equity_follows_exit_order():
    slow = trade(0, -1.0, "stop", hold=10)
    fast = trade(15, 1.0, "target", hold=1)
    assert window_metrics([slow, fast], None, None).equity_r == [1.0, 0.0]


def test_profit_factor_is_none_without_losses():
    m = window_metrics([trade(0, 1.0, "target"), trade(15, 0.5, "target")], None, None)
    assert m.profit_factor is None
    assert m.max_drawdown_r == 0.0


def test_empty_window_is_honest_about_missing_numbers():
    m = window_metrics([], None, None)
    assert (m.trades, m.wins, m.win_rate, m.expectancy_r, m.full_stop_rate) == (0, 0, None, None, None)
    assert m.win_rate_ci == (0.0, 1.0)
    assert m.equity_r == []


def test_max_drawdown_counts_from_the_starting_balance():
    assert max_drawdown([-1.0, -1.0, 3.0]) == pytest.approx(2.0)
    assert max_drawdown([]) == 0.0


def test_window_metrics_serialise_to_json_types():
    d = window_metrics([trade(0, 1.0, "target")], T0 - pd.Timedelta(days=1), T0).to_dict()
    assert d["start"] == "2026-03-01T08:00:00Z"
    assert d["win_rate_ci"] == [pytest.approx(0.2065, abs=1e-4), 1.0]


def test_split_windows_counts_whole_calendar_months_back_from_the_last_bar():
    w = split_windows(pd.Timestamp("2026-05-31 21:45", tz="UTC"), holdout_months=6, recent_months=3)
    assert w["recent"] == (pd.Timestamp("2026-02-28 21:45", tz="UTC"), pd.Timestamp("2026-05-31 21:45", tz="UTC"))
    assert w["holdout"] == (pd.Timestamp("2025-08-31 21:45", tz="UTC"), pd.Timestamp("2026-02-28 21:45", tz="UTC"))
    assert w["development"] == (None, pd.Timestamp("2025-08-31 21:45", tz="UTC"))
