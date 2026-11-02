from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from llm_trader.models import HolmDecision, iso, utc

TRIALS_FORMAT = "superagentic-trials/2"
TRIALS_FILE = "trials.json"
REQUIRED_KEYS = ("rule_id", "version", "holdout", "first_evaluated_at")
# Records from the first log format did not say which data they used, so they count against every data source.
ANY_DATA = "any"
MIN_OVERLAP = pd.Timedelta(days=30)


@dataclass(frozen=True)
class TrialEntry:
    rule_id: str
    version: str
    test_sha256: str
    locked_at: str | None = None


def dataset_fingerprint(dataset: dict) -> str:
    lines = sorted(f"{symbol}:{prov.get('sha256')}" for symbol, (_, prov) in dataset.items())
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def data_id(dataset: dict) -> str:
    provs = [prov for _, prov in dataset.values()]
    if any(p.get("source") == "mt5_export" for p in provs):
        servers = sorted({str(p["server"]) for p in provs if p.get("source") == "mt5_export" and p.get("server")})
        # Hashed so the broker's server name never appears in the log.
        return "mt5:" + (hashlib.sha256("|".join(servers).encode("utf-8")).hexdigest()[:12] if servers else "unknown-server")
    if provs and all(p.get("source") == "synthetic" for p in provs):
        return "synthetic"
    return "other"


def default_trials_path(plans_dir) -> Path:
    return Path(plans_dir).parent / TRIALS_FILE


def empty_log() -> dict:
    return {"format": TRIALS_FORMAT, "records": []}


def _test_key(record: dict) -> str:
    return record.get("test_sha256") or record.get("plan_sha256") or ""


def load_trials(path) -> dict:
    path = Path(path)
    if not path.exists():
        return empty_log()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is not valid JSON ({exc.msg})") from exc
    records = data.get("records") if isinstance(data, dict) else None
    valid = isinstance(records, list) and all(
        isinstance(r, dict) and all(k in r for k in REQUIRED_KEYS) and _test_key(r) for r in records
    )
    if not valid:
        raise ValueError(f"{path.name} is not a trial log")
    return data


def save_trials(path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(prefix=".trials-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def same_months(window, holdout) -> bool:
    a0, a1 = utc(window[0]), utc(window[1])
    b0, b1 = utc(holdout[0]), utc(holdout[1])
    return min(a1, b1) - max(a0, b0) >= min(MIN_OVERLAP, (b1 - b0) / 2)


def _matches(record: dict, data_key: str, holdout) -> bool:
    return record.get("data_id", ANY_DATA) in (data_key, ANY_DATA) and same_months(record["holdout"], holdout)


def merge_trials(data: dict, data_key: str, fingerprint: str, entries: list[TrialEntry], holdout, now=None) -> tuple[dict, int]:
    records = list(data["records"])
    seen = {_test_key(r) for r in records if _matches(r, data_key, holdout)}
    when = iso(now if now is not None else datetime.now(timezone.utc))
    added = 0
    for e in entries:
        if e.test_sha256 in seen:
            continue
        seen.add(e.test_sha256)
        added += 1
        records.append({
            "data_id": data_key, "test_sha256": e.test_sha256, "rule_id": e.rule_id, "version": e.version,
            "holdout": [iso(holdout[0]), iso(holdout[1])], "first_evaluated_at": when, "locked_at": e.locked_at,
            "fingerprint": fingerprint,
        })
    return {**data, "format": TRIALS_FORMAT, "records": records}, added


def count_trials(data: dict, data_key: str, holdout) -> int:
    return len({_test_key(r) for r in data["records"] if _matches(r, data_key, holdout)})


def first_test_before_lock(data: dict, data_key: str, holdout, test_key: str, locked_at: str | None) -> str | None:
    early = []
    for r in data["records"]:
        if _test_key(r) != test_key or not _matches(r, data_key, holdout):
            continue
        # A record keeps the lock time valid when it was tested; older records without one are compared with today's lock.
        lock = r.get("locked_at") or locked_at
        if lock is None or utc(r["first_evaluated_at"]) < utc(lock):
            early.append(r["first_evaluated_at"])
    return min(early) if early else None


def record_trials(path, data_key: str, fingerprint: str, entries: list[TrialEntry], holdout, now=None) -> int:
    path = Path(path)
    merged, added = merge_trials(load_trials(path), data_key, fingerprint, entries, holdout, now)
    if added:
        save_trials(path, merged)
    return count_trials(merged, data_key, holdout)


def open_trials(path) -> tuple[dict | None, str | None]:
    try:
        return load_trials(path), None
    except (OSError, ValueError) as exc:
        return None, f"the trial log is unreadable ({exc}), so the number of tries is unknown"


def tally_trials(
    path, data_key: str, fingerprint: str, entries: list[TrialEntry], holdout, record: bool = True, now=None,
) -> tuple[int | None, str | None]:
    log, note = open_trials(path)
    if log is None:
        return None, note
    merged, added = merge_trials(log, data_key, fingerprint, entries, holdout, now)
    if record and added:
        try:
            save_trials(path, merged)
        except OSError as exc:
            return count_trials(merged, data_key, holdout), f"the trial log could not be saved ({exc.strerror or exc})"
    return count_trials(merged, data_key, holdout), None


def holm_decisions(p_values: list[float], tries: int, alpha: float = 0.05) -> list[HolmDecision]:
    k = len(p_values)
    m = max(int(tries), k, 1)
    out: list[HolmDecision | None] = [None] * k
    still_rejecting = True
    for rank, i in enumerate(sorted(range(k), key=lambda j: (p_values[j], j)), start=1):
        threshold = alpha / (m - rank + 1)
        under = p_values[i] <= threshold
        passed = still_rejecting and under
        out[i] = HolmDecision(float(p_values[i]), rank, k, m, threshold, passed, stopped_early=under and not still_rejecting)
        # Holm's step-down: the first p above its threshold stops the procedure for every larger p.
        still_rejecting = passed
    return out
