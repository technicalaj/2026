import ast
import io
import os
import re
import tokenize
from pathlib import Path

from conftest import ROOT

from llm_trader.supervisor.self_tests import order_code_findings, order_code_test, python_files

# Spelled so that this file never matches its own scan.
ORDER = re.compile(r"order[_]send|Order[S]end|create[_]order")
MT5 = "MetaTrader" "5"


def project_files() -> list[Path]:
    found = []
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        found += [Path(folder) / name for name in files if name.endswith(".py")]
    return found


def names_in(text: str) -> set[str]:
    return {tok.string for tok in tokenize.generate_tokens(io.StringIO(text).readline) if tok.type == tokenize.NAME}


def mt5_imported(text: str) -> bool:
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == MT5 for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == MT5:
            return True
    return False


def test_no_order_placing_code_anywhere_in_the_project():
    files = project_files()
    assert len(files) > 40 and not any(".venv" in p.parts for p in files)
    for path in files:
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        if rel.parts[0] == "tests":
            # Tests may name these calls in strings (their own guards); they must never call or define them.
            assert not {n for n in names_in(text) if ORDER.fullmatch(n)}, rel
        else:
            assert not ORDER.search(text), rel
        if rel.parts[0] != "tools":
            assert not mt5_imported(text), f"{rel} imports the MT5 package outside tools/"


def test_the_only_mt5_import_is_the_read_only_exporter():
    importers = [p.relative_to(ROOT).as_posix() for p in project_files() if mt5_imported(p.read_text(encoding="utf-8"))]
    assert importers == ["tools/export_mt5_data.py"]


def plant(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_an_empty_scan_proves_nothing(tmp_path):
    result = order_code_test(tmp_path)
    assert result["ok"] is None and result["actual"] == "not run"


def test_the_runtime_self_test_finds_planted_order_code(tmp_path):
    plant(tmp_path, "llm_trader/clean.py", "x = 1\n")
    plant(tmp_path, "llm_trader/data/loader.py", "y = 2\n")
    plant(tmp_path, "tests/test_guard.py", 'FORBIDDEN = ("order' '_send",)\n')
    plant(tmp_path, "tools/exporter.py", f"import {MT5} as mt5\n")
    plant(tmp_path, "data/scratch.py", "mt5.order" "_send(request)\n")
    plant(tmp_path, ".venv/lib/site.py", "mt5.order" "_send(request)\n")
    assert sorted(p.relative_to(tmp_path).as_posix() for p in python_files(tmp_path)) == [
        "llm_trader/clean.py", "llm_trader/data/loader.py", "tests/test_guard.py", "tools/exporter.py"]
    assert order_code_findings(tmp_path) == []
    assert order_code_test(tmp_path)["ok"] is True

    plant(tmp_path, "llm_trader/bad.py", "def go(mt5, request):\n    return mt5.order" "_send(request)\n")
    plant(tmp_path, "llm_trader/sneaky.py", f"from {MT5} import initialize\n")
    plant(tmp_path, "tests/test_bad.py", "def create" "_order():\n    pass\n")
    assert order_code_findings(tmp_path) == [
        "llm_trader/bad.py: order" "_send", "llm_trader/sneaky.py: imports the MT5 package", "tests/test_bad.py: create" "_order"]
    result = order_code_test(tmp_path)
    assert result["ok"] is False and result["actual"] == "found in 3 places"
