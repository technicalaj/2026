import shutil
from pathlib import Path

from conftest import ROOT

from llm_trader.config import Paths
from llm_trader.risk.approvals import Approvals


def copy_project(root: Path, baseline: bool = True) -> Paths:
    local = shutil.ignore_patterns("settings.local.json", "approved.json", "trials.json")
    shutil.copytree(ROOT / "config", Path(root) / "config", ignore=local)
    paths = Paths(Path(root))
    if baseline:
        Approvals(paths).write_baseline(now="2026-11-01T00:00:00Z")
    return paths
