"""Eval-only replay of web tools from local fixture pages (PLAN.md Loop 2 step 6, correction C27)."""

import json
from pathlib import Path

from sabor_a2a import researcher_hooks as hooks
from sabor_a2a import web_replay

PAGES = Path(__file__).resolve().parents[2] / "evals" / "web_fixtures" / "pages"
MARMITA_URL = web_replay.FIXTURE_BASE_URL + "marmita_quatro_bocas.html"


def setup_function():
    hooks.reset()


def test_search_ranks_fixture_pages_by_title_words_in_hermes_result_shape():
    data = json.loads(web_replay.replay(PAGES, "web_search", {"query": "marmita completa arroz feijão bife couve"}))
    rows = data["data"]["web"]
    assert data["success"] is True and 1 <= len(rows) <= 3
    assert rows[0]["url"] == MARMITA_URL and rows[0]["title"].startswith("Marmita completa") and rows[0]["position"] == 1


def test_extract_returns_the_visible_text_of_fixture_pages_only():
    data = json.loads(web_replay.replay(PAGES, "web_extract", {"urls": [MARMITA_URL, "https://example.com/receita"]}))
    page, other = data["results"]
    assert page["url"] == MARMITA_URL and "use as 4 bocas do fogão ao mesmo tempo" in page["content"]
    assert "<li>" not in page["content"] and "Rendimento: 4 porções" in page["content"]
    assert other["url"] == "https://example.com/receita" and "error" in other and "content" not in other


def test_other_tools_are_not_replayed():
    assert web_replay.replay(PAGES, "delegate_task", {"goal": "x"}) is None


def test_researcher_replays_web_tools_and_counts_fixture_urls_as_visited(monkeypatch):
    monkeypatch.setenv("SABOR_WEB_FIXTURES_DIR", str(PAGES))
    hooks.pre_llm_call(session_id="session-1", user_message=json.dumps({"task_type": "recipe_search", "items": ["marmita"]}), platform="a2a")
    hooks.subagent_start(parent_session_id="session-1", child_session_id="child-1")
    replayed = hooks.transform_tool_result(tool_name="web_extract", args={"urls": [MARMITA_URL]},
                                           result='{"error": "backend unavailable"}', session_id="child-1")
    assert "use as 4 bocas" in json.loads(replayed)["results"][0]["content"]
    assert MARMITA_URL in hooks._visited["session-1"]


def test_without_the_fixtures_variable_the_real_result_is_kept(monkeypatch):
    monkeypatch.delenv("SABOR_WEB_FIXTURES_DIR", raising=False)
    assert hooks.transform_tool_result(tool_name="web_search", args={"query": "x"}, result='{"success": true}', session_id="s") is None
