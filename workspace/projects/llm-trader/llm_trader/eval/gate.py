from __future__ import annotations

from llm_trader.models import GateCheck, GateResult, RandomBaseline, WindowMetrics

DEFAULT_GATE = {
    "accuracy_bar": 0.80,
    "min_trades_holdout": 30,
    "min_trades_recent": 10,
    "max_p_value": 0.05,
    "max_p_value_recent": 0.10,
    "require_positive_expectancy": True,
}
HOLDOUT_LABEL = "never-seen months"
PLAN_CHECK = "Plan locked before testing"


def gate_config(cfg: dict | None) -> dict:
    return {**DEFAULT_GATE, **(cfg or {})}


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def _r(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.2f}R"


def _p(p: float) -> str:
    return f"{p:.3f}"


def _win_text(m: WindowMetrics) -> str:
    if not m.trades:
        return "no trades"
    lo, hi = m.win_rate_ci
    return f"{_pct(m.win_rate)} (95% CI {lo:.0%}-{hi:.0%})"


def _random_text(rb: RandomBaseline) -> str:
    if not rb.runs:
        return "not run (no trades)"
    return f"p = {_p(rb.p_value)} · random entries win {_pct(rb.win_rate_mean)}, {_r(rb.expectancy_mean)} per trade"


def _window_checks(label: str, m: WindowMetrics, rb: RandomBaseline, min_trades: int, max_p: float, cfg: dict) -> list[GateCheck]:
    bar = cfg["accuracy_bar"]
    if cfg["require_positive_expectancy"]:
        exp_ok = m.expectancy_r is not None and m.expectancy_r > 0
        exp_required = "> 0R per trade"
    else:
        exp_ok, exp_required = True, "not required"
    exp_value = "no trades" if m.expectancy_r is None else f"{_r(m.expectancy_r)} per trade"
    return [
        GateCheck(f"Enough trades in {label}", m.trades >= min_trades, f"{m.trades} trades", f"≥ {min_trades} trades"),
        GateCheck(f"Win rate ≥ {bar:.0%} in {label}", m.win_rate is not None and m.win_rate >= bar, _win_text(m), f"≥ {bar:.0%}"),
        GateCheck(f"Positive expectancy after costs ({label})", exp_ok, exp_value, exp_required),
        GateCheck(f"Beats random entries ({label})", rb.runs > 0 and rb.p_value <= max_p, _random_text(rb), f"p ≤ {max_p:g}"),
    ]


def _failed_window(label: str, m: WindowMetrics, rb: RandomBaseline, min_trades: int, max_p: float, cfg: dict, holdout: bool) -> str | None:
    bar = cfg["accuracy_bar"]
    enough = m.trades >= min_trades
    wr_ok = m.win_rate is not None and m.win_rate >= bar
    exp_ok = not cfg["require_positive_expectancy"] or (m.expectancy_r is not None and m.expectancy_r > 0)
    rnd_ok = rb.runs > 0 and rb.p_value <= max_p
    if enough and wr_ok and exp_ok and rnd_ok:
        return None
    if m.expectancy_r is not None and m.expectancy_r < 0:
        losing = f"it loses {abs(m.expectancy_r):.2f}R per trade after costs"
    else:
        losing = "it makes nothing after costs"
    if holdout and enough and wr_ok:
        clauses = []
        if not rnd_ok:
            clauses.append(f"random entries with the same stop/target also win {_pct(rb.win_rate_mean)}")
        if not exp_ok:
            clauses.append(losing)
        return f"Wins {_pct(m.win_rate)} of trades in the {label}, but " + " and ".join(clauses) + "."
    clauses = []
    if not enough:
        clauses.append(f"only {m.trades} trades (needs ≥ {min_trades})")
    if m.trades and not wr_ok:
        clauses.append(f"wins only {_pct(m.win_rate)} of trades (the bar is {bar:.0%})")
    elif m.trades and wr_ok and not holdout:
        clauses.append(f"wins {_pct(m.win_rate)} of trades")
    if m.trades and not exp_ok:
        clauses.append(losing)
    if m.trades and not rnd_ok:
        clauses.append(
            f"random entries with the same stop/target win {_pct(rb.win_rate_mean)} and average {_r(rb.expectancy_mean)} "
            f"per trade, so it shows no edge over chance (p = {_p(rb.p_value)})"
        )
    return f"In the {label}: " + "; ".join(clauses) + "."


def _reasons(status: str, holdout, h_rb, recent, r_rb, cfg: dict, hard: list[str], recent_label: str) -> list[str]:
    if status == "blocked":
        lines = [f"Blocked — {msg}" for msg in hard] or ["Blocked — the test plan is missing or was changed after it was locked."]
        lines.append("Nothing from this agent moves forward until that is fixed; its numbers are shown for diagnosis only.")
        return lines
    if status == "insufficient":
        n, need = holdout.trades, cfg["min_trades_holdout"]
        lines = [f"Only {n} trade{'' if n == 1 else 's'} in the {HOLDOUT_LABEL}; at least {need} are needed before a win rate means anything."]
        if n:
            lines.append(f"So far it won {_pct(holdout.win_rate)} of them, which is not enough evidence either way.")
        return lines
    if status == "qualified":
        lo, hi = holdout.win_rate_ci
        return [
            f"Wins {_pct(holdout.win_rate)} of trades in the {HOLDOUT_LABEL} (95% CI {lo:.0%}-{hi:.0%}) and "
            f"{_pct(recent.win_rate)} in the {recent_label}, making {_r(holdout.expectancy_r)} per trade after costs.",
            f"Random entries with the same stop and target win only {_pct(h_rb.win_rate_mean)} (p = {_p(h_rb.p_value)}).",
            "Passing this test is not permission to trade: next comes a 30-40 trade forward test at minimum lot on your broker's data.",
        ]
    lines = [
        _failed_window(HOLDOUT_LABEL, holdout, h_rb, cfg["min_trades_holdout"], cfg["max_p_value"], cfg, True),
        _failed_window(recent_label, recent, r_rb, cfg["min_trades_recent"], cfg["max_p_value_recent"], cfg, False),
    ]
    return [line for line in lines if line]


def evaluate_gate(
    holdout: WindowMetrics, holdout_rb: RandomBaseline, recent: WindowMetrics, recent_rb: RandomBaseline,
    gate_cfg: dict | None, hard_failures: list[str], *, plan_ok: bool = True, plan_note: str | None = None,
    recent_label: str = "last 3 months",
) -> GateResult:
    cfg = gate_config(gate_cfg)
    plan_value = plan_note or ("Locked and unchanged" if plan_ok else "Missing or changed after locking")
    checks = [GateCheck(PLAN_CHECK, plan_ok, plan_value, "Locked before testing, unchanged")]
    checks += _window_checks(HOLDOUT_LABEL, holdout, holdout_rb, cfg["min_trades_holdout"], cfg["max_p_value"], cfg)
    checks += _window_checks(recent_label, recent, recent_rb, cfg["min_trades_recent"], cfg["max_p_value_recent"], cfg)
    if hard_failures or not plan_ok:
        status = "blocked"
    elif holdout.trades < cfg["min_trades_holdout"]:
        status = "insufficient"
    elif all(c.passed for c in checks):
        status = "qualified"
    else:
        status = "failed"
    return GateResult(status, checks, _reasons(status, holdout, holdout_rb, recent, recent_rb, cfg, list(hard_failures), recent_label))
