from conftest import make_spec

from llm_trader.risk.feasibility import PLACEHOLDER_BALANCES, min_lot_balances, min_lot_row
from llm_trader.risk.limits import Limits

SPECS = {"XAUUSD": make_spec(name="XAUUSD", margin_per_min_lot=88.0), "BIG": make_spec(name="BIG", margin_per_min_lot=360.0)}
STOPS = {"XAUUSD": 450.0, "BIG": 1500.0}


def table() -> dict:
    return {(t["balance"], r["symbol"]): r for t in min_lot_balances(SPECS, STOPS, Limits()) for r in t["rows"]}


def test_four_placeholder_balances_with_the_contract_keys():
    tables = min_lot_balances(SPECS, STOPS, Limits())
    assert PLACEHOLDER_BALANCES == (500, 2000, 10_000, 25_000)
    assert [t["balance"] for t in tables] == [500.0, 2000.0, 10_000.0, 25_000.0]
    assert all(list(t) == ["balance", "rows"] for t in tables)
    assert all(list(r) == ["symbol", "risk_at_min_lot", "risk_pct", "ok", "note"] for t in tables for r in t["rows"])


def test_small_balance_uses_the_cap_and_says_so():
    small = table()[(500.0, "XAUUSD")]
    assert small["risk_at_min_lot"] == 4.5 and small["risk_pct"] == 0.9 and small["ok"] is True
    assert "above the 0.5% target but within the 1% cap" in small["note"]
    assert "uses 18% of the account as margin" in small["note"]
    assert table()[(2000.0, "XAUUSD")] == {"symbol": "XAUUSD", "risk_at_min_lot": 4.5, "risk_pct": 0.225, "ok": True, "note": None}


def test_minimum_lot_too_big_for_a_small_account():
    rows = table()
    big = rows[(500.0, "BIG")]
    assert big["ok"] is False and big["risk_pct"] == 3.0
    assert big["note"].startswith("Doesn't fit: one minimum lot needs 72% of the account as margin (limit 30%); one minimum lot risks")
    assert "above the 1% cap: trades would be skipped (never rounded up)" in big["note"]
    assert rows[(2000.0, "BIG")]["ok"] is True
    assert rows[(25_000.0, "BIG")] == {"symbol": "BIG", "risk_at_min_lot": 15.0, "risk_pct": 0.06, "ok": True, "note": None}


def test_a_margin_misfit_leads_with_the_blocker():
    row = min_lot_row("BTCUSD", make_spec(name="BTCUSD", margin_per_min_lot=360.0), 520.0, 1000.0, Limits())
    assert row["ok"] is False
    assert row["note"] == ("Doesn't fit: one minimum lot needs 36% of the account as margin (limit 30%). "
                           "Its risk, 0.52%, is above the 0.5% target but within the 1% cap.")


def test_no_measured_stop_means_unknown_not_ok():
    row = min_lot_row("XAUUSD", SPECS["XAUUSD"], None, 1000.0, Limits())
    assert row == {
        "symbol": "XAUUSD", "min_lot": 0.01, "median_stop_points": None, "risk_at_min_lot": None, "risk_pct": None,
        "margin_at_min_lot": 88.0, "ok": None, "note": "No trades yet to measure a typical stop.",
    }
