from __future__ import annotations

import zlib

import numpy as np
import pandas as pd

from llm_trader.costs import cost_model_from_settings
from llm_trader.data.symbols import MissingCostsError, SymbolSpec, resolve_spec
from llm_trader.eval.backtest import SignalRejected, simulate
from llm_trader.eval.gate import evaluate_gate, gate_config
from llm_trader.eval.leakcheck import leak_check
from llm_trader.eval.metrics import window_metrics, window_trades
from llm_trader.eval.plans import evaluation_config, load_plan, plan_settings, verify_plan
from llm_trader.eval.random_baseline import random_baseline
from llm_trader.eval.windows import split_windows
from llm_trader.models import TESTED_WINDOWS, WINDOW_NAMES, LeakCheck, PlanInfo, RuleEvaluation, Trade, utc
from llm_trader.signals.base import SignalRule
from llm_trader.signals.registry import all_rules

Dataset = dict[str, tuple[pd.DataFrame, dict]]


def stable_seed(base: int, *parts: str) -> int:
    return zlib.crc32("|".join([str(base), *parts]).encode())


def dataset_bounds(dataset: Dataset, settings: dict | None) -> dict:
    if not dataset:
        raise ValueError("Dataset is empty")
    windows = plan_settings(settings)["windows"]
    first = min(df.index[0] for df, _ in dataset.values())
    last = max(df.index[-1] for df, _ in dataset.values())
    bounds = split_windows(last, windows["holdout_months"], windows["recent_months"])
    bounds["development"] = (utc(first), bounds["development"][1])
    return bounds


def _plan_info(rule: SignalRule, settings: dict, plans_dir) -> PlanInfo:
    try:
        locked = load_plan(plans_dir, rule.rule_id)
    except ValueError as exc:
        return PlanInfo(None, None, False, str(exc), dict(rule.params))
    ok, reason = verify_plan(locked, rule, settings)
    locked = locked or {}
    return PlanInfo(locked.get("sha256"), locked.get("locked_at"), ok, reason, dict(rule.params))


def _plan_note(plan: PlanInfo) -> str:
    if plan.valid:
        return f"Locked {(plan.locked_at or '')[:10]} · {(plan.sha256 or '')[:8]}"
    return plan.reason or "Missing or changed after locking"


def _median_stop_points(trades: list[Trade], specs: dict[str, SymbolSpec]) -> dict[str, float | None]:
    out = {}
    for symbol, spec in specs.items():
        risks = [t.risk_price for t in trades if t.symbol == symbol]
        out[symbol] = float(np.median(risks) / spec.point) if risks else None
    return out


def _combine_leaks(results: list[tuple[bool, str]]) -> LeakCheck:
    if not results:
        return LeakCheck(True, "Not run: no data for this rule's symbols.")
    failed = [detail for ok, detail in results if not ok]
    return LeakCheck(not failed, " ".join(failed or [detail for _, detail in results]))


def evaluate_rule(rule: SignalRule, dataset: Dataset, settings: dict, plans_dir, bounds: dict | None = None) -> RuleEvaluation:
    settings = settings or {}
    ev = evaluation_config(settings)
    gate_cfg = gate_config(settings.get("gate"))
    bounds = bounds or dataset_bounds(dataset, settings)
    recent_months = plan_settings(settings)["windows"]["recent_months"]
    hard: list[str] = []

    plan = _plan_info(rule, settings, plans_dir)
    if not plan.valid:
        hard.append(f"Test plan: {plan.reason}")
    missing = [s for s in rule.symbols if s not in dataset]
    if missing:
        hard.append(f"No data for {', '.join(missing)}; the locked plan needs every listed symbol.")
    specs: dict[str, SymbolSpec] = {}
    for symbol in rule.symbols:
        if symbol in dataset:
            try:
                specs[symbol] = resolve_spec(symbol, dataset[symbol][1], settings.get("costs"))
            except MissingCostsError as exc:
                hard.append(f"{exc}.")

    cost_model = cost_model_from_settings(settings)
    trades: list[Trade] = []
    counts: dict[str, int] = {}
    leaks = []
    for symbol, spec in specs.items():
        df = dataset[symbol][0]
        signals = rule.generate(df, symbol)
        counts[symbol] = len(signals)
        try:
            trades += simulate(df, signals, spec, cost_model, ev["win_epsilon_r"])
        except SignalRejected as exc:
            hard.append(f"Rejected signal: {exc}.")
        leaks.append(leak_check(rule, df, symbol, ev["leak_cuts"], stable_seed(ev["seed"], rule.rule_id, symbol)))
    leak = _combine_leaks(leaks)
    if not leak.passed:
        hard.append(leak.detail)

    frames = {symbol: dataset[symbol][0] for symbol in specs}
    windows = {name: window_metrics(trades, *bounds[name]) for name in WINDOW_NAMES}
    random = {
        name: random_baseline(
            frames, trades, bounds[name], specs, cost_model, runs=ev["random_runs"],
            seed=stable_seed(ev["seed"], rule.rule_id, name), win_epsilon_r=ev["win_epsilon_r"],
        )
        for name in TESTED_WINDOWS
    }
    gate = evaluate_gate(
        windows["holdout"], random["holdout"], windows["recent"], random["recent"], gate_cfg, hard,
        plan_ok=plan.valid, plan_note=_plan_note(plan), recent_label=f"last {recent_months} months",
    )
    return RuleEvaluation(
        rule_id=rule.rule_id,
        name=rule.name,
        version=rule.version,
        symbols=list(rule.symbols),
        timeframe=rule.timeframe,
        description=rule.description,
        demo_note=rule.demo_note,
        control=rule.control,
        signals=sum(counts.values()),
        signals_by_symbol=counts,
        trades={name: window_trades(trades, *bounds[name]) for name in WINDOW_NAMES},
        windows=windows,
        random=random,
        leak_check=leak,
        plan=plan,
        median_stop_points=_median_stop_points(trades, specs),
        gate=gate,
        hard_failures=hard,
    )


def evaluate_all(dataset: Dataset, settings: dict, plans_dir) -> list[RuleEvaluation]:
    bounds = dataset_bounds(dataset, settings)
    return [evaluate_rule(rule, dataset, settings, plans_dir, bounds) for rule in all_rules()]
