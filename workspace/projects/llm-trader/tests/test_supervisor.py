import dataclasses

import numpy as np
import pandas as pd
import pytest

from llm_trader.data.symbols import resolve_spec
from llm_trader.models import GateResult
from llm_trader.risk.engine import Group, correlation_matrix
from llm_trader.supervisor import checks as c
from llm_trader.supervisor.supervisor import StageContext, assign_stage, data_eligibility, supervisor_summary

NOW = pd.Timestamp("2026-11-02 04:00", tz="UTC")
CLEAR = StageContext(data_eligible=True, data_reason="your broker's MT5 data", approvals_clear=True, kill_switch_on=False, risk_ok=True, risk_note=None)


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


def test_check_rows_have_the_contract_keys(demo_rows):
    rows, _ = demo_rows
    for row in rows:
        assert set(row) == {"stage", "agent_id", "subject", "name", "status", "detail"}
        assert row["status"] in ("pass", "warn", "fail", "info") and row["detail"]


def test_demo_data_checks(demo_rows):
    rows, parity = demo_rows
    status = {r["name"]: r["status"] for r in rows}
    assert status[c.NAME_SOURCE] == "warn" and "never eligible for money" in by_name(rows, c.NAME_SOURCE)[0]["detail"]
    for name in (c.NAME_GAPS, c.NAME_DUPLICATES, c.NAME_OHLC, c.NAME_SPIKES, c.NAME_SPREADS):
        assert status[name] == "pass", name
    assert status[c.NAME_END] == "info"
    assert status[c.NAME_PARITY] == "warn"
    assert parity["candles_differ"] > 0.5 and parity["trades_differ"] > 0
    assert "test on the broker data you trade" in by_name(rows, c.NAME_PARITY)[0]["detail"]


def test_gap_inside_market_hours_is_reported(demo, specs):
    df = demo["XAUUSD"][0]
    tuesday = df.index[(df.index.day_of_week == 1) & (df.index.hour == 10)][0]
    holed = df.drop(df.index[df.index.get_loc(tuesday): df.index.get_loc(tuesday) + 8])
    [row] = c.gap_checks(with_xau(demo, holed), specs)
    assert row["status"] == "warn" and row["subject"] == "XAUUSD" and "1 gap(s)" in row["detail"] and "2.0 hours" in row["detail"]


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
    assert row["status"] == "fail" and "1 bar(s)" in row["detail"]


def test_duplicates_are_reported(demo):
    [row] = c.duplicate_checks(with_xau(demo, duplicates=3))
    assert row["status"] == "warn" and "3 bar(s)" in row["detail"]


def test_bad_tick_spike_is_reported(demo):
    df = demo["XAUUSD"][0].copy()
    df.iloc[5000, df.columns.get_loc("high")] = df["close"].iloc[5000] * 1.2
    [row] = c.spike_checks(with_xau(demo, df))
    assert row["status"] == "warn" and "1 bar(s)" in row["detail"]


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


def qualified(e):
    gate = GateResult("qualified", list(e.gate.checks), ["Looks good."])
    return dataclasses.replace(e, gate=gate, control=False, hard_failures=[])


def test_stages_follow_the_gate_and_the_safety_switches(evaluations):
    sweep = qualified(evaluations["sweep_fade"])
    assert assign_stage(sweep, CLEAR)[0] == "forward_test"
    stage, note, forward = assign_stage(sweep, CLEAR)
    assert note == "Forward test: 0 of 30-40 trades at minimum lot." and forward["note"].startswith("Waiting for the MT5 bridge EA")
    assert assign_stage(sweep, dataclasses.replace(CLEAR, data_eligible=False, data_reason="demo data"))[0] == "research"
    assert assign_stage(sweep, dataclasses.replace(CLEAR, kill_switch_on=True))[0] == "shadow"
    assert assign_stage(sweep, dataclasses.replace(CLEAR, approvals_clear=False))[0] == "shadow"
    assert assign_stage(sweep, dataclasses.replace(CLEAR, risk_ok=False, risk_note="too big"))[0] == "shadow"
    assert assign_stage(evaluations["control_planted"], CLEAR)[:2] == (
        "research", "Qualified: the gate found the planted pattern. This is the self-test on synthetic data, so it is never traded.")
    assert assign_stage(evaluations["sweep_fade"], CLEAR)[0] == "research"
    assert assign_stage(evaluations["trend_pullback"], CLEAR)[0] == "research"
    assert assign_stage(evaluations["leaky"], CLEAR)[:2] == ("blocked", "Blocked by the supervisor (future-data leak). Nothing moves forward until that is fixed.")


def test_demo_data_is_never_eligible(evaluations, demo):
    assert data_eligibility(evaluations["sweep_fade"], demo) == (False, "demo data")
    broker = {s: (df, {**prov, "source": "mt5_export"}) for s, (df, prov) in demo.items()}
    assert data_eligibility(evaluations["sweep_fade"], broker) == (True, "your broker's MT5 data")
    mixed = {**broker, "EURUSD": (demo["EURUSD"][0], {**demo["EURUSD"][1], "source": "other"})}
    assert data_eligibility(evaluations["sweep_fade"], mixed)[0] is False


def test_overlapping_qualified_agents_count_as_one_bet(evaluations, demo):
    corr = correlation_matrix({s: df for s, (df, _) in demo.items()})
    usd = Group("USD", "US dollar", {"EURUSD": -1, "XAUUSD": -1, "GBPUSD": -1})
    a = qualified(evaluations["sweep_fade"])
    b = dataclasses.replace(qualified(evaluations["trend_pullback"]), rule_id="other")
    rows = c.overlap_checks([a, b], [usd], corr, 0.6)
    assert rows and all(r["status"] == "warn" for r in rows)
    assert "count as one bet" in rows[0]["detail"]
    [solo] = c.overlap_checks(list(evaluations.values()), [usd], corr, 0.6)
    assert solo["status"] == "pass" and "1 agent(s) qualified" in solo["detail"]


def test_correlated_symbols_without_a_group_are_flagged():
    corr = {"symbols": ["A", "B", "C"], "matrix": [[1, 0.8, 0.1], [0.8, 1, 0.0], [0.1, 0.0, 1]], "window": "last 90 days, H1 returns"}
    [row] = c.ungrouped_correlation_checks([], corr, 0.6)
    assert row["subject"] == "A + B" and row["status"] == "warn"
    assert c.ungrouped_correlation_checks([Group("G", "G", {"A": 1, "B": 1})], corr, 0.6) == []


def test_validation_and_research_checks_on_the_demo(evaluations):
    values = list(evaluations.values())
    gate = {r["subject"]: r for r in c.gate_checks(values, 0.8)}
    assert gate["control_planted"]["name"] == c.NAME_SELF_TEST and gate["control_planted"]["status"] == "pass"
    assert gate["tight_target"]["status"] == "fail" and gate["trend_pullback"]["status"] == "warn" and gate["leaky"]["status"] == "fail"
    assert [r["subject"] for r in c.leak_checks(values) if r["status"] == "fail"] == ["leaky"]
    strict = [r for r in c.strictness_checks(values, 30) if r["status"] == "warn"]
    assert [r["subject"] for r in strict] == ["trend_pullback"] and "Too strict" in strict[0]["detail"]
    assert c.stop_checks(values)[0]["status"] == "pass"
    assert c.plan_checks(values)[0]["detail"] == "6 of 6 test plans were locked (hashed) before testing and are unchanged."


def test_supervisor_summary_counts_what_it_caught(evaluations, demo_rows):
    status, summary = supervisor_summary(list(evaluations.values()), demo_rows[0])
    assert status == "warn"
    assert summary == "1 of 6 qualified (the self-test only). Caught: blocked 1 (future-data leak); 1 too strict to judge; 3 failed the gate."


def test_a_failed_self_test_is_a_supervisor_failure(evaluations, demo_rows):
    broken = dataclasses.replace(evaluations["control_planted"], gate=GateResult("failed", [], ["No edge found."]))
    assert supervisor_summary([broken], demo_rows[0])[0] == "fail"
