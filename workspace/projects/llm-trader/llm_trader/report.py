from __future__ import annotations

from llm_trader.llm import SupervisorReview

GATE_LABEL = {"qualified": "Qualified", "failed": "Failed", "insufficient": "Too few trades", "blocked": "Blocked"}
CLOSING = "> Agents don't create an edge; they only test ideas faster. Simple fixed rules, proven small first."


def report_title(generated_at: str) -> str:
    return f"Daily report — {generated_at[:10]}"


def _cell(text) -> str:
    return str(text).replace("|", "/").replace("\n", " ").strip()


def _pct(x, digits: int = 1) -> str:
    return "n/a" if x is None else f"{x:.{digits}%}"


def _r(x) -> str:
    return "n/a" if x is None else f"{x:+.2f}R"


def _wins(w: dict) -> str:
    if not w["trades"]:
        return "no trades"
    lo, hi = w["win_rate_ci"]
    return f"{_pct(w['win_rate'])} ({lo:.0%}-{hi:.0%}), {w['trades']} trades"


def _random(w: dict, max_p: float) -> str:
    rb = w["random"]
    if not rb["runs"]:
        return "not tested"
    return f"{'Yes' if rb['p_value'] <= max_p else 'No'} (p = {rb['p_value']:.3f}; random wins {_pct(rb['win_rate_mean'], 0)})"


def _verdict(state: dict) -> list[str]:
    meta, research = state["meta"], state["research"]
    bar = meta["accuracy_bar"]
    qualified = [r for r in research if r["gate"]["status"] == "qualified"]
    rules = [r for r in research if not r["control"]]
    real = [r for r in qualified if not r["control"]]
    lines = [f"- You asked for {bar:.0%}+ accuracy from each agent. **{len(qualified)} of {len(research)}** agents pass the {bar:.0%} gate"
             + (": only the planted-pattern self-test, which proves the gate can recognise a real pattern." if qualified and not real else ".")]
    if rules:
        line = f"- **{len(real)} of {len(rules)}** trading-rule agents qualified."
        if meta["data_mode"] == "demo" and not real:
            line += " On demo data that is the honest, expected result: these prices contain no edge to find."
        lines.append(line)
    lines.append(f"- **{meta['eligible_note']}**")
    ks, safe = meta["kill_switch"]["on"], meta["safe_mode"]["on"]
    lines.append(f"- Kill switch **{'ON' if ks else 'off'}** · safe mode **{'ON' if safe else 'off'}** · "
                 f"pending approvals **{len(state['approvals']['pending'])}** · signals sent to the EA **{state['bridge']['written']}**. "
                 "v1 places no trades.")
    return lines


def _table(state: dict, max_p: float) -> list[str]:
    lines = [
        "| Agent | Wins in never-seen months (95% CI) | Hit full stop | Per trade after costs | Beats random? | Last 3 months | Gate |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in state["research"]:
        h, rec = r["windows"]["holdout"], r["windows"]["recent"]
        name = r["name"] + (" (self-test)" if r["control"] else "")
        lines.append("| " + " | ".join(_cell(x) for x in (
            name, _wins(h), _pct(h["full_stop_rate"], 0), _r(h["expectancy_r"]), _random(h, max_p),
            f"{_pct(rec['win_rate'])} on {rec['trades']}", GATE_LABEL[r["gate"]["status"]],
        )) + " |")
    return lines


def _traps(state: dict, max_p: float) -> list[str]:
    bar = state["meta"]["accuracy_bar"]
    lines = []
    for r in state["research"]:
        h = r["windows"]["holdout"]
        rb = h["random"]
        if r["gate"]["status"] != "failed" or h["win_rate"] is None or h["win_rate"] < bar - 0.1:
            continue
        why = []
        if rb["runs"] and rb["p_value"] > max_p:
            why.append(f"random entries with the same stop and target win {_pct(rb['win_rate_mean'])} too")
        if h["expectancy_r"] is not None and h["expectancy_r"] <= 0:
            why.append(f"it makes {_r(h['expectancy_r'])} per trade after costs")
        if why:
            lines.append(f"- **A high win rate is not an edge.** {r['name']} wins {_pct(h['win_rate'])} of trades, but " + " and ".join(why) + ".")
    return lines


def _caught(state: dict, max_p: float, limit: int = 10) -> list[str]:
    rank = {"fail": 0, "warn": 1}
    found = sorted((c for c in state["checks"] if c["status"] in rank and not c["name"].startswith("Passes the")), key=lambda c: rank[c["status"]])
    lines = _traps(state, max_p) + [f"- **{c['name']}** ({c['subject']}): {c['detail']}" for c in found[:limit]]
    if len(found) > limit:
        lines.append(f"- ...and {len(found) - limit} more on the Checks tab.")
    return lines or ["- Nothing needed attention."]


def _demo(state: dict) -> list[str]:
    account = state["risk"]["account"]
    if state["meta"]["data_mode"] == "demo":
        return [
            "- Every price is synthetic, with a fixed end date. The real-named symbols (XAUUSD, EURUSD, ...) contain no pattern, "
            "so no rule should pass on them, and none did.",
            "- CTRL-SYN carries a pattern planted on purpose: the self-test agent must find it, or the gate is broken.",
            f"- Risk numbers use the balance in settings ({account['balance']:,.0f} {account['currency']}) to show how the limits work.",
        ]
    return [
        "- Prices come from your MT5 export. CTRL-SYN, the self-test symbol, stays synthetic and is never traded.",
        "- The TradingView-style comparison is simulated, to show how much a second data source can move results.",
    ]


def _next_steps(state: dict) -> list[str]:
    meta = state["meta"]
    steps = []
    if meta["data_mode"] == "demo":
        steps.append("On the Windows PC, export your broker's data with `python tools/export_mt5_data.py` and run "
                     "`python -m llm_trader run --data data/mt5`. Only results on that data count.")
    for p in state["approvals"]["pending"]:
        steps.append(f"Review change **{p['id']}** ({p['summary']}): approve it with YES or reject it. Nothing changes until you decide.")
    if meta["kill_switch"]["on"]:
        steps.append("The kill switch is ON. Turn it off (type YES) only when you are ready for signals to flow again.")
    forward = [r["name"] for r in state["research"] if r["stage"] == "forward_test"]
    if forward:
        steps.append(f"Forward test running for {', '.join(forward)}: let the EA take 30-40 trades at minimum lot, then decide.")
    else:
        steps.append("An agent that qualifies on your broker's data starts a forward test of 30-40 trades at minimum lot "
                     "through the bridge file and a fixed-rule EA (planned) before any decision about money.")
    steps.append("Propose rule changes as new locked plans; each one must pass the same gate on months it has never seen.")
    return [f"{i}. {s}" for i, s in enumerate(steps, 1)]


def template_report(state: dict, max_p: float = 0.05) -> str:
    meta = state["meta"]
    lines = [f"# {report_title(meta['generated_at'])}", "", f"**Data:** {meta['data_note']}", "", f"**AI:** {meta['llm_note']}", ""]
    lines += ["## Verdict", "", *_verdict(state), ""]
    lines += [f"## Each agent against the {meta['accuracy_bar']:.0%} bar", "", *_table(state, max_p), ""]
    lines += ["Break-even trades never count as wins. \"Hit full stop\" is the share of trades that lost the whole stop.", ""]
    lines += ["## Why", ""]
    lines += [f"- **{r['name']}** ({GATE_LABEL[r['gate']['status']]}): {r['gate']['reasons'][0] if r['gate']['reasons'] else r['stage_note']}"
              for r in state["research"]]
    lines += ["", "## What the supervisor caught", "", *_caught(state, max_p), ""]
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
