import copy
import json

import pytest

from llm_trader.eval.plans import (
    _class_source, canonical_json, lock_all_plans, lock_plan, lock_rule, load_plan, make_plan, plan_hash, risk_config_hash,
    rule_code_hash, save_plan, trial_hash, verify_plan,
)
from llm_trader.signals.demo_rule_a import DemoRuleA
from llm_trader.signals.registry import all_rules, get_rule

LOCKED_AT = "2026-11-01T20:00:00Z"


@pytest.fixture
def rule():
    return get_rule("demo_rule_a")


def test_plan_records_everything_that_decides_the_result(rule, settings):
    plan = make_plan(rule, settings)
    assert plan["rule_id"] == "demo_rule_a"
    assert plan["params"] == rule.params
    assert plan["symbols"] == ["XAUUSD", "EURUSD"]
    assert plan["windows"] == {"holdout_months": 6, "recent_months": 3}
    assert plan["gate"]["accuracy_bar"] == 0.8
    assert plan["evaluation"]["random_runs"] == 1000
    assert set(plan["costs"]["symbols"]) == {"XAUUSD", "EURUSD"}
    assert plan["costs"]["symbols"]["XAUUSD"]["commission_per_lot"] == 7.0
    assert plan["data_requirement"] == "mt5_export"
    assert plan["version"] == "2" and plan["origin"] == "human (demo)"
    assert plan["risk_config_sha256"] == risk_config_hash(settings)
    assert plan["gate"]["win_threshold_r"] == 0.1 and plan["gate"]["prior_trials"] == 0
    assert plan["code_sha256"] == rule_code_hash(rule) and len(plan["code_sha256"]) == 64


class EditedRuleA(DemoRuleA):
    def generate(self, df, symbol):
        signals = super().generate(df, symbol)
        for s in signals:
            s.side = -s.side
        return signals


def test_editing_a_rules_code_without_a_new_version_is_caught(rule, settings):
    locked = lock_plan(make_plan(rule, settings), LOCKED_AT)
    edited = EditedRuleA()
    assert (edited.rule_id, edited.version, edited.params) == (rule.rule_id, rule.version, rule.params)
    ok, reason = verify_plan(locked, edited, settings)
    assert not ok and reason.startswith("Changed after the plan was locked: the rule's code ")
    assert trial_hash(make_plan(edited, settings)) != trial_hash(locked)


def test_code_hash_ignores_windows_line_endings(tmp_path, monkeypatch):
    source = _class_source(DemoRuleA)
    crlf = tmp_path / "demo_rule_a.py"
    crlf.write_bytes(source.replace("\n", "\r\n").encode("utf-8"))
    monkeypatch.setattr("inspect.getsourcefile", lambda cls: str(crlf))
    assert _class_source(DemoRuleA) == source


def test_test_hash_leaves_out_risk_and_origin_only(rule, settings):
    plan = make_plan(rule, settings)
    risky = make_plan(rule, {**settings, "risk": {**settings["risk"], "risk_per_trade_pct": 0.4}})
    assert risky["risk_config_sha256"] != plan["risk_config_sha256"]
    assert trial_hash(risky) == trial_hash(plan) and plan_hash(risky) != plan_hash(plan)
    rule.params["target_r"] = 0.75
    assert trial_hash(make_plan(rule, settings)) != trial_hash(plan)


def test_relocking_the_same_test_keeps_its_original_lock_time(tmp_path, rule, settings):
    first = lock_rule(rule, settings, tmp_path, locked_at=LOCKED_AT)
    risk_only = {**settings, "risk": {**settings["risk"], "risk_per_trade_pct": 0.4}}
    again = lock_rule(rule, risk_only, tmp_path)
    assert again["locked_at"] == LOCKED_AT and again["sha256"] != first["sha256"]
    assert verify_plan(load_plan(tmp_path, rule.rule_id), rule, risk_only) == (True, None)
    rule.params["target_r"] = 0.75
    assert lock_rule(rule, risk_only, tmp_path)["locked_at"] != LOCKED_AT


def test_a_declaration_is_locked_into_the_hash_and_kept_for_the_same_test(tmp_path, rule, settings):
    plan = lock_rule(rule, settings, tmp_path, locked_at=LOCKED_AT, unstudied_since="2026-01-01")
    assert plan["unstudied_since"] == "2026-01-01T00:00:00Z" and verify_plan(plan, rule, settings) == (True, None)
    assert lock_rule(rule, settings, tmp_path)["unstudied_since"] == "2026-01-01T00:00:00Z"
    forged = {**plan, "unstudied_since": "2025-01-01T00:00:00Z"}
    assert verify_plan(forged, rule, settings)[1].startswith("The plan file was edited after it was locked")
    rule.params["target_r"] = 0.75
    assert "unstudied_since" not in lock_rule(rule, settings, tmp_path)


def test_risk_hash_covers_the_risk_section_only(settings):
    import hashlib
    assert risk_config_hash(settings) == hashlib.sha256(canonical_json(settings["risk"]).encode()).hexdigest()
    assert risk_config_hash({**settings, "llm": {"model": "other"}}) == risk_config_hash(settings)
    assert risk_config_hash({**settings, "risk": {**settings["risk"], "max_open_positions": 9}}) != risk_config_hash(settings)


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
        lambda r, s: setattr(r, "version", "3"),
        lambda r, s: s["gate"].update(accuracy_bar=0.7),
        lambda r, s: s["costs"]["symbols"]["XAUUSD"].update(commission_per_lot=3.0),
        lambda r, s: s["windows"].update(holdout_months=4),
        lambda r, s: s["evaluation"].update(random_runs=100),
        lambda r, s: s["risk"].update(risk_per_trade_pct=2.0),
        lambda r, s: s["gate"].update(prior_trials=53),
        lambda r, s: setattr(r, "origin", "claude-opus-5-5 (cutoff 2026-06)"),
    ],
    ids=["params", "version", "gate", "costs", "windows", "random_runs", "risk", "prior_trials", "origin"],
)
def test_any_change_after_locking_is_caught(change, settings):
    rule = get_rule("demo_rule_a")
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
    assert "params.target_r 0.5 -> 1.5" in reason


def test_risk_change_reason_shows_short_hashes(rule, settings):
    locked = lock_plan(make_plan(rule, settings), LOCKED_AT)
    changed = copy.deepcopy(settings)
    changed["risk"]["daily_stop_pct"] = 9.0
    ok, reason = verify_plan(locked, rule, changed)
    old, new = risk_config_hash(settings), risk_config_hash(changed)
    assert not ok
    assert reason == f"Changed after the plan was locked: risk_config_sha256 {old[:12]} -> {new[:12]}."


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
    assert path.name == "demo_rule_a.json"
    assert load_plan(tmp_path, "demo_rule_a") == locked
    assert verify_plan(load_plan(tmp_path, "demo_rule_a"), rule, settings) == (True, None)
    assert load_plan(tmp_path, "unknown") is None


def test_unreadable_plan_file_raises(tmp_path):
    (tmp_path / "broken.json").write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_plan(tmp_path, "broken")


def test_lock_all_writes_one_valid_plan_per_rule(tmp_path, settings):
    locked = lock_all_plans(settings, tmp_path, locked_at=LOCKED_AT)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(f"{r.rule_id}.json" for r in all_rules())
    for rule, plan in zip(all_rules(), locked):
        assert verify_plan(load_plan(tmp_path, rule.rule_id), rule, settings) == (True, None)
        assert plan["locked_at"] == LOCKED_AT


def test_committed_plans_match_current_rules_and_settings(committed_plans_dir, settings):
    assert sorted(p.name for p in committed_plans_dir.glob("*.json")) == sorted(f"{r.rule_id}.json" for r in all_rules())
    for rule in all_rules():
        locked = load_plan(committed_plans_dir, rule.rule_id)
        assert verify_plan(locked, rule, settings) == (True, None), rule.rule_id
        assert json.loads((committed_plans_dir / f"{rule.rule_id}.json").read_text())["sha256"] == locked["sha256"]
