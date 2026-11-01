import copy
import functools
import json
import re
import shutil

import pytest
from conftest import ROOT
from fastapi.testclient import TestClient

from llm_trader import cli, pipeline
from llm_trader.config import Paths
from llm_trader.risk.killswitch import KillSwitch
from llm_trader.server import create_app
from llm_trader.snapshot import build_snapshot, embed_json, write_snapshot

HOSTILE = "</script><script>alert('x')</script><!--"


@pytest.fixture
def project(tmp_path):
    shutil.copytree(ROOT / "config", tmp_path / "config", ignore=shutil.ignore_patterns("settings.local.json"))
    return Paths(tmp_path)


@pytest.fixture
def client(project, demo, evaluations):
    fast = functools.partial(pipeline.execute, dataset=demo, evaluations=list(evaluations.values()))
    with TestClient(create_app(project, execute=fast), base_url="http://127.0.0.1") as test_client:
        yield test_client


def edit_risk(project: Paths, value: float) -> None:
    settings = json.loads(project.settings.read_text())
    settings["risk"]["risk_per_trade_pct"] = value
    project.settings.write_text(json.dumps(settings, indent=2))


def test_serves_the_dashboard_files(client):
    page = client.get("/")
    assert page.status_code == 200 and "Superagentic" in page.text and page.headers["content-type"].startswith("text/html")
    assert client.get("/ui/app.js").status_code == 200
    assert client.get("/app.js").status_code == 200 and client.get("/app.css").status_code == 200


def test_state_runs_the_pipeline_once_when_missing(client, project):
    assert not project.state_file.exists()
    state = client.get("/api/state").json()
    assert state["meta"]["app"] == "Superagentic" and project.state_file.exists()
    project.state_file.write_text(json.dumps({"meta": {"app": "Superagentic", "marker": 1}}))
    assert client.get("/api/state").json() == {"meta": {"app": "Superagentic", "marker": 1}}


def test_run_returns_a_fresh_state(client):
    state = client.post("/api/run").json()
    assert [r["gate"]["status"] for r in state["research"]] == ["qualified", "failed", "failed", "insufficient", "failed", "blocked"]


def test_kill_switch_on_needs_no_yes_and_clears_the_bridge(client, project):
    client.post("/api/run")
    response = client.post("/api/killswitch", json={"on": True, "confirm": None})
    assert response.status_code == 200
    assert response.json()["meta"]["kill_switch"]["on"] is True
    assert json.loads(project.bridge_file.read_text())["kill_switch"] is True


@pytest.mark.parametrize("confirm", [None, "yes", "Y"])
def test_kill_switch_off_needs_yes(client, project, confirm):
    KillSwitch(project.killswitch_file).turn_on("test")
    response = client.post("/api/killswitch", json={"on": False, "confirm": confirm})
    assert response.status_code == 400
    assert response.json() == {"detail": "Turning the kill switch off needs your confirmation: type YES."}
    assert KillSwitch(project.killswitch_file).on


def test_kill_switch_off_with_yes(client, project):
    KillSwitch(project.killswitch_file).turn_on("test")
    response = client.post("/api/killswitch", json={"on": False, "confirm": "YES"})
    assert response.status_code == 200 and response.json()["meta"]["kill_switch"]["on"] is False


def test_approving_a_change_needs_yes(client, project):
    edit_risk(project, 1.5)
    [item] = client.post("/api/run").json()["approvals"]["pending"]
    refused = client.post(f"/api/approvals/{item['id']}", json={"decision": "approve", "confirm": None})
    assert refused.status_code == 400 and "type YES" in refused.json()["detail"]
    assert client.post("/api/approvals/chg-999", json={"decision": "approve", "confirm": "YES"}).status_code == 404
    state = client.post(f"/api/approvals/{item['id']}", json={"decision": "approve", "confirm": "YES"}).json()
    assert state["meta"]["safe_mode"]["on"] is False and state["approvals"]["pending"] == []
    assert state["approvals"]["history"][0]["decision"] == "approved"


def test_rejecting_a_change_puts_settings_back(client, project):
    edit_risk(project, 4.0)
    [item] = client.post("/api/run").json()["approvals"]["pending"]
    state = client.post(f"/api/approvals/{item['id']}", json={"decision": "reject", "confirm": None}).json()
    assert state["meta"]["safe_mode"]["on"] is False
    assert json.loads(project.settings.read_text())["risk"]["risk_per_trade_pct"] == 1.0


def test_no_endpoint_can_trade_and_cors_stays_closed(client):
    paths = {route.path for route in client.app.routes}
    assert paths == {"/", "/app.css", "/app.js", "/ui", "/api/state", "/api/run", "/api/killswitch", "/api/approvals/{change_id}"}
    assert not any(word in p for p in paths for word in ("order", "trade", "buy", "sell"))
    preflight = client.options("/api/killswitch", headers={"Origin": "https://example.com", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in preflight.headers
    assert client.get("/docs").status_code == 404


def test_other_host_names_are_refused(project):
    with TestClient(create_app(project), base_url="http://evil.example") as other:
        assert other.get("/api/state").status_code == 400


def test_serve_binds_to_this_computer_by_default(project, monkeypatch, capsys):
    import uvicorn

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port, log_level: seen.update(host=host, port=port))
    assert cli.main(["serve"], project) == 0
    assert seen == {"host": "127.0.0.1", "port": 8765}
    assert "http://127.0.0.1:8765" in capsys.readouterr().out
    cli.main(["serve", "--host", "0.0.0.0", "--port", "8764"], project)
    assert seen == {"host": "0.0.0.0", "port": 8764} and "Never expose it to the internet" in capsys.readouterr().err


def test_snapshot_inlines_the_ui_and_cannot_be_broken_by_state_text(project, demo, evaluations):
    state = pipeline.run("demo", paths=project, dataset=demo, evaluations=list(evaluations.values()))
    hostile = copy.deepcopy(state)
    hostile["checks"][0]["detail"] = HOSTILE
    html = build_snapshot(hostile)
    assert 'href="app.css"' not in html and 'src="app.js"' not in html
    assert ":root" in html and "window.__SUPERAGENTIC_UI__ = true" in html
    assert HOSTILE not in html and "alert('x')" in html
    assert len(re.findall(r"</script>", html, flags=re.IGNORECASE)) == len(re.findall(r"<script\b", html, flags=re.IGNORECASE))
    embedded = re.search(r"window\.__STATE__ = (\{.*?\});</script>", html, flags=re.DOTALL).group(1)
    assert json.loads(embedded) == hostile


def test_embed_json_escapes_markup_characters():
    text = embed_json({"a": "</script>&<!-- "})
    assert "<" not in text and ">" not in text and "&" not in text and " " not in text
    assert json.loads(text) == {"a": "</script>&<!-- "}


def test_write_snapshot_uses_the_saved_state(project, demo, evaluations):
    pipeline.run("demo", paths=project, dataset=demo, evaluations=list(evaluations.values()))
    target = write_snapshot(project)
    assert target == project.dashboard_file and "window.__STATE__" in target.read_text(encoding="utf-8")
    other = write_snapshot(project, out=project.root / "copy.html")
    assert other.exists()
