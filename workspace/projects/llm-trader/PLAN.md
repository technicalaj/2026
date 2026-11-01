# LLM Trader: Plan

*Draft, 2026-11-01. Public repo: no balances, results, broker or strategy names.*

We are building a "superagentic" desk around the fixed-rule EAs you already run in MetaTrader 5 (an EA, or Expert Advisor, is a program that trades inside MT5). A supervisor and a few specialist agents check data, test rules honestly, watch news and risk, and report to you. The core idea, from your 53 studies and the research: **agents make work faster; they do not create an edge.** EAs keep pulling the trigger, code has the final say on risk, and an AI agent gains influence only by passing a measured test on months it never saw. Safety first: within two to three weeks a Guardian EA gives every trade a stop and puts one loss limit and one kill switch over the account.

## 1. Reality check

**It can** give every position a stop (hand trades too), enforce one loss limit across everything, score every rule and agent honestly, watch data, news and exposure 24/7, report daily, and say "no pick today", the usual answer.

**It cannot:**
- **Create an edge.** Your studies found 12 of 13 indicator signals no better than random, machine learning on 98 features at chance, and 0 of 41 confirmation ideas holding up. Research agrees: reported LLM trading profits mostly vanish after the training cutoff and costs (Profit Mirage, FINSABER, The Alpha Illusion). With real money, 4 of 6 models lost in Alpha Arena Season 1, heavier trading did worse in live FX (HKU), and 7.5 million LLM calls showed no directional edge, while a fixed stop and target beat every LLM exit (DXRG).
- **Forecast prices.** Removing the LLM from LLM-based forecasters did not hurt accuracy (NeurIPS 2024).
- **Be backtested honestly.** The model has read about past prices (Opus 5.5 cutoff: June 2026, likely; Sonnet and Haiku unchecked), so AI agents are judged on forward data only.
- **Answer the same way twice.** The API rejects temperature settings, so we sample 3 times; disagreement means "no opinion".
- **Do multi-step maths reliably** (10–20% errors in one study). Code computes every price, lot and P&L.

**It is good at** reading and tagging text (calendars, headlines, central-bank wording), checking work and reporting. The best evidence of real LLM signal is headline sentiment for US stocks, usable only by very low-cost traders; we found no rigorous after-cost edge in FX, gold or crypto. So **autonomy goes where mistakes are cheap** (research, checks, monitoring, reports); trade decisions stay with fixed rules and code, as Anthropic advises when errors are costly.

**"80+ accuracy from each agent" by morning** can't be promised or manufactured, and version 1 won't show it. It becomes **the 80% gate**: an agent's signals qualify only if, on months it never saw, with a plan locked in advance and real costs, they show (1) 30+ trades, (2) a win rate of 80%+, break-evens not counted as wins, (3) positive expectancy (average result per trade) after costs, and (4) better results than random entries. Agents that fail stay in research or shadow mode (live data, scored, affecting nothing) and send nothing.

**Why win rate alone lies:** put the target 4× closer than the stop and *random* entries win about 80% and earn nothing (8 × +1 = +8; 2 × −4 = −8). Add costs of 0.1× the target and you need 82% to break even: break-even win rate = (stop + cost) ÷ (target + stop). Even a real pass is only a start: 24 wins in 30 means "somewhere between about 63% and 90%".

**"High confidence" is a measured number,** not the model's words: "said 80%, won 78% of 140 unseen calls". Under 30 scored calls the dashboard shows UNMEASURED.

**Success in the first 90 days is not profit:** a stop on every position within 2 seconds, kill drills passed, no change without your YES, no day beyond the daily stop plus gaps, every agent output scored, API spend in budget. **Later:** profit after trading costs *and* the API bill, versus your EAs alone.

Terms: **R** = the money risked on a trade (entry to stop); **drawdown** = fall from the equity high to a later low.

## 2. How it works

**LLMs read, check and advise. Code computes, decides and sizes. EAs execute.** No agent can open a trade, choose a direction, set a lot size or move a stop.

```
YOU: phone alerts, dashboard, YES / KILL / FLATTEN
WINDOWS PC (later a Windows VPS)
  MT5: your EAs --- orders, stop inside ---> broker
       Guardian EA: stops, equity loss stops, kill,
         alerts (runs even if Python is down)
       trade panel, RiskGate: checks before entry
         ^ advisories.json (pauses      | bars, deals,
         | with expiry; no lot sizes)   v calendar.csv
  Python (reads MT5, never sends orders): collector ->
    Data Steward -> journal -> scorer -> gate; agents ->
    supervisor rule + risk engine; dashboard
         ^ git pull (your YES for risk and MQL5 changes)
CLAUDE CODE CLOUD: builds and tests code only.
```

| Agent: job | Input → output | Engine, when |
|---|---|---|
| Supervisor: rule, stage checks | stage results → `{"decision":"pause","why":["data_red"]}` | code, each entry; nightly AI audit only alerts |
| Guardian EA: safety | positions, deals → stops, closes, alerts | MQL5, every second |
| Your EAs: fixed rules | prices → orders with a stop | MQL5, unchanged |
| Data Steward: data faults | MT5 exports → `{"status":"red","issues":["gap"]}` | code, each export |
| Risk engine: one portfolio limit | positions, signal → `{"ok":false,"rule":"cluster_cap"}` | Python + MQL5, each entry |
| Validation lab, scorer, reporter | trade lists, MT5 deals → gate, scorecards, report | code, nightly |
| Event-risk tagger (first AI agent) | calendar, whitelisted headlines → `{"symbol":"XAUUSD","pause":true}` | Haiku 5.5, no tools, 3 samples, hourly |
| Regime | code-computed ATR, trend → `{"vol_tercile":3}` | code, each H1 close |
| Later, shadow first | macro bias and a vetter judging EA trades afterwards (Sonnet 5.5); crypto funding extremes (code) | daily or per trade |
| Research assistant | ideas → locked test plans (your YES) | Claude Code |

AI calls are plain Messages API calls from our Python, with structured outputs (a JSON schema the reply must match), a timeout, a pinned model, no fallback, and a `stop_reason` check. A refusal, error, timeout or malformed reply is "no opinion": logged, never scored as skill.

**Supervisor decision rule** (plain code), per entry:
1. Kill switch on or loss stop hit → no entries.
2. Entries come only from your EAs or new rules that passed §5.
3. Symbol data red or stale → pause it.
4. Any risk rule fails → block.
5. Only QUALIFIED agents act, via advisories computed ahead with an expiry, so no entry waits for an LLM; a pause covers both directions for ≤4 hours. SHADOW agents are only logged.
6. Advisory missing or expired → your per-EA choice (default: trade under the code rules, logged "ungated"). Unqualified AI (the audit, SHADOW agents) never blocks.

Alerts report what an EA did, never "take this trade": hand trades outside the risk path have already caused real losses.

**Risk rules** (% of equity, never R; each needs your YES):
- **Stop-loss:** in every order. A hand trade stop-less after ~2 s gets a stop risking ≤0.5% (distance = 0.5% × equity ÷ (volume × money per point)), outside the broker's minimum distances, or is closed. EAs: alerts until you approve each.
- **Per trade:** 0.5%, cap 1%; if the minimum lot risks more, skip; never round up.
- **Open risk:** ≤1.5% total, ≤1.0% per cluster (USD: USD pairs, gold; risk-on: indices, crypto), as if fully correlated, no hedge credit; over weekends or big news, the larger of stop risk and a 99th-percentile gap. Margin ≤30% after the trade.
- **Activity:** ≤2 open positions incl. hand trades; ≤4 entries a day; 1 per symbol per 4 h.
- **Daily stop:** −2% since the firm's daily reset, closed + floating (or half the firm's limit, if tighter): flatten, cancel pending, lock until reset. A new trade must fit: losses so far + open stop risk + its risk + a gap buffer.
- **Weekly, overall:** −4% weekly; kill at −6% from the equity peak (or half the firm's overall limit, if tighter): flatten, lock until YES.
- **Blackouts (safety rules):** news ±15 min (FOMC, NFP, CPI ±30); rollover 16:45–17:15 New York; Friday after 20:00 UTC; calendar over 24 h old.
- **Spread, streak:** spread >2× the hour's median → skip; 3 full stops in a row → pause the rule.
- **Changes:** ceilings (max lot, risk %, daily %, overall %) are Guardian inputs set by hand; files can only tighten them. Increases wait 24 h after YES; cuts apply at once.

The Guardian enforces stops, loss stops and the kill switch inside MT5 even if Python is down, within 200 server requests a day (FTMO flags over 2,000; likely). Entry checks run in the trade panel (hand trades) and RiskGate (EAs with source); for compiled EAs the Guardian can close positions that break a hard limit (your YES). **Kill** (dashboard, chart button or `kill.flag`) blocks entries and deletes pending orders; **Flatten all** is a separate confirmed button; MT5's Algo Trading button is the backup; the MT5 phone app closes positions if the PC is down. Risk-reducing automatic actions need one standing YES; adding risk needs a YES each time.

## 3. Where things run

- **Where:** your Windows PC runs everything live; a Windows VPS ($5–40/month, likely) can take over for 24/7; an MQL5 VPS ($15/month) runs EAs only; the Claude Code cloud only builds and tests code (no keys, no broker).
- **MT5 link:** the official `MetaTrader5` package (5.0.6231) is Windows-only and needs a running, logged-in terminal (verified). A bare `initialize()` attaches without a stored password; one Python process per terminal; on IPC error −10005, retry 3 times, then stop issuing advisories.
- **Bridge (rule 7):** code goes cloud → private GitHub → `git pull` (risk or MQL5 changes need a plain-English summary and your YES). Decisions are files in MT5's `Common\Files\llmt\`: `advisories.json` (heartbeat; pauses with id and expiry; no lot field; stale or repeated ids ignored), `kill.flag`, and an exported `calendar.csv`.
- **Clocks:** UTC everywhere; server offset logged per date. US daylight saving ended today (EU on 25 Oct), so the New York 17:00 rollover moved from 21:00 to 22:00 UTC: **check tonight's EA session times against the new offset.**
- **Test data = trade data (rule 5):** bars, ticks and trade lists from your broker's MT5 server only, fingerprinted (SHA-256); TradingView only for charts.
- **Crypto:** broker crypto CFDs through the same risk engine, only where the minimum lot fits; funding rates and open interest later via CCXT (public data); exchange trading only after a crypto rule passes small live. Local rules vary (EU retail crypto CFDs capped at 2:1, UK retail ban; likely).

| Data | Source | Cost |
|---|---|---|
| Bars, ticks, specs, deals | your MT5 terminal | free |
| Calendar | MQL5 calendar via exporter EA; backup ForexFactory JSON (unofficial, no actuals) | free |
| Headlines | investingLive, FXStreet RSS (URLs unverified), archived with arrival time; CryptoPanic | free |
| Macro | FRED (DFII10, DGS2, DGS10, DTWEXBGS), first-published values via ALFRED | free key |
| Positioning | CFTC COT (weekly), Myfxbook outlook (100 calls/day) | free |
| Crypto derivatives | exchange endpoints via CCXT; CoinGlass if useful | free; $29/month |

## 4. Confidence and learning

**Journal:** one append-only SQLite row per agent output (agent; version = model ID + prompt, examples and rule hashes; symbol; decision time; inputs hash; 3 verdicts; `stop_reason`; answering model; cost), with inputs cut off at decision time. Code, never an LLM, fills in outcomes from MT5 deals, including each skipped signal's would-be result. Nightly backup.

**Labels** (after spread, commission, swap and slippage): **win** ≥+0.1R; **break-even** between −0.1R and +0.1R, not a win; **loss** below −0.1R; **full stop** ≤−0.9R (lost the whole risk). Win rate = wins ÷ all trades, always shown beside break-even and full-stop rates.

**Scorecards.** *Rules:* win rate and expectancy with 95% ranges, full-stop rate, profit factor (gross wins ÷ gross losses), drawdown in % of equity, random percentile, longs vs shorts, volatility terciles, 1.5× and 2× costs. *Pause agents:* share of paused trades that would have lost and R saved versus 1,000 random pauses; a pause-rate alarm. *Forecast agents:* hit rate versus a naive base rate (beat it by 10+ points) and Brier score (error of stated probabilities).

**Calibration** (does "80% sure" win about 80%?): the model's stated confidence is ignored (it runs high). Raw score = agreement among samples (3 of 3 vs 2 of 3; 5 samples where the level matters). Under 30 outcomes: UNMEASURED. 30–99: passes if the stated level lies inside the 95% range of the hit rate. 100+: check the score separates wins from losses (AUC above 0.6; 0.5 is a coin flip), then fit Platt scaling (a small logistic regression); isotonic only after several hundred (unverified rule of thumb).

**Lifecycle.** RESEARCH → SHADOW → QUALIFIED (may pause entries; your YES) → RETIRED, or BLOCKED for leaks or bad data; at most 8 in shadow, 3 enforcing, one version each. Automatic demotion (one standing YES) when the last 40 decisions fail a sequential test agreed in advance, a leak appears, the model's retirement is announced (60+ days' notice), or token cost beats R saved for 60 days. No automatic weights: after 100+ outcomes a logistic regression may *propose* them, for your YES after validation on later months, never for lot size.

**"Trained on each skill"** means a versioned skill pack, not fine-tuning (which bakes in look-ahead): one narrow question ("high-impact event for XAUUSD within 2 hours?"; narrow subtasks beat broad analyst roles in a leakage-controlled study); numbers computed by code; headlines as quoted data; no web tools; fixed answer choices; 10–20 labelled examples from before any evaluation period; the 5 most similar past setups closed before decision time; and a logistic-regression baseline, used instead if it does as well. Any change is a new version and a new trial.

## 5. Testing path and gates

**The 80% gate** (all must pass):
1. Plan locked first: SHA-256 hash, date, rule origin (human, or which model and its cutoff), risk-config hash. New caps or filters mean a new version and your YES.
2. Your broker's MT5 data; leak test passes (signals unchanged when later bars are removed). Win rate over 90% or profit factor over 4 forces a leak review.
3. 30+ trades in 6 never-seen months, 10+ in the last 3. Never-seen = after the plan lock and after any study of that data; for LLM-designed rules, after every involved model's cutoff (Opus 5.5: July 2026 on; unknown → forward only).
4. Win rate ≥80%, with its 95% range.
5. Expectancy >0 after costs in both windows, lower 95% bound above 0, still >0 at 1.5× costs.
6. Beats the random baseline (1,000 copies of the rule's trades: same direction, stop, target and hold, random entry times): p ≤0.05 never-seen, ≤0.10 last 3 months. After k tries on the same months the best needs p ≤0.05 ÷ k (Holm correction; deflated Sharpe once samples allow); the trial count, earlier studies included, is always shown.
7. Positive expectancy in 2 of 3 volatility terciles, else "regime-specific", kept in shadow.
8. Stop ≤2× the target distance, or a Monte Carlo tail check at real account size passes.

Existing EAs may use an **expectancy-only tier** (all but #4); your call. A pass means "may start a forward test", not "proven": a real +0.1R edge passes a 30-trade test only about 14% of the time; detecting it reliably takes about 600.

| Stage | What happens | Minimum | Pass | If it fails |
|---|---|---|---|---|
| G0 Harness | v1 on synthetic data | — | random data qualifies nothing; planted edge passes; leak blocked; no order code | fix first |
| G1 Safety | Guardian on demo, then alert-only live; enforce after YES | 5 demo days, 20 test trades; 3–5 live days | stop ≤2 s or close on 20/20 stop-less trades; kill ≤5 s in 5/5 drills; daily stop flattens and locks; looser config refused; phone-close drill; 0 false alarms | fix; stay alert-only |
| G2 Feasibility | min-lot risk and margin; 40-trade Monte Carlo from the rule's results | — | fits caps; ≤5% chance of a daily or overall stop | demo/shadow only, or your YES |
| G3 Historical | Strategy Tester "every tick based on real ticks" on your server, or account history; risk rules simulated | see gate | gate (or expectancy tier) | research; next variant needs fresh data |
| G4 Shadow | live data, no influence | 30 resolved calls (30 pauses), 8 weeks | gate on forward data; safe failures; in budget | retire or new version |
| G5 Demo execution | new EA, RiskGate or filter | 2 weeks, 20 orders | stop in every request; no duplicates; expired advisories ignored; no unresolved rejects | fix |
| G6 Small live (rule 8) | minimum lot, locked rule, YES | 30–40 trades | expectancy >0 after all costs incl. API share; full stops ≤ plan +10 points; costs ≤1.5× model; 0 incidents | stop at once on an incident or tripped sequential test |
| G7 Scale | one step at a time, YES | 100+ live trades | lower 95% bound >0; drawdown within Monte Carlo 95th percentile | stay or step down |

Replays of AI agents after their cutoff can kill an idea, never promote it. Slippage comes from live minimum-lot fills. Existing EAs follow rule 8 too (see §11, question 6), and none is switched off without your YES.

## 6. Costs

Prices per 1M tokens (in/out): Haiku 5.5 (`claude-haiku-5-5`) $0.10/$0.50, Sonnet 5.5 (`claude-sonnet-5-5`) $2/$10, Opus 5.5 (`claude-opus-5-5`) $4/$20, Fable 5.1 $10/$50; Batch API half price. Assumed: output includes thinking; 720 hourly cycles a month; one call covers all symbols; no cache discount; token counts are estimates.

| Scenario | What runs | Per cycle | Per month |
|---|---|---|---|
| 1 Starter (Phase 4) | Haiku tagger ×3 hourly (6K in, 0.6K out) + 100 release calls; nightly report/audit (Sonnet, Batch, 60K/5K); weekly review (Opus, Batch, 100K/10K) | $0.0027/hour | ~$6 |
| 2 Full shadow team | 1 + macro (Sonnet ×3 daily, 10K/1.5K) + vetter (Sonnet ×3 on 150 EA trades, 8K/1K) | $0.08/EA trade | ~$21 |
| 3 Big-model army (don't) | 4 specialists, Opus ×3, hourly (10K/2K) | $0.96/hour | ~$690; Fable ~$1,730 |

**Worth it?** At 0.5% risk per trade, a +0.1R edge over 30 trades a month earns about 1.5% of equity a month, so $6 needs about $400 of equity to break even and $21 about $1,400. On a small account the API bill is a research cost you accept up front; an agent enforces only when the R it saves beats its token cost.

**Other costs:** Windows VPS later; optional MQL5 VPS; data $0 to start (skip NewsAPI real-time at $449/month and paid Finnhub). The API is billed separately from Claude plans: Pro has no API credits; Max, Ultra and Team include monthly credits.

**Cut and cap:** call AI only when something changes; fixed prompt text first and live data last so Sonnet/Opus can cache it ($0.20/1M cached reads); Batch anything not live. Console limit $20/month plus $1/day in code; when hit, agents go quiet and EAs carry on under the Guardian.

## 7. Roadmap

About 8–10 hours a week with Claude Code; no AI spend in Phases 1–3.

**Phase 1, safety only (weeks 1–2):**
1. Make the repo private; add a gitleaks pre-commit hook.
2. EA inventory in gitignored `local/`: magic number (the ID an EA stamps on its trades), source available, how it sets stops (in the order, later, or hidden "virtual" stops), typical stop, max positions.
3. One Guardian EA: stops for stop-less trades (hand trades first, EAs by allow-list), equity loss stops rebuilt from deal history, kill switch, phone alerts (`SendNotification`), request budget, netting/hedging aware, hard caps as inputs.
4. A Python twin of its rules with shared JSON test cases, tested in the cloud; you get exact compile steps and paste back errors.
5. Read-only collector; min-lot feasibility table and Monte Carlo, computed on the PC, never committed.
6. PC setup: sleep off, MT5 in Startup, one-click trading off, update hours set, an outside uptime ping (e.g. healthchecks.io; free tier unverified).

Exit: pass G1, then enforce after your YES. Until then we recommend no hand trades on the live account.

- **Phase 0, tonight:** v1 (§10). You: review it and answer §11.
- **Phase 1, weeks 1–2:** the list above. You: the firm's loss rules, magic numbers, symbol suffixes, netting or hedging, a demo account, YES.
- **Phase 2, weeks 3–4:** trade panel (no order without a stop; lots from % risk), calendar exporter, Data Steward on real exports, headline archive, journal. You: 24 months of exports, commission and swaps.
- **Phase 3, weeks 5–7:** EA trade lists; tick costs within 5% of Strategy Tester; swaps; random, buy-and-hold and trend baselines; trial log; RiskGate, demo first, with atomic risk reservation so two EAs can't both pass at once. You: the never-seen months; YES per EA.
- **Phase 4, weeks 8–20:** event tagger in shadow plus nightly report/audit; the next agent only after one passes. You: API key, $20 cap.
- **Phase 5, when something qualifies:** G5 then G6; a VPS if needed. You: YES per rule.
- **Phase 6, after 100+ live trades:** one size step or instrument at a time. You: YES per step.

The Guardian protects your live account in two to three weeks. The earliest an AI agent could influence a live trade is 4–5 months away, possibly never; that is fine.

## 8. Risks and safeguards

| Risk | Safeguard |
|---|---|
| No real edge (most likely) | the gate; default "no pick"; agents still pay as research |
| Stop-less hand trades | Guardian first, then the trade panel |
| Minimum lot too big | feasibility check; misfits stay demo |
| One big correlated bet | clusters, no hedge credit, gap allowance |
| Firm limit breached | equity guard in MT5 at ≤half the firm's limits |
| Luck, overfitting | locked plans, trial log, Holm, forward trades |
| Look-ahead | forward-only AI tests, model-cutoff rule, leak test |
| Costs understated | tick costs, 1.5× stress, swaps, API bill |
| Prompt injection via news | no tools, fixed answers, whitelisted feeds, short pauses |
| AI outage, model retirement | "no opinion"; EAs carry on under code rules |
| PC asleep or crashed | broker-held stops, phone alerts, outside ping |
| Software approving itself | hand-set ceilings, typed YES, dashboard on 127.0.0.1 |
| Public-repo leak | private repo, gitignore, gitleaks |

## 9. Code layout

Starred items are new; the rest exist today.

```
workspace/projects/llm-trader/
  requirements.txt*
  .gitignore*              data/*, out/, local/, logs/, *.db, *.parquet, .pytest_cache/
  .env.example*            ANTHROPIC_API_KEY=, LLM_MODE=offline
  config/
    settings.json          windows, gate, costs, risk
    agents.json*           pinned model, stage, version per agent
    plans/                 locked test plans
  llm_trader/
    __main__.py*           CLI: demo, serve
    models.py
    costs.py               spread, commission, slippage (add swaps)
    state.py*              dashboard state
    server.py*             optional FastAPI, 127.0.0.1
    data/synthetic.py      demo data
    data/loader.py         CSV loading, UTC
    data/symbols.py        symbol specs, min-lot maths
    data/checks.py*        Data Steward
    signals/               one file per rule agent
    eval/backtest.py       simulation
    eval/random_baseline.py  direction-matched (fix)
    eval/gate.py           the 80% gate (extend)
    eval/metrics.py        statistics
    eval/leakcheck.py      leak test
    eval/plans.py          plan locking
    eval/windows.py
    eval/run.py
    eval/power.py*         gate power
    eval/trials.py*        trial log, Holm
    agents/registry.py*    team, lanes, stages
    agents/event_risk.py*  event tagger
    agents/regime.py*      tercile, trend
    agents/supervisor.py*  decision rule, stage checks
    agents/reporter.py*    daily report
    llm/client.py*         schema, stop_reason, timeout, budget
    llm/offline.py*        seeded mock answers
    risk/engine.py*        portfolio limits
    risk/feasibility.py*   min-lot table, Monte Carlo
    risk/guardian_rules.py*  Guardian twin (Phase 1)
    journal/store.py*      append-only SQLite (Phase 2)
    journal/resolve.py*    outcomes from MT5 deals (Phase 2)
    bridge/advisories.py*  pauses, expiry, no lots
    ui/                    dashboard
  mql5/
    GUARDIAN_SPEC.md*      tonight
    Guardian.mq5*          Phase 1
    TradePanel.mq5*        Phase 2
    CalendarExporter.mq5*  Phase 2
    RiskGate.mqh*          Phase 3
  tools/export_mt5_data.py read-only MT5 export
  tests/                   suite + no-order, risk, Guardian, DST tests
  local/ data/ out/        gitignored
```

## 10. Version 1 (overnight build)

**Goal:** a clickable, honest skeleton of the team and the 80% gate, on the existing `llm_trader` engine and dashboard. No MT5, no API key, never trades.

**Pages** (the seven existing tabs):
1. **Team** (home): "SYNTHETIC DATA · AI OFFLINE · NO TRADING" banners; the first superagentic layout (supervisor on top; lanes for Data, Research, Context, Validation, Risk, Monitor, Report; cards with kind, model, stage, status, last output); simulated kill switch; "qualified picks today" (empty, with the reason); self-tests in their own panel.
2. **Agents:** gate checks ✓/✗ in plain English; win rate and expectancy with 95% ranges; full-stop rate; 1.5× costs; long/short and tercile splits; equity curves; random-run histogram; "why 80% can lose" calculator; gate-power chart (how often planted edges of +0.02R to +0.2R pass).
3. **Checks:** data source, fingerprints, gaps, DST alignment, planted faults, an altered "TradingView-style" copy, plan locks, leak tests.
4. **Risk:** limits vs usage, clusters, correlations, min-lot table at four placeholder balances (e.g. 500 to 25,000).
5. **Approvals:** pending changes, typed-confirmation YES/NO (local only), history.
6. **Report:** template daily report (Claude only with a key and `--llm on`, $0.50 cap per run).
7. **Log:** supervisor decisions and would-be phone alerts.

**Agents.** Working code: Supervisor, Data Steward, Validation, Risk engine (its `out/bridge/advisories.json` stays empty), Regime, Reporter. Rule agents: Demo rules A and B, Trend Pullback (textbook demos, not your EAs). Self-tests: Tight Target (wins about 80%, loses after costs: must fail), Leaky (reads the next bar: must be blocked), a planted pattern on synthetic CTRL-SYN (must qualify; never traded). Event-risk tagger: offline mock with seeded disagreement among 3 samples, labelled "self-test, not accuracy", SHADOW, UNMEASURED. Other §2 agents appear as planned cards.

**Data:** the existing seeded generator (seed 7): M15 bars for XAUUSD, EURUSD, GBPUSD, USDJPY, US500, BTCUSD and CTRL-SYN, 2024-10-30 to 2026-10-30, split into design data, 6 never-seen months (to 2026-07-30) and the last 3 months. Your MT5 exports load with `--data mt5` on your PC only and show "not eligible".

**Build order tonight** (each step leaves a working demo):
1. Project `.gitignore` (§9) before any commit.
2. Rename the two demo rules whose names echo real strategy families to `demo_rule_a`, `demo_rule_b`; re-lock their plans as new versions.
3. `random_baseline.py`: keep each trade's direction, stop/target multiples and hold; randomize only entry time, within ±60 minutes of the same time of day. Today it flips direction at random, so a long-biased rule beats it on trend alone.
4. Labels as in §4 (today a win is above +0.05R; break-even means "stop moved to entry").
5. Gate additions: lower bound, 1.5× costs, terciles, long/short, stop:target, Holm with trial count, leak tripwire.
6. `state.py`, `__main__.py`: `demo` writes `out/state.json` and one self-contained `out/dashboard.html` (state as `window.__STATE__`; offline, phone-width).
7. Offline tagger mock, self-test panel, min-lot table, §2 risk defaults in `config/settings.json` (today 1/2/3/50%).
8. `tests/test_no_order_code.py`: fails on `order_send`, `OrderSend` or `create_order` in Python, or a `MetaTrader5` import outside `tools/` (MQL5 is reviewed separately).
9. If time allows: gate-power chart, swaps (triple on Wednesday), planted data faults, DST tests, `serve` mode.

**Done when:** `pytest -q` passes, `demo` runs in under 5 minutes, only the planted self-test qualifies, Tight Target fails with a plain reason, Leaky is blocked, and `eligible_for_money` is false everywhere.

**Run it:**
```
cd workspace/projects/llm-trader
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m llm_trader demo     # out/state.json + out/dashboard.html
python -m llm_trader serve    # optional: http://127.0.0.1:8765
pytest -q
```
Morning review: open `out/dashboard.html`, or the private preview page if shared.

**Mocked:** AI calls, feeds, Batch, alerts, kill switch and approvals (local files), Guardian (spec only; MQL5 can't compile in the cloud). **Not included:** MT5 connection, order code, crypto exchanges, debate agents (no evidence they pay), fine-tuning, per-context "probability" picks.

**Review items not adopted:**
- EA-side hash check of Python risk files: hand-set Guardian ceilings already make files tighten-only.
- Edge-in-spreads and 2× costs as pass rules: shown only; the 1.5× test catches thin edges.
- Automatic weekend close for existing EAs: changes a validated rule; a per-EA YES option instead.
- Windows auto-logon by default: a home security trade-off; your call.
- Two-model ensembles: each needs separate validation; 5 samples of one model instead.

## 11. Decisions and open questions

**Decided** (change any): LLMs never place, size or direct trades; build on the existing code; Guardian first; no AI spend before Phase 4, then one agent at a time; no Python order path (a qualifying rule becomes its own MQL5 EA); §2 defaults reach the live account only after your YES.

**Questions** [recommended default]:
1. Your firm's written loss rules (limits, balance or equity basis, reset time and zone, news, weekend, EA and request rules)? [Until then: daily −2%, kill −6% from peak, on equity.]
2. Make the repo private now? [Yes, before Phase 1.]
3. Hand trade that can't get a stop: close or alert? [Close.]
4. Hand trading before the Guardian enforces? [Pause it on live.]
5. 80% bar for all, or an expectancy-only tier for existing EAs? [Tier for existing EAs.]
6. EAs without 30–40 locked forward trades at minimum lot? [Yes, your rule 8.]
7. Instruments? [1–2 your EAs trade; crypto only if the minimum lot fits.]
8. AI layer down: gated EAs pause or trade under code rules? [Trade.]
9. API budget? [$20/month from Phase 4.]
10. PC or VPS for 24/7? [PC now, sleep off; VPS at Phase 5.]

## Sources

- [Profit Mirage](https://arxiv.org/abs/2510.07920), [FINSABER](https://arxiv.org/abs/2505.07078), [The Alpha Illusion](https://www.alphaxiv.org/abs/2605.16895), [strategies vs luck](https://arxiv.org/abs/2608.27734), [DXRG live record](https://arxiv.org/abs/2609.05663), [Alpha Arena S1](https://x.com/jay_azhang/status/1985481491078328621), [HKU live FX](https://www.hkubs.hku.hk/media/press-release/testing-ai-in-the-real-world-hku-business-school-released-ai-agents-trading-performance/)
- [LLM forecasters](https://proceedings.neurips.cc/paper_files/paper/2024/hash/6ed5bf446f59e2c6646d23058c86424b-Abstract.html), [headline sentiment](https://arxiv.org/abs/2304.07619), [narrow subtasks](https://arxiv.org/abs/2602.23330), [run-to-run variance](https://arxiv.org/abs/2602.18481), [maths errors](https://arxiv.org/pdf/2508.05201), [overconfidence](https://arxiv.org/pdf/2306.13063), [prompt injection](https://arxiv.org/pdf/2512.02261)
- [lookahead test](https://arxiv.org/pdf/2512.23847v1), [memorization](https://arxiv.org/abs/2605.24564), [Deflated Sharpe](https://papers.ssrn.com/abstract=2460551)
- [Opus 5.5 cutoff](https://platform.claude.com/docs/zh-CN/models/opus-5-5/overview), [deprecations](https://platform.claude.com/docs/en/resources/model-deprecations), [API billing](https://support.claude.com/en/articles/9876003-i-subscribe-to-claude-pro-why-do-i-have-to-pay-separately-for-api-usage-on-console), [plan API credits](https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers)
- [MetaTrader5 package](https://pypi.org/project/MetaTrader5/), [one process per terminal](https://www.mql5.com/en/forum/351590), [return codes](https://mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes), [netting vs hedging](https://www.mql5.com/en/blogs/post/774939), [MQL5 calendar](https://mql5.com/en/docs/calendar/calendarvaluehistory), [MQL5 VPS](https://www.mql5.com/en/vps/forex-plans), [Windows VPS prices](https://hostadvice.com/vps/metatrader/), [FTMO rules](https://ftmo.oanda.com/forbidden-trading-practices/)
- [CCXT](https://github.com/ccxt/ccxt/wiki/Manual), [CCXT release](https://www.piwheels.org/project/ccxt/), [crypto CFD rules](https://cointelegraph.com/news/crypto-derivatives-eu-regulations-esma), [ForexFactory feed](https://glama.ai/mcp/servers/atirek-pro/ForexFactory-MCP), [investingLive](https://investinglive.com/news/forexlive-rebrands-as-investinglive-to-reflect-broader-market-coverage-20250721), [CryptoPanic](https://cryptopanic.com/developers/api/about), [CFTC schedule](https://cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm), [Myfxbook](https://myfxbook.com/lv/api), [CoinGlass](https://coinglass.com/pricing), [NewsAPI](https://newsapi.org/pricing)
