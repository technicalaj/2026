from __future__ import annotations

import hashlib
import zlib
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from llm_trader.data.symbols import DEMO_SPECS
from llm_trader.models import iso

DEMO_END = pd.Timestamp("2026-10-30 22:00", tz="UTC")
DEMO_MONTHS = 24
DEMO_TIMEFRAME = "M15"
DEMO_SYMBOLS = ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "US500", "BTCUSD", "CTRL-SYN")
CONTROL_SYMBOL = "CTRL-SYN"
COLUMNS = ["open", "high", "low", "close", "spread", "volume"]
SUB_STEPS = 5
BARS_PER_DAY = 96
BAR_NS = 15 * 60 * 10**9
NS_PER_DAY = 86_400 * 10**9


@dataclass(frozen=True)
class MarketProfile:
    start_price: float
    daily_vol: float
    usd_beta: float = 0.0
    risk_beta: float = 0.0
    volume: float = 500.0
    gap_sigmas: float = 3.0


PROFILES = {
    "XAUUSD": MarketProfile(2650.0, 0.011, usd_beta=-0.45, risk_beta=-0.10, volume=900),
    "EURUSD": MarketProfile(1.0850, 0.0050, usd_beta=-0.75, volume=600),
    "GBPUSD": MarketProfile(1.2950, 0.0055, usd_beta=-0.70, risk_beta=0.05, volume=550),
    "USDJPY": MarketProfile(152.50, 0.0060, usd_beta=0.50, risk_beta=0.30, volume=650),
    "US500": MarketProfile(5800.0, 0.0095, risk_beta=0.70, volume=800),
    "BTCUSD": MarketProfile(72000.0, 0.028, risk_beta=0.45, volume=400),
    # Priced high enough that its 2-point spread is small next to each move, so a planted win is never eaten by costs.
    "CTRL-SYN": MarketProfile(1000.0, 0.012, volume=300),
}


@dataclass(frozen=True)
class PlantedPattern:
    # CTRL-SYN positive control. After the first bar of a UTC day that trades above the previous full day's
    # high and closes back below it (mirror for the low), the next `drift_bars` bars drift `drift_sigmas`
    # bar-sigmas per bar in the fade direction, except every `adverse_every`-th such event, which drifts the
    # same distance the other way. A "full day" has at least `min_day_bars` bars, so the 2-hour Sunday stub is
    # skipped. The fixed rhythm (not a coin flip per event) keeps the true win rate near 6 in 7 in every window
    # and on every seed, and makes the losers full stops, so control_planted's 0.5R target wins about 85% with
    # a profit factor near 2.7: clearly real, never "too good to be true" (win rate <= 90%, PF <= 4). Checked on
    # seeds 1-100: all qualify, never-seen win rate 82-86%.
    min_day_bars: int = 16
    drift_sigmas: float = 3.0
    drift_bars: int = 4
    adverse_every: int = 7


PLANTED = PlantedPattern()

_FX_VOL = [0.6] * 7 + [1.2] * 5 + [1.45] * 5 + [0.9] * 4 + [0.45] + [0.55] * 2
_VOL_BY_HOUR = {
    "fx": np.array(_FX_VOL),
    "metal": np.array(_FX_VOL),
    "index": np.array([0.45] * 7 + [0.75] * 6 + [1.3] + [1.5] * 6 + [0.9] + [0.4] + [0.5] * 2),
    "crypto": np.array([0.85] * 7 + [1.0] * 6 + [1.2] * 5 + [1.0] * 4 + [0.9] * 2),
}
_FX_SPREAD = np.array([1.3] * 7 + [1.0] * 14 + [4.0, 2.5, 1.6])
_SPREAD_BY_HOUR = {
    "fx": _FX_SPREAD,
    "metal": _FX_SPREAD,
    "index": _FX_SPREAD,
    "crypto": np.array([1.1] * 7 + [1.0] * 14 + [1.2, 1.1, 1.1]),
}
_LOGVOL_PARTS = ((400, 0.30), (12, 0.20))
_LOGVOL_VAR = sum(sd**2 for _, sd in _LOGVOL_PARTS)


def demo_calendar(end: pd.Timestamp = DEMO_END, months: int = DEMO_MONTHS) -> pd.DatetimeIndex:
    start = end - pd.DateOffset(months=months)
    grid = pd.date_range(start, end, freq="15min", inclusive="left", tz="UTC", name="time")
    return grid.as_unit("ns")


def market_open_mask(index: pd.DatetimeIndex, session: str) -> np.ndarray:
    if session == "crypto":
        return np.ones(len(index), dtype=bool)
    weekday = index.day_of_week.to_numpy()
    hour = index.hour.to_numpy()
    closed = ((weekday == 4) & (hour >= 22)) | (weekday == 5) | ((weekday == 6) & (hour < 22))
    return ~closed


def _stream(seed: int, name: str) -> np.random.Generator:
    return np.random.default_rng([seed, zlib.crc32(name.encode())])


def _logvol(rng: np.random.Generator, n: int) -> np.ndarray:
    burn = 2000
    total = np.zeros(n)
    for half_life, sd in _LOGVOL_PARTS:
        phi = 0.5 ** (1.0 / half_life)
        noise = rng.standard_normal(n + burn)
        smooth = pd.Series(noise).ewm(alpha=1 - phi, adjust=False).mean().to_numpy()[burn:]
        total += smooth * sd / np.sqrt((1 - phi) / (1 + phi))
    return total


def _factors(seed: int, n: int) -> dict[str, np.ndarray]:
    rng = _stream(seed, "factors")
    return {
        "usd": rng.standard_normal((n, SUB_STEPS)),
        "risk": rng.standard_normal((n, SUB_STEPS)),
        "logvol": _logvol(rng, n),
    }


def _bridge_extremes(points: np.ndarray, step_var: np.ndarray, u_hi: np.ndarray, u_lo: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    # Exact max/min of a Brownian bridge between consecutive sub-step points, so candle highs and lows behave
    # like continuous-price extremes instead of the coarse maximum of a few sampled points.
    a, b = points[:, :-1], points[:, 1:]
    var = step_var[:, None]
    high = (a + b + np.sqrt((b - a) ** 2 - 2.0 * var * np.log(u_hi))) / 2.0
    low = (a + b - np.sqrt((b - a) ** 2 - 2.0 * var * np.log(u_lo))) / 2.0
    return high.max(axis=1), low.min(axis=1)


def _free_path(steps: np.ndarray, gaps: np.ndarray, step_var: np.ndarray, uniforms: tuple, start: float, digits: int) -> tuple[np.ndarray, ...]:
    inc = np.concatenate([gaps[:, None], steps], axis=1)
    path = np.cumsum(inc.ravel()).reshape(inc.shape)
    high, low = _bridge_extremes(path, step_var, *uniforms)
    return tuple(np.round(start * np.exp(x), digits) for x in (path[:, 0], high, low, path[:, -1]))


def _planted_path(
    steps: np.ndarray, gaps: np.ndarray, sigma: np.ndarray, step_var: np.ndarray, uniforms: tuple, days: np.ndarray,
    start: float, digits: int, pattern: PlantedPattern,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    n = len(steps)
    walk = np.concatenate([np.zeros((n, 1)), np.cumsum(steps, axis=1)], axis=1)
    ramp = np.arange(SUB_STEPS + 1) / SUB_STEPS
    hi, lo, cl = [], [], []
    for sign in (-1, 0, 1):
        path = walk + sign * pattern.drift_sigmas * sigma[:, None] * ramp
        high, low = _bridge_extremes(path, step_var, *uniforms)
        hi.append(np.exp(high).tolist())
        lo.append(np.exp(low).tolist())
        cl.append(np.exp(path[:, -1]).tolist())
    gap_factor = np.exp(gaps).tolist()
    day_list = days.tolist()
    out_o, out_h, out_l, out_c = ([0.0] * n for _ in range(4))
    prev_close = start
    cur_day, cur_hi, cur_lo, cur_n = None, -np.inf, np.inf, 0
    pdh = pdl = None
    swept_hi = swept_lo = False
    bear_until = bull_until = -1
    events = 0
    for t in range(n):
        if day_list[t] != cur_day:
            if cur_n >= pattern.min_day_bars:
                pdh, pdl = cur_hi, cur_lo
            cur_day, cur_hi, cur_lo, cur_n = day_list[t], -np.inf, np.inf, 0
            swept_hi = swept_lo = False
        k = 1 + (t < bull_until) - (t < bear_until)
        o = round(prev_close * gap_factor[t], digits)
        h = round(o * hi[k][t], digits)
        low = round(o * lo[k][t], digits)
        c = round(o * cl[k][t], digits)
        out_o[t], out_h[t], out_l[t], out_c[t] = o, h, low, c
        cur_hi, cur_lo, cur_n = max(cur_hi, h), min(cur_lo, low), cur_n + 1
        prev_close = c
        if pdh is None:
            continue
        up = h > pdh and c < pdh
        down = low < pdl and c > pdl
        if up and not swept_hi:
            swept_hi = True
            if not down:
                events += 1
                if events % pattern.adverse_every:
                    bear_until = t + 1 + pattern.drift_bars
                else:
                    bull_until = t + 1 + pattern.drift_bars
        if down and not swept_lo:
            swept_lo = True
            if not up:
                events += 1
                if events % pattern.adverse_every:
                    bull_until = t + 1 + pattern.drift_bars
                else:
                    bear_until = t + 1 + pattern.drift_bars
    return np.array(out_o), np.array(out_h), np.array(out_l), np.array(out_c), events


def _symbol_frame(symbol: str, grid: pd.DatetimeIndex, factors: dict, seed: int) -> tuple[pd.DataFrame, dict]:
    spec = DEMO_SPECS[symbol]
    prof = PROFILES[symbol]
    rng = _stream(seed, symbol)
    open_mask = market_open_mask(grid, spec.session)
    index = grid[open_mask]
    n = len(index)
    hours = index.hour.to_numpy()
    season = _VOL_BY_HOUR[spec.session][hours]
    season = season / np.sqrt(np.mean(season**2))
    vol = np.exp(0.6 * factors["logvol"][open_mask] + 0.8 * _logvol(rng, n) - _LOGVOL_VAR)
    sigma = prof.daily_vol / np.sqrt(BARS_PER_DAY) * season * vol
    idio_weight = np.sqrt(max(0.0, 1.0 - prof.usd_beta**2 - prof.risk_beta**2))
    idio = rng.standard_t(5, size=(n, SUB_STEPS)) / np.sqrt(5 / 3)
    shocks = prof.usd_beta * factors["usd"][open_mask] + prof.risk_beta * factors["risk"][open_mask] + idio_weight * idio
    steps = sigma[:, None] / np.sqrt(SUB_STEPS) * shocks
    ns = index.asi8
    gaps = np.zeros(n)
    starts = np.flatnonzero(np.diff(ns) > BAR_NS) + 1
    gaps[starts] = rng.standard_normal(len(starts)) * prof.gap_sigmas * sigma[starts]
    step_var = sigma**2 / SUB_STEPS
    uniforms = (1.0 - rng.random((n, SUB_STEPS)), 1.0 - rng.random((n, SUB_STEPS)))
    extra: dict = {}
    if symbol == CONTROL_SYMBOL:
        *ohlc, events = _planted_path(steps, gaps, sigma, step_var, uniforms, ns // NS_PER_DAY, prof.start_price, spec.digits, PLANTED)
        extra = {"control": True, "planted_pattern": {**asdict(PLANTED), "events": events}}
    else:
        ohlc = _free_path(steps, gaps, step_var, uniforms, prof.start_price, spec.digits)
    spread_noise = np.exp(0.25 * rng.standard_normal(n))
    spread = np.maximum(1.0, np.round(spec.typical_spread_points * _SPREAD_BY_HOUR[spec.session][hours] * spread_noise * np.sqrt(vol)))
    volume = np.maximum(1.0, np.round(prof.volume * season**2 * vol**2 * np.exp(0.3 * rng.standard_normal(n))))
    o, h, low, c = ohlc
    df = pd.DataFrame({"open": o, "high": h, "low": low, "close": c, "spread": spread, "volume": volume}, index=index)
    return df, extra


def synthetic_provenance(symbol: str, df: pd.DataFrame, seed: int, extra: dict | None = None) -> dict:
    digest = hashlib.sha256(df.index.as_unit("ns").asi8.tobytes())
    digest.update(np.ascontiguousarray(df[COLUMNS].to_numpy(dtype=float)).tobytes())
    return {
        "source": "synthetic",
        "symbol": symbol,
        "timeframe": DEMO_TIMEFRAME,
        "server": None,
        "file": None,
        "sha256": digest.hexdigest(),
        "rows": len(df),
        "first": iso(df.index[0]),
        "last": iso(df.index[-1]),
        "duplicates": 0,
        "dropped_rows": 0,
        "format": "synthetic",
        "time_basis": "UTC",
        "symbol_info": None,
        "seed": seed,
        **(extra or {}),
    }


def make_demo_dataset(seed: int = 7) -> dict[str, tuple[pd.DataFrame, dict]]:
    grid = demo_calendar()
    factors = _factors(seed, len(grid))
    out = {}
    for symbol in DEMO_SYMBOLS:
        df, extra = _symbol_frame(symbol, grid, factors, seed)
        out[symbol] = (df, synthetic_provenance(symbol, df, seed, extra))
    return out


def make_tradingview_like_copy(df: pd.DataFrame, seed: int, point: float = 0.01) -> pd.DataFrame:
    rng = _stream(seed, "tradingview")
    n = len(df)
    ns = df.index.as_unit("ns").asi8
    session_start = np.r_[True, np.diff(ns) > BAR_NS]
    session_end = np.r_[np.diff(ns) > BAR_NS, True]
    near_start = np.zeros(n, dtype=bool)
    for lag in range(4):
        near_start[lag:] |= session_start[: n - lag]
    keep = ~(near_start | session_end)
    changed = rng.random(n) < 0.85
    offsets = rng.choice([-3, -2, -1, 1, 2, 3], size=(n, 4)) * point * changed[:, None]
    digits = max(0, int(round(-np.log10(point))))
    o, h, low, c = (np.round(df[col].to_numpy(dtype=float) + offsets[:, i], digits) for i, col in enumerate(["open", "high", "low", "close"]))
    h = np.maximum.reduce([h, o, c])
    low = np.minimum.reduce([low, o, c])
    volume = np.round(df["volume"].to_numpy(dtype=float) * rng.uniform(0.6, 1.4, n))
    out = pd.DataFrame({"open": o, "high": h, "low": low, "close": c, "spread": np.nan, "volume": volume}, index=df.index)
    return out[keep].copy()
