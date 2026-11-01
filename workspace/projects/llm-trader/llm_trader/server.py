from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from llm_trader import bridge, pipeline
from llm_trader.config import Paths, SettingsError, canonical_json, default_paths, load_settings, plan_hashes, sha256_text
from llm_trader.models import iso
from llm_trader.risk.approvals import ApprovalError, Approvals, UnknownChange
from llm_trader.risk.killswitch import KillSwitch, KillSwitchError

UI_DIR = Path(__file__).resolve().parent / "ui"
LOCAL_HOSTS = ["127.0.0.1", "localhost", "::1", "[::1]"]
EVALUATION_SECTIONS = ("data", "windows", "gate", "evaluation", "costs")


class KillSwitchRequest(BaseModel):
    on: bool
    confirm: str | None = None


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    confirm: str | None = None


class Desk:
    def __init__(self, paths: Paths, execute=pipeline.execute):
        self.paths = paths
        self.execute = execute
        self.lock = threading.Lock()
        self.memo: tuple | None = None

    def _source_and_llm(self) -> tuple:
        last = pipeline.last_run(self.paths)
        return last.get("data"), bool(last.get("use_llm"))

    def _key(self, source) -> str:
        settings = load_settings(self.paths)
        inputs = {"source": str(source), "settings": {k: settings.get(k) for k in EVALUATION_SECTIONS}, "plans": plan_hashes(self.paths.plans_dir)}
        return sha256_text(canonical_json(inputs))

    def _run(self, reuse: bool) -> dict:
        source, use_llm = self._source_and_llm()
        key = self._key(source)
        kwargs = {}
        if reuse and self.memo and self.memo[0] == key:
            kwargs = {"dataset": self.memo[1], "evaluations": self.memo[2]}
        try:
            result = self.execute(source, use_llm, self.paths, **kwargs)
        except (SettingsError, OSError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=500, detail=f"The run failed: {exc}") from None
        self.memo = (self._key(result.source), result.dataset, result.evaluations)
        return result.state

    def state(self) -> dict:
        with self.lock:
            if self.paths.state_file.exists():
                try:
                    return json.loads(self.paths.state_file.read_text(encoding="utf-8"))
                except ValueError:
                    pass
            return self._run(reuse=False)

    def run(self) -> dict:
        with self.lock:
            return self._run(reuse=False)

    def kill_switch(self, request: KillSwitchRequest) -> dict:
        with self.lock:
            switch = KillSwitch(self.paths.killswitch_file)
            if request.on:
                switch.turn_on("Turned on from the dashboard.")
                mode = "demo" if self._source_and_llm()[0] in (None, "demo") else "mt5"
                bridge.clear(self.paths.bridge_file, iso(datetime.now(timezone.utc)), mode, bridge.KILL_NOTE)
            else:
                try:
                    switch.turn_off(request.confirm)
                except KillSwitchError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from None
            return self._run(reuse=True)

    def decide(self, change_id: str, request: DecisionRequest) -> dict:
        with self.lock:
            approvals = Approvals(self.paths)
            try:
                if request.decision == "approve":
                    approvals.approve(change_id, request.confirm)
                else:
                    approvals.reject(change_id)
            except UnknownChange as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from None
            except ApprovalError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from None
            return self._run(reuse=True)


def create_app(paths: Paths | None = None, extra_hosts: list[str] | None = None, execute=pipeline.execute) -> FastAPI:
    desk = Desk(paths or default_paths(), execute)
    app = FastAPI(title="Superagentic", docs_url=None, redoc_url=None, openapi_url=None)
    # Only local host names are accepted, so a web page using DNS rebinding cannot reach this desk.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS + list(extra_hosts or []))
    app.state.desk = desk

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(UI_DIR / "index.html", media_type="text/html")

    @app.get("/app.css", include_in_schema=False)
    def css() -> FileResponse:
        return FileResponse(UI_DIR / "app.css", media_type="text/css")

    @app.get("/app.js", include_in_schema=False)
    def js() -> FileResponse:
        return FileResponse(UI_DIR / "app.js", media_type="text/javascript")

    app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")

    @app.get("/api/state")
    def get_state() -> dict:
        return desk.state()

    @app.post("/api/run")
    def post_run() -> dict:
        return desk.run()

    @app.post("/api/killswitch")
    def post_killswitch(request: KillSwitchRequest) -> dict:
        return desk.kill_switch(request)

    @app.post("/api/approvals/{change_id}")
    def post_decision(change_id: str, request: DecisionRequest) -> dict:
        return desk.decide(change_id, request)

    return app
