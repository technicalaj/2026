import math

import pandas as pd
import pytest
from conftest import BAR, make_bars, make_spec, signal_after

from llm_trader.costs import CostModel
from llm_trader.eval.backtest import SignalRejected, simulate
from llm_trader.models import Signal

FREE = CostModel()


def one(df, signal, spec=None, cost_model=FREE, **kw):
    trades = simulate(df, [signal], spec or make_spec(), cost_model, **kw)
    assert len(trades) == 1
    return trades[0]


def test_entry_is_next_bar_open_and_target_exit():
    df = make_bars([
        [99.0, 100.2, 98.9, 100.0],
        [100.0, 100.5, 99.5, 100.2],
        [100.2, 101.2, 100.0, 101.0],
    ])
    t = one(df, signal_after(df, 0, 1, stop=99.0, target=101.0))
    assert t.entry_time == df.index[1]
    assert t.entry == pytest.approx(100.0)
    assert (t.outcome, t.exit) == ("target", 101.0)
    assert t.r == pytest.approx(1.0)
    assert t.hold_bars == 2
    assert t.exit_time == df.index[2] + BAR
    assert t.win


def test_stop_counts_first_when_stop_and_target_touch_same_bar():
    df = make_bars([[100, 100, 100, 100], [100.0, 101.5, 98.5, 100.0]])
    t = one(df, signal_after(df, 0, 1, stop=99.0, target=101.0))
    assert t.outcome == "stop"
    assert t.r == pytest.approx(-1.0)
    assert not t.win


def test_long_pays_spread_on_entry_and_exits_on_bid():
    df = make_bars([[100, 100, 100, 100], [100.0, 101.0, 99.5, 100.5]], spread=10)
    t = one(df, signal_after(df, 0, 1, stop=99.0, target=101.0))
    assert t.entry == pytest.approx(100.10)
    assert t.exit == pytest.approx(101.0)
    assert t.risk_price == pytest.approx(1.10)
    assert t.r == pytest.approx(0.9 / 1.1)
    assert t.costs_r == pytest.approx(0.1 / 1.1)


def test_short_enters_on_bid_and_stop_is_checked_on_ask():
    df = make_bars([[100, 100, 100, 100], [100.0, 100.95, 99.5, 100.0]], spread=10)
    t = one(df, signal_after(df, 0, -1, stop=101.0, target=99.0))
    assert t.entry == pytest.approx(100.0)
    assert t.outcome == "stop"
    assert t.exit == pytest.approx(101.0)
    assert t.r == pytest.approx(-1.0)


def test_short_target_needs_the_ask_to_reach_it():
    near = make_bars([[100, 100, 100, 100], [100.0, 100.2, 98.95, 99.5], [99.5, 99.6, 99.4, 99.5]], spread=10)
    t = one(near, signal_after(near, 0, -1, stop=101.0, target=99.0, max_hold=2))
    assert t.outcome == "time"
    assert t.exit == pytest.approx(99.5 + 0.10)

    hit = make_bars([[100, 100, 100, 100], [100.0, 100.2, 98.90, 99.5]], spread=10)
    t = one(hit, signal_after(hit, 0, -1, stop=101.0, target=99.0))
    assert (t.outcome, t.exit, t.r) == ("target", 99.0, pytest.approx(1.0))


def test_slippage_and_commission_are_charged_in_r():
    spec = make_spec(slippage_points=5, commission_per_lot=7.0)
    stopped = make_bars([[100, 100, 100, 100], [100.0, 100.2, 98.0, 98.5]])
    t = one(stopped, signal_after(stopped, 0, 1, stop=99.0, target=101.0), spec)
    risk = 100.05 - 99.0
    assert t.entry == pytest.approx(100.05)
    assert t.exit == pytest.approx(98.95)
    assert t.r == pytest.approx((98.95 - 100.05) / risk - 0.07 / risk)
    assert t.costs_r == pytest.approx((0.05 * 2 + 0.07) / risk)

    won = make_bars([[100, 100, 100, 100], [100.0, 101.5, 99.8, 101.2]])
    t = one(won, signal_after(won, 0, 1, stop=99.0, target=101.0), spec)
    assert t.exit == pytest.approx(101.0)
    assert t.r == pytest.approx((101.0 - 100.05) / risk - 0.07 / risk)
    assert t.costs_r == pytest.approx((0.05 + 0.07) / risk)


def test_time_exit_at_close_of_last_held_bar():
    rows = [[100, 100, 100, 100]] + [[100.0, 100.4, 99.6, 100.0 + i / 10] for i in range(1, 6)]
    df = make_bars(rows, spread=4)
    spec = make_spec(slippage_points=1)
    t = one(df, signal_after(df, 0, 1, stop=99.0, target=102.0, max_hold=3), spec)
    assert (t.outcome, t.hold_bars) == ("time", 3)
    assert t.exit_time == df.index[3] + BAR
    assert t.exit == pytest.approx(100.3 - 0.01)

    t = one(df, signal_after(df, 0, -1, stop=101.0, target=98.0, max_hold=3), spec)
    assert t.exit == pytest.approx(100.3 + 0.04 + 0.01)


def test_gap_through_stop_fills_at_the_worse_open():
    df = make_bars([[100, 100, 100, 100], [100.0, 100.3, 99.5, 99.8], [98.5, 98.9, 98.2, 98.6]])
    t = one(df, signal_after(df, 0, 1, stop=99.0, target=101.0))
    assert (t.outcome, t.exit) == ("stop", 98.5)
    assert t.r == pytest.approx(-1.5)


def test_breakeven_exit_is_never_a_win():
    rows = [[100, 100, 100, 100], [100.0, 100.6, 99.8, 100.4], [100.4, 100.45, 99.9, 100.0]]
    df = make_bars(rows)
    t = one(df, signal_after(df, 0, 1, stop=99.0, target=102.0, breakeven_at_r=0.5))
    assert t.outcome == "breakeven"
    assert t.r == pytest.approx(0.0)
    assert not t.win

    rows[2] = [100.4, 100.45, 100.05, 100.2]
    df = make_bars(rows)
    t = one(df, signal_after(df, 0, 1, stop=99.0, target=102.0, breakeven_at_r=0.5, breakeven_offset_r=0.1))
    assert t.outcome == "breakeven"
    assert t.r == pytest.approx(0.1)
    assert not t.win


def test_breakeven_stop_only_applies_after_the_trigger_bar():
    df = make_bars([[100, 100, 100, 100], [100.0, 100.6, 99.7, 100.3], [100.3, 100.5, 100.1, 100.4]])
    t = one(df, signal_after(df, 0, 1, stop=99.0, target=102.0, max_hold=2, breakeven_at_r=0.5))
    assert t.outcome == "time"


def test_tiny_gains_are_not_wins():
    df = make_bars([[100, 100, 100, 100], [100.0, 100.2, 99.9, 100.03]])
    t = one(df, signal_after(df, 0, 1, stop=99.0, target=102.0, max_hold=1))
    assert t.r == pytest.approx(0.03)
    assert not t.win
    t = one(df, signal_after(df, 0, 1, stop=99.0, target=102.0, max_hold=1), win_epsilon_r=0.02)
    assert t.win


@pytest.mark.parametrize("stop", [None, math.nan])
def test_signal_without_stop_is_rejected(stop):
    df = make_bars([[100, 100, 100, 100], [100, 101, 99, 100]])
    with pytest.raises(SignalRejected, match="no stop-loss"):
        simulate(df, [signal_after(df, 0, 1, stop=stop, target=101.0)], make_spec(), FREE)


def test_target_on_the_wrong_side_is_rejected():
    df = make_bars([[100, 100, 100, 100], [100, 101, 99, 100]])
    with pytest.raises(SignalRejected, match="profit side"):
        simulate(df, [signal_after(df, 0, 1, stop=99.0, target=98.0)], make_spec(), FREE)


def test_trade_is_skipped_when_entry_opens_beyond_the_stop():
    df = make_bars([[100, 100, 100, 100], [98.8, 99.2, 98.5, 99.0]])
    assert simulate(df, [signal_after(df, 0, 1, stop=99.0, target=101.0)], make_spec(), FREE) == []


def test_unresolved_trade_at_end_of_data_is_dropped_but_resolved_one_kept():
    df = make_bars([[100, 100, 100, 100], [100.0, 100.4, 99.6, 100.1], [100.1, 100.5, 99.7, 100.2]])
    assert simulate(df, [signal_after(df, 0, 1, stop=99.0, target=102.0, max_hold=5)], make_spec(), FREE) == []
    t = one(df, signal_after(df, 0, 1, stop=99.0, target=100.45, max_hold=5))
    assert t.outcome == "target"


def test_signal_on_last_bar_has_no_entry():
    df = make_bars([[100, 100, 100, 100], [100, 101, 99, 100]])
    assert simulate(df, [signal_after(df, 1, 1, stop=99.0, target=101.0)], make_spec(), FREE) == []


def test_missing_bar_spread_falls_back_to_typical_spread():
    df = make_bars([[100, 100, 100, 100], [100.0, 101.0, 99.5, 100.5]], spread=float("nan"))
    t = one(df, signal_after(df, 0, 1, stop=99.0, target=101.0), make_spec(typical_spread_points=20))
    assert t.entry == pytest.approx(100.20)


def test_entry_after_weekend_gap_uses_next_available_bar():
    df = make_bars([[100, 100, 100, 100], [100, 100.5, 99.5, 100], [100.0, 101.2, 99.8, 101.0]], start="2026-03-06 21:30")
    df.index = pd.DatetimeIndex([df.index[0], df.index[1], pd.Timestamp("2026-03-08 22:00", tz="UTC")], name="time").as_unit("ns")
    signal = Signal("test_rule", "TEST", df.index[1] + BAR, 1, 99.0, 101.0, 4)
    t = one(df, signal)
    assert t.entry_time == pd.Timestamp("2026-03-08 22:00", tz="UTC")
    assert t.outcome == "target"
