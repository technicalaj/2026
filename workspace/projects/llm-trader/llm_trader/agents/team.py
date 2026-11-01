from __future__ import annotations

from llm_trader.agents.registry import AgentDef
from llm_trader.models import RuleEvaluation
from llm_trader.supervisor.supervisor import blocked_kind, control_ok, gate_counts

RESEARCH_STATUS = {"qualified": "ok", "failed": "fail", "insufficient": "warn", "blocked": "fail"}


def _pct(x) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def research_summary(e: RuleEvaluation, bar: float, min_trades: int) -> str:
    m, rb = e.windows["holdout"], e.random["holdout"]
    status = e.gate.status
    if status == "qualified":
        lo, hi = m.win_rate_ci
        text = (f"Qualified: wins {_pct(m.win_rate)} in never-seen months (95% CI {lo:.0%}-{hi:.0%}), "
                f"{m.expectancy_r:+.2f}R per trade, beats random (p = {rb.p_value:.3f}).")
        return text + (" Self-test only." if e.control else "")
    if status == "insufficient":
        return f"Too few trades: {m.trades} in never-seen months (needs {min_trades}), too strict to judge."
    if status == "blocked":
        text = f"Blocked: {blocked_kind(e)}."
        if m.win_rate is not None and m.win_rate >= bar:
            text += f" Its backtest showed {_pct(m.win_rate)} wins, which cannot be trusted."
        return text
    exp = "n/a" if m.expectancy_r is None else f"{m.expectancy_r:+.2f}R"
    return (f"Failed: wins {_pct(m.win_rate)} in never-seen months (bar {bar:.0%}), {exp} per trade after costs; "
            f"random entries win {_pct(rb.win_rate_mean)} (p = {rb.p_value:.2f}).")


def card(d: AgentDef, status: str, summary: str, gate_status: str | None = None, accuracy: float | None = None) -> dict:
    return {
        "id": d.id, "name": d.name, "lane": d.lane, "kind": d.kind, "role": d.role, "status": status, "summary": summary,
        "rule_id": d.rule_id, "gate_status": gate_status, "accuracy": accuracy, "control": d.control,
    }


def data_status(data_mode: str, checks: list[dict], symbols: int, parity: dict | None) -> tuple[str, str]:
    data_rows = [x for x in checks if x["stage"] == "data"]
    gaps = sum(1 for x in data_rows if x["name"] == "No missing bars in market hours" and x["status"] != "pass")
    label = "Demo data (synthetic)" if data_mode == "demo" else "Your MT5 data"
    summary = f"{label}: {symbols} symbols, " + ("0 unexplained gaps." if not gaps else f"gaps in {gaps} symbol(s).")
    if parity:
        summary += f" A TradingView-style copy differs on {parity['candles_differ']:.0%} of candles."
    if any(x["status"] == "fail" for x in data_rows):
        return "fail", summary
    if data_mode == "demo" or any(x["status"] == "warn" for x in data_rows if x["name"] != "Second source matches (parity check)"):
        return "warn", summary
    return "ok", summary


def research_status(evaluations: list[RuleEvaluation]) -> tuple[str, str]:
    total = sum(e.signals for e in evaluations)
    silent = [e.rule_id for e in evaluations if e.signals == 0]
    summary = f"{len(evaluations)} rules produced {total:,} signals"
    if silent:
        return "warn", summary + f"; no signals from {', '.join(silent)}."
    return "ok", summary + "."


def validation_status(evaluations: list[RuleEvaluation], bar: float) -> tuple[str, str]:
    counts = gate_counts(evaluations)
    real = [e for e in evaluations if e.gate.status == "qualified" and not e.control]
    note = " (the self-test)" if counts["qualified"] and not real else ""
    summary = f"{counts['qualified']} of {len(evaluations)} passed the {bar:.0%} gate{note}."
    others = [f"{counts[s]} {label}" for s, label in (("failed", "failed"), ("insufficient", "too few trades"), ("blocked", "blocked")) if counts[s]]
    if others:
        summary += " " + ", ".join(others) + "."
    if control_ok(evaluations) is False:
        return "fail", "Self-test failed: the gate could not find the planted pattern. " + summary
    return ("ok" if real else "warn"), summary


def risk_status(kill_switch_on: bool, usage: dict, limits: dict, min_lot_rows: list[dict]) -> tuple[str, str]:
    too_big = [r["symbol"] for r in min_lot_rows if r["ok"] is False]
    summary = (f"{usage['open_risk_pct']:.0f}% open risk of {limits['max_open_risk_pct']:g}% · kill switch "
               f"{'ON' if kill_switch_on else 'off'}")
    if too_big:
        summary += f" · min lot too big for {', '.join(too_big)}"
    return ("warn" if kill_switch_on or too_big else "ok"), summary


def monitor_status(research: list[dict], kill_switch: dict) -> tuple[str, str]:
    active = [r for r in research if r["stage"] == "forward_test"]
    if kill_switch["on"]:
        return "warn", f"Kill switch is ON: {kill_switch.get('reason') or 'no reason given'}"
    if active:
        return "ok", f"Tracking {len(active)} forward test(s): 0 trades so far, waiting for the EA."
    return "idle", "No agent in a forward test yet. Kill switch off. Waiting for EA trades."


def report_status(llm_mode: str) -> tuple[str, str]:
    if llm_mode == "claude":
        return "ok", "Report written; Claude wrote the review text, the numbers come from code."
    return "ok", "Report written by the built-in template (AI offline)."


def bridge_status(written: int, data_mode: str, kill_switch_on: bool, safe_mode_on: bool) -> tuple[str, str]:
    if written:
        return "ok", f"{written} signal(s) written for the EA"
    why = "kill switch on" if kill_switch_on else "demo data" if data_mode != "mt5" else "safe mode" if safe_mode_on else "nothing qualified"
    return "idle", f"0 signals written ({why})"


def build_agents(defs: list[AgentDef], evaluations: list[RuleEvaluation], statuses: dict[str, tuple[str, str]], bar: float, min_trades: int) -> list[dict]:
    by_rule = {e.rule_id: e for e in evaluations}
    agents = []
    for d in defs:
        if d.planned:
            agents.append(card(d, "planned", "Planned for a later version."))
        elif d.rule_id:
            e = by_rule.get(d.rule_id)
            if e is None:
                agents.append(card(d, "idle", "Not tested in this run."))
                continue
            agents.append(card(d, RESEARCH_STATUS[e.gate.status], research_summary(e, bar, min_trades), e.gate.status, e.windows["holdout"].win_rate))
        else:
            agents.append(card(d, *statuses[d.id]))
    return agents


def build_pipeline(statuses: dict[str, tuple[str, str]], bar: float) -> list[dict]:
    names = (("data", "Data checks"), ("research", "Research"), ("validation", f"Validation ({bar:.0%} gate)"),
             ("risk", "Portfolio risk"), ("bridge", "Bridge to MT5 EA"))
    return [{"id": key, "name": name, "status": statuses[key][0], "summary": statuses[key][1]} for key, name in names]
