from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from llm_trader.data.synthetic import make_demo_dataset
from llm_trader.models import TIMEFRAME_MINUTES, iso

PRICE_COLUMNS = ["open", "high", "low", "close"]
FILENAME_PATTERN = re.compile(r"^(?P<symbol>.+?)_(?P<timeframe>M1|M5|M15|M30|H1|H4|D1)(?:_|$)", re.IGNORECASE)
NY_CLOSE_OFFSET = pd.Timedelta(hours=7)


def _decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _separator(header: str) -> str:
    if "\t" in header:
        return "\t"
    if ";" in header and "," not in header:
        return ";"
    return ","


def server_times_to_utc(naive: pd.DatetimeIndex, server_tz) -> tuple[pd.DatetimeIndex, str]:
    if server_tz is None or str(server_tz).upper() in ("UTC", "0", "0.0"):
        return naive.tz_localize("UTC"), "UTC"
    if str(server_tz).lower() == "nyclose":
        # Common broker clock: New York time + 7h, i.e. UTC+2 in winter and UTC+3 during US summer time.
        local = (naive - NY_CLOSE_OFFSET).tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
        return local.tz_convert("UTC"), "server time (New York close, UTC+2/UTC+3) converted to UTC"
    hours = float(server_tz)
    return (naive - pd.Timedelta(hours=hours)).tz_localize("UTC"), f"server time (UTC{hours:+g}) converted to UTC"


def _numbers(frame: pd.DataFrame, column: str | None) -> np.ndarray:
    if column is None:
        return np.full(len(frame), np.nan)
    return pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)


def _parse_exporter(frame: pd.DataFrame) -> tuple[pd.DatetimeIndex, dict]:
    cols = {c.lower(): c for c in frame.columns}
    missing = [c for c in ["time", *PRICE_COLUMNS] if c not in cols]
    if missing:
        raise ValueError(f"missing column(s): {', '.join(missing)}")
    raw_time = frame[cols["time"]]
    epoch = pd.to_numeric(raw_time, errors="coerce")
    if epoch.notna().all():
        unit = "ms" if epoch.abs().max() > 1e11 else "s"
        times = pd.DatetimeIndex(pd.to_datetime(epoch.astype("int64"), unit=unit, utc=True))
    else:
        times = pd.DatetimeIndex(pd.to_datetime(raw_time, utc=True, format="ISO8601", errors="coerce"))
    volume_col = cols.get("tick_volume") or cols.get("volume") or cols.get("real_volume")
    values = {c: _numbers(frame, cols[c]) for c in PRICE_COLUMNS}
    values["spread"] = _numbers(frame, cols.get("spread"))
    values["volume"] = _numbers(frame, volume_col)
    return times, values


def _parse_terminal(frame: pd.DataFrame) -> tuple[pd.DatetimeIndex, dict]:
    cols = {c.upper(): c for c in frame.columns}
    missing = [c for c in ("<DATE>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>") if c not in cols]
    if missing:
        raise ValueError(f"missing column(s): {', '.join(missing)}")
    stamp = frame[cols["<DATE>"]].astype(str).str.strip()
    stamp = stamp + " " + (frame[cols["<TIME>"]].astype(str).str.strip() if "<TIME>" in cols else "00:00:00")
    times = pd.to_datetime(stamp, format="%Y.%m.%d %H:%M:%S", errors="coerce")
    short = pd.to_datetime(stamp, format="%Y.%m.%d %H:%M", errors="coerce")
    times = pd.DatetimeIndex(times.fillna(short))
    values = {c: _numbers(frame, cols[f"<{c.upper()}>"]) for c in PRICE_COLUMNS}
    values["spread"] = _numbers(frame, cols.get("<SPREAD>"))
    values["volume"] = _numbers(frame, cols.get("<TICKVOL>") or cols.get("<VOL>"))
    return times, values


def _meta_entry(meta: dict | None, filename: str, symbol: str | None) -> tuple[str, dict] | None:
    for name, info in ((meta or {}).get("symbols") or {}).items():
        if info.get("file") == filename or (symbol is not None and name == symbol):
            return name, info
    return None


def _infer_timeframe(index: pd.DatetimeIndex) -> str | None:
    if len(index) < 2:
        return None
    values, counts = np.unique(np.diff(index.as_unit("ns").asi8), return_counts=True)
    minutes = int(values[counts.argmax()] // 60_000_000_000)
    return next((tf for tf, m in TIMEFRAME_MINUTES.items() if m == minutes), None)


def load_mt5_csv(path, symbol: str | None = None, timeframe: str | None = None, meta: dict | None = None, server_tz=None) -> tuple[pd.DataFrame, dict]:
    path = Path(path)
    raw = path.read_bytes()
    text = _decode(raw)
    header = text.splitlines()[0] if text else ""
    frame = pd.read_csv(io.StringIO(text), sep=_separator(header), dtype=str, skipinitialspace=True)
    frame.columns = [str(c).strip() for c in frame.columns]
    terminal = any(c.upper() == "<DATE>" for c in frame.columns)
    try:
        times, values = _parse_terminal(frame) if terminal else _parse_exporter(frame)
    except ValueError as exc:
        raise ValueError(f"{path.name}: not an MT5 bar export ({exc})") from None
    if terminal:
        times, time_basis = server_times_to_utc(times, server_tz)
        if server_tz is None:
            time_basis = "assumed UTC (MT5 terminal export; server time zone not given)"
    else:
        time_basis = "UTC"

    df = pd.DataFrame(values, index=pd.DatetimeIndex(times, name="time"))
    bad = df.index.isna() | df[PRICE_COLUMNS].isna().any(axis=1).to_numpy()
    df = df[~bad]
    df.index = df.index.as_unit("ns")
    df = df.sort_index(kind="stable")
    duplicated = df.index.duplicated(keep="last")
    df = df[~duplicated]

    entry = _meta_entry(meta, path.name, symbol)
    name_match = FILENAME_PATTERN.match(path.stem)
    symbol = symbol or (entry[0] if entry else None) or (name_match["symbol"] if name_match else None)
    if not symbol:
        raise ValueError(f"{path.name}: cannot tell which symbol this is; name the file like XAUUSD_M15.csv")
    timeframe = timeframe or (meta or {}).get("timeframe") or (name_match["timeframe"].upper() if name_match else None) or _infer_timeframe(df.index)
    from_exporter = bool(meta) and meta.get("source") == "mt5_export" and entry is not None
    provenance = {
        "source": "mt5_export" if terminal or from_exporter else "other",
        "symbol": symbol,
        "timeframe": timeframe,
        "server": (meta or {}).get("server"),
        "file": path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "rows": len(df),
        "first": iso(df.index[0]) if len(df) else None,
        "last": iso(df.index[-1]) if len(df) else None,
        "duplicates": int(duplicated.sum()),
        "dropped_rows": int(bad.sum()),
        "format": "mt5_terminal" if terminal else "exporter",
        "time_basis": time_basis,
        "symbol_info": entry[1] if entry else None,
    }
    return df, provenance


def load_dataset(dir_or_demo="demo", seed: int = 7, server_tz=None) -> dict[str, tuple[pd.DataFrame, dict]]:
    if isinstance(dir_or_demo, str) and dir_or_demo == "demo":
        return make_demo_dataset(seed)
    folder = Path(dir_or_demo)
    if not folder.is_dir():
        raise FileNotFoundError(f"Data folder not found: {folder}")
    meta_path = folder / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
    tz = server_tz if server_tz is not None else (meta or {}).get("server_tz")
    out: dict[str, tuple[pd.DataFrame, dict]] = {}
    for path in sorted(folder.glob("*.csv")):
        df, provenance = load_mt5_csv(path, meta=meta, server_tz=tz)
        if provenance["symbol"] in out:
            raise ValueError(f"Two files for {provenance['symbol']}: {out[provenance['symbol']][1]['file']} and {path.name}")
        out[provenance["symbol"]] = (df, provenance)
    if not out:
        raise FileNotFoundError(f"No CSV files in {folder}")
    return out
