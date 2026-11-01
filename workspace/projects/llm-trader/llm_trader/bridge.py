from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from llm_trader.config import write_json
from llm_trader.data.symbols import SymbolSpec
from llm_trader.models import Signal, iso, timeframe_delta, utc
from llm_trader.risk.engine import Decision, RiskEngine

FORMAT = "superagentic-bridge/1"
DEMO_NOTE = "Only qualified + approved signals on broker data are written. None today (demo data)."
KILL_NOTE = "Kill switch is ON: nothing is sent to the EA."
SAFE_NOTE = "Safe mode: settings or test plans changed without your YES. Nothing is sent until you approve or undo the change."
IDLE_NOTE = "No agent is in a forward test on your broker's data, so there is nothing to send."


@dataclass(frozen=True)
class Candidate:
    rule_id: str
    plan_sha256: str
    signal: Signal
    price: float
    timeframe: str


@dataclass
class BridgeOutput:
    payload: dict
    skipped: list[str] = field(default_factory=list)

    @property
    def written(self) -> int:
        return len(self.payload["signals"])

    def state(self, file_label: str) -> dict:
        return {"file": file_label, "written": self.written, "signals": list(self.payload["signals"]), "note": self.payload["note"]}


def payload(generated_at: str, data_mode: str, kill_switch_on: bool, safe_mode_on: bool, signals: list[dict], note: str) -> dict:
    return {
        "format": FORMAT,
        "generated_at": generated_at,
        "data_mode": data_mode,
        "kill_switch": kill_switch_on,
        "safe_mode": safe_mode_on,
        "written": len(signals),
        "note": note,
        "signals": signals,
    }


def signal_record(candidate: Candidate, decision: Decision, spec: SymbolSpec, expires) -> dict:
    s = candidate.signal
    return {
        "id": f"{candidate.rule_id}-{s.symbol}-{utc(s.time).strftime('%Y%m%dT%H%MZ')}",
        "rule_id": candidate.rule_id,
        "plan_sha256": candidate.plan_sha256,
        "symbol": s.symbol,
        "side": "buy" if s.side > 0 else "sell",
        "order": "market",
        "lots": decision.lots,
        "stop": round(float(s.stop), spec.digits),
        "target": None if s.target is None else round(float(s.target), spec.digits),
        "time": iso(s.time),
        "expires_at": iso(expires),
        "max_hold_bars": int(s.max_hold_bars),
        "timeframe": candidate.timeframe,
        "risk_pct": round(decision.risk_pct, 3),
    }


def build(
    *, generated_at: str, data_mode: str, kill_switch_on: bool, safe_mode_on: bool, candidates: list[Candidate],
    engine: RiskEngine, positions=(), now=None, forward_agents: int = 0,
) -> BridgeOutput:
    def empty(note: str) -> BridgeOutput:
        return BridgeOutput(payload(generated_at, data_mode, kill_switch_on, safe_mode_on, [], note))

    if kill_switch_on:
        return empty(KILL_NOTE)
    if data_mode != "mt5":
        return empty(DEMO_NOTE)
    if safe_mode_on:
        return empty(SAFE_NOTE)
    if not candidates:
        return empty(f"{forward_agents} agent(s) in a forward test, but none signalled on the latest bar." if forward_agents else IDLE_NOTE)
    clock = utc(now if now is not None else generated_at)
    held = list(positions)
    signals, skipped = [], []
    for candidate in candidates:
        s = candidate.signal
        label = f"{candidate.rule_id} {s.symbol} {iso(s.time)}"
        expires = utc(s.time) + timeframe_delta(candidate.timeframe)
        if clock >= expires:
            skipped.append(f"{label}: expired at {iso(expires)}")
            continue
        decision = engine.check(s, candidate.price, held)
        if not decision.ok:
            skipped.append(f"{label}: {decision.reasons[0]}")
            continue
        held.append(decision.as_position(s))
        signals.append(signal_record(candidate, decision, engine.specs[s.symbol], expires))
    if signals:
        note = f"{len(signals)} signal(s) written for the EA. Each carries a stop, the minimum lot, its plan hash and an expiry."
    else:
        note = f"{len(skipped)} signal(s) checked, none sent: {skipped[0]}"
    return BridgeOutput(payload(generated_at, data_mode, False, False, signals, note), skipped)


def write(path: Path, output: BridgeOutput) -> Path:
    return write_json(path, output.payload)


def clear(path: Path, generated_at: str, data_mode: str, note: str, kill_switch_on: bool = True) -> Path:
    return write_json(path, payload(generated_at, data_mode, kill_switch_on, False, [], note))
