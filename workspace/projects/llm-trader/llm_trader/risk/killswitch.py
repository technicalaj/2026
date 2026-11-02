from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from llm_trader.config import CONFIRM_WORD, write_json, write_text
from llm_trader.models import iso

UNREADABLE = "The kill switch file could not be read, so it is treated as ON until it is turned off with YES."
FLAG_FOUND = "kill.flag was found in the bridge folder (set outside the dashboard), so everything is stopped until it is turned off with YES."


class KillSwitchError(ValueError):
    pass


def _now(now=None) -> str:
    return iso(now if now is not None else datetime.now(timezone.utc))


def confirmed(confirm) -> bool:
    return isinstance(confirm, str) and confirm.strip() == CONFIRM_WORD


class KillSwitch:
    def __init__(self, path: Path, flag_path: Path | None = None):
        self.path = Path(path)
        self.flag_path = Path(flag_path) if flag_path is not None else None

    @classmethod
    def at(cls, paths) -> "KillSwitch":
        return cls(paths.killswitch_file, paths.kill_flag)

    def _read(self) -> dict:
        if not self.path.exists():
            return {"on": False, "reason": None, "changed_at": None, "history": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("on"), bool):
                raise ValueError
        except (ValueError, OSError):
            # Fail safe: a damaged switch must stop everything rather than let anything out.
            return {"on": True, "reason": UNREADABLE, "changed_at": None, "history": []}
        data.setdefault("history", [])
        return data

    def flag_set(self) -> bool:
        return self.flag_path is not None and self.flag_path.exists()

    def state(self) -> dict:
        data = self._read()
        if not data["on"] and self.flag_set():
            return {"on": True, "reason": FLAG_FOUND, "changed_at": None}
        return {"on": data["on"], "reason": data.get("reason"), "changed_at": data.get("changed_at")}

    @property
    def on(self) -> bool:
        return self.state()["on"]

    def history(self) -> list[dict]:
        return list(self._read()["history"])

    def sync_flag(self) -> bool:
        # Only writes the flag. Removing it is left to turn_off (after YES), so a flag that the Guardian or a person
        # sets while this runs can never be deleted by mistake.
        if self.flag_path is None:
            return False
        state = self.state()
        if state["on"]:
            write_text(self.flag_path, f"Kill switch ON since {state['changed_at'] or 'unknown'}: {state['reason'] or 'no reason given'}\n")
        return self.flag_set()

    def _write(self, on: bool, reason: str | None, now=None) -> dict:
        data = self._read()
        when = _now(now)
        history = data["history"] + [{"time": when, "on": on, "reason": reason}]
        write_json(self.path, {"on": on, "reason": reason, "changed_at": when, "history": history[-200:]})
        if not on and self.flag_path is not None:
            self.flag_path.unlink(missing_ok=True)
        self.sync_flag()
        return self.state()

    def turn_on(self, reason: str | None = None, now=None) -> dict:
        return self._write(True, reason or "Turned on by hand.", now)

    def turn_off(self, confirm: str | None, now=None) -> dict:
        if not confirmed(confirm):
            raise KillSwitchError("Turning the kill switch off needs your confirmation: type YES.")
        return self._write(False, None, now)


def enforce_loss_stops(switch: KillSwitch, book, limits, now=None) -> list[tuple[str, str]]:
    hits = []
    if book.drawdown_pct >= limits.overall_kill_pct:
        hits.append(("overall_kill", f"Overall kill: equity is {book.drawdown_pct:.1f}% below its peak (limit {limits.overall_kill_pct:g}%). "
                                     "Flatten everything; locked until your YES."))
    if book.weekly_loss_pct >= limits.weekly_stop_pct:
        hits.append(("weekly_stop", f"Weekly stop: {book.weekly_loss_pct:.1f}% lost this week (limit {limits.weekly_stop_pct:g}%). "
                                    "Flatten everything; locked until your YES."))
    if hits and not switch.on:
        switch.turn_on(hits[0][1], now)
    if book.daily_loss_pct >= limits.daily_stop_pct:
        hits.append(("daily_stop", f"Daily stop: {book.daily_loss_pct:.1f}% lost today (limit {limits.daily_stop_pct:g}%). "
                                   "Flatten everything; no entries until the daily reset."))
    return hits
