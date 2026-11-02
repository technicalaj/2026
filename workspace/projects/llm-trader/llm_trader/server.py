from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from llm_trader import bridge, pipeline
from llm_trader.config import Paths, SettingsError, canonical_json, default_paths, load_settings, plan_hashes, sha256_text
from llm_trader.risk.approvals import ApprovalError, Approvals, UnknownChange
from llm_trader.risk.killswitch import KillSwitch, KillSwitchError

UI_DIR = Path(__file__).resolve().parent / "ui"
LOCAL_HOSTS = ["127.0.0.1", "localhost", "::1", "[::1]"]
# Everything the evaluations depend on; locked plans also hash the risk section.
EVALUATION_SECTIONS = ("data", "windows", "gate", "evaluation", "costs", "risk")
ACTION_HEADER = "x-superagentic"
SAME_SITE = ("same-origin", "none")
NOT_FROM_DASHBOARD = "Refused: this request did not come from the dashboard page on this computer."
RUN_ERRORS = (SettingsError, OSError, ValueError, KeyError)


class RunFailed(Exception):
    pass


def dashboard_only(request: Request) -> None:
    # Any web page can make a browser send a POST to 127.0.0.1. A same-origin Origin, Sec-Fetch-Site and a custom
    # header (which forces a CORS preflight this server never answers) together prove the dashboard sent it.
    origin = request.headers.get("origin")
    if origin is not None and origin != f"http://{request.headers.get('host', '')}":
        raise HTTPException(status_code=403, detail=NOT_FROM_DASHBOARD)
    if request.headers.get("sec-fetch-site", "same-origin") not in SAME_SITE:
        raise HTTPException(status_code=403, detail=NOT_FROM_DASHBOARD)
    if request.headers.get(ACTION_HEADER) != "1":
        raise HTTPException(status_code=403, detail=NOT_FROM_DASHBOARD)


def json_only(request: Request) -> None:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Send the request as JSON (Content-Type: application/json).")


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
        try:
            key = self._key(source)
            kwargs = {}
            if reuse and self.memo and self.memo[0] == key:
                kwargs = {"dataset": self.memo[1], "evaluations": self.memo[2]}
            result = self.execute(source, use_llm, self.paths, **kwargs)
            self.memo = (self._key(result.source), result.dataset, result.evaluations)
        except RUN_ERRORS as exc:
            raise RunFailed(str(exc)) from None
        return result.state

    def _run_or_500(self, reuse: bool) -> dict:
        try:
            return self._run(reuse)
        except RunFailed as exc:
            raise HTTPException(status_code=500, detail=f"The run failed: {exc}") from None

    def _saved_state(self) -> dict | None:
        try:
            data = json.loads(self.paths.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and isinstance(data.get("meta"), dict) else None

    def _after_change(self, done: str) -> dict:
        # The change already took effect; a failed refresh must not make it look as if it did not.
        try:
            return self._run(reuse=True)
        except RunFailed as exc:
            kill = KillSwitch.at(self.paths).state()
            warning = f"{done}, but the dashboard could not refresh: {exc}"
            saved = self._saved_state()
            if saved is None:
                return {"refresh_error": warning, "kill_switch": kill}
            return {**saved, "meta": {**saved["meta"], "kill_switch": kill}, "refresh_error": warning, "kill_switch": kill}

    def state(self) -> dict:
        with self.lock:
            return self._saved_state() or self._run_or_500(reuse=False)

    def run(self) -> dict:
        with self.lock:
            return self._run_or_500(reuse=False)

    def kill_switch(self, request: KillSwitchRequest) -> dict:
        with self.lock:
            switch = KillSwitch.at(self.paths)
            if request.on:
                switch.turn_on("Turned on from the dashboard.")
                bridge.write(self.paths.bridge_dir, bridge.payload(datetime.now(timezone.utc), kill=True))
            else:
                try:
                    switch.turn_off(request.confirm)
                except KillSwitchError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from None
            return self._after_change(f"Kill switch is {'ON' if request.on else 'OFF'}")

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
            return self._after_change(f"Change {change_id} {'approved' if request.decision == 'approve' else 'rejected'}")


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

    @app.post("/api/run", dependencies=[Depends(dashboard_only)])
    def post_run() -> dict:
        return desk.run()

    @app.post("/api/killswitch", dependencies=[Depends(dashboard_only), Depends(json_only)])
    def post_killswitch(request: KillSwitchRequest) -> dict:
        return desk.kill_switch(request)

    @app.post("/api/approvals/{change_id}", dependencies=[Depends(dashboard_only), Depends(json_only)])
    def post_decision(change_id: str, request: DecisionRequest) -> dict:
        return desk.decide(change_id, request)

    return app
