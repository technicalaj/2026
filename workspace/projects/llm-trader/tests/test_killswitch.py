import json
import shutil

import pytest
from conftest import ROOT

from llm_trader import cli
from llm_trader.config import Paths
from llm_trader.risk.killswitch import FLAG_FOUND, UNREADABLE, KillSwitch, KillSwitchError


@pytest.fixture
def switch(tmp_path):
    return KillSwitch(tmp_path / "out" / "killswitch.json", tmp_path / "out" / "bridge" / "kill.flag")


@pytest.fixture
def paths(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "config", tmp_path / "config", ignore=shutil.ignore_patterns("settings.local.json"))
    monkeypatch.setattr(cli, "_refresh", lambda paths: None)
    return Paths(tmp_path)


def test_off_by_default(switch):
    assert switch.state() == {"on": False, "reason": None, "changed_at": None}
    assert switch.history() == [] and not switch.flag_path.exists()


def test_turning_on_needs_no_confirmation_and_persists(switch):
    switch.turn_on("Too many losses today.", now="2026-11-02T08:00:00Z")
    again = KillSwitch(switch.path, switch.flag_path)
    assert again.state() == {"on": True, "reason": "Too many losses today.", "changed_at": "2026-11-02T08:00:00Z"}


@pytest.mark.parametrize("confirm", [None, "", "yes", "Yes", "no", "YES please"])
def test_turning_off_needs_the_word_yes(switch, confirm):
    switch.turn_on("test")
    with pytest.raises(KillSwitchError, match="type YES"):
        switch.turn_off(confirm)
    assert switch.on and switch.flag_path.exists()


def test_turning_off_with_yes(switch):
    switch.turn_on("test")
    assert switch.turn_off(" YES ")["on"] is False
    assert [h["on"] for h in switch.history()] == [True, False]


def test_kill_flag_exists_only_while_the_switch_is_on(switch):
    switch.turn_on("Drill.", now="2026-11-02T08:00:00Z")
    assert switch.flag_path.read_text() == "Kill switch ON since 2026-11-02T08:00:00Z: Drill.\n"
    switch.turn_off("YES")
    assert not switch.flag_path.exists()


def test_a_flag_set_outside_the_desk_counts_as_on(switch):
    switch.flag_path.parent.mkdir(parents=True)
    switch.flag_path.write_text("set by the chart button")
    assert switch.state() == {"on": True, "reason": FLAG_FOUND, "changed_at": None}
    with pytest.raises(KillSwitchError):
        switch.turn_off("no")
    switch.turn_off("YES")
    assert not switch.on and not switch.flag_path.exists()


def test_sync_flag_repairs_the_flag(switch):
    switch.turn_on("test")
    switch.flag_path.unlink()
    assert switch.sync_flag() is True and switch.flag_path.exists()
    assert KillSwitch(switch.path).sync_flag() is False


class FlagArrivesLate(KillSwitch):
    def state(self) -> dict:
        seen = super().state()
        self.flag_path.parent.mkdir(parents=True, exist_ok=True)
        self.flag_path.write_text("set by the Guardian a moment after the check")
        return seen


def test_syncing_never_deletes_a_flag_someone_else_just_set(switch):
    late = FlagArrivesLate(switch.path, switch.flag_path)
    assert late.sync_flag() is True and switch.flag_path.exists()
    assert KillSwitch(switch.path, switch.flag_path).on


def test_a_damaged_file_counts_as_on(switch):
    switch.path.parent.mkdir(parents=True)
    switch.path.write_text("{not json", encoding="utf-8")
    assert switch.state()["on"] is True and switch.state()["reason"] == UNREADABLE
    assert switch.sync_flag() is True and switch.flag_path.exists()
    switch.turn_off("YES")
    assert json.loads(switch.path.read_text())["on"] is False and not switch.flag_path.exists()


def test_cli_turns_it_on_sets_the_flag_and_empties_the_advisories(paths, capsys):
    paths.bridge_dir.mkdir(parents=True)
    (paths.bridge_dir / "signals.json").write_text(json.dumps({"signals": [{"id": "old"}]}), encoding="utf-8")
    assert cli.main(["killswitch", "on", "--reason", "Testing"], paths) == 0
    assert KillSwitch.at(paths).state()["reason"] == "Testing"
    assert paths.kill_flag.exists()
    payload = json.loads(paths.bridge_file.read_text())
    assert payload["kill"] is True and payload["advisories"] == []
    assert not (paths.bridge_dir / "signals.json").exists()
    assert "Kill switch is ON" in capsys.readouterr().out


def test_cli_turning_off_needs_yes(paths, capsys):
    KillSwitch.at(paths).turn_on("test")
    assert cli.main(["killswitch", "off"], paths) == 1
    assert "add --yes" in capsys.readouterr().err
    assert KillSwitch.at(paths).on and paths.kill_flag.exists()
    assert cli.main(["killswitch", "off", "--yes"], paths) == 0
    assert not KillSwitch.at(paths).on and not paths.kill_flag.exists()
