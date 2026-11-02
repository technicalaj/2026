# Guardian EA: Phase 1 specification

*Status: specification only. No MQL5 code yet. Written for review before anything is compiled.*

## 1. What it is, in one paragraph

The Guardian is one Expert Advisor that runs on a single chart in your MT5 terminal and watches the **whole account**.
It does three jobs, even when Python is not running: it gives **every position a stop** within about 2 seconds (or
closes it), it enforces **one set of loss stops** for the account (daily, weekly and overall), and it obeys **one kill
switch**. It also sends phone alerts about what happened. It never opens a trade, never chooses a direction, never
sizes a position and never moves an existing stop further away. It only adds stops, closes positions, deletes pending
orders and blocks new entries.

## 2. Ground rules

1. **Safety only.** The Guardian may reduce risk; it may never add risk.
2. **Hand-set ceilings.** Its limits are EA inputs you type in by hand. Files written by Python can only make the limits
   **tighter**; a file that tries to loosen a limit is refused and logged.
3. **Works alone.** If Python, the dashboard or the internet is down, the Guardian keeps enforcing everything.
4. **Alert-only first.** It starts in alert-only mode (it reports what it would do) and enforces only after the G1
   drills pass and you type YES.
5. **Small footprint.** At most 200 trade-server requests a day, including retries.
6. **UTC everywhere.** It logs the server's offset from UTC for every day, because the offset changes with daylight
   saving (US clocks changed on 1 November 2026, Europe on 25 October).

## 3. Inputs (hand-set hard ceilings)

| Input | Default | Meaning |
|---|---|---|
| `Mode` | `AlertOnly` | `AlertOnly`: detect and alert, change nothing. `Enforce`: act. |
| `DailyStopPct` | 2.0 | Loss since the daily reset, closed + floating, as % of equity at the reset. |
| `WeeklyStopPct` | 4.0 | Loss since the weekly reset, closed + floating. |
| `OverallKillPct` | 6.0 | Fall from the highest equity ever recorded. |
| `FirmDailyLimitPct` | 0 (off) | Your firm's daily limit, if any. The Guardian uses **half** of it when that is tighter. |
| `FirmOverallLimitPct` | 0 (off) | Your firm's overall limit, if any. Half of it is used when tighter. |
| `DailyResetTime` | `00:00` | Time of the firm's daily reset. |
| `DailyResetZone` | `UTC` | Time zone of that reset (for example `Europe/Prague`). |
| `WeeklyResetDay` | `Monday` | Weekly reset day, at `DailyResetTime`. |
| `StoplessGraceSeconds` | 2 | How long a position may stay without a stop before the Guardian acts. |
| `StoplessRiskPct` | 0.5 | Risk of the stop the Guardian adds, as % of equity. |
| `StoplessFallback` | `Close` | What to do when a valid stop cannot be placed: `Close` or `AlertOnly`. |
| `ManagedMagics` | (empty) | EA magic numbers whose stop-less trades the Guardian may fix. Hand trades (magic 0) are always managed. Other EAs only alert until you add them. |
| `MaxLot` | 0.01 | Largest volume per position. A bigger position is alerted, and closed down to this size only if you enable `EnforceMaxLot`. |
| `EnforceMaxLot` | false | See `MaxLot`. Needs your YES per EA, because it changes how a validated EA behaves. |
| `MaxServerRequestsPerDay` | 200 | Hard budget for trade requests (see section 9). |
| `BridgeFolder` | `llmt` | Folder under the terminal's `Common\Files\` for `kill.flag` and `advisories.json`. |
| `ShowChartButtons` | true | Draws the KILL and FLATTEN ALL buttons. |

Files may tighten but never loosen: a value in a file above the input is ignored and logged as
`config refused: looser than input`.

## 4. Timing

| Trigger | What runs |
|---|---|
| Every trade transaction (`OnTradeTransaction`) | Stop-less check for the affected position; loss-stop check. |
| Timer, every 1 second | Kill flag check; stop-less check for all positions; loss-stop check; heartbeat into the log every minute. |
| Terminal start or EA restart | Rebuild state from deal history (section 7), then run every check once before anything else. |

## 5. Stop-less trades

A position "has no stop" when its stop-loss is 0. The target (take-profit) does not matter.

**Stop distance.** distance = (StoplessRiskPct % × equity) ÷ (volume × money per point), rounded **inwards** (closer
to the price) to the symbol's tick size, so the risk never exceeds `StoplessRiskPct`. Money per point comes from the
symbol's tick value and tick size. The stop goes below the current bid for a buy and above the current ask for a sell.

**Broker minimums.** The stop must be at least the broker's stop level (and outside the freeze level) away from the
current price. If the stop that risks `StoplessRiskPct` would be closer than that minimum, a valid stop is impossible
without risking more, so the fallback applies.

| Situation | Who opened it | Mode `Enforce` | Mode `AlertOnly` |
|---|---|---|---|
| No stop after `StoplessGraceSeconds` | Hand trade (magic 0) | Add the stop. If that fails, apply `StoplessFallback` (default: close). | Alert only |
| No stop after `StoplessGraceSeconds` | EA in `ManagedMagics` | Same as a hand trade | Alert only |
| No stop after `StoplessGraceSeconds` | Any other EA | Alert only (until you add its magic number) | Alert only |
| Valid stop impossible (inside broker minimum) | Managed | Close the position | Alert only |
| Market closed (cannot modify) | Any | Alert, retry when the market opens; close at the open if still stop-less | Alert only |
| Stop removed later by hand | Managed | Treated as a new stop-less position | Alert only |

The Guardian never moves an existing stop. If you widen a stop by hand, it alerts but does not change it back.

## 6. Loss stops

All three are measured on **equity** (closed + floating). The tighter of the input and half the firm's limit is used.

| Stop | Measured from | Triggers at | Action (Enforce) | Lock lasts until |
|---|---|---|---|---|
| Daily | Equity at the last daily reset | Loss ≥ `DailyStopPct` | Close every position, delete every pending order, block new entries | The next daily reset |
| Weekly | Equity at the weekly reset | Loss ≥ `WeeklyStopPct` | Same, and set `kill.flag` | You turn the kill switch off with YES |
| Overall | Highest equity ever recorded | Fall ≥ `OverallKillPct` | Same, and set `kill.flag` | You turn the kill switch off with YES |

"Block new entries" means: any position opened while locked is closed at once (hand trade or EA) and alerted, and any
new pending order is deleted.

## 7. State and restarts

| Item | Where it lives | How it is rebuilt after a restart |
|---|---|---|
| Equity at the daily and weekly reset | Guardian state file in `Common\Files\llmt\` | From deal history: balance at the reset plus floating P&L of positions open at the reset (estimated from the reset-time prices; logged as estimated). |
| Highest equity | Guardian state file | Never lowered by a restart. If the file is missing, the highest balance in the deal history is used as a floor and the Guardian alerts. |
| Locks (daily, weekly, overall) | Guardian state file | Recomputed from the numbers above; a lock is never lifted by a restart. |
| Request count for today | Guardian state file | Counted again from today's log if the file is missing. |

## 8. Kill switch

| Way to turn it on | Effect |
|---|---|
| Dashboard button, `python -m llm_trader killswitch on`, or creating `kill.flag` | Block new entries and delete pending orders within 5 seconds. Open positions keep their stops. |
| KILL chart button | Same, and it creates `kill.flag` so Python sees it too. |
| FLATTEN ALL chart button | Separate button with a confirmation dialog: close every position and delete every pending order. Then the kill switch is on. |
| MT5's Algo Trading button | Backup: stops all EAs, the Guardian included. |
| MT5 phone app | Backup when the PC is down: close positions by hand. |

The kill switch is **on whenever `kill.flag` exists** in the bridge folder. Only Python removes it, after you type YES.
The Guardian never removes it.

## 9. Server-request budget

Every request to the trade server counts: adding a stop, closing a position, deleting an order, including retries.

| Requests today | Behaviour |
|---|---|
| Up to 150 | Normal. |
| 150 to 199 | Alert once; keep acting. |
| 200 | Stop making requests except for loss-stop and kill-switch flattening; alert. |
| Any failed request | Retry at most 3 times, at least 1 second apart; then alert and stop retrying that action. |

Some prop firms flag accounts that send more than about 2,000 requests a day (likely), so 200 leaves a wide margin.

## 10. Netting and hedging accounts

| Account type | How positions are handled |
|---|---|
| Hedging | Each position ticket is checked on its own. Stops are added per ticket; closing closes that ticket. |
| Netting | One position per symbol. The stop applies to the whole net position; closing sends an opposite deal of the full volume. |

The Guardian reads the account type when it starts and logs it. It refuses to run on an account type it does not know.

## 11. Alerts

Alerts go to your phone with `SendNotification` (MT5's push notifications; set your MetaQuotes ID in the terminal).
MT5 limits how often notifications can be sent (a few per second, about ten per minute; check the MQL5 docs), so the
Guardian queues them and merges repeats.

| Event | Alert text (example) |
|---|---|
| Stop added | `Stop added: XAUUSD buy 0.01, stop 2645.50 (0.5% risk). Opened by hand.` |
| Stop-less position closed | `Closed XAUUSD buy 0.01: no valid stop possible (broker minimum).` |
| Unmanaged EA without a stop | `EA 12345 opened EURUSD without a stop. Not managed yet: alert only.` |
| Daily stop | `Daily stop hit (-2.0%). All positions closed, entries locked until the reset.` |
| Weekly or overall stop | `Overall stop hit (-6.0% from peak). Flattened. Kill switch ON until your YES.` |
| Kill switch | `Kill switch ON (kill.flag). New entries blocked.` |
| Request budget | `150 trade requests used today (limit 200).` |
| Refused config | `Refused a settings file that loosens DailyStopPct (3.0 > 2.0).` |

Alerts report what happened. They never say "take this trade".

## 12. Logging

One file per day, `Common\Files\llmt\logs\guardian-YYYYMMDD.csv`, kept on your PC and never committed:

`time_utc, server_offset, event, ticket, symbol, side, volume, magic, action, result_code, requests_today, note`

Every check that leads to an action, every alert, every refused config and a heartbeat every minute are logged. Account
numbers and balances are not written to the log.

## 13. G1 drills (must pass before Enforce mode)

Run on a demo account for 5 days with at least 20 test trades, then 3-5 days alert-only on the live account.

| Drill | Pass when |
|---|---|
| Stop-less hand trades | 20 of 20 get a stop within 2 seconds, or are closed when no valid stop exists. |
| Kill switch | 5 of 5 drills block entries and delete pending orders within 5 seconds (dashboard, chart button and `kill.flag` each tried). |
| Daily stop | Forcing the daily loss past the limit on demo flattens everything and locks entries until the reset. |
| Looser config | A file that loosens a limit is refused and logged; the input value stays in force. |
| Restart | Restarting the terminal mid-lock keeps the lock and the equity peak. |
| Phone close | Closing a position from the MT5 phone app is seen and logged. |
| False alarms | 0 false alarms during the live alert-only days. |

If any drill fails: fix it and stay alert-only. Enforce mode starts only after all drills pass and you type YES.
