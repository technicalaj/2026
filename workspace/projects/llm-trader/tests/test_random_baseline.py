import time

import numpy as np
import pytest
from conftest import BAR, make_bars, make_spec

from llm_trader.costs import CostModel
from llm_trader.data.symbols import resolve_spec
from llm_trader.eval.backtest import simulate
from llm_trader.eval.metrics import clustered_mean_interval
from llm_trader.eval.random_baseline import atr_at_open, empirical_p_value, entry_day, random_baseline
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
    trades, frames, specs = rule_trades(demo, settings, "demo_rule_a")
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
    assert rb.win_rate_mean < np.mean([t.win for t in trades if window[0] < t.entry_time <= window[1]]) - 0.15


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
    trades, frames, specs = rule_trades(demo, settings, "demo_rule_b")
    rb_wide = random_baseline(frames, trades, window, specs, COSTS, runs=200, seed=2)
    assert 0.7 < rb_tight.win_rate_mean < 0.86
    assert rb_wide.win_rate_mean < 0.5


def test_higher_costs_make_random_entries_worse(demo, settings):
    window = dataset_bounds(demo, settings)["recent"]
    trades, frames, specs = rule_trades(demo, settings, "demo_rule_a")
    cheap = random_baseline(frames, trades, window, specs, COSTS, runs=200, seed=9)
    pricey = random_baseline(frames, trades, window, specs, CostModel(spread_multiplier=3.0), runs=200, seed=9)
    assert pricey.expectancy_mean < cheap.expectancy_mean - 0.05


def trending_bars(n: int = 20_000, drift: float = 0.01, sigma: float = 0.1, seed: int = 11):
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(drift + sigma * rng.standard_normal(n))
    open_ = np.r_[100.0, close[:-1]]
    wick = np.abs(0.6 * sigma * rng.standard_normal((n, 2)))
    rows = np.c_[open_, np.maximum(open_, close) + wick[:, 0], np.minimum(open_, close) - wick[:, 1], close]
    return make_bars(rows, start="2026-01-05 00:00")


def one_sided_trades(df, side: int, every: int = 16):
    a, close = atr(df), df["close"].to_numpy()
    bars = np.arange(50, len(df) - 40, every)
    signals = [Signal("one_sided", "TEST", df.index[i] + BAR, side, close[i] - side * a[i], close[i] + side * a[i], 16) for i in bars]
    return simulate(df, signals, make_spec(), COSTS)


def test_long_only_rule_on_an_uptrend_does_not_beat_the_direction_matched_baseline():
    df = trending_bars()
    trades = one_sided_trades(df, +1)
    window = (df.index[0], df.index[-1])
    rb = random_baseline({"TEST": df}, trades, window, {"TEST": make_spec()}, COSTS, runs=500, seed=4)
    assert np.mean([t.r for t in trades]) > 0.1
    assert rb.expectancy_mean > 0.1 and rb.win_rate_mean > 0.5
    assert rb.p_value > 0.05


def test_replicas_keep_each_trades_direction():
    df = trending_bars()
    window = (df.index[0], df.index[-1])
    long_trades = one_sided_trades(df, +1)
    longs = random_baseline({"TEST": df}, long_trades, window, {"TEST": make_spec()}, COSTS, runs=300, seed=4)
    shorts = random_baseline({"TEST": df}, one_sided_trades(df, -1), window, {"TEST": make_spec()}, COSTS, runs=300, seed=4)
    assert longs.expectancy_mean > 0.1 > -0.1 > shorts.expectancy_mean
    coin_flip_mean = (longs.expectancy_mean + shorts.expectancy_mean) / 2
    assert np.mean([t.r for t in long_trades]) - coin_flip_mean > 0.1


def test_atr_at_open_uses_only_earlier_bars(demo):
    df = demo["EURUSD"][0].iloc[:3000]
    before = atr_at_open(df)
    changed = df.copy()
    changed.iloc[2000:, :4] = changed.iloc[2000:, :4] * 1.05
    after = atr_at_open(changed)
    np.testing.assert_array_equal(before[:2001], after[:2001])
    assert not np.allclose(before[2001:], after[2001:])


def bunched_trades(df, seed: int = 5):
    # No edge: one coin per day picks the side for eight overlapping entries, the way many EAs re-enter.
    rng = np.random.default_rng(seed)
    a, close = atr(df), df["close"].to_numpy()
    days = df.index.normalize()
    coin = {d: rng.choice([-1, 1]) for d in days.unique()}
    bars = [i for i in range(50, len(df) - 40) if 8 <= df.index[i].hour < 10]
    signals = [Signal("bunched", "TEST", df.index[i] + BAR, int(coin[days[i]]), close[i] - coin[days[i]] * a[i],
                      close[i] + coin[days[i]] * a[i], 32) for i in bars]
    return simulate(df, signals, make_spec(), COSTS)


def test_random_days_keep_bunched_trades_together():
    df = trending_bars(n=12_000, drift=0.0)
    trades = bunched_trades(df)
    window = (df.index[0], df.index[-1])
    rb = random_baseline({"TEST": df}, trades, window, {"TEST": make_spec()}, COSTS, runs=400, seed=7)
    replica_sd = (rb.expectancy_p95 - rb.expectancy_mean) / 1.645
    r = np.array([t.r for t in trades])
    lo, hi = clustered_mean_interval(r, [entry_day(t) for t in trades])
    clustered_se = (hi - lo) / (2 * 1.96)
    iid_se = r.std(ddof=1) / np.sqrt(len(r))
    assert clustered_se > 1.4 * iid_se
    assert replica_sd > 0.8 * clustered_se and replica_sd > 1.3 * iid_se


def test_largest_window_runs_1000_replicas_quickly(demo, settings):
    trades, frames, specs = rule_trades(demo, settings, "tight_target")
    window = dataset_bounds(demo, settings)["holdout"]
    started = time.perf_counter()
    rb = random_baseline(frames, trades, window, specs, COSTS, runs=1000, seed=0)
    assert rb.runs == 1000
    assert time.perf_counter() - started < 10
