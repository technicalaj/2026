from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from llm_trader.data.symbols import SymbolSpec
from llm_trader.models import Signal


@dataclass(frozen=True)
class Limits:
    risk_per_trade_pct: float = 1.0
    max_open_risk_pct: float = 2.0
    max_daily_loss_pct: float = 3.0
    max_margin_use_pct: float = 50.0
    max_positions_per_group: int = 1

    @classmethod
    def from_settings(cls, risk_cfg) -> "Limits":
        return cls(**{name: getattr(risk_cfg, name) for name in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class Account:
    balance: float
    currency: str = "USD"
    leverage: float = 30.0

    def to_dict(self) -> dict:
        return {"balance": float(self.balance), "currency": self.currency, "leverage": self.leverage}


@dataclass(frozen=True)
class Group:
    id: str
    name: str
    members: dict[str, int]


@dataclass(frozen=True)
class Position:
    symbol: str
    side: int
    risk_money: float
    margin: float
    rule_id: str = ""


@dataclass
class Decision:
    ok: bool
    reasons: list[str]
    lots: float | None = None
    risk_money: float | None = None
    risk_pct: float | None = None
    margin: float | None = None
    margin_pct: float | None = None

    def as_position(self, signal: Signal) -> Position:
        return Position(signal.symbol, int(signal.side), self.risk_money or 0.0, self.margin or 0.0, signal.rule_id)


def _finite(value) -> bool:
    return value is not None and math.isfinite(float(value))


def _direction_words(group: Group, direction: int) -> str:
    return f"{'long' if direction > 0 else 'short'} {group.name}"


@dataclass
class RiskEngine:
    account: Account
    limits: Limits
    groups: list[Group] = field(default_factory=list)
    specs: dict[str, SymbolSpec] = field(default_factory=dict)

    def pct(self, money: float) -> float:
        return money / self.account.balance * 100.0

    def groups_for(self, symbol: str) -> list[Group]:
        found = [g for g in self.groups if symbol in g.members]
        return found or [Group(symbol, symbol, {symbol: 1})]

    def daily_loss_breached(self, daily_loss_pct: float) -> bool:
        return daily_loss_pct >= self.limits.max_daily_loss_pct

    def check(self, signal: Signal, price: float, positions=(), *, kill_switch_on: bool = False, daily_loss_pct: float = 0.0) -> Decision:
        positions = list(positions)
        reasons = []
        if kill_switch_on:
            reasons.append("Kill switch is ON: nothing goes out.")
        if not _finite(signal.stop):
            return Decision(False, reasons + ["No stop-loss: every signal needs a stop from the first second."])
        spec = self.specs.get(signal.symbol)
        if spec is None:
            return Decision(False, reasons + [f"No symbol specification for {signal.symbol}, so its risk cannot be measured."])
        if self.account.balance <= 0:
            return Decision(False, reasons + ["The account balance must be above zero."])
        if signal.side not in (1, -1) or (price - signal.stop) * signal.side <= 0:
            return Decision(False, reasons + [f"The stop {signal.stop:g} is on the wrong side of the price {price:g}."])
        if self.daily_loss_breached(daily_loss_pct):
            reasons.append(f"Daily loss limit reached: {daily_loss_pct:.1f}% lost today (limit {self.limits.max_daily_loss_pct:g}%).")

        lots = spec.min_lot
        risk_money = spec.risk_money(abs(price - signal.stop) / spec.point, lots)
        risk_pct = self.pct(risk_money)
        if risk_pct > self.limits.risk_per_trade_pct + 1e-9:
            reasons.append(
                f"The minimum lot ({lots:g}) risks {risk_pct:.2f}% of the account with this stop; "
                f"the limit is {self.limits.risk_per_trade_pct:g}% per trade."
            )
        margin = float(spec.margin_per_min_lot)
        margin_pct = self.pct(sum(p.margin for p in positions) + margin)
        if margin_pct > self.limits.max_margin_use_pct + 1e-9:
            reasons.append(f"Margin would reach {margin_pct:.0f}% of the account; the limit is {self.limits.max_margin_use_pct:g}%.")
        open_risk_pct = self.pct(sum(p.risk_money for p in positions) + risk_money)
        if open_risk_pct > self.limits.max_open_risk_pct + 1e-9:
            reasons.append(f"Open risk would reach {open_risk_pct:.2f}% of the account; the portfolio limit is {self.limits.max_open_risk_pct:g}%.")
        for group in self.groups_for(signal.symbol):
            direction = signal.side * group.members[signal.symbol]
            same = [p for p in positions if p.symbol in group.members and p.side * group.members[p.symbol] == direction]
            if len(same) >= self.limits.max_positions_per_group:
                held = ", ".join(f"{'long' if p.side > 0 else 'short'} {p.symbol}" for p in same)
                reasons.append(
                    f"The {group.name} group already holds {len(same)} {_direction_words(group, direction)} position(s) ({held}); "
                    f"correlated symbols count as one bet (limit {self.limits.max_positions_per_group})."
                )
        return Decision(not reasons, reasons, lots, risk_money, risk_pct, margin, margin_pct)

    def usage(self, positions=(), daily_loss_pct: float = 0.0) -> dict:
        positions = list(positions)
        return {
            "open_risk_pct": round(self.pct(sum(p.risk_money for p in positions)), 3),
            "margin_use_pct": round(self.pct(sum(p.margin for p in positions)), 3),
            "daily_loss_pct": round(float(daily_loss_pct), 3),
            "open_positions": len(positions),
        }

    def group_rows(self, positions=()) -> list[dict]:
        positions = list(positions)
        rows = []
        for g in self.groups:
            held = [p for p in positions if p.symbol in g.members]
            rows.append({
                "id": g.id,
                "name": g.name,
                "members": dict(g.members),
                "positions": len(held),
                "risk_pct": round(self.pct(sum(p.risk_money for p in held)), 3),
                "limit_pct": round(self.limits.risk_per_trade_pct * self.limits.max_positions_per_group, 3),
            })
        return rows

    def min_lot_row(self, symbol: str, median_stop_points: float | None) -> dict:
        spec = self.specs[symbol]
        margin_pct = self.pct(spec.margin_per_min_lot)
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
        risk_pct = self.pct(risk)
        notes = []
        if risk_pct > self.limits.risk_per_trade_pct + 1e-9:
            notes.append(f"Minimum lot risks {risk_pct:.2f}% with the median stop, above the {self.limits.risk_per_trade_pct:g}% per-trade limit.")
        if margin_pct > self.limits.max_margin_use_pct + 1e-9:
            notes.append(f"One minimum-lot position needs {margin_pct:.0f}% of the account as margin (limit {self.limits.max_margin_use_pct:g}%).")
        elif margin_pct > self.limits.max_margin_use_pct / 2:
            notes.append(f"One minimum-lot position uses {margin_pct:.0f}% of the account as margin.")
        row.update(
            risk_at_min_lot=round(risk, 2),
            risk_pct=round(risk_pct, 3),
            ok=risk_pct <= self.limits.risk_per_trade_pct + 1e-9 and margin_pct <= self.limits.max_margin_use_pct + 1e-9,
            note=" ".join(notes) or None,
        )
        return row


def correlation_matrix(frames: dict[str, pd.DataFrame], days: int = 90, min_hours: int = 50) -> dict:
    symbols = list(frames)
    window = f"last {days} days, H1 returns"
    if not symbols:
        return {"symbols": [], "matrix": [], "window": window}
    last = max(df.index[-1] for df in frames.values())
    start = last - pd.Timedelta(days=days)
    returns = {}
    for symbol, df in frames.items():
        close = df.loc[df.index > start, "close"]
        hourly = close.resample("1h", label="right", closed="right").last().dropna()
        returns[symbol] = np.log(hourly).diff()
    corr = pd.DataFrame(returns).corr(min_periods=min_hours).reindex(index=symbols, columns=symbols)
    matrix = [[round(float(v), 2) if np.isfinite(v) else None for v in row] for row in corr.to_numpy()]
    return {"symbols": symbols, "matrix": matrix, "window": window}
