from __future__ import annotations

from pathlib import Path

import pandas as pd

from llm_trader.config import write_json
from llm_trader.models import iso, utc

FILE_NAME = "advisories.json"
LEGACY_FILE = "signals.json"
ACTION = "pause"
MAX_PAUSE = pd.Timedelta(hours=4)
ADVISORY_KEYS = ("id", "symbol", "action", "reason", "issued_at", "expires_at")
KILL_NOTE = ("Kill switch is ON: kill.flag is set and the list is empty. A Guardian EA will block every new entry when it is "
             "built; in v1 nothing in MT5 reads the flag yet.")
DEMO_NOTE = ("No advisories: only QUALIFIED agents may pause entries, and none has qualified on your broker's data. "
             "Demo data is never eligible.")
SHADOW_NOTE = "No advisories: no pause agent has qualified yet. The event tagger runs in shadow, so its pauses are only logged."
WRITTEN_NOTE = "{n} pause advisory(ies) written. Each covers both directions and expires within 4 hours; nothing here sizes or opens a trade."


class AdvisoryError(ValueError):
    pass


def advisory(symbol: str, reason: str, issued_at, expires_at) -> dict:
    issued, expires = utc(issued_at), utc(expires_at)
    if not issued < expires <= issued + MAX_PAUSE:
        raise AdvisoryError(f"A pause must expire after it is issued and within {MAX_PAUSE / pd.Timedelta(hours=1):g} hours.")
    return {
        "id": f"pause-{symbol}-{issued:%Y%m%dT%H%MZ}",
        "symbol": symbol,
        "action": ACTION,
        "reason": reason,
        "issued_at": iso(issued),
        "expires_at": iso(expires),
    }


def _validate(item: dict) -> dict:
    if tuple(item) != ADVISORY_KEYS:
        extra = sorted(set(item) - set(ADVISORY_KEYS))
        raise AdvisoryError(f"An advisory holds exactly {', '.join(ADVISORY_KEYS)}" + (f"; not {', '.join(extra)}." if extra else "."))
    if item["action"] != ACTION:
        raise AdvisoryError(f"The only advisory action is {ACTION!r}.")
    advisory(item["symbol"], item["reason"], item["issued_at"], item["expires_at"])
    return dict(item)


def payload(heartbeat, kill: bool, advisories=()) -> dict:
    items = [] if kill else [_validate(a) for a in advisories]
    ids = [a["id"] for a in items]
    if len(ids) != len(set(ids)):
        raise AdvisoryError("Advisory ids must be unique.")
    return {"heartbeat": iso(heartbeat), "kill": bool(kill), "advisories": items}


def write(bridge_dir: Path, data: dict) -> Path:
    bridge_dir = Path(bridge_dir)
    path = write_json(bridge_dir / FILE_NAME, data)
    (bridge_dir / LEGACY_FILE).unlink(missing_ok=True)
    return path


def note(data: dict, data_mode: str) -> str:
    if data["kill"]:
        return KILL_NOTE
    if data["advisories"]:
        return WRITTEN_NOTE.format(n=len(data["advisories"]))
    return DEMO_NOTE if data_mode == "demo" else SHADOW_NOTE


def state(data: dict, file_label: str, kill_flag: bool, data_mode: str) -> dict:
    return {
        "file": file_label, "heartbeat": data["heartbeat"], "kill_flag": bool(kill_flag),
        "advisories": list(data["advisories"]), "note": note(data, data_mode),
    }
