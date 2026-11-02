from __future__ import annotations

import hashlib
import inspect
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from llm_trader.costs import cost_model_from_settings
from llm_trader.data.symbols import MissingCostsError, cost_settings
from llm_trader.eval.gate import gate_config
from llm_trader.eval.windows import DEFAULT_WINDOWS
from llm_trader.models import iso
from llm_trader.signals.base import SignalRule
from llm_trader.signals.registry import all_rules

DEFAULT_EVALUATION = {"random_runs": 1000, "leak_cuts": 100, "seed": 7}
DATA_REQUIREMENT = "mt5_export"
PLAN_FIELDS = (
    "rule_id", "version", "origin", "params", "code_sha256", "symbols", "timeframe", "windows", "gate", "evaluation", "costs",
    "risk_config_sha256", "data_requirement",
)
# Kept in the locked plan for the approvals workflow, but they do not change what the test measures.
UNTESTED_FIELDS = ("origin", "risk_config_sha256")
TEST_FIELDS = tuple(name for name in PLAN_FIELDS if name not in UNTESTED_FIELDS)
HASH_EXCLUDED = ("sha256", "locked_at")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
FIELD_LABELS = {"code_sha256": "the rule's code"}


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


def sha256_json(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def plan_hash(plan: dict) -> str:
    return sha256_json({k: v for k, v in plan.items() if k not in HASH_EXCLUDED})


def trial_hash(plan: dict) -> str:
    return sha256_json({name: plan.get(name) for name in TEST_FIELDS})


def risk_config_hash(settings: dict | None) -> str:
    return sha256_json((settings or {}).get("risk") or {})


def _class_source(cls: type) -> str:
    try:
        # Line endings are normalised so a Windows checkout (CRLF) hashes the same as the cloud copy.
        return Path(inspect.getsourcefile(cls)).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    except (TypeError, OSError):
        return f"source unavailable: {cls.__module__}.{cls.__qualname__}"


def rule_code_hash(rule: SignalRule) -> str:
    sources = {cls.__module__: _class_source(cls) for cls in type(rule).__mro__ if cls is not object}
    return sha256_json(sources)


def make_plan(rule: SignalRule, settings_subset: dict | None) -> dict:
    s = plan_settings(settings_subset)
    plan = {
        "rule_id": rule.rule_id,
        "version": rule.version,
        "origin": rule.origin,
        "params": rule.params,
        "code_sha256": rule_code_hash(rule),
        "symbols": list(rule.symbols),
        "timeframe": rule.timeframe,
        "windows": s["windows"],
        "gate": s["gate"],
        "evaluation": s["evaluation"],
        "costs": {
            "model": cost_model_from_settings({"costs": s["costs"]}).describe(),
            "symbols": {sym: cost_settings(sym, s["costs"]) for sym in rule.symbols},
        },
        "risk_config_sha256": risk_config_hash(settings_subset),
        "data_requirement": DATA_REQUIREMENT,
    }
    return json.loads(canonical_json(plan))


def intact(plan: dict | None) -> bool:
    return isinstance(plan, dict) and plan.get("sha256") == plan_hash(plan)


def lock_plan(plan: dict, locked_at=None, previous: dict | None = None, unstudied_since=None) -> dict:
    body = {k: v for k, v in plan.items() if k not in HASH_EXCLUDED and k != "unstudied_since"}
    same_test = intact(previous) and trial_hash(previous) == trial_hash(body)
    # Re-locking the same test (for example after a risk-only change) keeps its original lock time, so "locked before
    # testing" keeps meaning when the test itself was fixed, not when the file was last written.
    if locked_at is not None:
        when = iso(locked_at)
    elif same_test and previous.get("locked_at"):
        when = previous["locked_at"]
    else:
        when = iso(datetime.now(timezone.utc))
    declared = iso(unstudied_since) if unstudied_since is not None else plan.get("unstudied_since")
    if declared is None and same_test:
        declared = previous.get("unstudied_since")
    if declared:
        body["unstudied_since"] = declared
    return {**body, "sha256": plan_hash(body), "locked_at": when}


def _shown(value) -> str:
    if isinstance(value, str) and SHA256_PATTERN.match(value):
        return value[:12]
    return json.dumps(value)


def _differences(old, new, path: str) -> list[str]:
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for key in sorted(set(old) | set(new)):
            out += _differences(old.get(key), new.get(key), f"{path}.{key}" if path else key)
        return out
    if old == new:
        return []
    label = FIELD_LABELS.get(path, path)
    return [f"{label} {_shown(old)} -> {_shown(new)}"]


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


def previous_plan(plans_dir, rule_id: str) -> dict | None:
    try:
        return load_plan(plans_dir, rule_id)
    except ValueError:
        return None


def lock_rule(rule: SignalRule, settings: dict, plans_dir, locked_at=None, unstudied_since=None) -> dict:
    plan = lock_plan(make_plan(rule, settings), locked_at, previous_plan(plans_dir, rule.rule_id), unstudied_since)
    save_plan(plans_dir, plan)
    return plan


def lock_all_plans(settings: dict, plans_dir, rules: list[SignalRule] | None = None, locked_at=None, unstudied_since=None) -> list[dict]:
    return [lock_rule(rule, settings, plans_dir, locked_at, unstudied_since) for rule in (rules if rules is not None else all_rules())]
