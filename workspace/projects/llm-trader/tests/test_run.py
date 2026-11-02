import copy
import json
import shutil

import numpy as np
import pandas as pd
import pytest
from conftest import LOCKED_AT

import llm_trader.data.synthetic as synthetic
from llm_trader.eval.gate import TOO_GOOD_REASON
from llm_trader.eval.plans import lock_all_plans, lock_rule, make_plan, trial_hash
from llm_trader.eval.run import dataset_bounds, evaluate_all, evaluate_rule, finish_evaluation, raw_evaluation
from llm_trader.eval.trials import TrialEntry, holm_decisions, load_trials, record_trials
from llm_trader.models import WINDOW_NAMES
from llm_trader.signals.demo_rule_a import DemoRuleA
from llm_trader.signals.registry import all_rules, get_rule
from llm_trader.supervisor import checks as c

RULE_IDS = ["control_planted", "demo_rule_a", "demo_rule_b", "trend_pullback", "tight_target", "leaky"]
HOLDOUT_EXPECTANCY = "Positive expectancy after costs (never-seen months)"
HOLDOUT_RANDOM = "Beats random entries (never-seen months)"
STOP_TARGET = "Stop no more than 2× the target distance"
TOO_GOOD = "Not too good to be true (win rate ≤ 90%, profit factor ≤ 4)"
EXTRA_KEYS = {"expectancy_ci", "expectancy_1_5x_costs", "expectancy_2x_costs", "long", "short", "terciles",
              "stop_target_ratio", "holm_threshold", "trial_count"}


PLAN_CHECK = "Plan locked before testing"


def check(evaluation, name):
    return {c.name: c for c in evaluation.gate.checks}[name]


def holm_check(evaluation):
    return next(c for c in evaluation.gate.checks if c.name.startswith("Beats random after correcting for"))


def test_rules_and_self_tests_are_in_registry_order(evaluations):
    assert list(evaluations) == RULE_IDS
    kinds = {rule_id: (e.kind, e.self_test, e.expected) for rule_id, e in evaluations.items()}
    assert kinds == {
        "control_planted": ("self_test", True, "must qualify"),
        "demo_rule_a": ("rule", False, None),
        "demo_rule_b": ("rule", False, None),
        "trend_pullback": ("rule", False, None),
        "tight_target": ("self_test", True, "must fail"),
        "leaky": ("self_test", True, "must be blocked"),
    }
    assert {rule_id: e.self_test_ok for rule_id, e in evaluations.items()} == {
        "control_planted": True, "demo_rule_a": None, "demo_rule_b": None, "trend_pullback": None,
        "tight_target": True, "leaky": True,
    }


def test_planted_control_qualifies_on_every_check(evaluations):
    e = evaluations["control_planted"]
    holdout, recent, extra = e.windows["holdout"], e.windows["recent"], e.extra["holdout"]
    assert e.control and e.gate.status == "qualified"
    assert all(c.passed for c in e.gate.checks)
    assert 0.83 <= holdout.win_rate <= 0.88
    assert holdout.trades >= 40 and holdout.profit_factor < 4
    assert extra.expectancy_ci[0] > 0 and extra.expectancy_1_5x_costs > 0
    assert sum(1 for t in extra.terciles if t["trades"] >= 5 and t["expectancy_r"] > 0) >= 2
    assert extra.stop_target_ratio == pytest.approx(2.0)
    assert e.random["holdout"].p_value < 0.01 and e.holm.passed
    assert recent.trades >= 10 and recent.win_rate >= 0.80 and recent.expectancy_r > 0
    assert e.random["recent"].p_value <= 0.10


def test_demo_rule_a_fails_and_looks_like_random(evaluations):
    e = evaluations["demo_rule_a"]
    holdout, rb = e.windows["holdout"], e.random["holdout"]
    assert e.gate.status == "failed"
    assert holdout.trades >= 30 and holdout.win_rate < 0.6
    assert rb.p_value > 0.05
    assert abs(holdout.win_rate - rb.win_rate_mean) < 0.08


def test_demo_rule_b_fails_and_looks_like_random(evaluations):
    e = evaluations["demo_rule_b"]
    holdout, rb = e.windows["holdout"], e.random["holdout"]
    assert e.gate.status == "failed"
    assert holdout.trades >= 30 and holdout.win_rate < 0.6
    assert rb.p_value > 0.05
    assert abs(holdout.win_rate - rb.win_rate_mean) < 0.08


def test_trend_pullback_has_too_few_trades(evaluations):
    e = evaluations["trend_pullback"]
    assert e.gate.status == "insufficient"
    assert 0 < e.windows["holdout"].trades < 30
    assert check(e, TOO_GOOD).passed and "too few trades to judge" in check(e, TOO_GOOD).value


def test_tight_target_wins_most_trades_but_fails_with_plain_reasons(evaluations):
    e = evaluations["tight_target"]
    holdout, rb = e.windows["holdout"], e.random["holdout"]
    assert e.gate.status == "failed"
    assert 0.80 <= holdout.win_rate <= 0.85
    assert holdout.expectancy_r < 0 and not check(e, HOLDOUT_EXPECTANCY).passed
    assert rb.p_value > 0.05 and not check(e, HOLDOUT_RANDOM).passed
    assert abs(holdout.win_rate - rb.win_rate_mean) < 0.05
    assert holdout.full_stop_rate > 0.1
    assert e.extra["holdout"].stop_target_ratio == pytest.approx(5.0)
    assert not check(e, STOP_TARGET).passed
    first = e.gate.reasons[0]
    assert first.startswith("Wins 8") and "yet it loses" in first and "its stop is 5× its target" in first and "also win" in first
    text = " ".join(e.gate.reasons)
    assert "The stop is 5× the target distance" in text and "Monte Carlo tail check" in text


def test_leaky_rule_looks_great_but_is_blocked(evaluations):
    e = evaluations["leaky"]
    holdout = e.windows["holdout"]
    assert holdout.win_rate > 0.85 and holdout.expectancy_r > 0 and e.random["holdout"].p_value < 0.01
    assert not e.leak_check.passed
    assert e.gate.status == "blocked"
    assert e.gate.reasons[0].startswith("Blocked — Future-data leak on EURUSD")
    assert not check(e, TOO_GOOD).passed and TOO_GOOD_REASON in e.gate.reasons
    assert TOO_GOOD_REASON in e.hard_failures


def test_only_the_planted_control_qualifies(evaluations):
    assert [rule_id for rule_id, e in evaluations.items() if e.gate.status == "qualified"] == ["control_planted"]


def test_holm_thresholds_follow_the_ranked_p_values(evaluations):
    decisions = {rule_id: e.holm for rule_id, e in evaluations.items()}
    assert {d.tries for d in decisions.values()} == {6} and {d.family for d in decisions.values()} == {6}
    assert sorted(d.rank for d in decisions.values()) == [1, 2, 3, 4, 5, 6]
    for d in decisions.values():
        assert d.threshold == pytest.approx(0.05 / (6 - d.rank + 1))
    by_rank = sorted(decisions.values(), key=lambda d: d.rank)
    assert [d.p_value for d in by_rank] == sorted(d.p_value for d in by_rank)
    control = evaluations["control_planted"]
    assert holm_check(control).name == "Beats random after correcting for 6 tries (never-seen months)"
    assert holm_check(control).passed and "6 tries counted" in holm_check(control).value
    assert control.extra["holdout"].holm_threshold == control.holm.threshold
    assert control.extra["recent"].holm_threshold is None


def test_every_rule_version_is_recorded_once_as_a_trial(evaluations, trials_path, settings):
    log = load_trials(trials_path)
    assert sorted((r["rule_id"], r["version"]) for r in log["records"]) == sorted((r.rule_id, r.version) for r in all_rules())
    assert {r["test_sha256"] for r in log["records"]} == {trial_hash(make_plan(r, settings)) for r in all_rules()}
    assert {r["data_id"] for r in log["records"]} == {"synthetic"} and {r["locked_at"] for r in log["records"]} == {LOCKED_AT}
    assert all(e.trial_count == 6 and e.prior_trials == 0 and e.trials_note is None for e in evaluations.values())


def test_evaluations_are_complete_and_serialisable(evaluations):
    for e in evaluations.values():
        assert set(e.windows) == set(WINDOW_NAMES) and set(e.random) == {"holdout", "recent"} and set(e.extra) == {"holdout", "recent"}
        assert {name: len(trades) for name, trades in e.trades.items()} == {name: m.trades for name, m in e.windows.items()}
        assert e.plan.valid and len(e.plan.sha256) == 64 and e.plan.locked_at
        assert e.signals == sum(e.signals_by_symbol.values()) > 0
        assert set(e.median_stop_points) == set(e.symbols)
        assert all(v and v > 0 for v in e.median_stop_points.values())
        d = json.loads(json.dumps(e.to_dict()))
        assert {"trades", "wins", "losses", "win_rate", "win_rate_ci", "full_stop_rate", "breakeven_rate", "expectancy_r",
                "profit_factor", "max_drawdown_r", "avg_hold_bars", "equity_r", "random", "extra"} <= set(d["windows"]["holdout"])
        assert "random" not in d["windows"]["development"] and "extra" not in d["windows"]["development"]
        for name in ("holdout", "recent"):
            extra = d["windows"][name]["extra"]
            assert set(extra) == EXTRA_KEYS
            assert set(extra["long"]) == set(extra["short"]) == {"trades", "win_rate", "expectancy_r"}
            assert [t["name"] for t in extra["terciles"]] == ["low", "mid", "high"]
            assert all(set(t) == {"name", "trades", "expectancy_r"} for t in extra["terciles"])
            assert extra["long"]["trades"] + extra["short"]["trades"] == d["windows"][name]["trades"]
            assert extra["trial_count"] == 6
        assert len(d["windows"]["recent"]["random"]["hist"]["counts"]) == 25
        assert d["windows"]["development"]["start"] == "2024-10-30T22:00:00Z"
        assert d["windows"]["development"]["end"] == d["windows"]["holdout"]["start"]
        assert d["windows"]["holdout"]["end"] == d["windows"]["recent"]["start"]
        assert d["gate"]["status"] in ("qualified", "failed", "insufficient", "blocked")
        assert len(d["gate"]["checks"]) == 15
        assert d["kind"] in ("rule", "self_test") and d["trial_count"] == 6


def test_label_counts_add_up(evaluations):
    for e in evaluations.values():
        for m in e.windows.values():
            if m.trades:
                breakevens = round(m.breakeven_rate * m.trades)
                assert m.wins + m.losses + breakevens == m.trades
                assert round(m.full_stop_rate * m.trades) <= m.losses


def test_windows_follow_the_spec(demo, settings):
    bounds = dataset_bounds(demo, settings)
    last = pd.Timestamp("2026-10-30 21:45", tz="UTC")
    assert bounds["recent"] == (pd.Timestamp("2026-07-30 21:45", tz="UTC"), last)
    assert bounds["holdout"] == (pd.Timestamp("2026-01-30 21:45", tz="UTC"), pd.Timestamp("2026-07-30 21:45", tz="UTC"))


def test_missing_plan_blocks_and_hides_the_never_seen_results(tmp_path, demo, settings):
    e = evaluate_rule(get_rule("trend_pullback"), demo, settings, tmp_path)
    assert e.gate.status == "blocked" and e.results_hidden
    assert not e.plan.valid and "No locked test plan" in e.plan.reason
    assert e.gate.reasons[0].startswith("Blocked — Test plan:")
    assert "stay hidden until the plan is locked" in e.gate.reasons[-1]
    assert e.windows["holdout"].trades == e.windows["recent"].trades == 0 and e.random["holdout"].runs == 0
    assert e.trades["holdout"] == [] and e.windows["development"].trades > 0


def test_the_demo_passes_the_lock_check_as_a_labelled_exception(evaluations):
    plan = check(evaluations["demo_rule_a"], PLAN_CHECK)
    assert plan.passed and plan.value.startswith("Locked 2026-11-01")
    assert "never-seen months 2026-01-30 to 2026-07-30 are synthetic: a demo exception" in plan.value


def broker(demo):
    return {s: (df, {**prov, "source": "mt5_export", "server": "Demo-Server"}) for s, (df, prov) in demo.items() if s != "CTRL-SYN"}


def test_on_broker_data_a_plan_locked_after_the_never_seen_months_began_is_blocked(tmp_path, demo, settings):
    real = broker(demo)
    lock_all_plans(settings, tmp_path, locked_at=LOCKED_AT)
    e = evaluate_rule(get_rule("trend_pullback"), real, settings, tmp_path)
    assert e.gate.status == "blocked" and e.results_hidden and e.windows["holdout"].trades == 0
    assert not check(e, PLAN_CHECK).passed and "after its never-seen months began (2026-01-30)" in e.plan.reason
    assert "lock trend_pullback --unstudied-since 2026-01-30 --yes" in e.plan.reason
    self_test = evaluate_rule(get_rule("tight_target"), real, settings, tmp_path)
    assert self_test.gate.status == "failed" and "self-test only checks the harness" in check(self_test, PLAN_CHECK).value


@pytest.mark.parametrize("lock", [{"locked_at": "2026-01-15T00:00:00Z"}, {"locked_at": LOCKED_AT, "unstudied_since": "2026-01-01"}],
                         ids=["locked-before", "declared-unstudied"])
def test_on_broker_data_an_early_lock_or_a_declaration_passes(tmp_path, demo, settings, lock):
    lock_rule(get_rule("trend_pullback"), settings, tmp_path, **lock)
    e = evaluate_rule(get_rule("trend_pullback"), broker(demo), settings, tmp_path)
    assert check(e, PLAN_CHECK).passed and not e.results_hidden and e.gate.status == "insufficient"
    expected = "before the never-seen months 2026-01-30 to 2026-07-30 began" if "unstudied_since" not in lock else "declared the months from 2026-01-01 unstudied"
    assert expected in check(e, PLAN_CHECK).value


def test_a_test_seen_before_its_lock_fails_the_lock_check(tmp_path, demo, settings, plans_dir):
    control = {"CTRL-SYN": demo["CTRL-SYN"]}
    trials = tmp_path / "trials.json"
    tested = trial_hash(make_plan(get_rule("control_planted"), settings))
    record_trials(trials, "synthetic", "f0", [TrialEntry("control_planted", "2", tested, None)], dataset_bounds(control, settings)["holdout"],
                  "2026-11-01T21:00:00Z")
    e = {x.rule_id: x for x in evaluate_all(control, settings, plans_dir, trials_path=trials)}["control_planted"]
    assert e.gate.status == "blocked" and not check(e, PLAN_CHECK).passed
    assert "already tested 2026-11-01 21:00 UTC, before this plan was locked (2026-11-01 22:00 UTC)" in e.plan.reason


def test_a_fresh_export_of_the_same_months_keeps_the_try_count(tmp_path, demo, settings, plans_dir):
    control = {"CTRL-SYN": demo["CTRL-SYN"]}
    trials = tmp_path / "trials.json"
    first = evaluate_all(control, settings, plans_dir, trials_path=trials)
    df, prov = demo["CTRL-SYN"]
    later = {"CTRL-SYN": (df.iloc[:-1], {**prov, "sha256": "f" * 64})}
    again = evaluate_all(later, settings, plans_dir, trials_path=trials)
    assert first[0].trial_count == again[0].trial_count == 6


def test_a_risk_only_change_relocked_adds_no_tries(tmp_path, demo, settings):
    control = {"CTRL-SYN": demo["CTRL-SYN"]}
    plans, trials = tmp_path / "plans", tmp_path / "trials.json"
    lock_all_plans(settings, plans, locked_at=LOCKED_AT)
    before = evaluate_all(control, settings, plans, trials_path=trials)[0]
    risky = copy.deepcopy(settings)
    risky["risk"]["risk_per_trade_pct"] = 0.4
    lock_all_plans(risky, plans)
    after = evaluate_all(control, risky, plans, trials_path=trials)[0]
    assert after.trial_count == before.trial_count == 6 and after.holm.threshold == before.holm.threshold
    assert after.plan.locked_at == LOCKED_AT and after.gate.status == "qualified"


class FadedRuleA(DemoRuleA):
    def generate(self, df, symbol):
        signals = super().generate(df, symbol)
        for s in signals:
            s.side, s.stop, s.target = -s.side, s.target, s.stop
        return signals


def test_editing_a_rules_code_blocks_it_and_hides_its_results(demo, settings, plans_dir):
    e = evaluate_rule(FadedRuleA(), demo, settings, plans_dir)
    assert e.gate.status == "blocked" and e.results_hidden
    assert "the rule's code" in e.plan.reason


def test_changed_rule_blocks_and_plan_is_not_rewritten(tmp_path, demo, settings, plans_dir):
    shutil.copy(plans_dir / "trend_pullback.json", tmp_path)
    before = (tmp_path / "trend_pullback.json").read_text()
    rule = get_rule("trend_pullback")
    rule.params["rsi_low"] = 30
    e = evaluate_rule(rule, demo, settings, tmp_path)
    assert e.gate.status == "blocked"
    assert "params.rsi_low 25 -> 30" in e.plan.reason
    assert (tmp_path / "trend_pullback.json").read_text() == before


def test_changed_risk_settings_block_every_rule(demo, settings, plans_dir):
    changed = {**settings, "risk": {**settings["risk"], "risk_per_trade_pct": 5.0}}
    e = evaluate_rule(get_rule("control_planted"), demo, changed, plans_dir)
    assert e.gate.status == "blocked"
    assert "risk_config_sha256" in e.plan.reason


def test_missing_symbol_data_blocks(demo, settings, plans_dir):
    partial = {symbol: pair for symbol, pair in demo.items() if symbol != "USDJPY"}
    e = evaluate_rule(get_rule("trend_pullback"), partial, settings, plans_dir)
    assert e.gate.status == "blocked"
    assert any(h.startswith("No data for USDJPY") for h in e.hard_failures)


class NoStopRule(DemoRuleA):
    def generate(self, df, symbol):
        signals = super().generate(df, symbol)
        signals[0].stop = None
        return signals


def test_rule_emitting_a_signal_without_stop_is_blocked_not_crashed(demo, settings, plans_dir):
    e = evaluate_rule(NoStopRule(), demo, settings, plans_dir)
    assert e.gate.status == "blocked"
    assert any("has no stop-loss" in h for h in e.hard_failures)


class HalfStoplessRule(DemoRuleA):
    def generate(self, df, symbol):
        from llm_trader.signals.demo_rule_a import prior_day_reversal_arrays

        side, stop, target = prior_day_reversal_arrays(df, self.params)
        stop[np.flatnonzero(side)[::2]] = np.nan
        return self.signals_from_arrays(df, symbol, side, stop, target, self.params["max_hold_bars"])


def test_signals_whose_stop_could_not_be_computed_block_the_rule(demo, settings, plans_dir):
    rule = HalfStoplessRule()
    signals = rule.generate(demo["EURUSD"][0], "EURUSD")
    assert sum(s.stop is None for s in signals) == (len(signals) + 1) // 2
    e = evaluate_rule(rule, demo, settings, plans_dir)
    assert e.gate.status == "blocked" and any(h.startswith("Rejected signal") and "has no stop-loss" in h for h in e.hard_failures)
    rows = c.stop_checks([e])
    assert rows and all(r["status"] == "fail" and "blocked until every signal carries a stop" in r["detail"] for r in rows)


def test_standalone_rule_counts_prior_trials(demo, settings, plans_dir):
    e = evaluate_rule(get_rule("control_planted"), demo, settings, plans_dir)
    assert (e.trial_count, e.holm.tries, e.holm.threshold) == (1, 1, 0.05)
    assert holm_check(e).name == "Beats random after correcting for 1 try (never-seen months)"


def test_evaluation_is_deterministic(evaluations, demo, settings, plans_dir):
    again = evaluate_rule(get_rule("control_planted"), demo, settings, plans_dir, trial_count=6)
    first = evaluations["control_planted"].to_dict(include_trades=True)
    second = again.to_dict(include_trades=True)
    ranked = ("holm", "gate")
    assert {k: v for k, v in first.items() if k not in ranked} == {k: v for k, v in second.items() if k not in ranked}
    assert again.gate.status == "qualified" and again.holm.threshold == evaluations["control_planted"].holm.threshold


def test_unreadable_trial_log_fails_holm_but_keeps_running(tmp_path, demo, settings, plans_dir):
    bad = tmp_path / "trials.json"
    bad.write_text("{broken")
    subset = {s: demo[s] for s in ("CTRL-SYN",)}
    evaluations = {e.rule_id: e for e in evaluate_all(subset, settings, plans_dir, trials_path=bad)}
    control = evaluations["control_planted"]
    assert control.gate.status == "failed" and not holm_check(control).passed
    assert "trial log is unreadable" in holm_check(control).value
    assert bad.read_text() == "{broken"


def test_planted_control_qualifies_on_almost_every_seed(tmp_path, settings):
    fast = copy.deepcopy(settings)
    fast["evaluation"].update(leak_cuts=4, random_runs=300)
    rule = get_rule("control_planted")
    lock_rule(rule, fast, tmp_path, locked_at=LOCKED_AT)
    grid = synthetic.demo_calendar()
    statuses = []
    for seed in range(1, 21):
        df, extra = synthetic._symbol_frame("CTRL-SYN", grid, synthetic._factors(seed, len(grid)), seed)
        data = {"CTRL-SYN": (df, synthetic.synthetic_provenance("CTRL-SYN", df, seed, extra))}
        bounds = dataset_bounds(data, fast)
        raw = raw_evaluation(rule, data, fast, tmp_path, bounds)
        statuses.append(finish_evaluation(raw, fast, bounds, holm_decisions([raw.holdout_p], 6, 0.05)[0], 6).gate.status)
    assert statuses.count("qualified") >= 19, statuses


def test_full_demo_evaluation_is_fast(timed_evaluations):
    assert timed_evaluations[1] < 120
