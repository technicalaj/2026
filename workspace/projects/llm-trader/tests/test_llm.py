import json
from types import SimpleNamespace

import anthropic
import httpx
import pandas as pd
import pytest
from project_copy import copy_project

from llm_trader import cli, llm, pipeline
from llm_trader.config import LlmSettings
from llm_trader.llm import AgentNote, Budget, SupervisorReview
from llm_trader.report import build_report

NOW = pd.Timestamp("2026-11-02 04:10", tz="UTC")
REVIEW = SupervisorReview(
    summary="Only the self-tests behaved; no rule agent qualified. That is expected on demo data.",
    agent_notes=[AgentNote(agent_id="tight_target", note="High win rate, no edge.")],
    warnings=["Demo data is never eligible for money."],
    next_steps=["Export broker data and run again."],
)


def usage(input_tokens=6000, output_tokens=2000, iterations=None, **cache) -> SimpleNamespace:
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens, iterations=iterations,
                           cache_creation_input_tokens=cache.get("write", 0), cache_read_input_tokens=cache.get("read", 0))


def answered(review=REVIEW, stop_reason="end_turn", model="claude-opus-5-5", spent=None):
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=review, model=model, usage=spent or usage())


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
        raise AssertionError("the Claude client must not be used here")


@pytest.fixture(autouse=True)
def no_real_client(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: Untouchable())
    monkeypatch.delenv("LLM_MODE", raising=False)


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")


@pytest.fixture(scope="module")
def state(tmp_path_factory, demo, evaluations):
    return pipeline.run("demo", paths=copy_project(tmp_path_factory.mktemp("llm")), dataset=demo, evaluations=list(evaluations.values()), now=NOW)


def test_offline_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = llm.supervisor_review({"x": 1}, use_llm=True, client=Untouchable())
    assert (result.mode, result.note, result.review) == ("offline", llm.NO_KEY_NOTE, None)
    assert result.note == "No ANTHROPIC_API_KEY set: Supervisor review and report use built-in templates."


def test_offline_without_the_llm_switch(key):
    result = llm.supervisor_review({"x": 1}, use_llm=False, client=Untouchable())
    assert (result.mode, result.note, result.review) == ("offline", llm.NOT_ASKED_NOTE, None)


def test_the_call_matches_the_spec_exactly(key):
    client = FakeClient(answered())
    result = llm.supervisor_review({"date": "2026-11-02", "agents": []}, use_llm=True, client=client)
    assert result.mode == "claude" and result.review == REVIEW and result.note.startswith(llm.CLAUDE_NOTE)
    [call] = client.calls
    assert call == {
        "model": "claude-opus-5-5", "max_tokens": 16000,
        "betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default",
        "output_config": {"effort": "medium"},
        "system": llm.STABLE_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": json.dumps({"agents": [], "date": "2026-11-02"})}],
        "output_format": SupervisorReview,
    }


def test_cost_comes_from_usage_at_plan_prices():
    assert llm.tokens_cost(llm.price("claude-opus-5-5"), 1_000_000, 1_000_000) == pytest.approx(24.0)
    assert llm.tokens_cost(llm.price("claude-haiku-5-5"), 1_000_000, 1_000_000) == pytest.approx(0.6)
    assert llm.price("claude-sonnet-5-5") == (2.0, 10.0) and llm.price("some-new-model") == (10.0, 50.0)
    assert llm.response_cost(answered(), "claude-opus-5-5") == pytest.approx(0.064)
    cached = answered(spent=usage(1000, 0, write=1000, read=1000))
    assert llm.response_cost(cached, "claude-opus-5-5") == pytest.approx((1000 + 1000 + 1250) * 4 / 1e6)
    attempts = [SimpleNamespace(type="message", input_tokens=5000, output_tokens=100),
                SimpleNamespace(type="fallback_message", input_tokens=5000, output_tokens=2000)]
    rescued = answered(model="claude-opus-4-8", spent=usage(5000, 2000, iterations=attempts))
    assert llm.response_cost(rescued, "claude-opus-5-5") == pytest.approx((10_000 * 10 + 2100 * 50) / 1e6)
    assert llm.response_cost(SimpleNamespace(), "claude-opus-5-5") is None


def test_cost_cap_is_checked_before_the_call(key):
    small = LlmSettings(cost_cap_usd=0.10)
    result = llm.supervisor_review({"x": 1}, use_llm=True, client=Untouchable(), cfg=small)
    assert result.mode == "offline" and result.note.startswith("The AI cost cap ($0.10 per run) leaves no room")
    assert llm.worst_case_cost("claude-opus-5-5", 16000, "x" * 3000) == pytest.approx((1001 * 4 + 16000 * 20) / 1e6)


def test_calls_stop_once_the_cap_is_reached(key):
    budget = Budget(0.50)
    first = llm.supervisor_review({"x": 1}, use_llm=True, client=FakeClient(answered(spent=usage(6000, 12000))), budget=budget)
    assert first.mode == "claude" and budget.calls == 1 and budget.spent_usd == pytest.approx(0.264)
    assert "Estimated cost $0.264 of the $0.50 cap" in first.note
    second = llm.supervisor_review({"x": 1}, use_llm=True, client=Untouchable(), budget=budget)
    assert second.mode == "offline" and "cost cap" in second.note and budget.calls == 1


def test_the_daily_budget_carries_across_runs(key, tmp_path):
    ledger = tmp_path / "llm_spend.json"
    cfg = LlmSettings(cost_cap_usd=0.50, daily_cap_usd=0.55)
    first = llm.supervisor_review({"x": 1}, use_llm=True, client=FakeClient(answered(spent=usage(6000, 12000))), cfg=cfg,
                                  budget=llm.run_budget(cfg, ledger, "2026-11-02"))
    llm.record_spend(ledger, "2026-11-02", first.cost_usd)
    later = llm.run_budget(cfg, ledger, "2026-11-02")
    assert later.cap_usd == pytest.approx(0.55 - 0.264) and later.daily
    refused = llm.supervisor_review({"x": 1}, use_llm=True, client=Untouchable(), cfg=cfg, budget=later)
    assert refused.mode == "offline" and refused.note.startswith("Today's AI budget ($0.55 a day, reset at 00:00 UTC) is used up")
    assert llm.run_budget(cfg, ledger, "2026-11-03").cap_usd == pytest.approx(0.50)


def test_a_small_call_leaves_room_for_another(key):
    budget = Budget(0.50)
    llm.supervisor_review({"x": 1}, use_llm=True, client=FakeClient(answered()), budget=budget)
    assert budget.spent_usd == pytest.approx(0.064)
    assert llm.supervisor_review({"x": 1}, use_llm=True, client=FakeClient(answered()), budget=budget).mode == "claude"
    assert budget.calls == 2


def test_a_reply_without_usage_is_charged_the_worst_case(key):
    budget = Budget(0.50)
    llm.supervisor_review({"x": 1}, use_llm=True, client=FakeClient(SimpleNamespace(stop_reason="end_turn", parsed_output=REVIEW)), budget=budget)
    assert budget.spent_usd == pytest.approx(llm.worst_case_cost("claude-opus-5-5", 16000, llm.STABLE_SYSTEM_PROMPT, '{"x": 1}'))


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


def test_scored_agents_treat_refusals_and_fallbacks_as_no_opinion():
    pinned = "claude-haiku-5-5"
    assert not llm.no_opinion(answered(model=pinned), pinned)
    assert llm.no_opinion(None, pinned)
    assert llm.no_opinion(answered(stop_reason="refusal", model=pinned), pinned)
    assert llm.no_opinion(answered(model="claude-sonnet-5-5"), pinned)
    served = usage(iterations=[SimpleNamespace(type="message"), SimpleNamespace(type="fallback_message")])
    assert llm.no_opinion(answered(model=pinned, spent=served), pinned)


def test_llm_switch_and_env(monkeypatch):
    assert llm.llm_wanted("on") is True and llm.llm_wanted("off") is False and llm.llm_wanted(None) is False
    monkeypatch.setenv("LLM_MODE", "on")
    assert llm.llm_wanted(None) is True and llm.llm_wanted("off") is False
    monkeypatch.setenv("LLM_MODE", "offline")
    assert llm.llm_wanted(None) is False


@pytest.mark.parametrize("argv, wanted", [
    (["run", "--demo"], False), (["run", "--demo", "--llm"], True), (["run", "--demo", "--llm", "on"], True),
    (["run", "--demo", "--llm", "off"], False), (["demo", "--llm", "on"], True),
])
def test_cli_llm_option(tmp_path, state, monkeypatch, argv, wanted):
    calls = []
    monkeypatch.setattr(pipeline, "run", lambda data, use_llm, paths: calls.append(use_llm) or state)
    monkeypatch.setattr("llm_trader.snapshot.write_snapshot", lambda paths, state=None: paths.dashboard_file)
    assert cli.main(argv, copy_project(tmp_path)) == 0
    assert calls == [wanted]


def test_the_digest_holds_no_money_amounts(state):
    digest = llm.build_digest(state)
    text = json.dumps(digest)
    assert "balance" not in text and "risk_at_min_lot" not in text and "margin_at_min_lot" not in text
    assert [a["agent_id"] for a in digest["agents"]] == [r["rule_id"] for r in state["research"]]
    assert digest["agents"][0]["never_seen_months"]["full_stop_rate"] is not None
    assert digest["accuracy_bar"] == 0.8 and digest["eligible_for_money"] is False and digest["trial_count"] >= 6
    assert {t["name"] for t in digest["self_tests"]} == {t["name"] for t in state["self_tests"]}
    assert digest["event_tagger"]["measured"] == "UNMEASURED" and digest["picks_today"]["picks"] == []


def test_claude_review_is_added_below_the_facts(state):
    report = build_report(state, REVIEW)
    md = report["markdown"]
    assert report["generated_by"] == "claude"
    assert md.index("## Verdict") < md.index("## Supervisor review (Claude)") < md.index("> Agents don't create an edge")
    assert "`tight_target`: High win rate, no edge." in md and "1. Export broker data and run again." in md


def test_pipeline_with_a_mocked_claude(key, tmp_path, demo, evaluations):
    client = FakeClient(answered())
    state = pipeline.run("demo", True, copy_project(tmp_path), dataset=demo, evaluations=list(evaluations.values()), now=NOW, llm_client=client)
    assert state["meta"]["llm_mode"] == "claude" and state["report"]["generated_by"] == "claude"
    assert state["meta"]["banners"] == ["SYNTHETIC DATA", "NO TRADING"] and "Estimated cost $0.064" in state["meta"]["llm_note"]
    assert {a["id"]: a["summary"] for a in state["agents"]}["report"].startswith("Report written; Claude wrote the review text")
    assert [r["gate"]["status"] for r in state["research"]] == ["qualified", "failed", "failed", "insufficient", "failed", "blocked"]
    assert len(client.calls) == 1 and "balance" not in client.calls[0]["messages"][0]["content"]
