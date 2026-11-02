import numpy as np
import pandas as pd
import pytest

from llm_trader.eval.metrics import clustered_mean_interval, max_drawdown, t_quantile_975, wilson_interval, window_metrics
from llm_trader.eval.windows import split_windows
from llm_trader.models import Labels, Trade

T0 = pd.Timestamp("2026-03-02 08:00", tz="UTC")


def trade(minutes: int, r: float, outcome: str, hold: int = 3) -> Trade:
    entry = T0 + pd.Timedelta(minutes=minutes)
    return Trade(
        rule_id="x", symbol="TEST", signal_time=entry, entry_time=entry, entry=100.0, stop=99.0, target=101.0, side=1,
        exit_time=entry + pd.Timedelta(minutes=15 * hold), exit=100.0 + r, outcome=outcome, r=r, risk_price=1.0,
        costs_r=0.0, hold_bars=hold, max_hold_bars=10,
    )


@pytest.mark.parametrize("r, label, full_stop", [
    (0.1, "win", False), (0.0999, "breakeven", False), (0.0, "breakeven", False), (-0.0999, "breakeven", False),
    (-0.1, "loss", False), (-0.899, "loss", False), (-0.9, "loss", True), (-1.3, "loss", True),
])
def test_labels_follow_the_plan_thresholds(r, label, full_stop):
    labels = Labels()
    assert (labels.label(r), labels.is_full_stop(r)) == (label, full_stop)
    t = trade(0, r, "time")
    assert (t.label, t.full_stop, t.win) == (label, full_stop, label == "win")


def test_labels_come_from_gate_settings():
    labels = Labels.from_gate({"win_threshold_r": 0.2, "breakeven_band_r": 0.05, "full_stop_r": -0.8})
    assert [labels.label(r) for r in (0.19, 0.2, -0.04, -0.05)] == ["breakeven", "win", "breakeven", "loss"]
    assert labels.is_full_stop(-0.8) and not labels.is_full_stop(-0.79)
    assert Labels.from_gate(None) == Labels(0.1, 0.1, -0.9)


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
    trades = [trade(0, 1.0, "target"), trade(15, 0.02, "breakeven"), trade(30, -0.05, "time"), trade(45, -1.0, "stop"),
              trade(60, -0.4, "time")]
    m = window_metrics(trades, None, None)
    assert (m.wins, m.losses) == (1, 2)
    assert m.win_rate == pytest.approx(0.2)
    assert m.breakeven_rate == pytest.approx(0.4)
    assert m.full_stop_rate == pytest.approx(0.2)


def test_win_rate_counts_every_trade_in_the_denominator():
    m = window_metrics([trade(0, 0.5, "target"), trade(15, 0.05, "time"), trade(30, 0.0, "breakeven")], None, None)
    assert m.win_rate == pytest.approx(1 / 3) and m.losses == 0


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
    assert (m.trades, m.wins, m.losses, m.win_rate, m.expectancy_r, m.full_stop_rate) == (0, 0, 0, None, None, None)
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


@pytest.mark.parametrize("dof, expected", [(1, 12.7062), (2, 4.3027), (4, 2.7764), (5, 2.5706), (10, 2.2281), (29, 2.0452), (120, 1.9799)])
def test_t_quantile_matches_tables(dof, expected):
    assert t_quantile_975(dof) == pytest.approx(expected, abs=5e-4)


def test_one_trade_per_day_gives_the_usual_t_interval():
    values = [0.5, -1.0, 0.5, 0.5, 0.4, -1.1, 0.5, 0.45]
    lo, hi = clustered_mean_interval(values, range(8))
    x = np.array(values)
    half = t_quantile_975(7) * x.std(ddof=1) / np.sqrt(8)
    assert (lo, hi) == (pytest.approx(x.mean() - half), pytest.approx(x.mean() + half))
    assert clustered_mean_interval([0.3], [1]) is None and clustered_mean_interval([], []) is None
    assert clustered_mean_interval([0.2, 0.2], [1, 2]) == (pytest.approx(0.2), pytest.approx(0.2))


def test_trades_bunched_on_one_day_widen_the_interval():
    rng = np.random.default_rng(3)
    day_luck = np.repeat(rng.normal(0, 1, 40), 5)
    values = 0.1 + day_luck + rng.normal(0, 0.2, 200)
    days = np.repeat(np.arange(40), 5)
    lo, hi = clustered_mean_interval(values, days)
    naive_lo, naive_hi = clustered_mean_interval(values, np.arange(200))
    assert hi - lo > 1.8 * (naive_hi - naive_lo)
    assert clustered_mean_interval(values, np.zeros(200)) is None
