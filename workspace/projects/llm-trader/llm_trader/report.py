from __future__ import annotations

from llm_trader.fmt import p_text, pct, r_value, threshold, times
from llm_trader.llm import SupervisorReview

GATE_LABEL = {"qualified": "Qualified", "failed": "Failed", "insufficient": "Too few trades", "blocked": "Blocked"}
CLOSING = "> Agents don't create an edge; they only test ideas faster. Simple fixed rules, proven small first."
EXPORT_COMMAND = ("python tools/export_mt5_data.py --symbols XAUUSD,EURUSD,GBPUSD,USDJPY,US500,BTCUSD --timeframe M15 "
                  "--months 24 --out data/mt5")
NO_FEED = ("There is no live account feed yet, so open risk, margin and losses read 0%. Nothing watches or stops your live "
           "account until the Guardian EA is built (Phase 1).")
VERB = {"qualified": "qualified", "failed": "failed", "insufficient": "had too few trades", "blocked": "was blocked"}


def report_title(generated_at: str) -> str:
    return f"Daily report — {generated_at[:10]}"


def _cell(text) -> str:
    return str(text).replace("|", "/").replace("\n", " ").strip()


def display_name(r: dict) -> str:
    return r["name"] + (" · self-test" if r["self_test"] and not r["name"].startswith("Self-test") else "")


def short_name(r: dict) -> str:
    name = r["name"].removeprefix("Self-test: ").split(" (")[0]
    return f"the {name}" if name[:1].islower() else name


def _wins(w: dict) -> str:
    if not w["trades"]:
        return "no trades"
    lo, hi = w["win_rate_ci"]
    return f"{pct(w['win_rate'])} ({lo:.0%}-{hi:.0%}), {w['trades']} trades"


def _expectancy(w: dict) -> str:
    lo, hi = w["extra"]["expectancy_ci"]
    span = "" if lo is None or hi is None else f" ({r_value(lo)} to {r_value(hi)})"
    return r_value(w["expectancy_r"]) + span


def _random(w: dict, max_p: float) -> str:
    rb, holm = w["random"], w["extra"]["holm_threshold"]
    if not rb["runs"]:
        return "not tested"
    bar = max_p if holm is None else holm
    return f"{'Yes' if rb['p_value'] <= bar else 'No'} ({p_text(rb['p_value'])}, needs ≤ {threshold(bar)})"


def _verdict(state: dict) -> list[str]:
    meta, research = state["meta"], state["research"]
    bar = meta["accuracy_bar"]
    rules = [r for r in research if not r["self_test"]]
    tests = [r for r in research if r["self_test"]]
    real = [r for r in rules if r["gate"]["status"] == "qualified"]
    line = f"- You asked for {bar:.0%}+ accuracy from each agent. **{len(real)} of {len(rules)}** rule agents pass the {bar:.0%} gate."
    if meta["data_mode"] == "demo" and not real:
        line += " On demo data that is the honest, expected result: these prices contain no edge to find."
    lines = [line]
    checks = state["self_tests"]
    if checks:
        ok = sum(1 for t in checks if t["ok"])
        system = len(checks) - len(tests)
        story = ", ".join(f"{short_name(r)} {VERB[r['gate']['status']]}" for r in tests) + (f", plus {system} system checks" if system else "")
        lines.append(f"- Self-tests: **{ok} of {len(checks)}** as expected ({story}), so the harness works."
                     if ok == len(checks) else
                     f"- Self-tests: **{ok} of {len(checks)}** as expected. **Fix the harness before trusting any result.**")
    picks = state["picks_today"]
    lines.append(f"- **Picks today: {len(picks['picks']) or 'none'}.** {picks['reason']}")
    lines.append(f"- **{meta['eligible_note']}**")
    ks, safe = meta["kill_switch"]["on"], meta["safe_mode"]["on"]
    lines.append(f"- Kill switch **{'ON' if ks else 'off'}** · safe mode **{'ON' if safe else 'off'}** · "
                 f"pending approvals **{len(state['approvals']['pending'])}** · advisories sent **{len(state['bridge']['advisories'])}** · "
                 f"tries counted on these months **{meta['trial_count']}**. v1 places no trades.")
    return lines


def _table(state: dict, max_p: float) -> list[str]:
    lines = [
        "| Agent | Wins in never-seen months (95% CI) | Hit full stop | Per trade after costs (95% range) | At 1.5× costs | "
        "Beats random? | Last 3 months | Gate |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in state["research"]:
        h, rec = r["windows"]["holdout"], r["windows"]["recent"]
        lines.append("| " + " | ".join(_cell(x) for x in (
            display_name(r), _wins(h), pct(h["full_stop_rate"], 0), _expectancy(h), r_value(h["extra"]["expectancy_1_5x_costs"]),
            _random(h, max_p), f"{pct(rec['win_rate'])} on {rec['trades']}", GATE_LABEL[r["gate"]["status"]],
        )) + " |")
    return lines


def _traps(state: dict, max_p: float) -> list[str]:
    bar = state["meta"]["accuracy_bar"]
    lines = []
    for r in state["research"]:
        h = r["windows"]["holdout"]
        rb, ratio = h["random"], h["extra"]["stop_target_ratio"]
        if r["gate"]["status"] != "failed" or h["win_rate"] is None or h["win_rate"] < bar - 0.1:
            continue
        why = []
        if rb["runs"] and rb["p_value"] > max_p:
            why.append(f"the same trades at random times win {pct(rb['win_rate_mean'])} too")
        if h["expectancy_r"] is not None and h["expectancy_r"] <= 0:
            why.append(f"it makes {r_value(h['expectancy_r'])} per trade after costs")
        if why:
            line = f"- **A high win rate is not an edge.** {r['name']} wins {pct(h['win_rate'])} of trades, but " + " and ".join(why) + "."
            if ratio:
                line += (f" Its stop is {times(ratio)} the target, so it needs {ratio / (1 + ratio):.0%} wins just to break even before costs "
                         "(break-even win rate = stop ÷ (target + stop)).")
            lines.append(line)
    return lines


def _caught(state: dict, max_p: float, limit: int = 10) -> list[str]:
    rank = {"fail": 0, "warn": 1}
    found = sorted((c for c in state["checks"] if c["status"] in rank and not c["name"].startswith("Passes the")), key=lambda c: rank[c["status"]])
    lines = _traps(state, max_p) + [f"- **{c['name']}** ({c['subject']}): {c['detail']}" for c in found[:limit]]
    if len(found) > limit:
        lines.append(f"- ...and {len(found) - limit} more on the Checks tab.")
    return lines or ["- Nothing needed attention."]


def _self_tests(state: dict) -> list[str]:
    marks = {True: "✓", False: "✗", None: "–"}
    return [f"- {marks[t['ok']]} **{t['name']}**: expected {t['expected']}, got {t['actual']}. {t['detail']}" for t in state["self_tests"]]


def _context(state: dict) -> list[str]:
    tagger, regimes = state["context"]["event_tagger"], state["context"]["regime"]
    pauses = [row["symbol"] for row in tagger["last"] if row["pause"]]
    split = sum(1 for row in tagger["last"] if len(set(row["verdicts"])) > 1)
    lines = [f"- **Event-risk tagger** ({tagger['model']}): {tagger['stage']}, {tagger['measured']}. {len(tagger['last'])} questions, "
             f"{split} with split answers (no opinion); would-be pauses for {', '.join(pauses) or 'none'}, logged only. {tagger['note']}"]
    if regimes:
        lines.append("- **Regime agent:** " + "; ".join(f"{r['symbol']} volatility {r['vol_tercile']}/3, trend {r['trend']}" for r in regimes) + ".")
    return lines


def _no_edge_sentence(state: dict) -> str:
    base = "The real-named symbols (XAUUSD, EURUSD, ...) contain no pattern, so no rule should pass on them"
    test = next((t for t in state["self_tests"] if t["id"] == "no_edge_symbols"), None)
    if test is None or test["ok"] is None:
        return base + "."
    return base + (", and none did." if test["ok"] else f", but {test['actual']}: the gate is too loose (see Self-tests).")


def _balance_sentence(state: dict) -> str:
    account = state["risk"]["account"]
    if account["source"] == "local":
        used = "your own balance from config/settings.local.json (kept on this computer)"
    else:
        used = f"the placeholder balance in settings ({account['balance']:,.0f} {account['currency']}), not your account"
    return f"Risk numbers use {used}; the min-lot table also shows four example balances."


def _demo(state: dict) -> list[str]:
    feed = [] if state["meta"]["account_feed"] else [f"- {NO_FEED}"]
    if state["meta"]["data_mode"] == "demo":
        return [
            f"- Every price is synthetic, with a fixed end date. {_no_edge_sentence(state)}",
            "- CTRL-SYN carries a pattern planted on purpose: the self-test agent must find it, or the gate is broken.",
            "- The event tagger answers with seeded mock samples on a synthetic calendar: a plumbing test, not accuracy.",
            f"- {_balance_sentence(state)}",
            *feed,
        ]
    return [
        "- Prices come from your MT5 export. CTRL-SYN, the self-test symbol, stays synthetic and is never traded.",
        "- The TradingView-style comparison and the event tagger's calendar are simulated.",
        f"- {_balance_sentence(state)}",
        *feed,
    ]


def _next_steps(state: dict) -> list[str]:
    meta = state["meta"]
    steps = []
    if meta["data_mode"] == "demo":
        steps.append(f"On the Windows PC, export your broker's data with `{EXPORT_COMMAND}` (your broker's exact symbol names), then "
                     "run `python -m llm_trader run --data data/mt5` and `python -m llm_trader snapshot` to refresh "
                     "out/dashboard.html. Only results on that data count.")
    for p in state["approvals"]["pending"]:
        steps.append(f"Review change **{p['id']}** ({p['summary']}): approve it with YES or reject it. Nothing changes until you decide.")
    if meta["kill_switch"]["on"]:
        steps.append("The kill switch is ON. Turn it off (type YES) only when you are ready for entries to resume.")
    steps.append("Build the Guardian EA from `mql5/GUARDIAN_SPEC.md` (Phase 1): a stop on every position and one loss limit "
                 "over the whole account come before any new agent.")
    forward = [r["name"] for r in state["research"] if r["stage"] == "forward_test"]
    if forward:
        steps.append(f"Forward test running for {', '.join(forward)}: let its EA take 30-40 trades at minimum lot, then decide.")
    steps.append("Propose rule changes as new locked plans; each one must pass the same gate on months it has never seen.")
    return [f"{i}. {s}" for i, s in enumerate(steps, 1)]


def template_report(state: dict, max_p: float = 0.05) -> str:
    meta = state["meta"]
    lines = [f"# {report_title(meta['generated_at'])}", "", f"**{' · '.join(meta['banners'])}**", "",
             f"**Data:** {meta['data_note']}", "", f"**AI:** {meta['llm_note']}", ""]
    lines += ["## Verdict", "", *_verdict(state), ""]
    lines += [f"## Each agent against the {meta['accuracy_bar']:.0%} bar", "", *_table(state, max_p), ""]
    lines += ["Break-even trades never count as wins. \"Hit full stop\" is the share of trades that lost the whole stop. "
              "\"Beats random\" compares with the same trades at random entry times, after correcting for the number of tries.", ""]
    lines += ["## Why", ""]
    lines += [f"- **{display_name(r)}** ({GATE_LABEL[r['gate']['status']]}): {r['gate']['reasons'][0] if r['gate']['reasons'] else r['stage_note']}"
              for r in state["research"]]
    lines += ["", "## Self-tests", "", *_self_tests(state), ""]
    lines += ["## What the supervisor caught", "", *_caught(state, max_p), ""]
    lines += ["## Context agents (shadow)", "", *_context(state), ""]
    lines += ["## What is demo", "", *_demo(state), ""]
    lines += ["## Next steps", "", *_next_steps(state), "", CLOSING, ""]
    return "\n".join(lines)


def review_section(review: SupervisorReview) -> str:
    lines = ["## Supervisor review (Claude)", "", "_Written by Claude from the numbers above; it cannot change any of them._", "", review.summary.strip(), ""]
    if review.agent_notes:
        lines += [f"- `{n.agent_id}`: {n.note.strip()}" for n in review.agent_notes] + [""]
    if review.warnings:
        lines += ["**Watch out for**", "", *[f"- {w.strip()}" for w in review.warnings], ""]
    if review.next_steps:
        lines += ["**Suggested next steps**", "", *[f"{i}. {s.strip()}" for i, s in enumerate(review.next_steps, 1)], ""]
    return "\n".join(lines)


def build_report(state: dict, review: SupervisorReview | None = None, max_p: float = 0.05) -> dict:
    markdown = template_report(state, max_p)
    if review is not None:
        body, _, closing = markdown.rpartition(CLOSING)
        markdown = body + review_section(review) + "\n" + CLOSING + closing
    return {"title": report_title(state["meta"]["generated_at"]), "generated_by": "claude" if review else "template", "markdown": markdown}
