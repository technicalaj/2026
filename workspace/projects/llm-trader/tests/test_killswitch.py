import json
import shutil

import pytest
from conftest import ROOT

from llm_trader import cli
from llm_trader.config import Paths
from llm_trader.risk.killswitch import UNREADABLE, KillSwitch, KillSwitchError


@pytest.fixture
def switch(tmp_path):
    return KillSwitch(tmp_path / "out" / "killswitch.json")


@pytest.fixture
def paths(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "config", tmp_path / "config", ignore=shutil.ignore_patterns("settings.local.json"))
    monkeypatch.setattr(cli, "_refresh", lambda paths: None)
    return Paths(tmp_path)


def test_off_by_default(switch):
    assert switch.state() == {"on": False, "reason": None, "changed_at": None}
    assert switch.history() == []


def test_turning_on_needs_no_confirmation_and_persists(switch):
    switch.turn_on("Too many losses today.", now="2026-11-02T08:00:00Z")
    again = KillSwitch(switch.path)
    assert again.state() == {"on": True, "reason": "Too many losses today.", "changed_at": "2026-11-02T08:00:00Z"}


@pytest.mark.parametrize("confirm", [None, "", "yes", "Yes", "no", "YES please"])
def test_turning_off_needs_the_word_yes(switch, confirm):
    switch.turn_on("test")
    with pytest.raises(KillSwitchError, match="type YES"):
        switch.turn_off(confirm)
    assert switch.on


def test_turning_off_with_yes(switch):
    switch.turn_on("test")
    assert switch.turn_off(" YES ")["on"] is False
    assert [h["on"] for h in switch.history()] == [True, False]


def test_a_damaged_file_counts_as_on(switch):
    switch.path.parent.mkdir(parents=True)
    switch.path.write_text("{not json", encoding="utf-8")
    assert switch.state()["on"] is True and switch.state()["reason"] == UNREADABLE
    switch.turn_off("YES")
    assert json.loads(switch.path.read_text())["on"] is False


def test_cli_turns_it_on_and_clears_the_bridge_file(paths, capsys):
    paths.bridge_file.parent.mkdir(parents=True)
    paths.bridge_file.write_text(json.dumps({"signals": [{"id": "old"}]}), encoding="utf-8")
    assert cli.main(["killswitch", "on", "--reason", "Testing"], paths) == 0
    assert KillSwitch(paths.killswitch_file).state()["reason"] == "Testing"
    payload = json.loads(paths.bridge_file.read_text())
    assert payload["kill_switch"] is True and payload["signals"] == [] and payload["written"] == 0
    assert "Kill switch is ON" in capsys.readouterr().out


def test_cli_turning_off_needs_yes(paths, capsys):
    KillSwitch(paths.killswitch_file).turn_on("test")
    assert cli.main(["killswitch", "off"], paths) == 1
    assert "add --yes" in capsys.readouterr().err
    assert KillSwitch(paths.killswitch_file).on
    assert cli.main(["killswitch", "off", "--yes"], paths) == 0
    assert not KillSwitch(paths.killswitch_file).on
