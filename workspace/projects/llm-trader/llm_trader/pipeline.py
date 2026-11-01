from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from llm_trader import __version__, bridge
from llm_trader.agents import agent_defs, build_agents, build_pipeline
from llm_trader.agents import team
from llm_trader.config import Paths, default_paths, load_settings, read_local_override, section, write_json, write_text
from llm_trader.data.loader import load_dataset
from llm_trader.data.symbols import MissingCostsError, base_symbol, resolve_spec
from llm_trader.data.synthetic import CONTROL_SYMBOL, make_demo_dataset
from llm_trader.eval.gate import gate_config
from llm_trader.eval.run import evaluate_all
from llm_trader.llm import build_digest, supervisor_review
from llm_trader.models import RuleEvaluation, iso, timeframe_delta, utc
from llm_trader.report import build_report
from llm_trader.risk.approvals import Approvals
from llm_trader.risk.engine import Account, Group, Limits, RiskEngine, correlation_matrix
from llm_trader.risk.killswitch import KillSwitch, enforce_daily_loss
from llm_trader.signals.registry import all_rules, get_rule
from llm_trader.state import validate_state
from llm_trader.supervisor import checks as c
from llm_trader.supervisor.supervisor import (
    StageContext, assign_stage, data_eligibility, research_checks, supervisor_summary, validation_checks,
)

DEMO_DATA_NOTE = "Synthetic demo data: numbers show how the system works, not real performance."
DEMO_ELIGIBLE_NOTE = "Nothing is eligible for money: demo data is never eligible."


class RunLog:
    def __init__(self, now=None):
        self.fixed = now
        self.entries: list[dict] = []

    def add(self, agent_id: str, level: str, msg: str) -> None:
        when = self.fixed if self.fixed is not None else datetime.now(timezone.utc)
        self.entries.append({"time": iso(when), "agent_id": agent_id, "level": level, "msg": msg})


def resolve_source(data, settings: dict, paths: Paths):
    cfg = section(settings, "data")
    if data is None and cfg.mode == "demo" or str(data) == "demo":
        return "demo"
    if data is None or str(data) == "mt5":
        folder = Path(cfg.mt5_dir)
        return folder if folder.is_absolute() else paths.root / folder
    return Path(data)


def last_run(paths: Paths) -> dict:
    try:
        data = json.loads(paths.last_run_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def apply_symbol_aliases(dataset: dict) -> tuple[dict, list[str]]:
    wanted = {s for rule in all_rules() for s in rule.symbols}
    out, notes = {}, []
    for name, pair in dataset.items():
        base = base_symbol(name)
        if name not in wanted and base in wanted and base not in dataset and base not in out:
            out[base] = pair
            notes.append(f"Using {name} as {base} (broker symbol suffix).")
        else:
            out[name] = pair
    return out, notes


def aligned_control(dataset: dict, seed: int) -> tuple[pd.DataFrame, dict]:
    df, prov = make_demo_dataset(seed)[CONTROL_SYMBOL]
    last = max(frame.index[-1] for frame, _ in dataset.values())
    # Whole weeks keep the weekend closures and the planted daily pattern exactly where they were.
    weeks = math.floor((last - df.index[-1]) / pd.Timedelta(weeks=1))
    if weeks:
        df = df.copy()
        df.index = df.index + pd.Timedelta(weeks=weeks)
        prov = {**prov, "first": iso(df.index[0]), "last": iso(df.index[-1]), "shifted_weeks": weeks}
    return df, prov


def load_data(source, settings: dict) -> tuple[dict, list[str]]:
    seed = section(settings, "data").demo_seed
    if source == "demo":
        return load_dataset("demo", seed=seed), []
    dataset, notes = apply_symbol_aliases(load_dataset(source))
    if CONTROL_SYMBOL not in dataset:
        dataset[CONTROL_SYMBOL] = aligned_control(dataset, seed)
        notes.append("Added the synthetic CTRL-SYN self-test so the gate keeps proving it can find a real pattern.")
    return dataset, notes


def resolve_specs(dataset: dict, settings: dict) -> tuple[dict, list[str]]:
    specs, missing = {}, []
    for symbol, (_, prov) in dataset.items():
        try:
            specs[symbol] = resolve_spec(symbol, prov, settings.get("costs"))
        except MissingCostsError as exc:
            missing.append(f"{exc}.")
    return specs, missing


def build_engine(settings: dict, specs: dict) -> RiskEngine:
    account = section(settings, "account")
    groups = [Group(g.id, g.name, dict(g.members)) for g in section(settings, "correlation_groups")]
    return RiskEngine(Account(account.balance, account.currency, account.leverage), Limits.from_settings(section(settings, "risk")), groups, specs)


def worst_stops(evaluations: list[RuleEvaluation]) -> dict[str, float]:
    out: dict[str, float] = {}
    for e in evaluations:
        for symbol, points in e.median_stop_points.items():
            if points is not None:
                out[symbol] = max(points, out.get(symbol, 0.0))
    return out


def rule_risk(e: RuleEvaluation, engine: RiskEngine) -> tuple[dict, bool, str | None]:
    rows = [engine.min_lot_row(s, e.median_stop_points.get(s)) for s in e.symbols if s in engine.specs]
    measured = [r for r in rows if r["risk_pct"] is not None]
    if not measured:
        return {"median_stop_points": None, "risk": None, "risk_pct": None, "ok": None}, False, "no trades to measure the stop"
    worst = max(measured, key=lambda r: r["risk_pct"])
    ok = all(r["ok"] for r in measured)
    note = next((f"{r['symbol']}: {r['note']}" for r in measured if not r["ok"]), None)
    return {"median_stop_points": worst["median_stop_points"], "risk": worst["risk_at_min_lot"], "risk_pct": worst["risk_pct"], "ok": ok}, ok, note


def research_entry(e: RuleEvaluation, stage: str, note: str, forward: dict, risk: dict) -> dict:
    return {
        "rule_id": e.rule_id, "name": e.name, "symbols": list(e.symbols), "timeframe": e.timeframe,
        "description": e.description, "demo_note": e.demo_note, "control": e.control, "plan": e.plan.to_dict(),
        "signals": e.signals, "windows": e.windows_dict(), "gate": e.gate.to_dict(),
        "stage": stage, "stage_note": note, "forward": forward, "risk_at_min_lot": risk,
    }


def bridge_candidates(evaluations: list[RuleEvaluation], research: list[dict], dataset: dict) -> list[bridge.Candidate]:
    out = []
    for e, entry in zip(evaluations, research):
        if entry["stage"] != "forward_test":
            continue
        rule = get_rule(e.rule_id)
        for symbol in e.symbols:
            df = dataset[symbol][0]
            latest = df.index[-1] + timeframe_delta(rule.timeframe)
            price = float(df["close"].iloc[-1])
            out += [bridge.Candidate(e.rule_id, e.plan.sha256, s, price, rule.timeframe) for s in rule.generate(df, symbol) if utc(s.time) == latest]
    return out


def data_note(dataset: dict, data_mode: str) -> str:
    if data_mode == "demo":
        return DEMO_DATA_NOTE
    real = [s for s, (_, p) in dataset.items() if p["source"] == "mt5_export"]
    other = [s for s, (_, p) in dataset.items() if p["source"] == "other"]
    note = f"Your broker's MT5 data: {len(real)} symbol(s). The CTRL-SYN self-test stays synthetic."
    if other:
        note += f" {', '.join(other)} did not come from an MT5 export and can never be eligible for money."
    return note


def eligible_note(data_mode: str, forward_min: int, forward_max: int) -> str:
    if data_mode == "demo":
        return DEMO_ELIGIBLE_NOTE
    return (f"Nothing is eligible for money in v1: a qualified agent first runs a {forward_min}-{forward_max} "
            "trade forward test at minimum lot, then waits for your YES.")


@dataclass
class RunResult:
    state: dict
    dataset: dict
    evaluations: list[RuleEvaluation]
    source: object


def run(data=None, use_llm: bool = False, paths: Paths | None = None, **kwargs) -> dict:
    return execute(data, use_llm, paths, **kwargs).state


def build_research(evaluations: list[RuleEvaluation], dataset: dict, engine: RiskEngine, safe_mode: bool, kill_on: bool, risk_cfg) -> list[dict]:
    research = []
    for e in evaluations:
        eligible, reason = data_eligibility(e, dataset)
        risk_row, risk_ok, risk_note = rule_risk(e, engine)
        ctx = StageContext(eligible, reason, not safe_mode, kill_on, risk_ok, risk_note, risk_cfg.forward_min_trades, risk_cfg.forward_max_trades)
        research.append(research_entry(e, *assign_stage(e, ctx), risk_row))
    return research


def risk_checks(engine: RiskEngine, usage: dict, min_lot: list[dict], correlation: dict, evaluations: list[RuleEvaluation], risk_cfg) -> list[dict]:
    limits = engine.limits.to_dict()
    return [
        c.portfolio_check(usage, limits),
        *c.min_lot_checks(min_lot, limits["risk_per_trade_pct"]),
        *c.group_checks(engine.groups, limits["max_positions_per_group"]),
        *c.ungrouped_correlation_checks(engine.groups, correlation, risk_cfg.high_correlation),
        *c.overlap_checks(evaluations, engine.groups, correlation, risk_cfg.high_correlation),
    ]


def team_statuses(state: dict, evaluations: list[RuleEvaluation], dataset: dict, parity: dict | None, output: bridge.BridgeOutput) -> dict:
    meta, risk = state["meta"], state["risk"]
    kill, safe = meta["kill_switch"], meta["safe_mode"]["on"]
    return {
        "data": team.data_status(meta["data_mode"], state["checks"], len(dataset), parity),
        "research": team.research_status(evaluations),
        "validation": team.validation_status(evaluations, meta["accuracy_bar"]),
        "risk": team.risk_status(kill["on"], risk["usage"], risk["limits"], risk["min_lot"]),
        "bridge": team.bridge_status(output.written, meta["data_mode"], kill["on"], safe),
        "monitor": team.monitor_status(state["research"], kill),
        "report": team.report_status(meta["llm_mode"]),
        "supervisor": supervisor_summary(evaluations, state["checks"]),
    }


def execute(data=None, use_llm: bool = False, paths: Paths | None = None, *, now=None, dataset=None, evaluations=None, llm_client=None) -> RunResult:
    started = time.perf_counter()
    paths = paths or default_paths()
    clock = utc(now) if now is not None else pd.Timestamp(datetime.now(timezone.utc))
    generated_at = iso(clock)
    log = RunLog(clock if now is not None else None)
    settings = load_settings(paths)
    gate_cfg = gate_config(settings.get("gate"))
    risk_cfg = section(settings, "risk")
    source = resolve_source(data, settings, paths)
    data_mode = "demo" if source == "demo" else "mt5"
    log.add("supervisor", "info", f"Run started on {'demo' if data_mode == 'demo' else 'MT5'} data.")
    _, ignored = read_local_override(paths)
    if ignored:
        log.add("supervisor", "warn", f"config/settings.local.json may only hold 'account'; ignored: {', '.join(ignored)}.")

    notes: list[str] = []
    if dataset is None:
        dataset, notes = load_data(source, settings)
    for note in notes:
        log.add("data", "info", note)
    log.add("data", "info", f"Loaded {len(dataset)} symbols ({'synthetic demo data' if data_mode == 'demo' else 'MT5 export'}).")
    specs, missing_costs = resolve_specs(dataset, settings)
    data_rows, parity = c.data_checks(dataset, specs, settings, data_mode, clock)
    if data_mode == "demo":
        log.add("data", "warn", "Data is synthetic: nothing can be eligible for money.")
    if parity:
        log.add("data", "info", f"Parity check: a TradingView-style copy differs on {parity['candles_differ']:.0%} of XAUUSD candles.")

    if evaluations is None:
        evaluations = evaluate_all(dataset, settings, paths.plans_dir)
    for e in evaluations:
        log.add("research", "info", f"{e.name}: {e.signals:,} signals on {', '.join(e.symbols)}.")
        log.add("validation", "info" if e.gate.status == "qualified" else "warn",
                f"{e.name}: {e.gate.status}. {e.gate.reasons[0] if e.gate.reasons else ''}".strip())

    switch = KillSwitch(paths.killswitch_file)
    approvals = Approvals(paths).scan(clock)
    engine = build_engine(settings, specs)
    positions: list = []
    usage = engine.usage(positions)
    if enforce_daily_loss(switch, usage["daily_loss_pct"], engine.limits.max_daily_loss_pct, clock):
        log.add("risk", "error", "Daily loss limit reached: the kill switch is ON.")
    kill = switch.state()
    stops = worst_stops(evaluations)
    min_lot = [engine.min_lot_row(s, stops.get(s)) for s in dataset if s in engine.specs]
    for row in min_lot:
        if row["ok"] is False:
            log.add("risk", "warn", f"{row['symbol']}: {row['note']}")
    correlation = correlation_matrix({s: df for s, (df, _) in dataset.items()}, risk_cfg.correlation_days)
    research = build_research(evaluations, dataset, engine, approvals.safe_mode, kill["on"], risk_cfg)

    output = bridge.build(
        generated_at=generated_at, data_mode=data_mode, kill_switch_on=kill["on"], safe_mode_on=approvals.safe_mode,
        candidates=bridge_candidates(evaluations, research, dataset), engine=engine, positions=positions, now=clock,
        forward_agents=sum(1 for r in research if r["stage"] == "forward_test"),
    )
    bridge.write(paths.bridge_file, output)
    for skipped in output.skipped:
        log.add("risk", "warn", f"Bridge skipped {skipped}")
    log.add("risk", "info", f"Bridge: {output.written} signal(s) written. {output.payload['note']}")
    if approvals.safe_mode:
        log.add("supervisor", "warn", f"Safe mode: {approvals.reason}")
    log.add("monitor", "warn" if kill["on"] else "info", f"Kill switch is ON: {kill['reason']}" if kill["on"] else "Kill switch is off.")

    checks = data_rows + research_checks(evaluations, gate_cfg) + validation_checks(evaluations, gate_cfg)
    checks += [c.check("research", "research", "Costs", c.NAME_COSTS, "warn", msg) for msg in missing_costs]
    checks += risk_checks(engine, usage, min_lot, correlation, evaluations, risk_cfg)
    checks += [
        c.kill_switch_check(kill), c.forward_check(research, risk_cfg.forward_min_trades, risk_cfg.forward_max_trades),
        c.approvals_check(approvals, len(evaluations)), c.bridge_check(output.payload["note"], output.written),
    ]
    state = {
        "meta": {
            "app": "Superagentic", "version": __version__, "generated_at": generated_at, "data_mode": data_mode,
            "data_note": data_note(dataset, data_mode), "llm_mode": "offline", "llm_note": "",
            "accuracy_bar": gate_cfg["accuracy_bar"], "kill_switch": kill,
            "safe_mode": {"on": approvals.safe_mode, "reason": approvals.reason}, "eligible_for_money": False,
            "eligible_note": eligible_note(data_mode, risk_cfg.forward_min_trades, risk_cfg.forward_max_trades),
        },
        "pipeline": [],
        "agents": [],
        "research": research,
        "checks": checks,
        "risk": {
            "account": engine.account.to_dict(), "limits": engine.limits.to_dict(), "usage": usage,
            "groups": engine.group_rows(positions), "min_lot": min_lot, "correlation": correlation,
        },
        "approvals": approvals.view(),
        "bridge": output.state(paths.rel(paths.bridge_file)),
        "report": {},
        "log": [],
    }

    llm = supervisor_review(build_digest(state), use_llm, llm_client, section(settings, "llm"))
    state["meta"].update(llm_mode=llm.mode, llm_note=llm.note)
    checks.append(c.report_check(llm.mode, llm.note))
    log.add("report", "info", "Claude reviewed the run." if llm.review else llm.note)

    statuses = team_statuses(state, evaluations, dataset, parity, output)
    defs = agent_defs(all_rules(), gate_cfg["accuracy_bar"], risk_cfg.forward_min_trades, risk_cfg.forward_max_trades)
    state["agents"] = build_agents(defs, evaluations, statuses, gate_cfg["accuracy_bar"], gate_cfg["min_trades_holdout"])
    state["pipeline"] = build_pipeline(statuses, gate_cfg["accuracy_bar"])
    qualified = sum(1 for e in evaluations if e.gate.status == "qualified")
    log.add("supervisor", "info", f"Run finished in {time.perf_counter() - started:.1f} s: {qualified} of {len(evaluations)} agents qualified.")
    state["log"] = log.entries
    state["report"] = build_report(state, llm.review, gate_cfg["max_p_value"])

    state = validate_state(state)
    write_json(paths.state_file, state)
    write_text(paths.report_file, state["report"]["markdown"])
    write_json(paths.last_run_file, {"data": "demo" if source == "demo" else str(source), "use_llm": use_llm, "finished_at": generated_at})
    return RunResult(state, dataset, evaluations, source)
