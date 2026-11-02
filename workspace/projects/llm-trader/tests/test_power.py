import time

import pytest

from llm_trader.eval.power import EDGES_R, TRADE_COUNTS, gate_power


@pytest.fixture(scope="module")
def table():
    started = time.perf_counter()
    rows = gate_power()
    return {(r["edge_r"], r["trades"]): r["pass_rate"] for r in rows}, rows, time.perf_counter() - started


def test_table_covers_every_edge_and_sample_size(table):
    rates, rows, _ = table
    assert [(r["edge_r"], r["trades"]) for r in rows] == [(e, n) for n in TRADE_COUNTS for e in EDGES_R]
    assert all(set(r) == {"edge_r", "trades", "pass_rate"} and 0.0 <= r["pass_rate"] <= 1.0 for r in rows)


def test_small_samples_rarely_detect_a_real_edge(table):
    rates, _, _ = table
    assert rates[(0.1, 30)] < 0.15
    assert rates[(0.02, 600)] < 0.15
    assert rates[(0.1, 600)] > 0.6
    assert rates[(0.2, 600)] > 0.99


def test_power_grows_with_edge_and_with_trades(table):
    rates, _, _ = table
    for n in TRADE_COUNTS:
        assert rates[(0.02, n)] <= rates[(0.1, n)] <= rates[(0.2, n)]
    for edge in (0.1, 0.2):
        assert rates[(edge, 30)] < rates[(edge, 300)] <= rates[(edge, 600)]


def test_power_is_fast_and_repeatable(table):
    _, rows, seconds = table
    assert seconds < 10
    assert gate_power() == rows
    assert gate_power(seed=8) != rows


def test_no_edge_passes_about_as_often_as_the_false_alarm_rate():
    (row,) = gate_power(edges=(0.0,), trade_counts=(300,), sims=20_000)
    assert row["pass_rate"] < 0.05
