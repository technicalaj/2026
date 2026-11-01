from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from llm_trader.costs import cost_model_from_settings
from llm_trader.data.symbols import MissingCostsError, cost_settings
from llm_trader.eval.gate import gate_config
from llm_trader.eval.windows import DEFAULT_WINDOWS
from llm_trader.models import iso
from llm_trader.signals.base import SignalRule
from llm_trader.signals.registry import all_rules

DEFAULT_EVALUATION = {"random_runs": 1000, "win_epsilon_r": 0.05, "leak_cuts": 12, "seed": 7}
DATA_REQUIREMENT = "mt5_export"
PLAN_FIELDS = ("rule_id", "version", "params", "symbols", "timeframe", "windows", "gate", "evaluation", "costs", "data_requirement")
HASH_EXCLUDED = ("sha256", "locked_at")


def evaluation_config(settings: dict | None) -> dict:
    return {**DEFAULT_EVALUATION, **((settings or {}).get("evaluation") or {})}


def plan_settings(settings: dict | None) -> dict:
    s = settings or {}
    return {
        "windows": {**DEFAULT_WINDOWS, **(s.get("windows") or {})},
        "gate": gate_config(s.get("gate")),
        "evaluation": evaluation_config(s),
        "costs": s.get("costs") or {},
    }


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def plan_hash(plan: dict) -> str:
    body = {k: v for k, v in plan.items() if k not in HASH_EXCLUDED}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def make_plan(rule: SignalRule, settings_subset: dict | None) -> dict:
    s = plan_settings(settings_subset)
    plan = {
        "rule_id": rule.rule_id,
        "version": rule.version,
        "params": rule.params,
        "symbols": list(rule.symbols),
        "timeframe": rule.timeframe,
        "windows": s["windows"],
        "gate": s["gate"],
        "evaluation": s["evaluation"],
        "costs": {
            "model": cost_model_from_settings({"costs": s["costs"]}).describe(),
            "symbols": {sym: cost_settings(sym, s["costs"]) for sym in rule.symbols},
        },
        "data_requirement": DATA_REQUIREMENT,
    }
    return json.loads(canonical_json(plan))


def lock_plan(plan: dict, locked_at=None) -> dict:
    body = {k: v for k, v in plan.items() if k not in HASH_EXCLUDED}
    when = iso(locked_at) if locked_at is not None else iso(datetime.now(timezone.utc))
    return {**body, "sha256": plan_hash(body), "locked_at": when}


def _differences(old, new, path: str) -> list[str]:
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for key in sorted(set(old) | set(new)):
            out += _differences(old.get(key), new.get(key), f"{path}.{key}" if path else key)
        return out
    if old == new:
        return []
    return [f"{path} {json.dumps(old)} -> {json.dumps(new)}"]


def verify_plan(locked: dict | None, rule: SignalRule, settings_subset: dict | None) -> tuple[bool, str | None]:
    if not locked:
        return False, "No locked test plan. Lock one (needs your YES) before this rule can be tested."
    if locked.get("sha256") != plan_hash(locked):
        return False, "The plan file was edited after it was locked (its hash no longer matches)."
    try:
        expected = make_plan(rule, settings_subset)
    except MissingCostsError as exc:
        return False, str(exc)
    diffs = []
    for name in PLAN_FIELDS:
        diffs += _differences(locked.get(name), expected[name], name)
    if diffs:
        shown = "; ".join(diffs[:4]) + ("; ..." if len(diffs) > 4 else "")
        return False, f"Changed after the plan was locked: {shown}."
    return True, None


def plan_path(plans_dir, rule_id: str) -> Path:
    return Path(plans_dir) / f"{rule_id}.json"


def load_plan(plans_dir, rule_id: str) -> dict | None:
    path = plan_path(plans_dir, rule_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Plan file {path.name} is not valid JSON ({exc.msg})") from exc


def save_plan(plans_dir, plan: dict) -> Path:
    path = plan_path(plans_dir, plan["rule_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def lock_all_plans(settings: dict, plans_dir, rules: list[SignalRule] | None = None, locked_at=None) -> list[dict]:
    locked = [lock_plan(make_plan(rule, settings), locked_at) for rule in (rules if rules is not None else all_rules())]
    for plan in locked:
        save_plan(plans_dir, plan)
    return locked
