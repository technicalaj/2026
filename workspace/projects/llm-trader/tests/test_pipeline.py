import dataclasses
import json
import shutil

import pandas as pd
import pytest
from conftest import ROOT

from llm_trader import bridge, cli, pipeline
from llm_trader.config import Paths
from llm_trader.data.symbols import DEMO_SPECS
from llm_trader.models import GateResult, Signal
from llm_trader.risk.killswitch import KillSwitch
from llm_trader.state import State

NOW = pd.Timestamp("2026-11-02 04:10", tz="UTC")
TOP = ["meta", "pipeline", "agents", "research", "checks", "risk", "approvals", "bridge", "report", "log"]
EXPECTED = {
    "control_planted": ("qualified", "research"),
    "sweep_fade": ("failed", "research"),
    "range_breakout": ("failed", "research"),
    "trend_pullback": ("insufficient", "research"),
    "tight_target": ("failed", "research"),
    "leaky": ("blocked", "blocked"),
}
SAMPLE = json.loads((ROOT / "tests" / "fixtures" / "sample_state.json").read_text(encoding="utf-8"))


def copy_project(root) -> Paths:
    shutil.copytree(ROOT / "config", root / "config", ignore=shutil.ignore_patterns("settings.local.json"))
    return Paths(root)


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    return copy_project(tmp_path_factory.mktemp("project"))


@pytest.fixture
def fresh(tmp_path):
    return copy_project(tmp_path)


@pytest.fixture(scope="module")
def run_demo(demo, evaluations):
    def go(paths: Paths, **kwargs) -> dict:
        return pipeline.run("demo", paths=paths, dataset=demo, evaluations=list(evaluations.values()), now=NOW, **kwargs)
    return go


@pytest.fixture(scope="module")
def state(project, run_demo):
    return run_demo(project)


def test_state_has_every_key_and_validates(state):
    assert list(state) == TOP
    State.model_validate(state)
    assert list(state["meta"]) == list(SAMPLE["meta"])
    assert [list(r) for r in state["research"]] == [list(SAMPLE["research"][0])] * len(state["research"])
    for section in ("pipeline", "agents", "checks"):
        assert {tuple(x) for x in state[section]} == {tuple(SAMPLE[section][0])}, section
    for key in ("risk", "approvals", "bridge", "report"):
        assert list(state[key]) == list(SAMPLE[key]), key
    assert list(state["risk"]["min_lot"][0]) == list(SAMPLE["risk"]["min_lot"][0])
    assert list(state["research"][0]["windows"]["holdout"]) == list(SAMPLE["research"][0]["windows"]["holdout"])


def test_expected_demo_outcomes(state):
    got = {r["rule_id"]: (r["gate"]["status"], r["stage"]) for r in state["research"]}
    assert got == EXPECTED
    control = next(r for r in state["research"] if r["control"])
    assert control["rule_id"] == "control_planted" and control["forward"]["note"] == "Self-test only: never forward tested."
    assert all(r["stage"] != "live_eligible" for r in state["research"])
    accuracy = {a["id"]: a["accuracy"] for a in state["agents"] if a["rule_id"]}
    assert accuracy["control_planted"] >= 0.8 > accuracy["tight_target"]


def test_meta_is_honest(state):
    meta = state["meta"]
    assert meta["app"] == "Superagentic" and meta["version"] == "0.1.0" and meta["generated_at"] == "2026-11-02T04:10:00Z"
    assert meta["data_mode"] == "demo" and meta["data_note"] == pipeline.DEMO_DATA_NOTE
    assert meta["llm_mode"] == "offline" and meta["llm_note"].endswith("use built-in templates.")
    assert meta["accuracy_bar"] == 0.8 and meta["eligible_for_money"] is False
    assert meta["eligible_note"] == "Nothing is eligible for money: demo data is never eligible."
    assert meta["kill_switch"] == {"on": False, "reason": None, "changed_at": None}
    assert meta["safe_mode"] == {"on": False, "reason": None}


def test_outputs_are_written(state, project):
    assert json.loads(project.state_file.read_text()) == state
    assert project.report_file.read_text() == state["report"]["markdown"]
    payload = json.loads(project.bridge_file.read_text())
    assert payload["format"] == bridge.FORMAT and payload["signals"] == [] and payload["note"] == bridge.DEMO_NOTE
    assert state["bridge"] == {"file": "out/bridge/signals.json", "written": 0, "signals": [], "note": bridge.DEMO_NOTE}
    assert json.loads(project.last_run_file.read_text())["data"] == "demo"


def test_superagentic_team_layout(state):
    agents = {a["id"]: a for a in state["agents"]}
    assert list(agents) == ["supervisor", "data", *EXPECTED, "validation", "risk", "monitor", "report",
                            "news_calendar", "research_scout", "mt5_bridge_ea"]
    assert [a["id"] for a in state["agents"] if a["status"] == "planned"] == ["news_calendar", "research_scout", "mt5_bridge_ea"]
    assert all(a["lane"] == "planned" for a in state["agents"] if a["status"] == "planned")
    assert [a["id"] for a in state["agents"] if a["control"]] == ["control_planted"]
    assert {a["id"]: a["gate_status"] for a in state["agents"] if a["rule_id"]} == {k: v[0] for k, v in EXPECTED.items()}
    assert agents["supervisor"]["kind"] == "code+llm" and "Never trades" in agents["supervisor"]["role"]
    assert agents["monitor"]["status"] == "idle"
    assert [p["id"] for p in state["pipeline"]] == ["data", "research", "validation", "risk", "bridge"]
    assert state["pipeline"][2] == {"id": "validation", "name": "Validation (80% gate)", "status": "warn",
                                    "summary": "1 of 6 passed the 80% gate (the self-test). 3 failed, 1 too few trades, 1 blocked."}


def test_checks_cover_every_stage(state):
    stages = {c["stage"] for c in state["checks"]}
    assert stages == {"data", "research", "validation", "risk", "monitor", "approvals", "bridge", "report"}
    names = {c["name"] for c in state["checks"]}
    for name in ("Data source is your broker's MT5 export", "No missing bars in market hours", "No duplicate bars",
                 "Candles are consistent", "No price spikes", "Spread recorded on every bar", "Second source matches (parity check)",
                 "Every signal has a stop-loss", "Rule fires a sensible amount", "Real costs are charged", "Test plan locked before testing",
                 "No future data used (leak check)", "Self-test: gate finds the planted pattern", "Passes the 80% gate",
                 "Minimum lot fits the risk limit", "One risk limit across all agents", "Correlated symbols count as one bet",
                 "Qualified agents are not one big bet", "One kill switch stops everything", "No change without your YES"):
        assert name in names, name


def test_risk_section(state):
    risk = state["risk"]
    assert risk["account"] == {"balance": 1000.0, "currency": "USD", "leverage": 30.0}
    assert risk["limits"] == {"risk_per_trade_pct": 1.0, "max_open_risk_pct": 2.0, "max_daily_loss_pct": 3.0,
                              "max_margin_use_pct": 50.0, "max_positions_per_group": 1}
    assert risk["usage"] == {"open_risk_pct": 0.0, "margin_use_pct": 0.0, "daily_loss_pct": 0.0, "open_positions": 0}
    assert [g["id"] for g in risk["groups"]] == ["USD", "RISK"]
    assert [m["symbol"] for m in risk["min_lot"]] == ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "US500", "BTCUSD", "CTRL-SYN"]
    assert risk["correlation"]["symbols"] == [m["symbol"] for m in risk["min_lot"]]
    assert len(risk["correlation"]["matrix"]) == 7


def test_report_is_an_honest_template(state):
    md = state["report"]["markdown"]
    assert state["report"]["title"] == "Daily report — 2026-11-02" and state["report"]["generated_by"] == "template"
    assert md.startswith("# Daily report — 2026-11-02")
    assert "**1 of 6** agents pass the 80% gate: only the planted-pattern self-test" in md
    assert "**0 of 5** trading-rule agents qualified" in md
    assert "A high win rate is not an edge.** Tight Target (trap demo) wins 79.5%" in md
    for r in state["research"]:
        assert f"| {r['name']}" in md
    assert "export your broker's data" in md


def test_no_private_paths_or_secrets(state, project):
    text = json.dumps(state)
    assert str(project.root) not in text and "/home/" not in text and "\\Users\\" not in text
    assert "ANTHROPIC_API_KEY=" not in text


def test_runs_are_repeatable(project, run_demo, state):
    again = run_demo(project)
    assert {k: v for k, v in again.items() if k != "log"} == {k: v for k, v in state.items() if k != "log"}


def test_settings_change_turns_on_safe_mode(fresh, run_demo):
    settings = json.loads(fresh.settings.read_text())
    settings["risk"]["risk_per_trade_pct"] = 2.0
    fresh.settings.write_text(json.dumps(settings, indent=2))
    state = run_demo(fresh)
    assert state["meta"]["safe_mode"]["on"] and "chg-001" in state["meta"]["safe_mode"]["reason"]
    [item] = state["approvals"]["pending"]
    assert item["diff"] == ["risk.risk_per_trade_pct: 1.0 → 2.0"]
    assert state["bridge"]["written"] == 0
    assert next(c for c in state["checks"] if c["stage"] == "approvals")["status"] == "warn"


def test_kill_switch_is_reflected_everywhere(fresh, run_demo):
    KillSwitch(fresh.killswitch_file).turn_on("Testing the switch.")
    state = run_demo(fresh)
    assert state["meta"]["kill_switch"]["on"] and state["meta"]["kill_switch"]["reason"] == "Testing the switch."
    assert json.loads(fresh.bridge_file.read_text())["kill_switch"] is True
    assert {a["id"]: a["status"] for a in state["agents"]}["monitor"] == "warn"
    assert state["pipeline"][3]["status"] == "warn" and "kill switch ON" in state["pipeline"][3]["summary"]


def write_mt5_folder(folder, demo, server="Example-Broker-Live", shift=pd.Timedelta(weeks=3)) -> None:
    folder.mkdir()
    meta = {"source": "mt5_export", "server": server, "server_tz": "nyclose", "times": "UTC", "timeframe": "M15", "symbols": {}}
    for name, symbol in (("XAUUSD.a", "XAUUSD"), ("EURUSD", "EURUSD")):
        df = demo[symbol][0]
        df = df[df.index > df.index[-1] - pd.DateOffset(months=12)]
        frame = pd.DataFrame({
            "time": (df.index + shift).as_unit("s").asi8, "open": df["open"].to_numpy(), "high": df["high"].to_numpy(),
            "low": df["low"].to_numpy(), "close": df["close"].to_numpy(), "tick_volume": df["volume"].astype(int).to_numpy(),
            "spread": df["spread"].astype(int).to_numpy(), "real_volume": 0,
        })
        file = f"{name}_M15.csv"
        frame.to_csv(folder / file, index=False)
        spec = DEMO_SPECS[symbol]
        meta["symbols"][name] = {"file": file, "rows": len(frame), "point": spec.point, "digits": spec.digits,
                                 "contract_size": spec.contract_size, "tick_size": spec.tick_size, "tick_value": spec.tick_value,
                                 "min_lot": spec.min_lot, "lot_step": spec.lot_step, "margin_per_min_lot": spec.margin_per_min_lot}
    (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_run_on_an_mt5_export_folder(fresh, demo):
    folder = fresh.root / "data" / "mt5"
    folder.parent.mkdir()
    write_mt5_folder(folder, demo)
    state = pipeline.run(folder, paths=fresh, now=NOW + pd.Timedelta(weeks=3))
    text = json.dumps(state)
    assert "Example-Broker-Live" not in text and str(fresh.root) not in text
    meta = state["meta"]
    assert meta["data_mode"] == "mt5" and "MT5 data: 2 symbol(s)" in meta["data_note"]
    assert meta["eligible_for_money"] is False and "forward test" in meta["eligible_note"]
    stages = {r["rule_id"]: (r["gate"]["status"], r["stage"]) for r in state["research"]}
    assert stages["control_planted"] == ("qualified", "research")
    assert stages["range_breakout"] == ("blocked", "blocked") and stages["leaky"] == ("blocked", "blocked")
    assert stages["sweep_fade"][1] == "research"
    source = {(c["subject"], c["status"]) for c in state["checks"] if c["name"] == "Data source is your broker's MT5 export"}
    assert ("EURUSD, XAUUSD", "pass") in source and ("CTRL-SYN", "info") in source
    assert any("Using XAUUSD.a as XAUUSD" in entry["msg"] for entry in state["log"])
    assert state["bridge"]["written"] == 0 and state["bridge"]["note"] == bridge.IDLE_NOTE
    assert json.loads(fresh.last_run_file.read_text())["data"] == str(folder)


def test_cli_run_prints_a_plain_summary(fresh, state, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(pipeline, "run", lambda data, use_llm, paths: calls.append((data, use_llm)) or state)
    assert cli.main(["run", "--demo"], fresh) == 0
    out = capsys.readouterr().out
    assert calls == [("demo", False)]
    assert "Self-test: planted pattern     qualified" in out and "Leaky Rule (demo)" in out
    assert "Nothing is eligible for money" in out and out.isascii()
    with pytest.raises(SystemExit):
        cli.main(["run", "--demo", "--data", "x"], fresh)


def as_broker_data(demo) -> dict:
    return {s: (df, {**prov, "source": "mt5_export"}) for s, (df, prov) in demo.items() if s != "CTRL-SYN"} | {"CTRL-SYN": demo["CTRL-SYN"]}


def with_qualified_sweep(evaluations) -> list:
    sweep = evaluations["sweep_fade"]
    passed = dataclasses.replace(sweep, gate=GateResult("qualified", list(sweep.gate.checks), ["Passed (test double)."]))
    return [passed if e.rule_id == "sweep_fade" else e for e in evaluations.values()]


def test_qualified_agent_on_broker_data_enters_the_forward_test(fresh, demo, evaluations):
    state = pipeline.run(fresh.root / "data", paths=fresh, dataset=as_broker_data(demo), evaluations=with_qualified_sweep(evaluations), now=NOW)
    sweep = next(r for r in state["research"] if r["rule_id"] == "sweep_fade")
    assert sweep["stage"] == "forward_test" and sweep["stage_note"] == "Forward test: 0 of 30-40 trades at minimum lot."
    assert {a["id"]: a["status"] for a in state["agents"]}["monitor"] == "ok"
    assert state["bridge"]["note"] == "1 agent(s) in a forward test, but none signalled on the latest bar."
    assert state["meta"]["eligible_for_money"] is False
    KillSwitch(fresh.killswitch_file).turn_on("pause")
    paused = pipeline.run(fresh.root / "data", paths=fresh, dataset=as_broker_data(demo), evaluations=with_qualified_sweep(evaluations), now=NOW)
    assert next(r for r in paused["research"] if r["rule_id"] == "sweep_fade")["stage"] == "shadow"


def test_bridge_candidates_take_only_signals_on_the_newest_bar(monkeypatch, demo, evaluations):
    newest = demo["EURUSD"][0].index[-1] + pd.Timedelta(minutes=15)

    class Stub:
        timeframe = "M15"

        def generate(self, df, symbol):
            return [Signal("sweep_fade", symbol, newest - pd.Timedelta(minutes=15), 1, 1.0, None, 16),
                    Signal("sweep_fade", symbol, newest, -1, 99999.0, None, 16)]

    monkeypatch.setattr(pipeline, "get_rule", lambda rule_id: Stub())
    sweep = evaluations["sweep_fade"]
    found = pipeline.bridge_candidates([sweep, evaluations["leaky"]], [{"stage": "forward_test"}, {"stage": "blocked"}], demo)
    assert [(c.signal.symbol, c.signal.side, c.plan_sha256) for c in found] == [("XAUUSD", -1, sweep.plan.sha256), ("EURUSD", -1, sweep.plan.sha256)]
    assert found[1].price == float(demo["EURUSD"][0]["close"].iloc[-1])


def test_data_source_names(fresh):
    settings = json.loads(fresh.settings.read_text())
    assert pipeline.resolve_source("demo", settings, fresh) == "demo"
    assert pipeline.resolve_source(None, settings, fresh) == "demo"
    assert pipeline.resolve_source("mt5", settings, fresh) == fresh.root / "data" / "mt5"
    assert pipeline.resolve_source("exports", settings, fresh) == pipeline.Path("exports")
    settings["data"]["mode"] = "mt5"
    assert pipeline.resolve_source(None, settings, fresh) == fresh.root / "data" / "mt5"


def test_cli_demo_writes_the_one_file_dashboard(fresh, state, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "run", lambda data, use_llm, paths: state)
    assert cli.main(["demo"], fresh) == 0
    assert "window.__STATE__" in fresh.dashboard_file.read_text(encoding="utf-8")
    assert "Open out/dashboard.html in any browser" in capsys.readouterr().out
