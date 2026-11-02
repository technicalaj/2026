import dataclasses

import numpy as np
import pandas as pd
import pytest

from llm_trader.data.symbols import resolve_spec
from llm_trader.models import GateCheck, GateResult
from llm_trader.risk.engine import Group, correlation_matrix
from llm_trader.supervisor import checks as c
from llm_trader.supervisor.supervisor import (
    StageContext, assign_stage, blocked_kind, data_eligibility, entry_decision, self_tests_ok, supervisor_summary,
)

NOW = pd.Timestamp("2026-11-02 04:00", tz="UTC")
CLEAR = StageContext(data_eligible=True, data_reason="your broker's MT5 data", approvals_clear=True, kill_switch_on=False, risk_ok=True, risk_note=None)
REGIME = "Positive in at least 2 of 3 volatility regimes (never-seen months)"


@pytest.fixture(scope="module")
def specs(demo, settings):
    return {s: resolve_spec(s, prov, settings["costs"]) for s, (_, prov) in demo.items()}


@pytest.fixture(scope="module")
def demo_rows(demo, specs, settings):
    return c.data_checks(demo, specs, settings, "demo", NOW)


def by_name(rows, name):
    return [r for r in rows if r["name"] == name]


def with_xau(demo, df=None, **prov):
    frame, provenance = demo["XAUUSD"]
    return {"XAUUSD": (frame if df is None else df, {**provenance, **prov})}


def with_gate(e, status: str, failed=(), reasons=("Test double.",)):
    checks = [dataclasses.replace(ch, passed=ch.name not in failed) for ch in e.gate.checks]
    checks += [GateCheck(name, False, "x", "y") for name in failed if name not in {ch.name for ch in e.gate.checks}]
    return dataclasses.replace(e, gate=GateResult(status, checks, list(reasons)), hard_failures=[])


def test_check_rows_have_the_contract_keys(demo_rows):
    rows, _ = demo_rows
    for row in rows:
        assert set(row) == {"stage", "agent_id", "subject", "name", "status", "detail"}
        assert row["status"] in ("pass", "warn", "fail", "info") and row["detail"]


def test_demo_data_checks(demo_rows):
    rows, parity = demo_rows
    status = {r["name"]: r["status"] for r in rows}
    assert status[c.NAME_SOURCE] == "info" and "Expected on demo data" in by_name(rows, c.NAME_SOURCE)[0]["detail"]
    assert "never eligible for money" in by_name(rows, c.NAME_SOURCE)[0]["detail"].lower()
    for name in (c.NAME_GAPS, c.NAME_DUPLICATES, c.NAME_OHLC, c.NAME_SPIKES, c.NAME_SPREADS):
        assert status[name] == "pass", name
    assert status[c.NAME_END] == "info" and status[c.NAME_PARITY] == "info"
    assert parity["candles_differ"] > 0.5 and parity["trades_differ"] > 0
    detail = by_name(rows, c.NAME_PARITY)[0]["detail"]
    assert "Demo Rule A (reversal) takes" in detail and "test on the broker data you trade" in detail


def test_every_symbol_is_fingerprinted(demo, demo_rows):
    rows, _ = demo_rows
    [row] = by_name(rows, c.NAME_FINGERPRINT)
    assert row["status"] == "pass" and all(f"{s} {prov['sha256'][:8]}" in row["detail"] for s, (_, prov) in demo.items())
    unhashed = c.fingerprint_check(with_xau(demo, sha256=None))
    assert unhashed["status"] == "warn" and unhashed["subject"] == "XAUUSD"


def test_gap_inside_market_hours_is_reported(demo, specs):
    df = demo["XAUUSD"][0]
    tuesday = df.index[(df.index.day_of_week == 1) & (df.index.hour == 10)][0]
    holed = df.drop(df.index[df.index.get_loc(tuesday): df.index.get_loc(tuesday) + 8])
    [row] = c.gap_checks(with_xau(demo, holed), specs)
    assert row["status"] == "warn" and row["subject"] == "XAUUSD" and "1 gap outside" in row["detail"] and "2.0 hours" in row["detail"]


def test_weekend_rollover_and_holiday_closures_are_expected():
    friday = pd.Timestamp("2026-03-06 21:00", tz="UTC")
    assert c._expected_gap(friday, pd.Timestamp("2026-03-08 22:00", tz="UTC"), "metal")
    assert not c._expected_gap(friday, pd.Timestamp("2026-03-08 22:00", tz="UTC"), "crypto")
    assert c._expected_gap(pd.Timestamp("2026-03-03 21:00", tz="UTC"), pd.Timestamp("2026-03-03 22:00", tz="UTC"), "crypto")
    assert c._expected_gap(pd.Timestamp("2025-12-24 21:00", tz="UTC"), pd.Timestamp("2025-12-26 01:00", tz="UTC"), "fx")
    assert not c._expected_gap(pd.Timestamp("2026-03-03 10:00", tz="UTC"), pd.Timestamp("2026-03-03 11:00", tz="UTC"), "fx")


def test_broken_candles_fail(demo):
    df = demo["XAUUSD"][0].copy()
    df.iloc[100, df.columns.get_loc("high")] = df["low"].iloc[100] - 1.0
    [row] = c.ohlc_checks(with_xau(demo, df))
    assert row["status"] == "fail" and "1 bar breaks" in row["detail"]


def test_duplicates_are_reported(demo):
    [row] = c.duplicate_checks(with_xau(demo, duplicates=3))
    assert row["status"] == "warn" and "3 bars" in row["detail"]


def test_bad_tick_spike_is_reported(demo):
    df = demo["XAUUSD"][0].copy()
    df.iloc[5000, df.columns.get_loc("high")] = df["close"].iloc[5000] * 1.2
    [row] = c.spike_checks(with_xau(demo, df))
    assert row["status"] == "warn" and "1 bar " in row["detail"]


def test_missing_spread_falls_back_to_settings(demo, specs):
    df = demo["XAUUSD"][0].copy()
    df["spread"] = np.nan
    [row] = c.spread_checks(with_xau(demo, df), specs)
    assert row["status"] == "warn" and "100% of bars have no spread" in row["detail"] and "typical 20 points" in row["detail"]


def test_provenance_rows_for_broker_data(demo):
    frame, prov = demo["XAUUSD"]
    dataset = {
        "XAUUSD": (frame, {**prov, "source": "mt5_export", "time_basis": "UTC", "file": "XAUUSD_M15.csv"}),
        "EURUSD": (frame, {**prov, "source": "mt5_export", "time_basis": "assumed UTC (MT5 terminal export; server time zone not given)"}),
        "CTRL-SYN": demo["CTRL-SYN"],
        "US500": (frame, {**prov, "source": "other", "file": "tv_export.csv"}),
    }
    rows = {(r["subject"], r["status"]) for r in c.provenance_checks(dataset)}
    assert ("XAUUSD, EURUSD", "pass") in rows
    assert ("EURUSD", "warn") in rows and ("CTRL-SYN", "info") in rows and ("US500", "warn") in rows


def test_old_broker_data_is_flagged(demo):
    row = c.data_end_check(demo, "mt5", pd.Timestamp("2026-11-09", tz="UTC"))
    assert row["status"] == "warn" and "9 days ago" in row["detail"]


def test_stages_follow_the_gate_and_the_safety_switches(evaluations):
    rule = with_gate(evaluations["demo_rule_a"], "qualified")
    stage, note, forward = assign_stage(rule, CLEAR)
    assert stage == "forward_test" and note.startswith("Forward test: 0 of 30-40 trades at minimum lot")
    assert forward["note"] == "Waiting for the EA to report trades."
    assert assign_stage(rule, dataclasses.replace(CLEAR, data_eligible=False, data_reason="demo data"))[0] == "research"
    assert assign_stage(rule, dataclasses.replace(CLEAR, kill_switch_on=True))[0] == "shadow"
    assert assign_stage(rule, dataclasses.replace(CLEAR, approvals_clear=False))[0] == "shadow"
    assert assign_stage(rule, dataclasses.replace(CLEAR, risk_ok=False, risk_note="too big"))[0] == "shadow"
    assert assign_stage(evaluations["demo_rule_a"], CLEAR)[0] == "research"
    assert assign_stage(evaluations["trend_pullback"], CLEAR)[0] == "research"


def test_regime_specific_rule_is_kept_in_shadow(evaluations):
    rule = with_gate(evaluations["demo_rule_a"], "failed", failed=(REGIME,))
    stage, note, _ = assign_stage(rule, CLEAR)
    assert stage == "shadow" and note.startswith("Regime-specific")
    both = with_gate(evaluations["demo_rule_a"], "failed", failed=(REGIME, "Win rate ≥ 80% in never-seen months"))
    assert assign_stage(both, CLEAR)[0] == "research"


def test_self_tests_are_never_traded(evaluations):
    stage, note, forward = assign_stage(evaluations["control_planted"], CLEAR)
    assert stage == "research" and note.startswith("Self-test (must qualify): qualified, as expected")
    assert forward["note"] == "Self-test only: never forward tested."
    assert assign_stage(evaluations["tight_target"], CLEAR)[:2] == ("research", "Self-test (must fail): failed, as expected. Self-tests are never traded.")
    stage, note, _ = assign_stage(evaluations["leaky"], CLEAR)
    assert stage == "blocked" and "future-data leak" in note


def test_too_good_to_be_true_is_named(evaluations):
    rule = with_gate(evaluations["demo_rule_a"], "blocked", failed=("Not too good to be true (win rate ≤ 90%, profit factor ≤ 4)",))
    assert blocked_kind(rule) == "too good to be true: needs a leak review"


def test_missing_data_means_a_self_test_did_not_run(evaluations):
    missing = dataclasses.replace(evaluations["tight_target"], gate=GateResult("blocked", [], ["Blocked — No data for BTCUSD."]),
                                  hard_failures=["No data for BTCUSD; the locked plan needs every listed symbol."])
    assert self_tests_ok([missing]) is None
    assert self_tests_ok([missing, evaluations["leaky"]]) is True
    broken = dataclasses.replace(evaluations["control_planted"], gate=GateResult("failed", [], ["No edge found."]))
    assert self_tests_ok([missing, broken]) is False


@pytest.mark.parametrize("kwargs, expected", [
    (dict(kill_switch_on=True, loss_stops=[], qualified=True, data_red=False, risk_rules=[]), {"decision": "block", "why": ["kill_switch"]}),
    (dict(kill_switch_on=False, loss_stops=["daily_stop"], qualified=True, data_red=False, risk_rules=[]), {"decision": "block", "why": ["daily_stop"]}),
    (dict(kill_switch_on=False, loss_stops=[], qualified=False, data_red=False, risk_rules=[]), {"decision": "block", "why": ["not_qualified"]}),
    (dict(kill_switch_on=False, loss_stops=[], qualified=True, data_red=True, risk_rules=[]), {"decision": "pause", "why": ["data_red"]}),
    (dict(kill_switch_on=False, loss_stops=[], qualified=True, data_red=False, risk_rules=["cluster_cap"]), {"decision": "block", "why": ["cluster_cap"]}),
    (dict(kill_switch_on=False, loss_stops=[], qualified=True, data_red=False, risk_rules=[]), {"decision": "allow", "why": []}),
])
def test_entry_decision_rule_in_plan_order(kwargs, expected):
    assert entry_decision(**kwargs) == expected


def test_demo_data_is_never_eligible(evaluations, demo):
    rule = evaluations["demo_rule_a"]
    assert data_eligibility(rule, demo) == (False, "demo data")
    broker = {s: (df, {**prov, "source": "mt5_export"}) for s, (df, prov) in demo.items()}
    assert data_eligibility(rule, broker) == (True, "your broker's MT5 data")
    mixed = {**broker, "EURUSD": (demo["EURUSD"][0], {**demo["EURUSD"][1], "source": "other"})}
    assert data_eligibility(rule, mixed)[0] is False


def test_overlapping_qualified_rules_count_as_one_bet(evaluations, demo):
    corr = correlation_matrix({s: df for s, (df, _) in demo.items()})
    usd = Group("USD", "US dollar", {"EURUSD": -1, "XAUUSD": -1, "GBPUSD": -1})
    a = with_gate(evaluations["demo_rule_a"], "qualified")
    b = dataclasses.replace(with_gate(evaluations["trend_pullback"], "qualified"), rule_id="other")
    rows = c.overlap_checks([a, b], [usd], corr, 0.6)
    assert rows and all(r["status"] == "warn" for r in rows) and "count as one bet" in rows[0]["detail"]
    [solo] = c.overlap_checks(list(evaluations.values()), [usd], corr, 0.6)
    assert solo["status"] == "pass" and "0 rule agents qualified" in solo["detail"]


def test_correlated_symbols_without_a_cluster_are_flagged():
    corr = {"symbols": ["A", "B", "C"], "matrix": [[1, 0.8, 0.1], [0.8, 1, 0.0], [0.1, 0.0, 1]], "window": "last 90 days, H1 returns"}
    [row] = c.ungrouped_correlation_checks([], corr, 0.6)
    assert row["subject"] == "A + B" and row["status"] == "warn"
    assert c.ungrouped_correlation_checks([Group("G", "G", {"A": 1, "B": 1})], corr, 0.6) == []


def test_validation_and_research_checks_on_the_demo(evaluations):
    values = list(evaluations.values())
    gate = {r["agent_id"]: r for r in c.gate_checks(values, 0.8)}
    assert gate["control_planted"]["name"] == "Self-test: must qualify" and gate["control_planted"]["status"] == "pass"
    assert gate["control_planted"]["subject"] == "Planted pattern" and gate["demo_rule_a"]["subject"] == "Demo Rule A (reversal)"
    assert gate["tight_target"]["status"] == "pass" and gate["leaky"]["status"] == "pass"
    assert gate["demo_rule_a"]["status"] == "fail" and gate["trend_pullback"]["status"] == "warn"
    leaks = {r["agent_id"]: r for r in c.leak_checks(values)}
    assert not any(r["status"] == "fail" for r in leaks.values())
    assert leaks["leaky"]["status"] == "pass" and leaks["leaky"]["detail"].startswith("Caught the planted leak (self-test)")
    strict = [r for r in c.strictness_checks(values, 30) if r["agent_id"] == "trend_pullback"]
    assert [r["status"] for r in strict] == ["info"] and "Too strict: only 12 trades" in strict[0]["detail"]
    assert c.stop_checks(values)[0]["status"] == "pass"
    assert c.plan_checks(values)[0]["detail"] == "6 of 6 test plans were locked (hashed) before testing and are unchanged."


def test_loss_stop_and_shadow_checks():
    limits = {"daily_stop_pct": 2.0, "weekly_stop_pct": 4.0, "overall_kill_pct": 6.0}
    [ok] = c.loss_stop_checks([], limits)
    assert ok["status"] == "pass" and "daily 2%, weekly 4%, overall 6%" in ok["detail"]
    [hit] = c.loss_stop_checks([("daily_stop", "Daily stop: 2.1% lost today.")], limits)
    assert hit["status"] == "fail" and hit["detail"] == "Daily stop: 2.1% lost today."
    tagger = {"stage": "shadow", "measured": "UNMEASURED", "model": "m (offline mock)", "last": [{}, {}]}
    row = c.tagger_check(tagger, 1)
    assert row["status"] == "info" and row["agent_id"] == "event_tagger" and "1 of 2 questions got split answers" in row["detail"]


def test_supervisor_summary_counts_rules_and_self_tests_apart(evaluations, demo_rows):
    status, summary = supervisor_summary(list(evaluations.values()), demo_rows[0])
    assert status == "ok"
    assert summary == ("0 of 3 rule agents qualified (2 failed the gate; 1 too strict to judge). "
                       "Self-tests: 3 of 3 as expected (the planted pattern qualified, Tight Target failed, Leaky Rule was blocked).")
    system = [{"ok": True}, {"ok": True}, {"ok": True}, {"ok": True}, {"ok": True}, {"ok": True}]
    assert supervisor_summary(list(evaluations.values()), demo_rows[0], system)[1].endswith(
        "Self-tests: 6 of 6 as expected (the planted pattern qualified, Tight Target failed, Leaky Rule was blocked, plus 3 system checks).")


def test_a_failed_self_test_is_a_supervisor_failure(evaluations, demo_rows):
    broken = dataclasses.replace(evaluations["control_planted"], gate=GateResult("failed", [], ["No edge found."]))
    assert supervisor_summary([broken], demo_rows[0])[0] == "fail"
