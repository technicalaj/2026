import json
import shutil
from types import SimpleNamespace

import anthropic
import httpx
import pandas as pd
import pytest
from conftest import ROOT

from llm_trader import llm, pipeline
from llm_trader.config import Paths
from llm_trader.llm import AgentNote, SupervisorReview
from llm_trader.report import build_report

NOW = pd.Timestamp("2026-11-02 04:10", tz="UTC")
REVIEW = SupervisorReview(
    summary="Only the self-test passed. That is expected on demo data.",
    agent_notes=[AgentNote(agent_id="tight_target", note="High win rate, no edge.")],
    warnings=["Demo data is never eligible for money."],
    next_steps=["Export broker data and run again."],
)


class FakeClient:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result, self.error = result, error
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self.parse))

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class Untouchable:
    def __getattr__(self, name):
        raise AssertionError("the Claude client must not be used offline")


@pytest.fixture(autouse=True)
def no_real_client(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: Untouchable())


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")


@pytest.fixture(scope="module")
def state(tmp_path_factory, demo, evaluations):
    root = tmp_path_factory.mktemp("llm")
    shutil.copytree(ROOT / "config", root / "config", ignore=shutil.ignore_patterns("settings.local.json"))
    return pipeline.run("demo", paths=Paths(root), dataset=demo, evaluations=list(evaluations.values()), now=NOW)


def answered(review=REVIEW, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=review)


def test_offline_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = llm.supervisor_review({"x": 1}, use_llm=True, client=Untouchable())
    assert (result.mode, result.note, result.review) == ("offline", llm.NO_KEY_NOTE, None)
    assert result.note == "No ANTHROPIC_API_KEY set: Supervisor review and report use built-in templates."


def test_offline_without_the_llm_flag(key):
    result = llm.supervisor_review({"x": 1}, use_llm=False, client=Untouchable())
    assert (result.mode, result.note, result.review) == ("offline", llm.NOT_ASKED_NOTE, None)


def test_the_call_matches_the_spec_exactly(key):
    client = FakeClient(answered())
    result = llm.supervisor_review({"date": "2026-11-02", "agents": []}, use_llm=True, client=client)
    assert result.mode == "claude" and result.review == REVIEW and result.note == llm.CLAUDE_NOTE
    [call] = client.calls
    assert call == {
        "model": "claude-opus-5-5", "max_tokens": 16000,
        "betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default",
        "output_config": {"effort": "medium"},
        "system": llm.STABLE_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": json.dumps({"agents": [], "date": "2026-11-02"})}],
        "output_format": SupervisorReview,
    }


def test_refusal_falls_back_to_templates(key):
    result = llm.supervisor_review({}, use_llm=True, client=FakeClient(answered(None, "refusal")))
    assert result.mode == "offline" and result.review is None and "declined" in result.note


@pytest.mark.parametrize("error", [
    anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
    anthropic.RateLimitError("slow down", response=httpx.Response(429, request=httpx.Request("POST", "https://api.anthropic.com")), body=None),
])
def test_api_errors_fall_back_to_templates(key, error):
    result = llm.supervisor_review({}, use_llm=True, client=FakeClient(error=error))
    assert result.mode == "offline" and result.review is None and type(error).__name__ in result.note


def test_the_digest_holds_no_money_amounts(state):
    digest = llm.build_digest(state)
    text = json.dumps(digest)
    assert "balance" not in text and "risk_at_min_lot" not in text and "margin_at_min_lot" not in text
    assert [a["agent_id"] for a in digest["agents"]] == [r["rule_id"] for r in state["research"]]
    assert digest["agents"][0]["never_seen_months"]["full_stop_rate"] is not None
    assert digest["accuracy_bar"] == 0.8 and digest["eligible_for_money"] is False


def test_claude_review_is_added_below_the_facts(state):
    report = build_report(state, REVIEW)
    md = report["markdown"]
    assert report["generated_by"] == "claude"
    assert md.index("## Verdict") < md.index("## Supervisor review (Claude)") < md.index("> Agents don't create an edge")
    assert "`tight_target`: High win rate, no edge." in md and "1. Export broker data and run again." in md


def test_pipeline_with_a_mocked_claude(key, tmp_path, demo, evaluations):
    shutil.copytree(ROOT / "config", tmp_path / "config", ignore=shutil.ignore_patterns("settings.local.json"))
    client = FakeClient(answered())
    state = pipeline.run("demo", True, Paths(tmp_path), dataset=demo, evaluations=list(evaluations.values()), now=NOW, llm_client=client)
    assert state["meta"]["llm_mode"] == "claude" and state["report"]["generated_by"] == "claude"
    assert {a["id"]: a["summary"] for a in state["agents"]}["report"].startswith("Report written; Claude wrote the review text")
    assert [r["gate"]["status"] for r in state["research"]] == ["qualified", "failed", "failed", "insufficient", "failed", "blocked"]
    sent = json.loads(client.calls[0]["messages"][0]["content"])
    assert "balance" not in json.dumps(sent)
