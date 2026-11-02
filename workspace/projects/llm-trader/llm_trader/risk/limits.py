from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields


@dataclass(frozen=True)
class Blackouts:
    news_minutes: int = 15
    major_news_minutes: int = 30
    rollover: str = "16:45-17:15 America/New_York"
    friday_cutoff_utc: str = "20:00"
    calendar_max_age_hours: float = 24.0


@dataclass(frozen=True)
class Limits:
    risk_per_trade_pct: float = 0.5
    risk_per_trade_cap_pct: float = 1.0
    max_open_risk_pct: float = 1.5
    max_cluster_risk_pct: float = 1.0
    max_margin_use_pct: float = 30.0
    daily_stop_pct: float = 2.0
    weekly_stop_pct: float = 4.0
    overall_kill_pct: float = 6.0
    max_open_positions: int = 2
    max_entries_per_day: int = 4
    min_minutes_between_entries_per_symbol: int = 240
    spread_skip_multiple: float = 2.0
    pause_after_full_stops: int = 3
    blackouts: Blackouts = field(default_factory=Blackouts)

    @classmethod
    def from_settings(cls, risk) -> "Limits":
        data = risk.model_dump() if hasattr(risk, "model_dump") else dict(risk or {})
        own = {f.name for f in fields(cls)} - {"blackouts"}
        blackout_names = {f.name for f in fields(Blackouts)}
        blackouts = {k: v for k, v in dict(data.get("blackouts") or {}).items() if k in blackout_names}
        return cls(**{k: v for k, v in data.items() if k in own}, blackouts=Blackouts(**blackouts))

    def to_dict(self) -> dict:
        return asdict(self)
