from __future__ import annotations

import json
import os
from dataclasses import dataclass

import anthropic
from pydantic import BaseModel, Field, ValidationError

from llm_trader.config import LlmSettings

FALLBACK_BETA = "server-side-fallback-2026-07-01"
TEMPLATES = "Supervisor review and report use built-in templates."
NO_KEY_NOTE = f"No ANTHROPIC_API_KEY set: {TEMPLATES}"
NOT_ASKED_NOTE = f"AI review is off (run with --llm to use Claude): {TEMPLATES}"
CLAUDE_NOTE = "Claude wrote the review text. It cannot change rules, lots, settings, gate results or the bridge."

STABLE_SYSTEM_PROMPT = """\
You are the Supervisor of Superagentic, a research desk that tests fixed trading rules for a retail trader on a \
small live account. Agents research and supervise; they never place trades. Execution belongs to a fixed-rule EA.

You receive one JSON summary of a run, produced by code. Those numbers are final: never change, round up or \
contradict them, and never add numbers that are not in the JSON.

Apply these ground rules when you write:
- "Accuracy" means the win rate in months the rule has never seen (holdout), with its 95% interval. Break-even \
trades are not wins. Always mention the full-stop rate next to the win rate.
- The bar is accuracy_bar in the JSON. An agent below it is not qualified. Never suggest lowering the bar or \
re-tuning a rule on the same months to pass it.
- A rule must also beat random entries with the same stop and target, after real costs, in the never-seen months \
and in the last 3 months.
- Demo or synthetic data is never eligible for money. The planted-pattern self-test only proves the gate works.
- A qualified rule next runs a 30-40 trade forward test at the minimum lot on the broker's own data.
- Correlated symbols (gold, the dollar, stocks, crypto) can turn several signals into one big bet.
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


def api_key_set() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def ask_claude(volatile_json: str, client=None, cfg: LlmSettings | None = None) -> SupervisorReview | None:
    cfg = cfg or LlmSettings()
    client = client or anthropic.Anthropic()
    resp = client.beta.messages.parse(
        model=cfg.model, max_tokens=cfg.max_tokens,
        betas=[FALLBACK_BETA], fallbacks="default",
        output_config={"effort": cfg.effort},
        system=STABLE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": volatile_json}],
        output_format=SupervisorReview,
    )
    if resp.stop_reason == "refusal":
        return None
    return resp.parsed_output


def supervisor_review(digest: dict, use_llm: bool, client=None, cfg: LlmSettings | None = None) -> LlmResult:
    if not api_key_set():
        return LlmResult("offline", NO_KEY_NOTE)
    if not use_llm:
        return LlmResult("offline", NOT_ASKED_NOTE)
    try:
        review = ask_claude(json.dumps(digest, ensure_ascii=False, sort_keys=True), client, cfg)
    except anthropic.AnthropicError as exc:
        return LlmResult("offline", f"Claude could not be reached ({type(exc).__name__}): {TEMPLATES}")
    except ValidationError:
        return LlmResult("offline", f"Claude's answer did not match the expected format: {TEMPLATES}")
    if review is None:
        return LlmResult("offline", f"Claude declined to review this run: {TEMPLATES}")
    return LlmResult("claude", CLAUDE_NOTE, review)


def _window(w: dict) -> dict:
    rb = w["random"]
    return {
        "trades": w["trades"], "win_rate": w["win_rate"], "win_rate_ci_95": w["win_rate_ci"], "full_stop_rate": w["full_stop_rate"],
        "breakeven_rate": w["breakeven_rate"], "expectancy_r_after_costs": w["expectancy_r"],
        "p_value_vs_random": rb["p_value"], "random_entries_win_rate": rb["win_rate_mean"],
    }


def build_digest(state: dict) -> dict:
    meta = state["meta"]
    return {
        "date": meta["generated_at"][:10],
        "data_mode": meta["data_mode"],
        "data_note": meta["data_note"],
        "accuracy_bar": meta["accuracy_bar"],
        "kill_switch_on": meta["kill_switch"]["on"],
        "safe_mode_on": meta["safe_mode"]["on"],
        "eligible_for_money": meta["eligible_for_money"],
        "agents": [
            {
                "agent_id": r["rule_id"], "name": r["name"], "self_test": r["control"], "symbols": r["symbols"],
                "gate": r["gate"]["status"], "reasons": r["gate"]["reasons"], "stage": r["stage"], "stage_note": r["stage_note"],
                "never_seen_months": _window(r["windows"]["holdout"]), "last_3_months": _window(r["windows"]["recent"]),
            }
            for r in state["research"]
        ],
        "checks_needing_attention": [
            {k: c[k] for k in ("stage", "subject", "name", "status", "detail")} for c in state["checks"] if c["status"] in ("warn", "fail")
        ],
        "risk_limits_pct": state["risk"]["limits"],
        "risk_usage_pct": state["risk"]["usage"],
        "min_lot_fit": [{"symbol": m["symbol"], "risk_pct": m["risk_pct"], "ok": m["ok"]} for m in state["risk"]["min_lot"]],
        "pending_approvals": [p["summary"] for p in state["approvals"]["pending"]],
        "bridge": {"written": state["bridge"]["written"], "note": state["bridge"]["note"]},
    }
