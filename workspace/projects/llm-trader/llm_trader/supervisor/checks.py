from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd

from llm_trader.costs import cost_model_from_settings
from llm_trader.data.symbols import DEMO_SPECS, SymbolSpec, base_symbol
from llm_trader.data.synthetic import CONTROL_SYMBOL, make_tradingview_like_copy
from llm_trader.eval.backtest import SignalRejected, simulate
from llm_trader.eval.trials import dataset_fingerprint
from llm_trader.fmt import plural
from llm_trader.models import RuleEvaluation
from llm_trader.signals.registry import get_rule

PRICES = ["open", "high", "low", "close"]
SPIKE_FACTOR = 30.0
SPIKE_LOOKBACK = 96
BUSY_TRADES_PER_SYMBOL_DAY = 4.0
PARITY_SYMBOL = "XAUUSD"
PARITY_RULE = "demo_rule_a"
HOLIDAYS = ((12, 25), (1, 1))
GATE_STATUS = {"qualified": "pass", "failed": "fail", "insufficient": "warn", "blocked": "fail"}

NAME_SOURCE = "Data source is your broker's MT5 export"
NAME_FINGERPRINT = "Every symbol's data is fingerprinted (SHA-256)"
NAME_TIMEZONE = "Bar times are in UTC"
NAME_GAPS = "No missing bars in market hours"
NAME_DUPLICATES = "No duplicate bars"
NAME_OHLC = "Candles are consistent"
NAME_SPIKES = "No price spikes"
NAME_SPREADS = "Spread recorded on every bar"
NAME_END = "Data is up to date"
NAME_PARITY = "Second source matches (parity check)"
NAME_STOPS = "Every signal has a stop-loss"
NAME_STRICT = "Rule fires a sensible amount"
NAME_COSTS = "Real costs are charged"
NAME_PLANS = "Test plan locked before testing"
NAME_LEAK = "No future data used (leak check)"
NAME_SELF_TEST = "Self-test:"
NAME_MIN_LOT = "Minimum lot fits the risk cap and margin limit"
NAME_PORTFOLIO = "One risk limit across all agents"
NAME_GROUP = "Correlated symbols count as one bet"
NAME_OVERLAP = "Qualified agents are not one big bet"
NAME_KILL = "One kill switch stops every agent"
NAME_LOSS_STOPS = "Loss stops not reached"
NAME_SHADOW = "Shadow agents affect nothing"
NAME_FORWARD = "Forward tests at minimum lot"
NAME_APPROVALS = "No change without your YES"
NAME_BRIDGE = "Bridge carries only pauses from qualified agents"
NAME_REPORT = "AI review"


def check(stage: str, agent_id: str, subject: str, name: str, status: str, detail: str) -> dict:
    return {"stage": stage, "agent_id": agent_id, "subject": subject, "name": name, "status": status, "detail": detail}


def label(e: RuleEvaluation) -> str:
    name = e.name.removeprefix("Self-test: ")
    return name[:1].upper() + name[1:]


def labels(evaluations) -> str:
    return ", ".join(label(e) for e in evaluations)


def _session(symbol: str, specs: dict[str, SymbolSpec]) -> str:
    if symbol in specs:
        return specs[symbol].session
    base = base_symbol(symbol)
    return DEMO_SPECS[base].session if base else "fx"


def _bar(df: pd.DataFrame) -> pd.Timedelta:
    if len(df) < 2:
        return pd.Timedelta(minutes=15)
    values, counts = np.unique(np.diff(df.index.as_unit("ns").asi8), return_counts=True)
    return pd.Timedelta(int(values[counts.argmax()]), unit="ns")


def _months(dataset) -> float:
    first = min(df.index[0] for df, _ in dataset.values())
    last = max(df.index[-1] for df, _ in dataset.values())
    return (last - first).days / 30.44


def _when(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M UTC")


def _aggregate(rows: list[dict], stage: str, agent_id: str, name: str, ok_detail: str) -> list[dict]:
    return rows or [check(stage, agent_id, "All symbols" if stage == "data" else "All rules", name, "pass", ok_detail)]


def provenance_checks(dataset) -> list[dict]:
    provs = {s: p for s, (_, p) in dataset.items()}
    if all(p["source"] == "synthetic" for p in provs.values()):
        return [check("data", "data", "All symbols", NAME_SOURCE, "info",
                      f"Expected on demo data: {len(provs)} synthetic symbols that show how the system works. Never eligible for money.")]
    rows, real = [], []
    for symbol, prov in provs.items():
        if prov["source"] == "mt5_export":
            real.append(symbol)
            if str(prov.get("time_basis", "")).startswith("assumed UTC"):
                rows.append(check("data", "data", symbol, NAME_TIMEZONE, "warn",
                                  "MT5 terminal export without a time zone, so times were assumed to be UTC. Sessions may be off by "
                                  "2-3 hours: export with tools/export_mt5_data.py, which converts to UTC."))
        elif symbol == CONTROL_SYMBOL and prov["source"] == "synthetic":
            rows.append(check("data", "data", symbol, NAME_SOURCE, "info",
                              "CTRL-SYN is the synthetic self-test symbol: never eligible for money, by design."))
        else:
            rows.append(check("data", "data", symbol, NAME_SOURCE, "warn",
                              f"Not an MT5 export ({prov.get('file') or 'unknown file'}): never eligible for money. Test on the broker data you trade."))
    if real:
        rows.insert(0, check("data", "data", ", ".join(real), NAME_SOURCE, "pass",
                             f"{plural(len(real), 'symbol')} from your MT5 export; the server name stays in data/ on your PC."))
    return rows


def fingerprint_check(dataset) -> dict:
    hashes = {symbol: str(prov.get("sha256") or "") for symbol, (_, prov) in dataset.items()}
    missing = [symbol for symbol, sha in hashes.items() if not sha]
    if missing:
        return check("data", "data", ", ".join(missing), NAME_FINGERPRINT, "warn",
                     f"No SHA-256 for {', '.join(missing)}, so results on it cannot be traced to the exact data. Load the export again.")
    shown = ", ".join(f"{symbol} {sha[:8]}" for symbol, sha in hashes.items())
    return check("data", "data", "All symbols", NAME_FINGERPRINT, "pass",
                 f"Each result points to the exact bars it used: {shown}. Tries on these months are counted under the combined "
                 f"fingerprint {dataset_fingerprint(dataset)[:12]}.")


def _expected_gap(start: pd.Timestamp, end: pd.Timestamp, session: str) -> bool:
    length = end - start
    if length <= pd.Timedelta(hours=2) and (start.hour >= 19 or start.hour == 0):
        return True
    if session != "crypto":
        friday = (start - pd.Timedelta(days=(start.weekday() - 4) % 7)).normalize() + pd.Timedelta(hours=19)
        if start >= friday and end <= friday + pd.Timedelta(days=2, hours=6):
            return True
    days = pd.date_range(start.normalize(), end.normalize(), freq="D")
    return length <= pd.Timedelta(days=4, hours=12) and any((d.month, d.day) in HOLIDAYS for d in days)


def find_gaps(df: pd.DataFrame, session: str) -> list[tuple[pd.Timestamp, pd.Timedelta, int]]:
    if len(df) < 2:
        return []
    bar = _bar(df)
    index = df.index
    jumps = np.flatnonzero(np.diff(index.as_unit("ns").asi8) > bar.value)
    gaps = []
    for i in jumps:
        start, end = index[i] + bar, index[i + 1]
        if not _expected_gap(start, end, session):
            gaps.append((start, end - start, int((end - start) / bar)))
    return gaps


def gap_checks(dataset, specs) -> list[dict]:
    rows = []
    for symbol, (df, _) in dataset.items():
        gaps = find_gaps(df, _session(symbol, specs))
        if not gaps:
            continue
        missing = sum(g[2] for g in gaps)
        share = missing / (len(df) + missing)
        start, length, _ = max(gaps, key=lambda g: g[1])
        hours = length / pd.Timedelta(hours=1)
        rows.append(check("data", "data", symbol, NAME_GAPS, "fail" if share > 0.05 else "warn",
                          f"{plural(len(gaps), 'gap')} outside the weekend and daily rollover closures ({missing:,} missing bars, {share:.1%}); "
                          f"the longest is {hours:.1f} hours from {_when(start)}. Check the export before trusting results."))
    return _aggregate(rows, "data", "data", NAME_GAPS,
                      f"0 gaps outside the weekend and daily rollover closures across {len(dataset)} symbols "
                      f"({_months(dataset):.0f} months of bars).")


def duplicate_checks(dataset) -> list[dict]:
    rows = [
        check("data", "data", symbol, NAME_DUPLICATES, "warn",
              f"{plural(int(prov['duplicates']), 'bar')} had the same time as another; the later copy was kept. Re-export to be sure.")
        for symbol, (_, prov) in dataset.items() if int(prov.get("duplicates") or 0) > 0
    ]
    return _aggregate(rows, "data", "data", NAME_DUPLICATES, f"Every bar time is unique in all {len(dataset)} symbols.")


def ohlc_violations(df: pd.DataFrame) -> int:
    o, h, low, c = (df[col].to_numpy(dtype=float) for col in PRICES)
    tol = 1e-9 * np.maximum(1.0, np.abs(c))
    bad = (h + tol < np.maximum(o, c)) | (low - tol > np.minimum(o, c)) | (h < low) | (np.minimum.reduce([o, h, low, c]) <= 0)
    return int(bad.sum())


def ohlc_checks(dataset) -> list[dict]:
    rows = []
    for symbol, (df, _) in dataset.items():
        bad = ohlc_violations(df)
        if bad:
            rows.append(check("data", "data", symbol, NAME_OHLC, "fail",
                              f"{plural(bad, 'bar')} {'breaks' if bad == 1 else 'break'} high ≥ open/close ≥ low or {'has' if bad == 1 else 'have'} a price at or below zero. "
                              "The file is damaged: export it again."))
    return _aggregate(rows, "data", "data", NAME_OHLC, f"High ≥ open/close ≥ low on every bar of all {len(dataset)} symbols.")


def find_spikes(df: pd.DataFrame) -> pd.DatetimeIndex:
    if len(df) < SPIKE_LOOKBACK:
        return df.index[:0]
    bar = _bar(df).value
    close = df["close"].to_numpy(dtype=float)
    move = np.abs(np.diff(np.log(close), prepend=np.nan))
    move[np.r_[True, np.diff(df.index.as_unit("ns").asi8) != bar]] = np.nan
    wick = (df["high"] - df[["open", "close"]].max(axis=1)).clip(lower=0) + (df[["open", "close"]].min(axis=1) - df["low"]).clip(lower=0)
    wick = (wick / df["close"]).to_numpy(dtype=float)
    usual_move = pd.Series(move).rolling(SPIKE_LOOKBACK, min_periods=SPIKE_LOOKBACK // 2).median().shift(1).to_numpy()
    rng = ((df["high"] - df["low"]) / df["close"]).to_numpy(dtype=float)
    usual_range = pd.Series(rng).rolling(SPIKE_LOOKBACK, min_periods=SPIKE_LOOKBACK // 2).median().shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        spike = (move > SPIKE_FACTOR * usual_move) | (wick > SPIKE_FACTOR * usual_range)
    return df.index[np.nan_to_num(spike, nan=False).astype(bool)]


def spike_checks(dataset) -> list[dict]:
    rows = []
    for symbol, (df, _) in dataset.items():
        spikes = find_spikes(df)
        if len(spikes):
            shown = ", ".join(_when(t) for t in spikes[:3])
            rows.append(check("data", "data", symbol, NAME_SPIKES, "warn",
                              f"{plural(len(spikes), 'bar')} moved more than {SPIKE_FACTOR:.0f}× the usual move (first: {shown}). "
                              "Check they are real news moves, not bad ticks."))
    return _aggregate(rows, "data", "data", NAME_SPIKES,
                      f"No bar moved more than {SPIKE_FACTOR:.0f}× its usual move (median of the {SPIKE_LOOKBACK} bars before) in any of the {len(dataset)} symbols.")


def spread_checks(dataset, specs) -> list[dict]:
    rows, medians = [], {}
    for symbol, (df, _) in dataset.items():
        spread = df["spread"].to_numpy(dtype=float) if "spread" in df else np.full(len(df), np.nan)
        present = np.isfinite(spread) & (spread > 0)
        typical = specs[symbol].typical_spread_points if symbol in specs else None
        if present.mean() < 0.99:
            fallback = f"the typical {typical:g} points from settings" if typical else "nothing (costs are missing)"
            rows.append(check("data", "data", symbol, NAME_SPREADS, "warn",
                              f"{1 - present.mean():.0%} of bars have no spread, so backtests charge {fallback} there."))
            continue
        median = float(np.median(spread[present]))
        medians[symbol] = (median, df.index[present], spread[present])
        if typical and not 0.5 <= median / typical <= 2.0:
            rows.append(check("data", "data", symbol, NAME_SPREADS, "warn",
                              f"Median spread is {median:g} points but settings say {typical:g}: update costs.symbols.{symbol}.typical_spread_points."))
    if rows or not medians:
        return rows
    symbol = PARITY_SYMBOL if PARITY_SYMBOL in medians else next(iter(medians))
    median, times, values = medians[symbol]
    widest = int(pd.Series(values, index=times.hour).groupby(level=0).median().idxmax())
    return [check("data", "data", "All symbols", NAME_SPREADS, "pass",
                  f"Spread on every bar of all {len(dataset)} symbols. {symbol}: median {median:g} points, widest around "
                  f"{widest:02d}:00 UTC; backtests pay the spread of each bar.")]


def data_end_check(dataset, data_mode: str, now) -> dict:
    last = max(df.index[-1] for df, _ in dataset.values())
    if data_mode == "demo":
        return check("data", "data", "All symbols", NAME_END, "info", f"The demo data has a fixed end: last bar {_when(last)}.")
    age = (pd.Timestamp(now) - last).days
    if age > 3:
        return check("data", "data", "All symbols", NAME_END, "warn",
                     f"Last bar {_when(last)}, {age} days ago. Export again before trusting 'the last 3 months'.")
    return check("data", "data", "All symbols", NAME_END, "pass", f"Last bar {_when(last)}.")


def parity_check(dataset, specs, settings: dict, seed: int) -> tuple[dict, dict | None]:
    if PARITY_SYMBOL not in dataset or PARITY_SYMBOL not in specs:
        return check("data", "data", PARITY_SYMBOL, NAME_PARITY, "info", "Skipped: no XAUUSD data to compare."), None
    df, spec = dataset[PARITY_SYMBOL][0], specs[PARITY_SYMBOL]
    other = make_tradingview_like_copy(df, seed, point=spec.point)
    common = df.index.intersection(other.index)
    differ = float((np.abs(df.loc[common, PRICES].to_numpy() - other.loc[common, PRICES].to_numpy()) > spec.point / 2).any(axis=1).mean())
    only_one = 1.0 - len(common) / len(df.index.union(other.index))
    rule, cost = get_rule(PARITY_RULE), cost_model_from_settings(settings)
    try:
        mine = simulate(df, rule.generate(df, PARITY_SYMBOL), spec, cost)
        theirs = simulate(other, rule.generate(other, PARITY_SYMBOL), spec, cost)
    except SignalRejected as exc:
        return check("data", "data", PARITY_SYMBOL, NAME_PARITY, "info", f"Skipped: {exc}."), None
    changed = len({(t.signal_time, t.side) for t in mine} ^ {(t.signal_time, t.side) for t in theirs})
    stats = {
        "candles_differ": differ, "bars_in_one_source": only_one, "trades": [len(mine), len(theirs)], "trades_differ": changed,
        "total_r": [float(sum(t.r for t in mine)), float(sum(t.r for t in theirs))],
    }
    detail = (
        f"A simulated TradingView-style copy of {PARITY_SYMBOL} differs on {differ:.0%} of candles ({only_one:.1%} of bars exist in "
        f"only one source). {rule.name} takes {len(mine)} trades on one and {len(theirs)} on the other, {changed} of them "
        f"different, and its total moves from {stats['total_r'][0]:+.1f}R to {stats['total_r'][1]:+.1f}R. "
        "Lesson: test on the broker data you trade."
    )
    # The second source is simulated in v1, so this row teaches a lesson rather than reporting a fault in your data.
    return check("data", "data", PARITY_SYMBOL, NAME_PARITY, "info", detail), stats


def data_checks(dataset, specs, settings: dict, data_mode: str, now) -> tuple[list[dict], dict | None]:
    parity, stats = parity_check(dataset, specs, settings, int(settings.get("data", {}).get("demo_seed", 7)))
    rows = (
        provenance_checks(dataset) + [fingerprint_check(dataset)] + gap_checks(dataset, specs) + duplicate_checks(dataset)
        + ohlc_checks(dataset) + spike_checks(dataset) + spread_checks(dataset, specs) + [data_end_check(dataset, data_mode, now), parity]
    )
    return rows, stats


def missing_data(e: RuleEvaluation) -> bool:
    return any(h.startswith("No data for") for h in e.hard_failures)


def self_test_verdict(e: RuleEvaluation) -> bool | None:
    return None if missing_data(e) else bool(e.self_test_ok)


def _hard(e: RuleEvaluation, *prefixes: str) -> list[str]:
    return [h for h in e.hard_failures if h.startswith(prefixes)]


def stop_checks(evaluations: list[RuleEvaluation]) -> list[dict]:
    rows = [
        check("research", e.rule_id, label(e), NAME_STOPS, "fail", f"{msg} The rule is blocked until every signal carries a stop.")
        for e in evaluations for msg in _hard(e, "Rejected signal")
    ]
    total = sum(e.signals for e in evaluations)
    return _aggregate(rows, "research", "research", NAME_STOPS,
                      f"All {total:,} signals from {len(evaluations)} rules carry a stop-loss. A signal without one is rejected, never tested.")


def strictness_checks(evaluations: list[RuleEvaluation], min_trades: int) -> list[dict]:
    rows, fine = [], []
    for e in evaluations:
        m = e.windows["holdout"]
        days = max(1.0, (m.end - m.start).days * 5 / 7) if m.start is not None and m.end is not None else 1.0
        per_day = m.trades / (days * max(1, len(e.symbols)))
        if e.results_hidden:
            continue
        if m.trades < min_trades:
            rows.append(check("research", e.rule_id, label(e), NAME_STRICT, "info",
                              f"Too strict: only {plural(m.trades, 'trade')} in the never-seen months (needs {min_trades}). "
                              "A win rate on so few trades means nothing, so the gate says 'too few trades'."))
        elif per_day > BUSY_TRADES_PER_SYMBOL_DAY:
            rows.append(check("research", e.rule_id, label(e), NAME_STRICT, "warn",
                              f"Very busy: {per_day:.1f} trades per symbol per day. At that pace costs and noise dominate."))
        else:
            fine.append(e)
    if fine:
        rows.insert(0, check("research", "research", labels(fine), NAME_STRICT, "pass",
                             f"{plural(len(fine), 'rule')} with at least {min_trades} trades in the never-seen months, without over-trading."))
    return rows


def cost_checks(evaluations: list[RuleEvaluation]) -> list[dict]:
    rows = [
        check("research", e.rule_id, label(e), NAME_COSTS, "fail", f"{msg} The rule is blocked until costs are set.")
        for e in evaluations for msg in _hard(e, "Costs missing", "No symbol specification")
    ]
    return _aggregate(rows, "research", "research", NAME_COSTS,
                      "Every backtest pays the spread of each bar, commission and slippage, and the random comparison pays the same.")


def plan_checks(evaluations: list[RuleEvaluation]) -> list[dict]:
    rows = [
        check("validation", e.rule_id, label(e), NAME_PLANS, "fail",
              e.plan.reason if "YES" in (e.plan.reason or "") or "--yes" in (e.plan.reason or "") else f"{e.plan.reason} Lock it again only with your YES.")
        for e in evaluations if not e.plan.valid
    ]
    ok = [e for e in evaluations if e.plan.valid]
    if ok:
        rows.insert(0, check("validation", "validation", "All rules" if len(ok) == len(evaluations) else labels(ok),
                             NAME_PLANS, "pass", f"{len(ok)} of {len(evaluations)} test plans were locked (hashed) before testing and are unchanged."))
    return rows


def _planted_leak(e: RuleEvaluation) -> bool:
    return e.self_test and e.expected == "must be blocked"


def leak_checks(evaluations: list[RuleEvaluation]) -> list[dict]:
    rows = []
    for e in evaluations:
        if e.leak_check.passed:
            continue
        if _planted_leak(e):
            rows.append(check("validation", e.rule_id, label(e), NAME_LEAK, "pass",
                              f"Caught the planted leak (self-test), as it should: {e.leak_check.detail} The harness works."))
        else:
            rows.append(check("validation", e.rule_id, label(e), NAME_LEAK, "fail",
                              f"{e.leak_check.detail} Blocked: no live system can see the future."))
    ok = [e for e in evaluations if e.leak_check.passed]
    if ok:
        rows.insert(0, check("validation", "validation", labels(ok), NAME_LEAK, "pass",
                             f"{plural(len(ok), 'rule')} gave the same earlier signals when re-run on data cut off early."))
    return rows


def gate_checks(evaluations: list[RuleEvaluation], bar: float) -> list[dict]:
    rows = []
    for e in evaluations:
        detail = " ".join(e.gate.reasons[:2]) or e.gate.status
        if e.self_test:
            verdict = self_test_verdict(e)
            words = {True: "as expected, so the test harness works", None: "because its data is missing, so this self-test did not run",
                     False: "NOT as expected, so no result can be trusted until this is fixed"}[verdict]
            status = {True: "pass", None: "info", False: "fail"}[verdict]
            rows.append(check("validation", e.rule_id, label(e), f"{NAME_SELF_TEST} {e.expected}", status,
                              f"{e.gate.status.capitalize()} {words}. {detail}"))
            continue
        rows.append(check("validation", e.rule_id, label(e), f"Passes the {bar:.0%} gate", GATE_STATUS[e.gate.status], detail))
    return rows


def min_lot_checks(rows: list[dict], cap_pct: float) -> list[dict]:
    out = []
    for row in rows:
        if row["ok"] is False:
            out.append(check("risk", "risk", row["symbol"], NAME_MIN_LOT, "warn", row["note"] or "Too big for the limits."))
        elif row["ok"] and row["note"]:
            out.append(check("risk", "risk", row["symbol"], NAME_MIN_LOT, "info", row["note"]))
    fits = [r["symbol"] for r in rows if r["ok"]]
    if fits:
        out.insert(0, check("risk", "risk", ", ".join(fits), NAME_MIN_LOT, "pass",
                            f"With the median stop, one minimum lot risks at most the {cap_pct:g}% cap in {plural(len(fits), 'symbol')}; "
                            "a trade whose minimum lot risks more is skipped, never rounded up."))
    return out


def portfolio_check(usage: dict, limits: dict, account_feed: bool = False) -> dict:
    if not account_feed:
        return check("risk", "risk", "Portfolio", NAME_PORTFOLIO, "info",
                     f"No live account feed in v1, so open risk, margin and positions read 0% and nothing is enforced on your account "
                     f"yet. Once connected: at most {limits['max_open_risk_pct']:g}% open risk and {limits['max_margin_use_pct']:g}% "
                     f"margin, {limits['max_open_positions']} positions, counted together for all agents and hand trades.")
    return check("risk", "risk", "Portfolio", NAME_PORTFOLIO, "pass",
                 f"Open risk {usage['open_risk_pct']:.1f}% of the {limits['max_open_risk_pct']:g}% limit, margin "
                 f"{usage['margin_use_pct']:.0f}% of {limits['max_margin_use_pct']:g}%, {usage['open_positions']} of "
                 f"{limits['max_open_positions']} positions, counted together for all agents and hand trades.")


def group_checks(groups, cluster_cap_pct: float) -> list[dict]:
    rows = []
    for g in groups:
        inverse = next((symbol for symbol, sign in g.members.items() if sign < 0), None)
        example = f" Long {inverse} is short the dollar, yet it still adds to the same cluster." if inverse else ""
        rows.append(check("risk", "risk", f"{g.name} cluster", NAME_GROUP, "info",
                          f"{', '.join(g.members)} count as one bet: together at most {cluster_cap_pct:g}% risk, with no credit for "
                          f"hedges.{example}"))
    return rows


def overlap_checks(evaluations: list[RuleEvaluation], groups, correlation: dict, threshold: float) -> list[dict]:
    qualified = [e for e in evaluations if e.gate.status == "qualified" and not e.self_test]
    index = {s: i for i, s in enumerate(correlation["symbols"])}
    rows = []
    for a, b in combinations(qualified, 2):
        for sa in a.symbols:
            for sb in b.symbols:
                shared = [g.name for g in groups if sa in g.members and sb in g.members]
                r = correlation["matrix"][index[sa]][index[sb]] if sa in index and sb in index else None
                if shared:
                    rows.append(check("risk", "risk", f"{label(a)} + {label(b)}", NAME_OVERLAP, "warn",
                                      f"Both trade the {shared[0]} cluster ({sa}, {sb}): their trades count as one bet and share one risk cap."))
                elif sa != sb and r is not None and abs(r) >= threshold:
                    rows.append(check("risk", "risk", f"{label(a)} + {label(b)}", NAME_OVERLAP, "warn",
                                      f"{sa} and {sb} moved together (r = {r:+.2f}, {correlation['window']}) but share no cluster: add one in settings."))
    if rows:
        return rows
    if len(qualified) < 2:
        names = ", ".join(e.name for e in qualified) or "none"
        return [check("risk", "risk", "Qualified rule agents", NAME_OVERLAP, "pass",
                      f"{plural(len(qualified), 'rule agent')} qualified ({names}), so there is no overlap between agents to check.")]
    return [check("risk", "risk", "Qualified rule agents", NAME_OVERLAP, "pass",
                  f"The {len(qualified)} qualified rule agents trade unrelated symbols (no shared cluster, |r| below {threshold:g}).")]


def ungrouped_correlation_checks(groups, correlation: dict, threshold: float) -> list[dict]:
    symbols, matrix = correlation["symbols"], correlation["matrix"]
    rows = []
    for i, j in combinations(range(len(symbols)), 2):
        r = matrix[i][j]
        a, b = symbols[i], symbols[j]
        if r is not None and abs(r) >= threshold and not any(a in g.members and b in g.members for g in groups):
            rows.append(check("risk", "risk", f"{a} + {b}", NAME_GROUP, "warn",
                              f"{a} and {b} moved together (r = {r:+.2f}, {correlation['window']}) but share no cluster."))
    return rows


def kill_switch_check(state: dict, flag_set: bool) -> dict:
    flag = "kill.flag is set" if flag_set else "kill.flag is missing (it is rewritten on the next run)"
    if state["on"]:
        since = f" since {state['changed_at'][:16].replace('T', ' ')} UTC" if state.get("changed_at") else ""
        return check("monitor", "monitor", "Kill switch", NAME_KILL, "warn",
                     f"Kill switch is ON{since}: {state.get('reason') or 'no reason given'} {flag}: no agent output reaches the bridge. "
                     "Simulated in v1: no EA reads kill.flag yet, so your MT5 EAs keep trading (use MT5's Algo Trading button).")
    return check("monitor", "monitor", "Kill switch", NAME_KILL, "pass",
                 "Kill switch is off and kill.flag is absent. One switch (dashboard, command line or kill.flag) stops every agent "
                 "and the bridge; turning it off again needs your YES. Simulated in v1: nothing in MT5 reads kill.flag until "
                 "the Guardian EA is built.")


def loss_stop_checks(hits: list[tuple[str, str]], limits: dict) -> list[dict]:
    if not hits:
        return [check("monitor", "monitor", "Loss stops", NAME_LOSS_STOPS, "pass",
                      f"No loss stop reached: daily {limits['daily_stop_pct']:g}%, weekly {limits['weekly_stop_pct']:g}%, "
                      f"overall {limits['overall_kill_pct']:g}% from the equity peak. v1 has no live account feed, so losses read 0%.")]
    return [check("monitor", "monitor", "Loss stops", NAME_LOSS_STOPS, "fail", message) for _, message in hits]


def tagger_check(tagger: dict, split: int) -> dict:
    return check("monitor", "event_tagger", "Event-risk tagger", NAME_SHADOW, "info",
                 f"Stage {tagger['stage']}, {tagger['measured']}: {tagger['model']}. {split} of {len(tagger['last'])} questions got "
                 "split answers, so no opinion. Its would-be pauses are logged, never sent. Self-test, not accuracy.")


def forward_check(research: list[dict], min_trades: int, max_trades: int) -> dict:
    active = [r["rule_id"] for r in research if r["stage"] == "forward_test"]
    if not active:
        return check("monitor", "monitor", "Forward tests", NAME_FORWARD, "info",
                     f"No agent is in a forward test yet. A rule that qualifies on your broker's data first runs {min_trades}-{max_trades} "
                     "trades at minimum lot as its own fixed-rule EA.")
    return check("monitor", "monitor", ", ".join(active), NAME_FORWARD, "info",
                 f"{plural(len(active), 'agent')} in a forward test: 0 of {min_trades}-{max_trades} trades so far. Waiting for the EA to report trades.")


def approvals_check(status, plan_count: int) -> dict:
    if status.safe_mode:
        return check("approvals", "supervisor", "Settings and plans", NAME_APPROVALS, "warn", f"Safe mode is ON. {status.reason}")
    return check("approvals", "supervisor", "Settings and plans", NAME_APPROVALS, "pass",
                 f"Settings and the {plural(plan_count, 'test plan')} match what was approved (hashes in config/approved.json).")


def bridge_check(bridge_state: dict) -> dict:
    count = len(bridge_state["advisories"])
    return check("bridge", "risk", "Advisories file", NAME_BRIDGE, "pass" if count else "info",
                 f"{count} pause advisories written; never a lot, direction or entry. {bridge_state['note']}")


def report_check(llm_mode: str, llm_note: str) -> dict:
    return check("report", "report", "Daily report", NAME_REPORT, "pass" if llm_mode == "claude" else "info", llm_note)
