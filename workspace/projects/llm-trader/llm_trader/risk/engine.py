from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from llm_trader.data.symbols import SymbolSpec
from llm_trader.models import Signal, utc
from llm_trader.risk.blackouts import Event, blackout_reasons
from llm_trader.risk.limits import Limits

EPS = 1e-9


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


@dataclass(frozen=True)
class Entry:
    symbol: str
    time: pd.Timestamp
    rule_id: str = ""


@dataclass
class Book:
    equity: float
    peak_equity: float | None = None
    positions: list[Position] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)
    daily_loss_pct: float = 0.0
    weekly_loss_pct: float = 0.0
    full_stop_streaks: dict[str, int] = field(default_factory=dict)
    kill_switch_on: bool = False

    @property
    def peak(self) -> float:
        return max(self.peak_equity or 0.0, self.equity)

    @property
    def drawdown_pct(self) -> float:
        return (self.peak - self.equity) / self.peak * 100.0 if self.peak > 0 else 0.0


@dataclass
class Market:
    now: pd.Timestamp
    spread_points: float | None = None
    median_spread_points: float | None = None
    events: list[Event] = field(default_factory=list)
    calendar_updated_at: pd.Timestamp | None = None
    gap_buffer_pct: float = 0.0


@dataclass
class Decision:
    ok: bool
    reasons: list[str]
    rules: list[str]
    lots: float | None = None
    risk_money: float | None = None
    risk_pct: float | None = None
    margin: float | None = None
    margin_pct: float | None = None

    @property
    def rule(self) -> str | None:
        return self.rules[0] if self.rules else None

    def as_position(self, signal: Signal) -> Position:
        return Position(signal.symbol, int(signal.side), self.risk_money or 0.0, self.margin or 0.0, signal.rule_id)


class _Findings:
    def __init__(self):
        self.rules: list[str] = []
        self.reasons: list[str] = []

    def add(self, rule: str, reason: str) -> None:
        self.rules.append(rule)
        self.reasons.append(reason)

    def decision(self, **numbers) -> Decision:
        return Decision(not self.rules, self.reasons, self.rules, **numbers)


def _finite(value) -> bool:
    return value is not None and math.isfinite(float(value))


def pct(money: float, base: float) -> float:
    return money / base * 100.0


@dataclass
class RiskEngine:
    limits: Limits
    groups: list[Group] = field(default_factory=list)
    specs: dict[str, SymbolSpec] = field(default_factory=dict)

    def clusters_for(self, symbol: str) -> list[Group]:
        found = [g for g in self.groups if symbol in g.members]
        return found or [Group(symbol, symbol, {symbol: 1})]

    def size_lots(self, spec: SymbolSpec, stop_points: float, equity: float) -> float | None:
        per_lot = spec.risk_money(stop_points, 1.0)
        if per_lot <= 0 or equity <= 0:
            return None
        wanted = equity * self.limits.risk_per_trade_pct / 100.0 / per_lot
        lots = math.floor(wanted / spec.lot_step + EPS) * spec.lot_step
        if lots + EPS >= spec.min_lot:
            return round(lots, 8)
        min_lot_pct = pct(spec.risk_money(stop_points, spec.min_lot), equity)
        return spec.min_lot if min_lot_pct <= self.limits.risk_per_trade_cap_pct + EPS else None

    def check(self, signal: Signal, price: float, book: Book, market: Market) -> Decision:
        found = _Findings()
        if book.kill_switch_on:
            found.add("kill_switch", "Kill switch is ON: no entries.")
        if not _finite(signal.stop):
            found.add("no_stop", "No stop-loss: every entry needs a stop from the first second.")
            return found.decision()
        spec = self.specs.get(signal.symbol)
        if spec is None:
            found.add("no_spec", f"No symbol specification for {signal.symbol}, so its risk cannot be measured.")
            return found.decision()
        if book.equity <= 0:
            found.add("no_equity", "Account equity must be above zero.")
            return found.decision()
        if signal.side not in (1, -1) or (price - signal.stop) * signal.side <= 0:
            found.add("stop_side", f"The stop {signal.stop:g} is on the wrong side of the price {price:g}.")
            return found.decision()

        lim, equity = self.limits, book.equity
        stop_points = abs(price - float(signal.stop)) / spec.point
        lots = self.size_lots(spec, stop_points, equity)
        if lots is None:
            min_risk = spec.risk_money(stop_points, spec.min_lot)
            found.add("risk_cap", f"The minimum lot ({spec.min_lot:g}) risks {pct(min_risk, equity):.2f}% of equity with this stop, "
                                  f"above the {lim.risk_per_trade_cap_pct:g}% cap: skipped (never rounded up).")
            return found.decision(risk_money=min_risk, risk_pct=pct(min_risk, equity))
        risk_money = spec.risk_money(stop_points, lots)
        held = list(book.positions)
        open_money = sum(p.risk_money for p in held)
        self._loss_stops(found, book, open_money + risk_money, market.gap_buffer_pct)
        open_pct = pct(open_money + risk_money, equity)
        if open_pct > lim.max_open_risk_pct + EPS:
            found.add("open_risk_cap", f"Open risk would reach {open_pct:.2f}% of equity; the limit for all positions together "
                                       f"is {lim.max_open_risk_pct:g}%.")
        for group in self.clusters_for(signal.symbol):
            cluster_pct = pct(sum(p.risk_money for p in held if p.symbol in group.members) + risk_money, equity)
            if cluster_pct > lim.max_cluster_risk_pct + EPS:
                found.add("cluster_cap", f"The {group.name} cluster would carry {cluster_pct:.2f}% risk (limit {lim.max_cluster_risk_pct:g}%): "
                                         "correlated symbols count as one bet, with no credit for hedges.")
        margin = spec.margin_per_min_lot * lots / spec.min_lot
        margin_pct = pct(sum(p.margin for p in held) + margin, equity)
        if margin_pct > lim.max_margin_use_pct + EPS:
            found.add("margin_cap", f"Margin would reach {margin_pct:.0f}% of equity after the trade; the limit is {lim.max_margin_use_pct:g}%.")
        if len(held) >= lim.max_open_positions:
            found.add("max_positions", f"{len(held)} position(s) already open, hand trades included; the limit is {lim.max_open_positions}.")
        self._activity(found, signal, book.entries, market.now)
        self._spread(found, market)
        streak = book.full_stop_streaks.get(signal.rule_id, 0)
        if streak >= lim.pause_after_full_stops:
            found.add("full_stop_streak", f"{signal.rule_id} hit {streak} full stops in a row, so the rule is paused "
                                          f"(limit {lim.pause_after_full_stops}).")
        for rule, reason in blackout_reasons(signal.symbol, market.now, lim.blackouts, market.events, market.calendar_updated_at):
            found.add(rule, reason)
        return found.decision(lots=lots, risk_money=risk_money, risk_pct=pct(risk_money, equity), margin=margin, margin_pct=margin_pct)

    def _loss_stops(self, found: _Findings, book: Book, at_risk_money: float, gap_buffer_pct: float) -> None:
        lim = self.limits
        stops = (
            ("overall_kill", "Overall kill", book.drawdown_pct, lim.overall_kill_pct, "from the equity peak", book.peak,
             "the kill switch stays on until your YES"),
            ("weekly_stop", "Weekly stop", book.weekly_loss_pct, lim.weekly_stop_pct, "this week", book.equity, "locked until your YES"),
            ("daily_stop", "Daily stop", book.daily_loss_pct, lim.daily_stop_pct, "today", book.equity, "locked until the daily reset"),
        )
        for rule, label, lost, limit, period, base, lock in stops:
            at_risk = pct(at_risk_money, base) + gap_buffer_pct
            if lost >= limit - EPS:
                found.add(rule, f"{label} reached: {lost:.1f}% lost {period} (limit {limit:g}%), {lock}.")
            elif lost + at_risk > limit + EPS:
                found.add(rule, f"{label} could be breached: {lost:.1f}% lost {period} plus {at_risk:.2f}% open, new and gap risk "
                                f"is more than {limit:g}%.")

    def _activity(self, found: _Findings, signal: Signal, entries: list[Entry], now) -> None:
        lim, ts = self.limits, utc(now)
        today = [e for e in entries if utc(e.time).date() == ts.date()]
        if len(today) >= lim.max_entries_per_day:
            found.add("entries_per_day", f"{len(today)} entries already today (UTC); the limit is {lim.max_entries_per_day} a day.")
        last = max((utc(e.time) for e in entries if e.symbol == signal.symbol), default=None)
        gap = pd.Timedelta(minutes=lim.min_minutes_between_entries_per_symbol)
        if last is not None and ts - last < gap:
            wait = (gap - (ts - last)) / pd.Timedelta(minutes=1)
            found.add("symbol_cooldown", f"The last {signal.symbol} entry was at {last:%H:%M} UTC; one entry per symbol every "
                                         f"{lim.min_minutes_between_entries_per_symbol} minutes ({wait:.0f} more to wait).")

    def _spread(self, found: _Findings, market: Market) -> None:
        spread, median, multiple = market.spread_points, market.median_spread_points, self.limits.spread_skip_multiple
        if _finite(spread) and _finite(median) and median > 0 and spread > multiple * median + EPS:
            found.add("spread", f"Spread {spread:g} points is more than {multiple:g}x this hour's median ({median:g}): skipped.")

    def usage(self, book: Book) -> dict:
        return {
            "open_risk_pct": round(pct(sum(p.risk_money for p in book.positions), book.equity), 3),
            "margin_use_pct": round(pct(sum(p.margin for p in book.positions), book.equity), 3),
            "daily_loss_pct": round(float(book.daily_loss_pct), 3),
            "open_positions": len(book.positions),
        }

    def group_rows(self, book: Book) -> list[dict]:
        rows = []
        for g in self.groups:
            held = [p for p in book.positions if p.symbol in g.members]
            rows.append({
                "id": g.id,
                "name": g.name,
                "members": dict(g.members),
                "positions": len(held),
                "risk_pct": round(pct(sum(p.risk_money for p in held), book.equity), 3),
                "limit_pct": float(self.limits.max_cluster_risk_pct),
            })
        return rows


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
