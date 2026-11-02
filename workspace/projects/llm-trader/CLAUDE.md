# Superagentic (LLM trader): notes for Claude

Read this before doing anything in this folder. It holds the owner's goal, the rules this project must follow, where
the work stands and what comes next. Full plan: `PLAN.md`. How to run: `README.md`.

## The owner and the goal

- Retail trader on a small LIVE account with a firm, trading forex, XAUUSD and crypto. Already runs fixed-rule EAs in
  MetaTrader 5 on this Windows PC. Writes short, informal English: answer in short sentences and plain words, and
  explain any jargon the first time.
- Wants a "superagentic" desk: specialist agents, one per skill, plus one supervisor, giving high-confidence picks.
- Asked for "80+ accuracy from each agent". We never fake that number. It is a hard gate: an agent qualifies only if it
  wins at least 80% on months it never saw, with real costs, a positive expectancy (and its lower 95% bound above 0),
  still positive at 1.5x costs, better than random entries (Holm-corrected), positive in 2 of 3 volatility regimes,
  stop at most 2x the target, at least 30 trades, and no leak. Most ideas fail it; say so plainly.

## Ground rules (from the owner's own 53 studies; never break them)

1. Agents don't create an edge; they only work faster. Every signal passes the same gate before any money: a plan
   locked in advance, a block of never-seen months, the last 3 months, real costs, a random comparison.
2. LLMs research and supervise; they never place, size or direct trades. EAs execute fixed rules. No order code in
   Python: `tests/test_no_order_code.py` fails on `order_send`, `OrderSend`, `create_order`, or a MetaTrader5 import
   outside `tools/`.
3. Confidence is a measured number. Break-evens are not wins. Always show the full-stop rate.
4. One portfolio-level risk and margin limit across all agents and hand trades. Gold, the dollar, US stocks and crypto
   often move together; correlated symbols count as one bet.
5. Test on the same broker data you trade (MT5 exports). TradingView candles differ on most bars.
6. Every trade has a stop from the first second. One kill switch stops everything. No lot, risk or rule change
   without the owner's typed YES.
7. Python talks to MT5 only through bridge files (`advisories.json` with pauses that expire, and `kill.flag`). Never
   lots, directions or entries.
8. Prove small first: 30-40 forward trades at minimum lot on a locked rule, then decide.

## Privacy

The GitHub repo `technicalaj/2026` was public (the owner was asked to make it private). Never commit balances, P&L,
broker or account names, real strategy names, MT5 exports (`data/`), generated output (`out/`) or keys (`.env`).
`config/approved.json` (the owner's YES record) and `config/trials.json` (trial log) stay local on purpose.
`config/settings.local.json` holds the real balance and is never committed.

## Status (2 Nov 2026)

- `PLAN.md` is final. Version 1 is built: 466 tests pass, `python -m llm_trader demo` takes about 20 s.
- On demo data only the planted self-test qualifies (85% wins). Tight Target wins 82% and fails (loses after costs; random
  entries win 80.5% too). Leaky Rule is blocked by the leak check. Nothing is eligible for money.
- First run opens in safe mode with one pending change, `chg-001` (starting settings and locked plans), waiting for YES.
- The kill switch is simulated: nothing in MT5 reads `kill.flag` until the Guardian EA exists.
- AI agents run offline (templates) unless `ANTHROPIC_API_KEY` is set and `--llm on` is passed. Report writer:
  `claude-opus-5-5` with `fallbacks="default"`; the event-risk tagger (planned) uses `claude-haiku-5-5`, 3 samples, and is
  an offline mock today. API usage is billed separately from the owner's Claude plan; cap $0.50 per run, $1 per day.
- Not built yet: Guardian EA (spec in `mql5/GUARDIAN_SPEC.md`), live account and fills feed, DST checks, swaps,
  Monte Carlo tail check, journal (SQLite).
- On real MT5 data a rule counts only if its plan was locked before its never-seen months, or the owner truthfully
  declares those months unstudied: `python -m llm_trader lock RULE --unstudied-since YYYY-MM-DD --yes`.

## Map

- `llm_trader/data/` MT5 CSV loader (UTC), symbol specs, synthetic demo data. `tools/export_mt5_data.py` is the
  read-only MT5 exporter (needs `pip install MetaTrader5`, MT5 open and logged in).
- `llm_trader/signals/` one file per rule agent and self-test. `llm_trader/eval/` backtest, metrics, random baseline
  (same direction, random entry times), gate, leak check, locked plans, windows, trials (Holm), robustness, power.
- `llm_trader/supervisor/` stage checks and self-tests. `llm_trader/agents/` team registry, research and context agents.
- `llm_trader/risk/` engine, limits, blackouts, min-lot feasibility, kill switch, approvals.
- `llm_trader/pipeline.py` one run -> `out/state.json`; `llm_trader/state.py` is the dashboard contract;
  `llm_trader/ui/` the dashboard (no outside files); `llm_trader/server.py` serves it on 127.0.0.1:8765.

## Working here

- Windows setup is in `README.md` ("Run it on Windows, step by step"). Activate `.venv` in every new PowerShell window.
- Run `python -m pytest -q` before you say anything is done; keep it green.
- Commands: `demo`, `run --data data\mt5`, `serve`, `snapshot`, `lock`, `killswitch on|off --yes`, `approve ID --yes`,
  `reject ID` (all as `python -m llm_trader ...`).
- Editing a rule file or settings changes plan hashes and blocks the rule until re-locked. Re-lock
  (`lock --all --yes`) only after the owner says YES.
- MQL5: the owner compiles in MetaEditor and pastes back any errors. MetaEditor also compiles from the command line
  (`/compile:` and `/log` switches); confirm the install path before using it. Test every EA on a demo account first.
- Before any risky step (live account, risk limits, MQL5 that trades), explain it in plain words and wait for YES.

## Next steps (the owner decides)

1. Approve or reject `chg-001` in the dashboard.
2. Make the GitHub repo private.
3. Get the firm's written loss rules (daily and overall limits, reset time and zone). Until then: daily stop -2%,
   overall kill -6% from the equity peak, both on equity.
4. Check EA session times: US daylight saving ended on 1 Nov 2026.
5. Recommended build: Phase 1 Guardian EA from `mql5/GUARDIAN_SPEC.md` (stop on every position, equity loss stops,
   kill switch, phone alerts), demo first, then alert-only on live, then enforce after YES.
6. Or first: export MT5 data on this PC and run v1 on it (`README.md` step 7).
7. Open questions with defaults: `PLAN.md` section 11.
