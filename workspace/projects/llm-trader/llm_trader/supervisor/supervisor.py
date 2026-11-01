from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from llm_trader.models import RuleEvaluation
from llm_trader.supervisor import checks as c


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


def blocked_kind(e: RuleEvaluation) -> str:
    if not e.leak_check.passed:
        return "future-data leak"
    if not e.plan.valid:
        return "test plan missing or changed"
    if any(h.startswith("No data for") for h in e.hard_failures):
        return "missing data"
    if any(h.startswith(("Costs missing", "No symbol specification")) for h in e.hard_failures):
        return "costs missing"
    if any(h.startswith("Rejected signal") for h in e.hard_failures):
        return "signal without a stop"
    return "hard failure"


def assign_stage(e: RuleEvaluation, ctx: StageContext) -> tuple[str, str, dict]:
    span = f"{ctx.forward_min}-{ctx.forward_max}"
    waiting = {"trades": 0, "target_min": ctx.forward_min, "target_max": ctx.forward_max,
               "note": "Starts only after qualifying on your broker's data."}
    status = e.gate.status
    if status == "blocked":
        return "blocked", f"Blocked by the supervisor ({blocked_kind(e)}). Nothing moves forward until that is fixed.", waiting
    if status == "failed":
        return "research", "Failed the gate: stays in research.", waiting
    if status == "insufficient":
        return "research", "Too few trades to judge: stays in research.", waiting
    if e.control:
        return ("research", "Qualified: the gate found the planted pattern. This is the self-test on synthetic data, so it is never traded.",
                {**waiting, "note": "Self-test only: never forward tested."})
    if not ctx.data_eligible:
        return ("research", f"Qualified on {ctx.data_reason}, which is never eligible for money: stays in research. "
                "Run it again on your broker's MT5 export.", waiting)
    if ctx.kill_switch_on:
        return "shadow", "Qualified on your broker's data, but the kill switch is ON: nothing is sent.", waiting
    if not ctx.approvals_clear:
        return "shadow", "Qualified on your broker's data. Waiting for your YES on pending changes: nothing is sent until then.", waiting
    if not ctx.risk_ok:
        return "shadow", f"Qualified on your broker's data, but the minimum lot does not fit the risk limits ({ctx.risk_note}).", waiting
    return ("forward_test", f"Forward test: 0 of {span} trades at minimum lot.",
            {**waiting, "note": "Waiting for the MT5 bridge EA to report trades."})


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


def control_ok(evaluations: list[RuleEvaluation]) -> bool | None:
    controls = [e for e in evaluations if e.control]
    return None if not controls else all(e.gate.status == "qualified" for e in controls)


def supervisor_summary(evaluations: list[RuleEvaluation], checks: list[dict]) -> tuple[str, str]:
    counts = gate_counts(evaluations)
    qualified = [e for e in evaluations if e.gate.status == "qualified"]
    real = [e for e in qualified if not e.control]
    if qualified and not real:
        head = f"{len(qualified)} of {len(evaluations)} qualified (the self-test only)."
    else:
        head = f"{len(qualified)} of {len(evaluations)} qualified."
    caught = Counter(blocked_kind(e) for e in evaluations if e.gate.status == "blocked")
    parts = [f"blocked {n} ({kind})" for kind, n in caught.items()]
    if counts["insufficient"]:
        parts.append(f"{counts['insufficient']} too strict to judge")
    if counts["failed"]:
        parts.append(f"{counts['failed']} failed the gate")
    summary = head + (" Caught: " + "; ".join(parts) + "." if parts else "")
    if control_ok(evaluations) is False or any(x["status"] == "fail" and x["stage"] == "data" for x in checks):
        return "fail", summary
    if any(x["status"] in ("fail", "warn") for x in checks):
        return "warn", summary
    return "ok", summary


def research_checks(evaluations: list[RuleEvaluation], gate_cfg: dict) -> list[dict]:
    return c.stop_checks(evaluations) + c.strictness_checks(evaluations, gate_cfg["min_trades_holdout"]) + c.cost_checks(evaluations)


def validation_checks(evaluations: list[RuleEvaluation], gate_cfg: dict) -> list[dict]:
    return c.plan_checks(evaluations) + c.leak_checks(evaluations) + c.gate_checks(evaluations, gate_cfg["accuracy_bar"])
