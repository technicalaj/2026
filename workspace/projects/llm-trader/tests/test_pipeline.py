import dataclasses
import json

import pandas as pd
import pytest
from conftest import ROOT
from project_copy import copy_project

from llm_trader import bridge, cli, pipeline
from llm_trader.data.symbols import DEMO_SPECS
from llm_trader.models import GateResult
from llm_trader.report import template_report
from llm_trader.risk.killswitch import FLAG_FOUND, KillSwitch
from llm_trader.state import State

NOW = pd.Timestamp("2026-11-02 04:10", tz="UTC")
TOP = ["meta", "picks_today", "pipeline", "agents", "research", "self_tests", "context", "checks", "risk", "power", "approvals",
       "bridge", "report", "log"]
EXPECTED = {
    "control_planted": ("qualified", "research"),
    "demo_rule_a": ("failed", "research"),
    "demo_rule_b": ("failed", "research"),
    "trend_pullback": ("insufficient", "research"),
    "tight_target": ("failed", "research"),
    "leaky": ("blocked", "blocked"),
}
SELF_TESTS = ["control_planted", "tight_target", "leaky", "no_edge_symbols", "no_order_code", "event_tagger_disagrees"]
EXTRA_KEYS = ["expectancy_ci", "expectancy_1_5x_costs", "expectancy_2x_costs", "long", "short", "terciles", "stop_target_ratio",
              "holm_threshold", "trial_count"]
LIMITS = {
    "risk_per_trade_pct": 0.5, "risk_per_trade_cap_pct": 1.0, "max_open_risk_pct": 1.5, "max_cluster_risk_pct": 1.0,
    "max_margin_use_pct": 30.0, "daily_stop_pct": 2.0, "weekly_stop_pct": 4.0, "overall_kill_pct": 6.0, "max_open_positions": 2,
    "max_entries_per_day": 4, "min_minutes_between_entries_per_symbol": 240, "spread_skip_multiple": 2.0, "pause_after_full_stops": 3,
    "blackouts": {"news_minutes": 15, "major_news_minutes": 30, "rollover": "16:45-17:15 America/New_York", "friday_cutoff_utc": "20:00",
                  "calendar_max_age_hours": 24.0},
}
TRADED = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "US500", "BTCUSD"]
SAMPLE = json.loads((ROOT / "tests" / "fixtures" / "sample_state.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    return copy_project(tmp_path_factory.mktemp("project"))


@pytest.fixture
def fresh(tmp_path):
    return copy_project(tmp_path)


@pytest.fixture(scope="module")
def run_demo(demo, evaluations):
    def go(paths, **kwargs) -> dict:
        return pipeline.run("demo", paths=paths, dataset=demo, evaluations=list(evaluations.values()), now=NOW, **kwargs)
    return go


@pytest.fixture(scope="module")
def state(project, run_demo):
    return run_demo(project)


def by_id(rows, key="id") -> dict:
    return {row[key]: row for row in rows}


def test_state_follows_the_contract(state):
    assert list(state) == TOP
    State.model_validate(state)
    meta = state["meta"]
    assert {"banners", "trial_count", "prior_trials"} <= set(meta)
    assert set(state["picks_today"]) == {"picks", "reason"}
    for r in state["research"]:
        assert {"kind", "self_test", "expected", "self_test_ok"} <= set(r)
        for name in ("holdout", "recent"):
            window = r["windows"][name]
            assert list(window["extra"]) == EXTRA_KEYS and "losses" in window and "random" in window
            assert set(window["extra"]["long"]) == {"trades", "win_rate", "expectancy_r"}
        assert "losses" in r["windows"]["development"] and "extra" not in r["windows"]["development"]
    assert all(set(t) == {"id", "name", "expected", "actual", "ok", "detail"} for t in state["self_tests"])
    assert set(state["context"]) == {"event_tagger", "regime"}
    assert set(state["context"]["event_tagger"]) == {"stage", "measured", "samples", "model", "note", "last"}
    assert set(state["bridge"]) == {"file", "heartbeat", "kill_flag", "advisories", "note"}
    assert list(state["risk"]) == ["account", "limits", "usage", "groups", "min_lot", "min_lot_balances", "correlation"]
    assert all(list(p) == ["edge_r", "trades", "pass_rate"] for p in state["power"])


def test_gate_power_table(state):
    table = {(p["edge_r"], p["trades"]): p["pass_rate"] for p in state["power"]}
    assert sorted({e for e, _ in table}) == [0.02, 0.05, 0.1, 0.2] and sorted({n for _, n in table}) == [30, 100, 300, 600]
    assert table[(0.1, 30)] < 0.25 and table[(0.2, 600)] > 0.95
    assert table[(0.2, 30)] < table[(0.2, 100)] < table[(0.2, 300)]


def test_state_matches_the_ui_fixture_keys(state):
    assert set(state) == set(SAMPLE)
    assert set(state["meta"]) == set(SAMPLE["meta"])
    assert set(state["research"][0]) == set(SAMPLE["research"][0])
    assert set(state["research"][0]["windows"]["holdout"]) == set(SAMPLE["research"][0]["windows"]["holdout"])
    for key in ("risk", "bridge", "context", "picks_today"):
        assert set(state[key]) == set(SAMPLE[key]), key


def test_expected_demo_outcomes(state):
    research = by_id(state["research"], "rule_id")
    assert {k: (r["gate"]["status"], r["stage"]) for k, r in research.items()} == EXPECTED
    assert {k for k, r in research.items() if r["kind"] == "self_test"} == {"control_planted", "tight_target", "leaky"}
    assert all(r["self_test_ok"] is True for r in research.values() if r["self_test"])
    assert all(r["self_test_ok"] is None and r["expected"] is None for r in research.values() if not r["self_test"])
    assert research["control_planted"]["forward"]["note"] == "Self-test only: never forward tested."
    assert research["tight_target"]["windows"]["holdout"]["extra"]["stop_target_ratio"] == pytest.approx(5.0, abs=0.05)
    assert all(r["stage"] not in ("forward_test", "live_eligible") for r in research.values())


def test_self_tests_panel(state):
    tests = by_id(state["self_tests"])
    assert list(tests) == SELF_TESTS
    assert all(t["ok"] is True for t in tests.values())
    assert tests["control_planted"]["actual"] == "qualified" and tests["leaky"]["actual"] == "blocked"
    assert tests["no_edge_symbols"]["actual"] == "0 of 5 agents qualified"
    assert tests["no_order_code"]["actual"] == "none found" and "Scanned 0 " not in tests["no_order_code"]["detail"]
    assert tests["control_planted"]["name"] == "Planted pattern: must qualify"
    assert tests["event_tagger_disagrees"]["name"].endswith("(self-test, not accuracy)")


def test_meta_is_honest(state):
    meta = state["meta"]
    assert meta["generated_at"] == "2026-11-02T04:10:00Z" and meta["data_mode"] == "demo"
    assert meta["banners"] == ["SYNTHETIC DATA", "AI OFFLINE", "NO TRADING"]
    assert meta["trial_count"] >= 6 and meta["prior_trials"] == 0
    assert meta["data_note"] == pipeline.DEMO_DATA_NOTE and meta["eligible_for_money"] is False
    assert meta["llm_mode"] == "offline" and meta["llm_note"].endswith("use built-in templates.")
    assert meta["kill_switch"] == {"on": False, "reason": None, "changed_at": None}
    assert meta["safe_mode"] == {"on": False, "reason": None}
    assert state["picks_today"] == {"picks": [], "reason": pipeline.DEMO_PICKS}


def test_outputs_are_written(state, project):
    assert json.loads(project.state_file.read_text()) == state
    assert project.report_file.read_text() == state["report"]["markdown"]
    assert json.loads(project.bridge_file.read_text()) == {"heartbeat": "2026-11-02T04:10:00Z", "kill": False, "advisories": []}
    assert state["bridge"] == {"file": "out/bridge/advisories.json", "heartbeat": "2026-11-02T04:10:00Z", "kill_flag": False,
                               "advisories": [], "note": bridge.DEMO_NOTE}
    assert not (project.bridge_dir / "signals.json").exists() and not project.kill_flag.exists()
    assert json.loads(project.last_run_file.read_text())["data"] == "demo"


def test_superagentic_team_layout(state):
    agents = by_id(state["agents"])
    assert list(agents) == ["supervisor", "data", *EXPECTED, "event_tagger", "regime", "validation", "risk", "monitor", "report",
                            "guardian_ea", "macro_bias", "trade_vetter", "crypto_funding", "research_assistant"]
    assert {a["lane"] for a in agents.values()} == {"supervisor", "data", "research", "context", "validation", "risk", "monitor", "report", "planned"}
    assert [a["id"] for a in agents.values() if a["lane"] == "context"] == ["event_tagger", "regime"]
    assert agents["event_tagger"]["kind"] == "llm" and agents["regime"]["kind"] == "code"
    assert all(a["status"] == "planned" for a in agents.values() if a["lane"] == "planned")
    assert [a["id"] for a in agents.values() if a["control"]] == ["control_planted"]
    assert {a["id"]: a["gate_status"] for a in agents.values() if a["rule_id"]} == {k: v[0] for k, v in EXPECTED.items()}
    assert agents["tight_target"]["status"] == "ok" and agents["tight_target"]["role"].startswith("Self-test, must fail")
    assert agents["demo_rule_a"]["status"] == "fail" and "Never trades" not in agents["demo_rule_a"]["role"]
    assert [p["id"] for p in state["pipeline"]] == ["data", "research", "validation", "risk", "bridge"]
    assert state["pipeline"][2]["summary"].startswith("0 of 3 rule agents passed the 80% gate.")


def test_context_agents(state):
    tagger, regimes = state["context"]["event_tagger"], state["context"]["regime"]
    assert (tagger["stage"], tagger["measured"], tagger["samples"]) == ("shadow", "UNMEASURED", 3)
    assert tagger["model"] == "claude-haiku-5-5 (offline mock)" and tagger["note"] == "Self-test with seeded mock answers — not accuracy."
    assert [row["symbol"] for row in tagger["last"]] == TRADED
    assert all(len(row["verdicts"]) == 3 and "(synthetic)" in row["event"] for row in tagger["last"])
    assert any(row["agreement"] == "2 of 3" for row in tagger["last"])
    assert all(not row["pause"] for row in tagger["last"] if row["agreement"] != "3 of 3")
    assert [r["symbol"] for r in regimes] == TRADED
    assert all(r["vol_tercile"] in (1, 2, 3) and r["trend"] in ("up", "down", "flat") for r in regimes)


def test_checks_cover_every_stage(state):
    assert {c["stage"] for c in state["checks"]} == {"data", "research", "validation", "risk", "monitor", "approvals", "bridge", "report"}
    names = {c["name"] for c in state["checks"]}
    for name in ("Data source is your broker's MT5 export", "No missing bars in market hours", "Second source matches (parity check)",
                 "Every signal has a stop-loss", "Test plan locked before testing", "No future data used (leak check)",
                 "Self-test: must qualify", "Self-test: must fail", "Self-test: must be blocked", "Passes the 80% gate",
                 "Minimum lot fits the risk cap and margin limit", "One risk limit across all agents", "Correlated symbols count as one bet",
                 "One kill switch stops every agent", "Loss stops not reached", "Shadow agents affect nothing",
                 "No change without your YES", "Bridge carries only pauses from qualified agents"):
        assert name in names, name
    self_checks = [c for c in state["checks"] if c["name"].startswith("Self-test:")]
    assert all(c["status"] == "pass" for c in self_checks)


def test_risk_section(state):
    risk = state["risk"]
    assert risk["account"] == {"balance": 1000.0, "currency": "USD", "leverage": 30.0, "source": "placeholder"}
    assert risk["limits"] == LIMITS
    assert risk["usage"] == {"open_risk_pct": 0.0, "margin_use_pct": 0.0, "daily_loss_pct": 0.0, "open_positions": 0}
    assert [(g["id"], g["limit_pct"]) for g in risk["groups"]] == [("USD", 1.0), ("RISK_ON", 1.0)]
    assert [m["symbol"] for m in risk["min_lot"]] == TRADED
    assert [b["balance"] for b in risk["min_lot_balances"]] == [500.0, 2000.0, 10000.0, 25000.0]
    assert all([row["symbol"] for row in b["rows"]] == TRADED for b in risk["min_lot_balances"])
    assert risk["correlation"]["symbols"] == [*TRADED, "CTRL-SYN"]


def test_log_has_supervisor_decisions_and_would_be_alerts(state):
    messages = [e["msg"] for e in state["log"]]
    assert sum(m.startswith("Decision: ") for m in messages) == len(EXPECTED)
    assert any(m.startswith("New entries from agents: blocked (no agent has qualified yet)") for m in messages)
    assert not any("not_qualified" in m or " -> " in m for m in messages)
    alerts = [e for e in state["log"] if e["level"] == "alert"]
    assert [a["agent_id"] for a in alerts] == ["report"] and alerts[0]["msg"].startswith("Would-be phone alert: Morning report ready")
    assert any(e["agent_id"] == "event_tagger" for e in state["log"]) and any(e["agent_id"] == "regime" for e in state["log"])


def test_report_is_an_honest_template(state):
    md = state["report"]["markdown"]
    assert state["report"]["title"] == "Daily report — 2026-11-02" and state["report"]["generated_by"] == "template"
    assert md.startswith("# Daily report — 2026-11-02") and "**SYNTHETIC DATA · AI OFFLINE · NO TRADING**" in md
    assert "**0 of 3** rule agents pass the 80% gate" in md
    assert ("Self-tests: **6 of 6** as expected (the planted pattern qualified, Tight Target failed, Leaky Rule was blocked, "
            "plus 3 system checks)") in md
    assert "so no rule should pass on them, and none did." in md and "placeholder balance in settings (1,000 USD), not your account" in md
    assert "There is no live account feed yet" in md and "Nothing watches or stops your live account" in md
    assert "Leaky Rule (demo) · self-test" in md and "(demo) (self-test)" not in md
    assert "--symbols XAUUSD,EURUSD,GBPUSD,USDJPY,US500,BTCUSD --timeframe M15 --months 24 --out data/mt5" in md
    assert "python -m llm_trader snapshot" in md
    assert "**Picks today: none.**" in md
    assert "A high win rate is not an edge.** Tight Target (trap demo)" in md and "break-even win rate = stop ÷ (target + stop)" in md
    assert "## Self-tests" in md and "## Context agents (shadow)" in md and "mql5/GUARDIAN_SPEC.md" in md
    for r in state["research"]:
        assert f"| {r['name']}" in md


def test_the_no_edge_sentence_follows_the_self_test(state):
    broken = json.loads(json.dumps(state))
    no_edge = by_id(broken["self_tests"])["no_edge_symbols"]
    no_edge.update(ok=False, actual="1 of 5 agents qualified")
    md = template_report(broken)
    assert "so no rule should pass on them, but 1 of 5 agents qualified: the gate is too loose (see Self-tests)." in md
    assert "and none did" not in md


def test_a_balance_from_the_local_file_is_named_as_yours_and_not_printed(fresh, run_demo):
    fresh.settings_local.write_text(json.dumps({"account": {"balance": 4321.0}}))
    state = run_demo(fresh)
    assert state["risk"]["account"]["source"] == "local"
    md = state["report"]["markdown"]
    assert "your own balance from config/settings.local.json" in md and "4,321" not in md and "placeholder balance" not in md


def test_v1_says_plainly_that_nothing_is_connected(state):
    assert state["meta"]["account_feed"] is False and state["meta"]["guardian_connected"] is False


def test_no_private_paths_or_secrets(state, project):
    text = json.dumps(state)
    assert str(project.root) not in text and "/home/" not in text and "\\Users\\" not in text
    assert "ANTHROPIC_API_KEY=" not in text


def test_runs_are_repeatable(project, run_demo, state):
    again = run_demo(project)
    assert {k: v for k, v in again.items() if k != "log"} == {k: v for k, v in state.items() if k != "log"}


def test_settings_change_turns_on_safe_mode(fresh, run_demo):
    settings = json.loads(fresh.settings.read_text())
    settings["context"]["event_tagger"]["samples"] = 5
    fresh.settings.write_text(json.dumps(settings, indent=2))
    state = run_demo(fresh)
    assert state["meta"]["safe_mode"]["on"] and "chg-001" in state["meta"]["safe_mode"]["reason"]
    assert state["meta"]["banners"][-1] == "SAFE MODE"
    [item] = state["approvals"]["pending"]
    assert item["diff"] == ["context.event_tagger.samples: 3 → 5"]
    assert next(c for c in state["checks"] if c["stage"] == "approvals")["status"] == "warn"
    assert any(e["level"] == "alert" and "Safe mode" in e["msg"] for e in state["log"])


def test_kill_switch_is_reflected_everywhere(fresh, run_demo):
    KillSwitch.at(fresh).turn_on("Testing the switch.")
    state = run_demo(fresh)
    assert state["meta"]["kill_switch"]["on"] and state["meta"]["kill_switch"]["reason"] == "Testing the switch."
    assert "KILL SWITCH ON" in state["meta"]["banners"] and state["picks_today"]["reason"] == pipeline.KILL_PICKS
    assert state["bridge"]["kill_flag"] is True and state["bridge"]["note"] == bridge.KILL_NOTE and fresh.kill_flag.exists()
    assert json.loads(fresh.bridge_file.read_text()) == {"heartbeat": "2026-11-02T04:10:00Z", "kill": True, "advisories": []}
    assert by_id(state["agents"])["monitor"]["status"] == "warn"
    assert state["pipeline"][3]["status"] == "warn" and "kill switch ON" in state["pipeline"][3]["summary"]
    assert any(e["level"] == "alert" and "Kill switch is ON" in e["msg"] for e in state["log"])
    assert any(m["msg"].startswith("New entries from agents: blocked (the kill switch is on)") for m in state["log"])


def test_a_kill_flag_set_by_hand_stops_everything(fresh, run_demo):
    fresh.kill_flag.parent.mkdir(parents=True)
    fresh.kill_flag.write_text("chart button")
    state = run_demo(fresh)
    assert state["meta"]["kill_switch"] == {"on": True, "reason": FLAG_FOUND, "changed_at": None}
    assert json.loads(fresh.bridge_file.read_text())["kill"] is True


def test_the_old_signals_file_is_removed(fresh, run_demo):
    fresh.bridge_dir.mkdir(parents=True)
    (fresh.bridge_dir / "signals.json").write_text(json.dumps({"signals": [{"id": "old", "lots": 0.01}]}))
    run_demo(fresh)
    assert sorted(p.name for p in fresh.bridge_dir.iterdir()) == ["advisories.json"]


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
    assert meta["data_mode"] == "mt5" and "MT5 data: 2 symbols" in meta["data_note"]
    assert meta["banners"] == ["NOT ELIGIBLE FOR MONEY", "AI OFFLINE", "NO TRADING"]
    assert meta["eligible_for_money"] is False and "forward test" in meta["eligible_note"]
    stages = {r["rule_id"]: (r["gate"]["status"], r["stage"]) for r in state["research"]}
    assert stages["control_planted"] == ("qualified", "research")
    assert stages["demo_rule_b"] == ("blocked", "blocked") and stages["leaky"] == ("blocked", "blocked")
    tests = by_id(state["self_tests"])
    assert tests["tight_target"]["ok"] is None and tests["tight_target"]["actual"] == "not run"
    assert tests["leaky"]["ok"] is True and tests["no_edge_symbols"]["ok"] is None
    assert state["picks_today"]["reason"] == pipeline.BROKER_PICKS
    assert by_id(state["agents"])["tight_target"]["status"] == "idle"
    source = {(c["subject"], c["status"]) for c in state["checks"] if c["name"] == "Data source is your broker's MT5 export"}
    assert ("EURUSD, XAUUSD", "pass") in source and ("CTRL-SYN", "info") in source
    assert any("Using XAUUSD.a as XAUUSD" in entry["msg"] for entry in state["log"])
    assert state["bridge"]["advisories"] == [] and state["bridge"]["note"] == bridge.SHADOW_NOTE
    assert json.loads(fresh.last_run_file.read_text())["data"] == str(folder)
    assert fresh.trials_file.exists()


def as_broker_data(demo) -> dict:
    return {s: (df, {**prov, "source": "mt5_export"}) for s, (df, prov) in demo.items() if s != "CTRL-SYN"} | {"CTRL-SYN": demo["CTRL-SYN"]}


def with_qualified_rule(evaluations, rule_id="demo_rule_a") -> list:
    rule = evaluations[rule_id]
    passed = dataclasses.replace(rule, gate=GateResult("qualified", list(rule.gate.checks), ["Passed (test double)."]))
    return [passed if e.rule_id == rule_id else e for e in evaluations.values()]


def test_qualified_rule_on_broker_data_enters_the_forward_test(fresh, demo, evaluations):
    state = pipeline.run(fresh.root / "data", paths=fresh, dataset=as_broker_data(demo), evaluations=with_qualified_rule(evaluations), now=NOW)
    rule = by_id(state["research"], "rule_id")["demo_rule_a"]
    assert rule["stage"] == "forward_test" and rule["stage_note"].startswith("Forward test: 0 of 30-40 trades at minimum lot")
    assert by_id(state["agents"])["monitor"]["status"] == "ok"
    assert state["picks_today"]["picks"] == [] and state["picks_today"]["reason"].startswith("1 rule agent(s) qualified")
    assert state["bridge"]["advisories"] == [] and state["meta"]["eligible_for_money"] is False
    KillSwitch.at(fresh).turn_on("pause")
    paused = pipeline.run(fresh.root / "data", paths=fresh, dataset=as_broker_data(demo), evaluations=with_qualified_rule(evaluations), now=NOW)
    assert by_id(paused["research"], "rule_id")["demo_rule_a"]["stage"] == "shadow"


def test_data_source_names(fresh):
    settings = json.loads(fresh.settings.read_text())
    assert pipeline.resolve_source("demo", settings, fresh) == "demo"
    assert pipeline.resolve_source(None, settings, fresh) == "demo"
    assert pipeline.resolve_source("mt5", settings, fresh) == fresh.root / "data" / "mt5"
    assert pipeline.resolve_source("exports", settings, fresh) == pipeline.Path("exports")
    settings["data"]["mode"] = "mt5"
    assert pipeline.resolve_source(None, settings, fresh) == fresh.root / "data" / "mt5"


def test_cli_run_prints_a_plain_summary(fresh, state, monkeypatch, capsys):
    calls = []
    monkeypatch.delenv("LLM_MODE", raising=False)
    monkeypatch.setattr(pipeline, "run", lambda data, use_llm, paths: calls.append((data, use_llm)) or state)
    assert cli.main(["run", "--demo"], fresh) == 0
    out = capsys.readouterr().out
    assert calls == [("demo", False)]
    assert "SYNTHETIC DATA | AI OFFLINE | NO TRADING" in out and "Self-tests: 6 of 6 OK" in out
    assert "Self-test: planted pattern *" in out and "Picks today: 0." in out and "advisories.json" in out
    assert out.isascii()
    with pytest.raises(SystemExit):
        cli.main(["run", "--demo", "--data", "x"], fresh)


def test_demo_command_writes_state_and_dashboard_in_one_go(fresh, demo, evaluations, monkeypatch, capsys):
    real, calls = pipeline.run, []

    def fast(data, use_llm, paths):
        calls.append((data, use_llm))
        return real(data, use_llm, paths, dataset=demo, evaluations=list(evaluations.values()), now=NOW)

    monkeypatch.delenv("LLM_MODE", raising=False)
    monkeypatch.setattr(pipeline, "run", fast)
    assert cli.main(["demo"], fresh) == 0
    assert calls == [("demo", False)]
    state = json.loads(fresh.state_file.read_text())
    html = fresh.dashboard_file.read_text(encoding="utf-8")
    assert "window.__STATE__" in html and state["meta"]["generated_at"] in html
    assert json.loads(fresh.bridge_file.read_text())["advisories"] == []
    assert "Open out/dashboard.html in any browser" in capsys.readouterr().out
