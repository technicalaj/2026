# Superagentic v1

A supervisor and a small team of specialist agents that check data, test trading rules honestly, watch risk and
report to you every morning. **It never places trades.** There is no broker connection and no order code anywhere in
this project. Your own EAs in MetaTrader 5 keep pulling the trigger; this desk only researches, checks and advises.

The core idea: **agents make the work faster; they do not create an edge.** An agent gains influence only by passing a
measured test on months it has never seen.

## What you get in v1

- A dashboard (one HTML file, works offline and on a phone) with seven tabs: Team, Agents, Checks, Risk, Approvals,
  Report and Log.
- **Rule agents:** Demo Rule A, Demo Rule B and Trend Pullback, simple textbook rules (not your EAs) put through the gate.
- **Self-tests** that prove the test harness itself works: a pattern planted in synthetic data must qualify, a trap
  rule that wins about 80% of trades but loses money must fail, and a rule that peeks at the next bar must be blocked.
- **Context agents:** an event-risk tagger (an offline mock in v1, run in shadow, so it affects nothing) and a regime
  agent that measures volatility and trend in plain code.
- A risk engine with the plan's limits, a kill switch, a typed-YES approval step for every change, and a bridge folder
  that a future Guardian EA reads.

Everything runs on **synthetic demo data** out of the box. Demo numbers show how the system works, not real
performance, and demo data is never eligible for money. The AI is **offline** unless you add an API key and turn it on.

## Quick start

```
python -m llm_trader demo     # runs every agent on demo data, writes out/state.json and out/dashboard.html
python -m llm_trader serve    # optional live dashboard on http://127.0.0.1:8765
python -m pytest -q           # the test suite
```

Open `out/dashboard.html` in any browser. Nothing to install for the dashboard itself; actions (kill switch,
approvals) need `serve`.

**First run: one change waits for you.** Nothing ships pre-approved, so the desk starts in safe mode with a single
pending item, "Adopt the starting settings and locked plans". Read it in the Approvals tab and type YES there (or run
`python -m llm_trader approve chg-001 --yes`). Until then nothing is sent to the bridge; rejecting it keeps safe mode on.
Your YES is stored only on the computer where you typed it (`config/approved.json` is never committed), so a change
that arrives with `git pull` always shows up as pending.

## Run it on Windows, step by step

0. Get the code: on GitHub press **Code → Download ZIP** and unzip it (or `git clone` it). The project is the folder
   `workspace\projects\llm-trader` inside it.
1. Install Python 3.13 from python.org (tick "Add python.exe to PATH").
2. Open PowerShell and go to the project folder, for example `cd C:\Users\you\Downloads\2026\workspace\projects\llm-trader`.
3. `py -3.13 -m venv .venv`
4. `.venv\Scripts\activate`. If PowerShell says running scripts is disabled, run this once and try again:
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. **In every new PowerShell window**, `cd` to the project folder
   and run `.venv\Scripts\activate` first, or Python will not find the desk (`ModuleNotFoundError`).
5. `pip install -r requirements.txt`
6. `python -m llm_trader demo`, then `start out\dashboard.html` (opens it in your browser).
7. To test on your broker's data (MT5 open and logged in; the exporter only reads, it never trades):
   ```
   pip install MetaTrader5
   python tools\export_mt5_data.py --symbols XAUUSD,EURUSD,GBPUSD,USDJPY,US500,BTCUSD --timeframe M15 --months 24 --out data\mt5
   python -m llm_trader run --data data\mt5
   python -m llm_trader snapshot
   ```
   `run` updates `out\state.json`; `snapshot` rewrites `out\dashboard.html` from it (without it you would still see the
   demo). Use your broker's exact symbol names; a suffix such as `XAUUSD.a` is fine. On weekends the exporter cannot read
   the broker's clock from a live price: add `--server-tz nyclose` (most brokers) or the fixed offset, such as
   `--server-tz 2`. The export (and its `meta.json`, which holds your broker's server name) goes to `data\mt5` in the
   project, which is never committed; the exporter refuses a folder inside the project that git would not ignore.
8. `python -m llm_trader serve` and open http://127.0.0.1:8765 for the live dashboard with working buttons. Keep that
   PowerShell window open while you use it; Ctrl+C stops it.
9. Optional: put your real balance in `config\settings.local.json` (never committed), for example
   `{"account": {"balance": 1000, "currency": "USD", "leverage": 30}}`. In Notepad choose **Save as type: All files**,
   or it saves `settings.local.json.txt`. Only `account` is read from that file. A snapshot then contains your balance:
   share `out\dashboard.html` only with people you trust.

## The 80% gate in plain words

You asked for "80+ accuracy from each agent". Nobody can promise that, so we never fake it: the 80% is a gate an agent
must pass, measured on months it has never seen. A rule qualifies only if **all eight** hold:

1. **The test plan was locked first.** Its rules, the rule's code, costs and settings are hashed (fingerprinted)
   before testing, with the date, who wrote the rule and a hash of your risk settings. Any later change, even to the
   code alone, means a new version and your YES. On your broker's data the lock must come before the never-seen
   months began; if it did not, you may declare, only if true, that you have not studied those months (see "Changing
   a rule"). A rule whose plan is not properly locked shows no never-seen results at all, so nobody can look first and
   lock afterwards.
2. **Nothing peeks ahead, and only your broker's MT5 data counts.** A leak test re-runs the rule on data cut off early,
   right at up to 100 of its signal bars; the earlier signals must not change. A win rate over 90% or a profit factor
   over 4 is treated as "too good to be true" and blocked until someone looks for a leak. Only a pass on your broker's
   MT5 data can move forward: a pass on synthetic or non-MT5 data, like the planted self-test, is shown as QUALIFIED
   but is never eligible.
3. **Enough trades:** at least 30 in the 6 never-seen months and 10 in the last 3 months.
4. **Win rate of 80% or more**, shown with its 95% range. Break-evens (within ±0.1R) are not wins, and the share of
   trades that hit the full stop is always shown next to it.
5. **It makes money after costs** in both windows: the average result per trade is above zero, its lower 95% bound is
   above zero, and it is still above zero when all costs are 1.5 times higher.
6. **It beats random entries:** 1,000 copies of the rule's own trades (same direction, stop, target, hold and time of
   day) moved to random days, keeping trades that came on the same day together. It needs p ≤ 0.05 on the never-seen
   months and ≤ 0.10 on the last 3 months, and after several ideas were tried on the same months the bar gets stricter
   (Holm correction). The number of tries is always shown, and it keeps counting when you export fresh data covering
   the same months.
7. **It works in at least 2 of 3 volatility regimes** (quiet, normal, wild). If not, it is "regime-specific" and stays
   in shadow.
8. **The stop is no more than twice the target distance.** A tiny target with a big stop wins often and still loses:
   put the target 4 times closer than the stop and random entries win about 80% and earn nothing. The break-even win
   rate is (stop + cost) ÷ (target + stop).

Even a pass only means "may start a forward test": 30-40 trades at the minimum lot on your broker's data, run by its
own fixed-rule EA, and then your decision. On the demo data no rule agent qualifies, which is the honest result.

## Changing a rule (lock first, then test)

1. Change the rule's code or parameters and bump its `version`.
2. Lock it: `python -m llm_trader lock RULE --yes` (needs an approved starting point). Re-locking a test that did not
   change, for example after a risk-only settings change, keeps its original lock time.
3. Only then run it. Until the plan is locked, its never-seen results stay hidden and it does not count as a try.

On your broker's data the never-seen months usually began before today's lock. If, and only if, you have not studied
those months, declare it with `python -m llm_trader lock RULE --unstudied-since 2026-01-30 --yes` (the date the
dashboard shows). The declaration is locked into the plan's hash, like everything else.

## Safety rules (built in)

**Nothing in v1 watches or stops your live account.** There is no live account feed, and no EA reads `kill.flag`
yet. The limits below are written down and tested, but they are enforced on no account until the Guardian EA
(`mql5/GUARDIAN_SPEC.md`, Phase 1) is built and passes its G1 drills. Until then we recommend no hand trades on the
live account. To stop your EAs right now, use MT5's **Algo Trading** button.

- **No trading code.** A test fails the build if any order call, or an MT5 import outside the read-only exporter,
  appears anywhere in the project. The dashboard also shows this as a self-test.
- **One kill switch for the desk (simulated in v1).** Turning it on needs no confirmation (dashboard button,
  `killswitch on`, or a `kill.flag` file in the bridge folder); turning it off needs you to type YES. In v1 it blocks
  agent output and writes `kill.flag`, which nothing in MT5 reads yet: your EAs keep trading.
- **No change without your YES.** If `config/settings.json` or a test plan changes, the desk goes into safe mode
  until you approve (type YES) or reject the change; rejected settings are put back. Changes to `account`, `server`
  and `llm` (your balance, the port and the AI budget) need no YES. Your YES lives in `config/approved.json` on this
  computer only (never committed).
- **Risk limits in % of equity** (change any of them only with your YES; not enforced on any account yet):
  - risk per trade 0.5%, capped at 1%: if the minimum lot risks more than the cap, the trade is skipped, never
    rounded up;
  - at most 1.5% open risk in total and 1.0% per cluster (US dollar: USD pairs and gold; risk-on: indices and
    crypto), counted as if fully correlated, with no credit for hedges; margin at most 30% after the trade;
  - loss stops: 2% a day, 4% a week, 6% from the equity peak (the weekly and overall stops turn on the kill switch);
  - at most 2 open positions (hand trades included), 4 entries a day, 1 entry per symbol every 4 hours;
  - skip when the spread is more than twice the hour's median; pause a rule after 3 full stops in a row;
  - no entries within 15 minutes of high-impact news (30 for FOMC, NFP and CPI), during the 16:45-17:15 New York
    rollover, after 20:00 UTC on Fridays, or when the economic calendar is more than 24 hours old.
- The Risk tab also shows whether the minimum lot fits at four placeholder balances (500, 2,000, 10,000 and 25,000).
- **Test on the data you trade.** Synthetic or non-MT5 data is never eligible for money.
- **Local only.** The dashboard has no login and listens on 127.0.0.1. A `server.host` in `settings.json` other than
  this computer is ignored; only `serve --host ADDRESS --i-know-there-is-no-login` opens it to other computers. Every
  button also checks that the request came from the dashboard page itself, so another website cannot press it for you.

## What is mocked in v1

- **Prices:** synthetic demo data (seed 7), 24 months of M15 bars ending 2026-10-30. The real-named symbols contain
  no pattern on purpose; CTRL-SYN carries the planted pattern for the self-test.
- **AI calls:** offline templates unless you turn Claude on. The event-risk tagger uses seeded mock answers on a
  synthetic calendar: a plumbing test, labelled "self-test, not accuracy" and UNMEASURED.
- **Account feed:** there is no live link to your account yet, so open risk and losses read 0%.
- **Kill switch and approvals:** real, but local files on this computer. Nothing in MT5 reads `kill.flag` yet.
- **Guardian EA:** a written spec only (`mql5/GUARDIAN_SPEC.md`); MQL5 cannot be compiled in the cloud.

## The bridge folder (for the Guardian EA)

Python writes two things into `out/bridge/` (later MT5's `Common\Files\llmt\`), and nothing else:

- `kill.flag` exists **only while the kill switch is on**. The Guardian EA blocks new entries while it exists.
- `advisories.json`, rewritten (atomically) on every run:

```json
{
  "heartbeat": "2026-11-02T04:10:00Z",
  "kill": false,
  "advisories": [
    {
      "id": "pause-XAUUSD-20261102T1000Z",
      "symbol": "XAUUSD",
      "action": "pause",
      "reason": "US CPI in 30 minutes",
      "issued_at": "2026-11-02T10:00:00Z",
      "expires_at": "2026-11-02T11:00:00Z"
    }
  ]
}
```

Rules for the reader:

- The only action is `pause`: no new entries on that symbol, in either direction, until `expires_at` (at most 4 hours
  after `issued_at`). There is never a lot size, a direction or an entry price in this file.
- Act on each `id` once; ignore stale or repeated ids and anything past `expires_at`.
- If `heartbeat` is old or the file is missing, the advisory is missing: your EA follows its own code rules (logged
  as "ungated"). An agent that has not qualified can never block anything.
- Only QUALIFIED agents may write pauses. In v1 the list is always empty: nothing has qualified on broker data, and
  the event tagger runs in shadow.

The old `signals.json` file from earlier builds is deleted on every run.

## AI (optional)

Offline by default; the supervisor review and the report then use built-in templates. To let Claude write the review
text:

1. Get an API key from the Claude Console (billed separately from Claude subscriptions).
2. Put it in an environment variable `ANTHROPIC_API_KEY`, or copy `.env.example` to `.env` (never committed) and fill
   it in. Never paste the key into a settings file.
3. Run with `--llm on` (or set `LLM_MODE=on` in `.env`).

Each run has a cost cap of $0.50 (`llm.cost_cap_usd` in settings) and each UTC day $1.00 (`llm.daily_cap_usd`), estimated
from the token usage the API reports and kept in `out/llm_spend.json`; once a call could go over either, no more calls
are made. Claude only writes text: it cannot change rules, lots, settings,
gate results or the bridge, and every number in the report comes from code.

## Commands

| Command | What it does |
|---|---|
| `python -m llm_trader demo [--llm on\|off]` | run on demo data, write `out/state.json` and `out/dashboard.html` |
| `python -m llm_trader run [--demo \| --data DIR] [--llm on\|off]` | run every agent; writes `out/state.json`, `out/report.md`, the bridge files |
| `python -m llm_trader serve [--port P]` | live dashboard (default http://127.0.0.1:8765) |
| `python -m llm_trader snapshot [--out FILE]` | one self-contained HTML file of the last run (`out/dashboard.html`) |
| `python -m llm_trader lock RULE --yes` / `lock --all --yes` | lock test plans before you test a changed rule |
| `python -m llm_trader lock RULE --unstudied-since DATE --yes` | also declare, only if true, that you have not studied your data since DATE |
| `python -m llm_trader killswitch on` / `killswitch off --yes` | stop everything / allow entries again |
| `python -m llm_trader approve ID --yes` / `reject ID` | decide on a pending change |

`--data mt5` means the folder in `data.mt5_dir` of the settings (`data/mt5`).

## Files

- `config/settings.json`: settings. The `account` balance is a placeholder; use `config/settings.local.json` for yours.
- `config/plans/`: locked test plans. `config/approved.json`: hashes of the settings and plans you approved; it is
  written only when you type YES and never committed, so a fresh copy has none. `config/trials.json`: every distinct
  rule version whose never-seen results were shown, per data source and months (for the correction for many tries);
  also kept on this computer only.
- `mql5/GUARDIAN_SPEC.md`: the Phase 1 Guardian EA, in plain English.
- `out/` (never committed): `state.json`, `report.md`, `dashboard.html`, `bridge/advisories.json`, `bridge/kill.flag`,
  `killswitch.json`, `approvals.json`.
- `data/` (never committed): your MT5 exports.
