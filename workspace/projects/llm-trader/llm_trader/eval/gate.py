from __future__ import annotations

from llm_trader.eval.robustness import STRESS_COSTS, positive_terciles
from llm_trader.eval.trials import holm_decisions
from llm_trader.fmt import p_text, pct, r_value, threshold, times
from llm_trader.models import GateCheck, GateResult, HolmDecision, RandomBaseline, WindowExtra, WindowMetrics

DEFAULT_GATE = {
    "accuracy_bar": 0.80,
    "min_trades_holdout": 30,
    "min_trades_recent": 10,
    "max_p_value": 0.05,
    "max_p_value_recent": 0.10,
    "require_positive_expectancy": True,
    "win_threshold_r": 0.1,
    "breakeven_band_r": 0.1,
    "full_stop_r": -0.9,
    "min_positive_terciles": 2,
    "min_tercile_trades": 5,
    "max_stop_target_ratio": 2.0,
    "max_win_rate": 0.90,
    "max_profit_factor": 4.0,
    "prior_trials": 0,
}
HOLDOUT_LABEL = "never-seen months"
PLAN_CHECK = "Plan locked before testing"
HOLM_CHECK_PREFIX = "Beats random after correcting for"
TOO_GOOD_REASON = "Too good to be true — needs a leak review before it can qualify."
MONTE_CARLO_NOTE = "The plan's other route, a Monte Carlo tail check at real account size, is not built yet."
RANDOM_TIMES = "the same trades at random times (same direction, stop and target)"
RATIO_TOLERANCE = 1e-9


def gate_config(cfg: dict | None) -> dict:
    return {**DEFAULT_GATE, **(cfg or {})}


def too_good_check_name(cfg: dict) -> str:
    return f"Not too good to be true (win rate ≤ {cfg['max_win_rate']:.0%}, profit factor ≤ {cfg['max_profit_factor']:g})"


def _tries(n: int) -> str:
    return f"{n} {'try' if n == 1 else 'tries'}"


def holm_check_name(tries: int) -> str:
    return f"{HOLM_CHECK_PREFIX} {_tries(tries)} ({HOLDOUT_LABEL})"


def _win_text(m: WindowMetrics) -> str:
    if not m.trades:
        return "no trades"
    lo, hi = m.win_rate_ci
    return f"{pct(m.win_rate)} (95% CI {lo:.0%}-{hi:.0%})"


def _random_text(rb: RandomBaseline) -> str:
    if not rb.runs:
        return "not run (no trades)"
    return f"{p_text(rb.p_value)} · random entry times win {pct(rb.win_rate_mean)}, {r_value(rb.expectancy_mean)} per trade"


def _expectancy_required(cfg: dict, what: str = "> 0R per trade") -> str:
    return what if cfg["require_positive_expectancy"] else "not required"


def _window_checks(label: str, m: WindowMetrics, rb: RandomBaseline, min_trades: int, max_p: float, cfg: dict) -> list[GateCheck]:
    bar = cfg["accuracy_bar"]
    exp_ok = not cfg["require_positive_expectancy"] or (m.expectancy_r is not None and m.expectancy_r > 0)
    exp_value = "no trades" if m.expectancy_r is None else f"{r_value(m.expectancy_r)} per trade"
    return [
        GateCheck(f"Enough trades in {label}", m.trades >= min_trades, f"{m.trades} trades", f"≥ {min_trades} trades"),
        GateCheck(f"Win rate ≥ {bar:.0%} in {label}", m.win_rate is not None and m.win_rate >= bar, _win_text(m), f"≥ {bar:.0%}"),
        GateCheck(f"Positive expectancy after costs ({label})", exp_ok, exp_value, _expectancy_required(cfg)),
        GateCheck(f"Beats random entries ({label})", rb.runs > 0 and rb.p_value <= max_p, _random_text(rb), f"p ≤ {max_p:g}"),
    ]


def _too_good(m: WindowMetrics, cfg: dict) -> GateCheck:
    required = f"win rate ≤ {cfg['max_win_rate']:.0%}, profit factor ≤ {cfg['max_profit_factor']:g}"
    name = too_good_check_name(cfg)
    if m.trades < cfg["min_trades_holdout"]:
        return GateCheck(name, True, f"too few trades to judge ({m.trades})", required)
    pf_text = "no losing trades" if m.profit_factor is None else f"profit factor {m.profit_factor:.2f}"
    ok = m.win_rate <= cfg["max_win_rate"] and m.profit_factor is not None and m.profit_factor <= cfg["max_profit_factor"]
    return GateCheck(name, ok, f"{pct(m.win_rate)} win rate, {pf_text}", required)


def _interval(extra: WindowExtra | None) -> tuple[float, float] | None:
    ci = extra.expectancy_ci if extra else None
    return None if ci is None or ci[0] is None else ci


def _lower_bound(extra: WindowExtra | None, cfg: dict) -> GateCheck:
    name = f"Expectancy lower 95% bound above 0 ({HOLDOUT_LABEL})"
    ci = _interval(extra)
    value = "fewer than 2 trades" if ci is None else f"{r_value(ci[0])} (95% range {r_value(ci[0])} to {r_value(ci[1])})"
    ok = not cfg["require_positive_expectancy"] or (ci is not None and ci[0] > 0)
    return GateCheck(name, ok, value, _expectancy_required(cfg, "> 0R"))


def _stressed(extra: WindowExtra | None, cfg: dict) -> GateCheck:
    name = f"Still profitable at {STRESS_COSTS:g}× costs ({HOLDOUT_LABEL})"
    x = extra.expectancy_1_5x_costs if extra else None
    if x is None:
        value = "no trades"
    else:
        value = f"{r_value(x)} per trade" + (f" (2× costs: {r_value(extra.expectancy_2x_costs)})" if extra.expectancy_2x_costs is not None else "")
    ok = not cfg["require_positive_expectancy"] or (x is not None and x > 0)
    return GateCheck(name, ok, value, _expectancy_required(cfg, f"> 0R at {STRESS_COSTS:g}× costs"))


def _holm_required(holm: HolmDecision, cfg: dict) -> str:
    return f"p ≤ {threshold(holm.threshold)} ({cfg['max_p_value']:g} ÷ {holm.tries - holm.rank + 1}, Holm)"


def _holm(rb: RandomBaseline, holm: HolmDecision, trial_count: int, prior: int, cfg: dict) -> GateCheck:
    name, required = holm_check_name(holm.tries), _holm_required(holm, cfg)
    if not rb.runs:
        return GateCheck(name, False, "not run (no trades)", required)
    counted = f"{_tries(trial_count)} counted" + (f", {prior} from earlier studies" if prior else "")
    rank = f"rank {holm.rank} of {holm.family} rules; " if holm.family > 1 else ""
    value = f"{p_text(holm.p_value)} ({rank}{counted})"
    if holm.stopped_early:
        value += "; a rule with a smaller p already failed, so Holm stops there"
    floor = 1.0 / (rb.runs + 1)
    if holm.threshold < floor:
        value += f"; {rb.runs:,} random runs cannot show p below {floor:.4f}: raise evaluation.random_runs"
    if holm.note:
        value += f"; {holm.note}"
    return GateCheck(name, holm.passed, value, required)


def _terciles(extra: WindowExtra | None, cfg: dict) -> GateCheck:
    need, min_n = cfg["min_positive_terciles"], cfg["min_tercile_trades"]
    name = f"Positive in at least {need:g} of 3 volatility regimes ({HOLDOUT_LABEL})"
    terciles = extra.terciles if extra else []
    if not terciles or not any(t["trades"] for t in terciles):
        return GateCheck(name, False, "no trades with a known volatility regime", f"≥ {need:g} of 3, each with ≥ {min_n} trades")
    n = positive_terciles(terciles, min_n)
    parts = ", ".join(f"{t['name']} {r_value(t['expectancy_r'])} on {t['trades']}" for t in terciles)
    return GateCheck(name, n >= need, f"positive in {n} of 3 ({parts})", f"≥ {need:g} of 3, each with ≥ {min_n} trades")


def _stop_target(extra: WindowExtra | None, m: WindowMetrics, cfg: dict) -> GateCheck:
    limit = cfg["max_stop_target_ratio"]
    name = f"Stop no more than {limit:g}× the target distance"
    ratio = extra.stop_target_ratio if extra else None
    if ratio is None:
        value = "no trades" if not m.trades else "no fixed target (time exits only)"
        return GateCheck(name, bool(m.trades), value, f"≤ {limit:g}×")
    return GateCheck(name, ratio <= limit + RATIO_TOLERANCE, f"stop is {times(ratio)} the target (median)", f"≤ {limit:g}×")


def _losing(m: WindowMetrics) -> str:
    if m.expectancy_r is not None and m.expectancy_r < 0:
        return f"it loses {abs(m.expectancy_r):.2f}R per trade after costs"
    return "it makes nothing after costs"


def _high_win_rate_loser(label: str, m: WindowMetrics, rb: RandomBaseline, extra: WindowExtra | None, exp_ok: bool, rnd_ok: bool, cfg: dict) -> str:
    head = f"Wins {pct(m.win_rate)} of trades in the {label}"
    why = []
    ratio = extra.stop_target_ratio if extra else None
    if ratio is not None and ratio > cfg["max_stop_target_ratio"] + RATIO_TOLERANCE:
        why.append(f"its stop is {times(ratio)} its target")
    if not rnd_ok:
        why.append(f"{RANDOM_TIMES} also win {pct(rb.win_rate_mean)}")
    if not exp_ok:
        return f"{head}, yet {_losing(m)}" + (": " + ", and ".join(why) if why else "") + "."
    return f"{head}, but " + ", and ".join(why) + "."


def _failed_window(label: str, m: WindowMetrics, rb: RandomBaseline, min_trades: int, max_p: float, cfg: dict, holdout: bool,
                   extra: WindowExtra | None = None) -> str | None:
    bar = cfg["accuracy_bar"]
    enough = m.trades >= min_trades
    wr_ok = m.win_rate is not None and m.win_rate >= bar
    exp_ok = not cfg["require_positive_expectancy"] or (m.expectancy_r is not None and m.expectancy_r > 0)
    rnd_ok = rb.runs > 0 and rb.p_value <= max_p
    if enough and wr_ok and exp_ok and rnd_ok:
        return None
    if holdout and enough and wr_ok:
        return _high_win_rate_loser(label, m, rb, extra, exp_ok, rnd_ok, cfg)
    clauses = []
    if not enough:
        clauses.append(f"only {m.trades} trades (needs ≥ {min_trades})")
    if m.trades and not wr_ok:
        clauses.append(f"wins only {pct(m.win_rate)} of trades (the bar is {bar:.0%})")
    elif m.trades and wr_ok and not holdout:
        clauses.append(f"wins {pct(m.win_rate)} of trades")
    if m.trades and not exp_ok:
        clauses.append(_losing(m))
    if m.trades and not rnd_ok:
        clauses.append(
            f"the same trades at random times win {pct(rb.win_rate_mean)} and average {r_value(rb.expectancy_mean)} "
            f"per trade, so it shows no edge over chance ({p_text(rb.p_value)})"
        )
    return f"In the {label}: " + "; ".join(clauses) + "."


def _robustness_lines(holdout: WindowMetrics, rb: RandomBaseline, extra: WindowExtra | None, holm: HolmDecision, checks: dict, cfg: dict) -> list[str]:
    lines = []
    profitable = holdout.expectancy_r is not None and holdout.expectancy_r > 0
    ci = _interval(extra)
    if profitable and not checks["lower"].passed and ci is not None:
        lines.append(f"Its average of {r_value(holdout.expectancy_r)} per trade could be luck: the 95% range runs from {r_value(ci[0])} to {r_value(ci[1])}.")
    if profitable and not checks["stress"].passed and extra and extra.expectancy_1_5x_costs is not None:
        lines.append(f"At {STRESS_COSTS:g}× costs it would make {r_value(extra.expectancy_1_5x_costs)} per trade: the edge is too thin to survive higher costs.")
    if checks["random"].passed and not checks["holm"].passed:
        if holm.note and holm.p_value <= holm.threshold:
            lines.append(f"It beats random entry times ({p_text(rb.p_value)}), but {holm.note}.")
        else:
            lines.append(f"It beats random entry times ({p_text(rb.p_value)}), but not after correcting for {_tries(holm.tries)} on these "
                         f"months: Holm's step-down needs p ≤ {threshold(holm.threshold)} here.")
    if profitable and not checks["terciles"].passed:
        n = positive_terciles(extra.terciles, cfg["min_tercile_trades"]) if extra else 0
        lines.append(f"Regime-specific: positive in only {n} of 3 volatility regimes — kept in shadow.")
    if not checks["ratio"].passed and extra and extra.stop_target_ratio is not None:
        lines.append(f"The stop is {times(extra.stop_target_ratio)} the target distance (limit {cfg['max_stop_target_ratio']:g}×), so a few "
                     f"full stops wipe out many small wins. {MONTE_CARLO_NOTE}")
    return lines


def _qualified_lines(holdout: WindowMetrics, rb: RandomBaseline, recent: WindowMetrics, extra: WindowExtra | None, holm: HolmDecision, recent_label: str, cfg: dict) -> list[str]:
    lo, hi = holdout.win_rate_ci
    ci = _interval(extra)
    spread = f" (95% range {r_value(ci[0])} to {r_value(ci[1])})" if ci else ""
    lines = [
        f"Wins {pct(holdout.win_rate)} of trades in the {HOLDOUT_LABEL} (95% CI {lo:.0%}-{hi:.0%}) and {pct(recent.win_rate)} in the "
        f"{recent_label}, making {r_value(holdout.expectancy_r)} per trade after costs{spread}.",
        f"The same trades at random times win only {pct(rb.win_rate_mean)} ({p_text(rb.p_value)}), and it still beats them after "
        f"correcting for {_tries(holm.tries)} on these months (needs p ≤ {threshold(holm.threshold)}).",
    ]
    if extra:
        n = positive_terciles(extra.terciles, cfg["min_tercile_trades"])
        lines.append(f"It stays profitable at {STRESS_COSTS:g}× costs ({r_value(extra.expectancy_1_5x_costs)} per trade) and in {n} of 3 volatility regimes.")
    lines.append("Passing this test is not permission to trade: next comes a 30-40 trade forward test at minimum lot on your broker's data.")
    return lines


def evaluate_gate(
    holdout: WindowMetrics, holdout_rb: RandomBaseline, recent: WindowMetrics, recent_rb: RandomBaseline,
    gate_cfg: dict | None, hard_failures: list[str], *, holdout_extra: WindowExtra | None = None,
    holm: HolmDecision | None = None, plan_ok: bool = True, plan_note: str | None = None, recent_label: str = "last 3 months",
    hidden_note: str | None = None,
) -> GateResult:
    cfg = gate_config(gate_cfg)
    extra = holdout_extra
    trial_count = extra.trial_count if extra and extra.trial_count else 1
    if holm is None:
        holm = holm_decisions([holdout_rb.p_value if holdout_rb.runs else 1.0], trial_count, cfg["max_p_value"])[0]
    plan_value = plan_note or ("Locked and unchanged" if plan_ok else "Missing or changed after locking")
    held = _window_checks(HOLDOUT_LABEL, holdout, holdout_rb, cfg["min_trades_holdout"], cfg["max_p_value"], cfg)
    named = {
        "plan": GateCheck(PLAN_CHECK, plan_ok, plan_value, "Locked before testing, unchanged"),
        "too_good": _too_good(holdout, cfg),
        "trades": held[0], "win_rate": held[1], "expectancy": held[2],
        "lower": _lower_bound(extra, cfg),
        "stress": _stressed(extra, cfg),
        "random": held[3],
        "holm": _holm(holdout_rb, holm, trial_count, int(cfg["prior_trials"]), cfg),
        "terciles": _terciles(extra, cfg),
        "ratio": _stop_target(extra, holdout, cfg),
    }
    checks = list(named.values()) + _window_checks(recent_label, recent, recent_rb, cfg["min_trades_recent"], cfg["max_p_value_recent"], cfg)
    too_good = not named["too_good"].passed
    if hard_failures or not plan_ok or too_good:
        status = "blocked"
    elif holdout.trades < cfg["min_trades_holdout"]:
        status = "insufficient"
    elif all(c.passed for c in checks):
        status = "qualified"
    else:
        status = "failed"

    if status == "blocked":
        reasons = [f"Blocked — {msg}" for msg in hard_failures]
        if not plan_ok and not hard_failures:
            reasons.append("Blocked — the test plan is missing or was changed after it was locked.")
        if too_good:
            reasons.append(TOO_GOOD_REASON)
        reasons.append("Nothing from this agent moves forward until that is fixed; " + (
            hidden_note[:1].lower() + hidden_note[1:] if hidden_note else "its numbers are shown for diagnosis only."))
    elif status == "insufficient":
        n, need = holdout.trades, cfg["min_trades_holdout"]
        reasons = [f"Only {n} trade{'' if n == 1 else 's'} in the {HOLDOUT_LABEL}; at least {need} are needed before a win rate means anything."]
        if n:
            reasons.append(f"So far it won {pct(holdout.win_rate)} of them, which is not enough evidence either way.")
    elif status == "qualified":
        reasons = _qualified_lines(holdout, holdout_rb, recent, extra, holm, recent_label, cfg)
    else:
        reasons = [line for line in (
            _failed_window(HOLDOUT_LABEL, holdout, holdout_rb, cfg["min_trades_holdout"], cfg["max_p_value"], cfg, True, extra),
            _failed_window(recent_label, recent, recent_rb, cfg["min_trades_recent"], cfg["max_p_value_recent"], cfg, False),
        ) if line]
        reasons += _robustness_lines(holdout, holdout_rb, extra, holm, named, cfg)
        if not reasons:
            reasons = ["Failed: " + "; ".join(c.name for c in checks if not c.passed) + "."]
    return GateResult(status, checks, reasons)
