from __future__ import annotations

from dataclasses import dataclass

from llm_trader.signals.base import SignalRule

LANES = ("supervisor", "data", "research", "context", "validation", "risk", "monitor", "report", "planned")
SELF_TEST_ROLES = {
    "must qualify": "Self-test, must qualify: finds a pattern planted in synthetic {symbols}, proving the gate can detect a real edge.",
    "must fail": "Self-test, must fail: wins most trades but loses money after costs, proving a high win rate alone is not an edge.",
    "must be blocked": "Self-test, must be blocked: peeks at the next bar on purpose, proving the leak check catches look-ahead.",
}


@dataclass(frozen=True)
class AgentDef:
    id: str
    name: str
    lane: str
    kind: str
    role: str
    rule_id: str | None = None
    control: bool = False
    planned: bool = False


def _core(bar: float, forward_min: int, forward_max: int) -> dict[str, AgentDef]:
    return {
        "supervisor": AgentDef("supervisor", "Supervisor", "supervisor", "code+llm",
                               "Checks every stage and applies the decision rule: which agents may move forward, what is paused "
                               "or blocked. Never trades."),
        "data": AgentDef("data", "Data Steward", "data", "code",
                         "Checks where the prices come from, missing bars, spikes and spreads, and compares a second source."),
        "event_tagger": AgentDef("event_tagger", "Event-risk tagger", "context", "llm",
                                 "Asks one narrow question per symbol: a high-impact event within 2 hours? 3 samples; pause only if all agree."),
        "regime": AgentDef("regime", "Regime agent", "context", "code",
                           "Measures each symbol's volatility tercile (H1 ATR) and trend (EMA 20 vs 50). Code only, no AI."),
        "validation": AgentDef("validation", "Validation lab", "validation", "code",
                               f"Runs the {bar:.0%} gate: a plan locked in advance, never-seen months, the last 3 months, real and "
                               "1.5× costs, random entries, volatility regimes, a correction for many tries and a leak check."),
        "risk": AgentDef("risk", "Risk engine", "risk", "code",
                         "Keeps one portfolio limit in % of equity: per trade, open risk, clusters counted as one bet, margin, "
                         "loss stops, activity limits and blackouts. Writes only pause advisories and the kill flag."),
        "monitor": AgentDef("monitor", "Monitor", "monitor", "code",
                            f"Watches the kill switch, loss stops and would-be phone alerts; tracks forward tests ({forward_min}-"
                            f"{forward_max} trades at minimum lot) once an EA reports trades."),
        "report": AgentDef("report", "Reporter", "report", "code+llm",
                           "Writes the morning report in plain English. With AI on, Claude writes the review text; the numbers "
                           "always come from code."),
    }


PLANNED = (
    AgentDef("guardian_ea", "Guardian EA", "planned", "code",
             "Inside MT5 (Phase 1): a stop on every position within about 2 seconds, daily, weekly and overall loss stops, the "
             "kill switch and phone alerts, even when Python is down. Spec: mql5/GUARDIAN_SPEC.md.", planned=True),
    AgentDef("macro_bias", "Macro bias", "planned", "llm",
             "Later, shadow first: a daily macro view, scored on forward data only before it may influence anything.",
             planned=True),
    AgentDef("trade_vetter", "Trade vetter", "planned", "llm",
             "Later, shadow first: judges your EAs' trades after the fact, to learn which setups to skip.", planned=True),
    AgentDef("crypto_funding", "Crypto funding extremes", "planned", "code",
             "Later, shadow first: flags extreme crypto funding rates from public exchange data.", planned=True),
    AgentDef("research_assistant", "Research assistant", "planned", "llm",
             "Turns ideas into locked test plans for your YES. Every idea must pass the same gate on months it never saw.",
             planned=True),
)


def research_agent(rule: SignalRule) -> AgentDef:
    symbols = ", ".join(rule.symbols)
    if getattr(rule, "self_test", False):
        template = SELF_TEST_ROLES.get(rule.expected or "", "Self-test, {expected}: proves the test harness works.")
        role = template.format(symbols=symbols, expected=rule.expected) + " Never traded."
    else:
        role = f"Tests one fixed rule on {symbols} ({rule.timeframe}). Finds signals; never trades."
    return AgentDef(rule.rule_id, rule.name, "research", "code", role, rule_id=rule.rule_id, control=rule.control)


def agent_defs(rules: list[SignalRule], bar: float = 0.8, forward_min: int = 30, forward_max: int = 40) -> list[AgentDef]:
    core = _core(bar, forward_min, forward_max)
    return [
        core["supervisor"], core["data"], *[research_agent(r) for r in rules], core["event_tagger"], core["regime"],
        core["validation"], core["risk"], core["monitor"], core["report"], *PLANNED,
    ]
