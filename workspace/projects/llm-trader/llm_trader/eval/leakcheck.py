from __future__ import annotations

import numpy as np
import pandas as pd

from llm_trader.models import Signal, timeframe_delta, utc
from llm_trader.signals.base import SignalRule, index_ns


def _price(value) -> float:
    return np.nan if value is None else float(value)


def _key(signal: Signal) -> tuple:
    return (utc(signal.time).as_unit("ns").value, int(signal.side), _price(signal.stop), _price(signal.target), int(signal.max_hold_bars))


def _when(ns: int) -> str:
    return pd.Timestamp(ns, tz="UTC").strftime("%Y-%m-%d %H:%M UTC")


def _first_difference(expected: list[tuple], got: list[tuple]) -> str | None:
    want = {k[:2]: k for k in expected}
    have = {k[:2]: k for k in got}
    missing = sorted(want.keys() - have.keys())
    extra = sorted(have.keys() - want.keys())
    changed = sorted(
        k for k in want.keys() & have.keys()
        if want[k][4] != have[k][4] or not np.allclose(want[k][2:4], have[k][2:4], rtol=1e-9, atol=0.0, equal_nan=True)
    )
    if missing:
        return f"the signal at {_when(missing[0][0])} disappeared once later bars were removed"
    if extra:
        return f"a signal at {_when(extra[0][0])} appeared only once later bars were removed"
    if changed:
        return f"the signal at {_when(changed[0][0])} changed its stop or target once later bars were removed"
    return None


def detectable_share(cuts_at_signals: int, signals: int, confidence: float = 0.95) -> float:
    if signals and cuts_at_signals >= signals:
        return 1.0 / signals
    # A leak that changes a share f of the signals escapes k signal-bar cuts with probability (1 - f) ** k.
    return 1.0 - (1.0 - confidence) ** (1.0 / max(cuts_at_signals, 1))


def _coverage(k_signal: int, signals: int) -> str:
    if not signals:
        return "the rule gave no signals, so only random cut points were tested"
    if k_signal >= signals:
        return f"every one of its {signals:,} signal bars was a cut point, so a leak in any signal would have shown"
    share = detectable_share(k_signal, signals)
    return (f"{k_signal} of the cuts sat right on its {signals:,} signal bars, so a leak touching {share:.0%} or more of its "
            "signals would have shown 95% of the time")


def leak_check(rule: SignalRule, df: pd.DataFrame, symbol: str, cuts: int = 100, seed: int = 0) -> tuple[bool, str]:
    n = len(df)
    if n < 3 or cuts <= 0:
        return True, f"Not enough {symbol} data to test for future-data leaks."
    full = sorted(_key(s) for s in rule.generate(df, symbol))
    close_ns = index_ns(df) + timeframe_delta(rule.timeframe).value
    signal_bars = np.unique(np.searchsorted(close_ns, [k[0] for k in full]))
    signal_bars = signal_bars[signal_bars < n - 1]
    rng = np.random.default_rng(seed)
    # Cutting right at a signal bar always exposes a rule that peeks at later bars for that signal; a few random cuts
    # also catch signals that only appear once the data is cut short.
    k_signal = min(cuts, len(signal_bars))
    at_signals = rng.choice(signal_bars, size=k_signal, replace=False) if k_signal else np.array([], dtype=np.int64)
    low = max(1, n // 10)
    at_random = rng.integers(low, n - 1, size=max(1, cuts // 10))
    cut_points = sorted(set(at_signals.tolist()) | set(at_random.tolist()))
    problems = []
    for cut in cut_points:
        horizon = close_ns[cut]
        expected = [k for k in full if k[0] <= horizon]
        got = sorted(_key(s) for s in rule.generate(df.iloc[: cut + 1], symbol))
        difference = _first_difference(expected, got)
        if difference:
            problems.append(difference)
    if problems:
        return False, (
            f"Future-data leak on {symbol}: {len(problems)} of {len(cut_points)} re-runs on data cut off early "
            f"changed earlier signals ({problems[0]})."
        )
    return True, (
        f"No future-data leak on {symbol}: {len(cut_points)} re-runs on data cut off early reproduced every earlier signal "
        f"exactly; {_coverage(k_signal, len(signal_bars))}."
    )
