from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from llm_trader import __version__, bridge
from llm_trader.agents import agent_defs, build_agents, build_pipeline, team
from llm_trader.agents.context import event_tagger, regimes, split_answers
from llm_trader.agents.research import research_item
from llm_trader.config import ROOT as CODE_ROOT, Paths, default_paths, load_settings, read_local_override, section, write_json, write_text
from llm_trader.data.loader import load_dataset
from llm_trader.data.symbols import MissingCostsError, base_symbol, resolve_spec
from llm_trader.data.synthetic import CONTROL_SYMBOL, make_demo_dataset
from llm_trader.eval.gate import gate_config
from llm_trader.eval.plans import evaluation_config
from llm_trader.eval.power import gate_power
from llm_trader.eval.run import evaluate_all
from llm_trader.fmt import plural
from llm_trader.llm import build_digest, record_spend, run_budget, supervisor_review
from llm_trader.models import RuleEvaluation, iso, utc
from llm_trader.report import build_report
from llm_trader.risk.approvals import Approvals
from llm_trader.risk.engine import Book, Group, RiskEngine, correlation_matrix
from llm_trader.risk.feasibility import min_lot_balances, min_lot_row, min_lot_rows
from llm_trader.risk.killswitch import KillSwitch, enforce_loss_stops
from llm_trader.risk.limits import Limits
from llm_trader.signals.registry import all_rules
from llm_trader.state import validate_state
from llm_trader.supervisor import checks as c
from llm_trader.supervisor.self_tests import build_self_tests
from llm_trader.supervisor.supervisor import (
    StageContext, assign_stage, data_eligibility, entry_decision, research_checks, self_test_verdict, supervisor_summary,
    validation_checks,
)

DEMO_DATA_NOTE = "Synthetic demo data: numbers show how the system works, not real performance."
DEMO_ELIGIBLE_NOTE = "Nothing is eligible for money: demo data is never eligible."
DEMO_PICKS = "No agent has qualified on your broker's data. Demo data is never eligible."
BROKER_PICKS = "No agent has qualified on your broker's data."
KILL_PICKS = "Kill switch is ON: no picks."
QUALIFIED_PICKS = ("{n} rule agent(s) qualified on your broker's data. v1 lists no picks: each first needs its own fixed-rule EA "
                   "and a {lo}-{hi} trade forward test at minimum lot.")
# v1 reads no live account and no EA reads kill.flag yet; the dashboard words its risk and kill-switch views from these.
ACCOUNT_FEED = False
GUARDIAN_CONNECTED = False


class RunLog:
    def __init__(self, now=None):
        self.fixed = now
        self.entries: list[dict] = []

    def add(self, agent_id: str, level: str, msg: str) -> None:
        when = self.fixed if self.fixed is not None else datetime.now(timezone.utc)
        self.entries.append({"time": iso(when), "agent_id": agent_id, "level": level, "msg": msg})

    def alert(self, agent_id: str, msg: str) -> None:
        self.add(agent_id, "alert", f"Would-be phone alert: {msg}")


@dataclass
class RunResult:
    state: dict
    dataset: dict
    evaluations: list[RuleEvaluation]
    source: object


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


def build_engine(settings: dict, limits: Limits, specs: dict) -> RiskEngine:
    groups = [Group(g.id, g.name, dict(g.members)) for g in section(settings, "correlation_groups")]
    return RiskEngine(limits, groups, specs)


def worst_stops(evaluations: list[RuleEvaluation]) -> dict[str, float]:
    out: dict[str, float] = {}
    # Self-tests are never traded, so their stops say nothing about what this account could trade.
    for e in evaluations:
        if e.self_test:
            continue
        for symbol, points in e.median_stop_points.items():
            if points is not None:
                out[symbol] = max(points, out.get(symbol, 0.0))
    return out


def rule_risk(e: RuleEvaluation, engine: RiskEngine, balance: float) -> tuple[dict, bool, str | None]:
    rows = [min_lot_row(s, engine.specs[s], e.median_stop_points.get(s), balance, engine.limits) for s in e.symbols if s in engine.specs]
    measured = [r for r in rows if r["risk_pct"] is not None]
    if not measured:
        return {"median_stop_points": None, "risk": None, "risk_pct": None, "ok": None}, False, "no trades to measure the stop"
    worst = max(measured, key=lambda r: r["risk_pct"])
    ok = all(r["ok"] for r in measured)
    note = next((f"{r['symbol']}: {r['note']}" for r in measured if not r["ok"]), None)
    return {"median_stop_points": worst["median_stop_points"], "risk": worst["risk_at_min_lot"], "risk_pct": worst["risk_pct"], "ok": ok}, ok, note


def build_research(evaluations: list[RuleEvaluation], dataset: dict, engine: RiskEngine, balance: float, safe_mode: bool,
                   kill_on: bool, risk_cfg) -> list[dict]:
    research = []
    for e in evaluations:
        eligible, reason = data_eligibility(e, dataset)
        risk_row, risk_ok, risk_note = rule_risk(e, engine, balance)
        ctx = StageContext(eligible, reason, not safe_mode, kill_on, risk_ok, risk_note, risk_cfg.forward_min_trades, risk_cfg.forward_max_trades)
        research.append(research_item(e, *assign_stage(e, ctx), risk_row))
    return research


def build_context(dataset: dict, settings: dict, clock: pd.Timestamp) -> dict:
    cfg = section(settings, "context")
    watched = [s for s in dataset if s != CONTROL_SYMBOL]
    return {
        "event_tagger": event_tagger(watched, clock.floor("h"), cfg.event_tagger),
        "regime": regimes({s: dataset[s][0] for s in watched}, cfg.regime),
    }


def data_note(dataset: dict, data_mode: str) -> str:
    if data_mode == "demo":
        return DEMO_DATA_NOTE
    real = [s for s, (_, p) in dataset.items() if p["source"] == "mt5_export"]
    other = [s for s, (_, p) in dataset.items() if p["source"] == "other"]
    note = f"Your broker's MT5 data: {plural(len(real), 'symbol')}. The CTRL-SYN self-test stays synthetic."
    if other:
        note += f" {', '.join(other)} did not come from an MT5 export and can never be eligible for money."
    return note


def eligible_note(data_mode: str, forward_min: int, forward_max: int) -> str:
    if data_mode == "demo":
        return DEMO_ELIGIBLE_NOTE
    return (f"Nothing is eligible for money in v1: a qualified rule first runs a {forward_min}-{forward_max} "
            "trade forward test at minimum lot as its own EA, then waits for your YES.")


def banners(data_mode: str, llm_mode: str, kill_on: bool, safe_on: bool) -> list[str]:
    out = ["SYNTHETIC DATA" if data_mode == "demo" else "NOT ELIGIBLE FOR MONEY"]
    if llm_mode == "offline":
        out.append("AI OFFLINE")
    out.append("NO TRADING")
    if kill_on:
        out.append("KILL SWITCH ON")
    if safe_on:
        out.append("SAFE MODE")
    return out


def picks_today(research: list[dict], data_mode: str, kill_on: bool, forward_min: int, forward_max: int) -> dict:
    if kill_on:
        return {"picks": [], "reason": KILL_PICKS}
    if data_mode == "demo":
        return {"picks": [], "reason": DEMO_PICKS}
    qualified = [r for r in research if r["gate"]["status"] == "qualified" and not r["self_test"]]
    if not qualified:
        return {"picks": [], "reason": BROKER_PICKS}
    return {"picks": [], "reason": QUALIFIED_PICKS.format(n=len(qualified), lo=forward_min, hi=forward_max)}


def trial_counts(evaluations: list[RuleEvaluation], gate_cfg: dict) -> tuple[int, int]:
    prior = int(gate_cfg.get("prior_trials") or 0)
    counted = max((int(getattr(e, "trial_count", 0) or 0) for e in evaluations), default=0)
    return (counted or prior + len(evaluations)), prior


def power_table(settings: dict, gate_cfg: dict) -> list[dict]:
    ev = evaluation_config(settings)
    return gate_power(runs=ev["random_runs"], max_p=gate_cfg["max_p_value"], seed=ev["seed"])


def risk_checks(engine: RiskEngine, usage: dict, min_lot: list[dict], correlation: dict, evaluations: list[RuleEvaluation], risk_cfg) -> list[dict]:
    limits = engine.limits.to_dict()
    return [
        c.portfolio_check(usage, limits, ACCOUNT_FEED),
        *c.min_lot_checks(min_lot, limits["risk_per_trade_cap_pct"]),
        *c.group_checks(engine.groups, limits["max_cluster_risk_pct"]),
        *c.ungrouped_correlation_checks(engine.groups, correlation, risk_cfg.high_correlation),
        *c.overlap_checks(evaluations, engine.groups, correlation, risk_cfg.high_correlation),
    ]


def team_statuses(state: dict, evaluations: list[RuleEvaluation], dataset: dict, parity: dict | None, loss_stops: list) -> dict:
    meta, risk, context = state["meta"], state["risk"], state["context"]
    kill = meta["kill_switch"]
    return {
        "data": team.data_status(meta["data_mode"], state["checks"], len(dataset), parity),
        "research": team.research_status(evaluations),
        "event_tagger": team.tagger_status(context["event_tagger"]),
        "regime": team.regime_status(context["regime"]),
        "validation": team.validation_status(evaluations, meta["accuracy_bar"]),
        "risk": team.risk_status(kill["on"], risk["usage"], risk["limits"], risk["min_lot"], meta["account_feed"]),
        "bridge": team.bridge_status(len(state["bridge"]["advisories"]), meta["data_mode"], kill["on"]),
        "monitor": team.monitor_status(state["research"], kill, loss_stops),
        "report": team.report_status(meta["llm_mode"]),
        "supervisor": supervisor_summary(evaluations, state["checks"], state["self_tests"]),
    }


def log_context(log: RunLog, context: dict) -> None:
    tagger = context["event_tagger"]
    for row in tagger["last"]:
        if row["pause"]:
            log.add("event_tagger", "info", f"Shadow only, not sent: would pause {row['symbol']} for {row['event']} ({row['agreement']} agree).")
        elif len(set(row["verdicts"])) > 1:
            log.add("event_tagger", "info", f"No opinion on {row['symbol']} ({row['agreement']} agree on {row['event']}): no pause.")
    trends = ", ".join(f"{r['symbol']} vol {r['vol_tercile']}/3 {r['trend']}" for r in context["regime"])
    log.add("regime", "info", f"Regimes: {trends or 'not enough data'}.")


STAGE_WORDS = {"research": "stays in research", "shadow": "shadow test", "forward_test": "forward test",
               "live_eligible": "eligible for money", "blocked": "blocked"}
DECISION_WORDS = {"block": "blocked", "pause": "paused", "allow": "allowed"}
WHY_WORDS = {"kill_switch": "the kill switch is on", "not_qualified": "no agent has qualified yet", "data_red": "a data problem",
             "daily_stop": "the daily loss stop", "weekly_stop": "the weekly loss stop", "overall_kill": "the overall loss stop"}


def log_decisions(log: RunLog, research: list[dict], kill_on: bool, loss_stops: list, data_red: bool) -> None:
    for r in research:
        log.add("supervisor", "info", f"Decision: {r['name']}: {STAGE_WORDS.get(r['stage'], r['stage'])}. {r['stage_note']}")
    decision = entry_decision(kill_switch_on=kill_on, loss_stops=[code for code, _ in loss_stops],
                              qualified=any(r["stage"] == "forward_test" for r in research), data_red=data_red, risk_rules=[])
    why = ", ".join(WHY_WORDS.get(w, w.replace("_", " ")) for w in decision["why"]) or "all clear"
    log.add("supervisor", "info", f"New entries from agents: {DECISION_WORDS.get(decision['decision'], decision['decision'])} ({why}). "
                                  "Your own EAs carry on under their code rules and the Guardian.")


def run(data=None, use_llm: bool = False, paths: Paths | None = None, **kwargs) -> dict:
    return execute(data, use_llm, paths, **kwargs).state


def execute(data=None, use_llm: bool = False, paths: Paths | None = None, *, now=None, dataset=None, evaluations=None, llm_client=None) -> RunResult:
    started = time.perf_counter()
    paths = paths or default_paths()
    clock = utc(now) if now is not None else pd.Timestamp(datetime.now(timezone.utc))
    generated_at = iso(clock)
    log = RunLog(clock if now is not None else None)
    settings = load_settings(paths)
    gate_cfg = gate_config(settings.get("gate"))
    risk_cfg = section(settings, "risk")
    limits = Limits.from_settings(risk_cfg)
    account = section(settings, "account")
    source = resolve_source(data, settings, paths)
    data_mode = "demo" if source == "demo" else "mt5"
    log.add("supervisor", "info", f"Run started on {'demo' if data_mode == 'demo' else 'MT5'} data.")
    local_account, ignored = read_local_override(paths)
    account_source = "local" if isinstance(local_account, dict) and "balance" in local_account else "placeholder"
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
        evaluations = evaluate_all(dataset, settings, paths.plans_dir, trials_path=paths.trials_file)
    for e in evaluations:
        log.add("research", "info", f"{e.name}: {e.signals:,} signals on {', '.join(e.symbols)}.")
        log.add("validation", "info" if e.gate.status == "qualified" or self_test_verdict(e) else "warn",
                f"{e.name}: {e.gate.status}. {e.gate.reasons[0] if e.gate.reasons else ''}".strip())

    switch = KillSwitch.at(paths)
    approvals = Approvals(paths).scan(clock)
    engine = build_engine(settings, limits, specs)
    book = Book(equity=account.balance, peak_equity=account.balance)
    loss_stops = enforce_loss_stops(switch, book, limits, clock)
    for _, message in loss_stops:
        log.alert("monitor", message)
    switch.sync_flag()
    kill = switch.state()
    kill_flag = switch.flag_set()
    if kill["on"]:
        log.alert("monitor", f"Kill switch is ON: {kill['reason']}")
    usage = engine.usage(book)
    stops = worst_stops(evaluations)
    traded = {s: spec for s, spec in specs.items() if s != CONTROL_SYMBOL}
    min_lot = min_lot_rows(traded, stops, account.balance, limits)
    for row in min_lot:
        if row["ok"] is False:
            log.add("risk", "warn", f"{row['symbol']}: {row['note']}")
    correlation = correlation_matrix({s: df for s, (df, _) in dataset.items()}, risk_cfg.correlation_days)
    research = build_research(evaluations, dataset, engine, account.balance, approvals.safe_mode, kill["on"], risk_cfg)
    context = build_context(dataset, settings, clock)
    log_context(log, context)

    # Only QUALIFIED pause agents may add advisories; the event tagger is in shadow, so v1 writes none.
    payload = bridge.payload(clock, kill["on"], [])
    bridge.write(paths.bridge_dir, payload)
    bridge_state = bridge.state(payload, paths.rel(paths.bridge_file), kill_flag, data_mode)
    log.add("risk", "info", f"Bridge: {len(payload['advisories'])} advisories. {bridge_state['note']}")
    if approvals.safe_mode:
        log.alert("supervisor", f"Safe mode: {approvals.reason}")

    checks = data_rows + research_checks(evaluations, gate_cfg) + validation_checks(evaluations, gate_cfg)
    checks += [c.check("research", "research", "Costs", c.NAME_COSTS, "warn", msg) for msg in missing_costs]
    checks += risk_checks(engine, usage, min_lot, correlation, evaluations, risk_cfg)
    checks += [
        c.kill_switch_check(kill, kill_flag), *c.loss_stop_checks(loss_stops, limits.to_dict()),
        c.tagger_check(context["event_tagger"], split_answers(context["event_tagger"])),
        c.forward_check(research, risk_cfg.forward_min_trades, risk_cfg.forward_max_trades),
        c.approvals_check(approvals, len(evaluations)), c.bridge_check(bridge_state),
    ]
    self_tests = build_self_tests(research, context["event_tagger"], CODE_ROOT, data_mode, set(dataset))
    for t in self_tests:
        if t["ok"] is False:
            log.alert("supervisor", f"Self-test failed: {t['name']} ({t['actual']}). No result can be trusted until it is fixed.")
    trial_count, prior = trial_counts(evaluations, gate_cfg)
    state = {
        "meta": {
            "app": "Superagentic", "version": __version__, "generated_at": generated_at, "data_mode": data_mode,
            "data_note": data_note(dataset, data_mode), "llm_mode": "offline", "llm_note": "",
            "accuracy_bar": gate_cfg["accuracy_bar"], "kill_switch": kill,
            "safe_mode": {"on": approvals.safe_mode, "reason": approvals.reason}, "eligible_for_money": False,
            "eligible_note": eligible_note(data_mode, risk_cfg.forward_min_trades, risk_cfg.forward_max_trades),
            "banners": [], "trial_count": trial_count, "prior_trials": prior,
            "account_feed": ACCOUNT_FEED, "guardian_connected": GUARDIAN_CONNECTED,
        },
        "picks_today": picks_today(research, data_mode, kill["on"], risk_cfg.forward_min_trades, risk_cfg.forward_max_trades),
        "pipeline": [],
        "agents": [],
        "research": research,
        "self_tests": self_tests,
        "context": context,
        "checks": checks,
        "risk": {
            "account": {"balance": float(account.balance), "currency": account.currency, "leverage": float(account.leverage),
                        "source": account_source},
            "limits": limits.to_dict(), "usage": usage, "groups": engine.group_rows(book), "min_lot": min_lot,
            "min_lot_balances": min_lot_balances(traded, stops, limits), "correlation": correlation,
        },
        "power": power_table(settings, gate_cfg),
        "approvals": approvals.view(),
        "bridge": bridge_state,
        "report": {},
        "log": [],
    }

    llm_cfg = section(settings, "llm")
    day = generated_at[:10]
    llm = supervisor_review(build_digest(state), use_llm, llm_client, llm_cfg, run_budget(llm_cfg, paths.llm_spend_file, day))
    record_spend(paths.llm_spend_file, day, llm.cost_usd)
    state["meta"].update(llm_mode=llm.mode, llm_note=llm.note, banners=banners(data_mode, llm.mode, kill["on"], approvals.safe_mode))
    checks.append(c.report_check(llm.mode, llm.note))
    log.add("report", "info", "Claude reviewed the run." if llm.review else llm.note)

    statuses = team_statuses(state, evaluations, dataset, parity, loss_stops)
    defs = agent_defs(all_rules(), gate_cfg["accuracy_bar"], risk_cfg.forward_min_trades, risk_cfg.forward_max_trades)
    state["agents"] = build_agents(defs, evaluations, statuses, gate_cfg["accuracy_bar"], gate_cfg["min_trades_holdout"])
    state["pipeline"] = build_pipeline(statuses, gate_cfg["accuracy_bar"])
    log_decisions(log, research, kill["on"], loss_stops, any(x["status"] == "fail" and x["stage"] == "data" for x in checks))
    qualified = sum(1 for e in evaluations if e.gate.status == "qualified" and not e.self_test)
    log.add("supervisor", "info", f"Run finished in {time.perf_counter() - started:.1f} s: {qualified} of "
                                  f"{sum(1 for e in evaluations if not e.self_test)} rule agents qualified.")
    log.alert("report", f"Morning report ready. Picks today: {len(state['picks_today']['picks'])}. {state['picks_today']['reason']}")
    state["log"] = log.entries
    state["report"] = build_report(state, llm.review, gate_cfg["max_p_value"])

    state = validate_state(state)
    write_json(paths.state_file, state)
    write_text(paths.report_file, state["report"]["markdown"])
    write_json(paths.last_run_file, {"data": "demo" if source == "demo" else str(source), "use_llm": use_llm, "finished_at": generated_at})
    return RunResult(state, dataset, evaluations, source)
