import time

import numpy as np
import pytest

from llm_trader.costs import CostModel
from llm_trader.data.symbols import resolve_spec
from llm_trader.eval.backtest import simulate
from llm_trader.eval.random_baseline import _minutes_apart, atr_at_open, empirical_p_value, random_baseline
from llm_trader.eval.run import dataset_bounds
from llm_trader.models import Signal
from llm_trader.signals.base import atr
from llm_trader.signals.registry import get_rule

COSTS = CostModel()


def rule_trades(demo, settings, rule_id, cost_model=COSTS):
    rule = get_rule(rule_id)
    specs = {s: resolve_spec(s, demo[s][1], settings["costs"]) for s in rule.symbols}
    trades = []
    for s in rule.symbols:
        trades += simulate(demo[s][0], rule.generate(demo[s][0], s), specs[s], cost_model)
    return trades, {s: demo[s][0] for s in rule.symbols}, specs


def test_p_value_formula_counts_replicas_at_least_as_good():
    replicas = [0.1, 0.2, 0.3, float("nan")]
    assert empirical_p_value(replicas, 0.25) == pytest.approx(2 / 4)
    assert empirical_p_value(replicas, 0.35) == pytest.approx(1 / 4)
    assert empirical_p_value(replicas, 0.0) == pytest.approx(4 / 4)
    assert empirical_p_value(replicas, 0.3) == pytest.approx(2 / 4)


def test_no_trades_in_window_gives_empty_baseline(demo, settings):
    trades, frames, specs = rule_trades(demo, settings, "trend_pullback")
    rb = random_baseline(frames, trades, ("2030-01-01", "2030-02-01"), specs, COSTS, runs=100)
    assert (rb.runs, rb.p_value, rb.expectancy_mean) == (0, 1.0, None)
    assert rb.hist == {"bin_edges": [], "counts": []}


def test_baseline_is_deterministic_and_has_25_bins(demo, settings):
    trades, frames, specs = rule_trades(demo, settings, "sweep_fade")
    window = dataset_bounds(demo, settings)["recent"]
    a = random_baseline(frames, trades, window, specs, COSTS, runs=300, seed=5)
    b = random_baseline(frames, trades, window, specs, COSTS, runs=300, seed=5)
    assert a == b
    assert len(a.hist["counts"]) == 25 and len(a.hist["bin_edges"]) == 26
    assert sum(a.hist["counts"]) == a.runs == 300
    assert random_baseline(frames, trades, window, specs, COSTS, runs=300, seed=6).hist != a.hist


def test_planted_edge_is_detected(demo, settings):
    trades, frames, specs = rule_trades(demo, settings, "control_planted")
    window = dataset_bounds(demo, settings)["holdout"]
    rb = random_baseline(frames, trades, window, specs, COSTS, runs=300, seed=1)
    assert rb.p_value == pytest.approx(1 / 301)
    assert rb.win_rate_mean < 0.6


def test_random_entries_are_not_flagged_as_an_edge(demo, settings):
    df, prov = demo["XAUUSD"]
    spec = resolve_spec("XAUUSD", prov, settings["costs"])
    window = dataset_bounds(demo, settings)["holdout"]
    rng = np.random.default_rng(42)
    a = atr(df)
    candidates = np.flatnonzero((df.index > window[0]) & (df.index <= window[1]) & np.isfinite(a))
    picks = np.sort(rng.choice(candidates[:-40], size=300, replace=False))
    sides = rng.choice([-1, 1], size=300)
    close = df["close"].to_numpy()
    signals = [
        Signal("random", "XAUUSD", df.index[i] + np.timedelta64(15, "m"), int(s), close[i] - s * a[i], close[i] + s * a[i], 16)
        for i, s in zip(picks, sides)
    ]
    trades = simulate(df, signals, spec, COSTS)
    rb = random_baseline({"XAUUSD": df}, trades, window, {"XAUUSD": spec}, COSTS, runs=500, seed=3)
    assert 0.05 < rb.p_value < 0.95
    assert abs(np.mean([t.win for t in trades]) - rb.win_rate_mean) < 0.08


def test_replicas_keep_the_trade_geometry(demo, settings):
    window = dataset_bounds(demo, settings)["holdout"]
    trades, frames, specs = rule_trades(demo, settings, "tight_target")
    rb_tight = random_baseline(frames, trades, window, specs, COSTS, runs=200, seed=2)
    trades, frames, specs = rule_trades(demo, settings, "range_breakout")
    rb_wide = random_baseline(frames, trades, window, specs, COSTS, runs=200, seed=2)
    assert 0.7 < rb_tight.win_rate_mean < 0.86
    assert rb_wide.win_rate_mean < 0.5


def test_higher_costs_make_random_entries_worse(demo, settings):
    window = dataset_bounds(demo, settings)["recent"]
    trades, frames, specs = rule_trades(demo, settings, "sweep_fade")
    cheap = random_baseline(frames, trades, window, specs, COSTS, runs=200, seed=9)
    pricey = random_baseline(frames, trades, window, specs, CostModel(spread_multiplier=3.0), runs=200, seed=9)
    assert pricey.expectancy_mean < cheap.expectancy_mean - 0.05


def test_atr_at_open_uses_only_earlier_bars(demo):
    df = demo["EURUSD"][0].iloc[:3000]
    before = atr_at_open(df)
    changed = df.copy()
    changed.iloc[2000:, :4] = changed.iloc[2000:, :4] * 1.05
    after = atr_at_open(changed)
    np.testing.assert_array_equal(before[:2001], after[:2001])
    assert not np.allclose(before[2001:], after[2001:])


def test_time_of_day_distance_wraps_midnight():
    minutes = np.array([23 * 60 + 50, 20, 12 * 60])
    np.testing.assert_array_equal(_minutes_apart(minutes, 10), [20, 10, 710])


def test_largest_window_runs_1000_replicas_quickly(demo, settings):
    trades, frames, specs = rule_trades(demo, settings, "tight_target")
    window = dataset_bounds(demo, settings)["holdout"]
    started = time.perf_counter()
    rb = random_baseline(frames, trades, window, specs, COSTS, runs=1000, seed=0)
    assert rb.runs == 1000
    assert time.perf_counter() - started < 10
