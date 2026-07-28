#!/usr/bin/env python3
"""Check the live XAU/USD (gold) spot price.

Usage:
    python3 xau_usd_check.py            # one-shot price
    python3 xau_usd_check.py --watch 30 # refresh every 30 seconds

No API key and no third-party packages required — stdlib only.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

API_URL = "https://api.gold-api.com/price/XAU"
TIMEOUT = 15


def fetch_price():
    """Return (price_usd, updated_at_iso) for one troy ounce of gold."""
    req = urllib.request.Request(API_URL, headers={"User-Agent": "xau-usd-check/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.load(resp)
    return float(data["price"]), data.get("updatedAt", "unknown")


def show():
    try:
        price, updated_at = fetch_price()
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        print(f"XAU/USD lookup failed: {exc}", file=sys.stderr)
        return 1
    print(f"XAU/USD  ${price:,.2f} per troy ounce   (source updated {updated_at})")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Check the live XAU/USD gold price.")
    parser.add_argument(
        "--watch",
        type=int,
        metavar="SECONDS",
        help="keep polling every SECONDS instead of exiting after one reading",
    )
    args = parser.parse_args()

    if args.watch is None:
        return show()

    if args.watch < 1:
        parser.error("--watch needs a positive number of seconds")

    try:
        while True:
            show()
            time.sleep(args.watch)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
