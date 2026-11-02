import numpy as np
import pandas as pd
import pytest
from conftest import make_bars, make_spec, signal_after

from llm_trader.costs import CostModel
from llm_trader.eval.backtest import simulate
from llm_trader.eval.random_baseline import atr_at_open
from llm_trader.eval.robustness import (
    positive_terciles, side_summary, stop_target_ratio, tercile_cuts, tercile_of, tercile_results, volatility_cuts,
    window_extra,
)
from llm_trader.models import Trade

T0 = pd.Timestamp("2026-03-02 08:00", tz="UTC")


def trade(r: float, side: int = 1, symbol: str = "TEST", entry_atr: float | None = 1.0, signal_price: float | None = 100.0,
          stop: float = 99.0, target: float | None = 100.5, day: int = 0) -> Trade:
    t = T0 + pd.Timedelta(days=day)
    return Trade("x", symbol, t, t, 100.0, stop, target, side, t, 100.0 + r, "time", r, 1.0, 0.0,
                 entry_atr=entry_atr, signal_price=signal_price)


def test_cost_model_scales_every_cost():
    scaled = CostModel(spread_multiplier=2.0).scaled(1.5)
    assert (scaled.spread_multiplier, scaled.slippage_multiplier, scaled.commission_multiplier) == (3.0, 1.5, 1.5)
    assert scaled.spread_source == "bar"


def test_higher_costs_lower_every_trades_r():
    df = make_bars([[100, 100, 100, 100], [100.0, 101.5, 99.8, 101.2], [101.2, 101.3, 100.0, 100.2]], spread=5)
    spec = make_spec(slippage_points=3, commission_per_lot=7.0)
    signals = [signal_after(df, 0, 1, stop=99.0, target=101.0), signal_after(df, 1, -1, stop=102.5, target=99.0, max_hold=1)]
    base = simulate(df, signals, spec, CostModel())
    stressed = simulate(df, signals, spec, CostModel().scaled(1.5))
    assert len(base) == len(stressed) == 2
    assert all(s.r < b.r for b, s in zip(base, stressed))
    assert all(s.costs_r > b.costs_r for b, s in zip(base, stressed))


def test_side_summary_splits_longs_and_shorts():
    trades = [trade(0.5, 1), trade(-1.0, 1), trade(0.5, -1)]
    assert side_summary([t for t in trades if t.side > 0]) == {"trades": 2, "win_rate": 0.5, "expectancy_r": -0.25}
    assert side_summary([]) == {"trades": 0, "win_rate": None, "expectancy_r": None}


def test_tercile_cuts_and_bins():
    cuts = tercile_cuts(np.arange(1, 10, dtype=float))
    assert cuts == (pytest.approx(11 / 3), pytest.approx(19 / 3))
    assert [tercile_of(v, cuts) for v in (1.0, 4.0, 9.0)] == [0, 1, 2]
    assert tercile_of(float("nan"), cuts) is None and tercile_of(None, cuts) is None and tercile_of(2.0, None) is None
    assert tercile_cuts([1.0, float("nan")]) is None


def test_tercile_results_use_each_symbols_own_cut_points():
    cuts = {"A": (1.0, 2.0), "B": (10.0, 20.0)}
    trades = [trade(0.5, symbol="A", entry_atr=0.5), trade(-1.0, symbol="B", entry_atr=5.0), trade(0.3, symbol="A", entry_atr=1.5),
              trade(0.2, symbol="B", entry_atr=25.0), trade(0.4, symbol="A", entry_atr=None)]
    rows = tercile_results(trades, cuts)
    assert [r["name"] for r in rows] == ["low", "mid", "high"]
    assert [r["trades"] for r in rows] == [2, 1, 1]
    assert rows[0]["expectancy_r"] == pytest.approx(-0.25)
    assert positive_terciles(rows, min_trades=1) == 2 and positive_terciles(rows, min_trades=2) == 0


def test_cut_points_come_from_development_trades_or_bars(demo):
    df = demo["EURUSD"][0]
    dev = (None, df.index[20_000])
    many = [trade(0.1, symbol="EURUSD", entry_atr=v) for v in np.linspace(1e-4, 4e-4, 60)]
    cuts = volatility_cuts(many, {"EURUSD": df}, dev)["EURUSD"]
    assert cuts == (pytest.approx(2e-4), pytest.approx(3e-4))
    fallback = volatility_cuts(many[:5], {"EURUSD": df}, dev)["EURUSD"]
    expected = tercile_cuts(atr_at_open(df)[:20_001])
    assert fallback == (pytest.approx(expected[0]), pytest.approx(expected[1]))


def test_stop_target_ratio_is_measured_from_the_signal_price():
    trades = [trade(0.1, stop=99.0, target=100.25), trade(0.1, stop=99.0, target=100.5), trade(0.1, stop=99.0, target=100.25),
              trade(0.1, stop=99.0, target=None), trade(0.1, signal_price=None)]
    assert stop_target_ratio(trades) == pytest.approx(4.0)
    assert stop_target_ratio([trade(0.1, target=None)]) is None


def test_window_extra_has_the_state_contract_keys():
    trades = [trade(0.5, 1, entry_atr=0.5), trade(-1.0, -1, entry_atr=1.5, day=1), trade(0.4, 1, entry_atr=2.5, day=2)]
    extra = window_extra(trades, [0.4, -1.1, 0.3], [0.3, -1.2, 0.2], {"TEST": (1.0, 2.0)})
    d = extra.to_dict()
    assert set(d) == {"expectancy_ci", "expectancy_1_5x_costs", "expectancy_2x_costs", "long", "short", "terciles",
                      "stop_target_ratio", "holm_threshold", "trial_count"}
    assert d["expectancy_1_5x_costs"] == pytest.approx(-0.4 / 3, abs=1e-6)
    assert d["long"]["trades"] == 2 and d["short"]["trades"] == 1
    assert [t["trades"] for t in d["terciles"]] == [1, 1, 1]
    assert d["stop_target_ratio"] == pytest.approx(2.0) and d["holm_threshold"] is None and d["trial_count"] == 0
    assert len(d["expectancy_ci"]) == 2 and d["expectancy_ci"][0] < d["expectancy_ci"][1]
    empty = window_extra([], [], [], {}).to_dict()
    assert empty["expectancy_ci"] == [None, None]
    assert empty["expectancy_1_5x_costs"] is None and empty["stop_target_ratio"] is None
