from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from llm_trader.eval.plans import canonical_json, plan_hash

ROOT = Path(__file__).resolve().parents[1]
# Facts about the account and plumbing, not trading rules: changing them needs no YES.
UNTRACKED_SECTIONS = ("account", "llm", "server")
# Every locked test plan embeds these sections, so changing them blocks every rule until it is re-locked.
PLAN_SECTIONS = ("windows", "gate", "evaluation", "costs")
CONFIRM_WORD = "YES"


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def settings(self) -> Path:
        return self.root / "config" / "settings.json"

    @property
    def settings_local(self) -> Path:
        return self.root / "config" / "settings.local.json"

    @property
    def plans_dir(self) -> Path:
        return self.root / "config" / "plans"

    @property
    def approved(self) -> Path:
        return self.root / "config" / "approved.json"

    @property
    def out_dir(self) -> Path:
        return self.root / "out"

    @property
    def state_file(self) -> Path:
        return self.out_dir / "state.json"

    @property
    def report_file(self) -> Path:
        return self.out_dir / "report.md"

    @property
    def bridge_file(self) -> Path:
        return self.out_dir / "bridge" / "signals.json"

    @property
    def killswitch_file(self) -> Path:
        return self.out_dir / "killswitch.json"

    @property
    def approvals_file(self) -> Path:
        return self.out_dir / "approvals.json"

    @property
    def last_run_file(self) -> Path:
        return self.out_dir / "last_run.json"

    @property
    def dashboard_file(self) -> Path:
        return self.out_dir / "dashboard.html"

    @property
    def env_file(self) -> Path:
        return self.root / ".env"

    def rel(self, path: Path) -> str:
        try:
            return Path(path).resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return Path(path).name


def default_paths() -> Paths:
    return Paths(ROOT)


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class DataSettings(_Open):
    mode: Literal["demo", "mt5"] = "demo"
    demo_seed: int = 7
    mt5_dir: str = "data/mt5"
    timeframe: str = "M15"


class WindowSettings(_Open):
    holdout_months: int = Field(6, ge=1)
    recent_months: int = Field(3, ge=1)


class GateSettings(_Open):
    accuracy_bar: float = Field(0.8, gt=0, le=1)
    min_trades_holdout: int = Field(30, ge=1)
    min_trades_recent: int = Field(10, ge=1)
    max_p_value: float = Field(0.05, gt=0, le=1)
    max_p_value_recent: float = Field(0.1, gt=0, le=1)
    require_positive_expectancy: bool = True


class AccountSettings(_Open):
    balance: float = Field(1000.0, gt=0)
    currency: str = "USD"
    leverage: float = Field(30, gt=0)


class RiskSettings(_Open):
    risk_per_trade_pct: float = Field(1.0, gt=0, le=100)
    max_open_risk_pct: float = Field(2.0, gt=0, le=100)
    max_daily_loss_pct: float = Field(3.0, gt=0, le=100)
    max_margin_use_pct: float = Field(50.0, gt=0, le=100)
    max_positions_per_group: int = Field(1, ge=1)
    high_correlation: float = Field(0.6, gt=0, le=1)
    correlation_days: int = Field(90, ge=7)
    forward_min_trades: int = Field(30, ge=1)
    forward_max_trades: int = Field(40, ge=1)


class CorrelationGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    members: dict[str, Literal[-1, 1]]


class LlmSettings(_Open):
    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    max_tokens: int = Field(16000, ge=1024, le=128000)


class ServerSettings(_Open):
    host: str = "127.0.0.1"
    port: int = Field(8765, ge=1, le=65535)


class SettingsFile(_Open):
    data: DataSettings = Field(default_factory=DataSettings)
    windows: WindowSettings = Field(default_factory=WindowSettings)
    gate: GateSettings = Field(default_factory=GateSettings)
    evaluation: dict = Field(default_factory=dict)
    costs: dict = Field(default_factory=dict)
    account: AccountSettings = Field(default_factory=AccountSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    correlation_groups: list[CorrelationGroup] = Field(default_factory=list)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)


def _validation_message(source: str, exc: ValidationError) -> str:
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"{source}: {where}: {first['msg']}"


def read_json(path: Path, label: str | None = None) -> dict:
    label = label or Path(path).name
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SettingsError(f"{label} is missing") from None
    except json.JSONDecodeError as exc:
        raise SettingsError(f"{label} is not valid JSON (line {exc.lineno}: {exc.msg})") from None
    if not isinstance(data, dict):
        raise SettingsError(f"{label} must contain a JSON object")
    return data


def read_local_override(paths: Paths) -> tuple[dict | None, list[str]]:
    if not paths.settings_local.exists():
        return None, []
    local = read_json(paths.settings_local, "config/settings.local.json")
    ignored = sorted(k for k in local if k != "account")
    return local.get("account"), ignored


def load_settings(paths: Paths | None = None) -> dict:
    paths = paths or default_paths()
    settings = read_json(paths.settings, "config/settings.json")
    account, _ = read_local_override(paths)
    if account is not None:
        if not isinstance(account, dict):
            raise SettingsError("config/settings.local.json: account must be an object")
        settings["account"] = {**(settings.get("account") or {}), **account}
    validate_settings(settings)
    return settings


def validate_settings(settings: dict, source: str = "settings") -> SettingsFile:
    try:
        return SettingsFile.model_validate(settings)
    except ValidationError as exc:
        raise SettingsError(_validation_message(source, exc)) from None


def section(settings: dict, name: str):
    return getattr(SettingsFile.model_validate(settings), name)


def tracked_settings(settings: dict) -> dict:
    return {k: v for k, v in settings.items() if k not in UNTRACKED_SECTIONS}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def settings_hash(settings: dict) -> str:
    return sha256_text(canonical_json(tracked_settings(settings)))


def plan_file_hash(path: Path) -> str:
    raw = Path(path).read_bytes()
    try:
        return plan_hash(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return "unreadable-" + hashlib.sha256(raw).hexdigest()


def plan_hashes(plans_dir: Path) -> dict[str, str]:
    return {p.stem: plan_file_hash(p) for p in sorted(Path(plans_dir).glob("*.json"))}


def _replace(tmp: str, path: Path) -> None:
    # Windows refuses to replace a file another process (an EA, an editor) has open for a moment.
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.1)


def write_text(path: Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.chmod(tmp, mode)
        _replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def write_json(path: Path, data) -> Path:
    return write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def load_dotenv(path: Path) -> list[str]:
    path = Path(path)
    if not path.exists():
        return []
    loaded = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
