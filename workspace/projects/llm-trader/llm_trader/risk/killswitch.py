from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from llm_trader.config import CONFIRM_WORD, write_json
from llm_trader.models import iso

UNREADABLE = "The kill switch file could not be read, so it is treated as ON until it is turned off with YES."


class KillSwitchError(ValueError):
    pass


def _now(now=None) -> str:
    return iso(now if now is not None else datetime.now(timezone.utc))


def confirmed(confirm) -> bool:
    return isinstance(confirm, str) and confirm.strip() == CONFIRM_WORD


class KillSwitch:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _read(self) -> dict:
        if not self.path.exists():
            return {"on": False, "reason": None, "changed_at": None, "history": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("on"), bool):
                raise ValueError
        except (ValueError, OSError):
            # Fail safe: a damaged switch must stop everything rather than let signals out.
            return {"on": True, "reason": UNREADABLE, "changed_at": None, "history": []}
        data.setdefault("history", [])
        return data

    def state(self) -> dict:
        data = self._read()
        return {"on": data["on"], "reason": data.get("reason"), "changed_at": data.get("changed_at")}

    @property
    def on(self) -> bool:
        return self.state()["on"]

    def history(self) -> list[dict]:
        return list(self._read()["history"])

    def _write(self, on: bool, reason: str | None, now=None) -> dict:
        data = self._read()
        when = _now(now)
        history = data["history"] + [{"time": when, "on": on, "reason": reason}]
        write_json(self.path, {"on": on, "reason": reason, "changed_at": when, "history": history[-200:]})
        return self.state()

    def turn_on(self, reason: str | None = None, now=None) -> dict:
        return self._write(True, reason or "Turned on by hand.", now)

    def turn_off(self, confirm: str | None, now=None) -> dict:
        if not confirmed(confirm):
            raise KillSwitchError("Turning the kill switch off needs your confirmation: type YES.")
        return self._write(False, None, now)


def enforce_daily_loss(switch: KillSwitch, daily_loss_pct: float, limit_pct: float, now=None) -> bool:
    if daily_loss_pct < limit_pct:
        return False
    if not switch.on:
        switch.turn_on(f"Daily loss limit reached: {daily_loss_pct:.1f}% lost today (limit {limit_pct:g}%). Everything stops for the day.", now)
    return True
