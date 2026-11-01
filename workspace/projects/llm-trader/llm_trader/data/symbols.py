from __future__ import annotations

import re
from dataclasses import dataclass, replace

SESSIONS = ("fx", "metal", "index", "crypto")
CONTRACT_FIELDS = ("point", "digits", "contract_size", "tick_size", "tick_value", "min_lot", "lot_step", "margin_per_min_lot")
COST_FIELDS = ("commission_per_lot", "slippage_points", "typical_spread_points")


class MissingCostsError(KeyError):
    def __str__(self) -> str:
        return str(self.args[0]) if self.args else "Costs missing"


@dataclass(frozen=True)
class SymbolSpec:
    name: str
    point: float
    digits: int
    contract_size: float
    tick_size: float
    tick_value: float
    min_lot: float
    lot_step: float
    margin_per_min_lot: float
    commission_per_lot: float
    slippage_points: float
    typical_spread_points: float
    session: str
    demo: bool = True

    def money_per_price_unit(self, lots: float = 1.0) -> float:
        return self.tick_value / self.tick_size * lots

    def risk_money(self, stop_points: float, lots: float | None = None) -> float:
        lots = self.min_lot if lots is None else lots
        return stop_points * self.point * self.money_per_price_unit(lots)


# Demo placeholders in USD for a generic retail CFD account; real values come from the MT5 export's meta.json.
DEMO_SPECS: dict[str, SymbolSpec] = {
    s.name: s
    for s in (
        SymbolSpec("XAUUSD", 0.01, 2, 100, 0.01, 1.0, 0.01, 0.01, 88.0, 7.0, 5, 20, "metal"),
        SymbolSpec("EURUSD", 0.00001, 5, 100_000, 0.00001, 1.0, 0.01, 0.01, 36.0, 7.0, 2, 6, "fx"),
        SymbolSpec("GBPUSD", 0.00001, 5, 100_000, 0.00001, 1.0, 0.01, 0.01, 43.0, 7.0, 3, 9, "fx"),
        SymbolSpec("USDJPY", 0.001, 3, 100_000, 0.001, 0.66, 0.01, 0.01, 33.3, 7.0, 3, 8, "fx"),
        SymbolSpec("US500", 0.01, 2, 1, 0.01, 0.01, 0.1, 0.1, 29.0, 0.0, 10, 50, "index"),
        SymbolSpec("BTCUSD", 0.01, 2, 1, 0.01, 0.01, 0.01, 0.01, 360.0, 0.0, 500, 2500, "crypto"),
        SymbolSpec("CTRL-SYN", 0.01, 2, 1, 0.01, 0.01, 0.01, 0.01, 1.0, 0.0, 1, 2, "fx"),
    )
}


def base_symbol(name: str) -> str | None:
    if name in DEMO_SPECS:
        return name
    stripped = re.split(r"[^A-Za-z0-9]", name, maxsplit=1)[0].upper()
    if stripped in DEMO_SPECS:
        return stripped
    for known in DEMO_SPECS:
        if name.upper().startswith(known):
            return known
    return None


def cost_settings(symbol: str, costs_cfg: dict | None) -> dict:
    overrides = ((costs_cfg or {}).get("symbols") or {}).get(symbol, {})
    base = base_symbol(symbol)
    values = {f: getattr(DEMO_SPECS[base], f) for f in COST_FIELDS} if base else {}
    values.update({k: v for k, v in overrides.items() if k in COST_FIELDS})
    missing = [f for f in COST_FIELDS if f not in values]
    if missing:
        raise MissingCostsError(f"Costs missing for {symbol}: {', '.join(missing)} (add them under costs.symbols in settings)")
    return {f: float(values[f]) for f in COST_FIELDS}


def resolve_spec(symbol: str, provenance: dict | None, costs_cfg: dict | None) -> SymbolSpec:
    info = (provenance or {}).get("symbol_info") or {}
    base = base_symbol(symbol)
    costs = cost_settings(symbol, costs_cfg)
    if base is None and not all(f in info for f in CONTRACT_FIELDS):
        raise MissingCostsError(f"No symbol specification for {symbol}: export it with tools/export_mt5_data.py")
    fields = {f: getattr(DEMO_SPECS[base], f) for f in CONTRACT_FIELDS} if base else {}
    fields.update({f: info[f] for f in CONTRACT_FIELDS if f in info})
    session = info.get("session") or (DEMO_SPECS[base].session if base else "fx")
    real = (provenance or {}).get("source") == "mt5_export" and bool(info)
    return SymbolSpec(
        name=symbol,
        point=float(fields["point"]),
        digits=int(fields["digits"]),
        contract_size=float(fields["contract_size"]),
        tick_size=float(fields["tick_size"]),
        tick_value=float(fields["tick_value"]),
        min_lot=float(fields["min_lot"]),
        lot_step=float(fields["lot_step"]),
        margin_per_min_lot=float(fields["margin_per_min_lot"]),
        session=session,
        demo=not real,
        **costs,
    )


def with_overrides(spec: SymbolSpec, overrides: dict) -> SymbolSpec:
    allowed = set(CONTRACT_FIELDS) | set(COST_FIELDS) | {"session"}
    return replace(spec, **{k: v for k, v in overrides.items() if k in allowed})
