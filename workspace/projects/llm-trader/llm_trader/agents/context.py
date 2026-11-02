from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

from llm_trader.config import EventTaggerSettings, RegimeSettings
from llm_trader.models import iso, utc
from llm_trader.risk.blackouts import Event, symbol_currencies
from llm_trader.signals.base import atr, ema

PAUSE, NO_PAUSE = "pause", "no pause"
UNMEASURED = "UNMEASURED"
TAGGER_NOTE = "Self-test with seeded mock answers — not accuracy."
# Minutes after the decision time, currency, name, impact. Synthetic and labelled so wherever it shows.
SYNTHETIC_EVENTS = (
    (20, "EUR", "German Ifo business climate (synthetic)", "medium"),
    (40, "JPY", "BoJ Governor speaks (synthetic)", "high"),
    (60, "USD", "US pending home sales (synthetic)", "medium"),
    (100, "GBP", "BoE MPC minutes (synthetic)", "high"),
    (190, "USD", "FOMC statement (synthetic)", "high"),
)


@dataclass(frozen=True)
class Question:
    symbol: str
    event: Event
    truth: str


def synthetic_calendar(decision_time) -> list[Event]:
    start = utc(decision_time)
    return [Event(start + pd.Timedelta(minutes=m), currency, name, impact) for m, currency, name, impact in SYNTHETIC_EVENTS]


def questions(symbols, events: list[Event], decision_time, lookahead_hours: float) -> list[Question]:
    start = utc(decision_time)
    end = start + pd.Timedelta(hours=lookahead_hours)
    out = []
    for symbol in symbols:
        near = [e for e in events if e.currency in symbol_currencies(symbol) and start <= utc(e.time) <= end]
        if near:
            top = max(near, key=lambda e: (e.high_impact, -utc(e.time).value))
            out.append(Question(symbol, top, PAUSE if top.high_impact else NO_PAUSE))
    return out


def mock_samples(question: Question, samples: int, flip_rate: float, seed: int) -> list[str]:
    rng = np.random.default_rng([seed, zlib.crc32(question.symbol.encode("utf-8"))])
    other = NO_PAUSE if question.truth == PAUSE else PAUSE
    return [other if rng.random() < flip_rate else question.truth for _ in range(samples)]


def agreement(verdicts: list[str]) -> tuple[str, bool]:
    top = max(sorted(set(verdicts)), key=verdicts.count)
    count = verdicts.count(top)
    return f"{count} of {len(verdicts)}", count == len(verdicts) and top == PAUSE


def measured_label(scored_calls: int, min_calls: int) -> str:
    return UNMEASURED if scored_calls < min_calls else f"{scored_calls} scored calls"


def event_tagger(symbols, decision_time, cfg: EventTaggerSettings, scored_calls: int = 0) -> dict:
    rows = []
    for q in questions(symbols, synthetic_calendar(decision_time), decision_time, cfg.lookahead_hours):
        verdicts = mock_samples(q, cfg.samples, cfg.mock_flip_rate, cfg.seed)
        agreed, pause = agreement(verdicts)
        rows.append({"symbol": q.symbol, "event": q.event.name, "time": iso(q.event.time), "verdicts": verdicts,
                     "agreement": agreed, "pause": pause})
    return {
        "stage": "shadow", "measured": measured_label(scored_calls, cfg.min_scored_calls), "samples": cfg.samples,
        "model": f"{cfg.model} (offline mock)", "note": TAGGER_NOTE, "last": rows,
    }


def split_answers(tagger: dict) -> int:
    return sum(1 for row in tagger["last"] if len(set(row["verdicts"])) > 1)


def hourly(df: pd.DataFrame) -> pd.DataFrame:
    bars = df[["open", "high", "low", "close"]].resample("1h", label="left", closed="left")
    return bars.agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def regime(symbol: str, df: pd.DataFrame, cfg: RegimeSettings) -> dict | None:
    recent = df[df.index > df.index[-1] - pd.Timedelta(days=cfg.lookback_days)]
    h1 = hourly(recent)
    if len(h1) < cfg.ema_slow + cfg.atr_period:
        return None
    vol = atr(h1, cfg.atr_period)
    # Compare with the same UTC hour on other days: hourly ATR follows the session clock (Asia quiet, London/NY busy).
    same_hour = vol[(h1.index.hour == h1.index[-1].hour) & np.isfinite(vol)]
    low_cut, high_cut = np.quantile(same_hour, [1 / 3, 2 / 3])
    latest = float(vol[-1])
    tercile = 1 if latest <= low_cut else 3 if latest > high_cut else 2
    close = h1["close"].to_numpy(dtype=float)
    gap = (ema(close, cfg.ema_fast)[-1] - ema(close, cfg.ema_slow)[-1]) / latest
    trend = "up" if gap > cfg.flat_band_atr else "down" if gap < -cfg.flat_band_atr else "flat"
    return {"symbol": symbol, "vol_tercile": int(tercile), "trend": trend}


def regimes(frames: dict[str, pd.DataFrame], cfg: RegimeSettings) -> list[dict]:
    rows = (regime(symbol, df, cfg) for symbol, df in frames.items())
    return [row for row in rows if row is not None]
