from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any

import numpy as np
import pandas as pd

TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
OUTCOMES = ("target", "stop", "breakeven", "time")
LABELS = ("win", "breakeven", "loss")
GATE_STATUSES = ("qualified", "failed", "insufficient", "blocked")
WINDOW_NAMES = ("development", "holdout", "recent")
TESTED_WINDOWS = ("holdout", "recent")
EXPECTED_STATUS = {"must qualify": "qualified", "must fail": "failed", "must be blocked": "blocked"}


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


@dataclass(frozen=True, slots=True)
class Labels:
    win_threshold_r: float = 0.1
    breakeven_band_r: float = 0.1
    full_stop_r: float = -0.9

    @classmethod
    def from_gate(cls, gate_cfg: dict | None) -> Labels:
        cfg = gate_cfg or {}
        default = cls()
        return cls(
            float(cfg.get("win_threshold_r", default.win_threshold_r)),
            float(cfg.get("breakeven_band_r", default.breakeven_band_r)),
            float(cfg.get("full_stop_r", default.full_stop_r)),
        )

    def label(self, r: float) -> str:
        if r >= self.win_threshold_r:
            return "win"
        return "loss" if r <= -self.breakeven_band_r else "breakeven"

    def is_full_stop(self, r: float) -> bool:
        return bool(r <= self.full_stop_r)

    def wins(self, r: np.ndarray) -> np.ndarray:
        return np.asarray(r, dtype=float) >= self.win_threshold_r


DEFAULT_LABELS = Labels()


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
    label: str | None = None
    full_stop: bool | None = None
    entry_atr: float | None = None
    signal_price: float | None = None
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.label is None:
            self.label = DEFAULT_LABELS.label(self.r)
        if self.full_stop is None:
            self.full_stop = DEFAULT_LABELS.is_full_stop(self.r)

    @property
    def win(self) -> bool:
        return self.label == "win"

    def to_dict(self) -> dict:
        return {**to_jsonable(self), "win": self.win}


@dataclass(slots=True)
class WindowMetrics:
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    trades: int
    wins: int
    losses: int
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
class WindowExtra:
    expectancy_ci: tuple[float | None, float | None]
    expectancy_1_5x_costs: float | None
    expectancy_2x_costs: float | None
    long: dict
    short: dict
    terciles: list[dict]
    stop_target_ratio: float | None
    holm_threshold: float | None = None
    trial_count: int = 0

    def to_dict(self) -> dict:
        return to_jsonable(self)


@dataclass(slots=True)
class HolmDecision:
    p_value: float
    rank: int
    family: int
    tries: int
    threshold: float
    passed: bool
    stopped_early: bool = False
    note: str | None = None

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
    self_test: bool = False
    expected: str | None = None
    extra: dict[str, WindowExtra] = field(default_factory=dict)
    trial_count: int = 0
    prior_trials: int = 0
    holm: HolmDecision | None = None
    trials_note: str | None = None
    results_hidden: bool = False

    @property
    def kind(self) -> str:
        return "self_test" if self.self_test else "rule"

    @property
    def self_test_ok(self) -> bool | None:
        if not self.self_test:
            return None
        return EXPECTED_STATUS.get(self.expected or "") == self.gate.status

    def windows_dict(self) -> dict:
        out = {}
        for name in WINDOW_NAMES:
            entry = self.windows[name].to_dict()
            if name in self.random:
                entry["random"] = self.random[name].to_dict()
            if name in self.extra:
                entry["extra"] = self.extra[name].to_dict()
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
            "kind": self.kind,
            "self_test": self.self_test,
            "expected": self.expected,
            "self_test_ok": self.self_test_ok,
            "plan": self.plan.to_dict(),
            "signals": self.signals,
            "signals_by_symbol": dict(self.signals_by_symbol),
            "trades_by_window": {name: len(trades) for name, trades in self.trades.items()},
            "windows": self.windows_dict(),
            "gate": self.gate.to_dict(),
            "leak_check": self.leak_check.to_dict(),
            "median_stop_points": to_jsonable(self.median_stop_points, 1),
            "hard_failures": list(self.hard_failures),
            "trial_count": self.trial_count,
            "prior_trials": self.prior_trials,
            "holm": None if self.holm is None else self.holm.to_dict(),
            "trials_note": self.trials_note,
            "results_hidden": self.results_hidden,
        }
        if include_trades:
            out["trades"] = {name: [t.to_dict() for t in trades] for name, trades in self.trades.items()}
        return out
