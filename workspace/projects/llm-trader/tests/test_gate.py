import pytest

from llm_trader.eval.gate import DEFAULT_GATE, evaluate_gate
from llm_trader.eval.metrics import wilson_interval
from llm_trader.models import RandomBaseline, WindowMetrics

CHECK_NAMES = [
    "Plan locked before testing",
    "Enough trades in never-seen months",
    "Win rate ≥ 80% in never-seen months",
    "Positive expectancy after costs (never-seen months)",
    "Beats random entries (never-seen months)",
    "Enough trades in last 3 months",
    "Win rate ≥ 80% in last 3 months",
    "Positive expectancy after costs (last 3 months)",
    "Beats random entries (last 3 months)",
]


def metrics(trades: int, win_rate: float, expectancy: float) -> WindowMetrics:
    wins = round(trades * win_rate)
    return WindowMetrics(None, None, trades, wins, wins / trades if trades else None, wilson_interval(wins, trades),
                         0.1, 0.0, expectancy if trades else None, None, 1.0, 4.0, [])


def baseline(p: float, win_rate: float = 0.45, expectancy: float = -0.1) -> RandomBaseline:
    return RandomBaseline(1000, p, p, expectancy, expectancy + 0.1, win_rate, win_rate + 0.05, {"bin_edges": [], "counts": []})


GOOD = (metrics(100, 0.86, 0.5), baseline(0.001), metrics(50, 0.88, 0.55), baseline(0.001))


def test_check_names_are_exact_and_ordered():
    result = evaluate_gate(*GOOD, DEFAULT_GATE, [])
    assert [c.name for c in result.checks] == CHECK_NAMES


def test_all_checks_passing_qualifies_with_plain_reasons():
    result = evaluate_gate(*GOOD, DEFAULT_GATE, [])
    assert result.status == "qualified"
    assert all(c.passed for c in result.checks)
    assert "86.0%" in result.reasons[0]
    assert any("random" in line.lower() for line in result.reasons)
    assert any("forward test" in line for line in result.reasons)


def test_hard_failure_blocks_even_great_numbers():
    result = evaluate_gate(*GOOD, DEFAULT_GATE, ["Future-data leak on EURUSD: 6 of 12 re-runs changed earlier signals."])
    assert result.status == "blocked"
    assert result.reasons[0].startswith("Blocked — Future-data leak")


def test_unlocked_plan_blocks():
    result = evaluate_gate(*GOOD, DEFAULT_GATE, [], plan_ok=False, plan_note="No locked test plan.")
    assert result.status == "blocked"
    assert result.checks[0].passed is False
    assert result.checks[0].value == "No locked test plan."


def test_too_few_never_seen_trades_is_insufficient_not_failed():
    result = evaluate_gate(metrics(12, 0.9, 0.6), baseline(0.01), metrics(5, 1.0, 0.8), baseline(0.05), DEFAULT_GATE, [])
    assert result.status == "insufficient"
    assert "Only 12 trades" in result.reasons[0]


def test_high_win_rate_with_negative_expectancy_fails_with_the_trap_story():
    holdout = metrics(600, 0.81, -0.06)
    result = evaluate_gate(holdout, baseline(0.42, 0.80, -0.05), metrics(300, 0.80, -0.04), baseline(0.5, 0.79), DEFAULT_GATE, [])
    assert result.status == "failed"
    assert result.reasons[0] == (
        "Wins 81.0% of trades in the never-seen months, but random entries with the same stop/target also win 80.0% "
        "and it loses 0.06R per trade after costs."
    )


def test_low_win_rate_reason_names_every_failed_test():
    result = evaluate_gate(metrics(200, 0.43, -0.28), baseline(0.83, 0.46, -0.22), metrics(120, 0.46, -0.21), baseline(0.4), DEFAULT_GATE, [])
    assert result.status == "failed"
    first = result.reasons[0]
    assert first.startswith("In the never-seen months: wins only 43.0% of trades (the bar is 80%)")
    assert "loses 0.28R" in first and "no edge over chance (p = 0.830)" in first
    assert result.reasons[1].startswith("In the last 3 months:")


def test_recent_window_alone_can_fail_a_rule():
    result = evaluate_gate(metrics(120, 0.86, 0.5), baseline(0.001), metrics(6, 0.83, 0.4), baseline(0.2), DEFAULT_GATE, [])
    assert result.status == "failed"
    assert result.reasons == ["In the last 3 months: only 6 trades (needs ≥ 10); wins 83.3% of trades; random entries with the same stop/target "
                              "win 45.0% and average -0.10R per trade, so it shows no edge over chance (p = 0.200)."]


def test_win_rate_exactly_at_the_bar_passes():
    result = evaluate_gate(metrics(100, 0.80, 0.3), baseline(0.01), metrics(40, 0.80, 0.3), baseline(0.01), DEFAULT_GATE, [])
    assert result.status == "qualified"


def test_bar_is_configurable_and_named_honestly():
    cfg = {**DEFAULT_GATE, "accuracy_bar": 0.75, "require_positive_expectancy": False}
    result = evaluate_gate(metrics(100, 0.76, -0.1), baseline(0.01), metrics(40, 0.78, -0.1), baseline(0.01), cfg, [])
    assert result.checks[2].name == "Win rate ≥ 75% in never-seen months"
    assert result.checks[3].required == "not required"
    assert result.status == "qualified"


def test_custom_recent_label():
    result = evaluate_gate(*GOOD, DEFAULT_GATE, [], recent_label="last 2 months")
    assert result.checks[-1].name == "Beats random entries (last 2 months)"


def test_check_values_are_human_readable():
    result = evaluate_gate(*GOOD, DEFAULT_GATE, [])
    by_name = {c.name: c for c in result.checks}
    assert by_name["Enough trades in never-seen months"].value == "100 trades"
    assert by_name["Win rate ≥ 80% in never-seen months"].value.startswith("86.0% (95% CI")
    assert by_name["Positive expectancy after costs (never-seen months)"].value == "+0.50R per trade"
    assert by_name["Beats random entries (never-seen months)"].value.startswith("p = 0.001")
    assert by_name["Beats random entries (never-seen months)"].required == "p ≤ 0.05"


@pytest.mark.parametrize("status", ["qualified", "failed", "insufficient", "blocked"])
def test_every_status_has_reasons(status):
    cases = {
        "qualified": (GOOD, []),
        "failed": ((metrics(120, 0.5, -0.1), baseline(0.5), metrics(50, 0.5, -0.1), baseline(0.5)), []),
        "insufficient": ((metrics(3, 1.0, 1.0), baseline(0.2), metrics(0, 0, 0), baseline(1.0)), []),
        "blocked": (GOOD, ["Costs missing for XYZ: commission_per_lot."]),
    }
    windows, hard = cases[status]
    result = evaluate_gate(*windows, DEFAULT_GATE, hard)
    assert result.status == status
    assert result.reasons and all(isinstance(r, str) and r for r in result.reasons)
