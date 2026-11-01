import copy
import json

import pytest

from llm_trader.eval.plans import lock_plan, load_plan, make_plan, plan_hash, save_plan, verify_plan
from llm_trader.signals.registry import all_rules, get_rule

LOCKED_AT = "2026-11-01T20:00:00Z"


@pytest.fixture
def rule():
    return get_rule("sweep_fade")


def test_plan_records_everything_that_decides_the_result(rule, settings):
    plan = make_plan(rule, settings)
    assert plan["rule_id"] == "sweep_fade"
    assert plan["params"] == rule.params
    assert plan["symbols"] == ["XAUUSD", "EURUSD"]
    assert plan["windows"] == {"holdout_months": 6, "recent_months": 3}
    assert plan["gate"]["accuracy_bar"] == 0.8
    assert plan["evaluation"]["random_runs"] == 1000
    assert set(plan["costs"]["symbols"]) == {"XAUUSD", "EURUSD"}
    assert plan["costs"]["symbols"]["XAUUSD"]["commission_per_lot"] == 7.0
    assert plan["data_requirement"] == "mt5_export"


def test_lock_adds_hash_and_time_and_hash_ignores_them(rule, settings):
    locked = lock_plan(make_plan(rule, settings), LOCKED_AT)
    assert locked["locked_at"] == LOCKED_AT
    assert locked["sha256"] == plan_hash(make_plan(rule, settings))
    assert lock_plan(locked, "2027-01-01T00:00:00Z")["sha256"] == locked["sha256"]


def test_hash_ignores_key_order(rule, settings):
    plan = make_plan(rule, settings)
    reordered = dict(reversed(list(plan.items())))
    assert plan_hash(reordered) == plan_hash(plan)


@pytest.mark.parametrize(
    "change",
    [
        lambda r, s: r.params.update(target_r=1.5),
        lambda r, s: setattr(r, "version", "2"),
        lambda r, s: s["gate"].update(accuracy_bar=0.7),
        lambda r, s: s["costs"]["symbols"]["XAUUSD"].update(commission_per_lot=3.0),
        lambda r, s: s["windows"].update(holdout_months=4),
        lambda r, s: s["evaluation"].update(random_runs=100),
    ],
    ids=["params", "version", "gate", "costs", "windows", "random_runs"],
)
def test_any_change_after_locking_is_caught(change, settings):
    rule = get_rule("sweep_fade")
    locked = lock_plan(make_plan(rule, settings), LOCKED_AT)
    changed_settings = copy.deepcopy(settings)
    change(rule, changed_settings)
    assert plan_hash(make_plan(rule, changed_settings)) != locked["sha256"]
    ok, reason = verify_plan(locked, rule, changed_settings)
    assert not ok
    assert reason.startswith("Changed after the plan was locked")


def test_param_change_reason_names_the_parameter(rule, settings):
    locked = lock_plan(make_plan(rule, settings), LOCKED_AT)
    rule.params["target_r"] = 1.5
    ok, reason = verify_plan(locked, rule, settings)
    assert not ok
    assert "params.target_r 1.0 -> 1.5" in reason


def test_edited_plan_file_fails_its_own_hash(rule, settings):
    locked = lock_plan(make_plan(rule, settings), LOCKED_AT)
    locked["params"]["target_r"] = 2.0
    ok, reason = verify_plan(locked, rule, settings)
    assert not ok
    assert "hash no longer matches" in reason


def test_missing_plan_fails(rule, settings):
    ok, reason = verify_plan(None, rule, settings)
    assert not ok
    assert "No locked test plan" in reason


def test_fresh_plan_verifies(rule, settings):
    assert verify_plan(lock_plan(make_plan(rule, settings), LOCKED_AT), rule, settings) == (True, None)


def test_save_and_load_round_trip_keeps_the_hash_valid(tmp_path, rule, settings):
    locked = lock_plan(make_plan(rule, settings), LOCKED_AT)
    path = save_plan(tmp_path, locked)
    assert path.name == "sweep_fade.json"
    assert load_plan(tmp_path, "sweep_fade") == locked
    assert verify_plan(load_plan(tmp_path, "sweep_fade"), rule, settings) == (True, None)
    assert load_plan(tmp_path, "unknown") is None


def test_unreadable_plan_file_raises(tmp_path):
    (tmp_path / "broken.json").write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_plan(tmp_path, "broken")


def test_committed_plans_match_current_rules_and_settings(plans_dir, settings):
    for rule in all_rules():
        locked = load_plan(plans_dir, rule.rule_id)
        assert verify_plan(locked, rule, settings) == (True, None), rule.rule_id
        assert json.loads((plans_dir / f"{rule.rule_id}.json").read_text())["sha256"] == locked["sha256"]
