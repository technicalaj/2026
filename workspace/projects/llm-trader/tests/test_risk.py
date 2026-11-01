import math

import numpy as np
import pandas as pd
import pytest
from conftest import make_spec

from llm_trader.models import Signal
from llm_trader.risk.engine import Account, Group, Limits, Position, RiskEngine, correlation_matrix
from llm_trader.risk.killswitch import KillSwitch, enforce_daily_loss

T = pd.Timestamp("2026-03-03 10:00", tz="UTC")
USD = Group("USD", "US dollar", {"EURUSD": -1, "GBPUSD": -1, "USDJPY": 1, "XAUUSD": -1})
GOLD = 2650.0


def specs() -> dict:
    fx = dict(point=0.00001, digits=5, contract_size=100_000, tick_size=0.00001, tick_value=1.0, margin_per_min_lot=36.0)
    return {
        "XAUUSD": make_spec(name="XAUUSD", margin_per_min_lot=88.0),
        "EURUSD": make_spec(name="EURUSD", **fx),
        "GBPUSD": make_spec(name="GBPUSD", **fx),
        "USDJPY": make_spec(name="USDJPY", point=0.001, digits=3, tick_size=0.001, tick_value=0.66, margin_per_min_lot=33.3),
        "US500": make_spec(name="US500", tick_value=0.01, min_lot=0.1, margin_per_min_lot=29.0),
    }


def engine(balance: float = 1000.0, **limits) -> RiskEngine:
    return RiskEngine(Account(balance), Limits(**limits), [USD], specs())


def signal(symbol: str, side: int, stop, rule: str = "r1") -> Signal:
    return Signal(rule, symbol, T, side, stop, None, 16)


def position(symbol: str, side: int, risk: float = 2.0, margin: float = 30.0) -> Position:
    return Position(symbol, side, risk, margin)


@pytest.mark.parametrize("stop", [None, math.nan])
def test_signal_without_stop_is_rejected(stop):
    decision = engine().check(signal("XAUUSD", 1, stop), GOLD)
    assert not decision.ok
    assert decision.reasons == ["No stop-loss: every signal needs a stop from the first second."]


def test_stop_on_the_wrong_side_is_rejected():
    decision = engine().check(signal("XAUUSD", 1, GOLD + 5), GOLD)
    assert not decision.ok and "wrong side" in decision.reasons[0]


def test_min_lot_risk_inside_the_limit_passes():
    decision = engine().check(signal("XAUUSD", 1, GOLD - 4.5), GOLD)
    assert decision.ok and decision.reasons == []
    assert decision.lots == 0.01
    assert decision.risk_money == pytest.approx(4.5)
    assert decision.risk_pct == pytest.approx(0.45)


def test_min_lot_risk_above_the_limit_is_rejected_on_a_small_account():
    decision = engine(balance=200.0).check(signal("XAUUSD", 1, GOLD - 4.5), GOLD)
    assert not decision.ok
    assert "risks 2.25% of the account" in decision.reasons[0] and "limit is 1% per trade" in decision.reasons[0]


def test_margin_limit_counts_open_positions():
    e = engine(balance=200.0, risk_per_trade_pct=5.0, max_open_risk_pct=10.0)
    assert e.check(signal("EURUSD", 1, 1.0800), 1.0850).ok
    decision = e.check(signal("XAUUSD", -1, GOLD + 4.5), GOLD, [position("GBPUSD", 1, margin=20.0)])
    assert not decision.ok
    assert any("Margin would reach 54%" in r for r in decision.reasons)


def test_group_limit_uses_signs_long_eurusd_is_short_usd():
    e = engine(max_open_risk_pct=10.0)
    held = [position("EURUSD", 1)]
    same_bet = e.check(signal("XAUUSD", 1, GOLD - 4.5), GOLD, held)
    assert not same_bet.ok
    assert "US dollar group already holds 1 short US dollar position(s) (long EURUSD)" in same_bet.reasons[0]
    assert e.check(signal("XAUUSD", -1, GOLD + 4.5), GOLD, held).ok
    assert e.check(signal("USDJPY", 1, 152.0), 152.5, held).ok
    assert not e.check(signal("USDJPY", -1, 153.0), 152.5, held).ok


def test_ungrouped_symbol_is_its_own_group():
    e = engine(max_open_risk_pct=10.0, risk_per_trade_pct=5.0)
    held = [position("US500", 1)]
    assert not e.check(signal("US500", 1, 5790.0), 5800.0, held).ok
    assert e.check(signal("US500", -1, 5810.0), 5800.0, held).ok


def test_group_limit_can_allow_more_positions():
    e = engine(max_open_risk_pct=10.0, max_positions_per_group=2)
    assert e.check(signal("XAUUSD", 1, GOLD - 4.5), GOLD, [position("EURUSD", 1)]).ok
    assert not e.check(signal("XAUUSD", 1, GOLD - 4.5), GOLD, [position("EURUSD", 1), position("GBPUSD", 1)]).ok


def test_total_open_risk_is_one_limit_for_all_agents():
    e = engine(max_positions_per_group=10)
    assert e.check(signal("XAUUSD", 1, GOLD - 4.5), GOLD, [position("US500", 1, risk=8.0)]).ok
    decision = e.check(signal("XAUUSD", 1, GOLD - 4.5), GOLD, [position("US500", 1, risk=16.0)])
    assert not decision.ok
    assert any("Open risk would reach 2.05%" in r and "portfolio limit is 2%" in r for r in decision.reasons)


def test_kill_switch_blocks_everything():
    decision = engine().check(signal("XAUUSD", 1, GOLD - 4.5), GOLD, kill_switch_on=True)
    assert not decision.ok and decision.reasons[0].startswith("Kill switch is ON")


def test_daily_loss_limit_blocks_and_turns_the_kill_switch_on(tmp_path):
    e = engine()
    blocked = e.check(signal("XAUUSD", 1, GOLD - 4.5), GOLD, daily_loss_pct=3.2)
    assert not blocked.ok and any("Daily loss limit reached" in r for r in blocked.reasons)
    switch = KillSwitch(tmp_path / "killswitch.json")
    assert not enforce_daily_loss(switch, 2.9, e.limits.max_daily_loss_pct)
    assert not switch.on
    assert enforce_daily_loss(switch, 3.2, e.limits.max_daily_loss_pct)
    assert switch.on and "Daily loss limit reached: 3.2%" in switch.state()["reason"]


def test_unknown_symbol_or_empty_account_is_rejected():
    assert "No symbol specification" in engine().check(signal("NOPE", 1, 1.0), 2.0).reasons[0]
    assert "balance must be above zero" in engine(balance=0.0).check(signal("XAUUSD", 1, GOLD - 1), GOLD).reasons[0]


def test_usage_and_group_rows():
    e = engine()
    held = [position("EURUSD", 1, risk=3.0, margin=36.0), position("US500", -1, risk=2.0, margin=29.0)]
    assert e.usage(held, daily_loss_pct=0.5) == {"open_risk_pct": 0.5, "margin_use_pct": 6.5, "daily_loss_pct": 0.5, "open_positions": 2}
    [usd] = e.group_rows(held)
    assert usd["id"] == "USD" and usd["positions"] == 1 and usd["risk_pct"] == 0.3 and usd["limit_pct"] == 1.0
    assert usd["members"] == USD.members


def test_min_lot_rows_explain_what_does_not_fit():
    e = engine(balance=200.0)
    gold = e.min_lot_row("XAUUSD", 450.0)
    assert gold["risk_at_min_lot"] == 4.5 and gold["risk_pct"] == pytest.approx(2.25)
    assert gold["ok"] is False and "above the 1% per-trade limit" in gold["note"]
    assert "needs 44% of the account as margin" not in gold["note"] and "uses 44% of the account as margin" in gold["note"]
    assert e.min_lot_row("XAUUSD", None) | {"note": None} == {
        "symbol": "XAUUSD", "min_lot": 0.01, "median_stop_points": None, "risk_at_min_lot": None, "risk_pct": None,
        "margin_at_min_lot": 88.0, "ok": None, "note": None,
    }
    roomy = engine(balance=10_000.0).min_lot_row("XAUUSD", 450.0)
    assert roomy["ok"] is True and roomy["note"] is None


def _walk(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n) * 0.001


def test_correlation_matrix_uses_last_90_days_of_hourly_returns():
    index = pd.date_range("2026-01-01", periods=120 * 96, freq="15min", tz="UTC")
    base = _walk(len(index), 1)
    recent = index > index[-1] - pd.Timedelta(days=90)
    follower = np.where(recent, base, -base) + _walk(len(index), 2) * 0.1
    frames = {
        "A": pd.DataFrame({"close": 100 * np.exp(np.cumsum(base))}, index=index),
        "B": pd.DataFrame({"close": 100 * np.exp(np.cumsum(follower))}, index=index),
        "C": pd.DataFrame({"close": 100 * np.exp(np.cumsum(-base))}, index=index),
        "D": pd.DataFrame({"close": 100 * np.exp(np.cumsum(_walk(len(index), 3)))}, index=index),
    }
    out = correlation_matrix(frames, days=90)
    assert out["symbols"] == ["A", "B", "C", "D"] and out["window"] == "last 90 days, H1 returns"
    m = out["matrix"]
    assert m[0][0] == 1.0 and m[0][1] > 0.9 and m[0][2] < -0.99 and abs(m[0][3]) < 0.15
    assert m[1][0] == m[0][1]


def test_correlation_matrix_on_demo_data_follows_the_dollar(demo):
    out = correlation_matrix({s: df for s, (df, _) in demo.items()})
    at = {s: i for i, s in enumerate(out["symbols"])}
    m = out["matrix"]
    assert m[at["EURUSD"]][at["GBPUSD"]] > 0.3
    assert m[at["EURUSD"]][at["USDJPY"]] < -0.2
    assert abs(m[at["CTRL-SYN"]][at["XAUUSD"]]) < 0.1


def test_correlation_matrix_handles_empty_input():
    assert correlation_matrix({}) == {"symbols": [], "matrix": [], "window": "last 90 days, H1 returns"}
