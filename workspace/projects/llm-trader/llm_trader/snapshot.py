from __future__ import annotations

import json
import re
from pathlib import Path

from llm_trader import pipeline
from llm_trader.config import Paths, default_paths, write_text

UI_DIR = Path(__file__).resolve().parent / "ui"
CSS_LINK = re.compile(r'<link\b[^>]*\bhref="app\.css"[^>]*>', re.IGNORECASE)
JS_TAG = re.compile(r'<script\b[^>]*\bsrc="app\.js"[^>]*>\s*</script>', re.IGNORECASE)
JSON_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026", " ": "\\u2028", " ": "\\u2029"}


def embed_json(state: dict) -> str:
    text = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    return re.sub("[<>&  ]", lambda m: JSON_ESCAPES[m.group()], text)


def _guard(code: str, tag: str) -> str:
    return re.sub(rf"</({tag})", r"<\\/\1", code, flags=re.IGNORECASE)


def build_snapshot(state: dict, ui_dir: Path = UI_DIR) -> str:
    html = (ui_dir / "index.html").read_text(encoding="utf-8")
    if not CSS_LINK.search(html) or not JS_TAG.search(html):
        raise ValueError("ui/index.html no longer links app.css and app.js, so the snapshot cannot inline them")
    css = _guard((ui_dir / "app.css").read_text(encoding="utf-8"), "style")
    js = _guard((ui_dir / "app.js").read_text(encoding="utf-8"), "script")
    scripts = f"<script>window.__STATE__ = {embed_json(state)};</script>\n<script>\n{js}\n</script>"
    html = CSS_LINK.sub(lambda _: f"<style>\n{css}\n</style>", html, count=1)
    return JS_TAG.sub(lambda _: scripts, html, count=1)


def write_snapshot(paths: Paths | None = None, out=None, state: dict | None = None) -> Path:
    paths = paths or default_paths()
    if state is None:
        if paths.state_file.exists():
            state = json.loads(paths.state_file.read_text(encoding="utf-8"))
        else:
            state = pipeline.run(paths=paths)
    return write_text(Path(out) if out else paths.dashboard_file, build_snapshot(state))
