import numpy as np
import pandas as pd

from llm_trader.data.synthetic import DEMO_END, DEMO_SYMBOLS, PLANTED, make_demo_dataset, make_tradingview_like_copy
from llm_trader.signals.registry import get_rule

FX_LIKE = ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "US500", "CTRL-SYN")


def hourly_returns(df: pd.DataFrame) -> pd.Series:
    return np.log(df["close"].resample("1h").last().dropna()).diff().dropna()


def test_same_seed_same_data_and_new_seed_new_data(demo):
    again = make_demo_dataset(7)
    for symbol in DEMO_SYMBOLS:
        pd.testing.assert_frame_equal(again[symbol][0], demo[symbol][0])
        assert again[symbol][1]["sha256"] == demo[symbol][1]["sha256"]
    other = make_demo_dataset(8)
    assert not other["XAUUSD"][0]["close"].equals(demo["XAUUSD"][0]["close"])


def test_symbols_calendar_and_fixed_end(demo):
    assert tuple(demo) == DEMO_SYMBOLS
    for symbol, (df, prov) in demo.items():
        assert df.index.tz is not None and str(df.index.tz) == "UTC"
        assert df.index.name == "time"
        assert df.index.is_monotonic_increasing and df.index.is_unique
        assert df.index[-1] == DEMO_END - pd.Timedelta(minutes=15)
        assert df.index[0] == pd.Timestamp("2024-10-30 22:00", tz="UTC")
        assert list(df.columns) == ["open", "high", "low", "close", "spread", "volume"]
        assert all(df[c].dtype == float for c in df.columns)
        assert prov["source"] == "synthetic" and prov["rows"] == len(df)
    for symbol in FX_LIKE:
        idx = demo[symbol][0].index
        weekend = ((idx.day_of_week == 4) & (idx.hour >= 22)) | (idx.day_of_week == 5) | ((idx.day_of_week == 6) & (idx.hour < 22))
        assert not weekend.any(), symbol
    btc = demo["BTCUSD"][0].index
    assert (btc.day_of_week == 5).any()
    assert len(btc) == 730 * 96


def test_candles_are_internally_consistent(demo):
    for symbol, (df, _) in demo.items():
        assert (df["high"] >= df[["open", "close"]].max(axis=1)).all(), symbol
        assert (df["low"] <= df[["open", "close"]].min(axis=1)).all(), symbol
        assert (df["spread"] >= 1).all() and (df["volume"] >= 1).all()


def test_common_factors_give_realistic_correlations(demo):
    r = pd.DataFrame({s: hourly_returns(demo[s][0]) for s in DEMO_SYMBOLS}).dropna()
    c = r.corr()
    assert c.loc["EURUSD", "GBPUSD"] > 0.3
    assert c.loc["EURUSD", "USDJPY"] < -0.1
    assert c.loc["XAUUSD", "EURUSD"] > 0.1
    assert c.loc["US500", "BTCUSD"] > 0.1
    assert abs(c.loc["CTRL-SYN", "EURUSD"]) < 0.1


def test_volatility_is_higher_in_london_and_new_york_than_in_asia(demo):
    df = demo["EURUSD"][0]
    size = (df["high"] - df["low"]).groupby(df.index.hour).mean()
    assert size.loc[13] > 1.5 * size.loc[3]


def test_spreads_widen_around_rollover(demo):
    df = demo["XAUUSD"][0]
    by_hour = df["spread"].groupby(df.index.hour).median()
    assert by_hour.loc[21] > 2.5 * by_hour.loc[12]


def test_volatility_clusters(demo):
    absolute = hourly_returns(demo["XAUUSD"][0]).abs()
    assert absolute.autocorr(lag=1) > 0.1


def test_planted_events_match_the_control_rule_exactly(demo):
    df, prov = demo["CTRL-SYN"]
    assert prov["planted_pattern"]["events"] == len(get_rule("control_planted").generate(df, "CTRL-SYN"))
    assert prov["planted_pattern"]["min_day_bars"] == get_rule("control_planted").params["min_day_bars"] == PLANTED.min_day_bars


def test_pattern_exists_only_on_the_control_symbol(demo):
    def fade_move(symbol):
        df = demo[symbol][0]
        close = df["close"].to_numpy()
        signals = get_rule("demo_rule_a").generate(df, symbol)
        pos = np.searchsorted(df.index, [s.time for s in signals])
        pos = pos[pos + 8 < len(df)]
        sides = np.array([s.side for s in signals])[: len(pos)]
        scale = np.median(np.abs(np.diff(close))) or 1.0
        return np.mean(sides * (close[pos + 8] - close[pos]) / scale)

    assert fade_move("CTRL-SYN") > 2.0
    assert abs(fade_move("XAUUSD")) < 0.5
    assert abs(fade_move("EURUSD")) < 0.5


def test_tradingview_like_copy_differs_on_most_candles(demo):
    df = demo["XAUUSD"][0]
    tv = make_tradingview_like_copy(df, seed=3)
    common = df.index.intersection(tv.index)
    assert len(tv) < len(df)
    assert (df.loc[common, "close"] != tv.loc[common, "close"]).mean() > 0.7
    assert tv["spread"].isna().all()
    assert (tv["high"] >= tv[["open", "close"]].max(axis=1)).all()
    assert (tv["low"] <= tv[["open", "close"]].min(axis=1)).all()
    sunday_open = df.index[(df.index.day_of_week == 6) & (df.index.hour == 22) & (df.index.minute == 0)]
    assert not sunday_open.isin(tv.index).any()
    pd.testing.assert_frame_equal(tv, make_tradingview_like_copy(df, seed=3))
