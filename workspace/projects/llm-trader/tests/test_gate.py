import pytest

from llm_trader.eval.gate import DEFAULT_GATE, TOO_GOOD_REASON, evaluate_gate
from llm_trader.eval.metrics import wilson_interval
from llm_trader.eval.trials import holm_decisions
from llm_trader.models import HolmDecision, RandomBaseline, WindowExtra, WindowMetrics

CHECK_NAMES = [
    "Plan locked before testing",
    "Not too good to be true (win rate ≤ 90%, profit factor ≤ 4)",
    "Enough trades in never-seen months",
    "Win rate ≥ 80% in never-seen months",
    "Positive expectancy after costs (never-seen months)",
    "Expectancy lower 95% bound above 0 (never-seen months)",
    "Still profitable at 1.5× costs (never-seen months)",
    "Beats random entries (never-seen months)",
    "Beats random after correcting for 6 tries (never-seen months)",
    "Positive in at least 2 of 3 volatility regimes (never-seen months)",
    "Stop no more than 2× the target distance",
    "Enough trades in last 3 months",
    "Win rate ≥ 80% in last 3 months",
    "Positive expectancy after costs (last 3 months)",
    "Beats random entries (last 3 months)",
]
LOWER = "Expectancy lower 95% bound above 0 (never-seen months)"
STRESS = "Still profitable at 1.5× costs (never-seen months)"
TERCILES = "Positive in at least 2 of 3 volatility regimes (never-seen months)"
RATIO = "Stop no more than 2× the target distance"
TOO_GOOD = "Not too good to be true (win rate ≤ 90%, profit factor ≤ 4)"


def metrics(trades: int, win_rate: float, expectancy: float, pf: float | None = 2.5) -> WindowMetrics:
    wins = round(trades * win_rate)
    return WindowMetrics(None, None, trades, wins, trades - wins, wins / trades if trades else None, wilson_interval(wins, trades),
                         0.1, 0.0, expectancy if trades else None, pf if trades else None, 1.0, 4.0, [])


def baseline(p: float, win_rate: float = 0.45, expectancy: float = -0.1, runs: int = 1000) -> RandomBaseline:
    return RandomBaseline(runs, p, p, expectancy, expectancy + 0.1, win_rate, win_rate + 0.05, {"bin_edges": [], "counts": []})


def extra(ci=(0.1, 0.5), stressed=0.2, doubled=0.1, terciles=((40, 0.2), (40, 0.3), (40, 0.25)), ratio=1.0, trial_count=6) -> WindowExtra:
    side = {"trades": 50, "win_rate": 0.8, "expectancy_r": 0.3}
    rows = [{"name": n, "trades": t, "expectancy_r": e} for n, (t, e) in zip(("low", "mid", "high"), terciles)]
    return WindowExtra(ci, stressed, doubled, dict(side), dict(side), rows, ratio, None, trial_count)


def holm(p: float = 0.001, rank: int = 1, tries: int = 6) -> HolmDecision:
    threshold = 0.05 / (tries - rank + 1)
    return HolmDecision(p, rank, 6, tries, threshold, p <= threshold)


GOOD = (metrics(100, 0.86, 0.5), baseline(0.001), metrics(50, 0.88, 0.55), baseline(0.001))


def gate(windows=GOOD, hard=(), cfg=None, **kw):
    kw.setdefault("holdout_extra", extra())
    kw.setdefault("holm", holm())
    return evaluate_gate(*windows, cfg or DEFAULT_GATE, list(hard), **kw)


def by_name(result):
    return {c.name: c for c in result.checks}


def test_check_names_are_exact_and_ordered():
    assert [c.name for c in gate().checks] == CHECK_NAMES


def test_all_checks_passing_qualifies_with_plain_reasons():
    result = gate()
    assert result.status == "qualified"
    assert all(c.passed for c in result.checks)
    assert "86.0%" in result.reasons[0] and "95% range +0.10R to +0.50R" in result.reasons[0]
    assert "after correcting for 6 tries" in result.reasons[1] and "p ≤ 0.0083" in result.reasons[1]
    assert "1.5× costs (+0.20R per trade) and in 3 of 3 volatility regimes" in result.reasons[2]
    assert any("forward test" in line for line in result.reasons)


def test_hard_failure_blocks_even_great_numbers():
    result = gate(hard=["Future-data leak on EURUSD: 6 of 12 re-runs changed earlier signals."])
    assert result.status == "blocked"
    assert result.reasons[0].startswith("Blocked — Future-data leak")


def test_unlocked_plan_blocks():
    result = gate(plan_ok=False, plan_note="No locked test plan.")
    assert result.status == "blocked"
    assert result.checks[0].passed is False
    assert result.checks[0].value == "No locked test plan."


def test_lower_bound_needs_two_trades():
    result = gate((metrics(1, 1.0, 0.5, None), baseline(0.2), metrics(0, 0, 0), baseline(1.0)), holdout_extra=extra(ci=(None, None)))
    assert by_name(result)[LOWER].value == "fewer than 2 trades" and not by_name(result)[LOWER].passed


def test_too_few_never_seen_trades_is_insufficient_not_failed():
    result = gate((metrics(12, 0.9, 0.6), baseline(0.01), metrics(5, 1.0, 0.8), baseline(0.05)))
    assert result.status == "insufficient"
    assert "Only 12 trades" in result.reasons[0]


@pytest.mark.parametrize("win_rate, pf", [(0.91, 3.0), (0.86, 4.5), (0.95, None)], ids=["win-rate", "profit-factor", "no-losses"])
def test_too_good_to_be_true_blocks_with_a_leak_review(win_rate, pf):
    result = gate((metrics(100, win_rate, 0.5, pf), baseline(0.001), metrics(50, 0.88, 0.55), baseline(0.001)))
    assert result.status == "blocked"
    assert not by_name(result)[TOO_GOOD].passed
    assert result.reasons[0] == TOO_GOOD_REASON == "Too good to be true — needs a leak review before it can qualify."


def test_too_good_at_exactly_the_limits_passes():
    result = gate((metrics(100, 0.90, 0.5, 4.0), baseline(0.001), metrics(50, 0.88, 0.55), baseline(0.001)))
    assert by_name(result)[TOO_GOOD].passed and result.status == "qualified"


def test_too_good_is_not_judged_on_a_handful_of_trades():
    result = gate((metrics(8, 1.0, 0.5, None), baseline(0.01), metrics(3, 1.0, 0.5), baseline(0.05)))
    assert by_name(result)[TOO_GOOD].passed and "too few trades to judge (8)" in by_name(result)[TOO_GOOD].value
    assert result.status == "insufficient"


def test_high_win_rate_with_negative_expectancy_fails_with_the_trap_story():
    holdout = metrics(600, 0.81, -0.06, 0.8)
    result = gate((holdout, baseline(0.42, 0.80, -0.05), metrics(300, 0.80, -0.04), baseline(0.5, 0.79)),
                  holdout_extra=extra(ci=(-0.1, -0.02), stressed=-0.09, ratio=4.0), holm=holm(0.42, 4))
    assert result.status == "failed"
    assert result.reasons[0] == (
        "Wins 81.0% of trades in the never-seen months, yet it loses 0.06R per trade after costs: its stop is 4× its "
        "target, and the same trades at random times (same direction, stop and target) also win 80.0%."
    )
    assert result.reasons[-1].startswith("The stop is 4× the target distance (limit 2×)")
    assert "Monte Carlo tail check at real account size, is not built yet" in result.reasons[-1]
    assert not any("could be luck" in line or "Regime-specific" in line for line in result.reasons)


def test_low_win_rate_reason_names_every_failed_test():
    result = gate((metrics(200, 0.43, -0.28, 0.4), baseline(0.83, 0.46, -0.22), metrics(120, 0.46, -0.21), baseline(0.4)),
                  holdout_extra=extra(ci=(-0.4, -0.1), stressed=-0.35), holm=holm(0.83, 6))
    assert result.status == "failed"
    first = result.reasons[0]
    assert first.startswith("In the never-seen months: wins only 43.0% of trades (the bar is 80%)")
    assert "loses 0.28R" in first and "no edge over chance (p = 0.830)" in first
    assert result.reasons[1].startswith("In the last 3 months:")


def test_recent_window_alone_can_fail_a_rule():
    result = gate((metrics(120, 0.86, 0.5), baseline(0.001), metrics(6, 0.83, 0.4), baseline(0.2)))
    assert result.status == "failed"
    assert result.reasons == ["In the last 3 months: only 6 trades (needs ≥ 10); wins 83.3% of trades; the same trades at random "
                              "times win 45.0% and average -0.10R per trade, so it shows no edge over chance (p = 0.200)."]


def test_positive_average_with_a_lower_bound_below_zero_fails_as_possible_luck():
    result = gate(holdout_extra=extra(ci=(-0.02, 0.9)))
    assert result.status == "failed"
    assert not by_name(result)[LOWER].passed and by_name(result)[LOWER].value == "-0.02R (95% range -0.02R to +0.90R)"
    assert result.reasons == ["Its average of +0.50R per trade could be luck: the 95% range runs from -0.02R to +0.90R."]


def test_edge_that_vanishes_at_higher_costs_fails():
    result = gate(holdout_extra=extra(stressed=-0.01, doubled=-0.08))
    assert result.status == "failed"
    assert by_name(result)[STRESS].value == "-0.01R per trade (2× costs: -0.08R)"
    assert "At 1.5× costs it would make -0.01R per trade" in result.reasons[0]


@pytest.mark.parametrize("terciles, positive", [
    (((40, 0.2), (40, -0.1), (40, -0.3)), 1),
    (((40, 0.2), (4, 0.9), (40, -0.3)), 1),
    (((0, None), (60, 0.4), (60, 0.2)), 2),
])
def test_volatility_regimes_need_two_positive_terciles_with_five_trades(terciles, positive):
    result = gate(holdout_extra=extra(terciles=terciles))
    check = by_name(result)[TERCILES]
    assert check.value.startswith(f"positive in {positive} of 3")
    if positive < 2:
        assert result.status == "failed" and not check.passed
        assert result.reasons == [f"Regime-specific: positive in only {positive} of 3 volatility regimes — kept in shadow."]
    else:
        assert check.passed and result.status == "qualified"


def test_stop_at_exactly_twice_the_target_passes_and_wider_fails():
    assert by_name(gate(holdout_extra=extra(ratio=2.0 + 1e-12)))[RATIO].passed
    wide = gate(holdout_extra=extra(ratio=2.4))
    assert not by_name(wide)[RATIO].passed and wide.status == "failed"
    assert by_name(wide)[RATIO].value == "stop is 2.4× the target (median)"


def test_holm_threshold_and_trial_count_are_reported():
    result = gate(holm=holm(0.004, rank=2, tries=6))
    check = result.checks[8]
    assert check.passed and check.required == "p ≤ 0.01 (0.05 ÷ 5, Holm)"
    assert check.value == "p = 0.004 (rank 2 of 6 rules; 6 tries counted)"


def test_beating_random_but_not_after_correction_fails_with_reason():
    result = gate((metrics(100, 0.86, 0.5), baseline(0.02), metrics(50, 0.88, 0.55), baseline(0.001)), holm=holm(0.02, 1))
    assert result.status == "failed"
    assert by_name(result)["Beats random entries (never-seen months)"].passed and not result.checks[8].passed
    assert result.reasons == ["It beats random entry times (p = 0.020), but not after correcting for 6 tries on these months: "
                              "Holm's step-down needs p ≤ 0.00833 here."]


def test_holm_step_down_stops_at_the_first_failure():
    decisions = holm_decisions([0.001, 0.03, 0.012, 0.5], tries=4)
    assert [(d.rank, round(d.threshold, 4), d.passed) for d in decisions] == [
        (1, 0.0125, True), (3, 0.025, False), (2, 0.0167, True), (4, 0.05, False)]
    stopped = holm_decisions([0.024, 0.018, 0.001], tries=4)
    assert [(d.rank, d.passed, d.stopped_early) for d in stopped] == [(3, False, True), (2, False, False), (1, True, False)]
    assert stopped[0].p_value <= stopped[0].threshold
    assert holm_decisions([0.004], tries=10)[0].passed and holm_decisions([0.006], tries=10)[0].passed is False
    assert holm_decisions([], tries=6) == []


def test_holm_counts_earlier_studies_and_admits_when_runs_cannot_resolve_it():
    decision = holm_decisions([1 / 1001], tries=59)[0]
    result = gate(holdout_extra=extra(trial_count=59), holm=decision, cfg={**DEFAULT_GATE, "prior_trials": 53})
    check = result.checks[8]
    assert check.name == "Beats random after correcting for 59 tries (never-seen months)"
    assert not check.passed and result.status == "failed"
    assert "59 tries counted, 53 from earlier studies" in check.value
    assert "1,000 random runs cannot show p below 0.0010: raise evaluation.random_runs" in check.value
    assert check.required == "p ≤ 0.000847 (0.05 ÷ 59, Holm)"


def test_missing_holm_decision_is_treated_as_a_single_test():
    result = evaluate_gate(*GOOD, DEFAULT_GATE, [], holdout_extra=extra(trial_count=1))
    assert result.checks[8].name == "Beats random after correcting for 1 try (never-seen months)"
    assert result.checks[8].required == "p ≤ 0.05 (0.05 ÷ 1, Holm)" and result.status == "qualified"


def test_win_rate_exactly_at_the_bar_passes():
    result = gate((metrics(100, 0.80, 0.3), baseline(0.01), metrics(40, 0.80, 0.3), baseline(0.01)), holm=holm(0.01, 2, 6))
    assert result.status == "qualified"


def test_bar_is_configurable_and_named_honestly():
    cfg = {**DEFAULT_GATE, "accuracy_bar": 0.75, "require_positive_expectancy": False}
    result = gate((metrics(100, 0.76, -0.1), baseline(0.001), metrics(40, 0.78, -0.1), baseline(0.01)), cfg=cfg,
                  holdout_extra=extra(ci=(-0.2, 0.0), stressed=-0.2))
    assert result.checks[3].name == "Win rate ≥ 75% in never-seen months"
    assert result.checks[4].required == "not required"
    assert result.status == "qualified"


def test_custom_recent_label():
    result = gate(recent_label="last 2 months")
    assert result.checks[-1].name == "Beats random entries (last 2 months)"


def test_check_values_are_human_readable():
    checks = by_name(gate())
    assert checks["Enough trades in never-seen months"].value == "100 trades"
    assert checks["Win rate ≥ 80% in never-seen months"].value.startswith("86.0% (95% CI")
    assert checks["Positive expectancy after costs (never-seen months)"].value == "+0.50R per trade"
    assert checks["Beats random entries (never-seen months)"].value.startswith("p = 0.001")
    assert checks["Beats random entries (never-seen months)"].required == "p ≤ 0.05"
    assert checks[TOO_GOOD].value == "86.0% win rate, profit factor 2.50"
    assert checks[TERCILES].value == "positive in 3 of 3 (low +0.20R on 40, mid +0.30R on 40, high +0.25R on 40)"
    assert checks[RATIO].value == "stop is 1× the target (median)"


@pytest.mark.parametrize("status", ["qualified", "failed", "insufficient", "blocked"])
def test_every_status_has_reasons(status):
    cases = {
        "qualified": (GOOD, []),
        "failed": ((metrics(120, 0.5, -0.1), baseline(0.5), metrics(50, 0.5, -0.1), baseline(0.5)), []),
        "insufficient": ((metrics(3, 1.0, 1.0), baseline(0.2), metrics(0, 0, 0), baseline(1.0)), []),
        "blocked": (GOOD, ["Costs missing for XYZ: commission_per_lot."]),
    }
    windows, hard = cases[status]
    result = gate(windows, hard)
    assert result.status == status
    assert result.reasons and all(isinstance(r, str) and r for r in result.reasons)
