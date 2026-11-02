from __future__ import annotations

from llm_trader.signals.demo_rule_a import DemoRuleA


class ControlPlanted(DemoRuleA):
    rule_id = "control_planted"
    name = "Self-test: planted pattern"
    version = "2"
    default_symbols = ("CTRL-SYN",)
    control = True
    self_test = True
    expected = "must qualify"
    description = (
        "Fades moves beyond the previous day's high or low on CTRL-SYN, a synthetic symbol where exactly this "
        "pattern was planted on purpose. Stop beyond that bar's extreme, target 0.5R, exit after 16 bars at most."
    )
    demo_note = (
        "Harness self-test: proves the gate can recognise a real pattern when one exists. The pattern is planted to "
        "win about 6 trades in 7 on any seed, so the test does not hang on lucky data. It is never a trading idea and "
        "never eligible for money."
    )
