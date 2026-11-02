from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import anthropic
from pydantic import BaseModel, Field, ValidationError

from llm_trader.config import LlmSettings, write_json

FALLBACK_BETA = "server-side-fallback-2026-07-01"
TEMPLATES = "Supervisor review and report use built-in templates."
NO_KEY_NOTE = f"No ANTHROPIC_API_KEY set: {TEMPLATES}"
NOT_ASKED_NOTE = f"AI review is off (run with --llm on to use Claude): {TEMPLATES}"
CLAUDE_NOTE = "Claude wrote the review text. It cannot change rules, lots, settings, gate results or the bridge."
CAP_NOTE = "The AI cost cap (${cap:.2f} per run) leaves no room for another call: " + TEMPLATES
DAILY_CAP_NOTE = "Today's AI budget (${cap:.2f} a day, reset at 00:00 UTC) is used up, so Claude was not called: " + TEMPLATES
# USD per million tokens (input, output), from PLAN.md section 6 and the Claude API price list.
PRICES_PER_MTOK = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-fable-5-1": (10.0, 50.0),
}
UNKNOWN_PRICE = max(PRICES_PER_MTOK.values())
CACHE_WRITE_FACTOR = 1.25
CHARS_PER_TOKEN = 3
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")

STABLE_SYSTEM_PROMPT = """\
You are the Supervisor of Superagentic, a research desk that tests fixed trading rules for a retail trader on a \
small live account. Agents research and supervise; they never place trades. Execution belongs to fixed-rule EAs.

You receive one JSON summary of a run, produced by code. Those numbers are final: never change, round up or \
contradict them, and never add numbers that are not in the JSON.

Apply these ground rules when you write:
- "Accuracy" means the win rate in months the rule has never seen (holdout), with its 95% interval. Break-even \
trades are not wins. Always mention the full-stop rate next to the win rate.
- The bar is accuracy_bar in the JSON. An agent below it is not qualified. Never suggest lowering the bar or \
re-tuning a rule on the same months to pass it.
- A rule must also make money after costs (also at 1.5x costs), beat random entries with the same direction, stop and \
target, and stay positive in at least 2 of 3 volatility regimes. trial_count is how many ideas were tried on the same months.
- Self-tests only prove the test harness works: the planted pattern must qualify, the trap must fail, the leaky rule \
must be blocked. They are never traded. Demo or synthetic data is never eligible for money.
- Agents in shadow (like the event tagger) are logged and scored only; under 30 scored calls they are UNMEASURED.
- A qualified rule next runs a 30-40 trade forward test at the minimum lot on the broker's own data.
- Correlated symbols (gold, the dollar, stocks, crypto) can turn several trades into one big bet.
- Nothing changes without the trader's explicit YES. You cannot change rules, lots, settings, gate results or the bridge.

Write short, plain English for a beginner-to-intermediate trader. No hype; explain any jargon in a few words.
"""


class AgentNote(BaseModel):
    agent_id: str = Field(description="id of the agent the note is about")
    note: str = Field(description="one or two plain sentences")


class SupervisorReview(BaseModel):
    summary: str = Field(description="three to five sentences: what this run shows and what it does not")
    agent_notes: list[AgentNote]
    warnings: list[str] = Field(description="risks or data problems the trader should know about")
    next_steps: list[str] = Field(description="concrete next steps, in order")


@dataclass
class LlmResult:
    mode: str
    note: str
    review: SupervisorReview | None = None
    cost_usd: float = 0.0


@dataclass
class Budget:
    cap_usd: float
    spent_usd: float = 0.0
    calls: int = 0
    daily: bool = False

    def allows(self, worst_case_usd: float) -> bool:
        return self.spent_usd + worst_case_usd <= self.cap_usd + 1e-12

    def charge(self, usd: float) -> None:
        self.spent_usd += usd
        self.calls += 1


def spent_today(path, day: str) -> float:
    try:
        return float(json.loads(Path(path).read_text(encoding="utf-8")).get(day, 0.0))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0.0


def record_spend(path, day: str, usd: float) -> None:
    if usd <= 0:
        return
    try:
        ledger = json.loads(Path(path).read_text(encoding="utf-8"))
        ledger = ledger if isinstance(ledger, dict) else {}
    except (OSError, ValueError):
        ledger = {}
    ledger[day] = round(float(ledger.get(day, 0.0)) + usd, 6)
    write_json(Path(path), dict(sorted(ledger.items())[-60:]))


def run_budget(cfg: LlmSettings, path, day: str) -> Budget:
    left_today = max(0.0, cfg.daily_cap_usd - spent_today(path, day))
    return Budget(min(cfg.cost_cap_usd, left_today), daily=left_today < cfg.cost_cap_usd)


def llm_wanted(choice: str | None) -> bool:
    if choice is not None:
        return choice == "on"
    return os.environ.get("LLM_MODE", "").strip().lower() in ("on", "claude")


def api_key_set() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def price(model: str | None) -> tuple[float, float]:
    return PRICES_PER_MTOK.get(model or "", UNKNOWN_PRICE)


def tokens_cost(rate: tuple[float, float], input_tokens: int = 0, output_tokens: int = 0, cache_write: int = 0, cache_read: int = 0) -> float:
    per_in, per_out = rate
    # Cache reads are charged at the full input price so the cap errs on the safe side.
    return ((input_tokens + cache_read + cache_write * CACHE_WRITE_FACTOR) * per_in + output_tokens * per_out) / 1e6


def worst_case_cost(model: str, max_tokens: int, *texts: str) -> float:
    return tokens_cost(price(model), sum(len(t) for t in texts) // CHARS_PER_TOKEN + 1, max_tokens)


def response_cost(resp, requested_model: str) -> float | None:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return None
    # usage.iterations holds every attempt, refused ones and fallbacks included; top-level usage only the last one.
    entries = list(getattr(usage, "iterations", None) or []) or [usage]
    totals = {f: sum(int(getattr(e, f, 0) or 0) for e in entries) for f in TOKEN_FIELDS}
    rate = max(price(requested_model), price(getattr(resp, "model", None)), key=lambda p: p[1])
    return tokens_cost(rate, totals["input_tokens"], totals["output_tokens"], totals["cache_creation_input_tokens"], totals["cache_read_input_tokens"])


def fallback_served(resp) -> bool:
    iterations = getattr(getattr(resp, "usage", None), "iterations", None) or []
    return any(getattr(entry, "type", None) == "fallback_message" for entry in iterations)


def no_opinion(resp, pinned_model: str) -> bool:
    if resp is None or getattr(resp, "stop_reason", None) == "refusal":
        return True
    return fallback_served(resp) or getattr(resp, "model", pinned_model) != pinned_model


def _call(volatile_json: str, client, cfg: LlmSettings):
    return client.beta.messages.parse(
        model=cfg.model, max_tokens=cfg.max_tokens,
        betas=[FALLBACK_BETA], fallbacks="default",
        output_config={"effort": cfg.effort},
        system=STABLE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": volatile_json}],
        output_format=SupervisorReview,
    )


def supervisor_review(digest: dict, use_llm: bool, client=None, cfg: LlmSettings | None = None, budget: Budget | None = None) -> LlmResult:
    if not api_key_set():
        return LlmResult("offline", NO_KEY_NOTE)
    if not use_llm:
        return LlmResult("offline", NOT_ASKED_NOTE)
    cfg = cfg or LlmSettings()
    budget = budget or Budget(cfg.cost_cap_usd)
    content = json.dumps(digest, ensure_ascii=False, sort_keys=True)
    worst = worst_case_cost(cfg.model, cfg.max_tokens, STABLE_SYSTEM_PROMPT, content)
    if not budget.allows(worst):
        return LlmResult("offline", (DAILY_CAP_NOTE.format(cap=cfg.daily_cap_usd) if budget.daily else CAP_NOTE.format(cap=budget.cap_usd)))
    try:
        resp = _call(content, client or anthropic.Anthropic(), cfg)
    except anthropic.AnthropicError as exc:
        return LlmResult("offline", f"Claude could not be reached ({type(exc).__name__}): {TEMPLATES}")
    except ValidationError:
        budget.charge(worst)
        return LlmResult("offline", f"Claude's answer did not match the expected format: {TEMPLATES}", cost_usd=worst)
    cost = response_cost(resp, cfg.model)
    cost = worst if cost is None else cost
    budget.charge(cost)
    review = None if resp.stop_reason == "refusal" else resp.parsed_output
    if review is None:
        return LlmResult("offline", f"Claude declined to review this run: {TEMPLATES}", cost_usd=cost)
    note = f"{CLAUDE_NOTE} Estimated cost ${cost:.3f} of the ${budget.cap_usd:.2f} cap for this run."
    return LlmResult("claude", note, review, cost)


def _window(w: dict) -> dict:
    rb, extra = w["random"], w["extra"]
    return {
        "trades": w["trades"], "win_rate": w["win_rate"], "win_rate_ci_95": w["win_rate_ci"], "full_stop_rate": w["full_stop_rate"],
        "breakeven_rate": w["breakeven_rate"], "expectancy_r_after_costs": w["expectancy_r"],
        "expectancy_ci_95": extra["expectancy_ci"], "expectancy_at_1_5x_costs": extra["expectancy_1_5x_costs"],
        "p_value_vs_random": rb["p_value"], "random_entries_win_rate": rb["win_rate_mean"], "holm_threshold": extra["holm_threshold"],
    }


def build_digest(state: dict) -> dict:
    meta, context = state["meta"], state["context"]
    tagger = context["event_tagger"]
    return {
        "date": meta["generated_at"][:10],
        "banners": meta["banners"],
        "data_mode": meta["data_mode"],
        "data_note": meta["data_note"],
        "accuracy_bar": meta["accuracy_bar"],
        "trial_count": meta["trial_count"],
        "kill_switch_on": meta["kill_switch"]["on"],
        "safe_mode_on": meta["safe_mode"]["on"],
        "eligible_for_money": meta["eligible_for_money"],
        "picks_today": state["picks_today"],
        "agents": [
            {
                "agent_id": r["rule_id"], "name": r["name"], "kind": r["kind"], "expected": r["expected"],
                "self_test_ok": r["self_test_ok"], "symbols": r["symbols"], "gate": r["gate"]["status"], "reasons": r["gate"]["reasons"],
                "stage": r["stage"], "stage_note": r["stage_note"],
                "never_seen_months": _window(r["windows"]["holdout"]), "last_3_months": _window(r["windows"]["recent"]),
            }
            for r in state["research"]
        ],
        "self_tests": [{k: t[k] for k in ("name", "expected", "actual", "ok")} for t in state["self_tests"]],
        "event_tagger": {k: tagger[k] for k in ("stage", "measured", "samples", "model", "note")},
        "regime": context["regime"],
        "checks_needing_attention": [
            {k: c[k] for k in ("stage", "subject", "name", "status", "detail")} for c in state["checks"] if c["status"] in ("warn", "fail")
        ],
        "risk_limits_pct": state["risk"]["limits"],
        "risk_usage_pct": state["risk"]["usage"],
        "min_lot_fit": [{"symbol": m["symbol"], "risk_pct": m["risk_pct"], "ok": m["ok"]} for m in state["risk"]["min_lot"]],
        "pending_approvals": [p["summary"] for p in state["approvals"]["pending"]],
        "bridge": {"advisories": len(state["bridge"]["advisories"]), "kill_flag": state["bridge"]["kill_flag"], "note": state["bridge"]["note"]},
    }
