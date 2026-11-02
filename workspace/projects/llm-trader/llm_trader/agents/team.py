from __future__ import annotations

from collections import Counter

from llm_trader.agents.context import split_answers
from llm_trader.agents.registry import AgentDef
from llm_trader.fmt import p_text, pct, plural, r_value
from llm_trader.models import RuleEvaluation
from llm_trader.supervisor.supervisor import blocked_kind, gate_counts, self_test_verdict, self_tests_ok

RESEARCH_STATUS = {"qualified": "ok", "failed": "fail", "insufficient": "warn", "blocked": "fail"}
TERCILES = {1: "low", 2: "mid", 3: "high"}


def _reason(e: RuleEvaluation) -> str:
    return e.gate.reasons[0] if e.gate.reasons else e.gate.status


def research_summary(e: RuleEvaluation, bar: float, min_trades: int) -> str:
    m, rb = e.windows["holdout"], e.random["holdout"]
    status = e.gate.status
    if e.self_test:
        verdict = {True: "as expected", False: "NOT as expected", None: "could not run (missing data)"}[self_test_verdict(e)]
        return f"Self-test ({e.expected}): {status}, {verdict}. {_reason(e)}"
    if status == "qualified":
        lo, hi = m.win_rate_ci
        return (f"Qualified: wins {pct(m.win_rate)} in never-seen months (95% CI {lo:.0%}-{hi:.0%}), "
                f"{r_value(m.expectancy_r)} per trade, beats random ({p_text(rb.p_value)}).")
    if status == "insufficient":
        return f"Too few trades: {m.trades} in never-seen months (needs {min_trades}), too strict to judge."
    if status == "blocked":
        text = f"Blocked: {blocked_kind(e)}."
        if e.results_hidden:
            text += " Its never-seen results stay hidden until the plan is locked again."
        elif m.win_rate is not None and m.win_rate >= bar:
            text += f" Its backtest showed {pct(m.win_rate)} wins, which cannot be trusted."
        return text
    versus = "beats random" if e.holm and e.holm.passed else "no better than random"
    return f"Failed: {pct(m.win_rate)} wins (bar {bar:.0%}), {r_value(m.expectancy_r)} per trade after costs; {versus} ({p_text(rb.p_value)})."


def card(d: AgentDef, status: str, summary: str, gate_status: str | None = None, accuracy: float | None = None) -> dict:
    return {
        "id": d.id, "name": d.name, "lane": d.lane, "kind": d.kind, "role": d.role, "status": status, "summary": summary,
        "rule_id": d.rule_id, "gate_status": gate_status, "accuracy": accuracy, "control": d.control,
    }


def data_status(data_mode: str, checks: list[dict], symbols: int, parity: dict | None) -> tuple[str, str]:
    data_rows = [x for x in checks if x["stage"] == "data"]
    gaps = sum(1 for x in data_rows if x["name"] == "No missing bars in market hours" and x["status"] != "pass")
    label = "Demo data (synthetic)" if data_mode == "demo" else "Your MT5 data"
    summary = f"{label}: {symbols} symbols, " + ("0 unexplained gaps." if not gaps else f"gaps in {plural(gaps, 'symbol')}.")
    if parity:
        summary += f" A TradingView-style copy differs on {parity['candles_differ']:.0%} of candles."
    if any(x["status"] == "fail" for x in data_rows):
        return "fail", summary
    if any(x["status"] == "warn" for x in data_rows):
        return "warn", summary
    return "ok", summary + (" Expected on demo data: never eligible for money." if data_mode == "demo" else "")


def research_status(evaluations: list[RuleEvaluation]) -> tuple[str, str]:
    total = sum(e.signals for e in evaluations)
    tests = sum(1 for e in evaluations if e.self_test)
    silent = [e.rule_id for e in evaluations if e.signals == 0]
    summary = f"{len(evaluations) - tests} rule agents and {tests} self-tests produced {total:,} signals"
    if silent:
        return "warn", summary + f"; no signals from {', '.join(silent)}."
    return "ok", summary + "."


def validation_status(evaluations: list[RuleEvaluation], bar: float) -> tuple[str, str]:
    rules = [e for e in evaluations if not e.self_test]
    counts = gate_counts(rules)
    summary = f"{counts['qualified']} of {len(rules)} rule agents passed the {bar:.0%} gate."
    others = [f"{counts[s]} {label}" for s, label in (("failed", "failed"), ("insufficient", "too few trades"), ("blocked", "blocked")) if counts[s]]
    if others:
        summary += " " + ", ".join(others) + "."
    ran = [e for e in evaluations if e.self_test and self_test_verdict(e) is not None]
    if ran:
        summary += f" Rule self-tests: {sum(1 for e in ran if e.self_test_ok)} of {len(ran)} as expected."
    if self_tests_ok(evaluations) is False:
        return "fail", "A self-test did not behave as expected, so no result can be trusted. " + summary
    return "ok", summary


def risk_status(kill_switch_on: bool, usage: dict, limits: dict, min_lot_rows: list[dict], account_feed: bool = False) -> tuple[str, str]:
    too_big = [r["symbol"] for r in min_lot_rows if r["ok"] is False]
    kill = f"kill switch {'ON' if kill_switch_on else 'off'}"
    if account_feed:
        summary = f"{usage['open_risk_pct']:.0f}% open risk of {limits['max_open_risk_pct']:g}% · {kill}"
    else:
        summary = f"No live account feed: open risk, margin and losses read 0% and nothing is enforced yet · {kill}"
    if too_big:
        summary += f" · min lot does not fit {', '.join(too_big)}"
    if kill_switch_on:
        return "warn", summary
    if not account_feed:
        return "idle", summary
    return ("warn" if too_big else "ok"), summary


def monitor_status(research: list[dict], kill_switch: dict, loss_stops: list) -> tuple[str, str]:
    active = [r for r in research if r["stage"] == "forward_test"]
    if kill_switch["on"]:
        return "warn", f"Kill switch is ON: {kill_switch.get('reason') or 'no reason given'}"
    if loss_stops:
        return "fail", f"{plural(len(loss_stops), 'loss stop')} reached: no entries."
    if active:
        return "ok", f"Tracking {plural(len(active), 'forward test')}: 0 trades so far, waiting for the EA."
    return "idle", "No forward test yet. Kill switch off, no loss stop reached. Would-be phone alerts go to the log."


def report_status(llm_mode: str) -> tuple[str, str]:
    if llm_mode == "claude":
        return "ok", "Report written; Claude wrote the review text, the numbers come from code."
    return "ok", "Report written by the built-in template (AI offline)."


def bridge_status(advisories: int, data_mode: str, kill_switch_on: bool) -> tuple[str, str]:
    if kill_switch_on:
        return "warn", "kill.flag set: agent output stopped (no EA reads it yet in v1)"
    if advisories:
        return "ok", f"{advisories} pause advisory(ies) written"
    return "idle", f"0 advisories ({'demo data' if data_mode != 'mt5' else 'no pause agent has qualified'})"


def tagger_status(tagger: dict) -> tuple[str, str]:
    split = split_answers(tagger)
    return "idle", f"{split} of {len(tagger['last'])} questions got split answers, so no opinion. Logged only."


def regime_status(rows: list[dict]) -> tuple[str, str]:
    if not rows:
        return "idle", "Not enough H1 bars to measure volatility and trend."
    vol = Counter(TERCILES[r["vol_tercile"]] for r in rows)
    trend = Counter(r["trend"] for r in rows)
    vol_text = ", ".join(f"{vol[k]} {k}" for k in ("high", "mid", "low") if vol[k])
    trend_text = ", ".join(f"{trend[k]} {k}" for k in ("up", "down", "flat") if trend[k])
    return "ok", f"{len(rows)} symbols. Volatility: {vol_text}. Trend: {trend_text}."


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
            status = {True: "ok", False: "fail", None: "idle"}[self_test_verdict(e)] if e.self_test else RESEARCH_STATUS[e.gate.status]
            agents.append(card(d, status, research_summary(e, bar, min_trades), e.gate.status, e.windows["holdout"].win_rate))
        else:
            agents.append(card(d, *statuses[d.id]))
    return agents


def build_pipeline(statuses: dict[str, tuple[str, str]], bar: float) -> list[dict]:
    names = (("data", "Data checks"), ("research", "Research"), ("validation", f"Validation ({bar:.0%} gate)"),
             ("risk", "Portfolio risk"), ("bridge", "Bridge to MT5"))
    return [{"id": key, "name": name, "status": statuses[key][0], "summary": statuses[key][1]} for key, name in names]
