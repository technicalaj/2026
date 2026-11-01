import json
import shutil

import pandas as pd

from llm_trader.eval.run import dataset_bounds, evaluate_rule
from llm_trader.models import WINDOW_NAMES
from llm_trader.signals.registry import get_rule
from llm_trader.signals.sweep_fade import SweepFade

HOLDOUT_EXPECTANCY = "Positive expectancy after costs (never-seen months)"
HOLDOUT_RANDOM = "Beats random entries (never-seen months)"


def passed(evaluation, name):
    return {c.name: c.passed for c in evaluation.gate.checks}[name]


def test_planted_control_qualifies(evaluations):
    e = evaluations["control_planted"]
    holdout, recent = e.windows["holdout"], e.windows["recent"]
    assert e.control and e.gate.status == "qualified"
    assert 0.83 <= holdout.win_rate <= 0.90
    assert holdout.trades >= 40
    assert holdout.expectancy_r > 0
    assert e.random["holdout"].p_value < 0.01
    assert recent.trades >= 10 and recent.win_rate >= 0.80 and recent.expectancy_r > 0
    assert e.random["recent"].p_value <= 0.10


def test_sweep_fade_fails_and_looks_like_random(evaluations):
    e = evaluations["sweep_fade"]
    holdout, rb = e.windows["holdout"], e.random["holdout"]
    assert e.gate.status == "failed"
    assert holdout.trades >= 30 and holdout.win_rate < 0.6
    assert rb.p_value > 0.05
    assert abs(holdout.win_rate - rb.win_rate_mean) < 0.08


def test_range_breakout_fails_and_looks_like_random(evaluations):
    e = evaluations["range_breakout"]
    holdout, rb = e.windows["holdout"], e.random["holdout"]
    assert e.gate.status == "failed"
    assert holdout.trades >= 30 and holdout.win_rate < 0.6
    assert rb.p_value > 0.05
    assert abs(holdout.win_rate - rb.win_rate_mean) < 0.08


def test_trend_pullback_has_too_few_trades(evaluations):
    e = evaluations["trend_pullback"]
    assert e.gate.status == "insufficient"
    assert 0 < e.windows["holdout"].trades < 30


def test_tight_target_wins_most_trades_but_fails(evaluations):
    e = evaluations["tight_target"]
    holdout, rb = e.windows["holdout"], e.random["holdout"]
    assert e.gate.status == "failed"
    assert 0.75 <= holdout.win_rate <= 0.85
    assert holdout.expectancy_r < 0 and not passed(e, HOLDOUT_EXPECTANCY)
    assert rb.p_value > 0.05 and not passed(e, HOLDOUT_RANDOM)
    assert abs(holdout.win_rate - rb.win_rate_mean) < 0.05
    assert holdout.full_stop_rate > 0.15


def test_leaky_rule_looks_great_but_is_blocked(evaluations):
    e = evaluations["leaky"]
    holdout = e.windows["holdout"]
    assert holdout.win_rate > 0.85 and holdout.expectancy_r > 0 and e.random["holdout"].p_value < 0.01
    assert not e.leak_check.passed
    assert e.gate.status == "blocked"
    assert e.gate.reasons[0].startswith("Blocked — Future-data leak on EURUSD")


def test_only_the_planted_control_qualifies(evaluations):
    assert [rule_id for rule_id, e in evaluations.items() if e.gate.status == "qualified"] == ["control_planted"]


def test_evaluations_are_complete_and_serialisable(evaluations):
    for e in evaluations.values():
        assert set(e.windows) == set(WINDOW_NAMES) and set(e.random) == {"holdout", "recent"}
        assert {name: len(trades) for name, trades in e.trades.items()} == {name: m.trades for name, m in e.windows.items()}
        assert e.plan.valid and len(e.plan.sha256) == 64 and e.plan.locked_at
        assert e.signals == sum(e.signals_by_symbol.values()) > 0
        assert set(e.median_stop_points) == set(e.symbols)
        assert all(v and v > 0 for v in e.median_stop_points.values())
        d = json.loads(json.dumps(e.to_dict()))
        assert {"trades", "wins", "win_rate", "win_rate_ci", "full_stop_rate", "breakeven_rate", "expectancy_r",
                "profit_factor", "max_drawdown_r", "avg_hold_bars", "equity_r", "random"} <= set(d["windows"]["holdout"])
        assert "random" not in d["windows"]["development"]
        assert len(d["windows"]["recent"]["random"]["hist"]["counts"]) == 25
        assert d["windows"]["development"]["start"] == "2024-10-30T22:00:00Z"
        assert d["windows"]["development"]["end"] == d["windows"]["holdout"]["start"]
        assert d["windows"]["holdout"]["end"] == d["windows"]["recent"]["start"]
        assert d["gate"]["status"] in ("qualified", "failed", "insufficient", "blocked")
        assert len(d["gate"]["checks"]) == 9


def test_windows_follow_the_spec(demo, settings):
    bounds = dataset_bounds(demo, settings)
    last = pd.Timestamp("2026-10-30 21:45", tz="UTC")
    assert bounds["recent"] == (pd.Timestamp("2026-07-30 21:45", tz="UTC"), last)
    assert bounds["holdout"] == (pd.Timestamp("2026-01-30 21:45", tz="UTC"), pd.Timestamp("2026-07-30 21:45", tz="UTC"))


def test_missing_plan_blocks_but_still_shows_numbers(tmp_path, demo, settings):
    e = evaluate_rule(get_rule("trend_pullback"), demo, settings, tmp_path)
    assert e.gate.status == "blocked"
    assert not e.plan.valid and "No locked test plan" in e.plan.reason
    assert e.gate.reasons[0].startswith("Blocked — Test plan:")
    assert e.windows["holdout"].trades > 0


def test_changed_rule_blocks_and_plan_is_not_rewritten(tmp_path, demo, settings, plans_dir):
    shutil.copy(plans_dir / "trend_pullback.json", tmp_path)
    before = (tmp_path / "trend_pullback.json").read_text()
    rule = get_rule("trend_pullback")
    rule.params["rsi_low"] = 30
    e = evaluate_rule(rule, demo, settings, tmp_path)
    assert e.gate.status == "blocked"
    assert "params.rsi_low 25 -> 30" in e.plan.reason
    assert (tmp_path / "trend_pullback.json").read_text() == before


def test_missing_symbol_data_blocks(demo, settings, plans_dir):
    partial = {symbol: pair for symbol, pair in demo.items() if symbol != "USDJPY"}
    e = evaluate_rule(get_rule("trend_pullback"), partial, settings, plans_dir)
    assert e.gate.status == "blocked"
    assert any(h.startswith("No data for USDJPY") for h in e.hard_failures)


class NoStopSweepFade(SweepFade):
    def generate(self, df, symbol):
        signals = super().generate(df, symbol)
        signals[0].stop = None
        return signals


def test_rule_emitting_a_signal_without_stop_is_blocked_not_crashed(demo, settings, plans_dir):
    e = evaluate_rule(NoStopSweepFade(), demo, settings, plans_dir)
    assert e.gate.status == "blocked"
    assert any("has no stop-loss" in h for h in e.hard_failures)


def test_evaluation_is_deterministic(evaluations, demo, settings, plans_dir):
    again = evaluate_rule(get_rule("control_planted"), demo, settings, plans_dir)
    assert again.to_dict(include_trades=True) == evaluations["control_planted"].to_dict(include_trades=True)


def test_full_demo_evaluation_is_fast(timed_evaluations):
    assert timed_evaluations[1] < 120
