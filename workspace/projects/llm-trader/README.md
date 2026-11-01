# Superagentic v1

A supervisor and a team of specialist agents that research, test and check trading rules, then report to you.
**It never places trades.** Signals can only leave through a file (the bridge) for a future fixed-rule MT5 EA.

## What v1 is, and is not

- **Is:** a research desk. Each research agent tests one fixed rule. The Supervisor checks every stage (data, leaks,
  locked test plans, costs, the 80% gate, risk) and the dashboard shows the result.
- **Is not:** a trading bot. There is no broker connection and no order code anywhere.
- Out of the box it runs on **synthetic demo data**. Demo numbers show how the system works, not real performance,
  and demo data is never eligible for money. The AI is **offline** unless you add an API key and `--llm`.

## The 80% gate

An agent qualifies only if, in months it has never seen (the 6 months before the last 3) **and** in the last 3 months:

1. its test plan was locked (hashed) before testing and has not changed since;
2. it has enough trades (30 in the never-seen months, 10 in the last 3);
3. it wins at least 80% of trades. Break-evens are not wins, and the full-stop rate is always shown;
4. it makes money per trade after spread, commission and slippage;
5. it beats random entries with the same stop and target (p ≤ 0.05, or ≤ 0.10 for the last 3 months);
6. it uses no future data (leak check).

Nobody can promise "80%+ from every agent", so we never fake it: agents below the bar are shown as not qualified,
with the reason. On the demo data only the planted-pattern self-test qualifies, which proves the gate can find a real
pattern. Qualifying is not permission to trade: next comes a 30-40 trade forward test at minimum lot on your broker's
data, and then your decision.

## Run it here (Linux or a cloud box)

```
.venv/bin/python -m llm_trader demo      # demo run + out/dashboard.html (open it in a browser)
.venv/bin/python -m llm_trader serve     # live dashboard on http://127.0.0.1:8765
.venv/bin/pytest -q
```

## Run it on Windows, step by step

1. Install Python 3.13 from python.org (tick "Add python.exe to PATH").
2. Open PowerShell in the project folder.
3. `py -3.13 -m venv .venv`
4. `.venv\Scripts\activate`
5. `pip install -r requirements.txt`
6. Export your broker's data (MT5 open and logged in; the tool only reads, it never trades):
   ```
   pip install MetaTrader5
   python tools\export_mt5_data.py --symbols XAUUSD,EURUSD,GBPUSD,USDJPY,US500,BTCUSD --timeframe M15 --months 24 --out data\mt5
   ```
   Use your broker's exact symbol names; a suffix such as `XAUUSD.a` is fine.
7. `python -m llm_trader run --data data\mt5`
8. `python -m llm_trader serve` and open http://127.0.0.1:8765, or `python -m llm_trader snapshot` and open
   `out\dashboard.html`.
9. Optional: put your real balance in `config\settings.local.json` (never committed), for example
   `{"account": {"balance": 500, "currency": "USD", "leverage": 30}}`. Only `account` is read from that file.

## Safety rules (built in)

- Every signal needs a stop-loss from the first second; a signal without one is rejected.
- One kill switch stops everything: `killswitch on` needs no confirmation, `killswitch off --yes` does.
- No rule, lot or settings change takes effect without your YES. If `config/settings.json` or a test plan changes,
  the desk goes into safe mode (nothing goes to the bridge) until you approve the change (type YES in the dashboard,
  or `approve chg-001 --yes`) or reject it (rejected settings are put back). Changes to `account`, `server` and `llm`
  need no YES.
- One risk and margin limit for all agents. Correlated symbols (the dollar group, the risk group) count as one bet.
  Minimum lot only.
- Demo, synthetic or non-MT5 data is never eligible for money: test on the broker data you trade.
- The dashboard has no login. Keep it on 127.0.0.1 and never expose it to the internet.

## Commands

| Command | What it does |
|---|---|
| `python -m llm_trader demo` | run on demo data and write `out/dashboard.html` |
| `python -m llm_trader run [--demo \| --data DIR] [--llm]` | run every agent; writes `out/state.json`, `out/report.md`, the bridge file |
| `python -m llm_trader serve [--host H] [--port P]` | live dashboard (default http://127.0.0.1:8765) |
| `python -m llm_trader snapshot [--out FILE]` | one self-contained HTML file of the last run |
| `python -m llm_trader lock RULE --yes` / `lock --all --yes` | lock (hash) test plans after you decide to change a rule |
| `python -m llm_trader killswitch on` / `killswitch off --yes` | stop everything / allow signals again |
| `python -m llm_trader approve ID --yes` / `reject ID` | decide on a pending change |

`--data mt5` means the folder in `data.mt5_dir` of the settings (`data/mt5`).

## Bridge file (for the future MT5 EA)

`out/bridge/signals.json` is the only way a signal leaves this system. It is rewritten (atomically) on every run, and
cleared at once when the kill switch goes on.

```json
{
  "format": "superagentic-bridge/1",
  "generated_at": "2026-11-02T04:10:00Z",
  "data_mode": "mt5",
  "kill_switch": false,
  "safe_mode": false,
  "written": 1,
  "note": "1 signal(s) written for the EA. Each carries a stop, the minimum lot, its plan hash and an expiry.",
  "signals": [
    {
      "id": "demo_rule-XAUUSD-20261102T0415Z", "rule_id": "demo_rule", "plan_sha256": "1c33cea9...",
      "symbol": "XAUUSD", "side": "buy", "order": "market", "lots": 0.01,
      "stop": 2645.5, "target": 2654.5, "time": "2026-11-02T04:15:00Z", "expires_at": "2026-11-02T04:30:00Z",
      "max_hold_bars": 16, "timeframe": "M15", "risk_pct": 0.45
    }
  ]
}
```

Rules for the EA:

- Ignore the file unless `format` is `superagentic-bridge/1`. Open nothing when `kill_switch` or `safe_mode` is true.
- Act on each `id` once, and only before `expires_at` (UTC). Otherwise skip it.
- Send one market order of `lots` (always the minimum lot) with `stop` attached in the same request, plus `target`
  when it is not null. Never send an order without the stop, and never move the stop further away.
- Close the trade after `max_hold_bars` bars of `timeframe` if neither stop nor target was hit.
- Report fills back for the forward test (30-40 trades at minimum lot) before any decision about money.

In v1 the file is written but always empty: demo data is never sent, and nothing has qualified on broker data yet.

## AI (optional)

Offline by default; the Supervisor review and the report then use built-in templates. To let Claude write the review
text, set `ANTHROPIC_API_KEY` in your environment, or copy `.env.example` to `.env` (never committed) and fill it in,
then run with `--llm`. Claude only writes text: it cannot change rules, lots, settings, gate results or the bridge,
and every number in the report comes from code.

## Files

- `config/settings.json`: settings. The `account` balance is a placeholder; use `config/settings.local.json` for yours.
- `config/plans/`: locked test plans. `config/approved.json`: hashes of the settings and plans you approved.
- `out/`: generated (git-ignored): `state.json`, `report.md`, `bridge/signals.json`, `dashboard.html`,
  `killswitch.json`, `approvals.json`.
- `data/`: your MT5 exports (git-ignored; `meta.json` holds your broker's server name and stays on your PC).
