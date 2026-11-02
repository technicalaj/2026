import copy
import functools
import json
import re

import pytest
from fastapi.testclient import TestClient
from project_copy import copy_project

from llm_trader import cli, pipeline
from llm_trader.config import Paths
from llm_trader.risk.killswitch import KillSwitch
from llm_trader.server import create_app
from llm_trader.snapshot import build_snapshot, embed_json, write_snapshot

HOSTILE = "</script><script>alert('x')</script><!--"
DASHBOARD = {"X-Superagentic": "1"}


@pytest.fixture
def project(tmp_path):
    return copy_project(tmp_path)


@pytest.fixture
def client(project, demo, evaluations):
    fast = functools.partial(pipeline.execute, dataset=demo, evaluations=list(evaluations.values()))
    with TestClient(create_app(project, execute=fast), base_url="http://127.0.0.1", headers=DASHBOARD) as test_client:
        yield test_client


@pytest.fixture
def bare(client):
    with TestClient(client.app, base_url="http://127.0.0.1") as other:
        yield other


def edit_context(project: Paths, samples: int) -> None:
    settings = json.loads(project.settings.read_text())
    settings["context"]["event_tagger"]["samples"] = samples
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
    assert state["bridge"]["file"] == "out/bridge/advisories.json"


def test_kill_switch_on_needs_no_yes_sets_the_flag_and_empties_the_bridge(client, project):
    client.post("/api/run")
    response = client.post("/api/killswitch", json={"on": True, "confirm": None})
    assert response.status_code == 200
    state = response.json()
    assert state["meta"]["kill_switch"]["on"] is True and state["bridge"]["kill_flag"] is True
    assert project.kill_flag.exists()
    assert json.loads(project.bridge_file.read_text())["kill"] is True


@pytest.mark.parametrize("confirm", [None, "yes", "Y"])
def test_kill_switch_off_needs_yes(client, project, confirm):
    KillSwitch.at(project).turn_on("test")
    response = client.post("/api/killswitch", json={"on": False, "confirm": confirm})
    assert response.status_code == 400
    assert response.json() == {"detail": "Turning the kill switch off needs your confirmation: type YES."}
    assert KillSwitch.at(project).on and project.kill_flag.exists()


def test_kill_switch_off_with_yes_removes_the_flag(client, project):
    KillSwitch.at(project).turn_on("test")
    response = client.post("/api/killswitch", json={"on": False, "confirm": "YES"})
    assert response.status_code == 200 and response.json()["meta"]["kill_switch"]["on"] is False
    assert not project.kill_flag.exists() and response.json()["bridge"]["kill_flag"] is False


def test_approving_a_change_needs_yes(client, project):
    edit_context(project, 5)
    [item] = client.post("/api/run").json()["approvals"]["pending"]
    refused = client.post(f"/api/approvals/{item['id']}", json={"decision": "approve", "confirm": None})
    assert refused.status_code == 400 and "type YES" in refused.json()["detail"]
    assert client.post("/api/approvals/chg-999", json={"decision": "approve", "confirm": "YES"}).status_code == 404
    state = client.post(f"/api/approvals/{item['id']}", json={"decision": "approve", "confirm": "YES"}).json()
    assert state["meta"]["safe_mode"]["on"] is False and state["approvals"]["pending"] == []
    assert state["approvals"]["history"][0]["decision"] == "approved"


def test_rejecting_a_change_puts_settings_back(client, project):
    edit_context(project, 7)
    [item] = client.post("/api/run").json()["approvals"]["pending"]
    state = client.post(f"/api/approvals/{item['id']}", json={"decision": "reject", "confirm": None}).json()
    assert state["meta"]["safe_mode"]["on"] is False
    assert json.loads(project.settings.read_text())["context"]["event_tagger"]["samples"] == 3


def test_no_endpoint_can_trade_and_cors_stays_closed(client):
    paths = {route.path for route in client.app.routes}
    assert paths == {"/", "/app.css", "/app.js", "/ui", "/api/state", "/api/run", "/api/killswitch", "/api/approvals/{change_id}"}
    assert not any(word in p for p in paths for word in ("order", "trade", "buy", "sell"))
    preflight = client.options("/api/killswitch", headers={"Origin": "https://example.com", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in preflight.headers
    assert client.get("/docs").status_code == 404


@pytest.mark.parametrize("headers", [
    {"Origin": "http://evil.example", **DASHBOARD},
    {"Origin": "http://127.0.0.1:9999", **DASHBOARD},
    {"Sec-Fetch-Site": "cross-site", **DASHBOARD},
    {},
], ids=["foreign-origin", "other-port", "cross-site", "no-dashboard-header"])
def test_actions_from_other_pages_are_refused(bare, project, headers):
    KillSwitch.at(project).turn_on("test")
    approved = project.approved.read_text()
    for path, body in (("/api/run", None), ("/api/killswitch", {"on": False, "confirm": "YES"}),
                       ("/api/approvals/chg-001", {"decision": "approve", "confirm": "YES"})):
        response = bare.post(path, json=body, headers=headers)
        assert response.status_code == 403, path
    assert not project.state_file.exists() and KillSwitch.at(project).on and project.approved.read_text() == approved


def test_a_cross_site_form_post_cannot_run_the_pipeline(bare, project):
    response = bare.post("/api/run", data={"x": "1"}, headers={"Origin": "http://evil.example", "Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403 and not project.last_run_file.exists()


@pytest.mark.parametrize("content_type", [None, "text/plain"])
def test_bodies_must_be_json(client, project, content_type):
    KillSwitch.at(project).turn_on("test")
    headers = {**DASHBOARD, **({"Content-Type": content_type} if content_type else {})}
    response = client.post("/api/killswitch", content=b'{"on": false, "confirm": "YES"}', headers=headers)
    assert 400 <= response.status_code < 500
    assert KillSwitch.at(project).on


def test_the_page_itself_may_act(client):
    response = client.post("/api/run", headers={"Origin": "http://127.0.0.1", "Sec-Fetch-Site": "same-origin"})
    assert response.status_code == 200


def test_a_change_that_worked_is_reported_even_if_the_refresh_fails(client, project):
    client.post("/api/run")
    project.settings.write_text("{broken")
    on = client.post("/api/killswitch", json={"on": True, "confirm": None})
    assert on.status_code == 200 and on.json()["meta"]["kill_switch"]["on"] is True
    assert on.json()["refresh_error"].startswith("Kill switch is ON, but the dashboard could not refresh")
    assert KillSwitch.at(project).on and project.kill_flag.exists()
    off = client.post("/api/killswitch", json={"on": False, "confirm": "YES"})
    assert off.status_code == 200 and off.json()["kill_switch"]["on"] is False and "Kill switch is OFF" in off.json()["refresh_error"]
    assert not KillSwitch.at(project).on and not project.kill_flag.exists()
    assert client.post("/api/run").status_code == 500


def test_other_host_names_are_refused(project):
    with TestClient(create_app(project), base_url="http://evil.example") as other:
        assert other.get("/api/state").status_code == 400


def test_serve_binds_to_this_computer_on_port_8765_by_default(project, monkeypatch, capsys):
    import uvicorn

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port, log_level: seen.update(host=host, port=port))
    assert cli.main(["serve"], project) == 0
    assert seen == {"host": "127.0.0.1", "port": 8765}
    assert "http://127.0.0.1:8765" in capsys.readouterr().out
    seen.clear()
    assert cli.main(["serve", "--host", "0.0.0.0", "--port", "8764"], project) == 2
    assert seen == {} and "--i-know-there-is-no-login" in capsys.readouterr().err
    assert cli.main(["serve", "--host", "0.0.0.0", "--port", "8764", "--i-know-there-is-no-login"], project) == 0
    assert seen == {"host": "0.0.0.0", "port": 8764} and "Never expose it to the internet" in capsys.readouterr().err


def test_a_host_in_settings_cannot_open_the_dashboard_to_the_network(project, monkeypatch, capsys):
    import uvicorn

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port, log_level: seen.update(host=host, port=port))
    settings = json.loads(project.settings.read_text())
    settings["server"]["host"] = "0.0.0.0"
    project.settings.write_text(json.dumps(settings))
    assert cli.main(["serve"], project) == 0
    assert seen["host"] == "127.0.0.1" and "Ignoring server.host '0.0.0.0'" in capsys.readouterr().err


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


def test_a_snapshot_with_your_own_balance_says_so(project, demo, evaluations, capsys):
    project.settings_local.write_text(json.dumps({"account": {"balance": 4321.0}}))
    pipeline.run("demo", paths=project, dataset=demo, evaluations=list(evaluations.values()))
    assert cli.main(["snapshot"], project) == 0
    assert "contains your balance from config/settings.local.json" in capsys.readouterr().err


def test_embed_json_escapes_markup_characters():
    raw = "</script>&<!--  "
    text = embed_json({"a": raw})
    assert not any(ch in text for ch in "<>&  ")
    assert json.loads(text) == {"a": raw}


def test_write_snapshot_uses_the_saved_state(project, demo, evaluations):
    pipeline.run("demo", paths=project, dataset=demo, evaluations=list(evaluations.values()))
    target = write_snapshot(project)
    assert target == project.dashboard_file and "window.__STATE__" in target.read_text(encoding="utf-8")
    other = write_snapshot(project, out=project.root / "copy.html")
    assert other.exists()
