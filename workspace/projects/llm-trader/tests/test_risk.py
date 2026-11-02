import math

import numpy as np
import pandas as pd
import pytest
from conftest import make_spec

from llm_trader.config import SettingsError, validate_settings
from llm_trader.models import Signal
from llm_trader.risk.blackouts import Event, symbol_currencies
from llm_trader.risk.engine import Book, Entry, Group, Market, Position, RiskEngine, correlation_matrix
from llm_trader.risk.killswitch import KillSwitch, enforce_loss_stops
from llm_trader.risk.limits import Blackouts, Limits

NOW = pd.Timestamp("2026-03-03 10:00", tz="UTC")
USD = Group("USD", "US dollar", {"EURUSD": -1, "GBPUSD": -1, "USDJPY": 1, "XAUUSD": -1})
RISK_ON = Group("RISK_ON", "Risk-on", {"US500": 1, "BTCUSD": 1})
GOLD = 2650.0
B1_KEYS = [
    "risk_per_trade_pct", "risk_per_trade_cap_pct", "max_open_risk_pct", "max_cluster_risk_pct", "max_margin_use_pct",
    "daily_stop_pct", "weekly_stop_pct", "overall_kill_pct", "max_open_positions", "max_entries_per_day",
    "min_minutes_between_entries_per_symbol", "spread_skip_multiple", "pause_after_full_stops", "blackouts",
]


def specs() -> dict:
    fx = dict(point=0.00001, digits=5, contract_size=100_000, tick_size=0.00001, tick_value=1.0, margin_per_min_lot=36.0)
    return {
        "XAUUSD": make_spec(name="XAUUSD", margin_per_min_lot=88.0),
        "EURUSD": make_spec(name="EURUSD", **fx),
        "GBPUSD": make_spec(name="GBPUSD", **fx),
        "US500": make_spec(name="US500", tick_value=0.01, min_lot=0.1, lot_step=0.1, margin_per_min_lot=29.0),
    }


def engine(groups=(USD, RISK_ON), **limits) -> RiskEngine:
    return RiskEngine(Limits(**limits), list(groups), specs())


def book(equity: float = 1000.0, **kwargs) -> Book:
    return Book(equity=equity, peak_equity=kwargs.pop("peak_equity", equity), **kwargs)


def market(now=NOW, **kwargs) -> Market:
    return Market(now=now, calendar_updated_at=kwargs.pop("calendar_updated_at", now - pd.Timedelta(hours=1)), **kwargs)


def gold(side: int = 1, stop_points: float = 450, rule: str = "r1", symbol: str = "XAUUSD", price: float = GOLD) -> Signal:
    return Signal(rule, symbol, NOW, side, price - side * stop_points * 0.01, None, 16)


def position(symbol: str, risk: float = 2.0, margin: float = 30.0, side: int = 1, rule: str = "r2") -> Position:
    return Position(symbol, side, risk, margin, rule)


def rules(decision) -> list[str]:
    return decision.rules


def test_a_clean_signal_passes_every_rule():
    decision = engine().check(gold(), GOLD, book(), market())
    assert decision.ok and decision.rules == [] and decision.reasons == []
    assert decision.lots == 0.01 and decision.risk_money == pytest.approx(4.5) and decision.risk_pct == pytest.approx(0.45)


@pytest.mark.parametrize("stop", [None, math.nan])
def test_signal_without_stop_is_rejected(stop):
    decision = engine().check(Signal("r1", "XAUUSD", NOW, 1, stop, None, 16), GOLD, book(), market())
    assert not decision.ok and rules(decision) == ["no_stop"]
    assert decision.reasons == ["No stop-loss: every entry needs a stop from the first second."]


def test_stop_on_the_wrong_side_is_rejected():
    decision = engine().check(Signal("r1", "XAUUSD", NOW, 1, GOLD + 5, None, 16), GOLD, book(), market())
    assert rules(decision) == ["stop_side"]


def test_unknown_symbol_or_empty_account_is_rejected():
    assert rules(engine().check(gold(symbol="NOPE"), GOLD, book(), market())) == ["no_spec"]
    assert rules(engine().check(gold(), GOLD, book(equity=0.0), market())) == ["no_equity"]


def test_size_targets_half_a_percent_and_rounds_down():
    decision = engine().check(gold(), GOLD, book(equity=10_000), market())
    assert decision.ok and decision.lots == pytest.approx(0.11)
    assert decision.risk_pct == pytest.approx(0.495) and decision.risk_pct <= 0.5


def test_minimum_lot_inside_the_cap_is_used():
    decision = engine().check(gold(), GOLD, book(equity=600), market())
    assert decision.ok and decision.lots == 0.01 and decision.risk_pct == pytest.approx(0.75)


def test_minimum_lot_above_the_cap_is_skipped_never_rounded_up():
    decision = engine().check(gold(), GOLD, book(equity=400), market())
    assert rules(decision) == ["risk_cap"] and decision.lots is None
    assert "1.12% of equity" in decision.reasons[0] and "never rounded up" in decision.reasons[0]


def test_open_risk_is_one_limit_for_all_positions():
    assert engine().check(gold(), GOLD, book(positions=[position("US500", risk=10.0)]), market()).ok
    decision = engine().check(gold(), GOLD, book(positions=[position("US500", risk=11.0)]), market())
    assert rules(decision) == ["open_risk_cap"] and "1.55% of equity" in decision.reasons[0]


def test_cluster_counts_hedges_as_risk_too():
    held = [position("EURUSD", risk=5.0, side=1)]
    assert engine().check(gold(side=-1), GOLD, book(positions=held), market()).ok
    hedge = engine().check(gold(side=-1), GOLD, book(positions=[position("EURUSD", risk=6.0, side=1)]), market())
    assert rules(hedge) == ["cluster_cap"] and "US dollar cluster would carry 1.05%" in hedge.reasons[0]
    assert "no credit for hedges" in hedge.reasons[0]


def test_symbol_outside_every_cluster_is_its_own_cluster():
    us500 = Signal("r1", "US500", NOW, 1, 5790.0, None, 16)
    lone = engine(groups=(USD,), risk_per_trade_cap_pct=1.0)
    assert lone.check(us500, 5800.0, book(), market()).ok
    decision = lone.check(us500, 5800.0, book(positions=[position("US500", risk=9.5)]), market())
    assert "cluster_cap" in rules(decision)


def test_margin_after_the_trade_stays_under_30_percent():
    assert engine().check(gold(), GOLD, book(positions=[position("US500", risk=1.0, margin=200.0)]), market()).ok
    decision = engine().check(gold(), GOLD, book(positions=[position("US500", risk=1.0, margin=220.0)]), market())
    assert rules(decision) == ["margin_cap"] and "31% of equity" in decision.reasons[0]


def test_daily_stop_reached_locks_until_the_reset():
    decision = engine().check(gold(), GOLD, book(daily_loss_pct=2.0), market())
    assert rules(decision) == ["daily_stop"] and "locked until the daily reset" in decision.reasons[0]


def test_new_trade_must_fit_inside_the_daily_stop():
    tight = book(daily_loss_pct=1.2, positions=[position("US500", risk=4.0)])
    decision = engine().check(gold(), GOLD, tight, market())
    assert rules(decision) == ["daily_stop"] and "could be breached" in decision.reasons[0]
    assert engine().check(gold(), GOLD, book(daily_loss_pct=1.0), market(gap_buffer_pct=0.5)).ok
    assert rules(engine().check(gold(), GOLD, book(daily_loss_pct=1.0), market(gap_buffer_pct=0.6))) == ["daily_stop"]


def test_weekly_stop():
    assert rules(engine().check(gold(), GOLD, book(weekly_loss_pct=4.0), market())) == ["weekly_stop"]
    assert rules(engine().check(gold(), GOLD, book(weekly_loss_pct=3.6), market())) == ["weekly_stop"]
    assert engine().check(gold(), GOLD, book(weekly_loss_pct=3.5), market()).ok


def test_overall_kill_from_the_equity_peak():
    decision = engine().check(gold(), GOLD, book(equity=940.0, peak_equity=1000.0), market())
    assert "overall_kill" in rules(decision) and "6.0% lost from the equity peak" in decision.reasons[0]
    near = book(equity=950.0, peak_equity=1000.0, positions=[position("US500", risk=6.0)])
    assert rules(engine().check(gold(), GOLD, near, market())) == ["overall_kill"]
    assert engine().check(gold(), GOLD, book(equity=950.0, peak_equity=1000.0), market()).ok


def test_at_most_two_open_positions_hand_trades_included():
    held = [position("US500", risk=1.0, rule=""), position("BTCUSD", risk=1.0)]
    decision = engine(max_open_risk_pct=10.0, max_cluster_risk_pct=10.0).check(gold(), GOLD, book(positions=held), market())
    assert rules(decision) == ["max_positions"] and "hand trades included" in decision.reasons[0]


def test_at_most_four_entries_a_day():
    yesterday = [Entry("EURUSD", NOW - pd.Timedelta(days=1)) for _ in range(4)]
    assert engine().check(gold(), GOLD, book(entries=yesterday), market()).ok
    today = [Entry(s, NOW - pd.Timedelta(hours=h)) for s, h in (("EURUSD", 9), ("GBPUSD", 8), ("US500", 7), ("BTCUSD", 6))]
    assert rules(engine().check(gold(), GOLD, book(entries=today), market())) == ["entries_per_day"]


def test_one_entry_per_symbol_every_four_hours():
    recent = [Entry("XAUUSD", NOW - pd.Timedelta(minutes=239))]
    decision = engine().check(gold(), GOLD, book(entries=recent), market())
    assert rules(decision) == ["symbol_cooldown"] and "1 more to wait" in decision.reasons[0]
    assert engine().check(gold(), GOLD, book(entries=[Entry("XAUUSD", NOW - pd.Timedelta(minutes=240))]), market()).ok
    assert engine().check(gold(), GOLD, book(entries=[Entry("EURUSD", NOW - pd.Timedelta(minutes=5))]), market()).ok


def test_spread_wider_than_twice_the_hours_median_is_skipped():
    assert rules(engine().check(gold(), GOLD, book(), market(spread_points=41, median_spread_points=20))) == ["spread"]
    assert engine().check(gold(), GOLD, book(), market(spread_points=40, median_spread_points=20)).ok
    assert engine().check(gold(), GOLD, book(), market(spread_points=99, median_spread_points=None)).ok


def test_three_full_stops_in_a_row_pause_the_rule():
    assert rules(engine().check(gold(rule="r1"), GOLD, book(full_stop_streaks={"r1": 3}), market())) == ["full_stop_streak"]
    assert engine().check(gold(rule="r1"), GOLD, book(full_stop_streaks={"r1": 2, "other": 5}), market()).ok


def test_news_blackout_is_15_minutes_for_high_impact_news():
    def at(minutes, currency="USD", name="US retail sales", impact="high"):
        return market(events=[Event(NOW + pd.Timedelta(minutes=minutes), currency, name, impact)])

    assert rules(engine().check(gold(), GOLD, book(), at(10))) == ["news_blackout"]
    assert rules(engine().check(gold(), GOLD, book(), at(-15))) == ["news_blackout"]
    assert engine().check(gold(), GOLD, book(), at(16)).ok
    assert engine().check(gold(), GOLD, book(), at(10, impact="medium")).ok
    assert engine().check(gold(), GOLD, book(), at(10, currency="JPY", name="BoJ rate decision")).ok


@pytest.mark.parametrize("name", ["US CPI (m/m)", "FOMC statement", "Non-Farm Payrolls"])
def test_major_news_blackout_is_30_minutes(name):
    decision = engine().check(gold(), GOLD, book(), market(events=[Event(NOW + pd.Timedelta(minutes=25), "USD", name)]))
    assert rules(decision) == ["news_blackout"] and "within 30 minutes" in decision.reasons[0]


@pytest.mark.parametrize("utc_time, blocked", [
    ("2026-11-03 21:50", True), ("2026-11-03 21:40", False), ("2026-11-03 22:15", False),
    ("2026-07-07 20:50", True), ("2026-07-07 21:50", False),
])
def test_rollover_blackout_follows_new_york_time(utc_time, blocked):
    now = pd.Timestamp(utc_time, tz="UTC")
    decision = engine().check(gold(), GOLD, book(), market(now=now))
    assert ("rollover" in rules(decision)) is blocked


@pytest.mark.parametrize("utc_time, blocked", [("2026-03-06 20:00", True), ("2026-03-06 19:59", False), ("2026-03-05 21:00", False)])
def test_no_entries_on_friday_after_20_utc(utc_time, blocked):
    decision = engine().check(gold(), GOLD, book(), market(now=pd.Timestamp(utc_time, tz="UTC")))
    assert ("friday_cutoff" in rules(decision)) is blocked


def test_stale_or_missing_calendar_blocks_entries():
    assert rules(engine().check(gold(), GOLD, book(), market(calendar_updated_at=NOW - pd.Timedelta(hours=25)))) == ["calendar_stale"]
    missing = Market(now=NOW)
    decision = engine().check(gold(), GOLD, book(), missing)
    assert rules(decision) == ["calendar_stale"] and "calendar is missing" in decision.reasons[0]
    assert engine().check(gold(), GOLD, book(), market(calendar_updated_at=NOW - pd.Timedelta(hours=23))).ok


def test_kill_switch_blocks_everything():
    decision = engine().check(gold(), GOLD, book(kill_switch_on=True), market())
    assert rules(decision) == ["kill_switch"] and decision.reasons[0].startswith("Kill switch is ON")


def test_every_failed_rule_is_listed():
    crowded = book(daily_loss_pct=2.5, kill_switch_on=True, full_stop_streaks={"r1": 4})
    decision = engine().check(gold(), GOLD, crowded, market(now=pd.Timestamp("2026-03-06 20:30", tz="UTC")))
    assert rules(decision)[:2] == ["kill_switch", "daily_stop"] and {"full_stop_streak", "friday_cutoff"} <= set(rules(decision))
    assert decision.rule == "kill_switch"


def test_daily_stop_alerts_but_weekly_and_overall_turn_the_kill_switch_on(tmp_path):
    limits = Limits()
    switch = KillSwitch(tmp_path / "killswitch.json", tmp_path / "bridge" / "kill.flag")
    assert enforce_loss_stops(switch, book(daily_loss_pct=1.9), limits) == []
    [(code, message)] = enforce_loss_stops(switch, book(daily_loss_pct=2.0), limits)
    assert code == "daily_stop" and "until the daily reset" in message and not switch.on
    hits = enforce_loss_stops(switch, book(weekly_loss_pct=4.2), limits)
    assert [c for c, _ in hits] == ["weekly_stop"] and switch.on and "Weekly stop: 4.2%" in switch.state()["reason"]
    assert switch.flag_path.exists()
    other = KillSwitch(tmp_path / "other.json")
    hits = enforce_loss_stops(other, book(equity=930.0, peak_equity=1000.0), limits)
    assert [c for c, _ in hits] == ["overall_kill"] and other.on and "7.0% below its peak" in other.state()["reason"]


def test_limits_follow_the_plan_defaults(settings):
    limits = Limits.from_settings(settings["risk"])
    assert limits == Limits()
    assert list(limits.to_dict()) == B1_KEYS
    assert limits.to_dict()["blackouts"] == {
        "news_minutes": 15, "major_news_minutes": 30, "rollover": "16:45-17:15 America/New_York",
        "friday_cutoff_utc": "20:00", "calendar_max_age_hours": 24,
    }
    assert Limits.from_settings({"risk_per_trade_pct": 0.25, "unknown": 1, "blackouts": {"news_minutes": 20}}) == Limits(
        risk_per_trade_pct=0.25, blackouts=Blackouts(news_minutes=20))


@pytest.mark.parametrize("change, message", [
    ({"risk_per_trade_pct": 1.5}, "risk_per_trade_pct must not be above risk_per_trade_cap_pct"),
    ({"blackouts": {"rollover": "16:45 to 17:15 New York"}}, "HH:MM-HH:MM Area/City"),
    ({"blackouts": {"rollover": "16:45-17:15 Mars/Olympus"}}, "unknown time zone"),
    ({"blackouts": {"friday_cutoff_utc": "8pm"}}, "HH:MM"),
    ({"spread_skip_multiple": 1.0}, "greater than 1"),
])
def test_bad_risk_settings_are_refused(settings, change, message):
    bad = {**settings, "risk": {**settings["risk"], **change}}
    with pytest.raises(SettingsError, match=message):
        validate_settings(bad)


def test_usage_and_cluster_rows():
    e = engine()
    held = book(positions=[position("EURUSD", risk=3.0, margin=36.0), position("US500", risk=2.0, margin=29.0, side=-1)], daily_loss_pct=0.5)
    assert e.usage(held) == {"open_risk_pct": 0.5, "margin_use_pct": 6.5, "daily_loss_pct": 0.5, "open_positions": 2}
    usd, risk_on = e.group_rows(held)
    assert usd == {"id": "USD", "name": "US dollar", "members": USD.members, "positions": 1, "risk_pct": 0.3, "limit_pct": 1.0}
    assert risk_on["positions"] == 1 and risk_on["risk_pct"] == 0.2


def test_symbol_currencies():
    assert symbol_currencies("XAUUSD.a") == {"XAU", "USD"}
    assert symbol_currencies("EURUSD") == {"EUR", "USD"}
    assert symbol_currencies("US500") == {"USD"}
    assert symbol_currencies("CTRL-SYN") == frozenset()


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
