from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time as dtime

import pandas as pd

from llm_trader.data.symbols import base_symbol
from llm_trader.models import utc
from llm_trader.risk.limits import Blackouts

MAJOR_WORDS = ("FOMC", "NFP", "NON-FARM", "NONFARM", "CPI")
INDEX_CURRENCY = {
    "US500": "USD", "US30": "USD", "US100": "USD", "NAS100": "USD", "GER40": "EUR", "DE40": "EUR",
    "UK100": "GBP", "JP225": "JPY", "AUS200": "AUD",
}


@dataclass(frozen=True)
class Event:
    time: pd.Timestamp
    currency: str
    name: str
    impact: str = "high"

    @property
    def major(self) -> bool:
        upper = self.name.upper()
        return any(word in upper for word in MAJOR_WORDS)

    @property
    def high_impact(self) -> bool:
        return self.impact == "high" or self.major


def symbol_currencies(symbol: str) -> frozenset[str]:
    name = (base_symbol(symbol) or symbol).upper()
    if name in INDEX_CURRENCY:
        return frozenset({INDEX_CURRENCY[name]})
    letters = re.sub("[^A-Z]", "", name)
    return frozenset({letters[:3], letters[3:6]}) if len(letters) == 6 else frozenset()


def _hhmm(text: str) -> dtime:
    hours, minutes = text.split(":")
    return dtime(int(hours), int(minutes))


def in_rollover(now, rollover: str) -> bool:
    window, zone = rollover.rsplit(" ", 1)
    start, end = (_hhmm(t) for t in window.split("-"))
    local = utc(now).tz_convert(zone).time()
    return start <= local < end if start <= end else (local >= start or local < end)


def after_friday_cutoff(now, cutoff: str) -> bool:
    ts = utc(now)
    return ts.weekday() == 4 and ts.time() >= _hhmm(cutoff)


def news_window(event: Event, blackouts: Blackouts) -> pd.Timedelta:
    return pd.Timedelta(minutes=blackouts.major_news_minutes if event.major else blackouts.news_minutes)


def news_hits(symbol: str, now, events, blackouts: Blackouts) -> list[Event]:
    ts, affected = utc(now), symbol_currencies(symbol)
    return [e for e in events if e.high_impact and e.currency in affected and abs(ts - utc(e.time)) <= news_window(e, blackouts)]


def calendar_stale(now, updated_at, max_age_hours: float) -> bool:
    return updated_at is None or utc(now) - utc(updated_at) > pd.Timedelta(hours=max_age_hours)


def blackout_reasons(symbol: str, now, blackouts: Blackouts, events=(), calendar_updated_at=None) -> list[tuple[str, str]]:
    out = []
    for e in news_hits(symbol, now, events, blackouts):
        minutes = round(news_window(e, blackouts) / pd.Timedelta(minutes=1))
        out.append(("news_blackout", f"News blackout: {e.name} ({e.currency}) at {utc(e.time):%H:%M} UTC; "
                                     f"no entries within {minutes} minutes of it."))
    if in_rollover(now, blackouts.rollover):
        out.append(("rollover", f"Rollover blackout ({blackouts.rollover}): spreads widen, so no entries."))
    if after_friday_cutoff(now, blackouts.friday_cutoff_utc):
        out.append(("friday_cutoff", f"Friday after {blackouts.friday_cutoff_utc} UTC: no new entries before the weekend."))
    if calendar_stale(now, calendar_updated_at, blackouts.calendar_max_age_hours):
        if calendar_updated_at is None:
            age = "missing"
        else:
            age = f"{(utc(now) - utc(calendar_updated_at)) / pd.Timedelta(hours=1):.0f} hours old"
        out.append(("calendar_stale", f"The economic calendar is {age} (limit {blackouts.calendar_max_age_hours:g} hours), "
                                      "so news risk is unknown: no entries."))
    return out
