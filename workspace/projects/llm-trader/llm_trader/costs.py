from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import numpy as np
import pandas as pd

from llm_trader.data.symbols import SymbolSpec

SPREAD_SOURCES = ("bar", "typical")


@dataclass(frozen=True)
class CostModel:
    spread_source: str = "bar"
    spread_multiplier: float = 1.0
    slippage_multiplier: float = 1.0
    commission_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.spread_source not in SPREAD_SOURCES:
            raise ValueError(f"spread_source must be one of {SPREAD_SOURCES}")

    def spread_price(self, df: pd.DataFrame, spec: SymbolSpec) -> np.ndarray:
        typical = float(spec.typical_spread_points)
        if self.spread_source == "bar" and "spread" in df.columns:
            points = df["spread"].to_numpy(dtype=float)
            points = np.where(np.isfinite(points), points, typical)
        else:
            points = np.full(len(df), typical)
        return points * spec.point * self.spread_multiplier

    def slippage_price(self, spec: SymbolSpec) -> float:
        return float(spec.slippage_points) * spec.point * self.slippage_multiplier

    def commission_price(self, spec: SymbolSpec) -> float:
        # Round-turn commission per lot expressed as a price move for one lot.
        return float(spec.commission_per_lot) * self.commission_multiplier / spec.money_per_price_unit()

    def scaled(self, factor: float) -> "CostModel":
        return replace(
            self,
            spread_multiplier=self.spread_multiplier * factor,
            slippage_multiplier=self.slippage_multiplier * factor,
            commission_multiplier=self.commission_multiplier * factor,
        )

    def describe(self) -> dict:
        return asdict(self)


def cost_model_from_settings(settings: dict | None) -> CostModel:
    cfg = (settings or {}).get("costs") or {}
    return CostModel(
        spread_source=cfg.get("spread_source", "bar"),
        spread_multiplier=float(cfg.get("spread_multiplier", 1.0)),
        slippage_multiplier=float(cfg.get("slippage_multiplier", 1.0)),
        commission_multiplier=float(cfg.get("commission_multiplier", 1.0)),
    )
