from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any

import numpy as np
import pandas as pd

TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
OUTCOMES = ("target", "stop", "breakeven", "time")
GATE_STATUSES = ("qualified", "failed", "insufficient", "blocked")
WINDOW_NAMES = ("development", "holdout", "recent")
TESTED_WINDOWS = ("holdout", "recent")


def timeframe_delta(timeframe: str) -> pd.Timedelta:
    if timeframe not in TIMEFRAME_MINUTES:
        raise ValueError(f"Unknown timeframe {timeframe!r}")
    return pd.Timedelta(minutes=TIMEFRAME_MINUTES[timeframe])


def utc(ts: Any) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def iso(ts: Any) -> str | None:
    return None if ts is None else utc(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_jsonable(value: Any, ndigits: int = 6) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name), ndigits) for f in fields(value)}
    if isinstance(value, dict):
        return {str(k): to_jsonable(v, ndigits) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [to_jsonable(v, ndigits) for v in value]
    if isinstance(value, pd.Timestamp):
        return iso(value)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        v = float(value)
        return round(v, ndigits) if math.isfinite(v) else None
    return value


@dataclass(slots=True)
class Signal:
    rule_id: str
    symbol: str
    time: pd.Timestamp
    side: int
    stop: float | None
    target: float | None
    max_hold_bars: int
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return to_jsonable(self)


@dataclass(slots=True)
class Trade:
    rule_id: str
    symbol: str
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    entry: float
    stop: float
    target: float | None
    side: int
    exit_time: pd.Timestamp
    exit: float
    outcome: str
    r: float
    risk_price: float
    costs_r: float
    hold_bars: int = 1
    max_hold_bars: int = 1
    win: bool = False
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return to_jsonable(self)


@dataclass(slots=True)
class WindowMetrics:
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    trades: int
    wins: int
    win_rate: float | None
    win_rate_ci: tuple[float, float]
    full_stop_rate: float | None
    breakeven_rate: float | None
    expectancy_r: float | None
    profit_factor: float | None
    max_drawdown_r: float
    avg_hold_bars: float | None
    equity_r: list[float]

    def to_dict(self) -> dict:
        return to_jsonable(self)


@dataclass(slots=True)
class RandomBaseline:
    runs: int
    p_value: float
    p_value_win_rate: float
    expectancy_mean: float | None
    expectancy_p95: float | None
    win_rate_mean: float | None
    win_rate_p95: float | None
    hist: dict

    def to_dict(self) -> dict:
        return to_jsonable(self)


@dataclass(slots=True)
class GateCheck:
    name: str
    passed: bool
    value: str
    required: str

    def to_dict(self) -> dict:
        return to_jsonable(self)


@dataclass(slots=True)
class GateResult:
    status: str
    checks: list[GateCheck]
    reasons: list[str]

    def to_dict(self) -> dict:
        return to_jsonable(self)


@dataclass(slots=True)
class PlanInfo:
    sha256: str | None
    locked_at: str | None
    valid: bool
    reason: str | None
    params: dict

    def to_dict(self) -> dict:
        return to_jsonable(self)


@dataclass(slots=True)
class LeakCheck:
    passed: bool
    detail: str

    def to_dict(self) -> dict:
        return to_jsonable(self)


@dataclass(slots=True)
class RuleEvaluation:
    rule_id: str
    name: str
    version: str
    symbols: list[str]
    timeframe: str
    description: str
    demo_note: str
    control: bool
    signals: int
    signals_by_symbol: dict[str, int]
    trades: dict[str, list[Trade]]
    windows: dict[str, WindowMetrics]
    random: dict[str, RandomBaseline]
    leak_check: LeakCheck
    plan: PlanInfo
    median_stop_points: dict[str, float | None]
    gate: GateResult
    hard_failures: list[str]

    def windows_dict(self) -> dict:
        out = {}
        for name in WINDOW_NAMES:
            entry = self.windows[name].to_dict()
            if name in self.random:
                entry["random"] = self.random[name].to_dict()
            out[name] = entry
        return out

    def to_dict(self, include_trades: bool = False) -> dict:
        out = {
            "rule_id": self.rule_id,
            "name": self.name,
            "version": self.version,
            "symbols": list(self.symbols),
            "timeframe": self.timeframe,
            "description": self.description,
            "demo_note": self.demo_note,
            "control": self.control,
            "plan": self.plan.to_dict(),
            "signals": self.signals,
            "signals_by_symbol": dict(self.signals_by_symbol),
            "trades_by_window": {name: len(trades) for name, trades in self.trades.items()},
            "windows": self.windows_dict(),
            "gate": self.gate.to_dict(),
            "leak_check": self.leak_check.to_dict(),
            "median_stop_points": to_jsonable(self.median_stop_points, 1),
            "hard_failures": list(self.hard_failures),
        }
        if include_trades:
            out["trades"] = {name: [t.to_dict() for t in trades] for name, trades in self.trades.items()}
        return out
