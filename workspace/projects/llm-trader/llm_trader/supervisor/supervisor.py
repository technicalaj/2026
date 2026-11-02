from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from llm_trader.fmt import plural
from llm_trader.models import RuleEvaluation
from llm_trader.supervisor import checks as c
from llm_trader.supervisor.checks import missing_data, self_test_verdict

REGIME_CHECK = "Positive in at least"
TOO_GOOD_CHECK = "Not too good to be true"


@dataclass(frozen=True)
class StageContext:
    data_eligible: bool
    data_reason: str
    approvals_clear: bool
    kill_switch_on: bool
    risk_ok: bool
    risk_note: str | None
    forward_min: int = 30
    forward_max: int = 40


def failed_checks(e: RuleEvaluation) -> list[str]:
    return [check.name for check in e.gate.checks if not check.passed]


def blocked_kind(e: RuleEvaluation) -> str:
    if not e.leak_check.passed:
        return "future-data leak"
    if not e.plan.valid:
        return "test plan not locked before testing"
    if missing_data(e):
        return "missing data"
    if any(h.startswith(("Costs missing", "No symbol specification")) for h in e.hard_failures):
        return "costs missing"
    if any(h.startswith("Rejected signal") for h in e.hard_failures):
        return "signal without a stop"
    if any(name.startswith(TOO_GOOD_CHECK) for name in failed_checks(e)):
        return "too good to be true: needs a leak review"
    return "hard failure"


def regime_specific(e: RuleEvaluation) -> bool:
    failed = failed_checks(e)
    return bool(failed) and all(name.startswith(REGIME_CHECK) for name in failed)


def assign_stage(e: RuleEvaluation, ctx: StageContext) -> tuple[str, str, dict]:
    span = f"{ctx.forward_min}-{ctx.forward_max}"
    waiting = {"trades": 0, "target_min": ctx.forward_min, "target_max": ctx.forward_max,
               "note": "Starts only after qualifying on your broker's data."}
    status = e.gate.status
    if status == "blocked":
        return "blocked", f"Blocked by the supervisor ({blocked_kind(e)}). Nothing moves forward until that is fixed.", waiting
    if e.self_test:
        verdict = "as expected" if e.self_test_ok else "NOT as expected: no result can be trusted until this is fixed"
        return "research", f"Self-test ({e.expected}): {status}, {verdict}. Self-tests are never traded.", {
            **waiting, "note": "Self-test only: never forward tested."}
    if status == "failed" and regime_specific(e):
        return "shadow", "Regime-specific: it passes everything except the volatility-regime check, so it is kept in shadow.", waiting
    if status == "failed":
        return "research", "Failed the gate: stays in research.", waiting
    if status == "insufficient":
        return "research", "Too few trades to judge: stays in research.", waiting
    if not ctx.data_eligible:
        return ("research", f"Qualified on {ctx.data_reason}, which is never eligible for money: stays in research. "
                "Run it again on your broker's MT5 export.", waiting)
    if ctx.kill_switch_on:
        return "shadow", "Qualified on your broker's data, but the kill switch is ON: nothing moves forward.", waiting
    if not ctx.approvals_clear:
        return "shadow", "Qualified on your broker's data. Waiting for your YES on pending changes.", waiting
    if not ctx.risk_ok:
        return "shadow", f"Qualified on your broker's data, but the minimum lot does not fit the risk limits ({ctx.risk_note}).", waiting
    return ("forward_test", f"Forward test: 0 of {span} trades at minimum lot, run by its own fixed-rule EA.",
            {**waiting, "note": "Waiting for the EA to report trades."})


def entry_decision(*, kill_switch_on: bool, loss_stops: list[str], qualified: bool, data_red: bool, risk_rules: list[str]) -> dict:
    if kill_switch_on or loss_stops:
        return {"decision": "block", "why": ["kill_switch"] * kill_switch_on + list(loss_stops)}
    if not qualified:
        return {"decision": "block", "why": ["not_qualified"]}
    if data_red:
        return {"decision": "pause", "why": ["data_red"]}
    if risk_rules:
        return {"decision": "block", "why": list(risk_rules)}
    return {"decision": "allow", "why": []}


def data_eligibility(e: RuleEvaluation, dataset) -> tuple[bool, str]:
    sources = {s: dataset[s][1]["source"] for s in e.symbols if s in dataset}
    if sources and all(src == "mt5_export" for src in sources.values()):
        return True, "your broker's MT5 data"
    if all(src == "synthetic" for src in sources.values()):
        return False, "demo data"
    other = [s for s, src in sources.items() if src != "mt5_export"]
    return False, f"data that is not your MT5 export ({', '.join(other)})"


def gate_counts(evaluations: list[RuleEvaluation]) -> Counter:
    return Counter(e.gate.status for e in evaluations)


def self_tests_ok(evaluations: list[RuleEvaluation]) -> bool | None:
    verdicts = [self_test_verdict(e) for e in evaluations if e.self_test]
    ran = [v for v in verdicts if v is not None]
    return None if not ran else all(ran)


VERB = {"qualified": "qualified", "failed": "failed", "insufficient": "had too few trades", "blocked": "was blocked"}


def short_name(e: RuleEvaluation) -> str:
    name = e.name.removeprefix("Self-test: ").split(" (")[0]
    return f"the {name}" if name[:1].islower() else name


def supervisor_summary(evaluations: list[RuleEvaluation], checks: list[dict], self_tests: list[dict] | None = None) -> tuple[str, str]:
    rules = [e for e in evaluations if not e.self_test]
    tests = [e for e in evaluations if e.self_test]
    counts = gate_counts(rules)
    head = f"{counts['qualified']} of {len(rules)} rule agents qualified"
    caught = [f"{counts[s]} {label}" for s, label in (("failed", "failed the gate"), ("insufficient", "too strict to judge")) if counts[s]]
    caught += [f"blocked {n} ({kind})" for kind, n in Counter(blocked_kind(e) for e in rules if e.gate.status == "blocked").items()]
    summary = head + (f" ({'; '.join(caught)})." if caught else ".")
    ran = [e for e in tests if self_test_verdict(e) is not None]
    every = [t for t in (self_tests or []) if t["ok"] is not None]
    if ran or every:
        total = every or [{"ok": e.self_test_ok} for e in ran]
        ok = sum(1 for t in total if t["ok"])
        story = ", ".join(f"{short_name(e)} {VERB[e.gate.status]}" for e in ran)
        system = len(total) - len(ran)
        summary += f" Self-tests: {ok} of {len(total)} as expected ({story}{f', plus {system} system checks' if system else ''})."
    if len(ran) < len(tests):
        summary += f" {plural(len(tests) - len(ran), 'self-test')} could not run (missing data)."
    if self_tests_ok(evaluations) is False or any(x["status"] == "fail" and x["stage"] == "data" for x in checks):
        return "fail", summary
    if any(x["status"] in ("fail", "warn") for x in checks):
        return "warn", summary
    return "ok", summary


def research_checks(evaluations: list[RuleEvaluation], gate_cfg: dict) -> list[dict]:
    return c.stop_checks(evaluations) + c.strictness_checks(evaluations, gate_cfg["min_trades_holdout"]) + c.cost_checks(evaluations)


def validation_checks(evaluations: list[RuleEvaluation], gate_cfg: dict) -> list[dict]:
    return c.plan_checks(evaluations) + c.leak_checks(evaluations) + c.gate_checks(evaluations, gate_cfg["accuracy_bar"])
