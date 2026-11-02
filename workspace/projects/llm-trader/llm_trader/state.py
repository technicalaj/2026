from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AgentStatus = Literal["ok", "warn", "fail", "idle", "planned"]
GateStatus = Literal["qualified", "failed", "insufficient", "blocked"]
Lane = Literal["supervisor", "data", "research", "context", "validation", "risk", "monitor", "report", "planned"]


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
    eligible_for_money: Literal[False]
    eligible_note: str
    banners: list[str]
    trial_count: int = Field(ge=0)
    prior_trials: int = Field(ge=0)
    account_feed: bool
    guardian_connected: bool


class PicksToday(Strict):
    picks: list[dict[str, Any]]
    reason: str


class Stage(Strict):
    id: str
    name: str
    status: Literal["ok", "warn", "fail", "idle"]
    summary: str


class Agent(Strict):
    id: str
    name: str
    lane: Lane
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
    losses: int
    win_rate: float | None
    win_rate_ci: list[float] = Field(min_length=2, max_length=2)
    full_stop_rate: float | None
    breakeven_rate: float | None
    expectancy_r: float | None
    profit_factor: float | None
    max_drawdown_r: float
    avg_hold_bars: float | None
    equity_r: list[float]


class Split(Strict):
    trades: int
    win_rate: float | None
    expectancy_r: float | None


class Tercile(Strict):
    name: Literal["low", "mid", "high"]
    trades: int
    expectancy_r: float | None


class Extra(Strict):
    expectancy_ci: list[float | None] = Field(min_length=2, max_length=2)
    expectancy_1_5x_costs: float | None
    expectancy_2x_costs: float | None
    long: Split
    short: Split
    terciles: list[Tercile]
    stop_target_ratio: float | None
    holm_threshold: float | None
    trial_count: int = Field(ge=0)


class ScoredWindow(WindowMetrics):
    random: RandomBaseline
    extra: Extra


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
    kind: Literal["rule", "self_test"]
    self_test: bool
    expected: str | None
    self_test_ok: bool | None
    plan: Plan
    results_hidden: bool
    signals: int
    windows: Windows
    gate: Gate
    stage: Literal["research", "shadow", "forward_test", "live_eligible", "blocked"]
    stage_note: str
    forward: Forward
    risk_at_min_lot: RiskAtMinLot


class SelfTest(Strict):
    id: str
    name: str
    expected: str
    actual: str
    ok: bool | None
    detail: str


class TaggerAnswer(Strict):
    symbol: str
    event: str
    time: str
    verdicts: list[Literal["pause", "no pause"]]
    agreement: str
    pause: bool


class EventTagger(Strict):
    stage: Literal["research", "shadow", "qualified", "retired", "blocked"]
    measured: str
    samples: int = Field(ge=1)
    model: str
    note: str
    last: list[TaggerAnswer]


class RegimeRow(Strict):
    symbol: str
    vol_tercile: Literal[1, 2, 3]
    trend: Literal["up", "down", "flat"]


class Context(Strict):
    event_tagger: EventTagger
    regime: list[RegimeRow]


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
    source: Literal["placeholder", "local"]


class Blackouts(Strict):
    news_minutes: int
    major_news_minutes: int
    rollover: str
    friday_cutoff_utc: str
    calendar_max_age_hours: float


class Limits(Strict):
    risk_per_trade_pct: float
    risk_per_trade_cap_pct: float
    max_open_risk_pct: float
    max_cluster_risk_pct: float
    max_margin_use_pct: float
    daily_stop_pct: float
    weekly_stop_pct: float
    overall_kill_pct: float
    max_open_positions: int
    max_entries_per_day: int
    min_minutes_between_entries_per_symbol: int
    spread_skip_multiple: float
    pause_after_full_stops: int
    blackouts: Blackouts


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


class BalanceRow(Strict):
    symbol: str
    risk_at_min_lot: float | None
    risk_pct: float | None
    ok: bool | None
    note: str | None


class MinLotAtBalance(Strict):
    balance: float
    rows: list[BalanceRow]


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
    min_lot_balances: list[MinLotAtBalance]
    correlation: Correlation


class PowerRow(Strict):
    edge_r: float
    trades: int
    pass_rate: float = Field(ge=0, le=1)


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


class Advisory(Strict):
    id: str
    symbol: str
    action: Literal["pause"]
    reason: str
    issued_at: str
    expires_at: str


class Bridge(Strict):
    file: str
    heartbeat: str
    kill_flag: bool
    advisories: list[Advisory]
    note: str


class Report(Strict):
    title: str
    generated_by: Literal["template", "claude"]
    markdown: str


class LogEntry(Strict):
    time: str
    agent_id: str
    level: Literal["info", "warn", "error", "alert"]
    msg: str


class State(Strict):
    meta: Meta
    picks_today: PicksToday
    pipeline: list[Stage]
    agents: list[Agent]
    research: list[Research]
    self_tests: list[SelfTest]
    context: Context
    checks: list[Check]
    risk: Risk
    power: list[PowerRow] | None
    approvals: Approvals
    bridge: Bridge
    report: Report
    log: list[LogEntry]


def validate_state(state: dict) -> dict:
    return State.model_validate(state).model_dump(mode="json")
