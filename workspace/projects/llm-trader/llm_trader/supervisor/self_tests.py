from __future__ import annotations

import ast
import io
import os
import re
import tokenize
from pathlib import Path

from llm_trader.agents.context import split_answers

# Spelled so that this scanner never matches its own source.
ORDER_NAMES = re.compile(r"order[_]send|Order[S]end|create[_]order")
MT5_MODULE = "MetaTrader" "5"
SKIP_ANYWHERE = {"__pycache__", "node_modules", "venv"}
SKIP_AT_ROOT = {"data", "out", "local", "logs"}


def python_files(root: Path) -> list[Path]:
    root = Path(root)
    found = []
    for folder, dirs, files in os.walk(root):
        at_root = Path(folder) == root
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_ANYWHERE and not (at_root and d in SKIP_AT_ROOT))
        found += [Path(folder) / name for name in files if name.endswith(".py")]
    return sorted(found)


def identifiers(text: str) -> list[str]:
    try:
        return [tok.string for tok in tokenize.generate_tokens(io.StringIO(text).readline) if tok.type == tokenize.NAME]
    except (tokenize.TokenError, SyntaxError):
        return re.findall(r"[A-Za-z_]\w*", text)


def imports_mt5(text: str) -> bool:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return MT5_MODULE in text
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(alias.name.split(".")[0] == MT5_MODULE for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == MT5_MODULE:
            return True
    return False


def order_code_findings(root: Path) -> list[str]:
    findings = []
    for path in python_files(root):
        rel = path.relative_to(root)
        text = path.read_text(encoding="utf-8", errors="replace")
        # Tests hold these names as strings for their own guards; there only real identifiers count.
        hits = [t for t in identifiers(text) if ORDER_NAMES.fullmatch(t)] if rel.parts[0] == "tests" else ORDER_NAMES.findall(text)
        if hits:
            findings.append(f"{rel.as_posix()}: {hits[0]}")
        if rel.parts[0] != "tools" and imports_mt5(text):
            findings.append(f"{rel.as_posix()}: imports the MT5 package")
    return findings


def _entry(id_: str, name: str, expected: str, actual: str, ok: bool | None, detail: str) -> dict:
    return {"id": id_, "name": name, "expected": expected, "actual": actual, "ok": ok, "detail": detail}


def rule_self_tests(research: list[dict], available: set[str]) -> list[dict]:
    out = []
    for r in research:
        if not r["self_test"]:
            continue
        base = r["name"].removeprefix("Self-test: ")
        name = f"{base[:1].upper()}{base[1:]}: {r['expected']}"
        missing = [s for s in r["symbols"] if s not in available]
        if missing:
            out.append(_entry(r["rule_id"], name, r["expected"], "not run", None,
                              f"No data for {', '.join(missing)}, so this self-test could not run. Export those symbols to run it."))
            continue
        reason = r["gate"]["reasons"][0] if r["gate"]["reasons"] else r["stage_note"]
        out.append(_entry(r["rule_id"], name, r["expected"], r["gate"]["status"], bool(r["self_test_ok"]), reason))
    return out


def no_edge_test(research: list[dict], data_mode: str) -> dict:
    name = "Real-named symbols (no edge) qualify nothing"
    if data_mode != "demo":
        return _entry("no_edge_symbols", name, "nothing qualifies", "not run on broker data", None,
                      "Real broker prices may hold an edge, so this check runs only on the synthetic demo data, where the "
                      "real-named symbols have no pattern by construction.")
    candidates = [r for r in research if not r["control"]]
    qualified = [r["name"] for r in candidates if r["gate"]["status"] == "qualified"]
    detail = ("No agent passed on prices that hold no pattern, as it should be."
              if not qualified else f"{', '.join(qualified)} qualified on prices with no pattern: the gate is too loose.")
    return _entry("no_edge_symbols", name, "nothing qualifies", f"{len(qualified)} of {len(candidates)} agents qualified",
                  not qualified, detail)


def order_code_test(root: Path) -> dict:
    name, files = "No order-placing code in the project", len(python_files(root))
    if not files:
        return _entry("no_order_code", name, "none found", "not run", None, "No Python files were found to scan, so this proves nothing.")
    findings = order_code_findings(root)
    detail = (f"Scanned {files} Python files: no order calls, and the MT5 package is imported only by the read-only exporter in tools/."
              if not findings else "Found: " + "; ".join(findings[:5]))
    return _entry("no_order_code", name, "none found", "none found" if not findings else f"found in {len(findings)} place{'' if len(findings) == 1 else 's'}", not findings, detail)


def tagger_test(tagger: dict) -> dict:
    split = split_answers(tagger)
    split_paused = [row["symbol"] for row in tagger["last"] if len(set(row["verdicts"])) > 1 and row["pause"]]
    ok = split > 0 and not split_paused
    detail = (f"{len(tagger['last'])} questions, {tagger['samples']} seeded mock samples each. A split means no opinion, so no pause. "
              "This tests the plumbing, not accuracy.")
    return _entry("event_tagger_disagrees", "Event tagger mock disagrees sometimes (self-test, not accuracy)",
                  "some split answers, never a pause from a split", f"{split} of {len(tagger['last'])} questions split", ok, detail)


def build_self_tests(research: list[dict], tagger: dict, root: Path, data_mode: str, available: set[str]) -> list[dict]:
    return [*rule_self_tests(research, available), no_edge_test(research, data_mode), order_code_test(root), tagger_test(tagger)]
