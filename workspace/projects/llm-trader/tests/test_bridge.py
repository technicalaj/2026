import json
import re

import pandas as pd
import pytest
from conftest import ROOT, make_spec

from llm_trader import bridge
from llm_trader.models import Signal
from llm_trader.risk.engine import Account, Group, Limits, RiskEngine

NOW = pd.Timestamp("2026-11-02 10:20", tz="UTC")
SIGNAL_TIME = pd.Timestamp("2026-11-02 10:15", tz="UTC")
PLAN = "a" * 64


def engine() -> RiskEngine:
    specs = {
        "XAUUSD": make_spec(name="XAUUSD", margin_per_min_lot=88.0),
        "EURUSD": make_spec(name="EURUSD", point=0.00001, digits=5, contract_size=100_000, tick_size=0.00001, tick_value=1.0, margin_per_min_lot=36.0),
    }
    return RiskEngine(Account(1000.0), Limits(max_open_risk_pct=10.0), [Group("USD", "US dollar", {"EURUSD": -1, "XAUUSD": -1})], specs)


def candidate(symbol="XAUUSD", side=1, stop=2645.504, target=2654.5, price=2650.0, time=SIGNAL_TIME) -> bridge.Candidate:
    return bridge.Candidate("sweep_fade", PLAN, Signal("sweep_fade", symbol, time, side, stop, target, 16), price, "M15")


def build(**overrides) -> bridge.BridgeOutput:
    args = dict(generated_at="2026-11-02T10:20:00Z", data_mode="mt5", kill_switch_on=False, safe_mode_on=False,
                candidates=[candidate()], engine=engine(), now=NOW)
    return bridge.build(**{**args, **overrides})


def test_demo_data_is_never_sent(tmp_path):
    out = build(data_mode="demo")
    assert out.written == 0 and out.payload["note"] == bridge.DEMO_NOTE
    path = bridge.write(tmp_path / "bridge" / "signals.json", out)
    payload = json.loads(path.read_text())
    assert payload == {
        "format": "superagentic-bridge/1", "generated_at": "2026-11-02T10:20:00Z", "data_mode": "demo", "kill_switch": False,
        "safe_mode": False, "written": 0, "note": bridge.DEMO_NOTE, "signals": [],
    }
    assert out.state("out/bridge/signals.json") == {"file": "out/bridge/signals.json", "written": 0, "signals": [], "note": bridge.DEMO_NOTE}


def test_kill_switch_sends_nothing():
    out = build(kill_switch_on=True)
    assert out.written == 0 and out.payload["kill_switch"] is True and out.payload["note"] == bridge.KILL_NOTE


def test_safe_mode_sends_nothing():
    out = build(safe_mode_on=True)
    assert out.written == 0 and out.payload["safe_mode"] is True and out.payload["note"] == bridge.SAFE_NOTE


def test_no_forward_test_means_nothing_to_send():
    assert build(candidates=[]).payload["note"] == bridge.IDLE_NOTE
    assert build(candidates=[], forward_agents=2).payload["note"] == "2 agent(s) in a forward test, but none signalled on the latest bar."


def test_forward_test_signal_carries_stop_min_lot_plan_hash_and_expiry():
    out = build()
    assert out.written == 1 and out.skipped == []
    [record] = out.payload["signals"]
    assert record == {
        "id": "sweep_fade-XAUUSD-20261102T1015Z", "rule_id": "sweep_fade", "plan_sha256": PLAN, "symbol": "XAUUSD",
        "side": "buy", "order": "market", "lots": 0.01, "stop": 2645.5, "target": 2654.5, "time": "2026-11-02T10:15:00Z",
        "expires_at": "2026-11-02T10:30:00Z", "max_hold_bars": 16, "timeframe": "M15", "risk_pct": 0.45,
    }
    assert "Each carries a stop" in out.payload["note"]


def test_expired_signal_is_skipped():
    out = build(now=pd.Timestamp("2026-11-02 10:30", tz="UTC"))
    assert out.written == 0 and "expired at 2026-11-02T10:30:00Z" in out.skipped[0]


def test_signal_without_stop_is_never_written():
    out = build(candidates=[candidate(stop=None, target=None)])
    assert out.written == 0 and "No stop-loss" in out.skipped[0] and "none sent" in out.payload["note"]


def test_one_portfolio_limit_inside_a_batch():
    out = build(candidates=[candidate(), candidate(symbol="EURUSD", stop=1.08, target=1.09, price=1.085)])
    assert [s["symbol"] for s in out.payload["signals"]] == ["XAUUSD"]
    assert "US dollar group already holds" in out.skipped[0]


@pytest.mark.parametrize("kill", [True, False])
def test_clear_writes_an_empty_file(tmp_path, kill):
    path = tmp_path / "signals.json"
    path.write_text(json.dumps({"signals": [{"id": "stale"}]}))
    bridge.clear(path, "2026-11-02T10:20:00Z", "mt5", "Stopped.", kill_switch_on=kill)
    payload = json.loads(path.read_text())
    assert payload["signals"] == [] and payload["written"] == 0 and payload["kill_switch"] is kill and payload["note"] == "Stopped."
    assert not list(tmp_path.glob("*.tmp"))


def test_no_order_code_anywhere():
    order_calls = re.compile(r"order_send|OrderSend|create_order|order_check")
    mt5_import = re.compile(r"^\s*(import|from)\s+MetaTrader5", re.MULTILINE)
    for path in (ROOT / "llm_trader").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not order_calls.search(text), path
        assert not mt5_import.search(text), path
    exporter = (ROOT / "tools" / "export_mt5_data.py").read_text(encoding="utf-8")
    assert not re.search(r"\.(order_send|order_check)\(", exporter)
