from __future__ import annotations

import numpy as np
import pandas as pd

from llm_trader.models import utc

DEFAULT_WINDOWS = {"holdout_months": 6, "recent_months": 3}
Bounds = tuple[pd.Timestamp | None, pd.Timestamp]


def split_windows(last_ts, holdout_months: int = 6, recent_months: int = 3) -> dict[str, Bounds]:
    end = utc(last_ts)
    recent_start = end - pd.DateOffset(months=recent_months)
    holdout_start = end - pd.DateOffset(months=recent_months + holdout_months)
    return {
        "development": (None, holdout_start),
        "holdout": (holdout_start, recent_start),
        "recent": (recent_start, end),
    }


def in_window(times_ns: np.ndarray, start, end) -> np.ndarray:
    times_ns = np.asarray(times_ns, dtype=np.int64)
    mask = np.ones(times_ns.shape, dtype=bool)
    if start is not None:
        mask &= times_ns > utc(start).as_unit("ns").value
    if end is not None:
        mask &= times_ns <= utc(end).as_unit("ns").value
    return mask


def contains(start, end, ts) -> bool:
    ts = utc(ts)
    return (start is None or ts > utc(start)) and (end is None or ts <= utc(end))
