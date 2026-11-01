"""Read-only export of MT5 bars for Superagentic (Windows, MetaTrader 5 running and logged in).

Example:  python tools/export_mt5_data.py --symbols XAUUSD,EURUSD --timeframe M15 --months 24 --out data/mt5
Writes <SYMBOL>_<TF>.csv (times in UTC) plus meta.json. data/ stays on your PC: meta.json holds your broker's server name.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

EXPORTER_VERSION = "0.1.0"
CSV_HEADER = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only MT5 bar exporter for Superagentic (Windows).")
    parser.add_argument("--symbols", required=True, help="comma-separated symbol names exactly as in Market Watch, e.g. XAUUSD,EURUSD")
    parser.add_argument("--timeframe", default="M15", choices=TIMEFRAMES)
    parser.add_argument("--months", type=int, default=24)
    parser.add_argument("--out", default="data/mt5")
    parser.add_argument(
        "--server-tz", default="auto",
        help="broker clock: auto (detect from the live tick), nyclose (UTC+2 winter / UTC+3 US summer) or fixed hours like 2",
    )
    return parser.parse_args(argv)


def us_summer_time(moment: datetime) -> bool:
    year = moment.year
    march = datetime(year, 3, 8, 7, tzinfo=timezone.utc)
    november = datetime(year, 11, 1, 6, tzinfo=timezone.utc)
    start = march + timedelta(days=(6 - march.weekday()) % 7)
    end = november + timedelta(days=(6 - november.weekday()) % 7)
    return start <= moment < end


def server_to_utc_seconds(server_seconds: int, server_tz) -> int:
    # MT5 stamps bars with the broker's wall clock, not UTC.
    if server_tz == "nyclose":
        summer_guess = server_seconds - 3 * 3600
        if us_summer_time(datetime.fromtimestamp(summer_guess, tz=timezone.utc)):
            return summer_guess
        return server_seconds - 2 * 3600
    return int(round(server_seconds - float(server_tz) * 3600))


def rates_to_rows(rates, server_tz) -> list[list]:
    return [
        [
            server_to_utc_seconds(int(bar["time"]), server_tz),
            float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]),
            int(bar["tick_volume"]), int(bar["spread"]), int(bar["real_volume"]),
        ]
        for bar in rates
    ]


def write_csv(path: Path, rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerows(rows)


def detect_server_tz(tick_seconds: float, now: datetime):
    offset = (tick_seconds - now.timestamp()) / 3600
    if abs(offset - round(offset)) > 0.25 or abs(offset) > 14:
        return None
    hours = int(round(offset))
    return "nyclose" if hours == (3 if us_summer_time(now) else 2) else hours


def symbol_spec(mt5, symbol: str, info) -> dict:
    tick = mt5.symbol_info_tick(symbol)
    margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, symbol, info.volume_min, tick.ask) if tick else None
    return {
        "point": info.point,
        "digits": info.digits,
        "contract_size": info.trade_contract_size,
        "tick_size": info.trade_tick_size,
        "tick_value": info.trade_tick_value,
        "min_lot": info.volume_min,
        "lot_step": info.volume_step,
        "margin_per_min_lot": margin,
    }


def resolve_server_tz(mt5, choice: str, symbols: list[str]):
    if choice != "auto":
        return choice if choice == "nyclose" else float(choice)
    for symbol in symbols:
        tick = mt5.symbol_info_tick(symbol)
        detected = detect_server_tz(tick.time, datetime.now(timezone.utc)) if tick else None
        if detected is not None:
            print(f"Broker clock detected as {detected!r} (from the live {symbol} tick).")
            return detected
    print("Could not detect the broker clock (market closed?). Re-run with --server-tz nyclose or e.g. --server-tz 2.", file=sys.stderr)
    return None


def export(mt5, args: argparse.Namespace) -> int:
    account = mt5.account_info()
    if account is None:
        print("MT5 is running but no account is logged in. Log in, then run this again.", file=sys.stderr)
        return 2
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    server_tz = resolve_server_tz(mt5, args.server_tz, symbols)
    if server_tz is None:
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    utc_to = datetime.now(timezone.utc)
    utc_from = utc_to - timedelta(days=round(args.months * 30.44))
    timeframe = getattr(mt5, f"TIMEFRAME_{args.timeframe}")
    meta = {
        "source": "mt5_export",
        "exporter_version": EXPORTER_VERSION,
        "exported_at": utc_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "server": account.server,
        "server_tz": server_tz,
        "times": "UTC",
        "timeframe": args.timeframe,
        "symbols": {},
    }
    failures = 0
    for symbol in symbols:
        info = mt5.symbol_info(symbol)
        if info is None:
            print(f"{symbol}: not found on this account; check the exact name in Market Watch.", file=sys.stderr)
            failures += 1
            continue
        rates = mt5.copy_rates_range(symbol, timeframe, utc_from, utc_to)
        if rates is None or len(rates) == 0:
            print(f"{symbol}: no bars returned ({mt5.last_error()}). Open its chart once so MT5 downloads history.", file=sys.stderr)
            failures += 1
            continue
        filename = f"{symbol}_{args.timeframe}.csv"
        rows = rates_to_rows(rates, server_tz)
        write_csv(out / filename, rows)
        meta["symbols"][symbol] = {"file": filename, "rows": len(rows), **symbol_spec(mt5, symbol, info)}
        print(f"{symbol}: {len(rows)} bars -> {out / filename}")
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"Done. Keep {out} on this PC (git-ignored): meta.json contains your broker's server name.")
    return 1 if failures else 0


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("This tool runs on Windows with the MetaTrader5 package: pip install MetaTrader5", file=sys.stderr)
        return 2
    if not mt5.initialize():
        print(f"Could not connect to MetaTrader 5 ({mt5.last_error()}). Start MT5 and log in, then try again.", file=sys.stderr)
        return 2
    try:
        return export(mt5, args)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    sys.exit(main())
