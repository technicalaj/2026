from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AgentStatus = Literal["ok", "warn", "fail", "idle", "planned"]
GateStatus = Literal["qualified", "failed", "insufficient", "blocked"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KillSwitchState(Strict):
    on: bool
    reason: str | None
    changed_at: str | None


class SafeMode(Strict):
    on: bool
    reason: str | None


class Meta(Strict):
    app: Literal["Superagentic"]
    version: str
    generated_at: str
    data_mode: Literal["demo", "mt5"]
    data_note: str
    llm_mode: Literal["offline", "claude"]
    llm_note: str
    accuracy_bar: float = Field(gt=0, le=1)
    kill_switch: KillSwitchState
    safe_mode: SafeMode
    eligible_for_money: bool
    eligible_note: str


class Stage(Strict):
    id: str
    name: str
    status: Literal["ok", "warn", "fail", "idle"]
    summary: str


class Agent(Strict):
    id: str
    name: str
    lane: Literal["supervisor", "data", "research", "validation", "risk", "monitor", "report", "planned"]
    kind: Literal["code", "llm", "code+llm"]
    role: str
    status: AgentStatus
    summary: str
    rule_id: str | None
    gate_status: GateStatus | None
    accuracy: float | None = Field(ge=0, le=1)
    control: bool


class Hist(Strict):
    bin_edges: list[float]
    counts: list[int]


class RandomBaseline(Strict):
    runs: int
    p_value: float
    p_value_win_rate: float
    expectancy_mean: float | None
    expectancy_p95: float | None
    win_rate_mean: float | None
    win_rate_p95: float | None
    hist: Hist


class WindowMetrics(Strict):
    start: str | None
    end: str | None
    trades: int
    wins: int
    win_rate: float | None
    win_rate_ci: list[float] = Field(min_length=2, max_length=2)
    full_stop_rate: float | None
    breakeven_rate: float | None
    expectancy_r: float | None
    profit_factor: float | None
    max_drawdown_r: float
    avg_hold_bars: float | None
    equity_r: list[float]


class ScoredWindow(WindowMetrics):
    random: RandomBaseline


class Windows(Strict):
    development: WindowMetrics
    holdout: ScoredWindow
    recent: ScoredWindow


class GateCheck(Strict):
    name: str
    passed: bool
    value: str
    required: str


class Gate(Strict):
    status: GateStatus
    checks: list[GateCheck]
    reasons: list[str]


class Plan(Strict):
    sha256: str | None
    locked_at: str | None
    valid: bool
    reason: str | None
    params: dict[str, Any]


class Forward(Strict):
    trades: int
    target_min: int
    target_max: int
    note: str


class RiskAtMinLot(Strict):
    median_stop_points: float | None
    risk: float | None
    risk_pct: float | None
    ok: bool | None


class Research(Strict):
    rule_id: str
    name: str
    symbols: list[str]
    timeframe: str
    description: str
    demo_note: str
    control: bool
    plan: Plan
    signals: int
    windows: Windows
    gate: Gate
    stage: Literal["research", "shadow", "forward_test", "live_eligible", "blocked"]
    stage_note: str
    forward: Forward
    risk_at_min_lot: RiskAtMinLot


class Check(Strict):
    stage: Literal["data", "research", "validation", "risk", "monitor", "approvals", "bridge", "report"]
    agent_id: str
    subject: str
    name: str
    status: Literal["pass", "warn", "fail", "info"]
    detail: str


class Account(Strict):
    balance: float
    currency: str
    leverage: float


class Limits(Strict):
    risk_per_trade_pct: float
    max_open_risk_pct: float
    max_daily_loss_pct: float
    max_margin_use_pct: float
    max_positions_per_group: int


class Usage(Strict):
    open_risk_pct: float
    margin_use_pct: float
    daily_loss_pct: float
    open_positions: int


class GroupRow(Strict):
    id: str
    name: str
    members: dict[str, int]
    positions: int
    risk_pct: float
    limit_pct: float


class MinLotRow(Strict):
    symbol: str
    min_lot: float
    median_stop_points: float | None
    risk_at_min_lot: float | None
    risk_pct: float | None
    margin_at_min_lot: float | None
    ok: bool | None
    note: str | None


class Correlation(Strict):
    symbols: list[str]
    matrix: list[list[float | None]]
    window: str


class Risk(Strict):
    account: Account
    limits: Limits
    usage: Usage
    groups: list[GroupRow]
    min_lot: list[MinLotRow]
    correlation: Correlation


class Pending(Strict):
    id: str
    created_at: str
    kind: str
    summary: str
    diff: list[str]


class Decided(Strict):
    id: str
    decided_at: str
    decision: str
    summary: str


class Approvals(Strict):
    pending: list[Pending]
    history: list[Decided]


class Bridge(Strict):
    file: str
    written: int
    signals: list[dict[str, Any]]
    note: str


class Report(Strict):
    title: str
    generated_by: Literal["template", "claude"]
    markdown: str


class LogEntry(Strict):
    time: str
    agent_id: str
    level: Literal["info", "warn", "error"]
    msg: str


class State(Strict):
    meta: Meta
    pipeline: list[Stage]
    agents: list[Agent]
    research: list[Research]
    checks: list[Check]
    risk: Risk
    approvals: Approvals
    bridge: Bridge
    report: Report
    log: list[LogEntry]


def validate_state(state: dict) -> dict:
    return State.model_validate(state).model_dump(mode="json")
