from __future__ import annotations

from llm_trader.signals.base import SignalRule
from llm_trader.signals.control_planted import ControlPlanted
from llm_trader.signals.demo_rule_a import DemoRuleA
from llm_trader.signals.demo_rule_b import DemoRuleB
from llm_trader.signals.leaky import Leaky
from llm_trader.signals.tight_target import TightTarget
from llm_trader.signals.trend_pullback import TrendPullback

RULE_CLASSES: tuple[type[SignalRule], ...] = (ControlPlanted, DemoRuleA, DemoRuleB, TrendPullback, TightTarget, Leaky)


def all_rules() -> list[SignalRule]:
    return [cls() for cls in RULE_CLASSES]


def get_rule(rule_id: str) -> SignalRule:
    for cls in RULE_CLASSES:
        if cls.rule_id == rule_id:
            return cls()
    raise KeyError(f"Unknown rule {rule_id!r}")
