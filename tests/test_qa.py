import os
from dataclasses import dataclass

import httpx
import pytest

from archive import config
from archive.llm import ChatCompletionsLLM, LLMError, get_llm
from archive.qa import NOT_FOUND, SYSTEM_PROMPT, answer_question, build_prompt, cited_numbers


@dataclass
class FakeHit:
    text: str
    score: float
    page: int
    title: str = "COS 101"
    doc_id: str = "abc123"

    @property
    def citation(self):
        return f"[{self.title}, p. {self.page}]"


class FakeStore:
    def __init__(self, hits):
        self._hits = hits

    def count(self):
        return len(self._hits)

    def search(self, question, k, course=None, doc_id=None):
        return self._hits[:k]


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def complete(self, system, user, **kw):
        self.calls.append((system, user))
        return self.reply


HITS = [FakeHit("Anaconda is a Python distribution.", 0.71, 13),
        FakeHit("Download the installer for your system.", 0.66, 14),
        FakeHit("Launch Anaconda Navigator from search.", 0.59, 15)]


def test_weak_match_never_calls_the_model():
    llm = FakeLLM("should not be used")
    res = answer_question("what is football", FakeStore([FakeHit("x", 0.10, 1)]), llm, min_score=0.30)
    assert llm.calls == [] and res.answer == NOT_FOUND and res.low_confidence


def test_empty_archive_never_calls_the_model():
    llm = FakeLLM("nope")
    res = answer_question("anything", FakeStore([]), llm)
    assert llm.calls == [] and res.answer == NOT_FOUND


def test_only_cited_excerpts_become_sources():
    res = answer_question("what is anaconda", FakeStore(HITS), FakeLLM("A Python distribution [2]."))
    assert res.cited and [s["page"] for s in res.sources] == [14]
    assert len(res.related) == 3 and not res.low_confidence


def test_citation_formats_and_invalid_numbers():
    assert cited_numbers("a [1, 3] b [1][2]", 3) == [1, 3, 2]
    assert cited_numbers("nothing valid [9] [0]", 3) == []


def test_answer_without_citations_is_flagged():
    res = answer_question("q", FakeStore(HITS), FakeLLM("Sounds right but no markers."))
    assert not res.cited and res.sources == [] and len(res.related) == 3


def test_model_saying_not_found_is_low_confidence():
    res = answer_question("q", FakeStore(HITS), FakeLLM(NOT_FOUND))
    assert res.low_confidence and res.sources == []


def test_prompt_has_rules_excerpts_and_question():
    llm = FakeLLM("ok [1]")
    answer_question("what is anaconda", FakeStore(HITS), llm)
    system, user = llm.calls[0]
    assert system == SYSTEM_PROMPT and "ONLY" in system
    assert "Anaconda is a Python distribution." in user and "QUESTION: what is anaconda" in user
    assert "[1] (COS 101, p. 13)" in build_prompt("q", HITS)


def _llm_with(handler, key="secret-key-123"):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ChatCompletionsLLM("https://example.test/v1", "test-model", key, client=client)


def test_llm_success_sends_expected_request():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": "  hello [1] "}}]})

    assert _llm_with(handler).complete("sys", "usr") == "hello [1]"
    assert seen["auth"] == "Bearer secret-key-123" and "test-model" in seen["body"]


def test_llm_rejected_key_does_not_leak_the_key():
    with pytest.raises(LLMError) as e:
        _llm_with(lambda r: httpx.Response(401)).complete("s", "u")
    assert "key" in str(e.value).lower() and "secret-key-123" not in str(e.value)


def test_llm_rate_limit_and_server_errors_are_worded_for_humans():
    with pytest.raises(LLMError, match="rate limit"):
        _llm_with(lambda r: httpx.Response(429)).complete("s", "u")
    with pytest.raises(LLMError, match="500"):
        _llm_with(lambda r: httpx.Response(500)).complete("s", "u")


def test_llm_error_shows_service_message_but_hides_the_key():
    body = {"message": "Rate limit exceeded for key secret-key-123 on this plan"}
    with pytest.raises(LLMError) as e:
        _llm_with(lambda r: httpx.Response(429, json=body)).complete("s", "u")
    text = str(e.value)
    assert "Rate limit exceeded" in text and "secret-key-123" not in text and "***" in text


def test_llm_text_parts_reply_is_joined():
    reply = {"choices": [{"message": {"content": [{"text": "a"}, {"text": "b"}]}}]}
    assert _llm_with(lambda r: httpx.Response(200, json=reply)).complete("s", "u") == "ab"


def test_get_llm_needs_a_key_and_knows_providers(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(LLMError, match=".env"):
        get_llm("mistral")
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    monkeypatch.setattr(config, "LLM_MODEL", "")      # ignore the model chosen in your own .env
    assert get_llm("mistral").model == "mistral-small-latest"
    assert get_llm("ollama").base_url.startswith("http://localhost")   # no key needed
    with pytest.raises(LLMError, match="Unknown provider"):
        get_llm("nonsense")


def test_dotenv_reader(tmp_path, monkeypatch):
    monkeypatch.setenv("DOTENV_TEST_NEW", "x")
    monkeypatch.delenv("DOTENV_TEST_NEW")          # makes pytest remove it again afterwards
    monkeypatch.setenv("DOTENV_TEST_KEEP", "original")
    env = tmp_path / ".env"
    env.write_text('# comment\n\nDOTENV_TEST_NEW="quoted value"\nDOTENV_TEST_KEEP=changed\n', "utf-8")
    config.load_dotenv(env)
    assert os.environ["DOTENV_TEST_NEW"] == "quoted value"
    assert os.environ["DOTENV_TEST_KEEP"] == "original"        # existing variables win
    config.load_dotenv(tmp_path / "missing.env")                # a missing file is fine