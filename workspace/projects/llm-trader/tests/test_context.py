import numpy as np
import pandas as pd
import pytest

from llm_trader.agents.context import (
    NO_PAUSE, PAUSE, Question, agreement, event_tagger, measured_label, mock_samples, questions, regime, split_answers,
    synthetic_calendar,
)
from llm_trader.config import EventTaggerSettings, RegimeSettings
from llm_trader.risk.blackouts import Event

T0 = pd.Timestamp("2026-11-02 04:00", tz="UTC")
SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "US500", "BTCUSD"]


def bars(close: np.ndarray, wick: np.ndarray, start="2026-06-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=len(close), freq="15min", tz="UTC", name="time")
    return pd.DataFrame({"open": close, "high": close + wick, "low": close - wick, "close": close}, index=index)


def walk(n: int, step_sigma: np.ndarray, drift: float = 0.0, seed: int = 3) -> np.ndarray:
    steps = np.random.default_rng(seed).standard_normal(n) * step_sigma + drift
    return 1000 + np.cumsum(steps)


def test_synthetic_calendar_is_labelled_and_follows_the_decision_time():
    events = synthetic_calendar(T0)
    assert all(e.name.endswith("(synthetic)") for e in events)
    assert [e.time for e in events][:2] == [T0 + pd.Timedelta(minutes=20), T0 + pd.Timedelta(minutes=40)]


def test_questions_pick_the_most_important_event_in_the_window():
    events = [
        Event(T0 + pd.Timedelta(minutes=10), "USD", "US home sales", "medium"),
        Event(T0 + pd.Timedelta(minutes=90), "USD", "US CPI", "medium"),
        Event(T0 + pd.Timedelta(minutes=50), "JPY", "BoJ speech", "high"),
        Event(T0 + pd.Timedelta(hours=3), "EUR", "ECB decision", "high"),
    ]
    asked = {q.symbol: q for q in questions(["XAUUSD", "USDJPY", "EURGBP", "US500"], events, T0, 2)}
    assert asked["XAUUSD"].event.name == "US CPI" and asked["XAUUSD"].truth == PAUSE
    assert asked["USDJPY"].event.name == "BoJ speech" and asked["USDJPY"].truth == PAUSE
    assert "EURGBP" not in asked
    calm = questions(["US500"], events[:1], T0, 2)
    assert [(q.event.name, q.truth) for q in calm] == [("US home sales", NO_PAUSE)]


def test_mock_samples_are_seeded():
    q = Question("XAUUSD", synthetic_calendar(T0)[0], PAUSE)
    assert mock_samples(q, 3, 0.0, 7) == [PAUSE] * 3
    assert mock_samples(q, 5, 0.3, 7) == mock_samples(q, 5, 0.3, 7)
    assert set(mock_samples(q, 50, 0.5, 7)) == {PAUSE, NO_PAUSE}


@pytest.mark.parametrize("verdicts, expected", [
    ([PAUSE] * 3, ("3 of 3", True)),
    ([PAUSE, PAUSE, NO_PAUSE], ("2 of 3", False)),
    ([NO_PAUSE, PAUSE, NO_PAUSE], ("2 of 3", False)),
    ([NO_PAUSE] * 3, ("3 of 3", False)),
])
def test_a_pause_needs_every_sample_to_agree(verdicts, expected):
    assert agreement(verdicts) == expected


def test_under_30_scored_calls_is_unmeasured():
    assert measured_label(0, 30) == "UNMEASURED" and measured_label(29, 30) == "UNMEASURED"
    assert measured_label(30, 30) == "30 scored calls"


def test_event_tagger_mock_is_shadow_unmeasured_and_disagrees_sometimes():
    tagger = event_tagger(SYMBOLS, T0, EventTaggerSettings())
    assert {k: tagger[k] for k in ("stage", "measured", "samples", "model")} == {
        "stage": "shadow", "measured": "UNMEASURED", "samples": 3, "model": "claude-haiku-5-5 (offline mock)"}
    assert tagger["note"] == "Self-test with seeded mock answers — not accuracy."
    assert [row["symbol"] for row in tagger["last"]] == SYMBOLS
    assert all(len(row["verdicts"]) == 3 and row["time"].endswith("Z") for row in tagger["last"])
    assert split_answers(tagger) > 0
    assert all(not row["pause"] for row in tagger["last"] if len(set(row["verdicts"])) > 1)
    assert any(row["pause"] for row in tagger["last"])
    assert event_tagger(SYMBOLS, T0, EventTaggerSettings()) == tagger


def test_regime_reads_trend_from_the_moving_averages():
    n = 120 * 96
    calm = np.full(n, 0.05)
    assert regime("UP", bars(walk(n, calm, drift=0.02), np.full(n, 0.2)), RegimeSettings())["trend"] == "up"
    assert regime("DOWN", bars(walk(n, calm, drift=-0.02), np.full(n, 0.2)), RegimeSettings())["trend"] == "down"
    flat = regime("FLAT", bars(1000 + np.sin(np.arange(n) / 3.0) * 0.01, np.full(n, 0.2)), RegimeSettings())
    assert flat["trend"] == "flat"


def test_regime_volatility_tercile_compares_the_same_hour_of_day():
    n = 120 * 96
    wild_end = np.where(np.arange(n) >= n - 96, 1.0, 0.2)
    calm_end = np.where(np.arange(n) >= n - 96, 0.02, 0.2)
    assert regime("WILD", bars(walk(n, np.full(n, 0.05)), wild_end), RegimeSettings())["vol_tercile"] == 3
    assert regime("CALM", bars(walk(n, np.full(n, 0.05)), calm_end), RegimeSettings())["vol_tercile"] == 1
    row = regime("X", bars(walk(n, np.full(n, 0.05)), np.full(n, 0.2)), RegimeSettings())
    assert set(row) == {"symbol", "vol_tercile", "trend"} and isinstance(row["vol_tercile"], int)


def test_regime_needs_enough_bars():
    assert regime("SHORT", bars(walk(200, np.full(200, 0.05)), np.full(200, 0.2)), RegimeSettings()) is None
