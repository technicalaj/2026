import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm_trader.data.loader import load_dataset  # noqa: E402
from llm_trader.data.symbols import SymbolSpec  # noqa: E402
from llm_trader.eval.plans import lock_all_plans  # noqa: E402
from llm_trader.models import Signal  # noqa: E402

SETTINGS_PATH = ROOT / "config" / "settings.json"
PLANS_DIR = ROOT / "config" / "plans"
TRIALS_PATH = ROOT / "config" / "trials.json"
TRIALS_AT_START = TRIALS_PATH.read_bytes() if TRIALS_PATH.exists() else None
LOCKED_AT = "2026-11-01T22:00:00Z"
BAR = pd.Timedelta(minutes=15)


@pytest.fixture(scope="session")
def settings() -> dict:
    return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def committed_plans_dir() -> Path:
    return PLANS_DIR


@pytest.fixture(scope="session")
def plans_dir(tmp_path_factory, settings) -> Path:
    # Locked from the settings as they are now, so engine tests do not depend on when config/plans was last re-locked;
    # test_plans checks the committed plans separately.
    folder = tmp_path_factory.mktemp("plans")
    lock_all_plans(settings, folder, locked_at=LOCKED_AT)
    return folder


@pytest.fixture(scope="session")
def demo():
    return load_dataset("demo")


@pytest.fixture(scope="session")
def trials_path(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("trials") / "trials.json"


@pytest.fixture(scope="session")
def timed_evaluations(demo, settings, plans_dir, trials_path):
    from llm_trader.eval.run import evaluate_all

    started = time.perf_counter()
    evaluations = evaluate_all(demo, settings, plans_dir, trials_path=trials_path)
    return {e.rule_id: e for e in evaluations}, time.perf_counter() - started


@pytest.fixture(scope="session")
def evaluations(timed_evaluations):
    return timed_evaluations[0]


def make_spec(**overrides) -> SymbolSpec:
    base = dict(
        name="TEST", point=0.01, digits=2, contract_size=100, tick_size=0.01, tick_value=1.0, min_lot=0.01,
        lot_step=0.01, margin_per_min_lot=10.0, commission_per_lot=0.0, slippage_points=0.0,
        typical_spread_points=0.0, session="fx", demo=True,
    )
    return SymbolSpec(**{**base, **overrides})


def make_bars(rows, start="2026-03-02 08:00", spread=0.0) -> pd.DataFrame:
    rows = np.asarray(rows, dtype=float)
    index = pd.date_range(start, periods=len(rows), freq="15min", tz="UTC", name="time").as_unit("ns")
    df = pd.DataFrame(rows[:, :4], columns=["open", "high", "low", "close"], index=index)
    df["spread"] = spread
    df["volume"] = 100.0
    return df


def signal_after(df: pd.DataFrame, bar: int, side: int, stop, target, max_hold: int = 10, **meta) -> Signal:
    return Signal("test_rule", "TEST", df.index[bar] + BAR, side, stop, target, max_hold, dict(meta))
