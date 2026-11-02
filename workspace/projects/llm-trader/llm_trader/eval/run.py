from __future__ import annotations

import dataclasses
import zlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

from llm_trader.costs import cost_model_from_settings
from llm_trader.data.symbols import MissingCostsError, SymbolSpec, resolve_spec
from llm_trader.eval.backtest import SignalRejected, simulate
from llm_trader.eval.gate import TOO_GOOD_REASON, evaluate_gate, gate_config
from llm_trader.eval.leakcheck import leak_check
from llm_trader.eval.metrics import window_metrics, window_trades
from llm_trader.eval.plans import evaluation_config, load_plan, make_plan, plan_settings, trial_hash, verify_plan
from llm_trader.eval.random_baseline import empty_baseline, random_baseline
from llm_trader.eval.robustness import DISPLAY_COSTS, STRESS_COSTS, volatility_cuts, window_extra
from llm_trader.eval.trials import (
    TrialEntry, data_id, dataset_fingerprint, default_trials_path, first_test_before_lock, holm_decisions, open_trials, tally_trials,
)
from llm_trader.eval.windows import split_windows
from llm_trader.models import (
    TESTED_WINDOWS, WINDOW_NAMES, HolmDecision, Labels, LeakCheck, PlanInfo, RandomBaseline, RuleEvaluation, Trade,
    WindowExtra, WindowMetrics, utc,
)
from llm_trader.signals.base import SignalRule
from llm_trader.signals.registry import all_rules

Dataset = dict[str, tuple[pd.DataFrame, dict]]
HIDDEN_NOTE = ("Its never-seen results stay hidden until the plan is locked properly (needs your YES), so nobody can look "
               "first and lock afterwards.")


@dataclass
class RawEvaluation:
    rule: SignalRule
    plan: PlanInfo
    plan_note: str
    tested_sha256: str
    results_hidden: bool
    hard_failures: list[str]
    signals_by_symbol: dict[str, int]
    trades: list[Trade]
    windows: dict[str, WindowMetrics]
    random: dict[str, RandomBaseline]
    extra: dict[str, WindowExtra]
    leak: LeakCheck
    median_stop_points: dict[str, float | None]

    @property
    def holdout_p(self) -> float:
        rb = self.random["holdout"]
        return rb.p_value if rb.runs else 1.0


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


def _plan_info(rule: SignalRule, settings: dict, plans_dir) -> tuple[PlanInfo, dict]:
    try:
        locked = load_plan(plans_dir, rule.rule_id)
    except ValueError as exc:
        return PlanInfo(None, None, False, str(exc), dict(rule.params)), {}
    ok, reason = verify_plan(locked, rule, settings)
    locked = locked or {}
    return PlanInfo(locked.get("sha256"), locked.get("locked_at"), ok, reason, dict(rule.params)), locked


def _tested_hash(rule: SignalRule, settings: dict, plan: PlanInfo) -> str:
    # The variant actually tested, even when it differs from the locked file: every variant counts as a try.
    try:
        return trial_hash(make_plan(rule, settings))
    except MissingCostsError:
        return plan.sha256 or ""


def _day(ts) -> str:
    return utc(ts).strftime("%Y-%m-%d")


def _minute(ts) -> str:
    return utc(ts).strftime("%Y-%m-%d %H:%M UTC")


def data_kind(rule: SignalRule, dataset: Dataset) -> str:
    present = [s for s in rule.symbols if s in dataset] or list(dataset)
    return "synthetic" if {dataset[s][1].get("source") for s in present} == {"synthetic"} else "real"


def lock_timing(rule: SignalRule, plan: PlanInfo, unstudied_since: str | None, kind: str, holdout) -> tuple[bool, str]:
    if not plan.valid:
        return False, plan.reason or "Missing or changed after locking"
    if not plan.locked_at:
        return False, "The plan file has no lock time, so it cannot show it was locked before testing. Lock it again (needs your YES)."
    start, end = holdout
    head = f"Locked {_day(plan.locked_at)} · {(plan.sha256 or '')[:8]} · origin {rule.origin}"
    months = f"never-seen months {_day(start)} to {_day(end)}"
    if kind == "synthetic":
        return True, f"{head}. The {months} are synthetic: a demo exception (generated before the lock)"
    if rule.self_test:
        return True, f"{head}. The {months} began earlier, but a self-test only checks the harness and is never traded"
    if utc(plan.locked_at) <= utc(start):
        return True, f"{head}, before the {months} began"
    if unstudied_since and utc(unstudied_since) <= utc(start):
        return True, f"{head}. You declared the months from {_day(unstudied_since)} unstudied (with YES), which covers the {months}"
    return False, (
        f"Locked {_day(plan.locked_at)}, after its never-seen months began ({_day(start)}), so they may already have been "
        f"studied. Lock before the months you test, or, only if you have not studied them, declare that with: "
        f"python -m llm_trader lock {rule.rule_id} --unstudied-since {_day(start)} --yes"
    )


def tested_early_note(first_tested: str, plan: PlanInfo) -> str:
    return (f"Its never-seen months were already tested {_minute(first_tested)}, before this plan was locked "
            f"({_minute(plan.locked_at)}). Looking first and locking afterwards does not count: lock a new version and test it "
            "on months it has never seen.")


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


def raw_evaluation(rule: SignalRule, dataset: Dataset, settings: dict, plans_dir, bounds: dict) -> RawEvaluation:
    ev = evaluation_config(settings)
    labels = Labels.from_gate(gate_config(settings.get("gate")))
    hard: list[str] = []

    plan, locked = _plan_info(rule, settings, plans_dir)
    tested = _tested_hash(rule, settings, plan)
    timing_ok, plan_note = lock_timing(rule, plan, locked.get("unstudied_since"), data_kind(rule, dataset), bounds["holdout"])
    if not timing_ok:
        plan = dataclasses.replace(plan, valid=False, reason=plan_note)
        hard.append(f"Test plan: {plan_note}")
    hidden = not timing_ok
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
    stressed: list[Trade] = []
    display: list[Trade] = []
    counts: dict[str, int] = {}
    leaks = []
    for symbol, spec in specs.items():
        df = dataset[symbol][0]
        signals = rule.generate(df, symbol)
        counts[symbol] = len(signals)
        try:
            trades += simulate(df, signals, spec, cost_model, labels)
            stressed += simulate(df, signals, spec, cost_model.scaled(STRESS_COSTS), labels)
            display += simulate(df, signals, spec, cost_model.scaled(DISPLAY_COSTS), labels)
        except SignalRejected as exc:
            hard.append(f"Rejected signal: {exc}.")
        leaks.append(leak_check(rule, df, symbol, ev["leak_cuts"], stable_seed(ev["seed"], rule.rule_id, symbol)))
    leak = _combine_leaks(leaks)
    if not leak.passed:
        hard.append(leak.detail)

    frames = {symbol: dataset[symbol][0] for symbol in specs}
    shown = window_trades(trades, *bounds["development"]) if hidden else trades
    windows = {name: window_metrics(shown, *bounds[name]) for name in WINDOW_NAMES}
    random = {
        name: empty_baseline() if hidden else random_baseline(
            frames, trades, bounds[name], specs, cost_model, runs=ev["random_runs"],
            seed=stable_seed(ev["seed"], rule.rule_id, name), labels=labels,
        )
        for name in TESTED_WINDOWS
    }
    cuts = volatility_cuts(window_trades(trades, *bounds["development"]), frames, bounds["development"])
    extra = {
        name: window_extra([], [], [], cuts) if hidden else window_extra(
            window_trades(trades, *bounds[name]),
            [t.r for t in window_trades(stressed, *bounds[name])],
            [t.r for t in window_trades(display, *bounds[name])],
            cuts,
        )
        for name in TESTED_WINDOWS
    }
    return RawEvaluation(
        rule=rule,
        plan=plan,
        plan_note=plan_note,
        tested_sha256=tested,
        results_hidden=hidden,
        hard_failures=hard,
        signals_by_symbol=counts,
        trades=shown,
        windows=windows,
        random=random,
        extra=extra,
        leak=leak,
        median_stop_points=_median_stop_points(trades, specs),
    )


def finish_evaluation(
    raw: RawEvaluation, settings: dict, bounds: dict, holm: HolmDecision, trial_count: int, trials_note: str | None = None,
    first_tested: str | None = None,
) -> RuleEvaluation:
    gate_cfg = gate_config(settings.get("gate"))
    recent_months = plan_settings(settings)["windows"]["recent_months"]
    rule = raw.rule
    plan, plan_note, hard = raw.plan, raw.plan_note, list(raw.hard_failures)
    if plan.valid and first_tested:
        plan_note = tested_early_note(first_tested, plan)
        plan = dataclasses.replace(plan, valid=False, reason=plan_note)
        hard.append(f"Test plan: {plan_note}")
    extra = {
        "holdout": dataclasses.replace(raw.extra["holdout"], holm_threshold=holm.threshold, trial_count=trial_count),
        "recent": dataclasses.replace(raw.extra["recent"], holm_threshold=None, trial_count=trial_count),
    }
    gate = evaluate_gate(
        raw.windows["holdout"], raw.random["holdout"], raw.windows["recent"], raw.random["recent"], gate_cfg, hard,
        holdout_extra=extra["holdout"], holm=holm, plan_ok=plan.valid, plan_note=plan_note,
        recent_label=f"last {recent_months} months", hidden_note=HIDDEN_NOTE if raw.results_hidden else None,
    )
    hard += [TOO_GOOD_REASON] if TOO_GOOD_REASON in gate.reasons else []
    return RuleEvaluation(
        rule_id=rule.rule_id,
        name=rule.name,
        version=rule.version,
        symbols=list(rule.symbols),
        timeframe=rule.timeframe,
        description=rule.description,
        demo_note=rule.demo_note,
        control=rule.control,
        signals=sum(raw.signals_by_symbol.values()),
        signals_by_symbol=raw.signals_by_symbol,
        trades={name: window_trades(raw.trades, *bounds[name]) for name in WINDOW_NAMES},
        windows=raw.windows,
        random=raw.random,
        leak_check=raw.leak,
        plan=plan,
        median_stop_points=raw.median_stop_points,
        gate=gate,
        hard_failures=hard,
        self_test=rule.self_test,
        expected=rule.expected,
        extra=extra,
        trial_count=trial_count,
        prior_trials=int(gate_cfg["prior_trials"]),
        holm=holm,
        trials_note=trials_note,
        results_hidden=raw.results_hidden,
    )


def evaluate_rule(
    rule: SignalRule, dataset: Dataset, settings: dict, plans_dir, bounds: dict | None = None, *, trial_count: int | None = None,
) -> RuleEvaluation:
    settings = settings or {}
    gate_cfg = gate_config(settings.get("gate"))
    bounds = bounds or dataset_bounds(dataset, settings)
    raw = raw_evaluation(rule, dataset, settings, plans_dir, bounds)
    count = trial_count if trial_count is not None else int(gate_cfg["prior_trials"]) + 1
    holm = holm_decisions([raw.holdout_p], count, gate_cfg["max_p_value"])[0]
    return finish_evaluation(raw, settings, bounds, holm, count)


def evaluate_all(dataset: Dataset, settings: dict, plans_dir, *, trials_path=None, record_trials: bool = True) -> list[RuleEvaluation]:
    settings = settings or {}
    gate_cfg = gate_config(settings.get("gate"))
    prior = int(gate_cfg["prior_trials"])
    bounds = dataset_bounds(dataset, settings)
    raws = [raw_evaluation(rule, dataset, settings, plans_dir, bounds) for rule in all_rules()]
    path = trials_path or default_trials_path(plans_dir)
    key, holdout = data_id(dataset), bounds["holdout"]
    log, _ = open_trials(path)
    first_tested = [
        first_test_before_lock(log, key, holdout, r.tested_sha256, r.plan.locked_at) if log and not r.results_hidden else None
        for r in raws
    ]
    # Only results that were actually shown count as tries; hidden ones were never looked at.
    entries = [TrialEntry(r.rule.rule_id, r.rule.version, r.tested_sha256, r.plan.locked_at) for r in raws if not r.results_hidden]
    recorded, note = tally_trials(path, key, dataset_fingerprint(dataset), entries, holdout, record_trials)
    trial_count = prior + (recorded if recorded is not None else len(raws))
    decisions = holm_decisions([r.holdout_p for r in raws], max(trial_count, len(raws)), gate_cfg["max_p_value"])
    if recorded is None:
        decisions = [dataclasses.replace(d, passed=False, note=note) for d in decisions]
    elif note:
        decisions = [dataclasses.replace(d, note=note) for d in decisions]
    return [finish_evaluation(raw, settings, bounds, d, trial_count, note, early) for raw, d, early in zip(raws, decisions, first_tested)]
