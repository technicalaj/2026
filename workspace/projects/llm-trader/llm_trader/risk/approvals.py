from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from llm_trader.config import (
    PLAN_SECTIONS, UNTRACKED_SECTIONS, Paths, SettingsError, canonical_json, plan_file_hash, plan_hashes, read_json,
    settings_hash, sha256_text, tracked_settings, write_json, write_text,
)
from llm_trader.eval.plans import plan_hash, plan_path
from llm_trader.models import iso
from llm_trader.risk.killswitch import confirmed
from llm_trader.signals.registry import RULE_CLASSES

SETTINGS = "settings"
BASELINE = "baseline"
PLAN_PREFIX = "plan:"
RELOCK_HINT = "python -m llm_trader lock --all --yes"
BASELINE_NOTE = "Approved starting point. Any later change to settings or test plans waits for your YES."
BASELINE_SUMMARY = "Adopt the starting settings and locked plans"
BASELINE_KEPT = "nothing earlier to go back to, so it still waits for your YES and safe mode stays on"


class ApprovalError(ValueError):
    pass


class UnknownChange(ApprovalError):
    pass


@dataclass
class ApprovalStatus:
    pending: list[dict]
    history: list[dict]
    safe_mode: bool
    reason: str | None

    def view(self) -> dict:
        keys = ("id", "created_at", "kind", "summary", "diff")
        return {"pending": [{k: p[k] for k in keys} for p in self.pending], "history": list(reversed(self.history))}


def _now(now=None) -> str:
    return iso(now if now is not None else datetime.now(timezone.utc))


def _short(sha: str | None) -> str:
    return "(none)" if not sha else sha.removeprefix("unreadable-")[:8]


def _fmt(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _flatten(value, prefix: str = "") -> dict:
    if isinstance(value, dict):
        out: dict = {}
        for key, item in value.items():
            out.update(_flatten(item, f"{prefix}.{key}" if prefix else str(key)))
        return out if out or not prefix else {prefix: {}}
    if isinstance(value, list) and value and all(isinstance(x, dict) and "id" in x for x in value):
        out = {}
        for item in value:
            out.update(_flatten({k: v for k, v in item.items() if k != "id"}, f"{prefix}[{item['id']}]"))
        return out
    return {prefix: value}


def settings_diff(old: dict, new: dict) -> list[str]:
    a, b = _flatten(old), _flatten(new)
    lines = []
    for key, value in b.items():
        if key not in a:
            lines.append(f"{key}: (none) → {_fmt(value)}")
        elif a[key] != value:
            lines.append(f"{key}: {_fmt(a[key])} → {_fmt(value)}")
    lines += [f"{key}: {_fmt(value)} → (removed)" for key, value in a.items() if key not in b]
    return lines


def _rule_name(rule_id: str) -> str:
    return next((cls.name for cls in RULE_CLASSES if cls.rule_id == rule_id), rule_id)


def _settings_summary(diff: list[str]) -> str:
    paths = [line.split(":", 1)[0] for line in diff]
    if len(diff) == 1:
        name, change = diff[0].split(": ", 1)
        summary = f"{name.rsplit('.', 1)[-1]} {change}"
    else:
        sections = sorted({p.split(".", 1)[0].split("[", 1)[0] for p in paths})
        summary = f"{len(diff)} settings changed ({', '.join(sections)})"
    if any(p.split(".", 1)[0] in PLAN_SECTIONS for p in paths):
        summary += f". Every test plan includes this, so re-lock them after approving: {RELOCK_HINT}"
    return summary


def _was_rejected(log: dict, subject: str, sha: str | None) -> bool:
    # A removed plan has no hash, so a plain .get() would match "never rejected" against None.
    return subject in log["rejected"] and log["rejected"][subject] == sha


def _order(subject: str) -> tuple:
    return (subject != BASELINE, subject != SETTINGS, subject)


class Approvals:
    def __init__(self, paths: Paths):
        self.paths = paths

    def record(self) -> dict | None:
        if not self.paths.approved.exists():
            return None
        try:
            return read_json(self.paths.approved, "config/approved.json")
        except SettingsError:
            return None

    def _log(self) -> dict:
        log = {"next_id": 1, "pending": [], "history": [], "rejected": {}, "copies": {}}
        if self.paths.approvals_file.exists():
            try:
                saved = json.loads(self.paths.approvals_file.read_text(encoding="utf-8"))
                log.update({k: v for k, v in saved.items() if k in log})
            except (ValueError, OSError):
                pass
        return log

    def _save_log(self, log: dict) -> None:
        log["history"] = log["history"][-200:]
        write_json(self.paths.approvals_file, log)

    def _current(self) -> tuple[dict, dict]:
        raw = read_json(self.paths.settings, "config/settings.json")
        hashes = {SETTINGS: settings_hash(raw)}
        hashes.update({PLAN_PREFIX + k: v for k, v in plan_hashes(self.paths.plans_dir).items()})
        return hashes, tracked_settings(raw)

    @staticmethod
    def _approved_hashes(record: dict) -> dict:
        hashes = {SETTINGS: record.get("settings_sha256")}
        hashes.update({PLAN_PREFIX + k: v for k, v in (record.get("plans") or {}).items()})
        return hashes

    @staticmethod
    def _combined(current: dict) -> str:
        return sha256_text(canonical_json(current))

    @staticmethod
    def _next_id(log: dict) -> str:
        change_id = f"chg-{log['next_id']:03d}"
        log["next_id"] += 1
        return change_id

    def _plan_body(self, rule_id: str) -> dict | None:
        try:
            return json.loads(plan_path(self.paths.plans_dir, rule_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _describe_plan(self, rule_id: str, old: str | None, new: str | None, log: dict) -> tuple[str, list[str]]:
        name = _rule_name(rule_id)
        line = f"plan {rule_id}: {_short(old)} → {_short(new) if new else '(removed)'}"
        if new is None:
            return f"Test plan for {name} was removed", [line]
        if old is None:
            return f"New test plan for {name} (not approved yet)", [line]
        body = self._plan_body(rule_id)
        before = log["copies"].get(PLAN_PREFIX + rule_id)
        diff = settings_diff(before, body) if isinstance(before, dict) and isinstance(body, dict) else [line]
        diff = [d for d in diff if not d.startswith(("sha256:", "locked_at:"))] or [line]
        if not isinstance(body, dict) or body.get("sha256") != plan_hash(body):
            return f"Test plan for {name} was edited by hand, so it no longer matches its lock and the rule stays blocked", diff
        return f"Test plan for {name} was re-locked on {str(body.get('locked_at', ''))[:10]}", diff

    def _wanted(self, record: dict | None, current: dict, copy: dict, log: dict) -> dict:
        if record is None:
            diff = [f"settings: (none) → {_short(current[SETTINGS])}"]
            diff += [f"plan {s.removeprefix(PLAN_PREFIX)}: (none) → {_short(h)}" for s, h in current.items() if s != SETTINGS]
            return {BASELINE: ("baseline", self._combined(current), BASELINE_SUMMARY, diff)}
        approved = self._approved_hashes(record)
        wanted = {}
        for subject in sorted(set(current) | set(approved), key=_order):
            old, new = approved.get(subject), current.get(subject)
            if old == new:
                continue
            if subject == SETTINGS:
                before = record.get("settings")
                if isinstance(before, dict) and settings_hash(before) == old:
                    diff = settings_diff(before, copy) or [f"settings: {_short(old)} → {_short(new)}"]
                    summary = _settings_summary(diff)
                else:
                    diff = [f"settings: {_short(old)} → {_short(new)}"]
                    summary = "Settings changed since your last YES (no approved copy here to compare line by line)"
                wanted[subject] = ("settings", new, summary, diff)
            else:
                summary, diff = self._describe_plan(subject.removeprefix(PLAN_PREFIX), old, new, log)
                wanted[subject] = ("plan", new, summary, diff)
        return wanted

    def _remember_copies(self, record: dict | None, current: dict, log: dict) -> None:
        if record is None:
            return
        approved = self._approved_hashes(record)
        for subject, sha in current.items():
            if subject.startswith(PLAN_PREFIX) and approved.get(subject) == sha:
                body = self._plan_body(subject.removeprefix(PLAN_PREFIX))
                if isinstance(body, dict):
                    log["copies"][subject] = body

    def scan(self, now=None) -> ApprovalStatus:
        when = _now(now)
        log = self._log()
        record = self.record()
        current, copy = self._current()
        self._remember_copies(record, current, log)
        wanted = self._wanted(record, current, copy, log)
        old_pending = {p["subject"]: p for p in log["pending"]}
        pending = []
        for subject, (kind, sha, summary, diff) in wanted.items():
            if _was_rejected(log, subject, sha):
                continue
            existing = old_pending.pop(subject, None)
            if existing and existing["sha256"] == sha:
                pending.append(existing)
                continue
            change_id = existing["id"] if existing else self._next_id(log)
            pending.append({"id": change_id, "created_at": when, "kind": kind, "subject": subject, "sha256": sha, "summary": summary, "diff": diff})
        for item in old_pending.values():
            log["history"].append({"id": item["id"], "decided_at": when, "decision": "withdrawn", "summary": f"{item['summary']} (put back, so nothing changed)"})
        log["rejected"] = {s: h for s, h in log["rejected"].items() if s in wanted and wanted[s][1] == h}
        log["pending"] = pending
        self._save_log(log)
        return self._status(log, wanted)

    @staticmethod
    def _status(log: dict, wanted: dict) -> ApprovalStatus:
        if not wanted:
            return ApprovalStatus(log["pending"], log["history"], False, None)
        ids = [p["id"] for p in log["pending"]]
        parts = []
        if [p["subject"] for p in log["pending"]] == [BASELINE]:
            parts.append(f"The starting settings and locked test plans wait for your YES ({ids[0]}).")
        elif len(ids) == 1:
            parts.append(f"A change waits for your YES ({ids[0]}).")
        elif ids:
            parts.append(f"{len(ids)} changes wait for your YES ({', '.join(ids)}).")
        if any(_was_rejected(log, s, w[1]) for s, w in wanted.items()):
            parts.append("A change you rejected is still in the files: put the approved version back by hand to leave safe mode.")
        parts.append("Nothing is sent to the bridge until then.")
        return ApprovalStatus(log["pending"], log["history"], True, " ".join(parts))

    def _find(self, log: dict, change_id: str) -> dict:
        for item in log["pending"]:
            if item["id"] == change_id:
                return item
        raise UnknownChange(f"No pending change called {change_id!r}.")

    def approve(self, change_id: str, confirm: str | None, now=None) -> dict:
        if not confirmed(confirm):
            raise ApprovalError("Approving a change needs your confirmation: type YES.")
        when = _now(now)
        log = self._log()
        item = self._find(log, change_id)
        current, copy = self._current()
        subject = item["subject"]
        expected = self._combined(current) if subject == BASELINE else current.get(subject)
        if expected != item["sha256"]:
            raise ApprovalError("This change was edited again after it was listed. Run the pipeline again and review the new version.")
        record = self.record() or {}
        if subject == BASELINE:
            record = self._fresh_record(current, copy, when)
        elif subject == SETTINGS:
            record.update(settings_sha256=current[SETTINGS], settings=copy)
        else:
            plans = record.setdefault("plans", {})
            rule_id = subject.removeprefix(PLAN_PREFIX)
            if expected is None:
                plans.pop(rule_id, None)
            else:
                plans[rule_id] = expected
        record["approved_at"] = when
        write_json(self.paths.approved, record)
        log["pending"].remove(item)
        log["rejected"].pop(subject, None)
        entry = {"id": item["id"], "decided_at": when, "decision": "approved", "summary": item["summary"]}
        log["history"].append(entry)
        self._remember_copies(record, current, log)
        self._save_log(log)
        return entry

    def reject(self, change_id: str, now=None) -> dict:
        when = _now(now)
        log = self._log()
        item = self._find(log, change_id)
        subject = item["subject"]
        if subject == BASELINE:
            # Rejecting the starting point must not hide it: there is nothing to restore, and it must stay approvable.
            entry = {"id": item["id"], "decided_at": when, "decision": "rejected", "summary": f"{item['summary']} ({BASELINE_KEPT})"}
            log["history"].append(entry)
            self._save_log(log)
            return entry
        restored = self._restore(subject, log)
        if not restored:
            log["rejected"][subject] = item["sha256"]
        log["pending"].remove(item)
        outcome = "put back to the approved version" if restored else "still in the files: put it back by hand; safe mode stays on"
        entry = {"id": item["id"], "decided_at": when, "decision": "rejected", "summary": f"{item['summary']} ({outcome})"}
        log["history"].append(entry)
        self._save_log(log)
        return entry

    def _restore(self, subject: str, log: dict) -> bool:
        record = self.record()
        if record is None:
            return False
        if subject == SETTINGS:
            before = record.get("settings")
            if not isinstance(before, dict) or settings_hash(before) != record.get("settings_sha256"):
                return False
            raw = read_json(self.paths.settings, "config/settings.json")
            restored = {k: (raw[k] if k in UNTRACKED_SECTIONS else before[k]) for k in raw if k in before or k in UNTRACKED_SECTIONS}
            restored.update({k: v for k, v in before.items() if k not in restored})
            write_json(self.paths.settings, restored)
            return True
        if subject.startswith(PLAN_PREFIX):
            body = log["copies"].get(subject)
            approved = self._approved_hashes(record).get(subject)
            if not isinstance(body, dict) or plan_hash(body) != approved:
                return False
            path = plan_path(self.paths.plans_dir, subject.removeprefix(PLAN_PREFIX))
            write_text(path, json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
            return plan_file_hash(path) == approved
        return False

    @staticmethod
    def _fresh_record(current: dict, copy: dict, when: str) -> dict:
        return {
            "approved_at": when,
            "note": BASELINE_NOTE,
            "settings_sha256": current[SETTINGS],
            "plans": {s.removeprefix(PLAN_PREFIX): h for s, h in current.items() if s.startswith(PLAN_PREFIX)},
            "settings": copy,
        }

    def write_baseline(self, now=None) -> dict:
        current, copy = self._current()
        record = self._fresh_record(current, copy, _now(now))
        write_json(self.paths.approved, record)
        return record

    def settings_pending(self) -> bool:
        record = self.record()
        if record is None:
            return True
        current, _ = self._current()
        return current[SETTINGS] != record.get("settings_sha256")

    def record_lock(self, rule_id: str, plan: dict, now=None) -> dict:
        record = self.record()
        if record is None:
            raise ApprovalError("There is no approved starting point yet: approve the pending baseline change first.")
        when = _now(now)
        subject = PLAN_PREFIX + rule_id
        record.setdefault("plans", {})[rule_id] = plan_hash(plan)
        record["approved_at"] = when
        write_json(self.paths.approved, record)
        log = self._log()
        stale = [p for p in log["pending"] if p["subject"] == subject]
        for item in stale:
            log["pending"].remove(item)
        log["rejected"].pop(subject, None)
        entry = {
            "id": stale[0]["id"] if stale else self._next_id(log),
            "decided_at": when,
            "decision": "approved",
            "summary": f"Re-locked the test plan for {_rule_name(rule_id)} (confirmed with --yes)",
        }
        log["history"].append(entry)
        log["copies"][subject] = plan
        self._save_log(log)
        return entry
