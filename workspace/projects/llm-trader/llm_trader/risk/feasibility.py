from __future__ import annotations

from llm_trader.data.symbols import SymbolSpec
from llm_trader.risk.limits import Limits

# Placeholder balances that show where the minimum lot starts to fit; never the user's own balance.
PLACEHOLDER_BALANCES = (500, 2000, 10_000, 25_000)
BALANCE_ROW_KEYS = ("symbol", "risk_at_min_lot", "risk_pct", "ok", "note")
EPS = 1e-9


def min_lot_row(symbol: str, spec: SymbolSpec, median_stop_points: float | None, balance: float, limits: Limits) -> dict:
    margin_pct = spec.margin_per_min_lot / balance * 100.0
    row = {
        "symbol": symbol,
        "min_lot": spec.min_lot,
        "median_stop_points": None if median_stop_points is None else round(float(median_stop_points), 1),
        "risk_at_min_lot": None,
        "risk_pct": None,
        "margin_at_min_lot": round(float(spec.margin_per_min_lot), 2),
        "ok": None,
        "note": "No trades yet to measure a typical stop.",
    }
    if median_stop_points is None:
        return row
    risk = spec.risk_money(median_stop_points)
    risk_pct = risk / balance * 100.0
    fits_cap = risk_pct <= limits.risk_per_trade_cap_pct + EPS
    fits_margin = margin_pct <= limits.max_margin_use_pct + EPS
    cap, target = limits.risk_per_trade_cap_pct, limits.risk_per_trade_pct
    blockers, facts = [], []
    if not fits_margin:
        blockers.append(f"one minimum lot needs {margin_pct:.0f}% of the account as margin (limit {limits.max_margin_use_pct:g}%)")
    if not fits_cap:
        blockers.append(f"one minimum lot risks {risk_pct:.2f}% with the median stop, above the {cap:g}% cap: trades would be "
                        "skipped (never rounded up)")
    if fits_cap and risk_pct > target + EPS:
        facts.append(f"Its risk, {risk_pct:.2f}%, is above the {target:g}% target but within the {cap:g}% cap.")
    elif fits_cap and blockers:
        facts.append(f"Its risk, {risk_pct:.2f}%, is within the {cap:g}% cap.")
    if fits_margin and margin_pct > limits.max_margin_use_pct / 2:
        facts.append(f"One minimum-lot position uses {margin_pct:.0f}% of the account as margin.")
    note = " ".join(([f"Doesn't fit: {'; '.join(blockers)}."] if blockers else []) + facts) or None
    row.update(risk_at_min_lot=round(risk, 2), risk_pct=round(risk_pct, 3), ok=fits_cap and fits_margin, note=note)
    return row


def min_lot_rows(specs: dict[str, SymbolSpec], stops: dict[str, float], balance: float, limits: Limits) -> list[dict]:
    return [min_lot_row(symbol, spec, stops.get(symbol), balance, limits) for symbol, spec in specs.items()]


def min_lot_balances(specs: dict[str, SymbolSpec], stops: dict[str, float], limits: Limits,
                     balances=PLACEHOLDER_BALANCES) -> list[dict]:
    return [
        {"balance": float(balance), "rows": [{k: row[k] for k in BALANCE_ROW_KEYS} for row in min_lot_rows(specs, stops, balance, limits)]}
        for balance in balances
    ]
