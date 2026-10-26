"""Explicit acceptance tests for project items 5/6.

No BGE weights are loaded and no real LLM request is sent in this module.
"""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from config import Settings
from engine import RagEngine, weighted_retrieve
from providers import DeepSeekProvider, OllamaProvider, make_provider
from serve import create_app


class FakeStore:
    def __init__(self, docs):
        self.docs = docs
        self.search_calls = 0

    def similarity_search(self, query, k):
        self.search_calls += 1
        return self.docs[:k]


class FakeProvider:
    def __init__(self, answer="mock answer"):
        self.answer = answer
        self.calls = []

    def invoke(self, prompt, role):
        self.calls.append((prompt, role))
        return self.answer

    def stream(self, prompt, role, cancelled=None):
        self.calls.append((prompt, role))
        yield self.answer


def fake_doc(kind="word_document", title="测试资料"):
    return SimpleNamespace(
        metadata={"doc_type": kind, "title": title},
        page_content="营养资料",
    )


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ci-placeholder-not-a-real-key")
    return replace(
        Settings.from_env(load_file=False),
        rate_storage_uri="memory://",
        ask_limit="100/minute",
    )


def test_weighted_retrieval_prioritizes_word_documents():
    word_docs = [fake_doc("word_document", f"word-{i}") for i in range(6)]
    other_docs = [fake_doc("paper", f"paper-{i}") for i in range(10)]
    result = weighted_retrieve(FakeStore(word_docs + other_docs), "蛋白质", k=8)
    assert result == word_docs[:4] + other_docs[:4]
    assert len(result) == 8


def test_api_ask_and_student_teacher_routes(settings):
    engine = RagEngine(
        settings,
        store_loader=lambda: FakeStore([fake_doc()]),
        provider=FakeProvider("固定测试回答"),
    )
    client = create_app(settings, engine).test_client()
    assert client.get("/student/").status_code == 200
    assert client.get("/teacher/").status_code == 200

    for role in ("student", "teacher"):
        response = client.post(f"/{role}/api/ask", json={"question": "蛋白质有什么作用"})
        assert response.status_code == 200
        assert response.json["ok"] is True
        assert "固定测试回答" in response.json["answer"]


def test_greeting_branch_does_not_search_or_call_llm(settings):
    store = FakeStore([fake_doc()])
    provider = FakeProvider()
    engine = RagEngine(settings, store_loader=lambda: store, provider=provider)
    result = engine.ask("student", "你好")
    assert result["ok"] is True
    assert provider.calls == []
    assert store.search_calls == 0


def test_empty_retrieval_does_not_call_llm(settings):
    store = FakeStore([])
    provider = FakeProvider()
    engine = RagEngine(settings, store_loader=lambda: store, provider=provider)
    result = engine.ask("teacher", "请说明某营养问题")
    assert result["ok"] is True
    assert provider.calls == []
    assert store.search_calls == 1


def test_llm_backend_switch_is_mock_safe(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ci-placeholder-not-a-real-key")

    class DummyOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr("providers.OpenAI", DummyOpenAI)

    deepseek = make_provider(Settings.from_env(load_file=False))
    assert isinstance(deepseek, DeepSeekProvider)
    assert deepseek.options("问题", "student")["model"] == "deepseek-flash"
    assert deepseek.options("问题", "student")["extra_body"] == {"thinking": {"type": "disabled"}}

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    ollama = make_provider(Settings.from_env(load_file=False))
    assert isinstance(ollama, OllamaProvider)


def test_embedding_model_is_mocked_by_store_loader(settings):
    """If this passes without torch/langchain, CI never loads/downloads BGE."""
    sentinel_store = FakeStore([fake_doc()])
    engine = RagEngine(settings, store_loader=lambda: sentinel_store, provider=FakeProvider())
    assert engine.ready() is sentinel_store
    assert engine.embedding is None
    assert engine.load_count == 1


def test_student_and_teacher_are_separate_blueprints(settings):
    engine = RagEngine(settings, store_loader=lambda: FakeStore([fake_doc()]), provider=FakeProvider())
    app = create_app(settings, engine)
    assert {"student", "teacher"} <= set(app.blueprints)
    endpoints = {rule.rule: rule.endpoint for rule in app.url_map.iter_rules()}
    assert endpoints["/student/api/ask"] == "student.ask"
    assert endpoints["/teacher/api/ask/stream"] == "teacher.stream"
