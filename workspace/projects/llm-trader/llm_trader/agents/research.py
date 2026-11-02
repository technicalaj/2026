from __future__ import annotations

from llm_trader.models import WINDOW_NAMES, RuleEvaluation, to_jsonable

WINDOW_KEYS = (
    "start", "end", "trades", "wins", "losses", "win_rate", "win_rate_ci", "full_stop_rate", "breakeven_rate", "expectancy_r",
    "profit_factor", "max_drawdown_r", "avg_hold_bars", "equity_r",
)
RANDOM_KEYS = ("runs", "p_value", "p_value_win_rate", "expectancy_mean", "expectancy_p95", "win_rate_mean", "win_rate_p95", "hist")
TESTED = ("holdout", "recent")


def _split(raw) -> dict:
    raw = raw or {}
    return {"trades": int(raw.get("trades") or 0), "win_rate": raw.get("win_rate"), "expectancy_r": raw.get("expectancy_r")}


def extra_view(raw: dict | None, trial_count: int) -> dict:
    raw = raw or {}
    ci = raw.get("expectancy_ci")
    return {
        "expectancy_ci": list(ci) if ci else [None, None],
        "expectancy_1_5x_costs": raw.get("expectancy_1_5x_costs"),
        "expectancy_2x_costs": raw.get("expectancy_2x_costs"),
        "long": _split(raw.get("long")),
        "short": _split(raw.get("short")),
        "terciles": [{"name": t["name"], "trades": int(t.get("trades") or 0), "expectancy_r": t.get("expectancy_r")} for t in raw.get("terciles") or []],
        "stop_target_ratio": raw.get("stop_target_ratio"),
        "holm_threshold": raw.get("holm_threshold"),
        "trial_count": int(raw.get("trial_count") or trial_count),
    }


def window_view(raw: dict, trades: list, name: str, trial_count: int) -> dict:
    out = {k: raw.get(k) for k in WINDOW_KEYS}
    if out["losses"] is None:
        out["losses"] = sum(1 for t in trades if getattr(t, "label", None) == "loss")
    if name in TESTED:
        out["random"] = {k: raw.get("random", {}).get(k) for k in RANDOM_KEYS}
        out["extra"] = extra_view(raw.get("extra"), trial_count)
    return out


def windows_view(e: RuleEvaluation) -> dict:
    raw = to_jsonable(e.windows_dict())
    return {name: window_view(raw[name], e.trades.get(name, []), name, e.trial_count) for name in WINDOW_NAMES}


def gate_view(e: RuleEvaluation) -> dict:
    gate = e.gate.to_dict()
    return {"status": gate["status"], "checks": [{k: c[k] for k in ("name", "passed", "value", "required")} for c in gate["checks"]],
            "reasons": list(gate["reasons"])}


def plan_view(e: RuleEvaluation) -> dict:
    plan = e.plan.to_dict()
    return {k: plan[k] for k in ("sha256", "locked_at", "valid", "reason", "params")}


def research_item(e: RuleEvaluation, stage: str, note: str, forward: dict, risk: dict) -> dict:
    return {
        "rule_id": e.rule_id, "name": e.name, "symbols": list(e.symbols), "timeframe": e.timeframe,
        "description": e.description, "demo_note": e.demo_note, "control": e.control,
        "kind": "self_test" if e.self_test else "rule", "self_test": bool(e.self_test), "expected": e.expected,
        "self_test_ok": e.self_test_ok, "plan": plan_view(e), "results_hidden": e.results_hidden, "signals": e.signals,
        "windows": windows_view(e), "gate": gate_view(e),
        "stage": stage, "stage_note": note, "forward": forward, "risk_at_min_lot": risk,
    }
