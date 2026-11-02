import json

import pytest
from conftest import ROOT
from project_copy import copy_project

from llm_trader import cli
from llm_trader.config import Paths, load_settings, plan_hashes
from llm_trader.eval.plans import load_plan, lock_plan, make_plan, save_plan, verify_plan
from llm_trader.risk.approvals import BASELINE_SUMMARY, ApprovalError, Approvals, UnknownChange
from llm_trader.signals.registry import get_rule

RELOCK = "re-lock them after approving: python -m llm_trader lock --all --yes"


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_refresh", lambda paths: None)
    return copy_project(tmp_path)


def edit_settings(paths: Paths, change) -> None:
    settings = json.loads(paths.settings.read_text(encoding="utf-8"))
    change(settings)
    paths.settings.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def set_risk(value):
    return lambda s: s["risk"].update(risk_per_trade_pct=value)


def settings_value(paths: Paths, section: str, key: str):
    return json.loads(paths.settings.read_text(encoding="utf-8"))[section][key]


def first_number(params: dict) -> str:
    return next(k for k, v in sorted(params.items()) if isinstance(v, (int, float)) and not isinstance(v, bool))


def ignored(path: str) -> bool:
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    return path in {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def test_a_yes_and_the_trial_log_never_travel_with_the_code():
    assert ignored("config/approved.json"), "a committed approval would let a pulled change arrive pre-approved"
    assert ignored("config/trials.json"), "a committed trial log could lower the number of tries after a pull"


def test_a_fresh_copy_asks_for_the_starting_point(tmp_path):
    paths = copy_project(tmp_path, baseline=False)
    status = Approvals(paths).scan()
    [item] = status.view()["pending"]
    assert item["id"] == "chg-001" and item["kind"] == "baseline" and item["summary"] == BASELINE_SUMMARY
    assert len(item["diff"]) == 1 + len(plan_hashes(paths.plans_dir))
    assert status.safe_mode and status.view()["history"] == []
    assert status.reason == "The starting settings and locked test plans wait for your YES (chg-001). Nothing is sent to the bridge until then."


def test_unchanged_files_mean_no_safe_mode(paths):
    status = Approvals(paths).scan()
    assert status.pending == [] and not status.safe_mode and status.reason is None


def test_risk_change_waits_for_yes_with_a_readable_diff(paths):
    edit_settings(paths, set_risk(0.75))
    status = Approvals(paths).scan()
    assert status.safe_mode and "chg-001" in status.reason and "Nothing is sent to the bridge" in status.reason
    [item] = status.view()["pending"]
    assert set(item) == {"id", "created_at", "kind", "summary", "diff"}
    assert item["kind"] == "settings" and item["diff"] == ["risk.risk_per_trade_pct: 0.5 → 0.75"]
    assert item["summary"] == f"risk_per_trade_pct 0.5 → 0.75. Every test plan includes this, so {RELOCK}"
    assert [p["id"] for p in Approvals(paths).scan().pending] == ["chg-001"]


@pytest.mark.parametrize("confirm", [None, "", "yes", "ok"])
def test_approving_needs_the_word_yes(paths, confirm):
    edit_settings(paths, set_risk(0.75))
    approvals = Approvals(paths)
    approvals.scan()
    with pytest.raises(ApprovalError, match="type YES"):
        approvals.approve("chg-001", confirm)
    assert approvals.scan().safe_mode


def test_approving_with_yes_ends_safe_mode_and_is_remembered(paths):
    edit_settings(paths, set_risk(0.75))
    approvals = Approvals(paths)
    approvals.scan()
    entry = approvals.approve("chg-001", "YES")
    assert entry["decision"] == "approved" and entry["summary"].startswith("risk_per_trade_pct 0.5 → 0.75")
    status = approvals.scan()
    assert not status.safe_mode and status.pending == []
    assert status.view()["history"][0]["id"] == "chg-001"
    assert json.loads(paths.approved.read_text())["settings"]["risk"]["risk_per_trade_pct"] == 0.75


def test_rejecting_puts_the_approved_settings_back(paths):
    edit_settings(paths, set_risk(1.0))
    approvals = Approvals(paths)
    approvals.scan()
    entry = approvals.reject("chg-001")
    assert entry["decision"] == "rejected" and "put back to the approved version" in entry["summary"]
    assert settings_value(paths, "risk", "risk_per_trade_pct") == 0.5
    assert not approvals.scan().safe_mode


def test_putting_the_file_back_by_hand_withdraws_the_change(paths):
    edit_settings(paths, set_risk(0.75))
    approvals = Approvals(paths)
    approvals.scan()
    edit_settings(paths, set_risk(0.5))
    status = approvals.scan()
    assert not status.safe_mode and status.pending == []
    assert status.history[-1]["decision"] == "withdrawn"


def test_account_server_and_llm_changes_need_no_yes(paths):
    def change(s):
        s["account"]["balance"] = 250.0
        s["server"]["port"] = 9000
        s["llm"]["cost_cap_usd"] = 0.25
    edit_settings(paths, change)
    assert not Approvals(paths).scan().safe_mode


def test_context_agent_change_needs_yes_but_no_relock(paths):
    edit_settings(paths, lambda s: s["context"]["event_tagger"].update(samples=5))
    [item] = Approvals(paths).scan().pending
    assert item["diff"] == ["context.event_tagger.samples: 3 → 5"] and RELOCK not in item["summary"]


def test_gate_change_says_the_plans_must_be_relocked(paths):
    edit_settings(paths, lambda s: s["gate"].update(accuracy_bar=0.7))
    [item] = Approvals(paths).scan().pending
    assert item["diff"] == ["gate.accuracy_bar: 0.8 → 0.7"] and RELOCK in item["summary"]


def test_cluster_change_names_the_cluster(paths):
    edit_settings(paths, lambda s: s["correlation_groups"][0]["members"].pop("XAUUSD"))
    [item] = Approvals(paths).scan().pending
    assert item["diff"] == ["correlation_groups[USD].members.XAUUSD: -1 → (removed)"]


def test_hand_edited_plan_waits_for_yes_and_can_be_rejected(paths):
    approvals = Approvals(paths)
    approvals.scan()
    plan_file = paths.plans_dir / "trend_pullback.json"
    original = plan_file.read_text()
    plan = json.loads(original)
    key = first_number(plan["params"])
    old = plan["params"][key]
    plan["params"][key] = old + 1
    plan_file.write_text(json.dumps(plan, indent=2))
    [item] = approvals.scan().pending
    assert item["kind"] == "plan" and "edited by hand" in item["summary"]
    assert item["diff"] == [f"params.{key}: {old} → {old + 1}"]
    assert "put back" in approvals.reject(item["id"])["summary"]
    assert json.loads(plan_file.read_text()) == json.loads(original)
    assert not approvals.scan().safe_mode


def test_removed_plan_is_listed_and_not_mistaken_for_a_rejection(paths):
    approvals = Approvals(paths)
    approvals.scan()
    (paths.plans_dir / "trend_pullback.json").unlink()
    status = approvals.scan()
    [item] = status.pending
    assert item["kind"] == "plan" and item["summary"] == "Test plan for Trend Pullback (demo) was removed"
    assert "you rejected" not in status.reason
    approvals.reject(item["id"])
    assert (paths.plans_dir / "trend_pullback.json").exists() and not approvals.scan().safe_mode


def test_change_edited_again_cannot_be_approved_unseen(paths):
    edit_settings(paths, set_risk(0.75))
    approvals = Approvals(paths)
    approvals.scan()
    edit_settings(paths, set_risk(0.9))
    with pytest.raises(ApprovalError, match="edited again"):
        approvals.approve("chg-001", "YES")
    [item] = approvals.scan().pending
    assert item["id"] == "chg-001" and item["diff"] == ["risk.risk_per_trade_pct: 0.5 → 0.9"]


def test_rejected_change_without_a_copy_keeps_safe_mode(paths):
    record = json.loads(paths.approved.read_text())
    record.pop("settings")
    paths.approved.write_text(json.dumps(record))
    edit_settings(paths, set_risk(0.75))
    approvals = Approvals(paths)
    [item] = approvals.scan().pending
    assert "no approved copy" in item["summary"]
    assert "still in the files" in approvals.reject(item["id"])["summary"]
    status = approvals.scan()
    assert status.safe_mode and status.pending == [] and "you rejected" in status.reason


def test_missing_approvals_file_asks_for_a_starting_point(paths):
    paths.approved.unlink()
    approvals = Approvals(paths)
    [item] = approvals.scan().pending
    assert item["kind"] == "baseline" and approvals.scan().safe_mode
    approvals.approve(item["id"], "YES")
    assert not approvals.scan().safe_mode
    assert json.loads(paths.approved.read_text())["plans"] == plan_hashes(paths.plans_dir)


def test_rejecting_the_starting_point_keeps_it_approvable(paths):
    paths.approved.unlink()
    approvals = Approvals(paths)
    [item] = approvals.scan().pending
    entry = approvals.reject(item["id"])
    assert entry["decision"] == "rejected" and "still waits for your YES" in entry["summary"]
    status = approvals.scan()
    assert status.safe_mode and [p["id"] for p in status.pending] == [item["id"]] and "you rejected" not in status.reason
    approvals.approve(item["id"], "YES")
    assert not approvals.scan().safe_mode


def test_unknown_change_id(paths):
    with pytest.raises(UnknownChange):
        Approvals(paths).approve("chg-404", "YES")
    with pytest.raises(UnknownChange):
        Approvals(paths).reject("chg-404")


def test_relocking_with_yes_records_the_approval(paths):
    rule = get_rule("trend_pullback")
    key = first_number(rule.params)
    rule.params[key] += 1
    plan = lock_plan(make_plan(rule, load_settings(paths)))
    save_plan(paths.plans_dir, plan)
    approvals = Approvals(paths)
    entry = approvals.record_lock("trend_pullback", plan)
    assert entry["decision"] == "approved" and "Re-locked the test plan for Trend Pullback (demo)" in entry["summary"]
    assert not approvals.scan().safe_mode


def test_cli_lock_needs_yes_and_no_pending_settings(paths, capsys):
    assert cli.main(["lock", "trend_pullback"], paths) == 1
    assert "Add --yes" in capsys.readouterr().err
    assert cli.main(["lock", "--all", "trend_pullback", "--yes"], paths) == 2
    assert cli.main(["lock", "no_such_rule", "--yes"], paths) == 2
    edit_settings(paths, set_risk(0.75))
    assert cli.main(["lock", "--all", "--yes"], paths) == 1
    assert "waiting for your YES" in capsys.readouterr().err


def test_cli_lock_asks_for_the_starting_point_first(paths, capsys):
    paths.approved.unlink()
    assert cli.main(["lock", "--all", "--yes"], paths) == 1
    assert "Approve the starting point first" in capsys.readouterr().err
    assert not paths.approved.exists()


def test_cli_lock_all_produces_valid_plans_and_clean_approvals(paths, capsys):
    assert cli.main(["lock", "--all", "--yes"], paths) == 0
    out = capsys.readouterr().out
    settings = load_settings(paths)
    for rule_id in ("control_planted", "demo_rule_a", "demo_rule_b", "trend_pullback", "tight_target", "leaky"):
        assert verify_plan(load_plan(paths.plans_dir, rule_id), get_rule(rule_id), settings) == (True, None)
        assert f"Locked {rule_id}:" in out
    assert not Approvals(paths).scan().safe_mode


def test_cli_approve_needs_yes_and_reject_needs_none(paths, capsys):
    edit_settings(paths, set_risk(0.75))
    Approvals(paths).scan()
    assert cli.main(["approve", "chg-001"], paths) == 1
    assert "add --yes" in capsys.readouterr().err
    assert cli.main(["approve", "chg-001", "--yes"], paths) == 0
    edit_settings(paths, set_risk(0.9))
    Approvals(paths).scan()
    assert cli.main(["reject", "chg-002"], paths) == 0
    assert settings_value(paths, "risk", "risk_per_trade_pct") == 0.75
    assert cli.main(["approve", "chg-999", "--yes"], paths) == 1
    assert "No pending change called 'chg-999'" in capsys.readouterr().err
