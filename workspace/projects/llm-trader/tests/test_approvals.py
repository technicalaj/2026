import json
import shutil

import pytest
from conftest import ROOT

from llm_trader import cli
from llm_trader.config import Paths, plan_hashes, settings_hash
from llm_trader.eval.plans import lock_plan, make_plan, save_plan
from llm_trader.risk.approvals import ApprovalError, Approvals, UnknownChange
from llm_trader.signals.registry import get_rule


@pytest.fixture
def paths(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "config", tmp_path / "config", ignore=shutil.ignore_patterns("settings.local.json"))
    monkeypatch.setattr(cli, "_refresh", lambda paths: None)
    return Paths(tmp_path)


def edit_settings(paths: Paths, change) -> None:
    settings = json.loads(paths.settings.read_text(encoding="utf-8"))
    change(settings)
    paths.settings.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def set_risk(value):
    return lambda s: s["risk"].update(risk_per_trade_pct=value)


def settings_value(paths: Paths, section: str, key: str):
    return json.loads(paths.settings.read_text(encoding="utf-8"))[section][key]


def test_shipped_approvals_match_the_shipped_settings_and_plans():
    record = json.loads((ROOT / "config" / "approved.json").read_text(encoding="utf-8"))
    settings = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
    assert record["settings_sha256"] == settings_hash(settings)
    assert record["plans"] == plan_hashes(ROOT / "config" / "plans")
    assert set(record) == {"approved_at", "note", "settings_sha256", "plans", "settings"}


def test_unchanged_files_mean_no_safe_mode(paths):
    status = Approvals(paths).scan()
    assert status.pending == [] and not status.safe_mode and status.reason is None


def test_settings_change_waits_for_yes_with_a_readable_diff(paths):
    edit_settings(paths, set_risk(1.5))
    status = Approvals(paths).scan()
    assert status.safe_mode and "chg-001" in status.reason and "Nothing is sent to the bridge" in status.reason
    [item] = status.view()["pending"]
    assert set(item) == {"id", "created_at", "kind", "summary", "diff"}
    assert item["kind"] == "settings"
    assert item["diff"] == ["risk.risk_per_trade_pct: 1.0 → 1.5"]
    assert item["summary"] == "risk_per_trade_pct 1.0 → 1.5"
    assert [p["id"] for p in Approvals(paths).scan().pending] == ["chg-001"]


@pytest.mark.parametrize("confirm", [None, "", "yes", "ok"])
def test_approving_needs_the_word_yes(paths, confirm):
    edit_settings(paths, set_risk(1.5))
    approvals = Approvals(paths)
    approvals.scan()
    with pytest.raises(ApprovalError, match="type YES"):
        approvals.approve("chg-001", confirm)
    assert approvals.scan().safe_mode


def test_approving_with_yes_ends_safe_mode_and_is_remembered(paths):
    edit_settings(paths, set_risk(1.5))
    approvals = Approvals(paths)
    approvals.scan()
    entry = approvals.approve("chg-001", "YES")
    assert entry["decision"] == "approved" and entry["summary"] == "risk_per_trade_pct 1.0 → 1.5"
    status = approvals.scan()
    assert not status.safe_mode and status.pending == []
    assert status.view()["history"][0]["id"] == "chg-001"
    record = json.loads(paths.approved.read_text())
    assert record["settings"]["risk"]["risk_per_trade_pct"] == 1.5


def test_rejecting_puts_the_approved_settings_back(paths):
    edit_settings(paths, set_risk(5.0))
    approvals = Approvals(paths)
    approvals.scan()
    entry = approvals.reject("chg-001")
    assert entry["decision"] == "rejected" and "put back to the approved version" in entry["summary"]
    assert settings_value(paths, "risk", "risk_per_trade_pct") == 1.0
    assert not approvals.scan().safe_mode


def test_putting_the_file_back_by_hand_withdraws_the_change(paths):
    edit_settings(paths, set_risk(1.5))
    approvals = Approvals(paths)
    approvals.scan()
    edit_settings(paths, set_risk(1.0))
    status = approvals.scan()
    assert not status.safe_mode and status.pending == []
    assert status.history[-1]["decision"] == "withdrawn"


def test_account_server_and_llm_changes_need_no_yes(paths):
    def change(s):
        s["account"]["balance"] = 250.0
        s["server"]["port"] = 9000
        s["llm"]["effort"] = "high"
    edit_settings(paths, change)
    assert not Approvals(paths).scan().safe_mode


def test_gate_change_says_the_plans_must_be_relocked(paths):
    edit_settings(paths, lambda s: s["gate"].update(accuracy_bar=0.7))
    [item] = Approvals(paths).scan().pending
    assert item["diff"] == ["gate.accuracy_bar: 0.8 → 0.7"]
    assert "re-lock them after approving: python -m llm_trader lock --all --yes" in item["summary"]


def test_correlation_group_change_names_the_group(paths):
    edit_settings(paths, lambda s: s["correlation_groups"][0]["members"].pop("XAUUSD"))
    [item] = Approvals(paths).scan().pending
    assert item["diff"] == ["correlation_groups[USD].members.XAUUSD: -1 → (removed)"]


def test_hand_edited_plan_waits_for_yes_and_can_be_rejected(paths):
    approvals = Approvals(paths)
    approvals.scan()
    plan_file = paths.plans_dir / "trend_pullback.json"
    original = plan_file.read_text()
    plan = json.loads(original)
    plan["params"]["rsi_low"] = 30
    plan_file.write_text(json.dumps(plan, indent=2))
    [item] = approvals.scan().pending
    assert item["kind"] == "plan" and "edited by hand" in item["summary"]
    assert item["diff"] == ["params.rsi_low: 25 → 30"]
    assert "put back" in approvals.reject(item["id"])["summary"]
    assert json.loads(plan_file.read_text()) == json.loads(original)
    assert not approvals.scan().safe_mode


def test_change_edited_again_cannot_be_approved_unseen(paths):
    edit_settings(paths, set_risk(1.5))
    approvals = Approvals(paths)
    approvals.scan()
    edit_settings(paths, set_risk(3.0))
    with pytest.raises(ApprovalError, match="edited again"):
        approvals.approve("chg-001", "YES")
    [item] = approvals.scan().pending
    assert item["id"] == "chg-001" and item["diff"] == ["risk.risk_per_trade_pct: 1.0 → 3.0"]


def test_rejected_change_without_a_copy_keeps_safe_mode(paths):
    record = json.loads(paths.approved.read_text())
    record.pop("settings")
    paths.approved.write_text(json.dumps(record))
    edit_settings(paths, set_risk(1.5))
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


def test_unknown_change_id(paths):
    with pytest.raises(UnknownChange):
        Approvals(paths).approve("chg-404", "YES")
    with pytest.raises(UnknownChange):
        Approvals(paths).reject("chg-404")


def test_relocking_with_yes_records_the_approval(paths):
    rule = get_rule("trend_pullback")
    rule.params["rsi_low"] = 30
    plan = lock_plan(make_plan(rule, json.loads(paths.settings.read_text())))
    save_plan(paths.plans_dir, plan)
    approvals = Approvals(paths)
    entry = approvals.record_lock("trend_pullback", plan)
    assert entry["decision"] == "approved" and "Re-locked the test plan for Trend Pullback (demo)" in entry["summary"]
    assert not approvals.scan().safe_mode


def test_cli_lock_needs_yes_and_no_pending_settings(paths, capsys):
    assert cli.main(["lock", "sweep_fade"], paths) == 1
    assert "Add --yes" in capsys.readouterr().err
    assert cli.main(["lock", "--all", "sweep_fade", "--yes"], paths) == 2
    assert cli.main(["lock", "no_such_rule", "--yes"], paths) == 2
    edit_settings(paths, set_risk(1.5))
    assert cli.main(["lock", "--all", "--yes"], paths) == 1
    assert "waiting for your YES" in capsys.readouterr().err


def test_cli_lock_relocks_and_keeps_approvals_clean(paths, capsys):
    before = json.loads((paths.plans_dir / "sweep_fade.json").read_text())
    assert cli.main(["lock", "sweep_fade", "--yes"], paths) == 0
    after = json.loads((paths.plans_dir / "sweep_fade.json").read_text())
    assert after["sha256"] == before["sha256"]
    assert "Locked sweep_fade" in capsys.readouterr().out
    assert not Approvals(paths).scan().safe_mode


def test_cli_approve_needs_yes_and_reject_needs_none(paths, capsys):
    edit_settings(paths, set_risk(1.5))
    Approvals(paths).scan()
    assert cli.main(["approve", "chg-001"], paths) == 1
    assert "add --yes" in capsys.readouterr().err
    assert cli.main(["approve", "chg-001", "--yes"], paths) == 0
    edit_settings(paths, set_risk(2.0))
    Approvals(paths).scan()
    assert cli.main(["reject", "chg-002"], paths) == 0
    assert settings_value(paths, "risk", "risk_per_trade_pct") == 1.5
    assert cli.main(["approve", "chg-999", "--yes"], paths) == 1
    assert "No pending change called 'chg-999'" in capsys.readouterr().err
