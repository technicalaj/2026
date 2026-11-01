from __future__ import annotations

from llm_trader.signals.sweep_fade import SweepFade


class ControlPlanted(SweepFade):
    rule_id = "control_planted"
    name = "Self-test: planted pattern"
    default_symbols = ("CTRL-SYN",)
    control = True
    description = (
        "Fades sweeps of the previous day's high or low on CTRL-SYN, a synthetic symbol where exactly this "
        "pattern was planted on purpose. Stop beyond the sweep's extreme, target 1R, exit after 16 bars at most."
    )
    demo_note = (
        "Harness self-test: proves the gate can recognise a real pattern when one exists. It is never a trading "
        "idea and never eligible for money."
    )
