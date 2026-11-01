from __future__ import annotations

from dataclasses import dataclass

from llm_trader.signals.base import SignalRule


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
                               "Checks every stage and decides which agents may move forward. Never trades."),
        "data": AgentDef("data", "Data Agent", "data", "code",
                         "Checks where the prices come from, missing bars, spikes and spreads, and compares a second source."),
        "validation": AgentDef("validation", "Validation Agent", "validation", "code",
                               f"Runs the {bar:.0%} gate: a plan locked in advance, never-seen months, the last 3 months, "
                               "real costs, random entries and a future-data leak check."),
        "risk": AgentDef("risk", "Risk Agent", "risk", "code",
                         "Keeps one risk and margin limit for all agents, counts correlated symbols as one bet, allows the "
                         "minimum lot only and writes the bridge file."),
        "monitor": AgentDef("monitor", "Monitor Agent", "monitor", "code",
                            f"Watches the kill switch and tracks forward tests ({forward_min}-{forward_max} trades at minimum lot). "
                            "Waits for trades reported by the EA."),
        "report": AgentDef("report", "Report Agent", "report", "code+llm",
                           "Writes the morning report in plain English. With AI on, Claude writes the review text; "
                           "the numbers always come from code."),
    }


PLANNED = (
    AgentDef("news_calendar", "News & Calendar Agent", "planned", "llm",
             "Will flag high-impact news so the fixed rules can stand aside.", planned=True),
    AgentDef("research_scout", "Research Scout", "planned", "llm",
             "Will suggest new rule ideas. Every idea must be locked in a plan and pass the same gate before it counts.",
             planned=True),
    AgentDef("mt5_bridge_ea", "MT5 Bridge EA", "planned", "code",
             "A fixed-rule EA on your PC or a broker VPS: reads the bridge file and trades the minimum lot, always with "
             "the stop attached.", planned=True),
)


def research_agent(rule: SignalRule) -> AgentDef:
    if rule.control:
        role = f"Self-test: tests a pattern planted in synthetic {', '.join(rule.symbols)} to prove the gate can find a real edge."
    else:
        role = f"Tests one fixed rule on {', '.join(rule.symbols)} ({rule.timeframe}). Finds signals; never trades."
    return AgentDef(rule.rule_id, rule.name, "research", "code", role, rule_id=rule.rule_id, control=rule.control)


def agent_defs(rules: list[SignalRule], bar: float = 0.8, forward_min: int = 30, forward_max: int = 40) -> list[AgentDef]:
    core = _core(bar, forward_min, forward_max)
    return [
        core["supervisor"], core["data"], *[research_agent(r) for r in rules],
        core["validation"], core["risk"], core["monitor"], core["report"], *PLANNED,
    ]
