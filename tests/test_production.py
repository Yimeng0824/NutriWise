import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from config import Settings
from engine import RagEngine, weighted_retrieve
from providers import make_provider
from serve import create_app


class Backend:
    calls = 0

    def invoke(self, prompt, role):
        self.calls += 1
        return '营养回答'

    def stream(self, prompt, role, cancelled=None):
        self.calls += 1
        yield '营养'
        yield '回答'


class Store:
    def __init__(self, docs):
        self.docs = docs

    def similarity_search(self, query, k):
        return self.docs[:k]


def doc(kind='word_document'):
    return SimpleNamespace(metadata={'doc_type': kind, 'title': '测试资料'}, page_content='营养资料')


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-placeholder')
    return replace(Settings.from_env(load_file=False), rate_storage_uri='memory://', ask_limit='2/minute')


def test_environment_and_backend(settings, monkeypatch):
    monkeypatch.setenv('EMBEDDING_DEVICE', 'cpu')
    monkeypatch.setenv('LLM_PROVIDER', 'ollama')
    s = Settings.from_env(load_file=False)
    assert s.embedding_device == 'cpu'
    assert type(make_provider(s)).__name__ == 'OllamaProvider'
    assert type(make_provider(settings)).__name__ == 'DeepSeekProvider'
    monkeypatch.setenv('LLM_PROVIDER', 'typo')
    with pytest.raises(ValueError):
        Settings.from_env(load_file=False)


def test_weighting_greetings_and_empty(settings):
    words, others = [doc() for _ in range(8)], [doc('paper') for _ in range(8)]
    result = weighted_retrieve(Store(words + others), '问题')
    assert result == words[:4] + others[:4]
    backend = Backend()
    engine = RagEngine(settings, store_loader=lambda: Store([]), provider=backend)
    assert '小朋友' in engine.ask('student', '你好')['answer']
    assert '老师' in engine.ask('teacher', '你好')['answer']
    assert engine.ask('student', '这是一个知识问题')['answer']
    assert backend.calls == 0


def test_routes_stream_and_shared_ip_quota(settings):
    engine = RagEngine(settings, store_loader=lambda: Store([doc()]), provider=Backend())
    client = create_app(settings, engine).test_client()
    for route in ['/', '/student/', '/teacher/', '/healthz', '/readyz']:
        assert client.get(route).status_code == 200
    response = client.post('/student/api/ask', json={'question': '营养问题'})
    assert response.json['ok'] and response.json['answer'] == '营养回答'
    response = client.post('/teacher/api/ask/stream', json={'question': '教师营养问题'})
    assert response.mimetype == 'text/event-stream'
    frames = response.data.decode().split('\n\n')
    assert sum('event: token' in f for f in frames) == 2
    done = [json.loads(f.split('data: ', 1)[1]) for f in frames if 'event: done' in f][0]
    assert done['answer'] == '营养回答'
    blocked = client.post('/teacher/api/ask', json={'question': '你好'}, headers={'X-Forwarded-For': '8.8.8.8'})
    assert blocked.status_code == 429  # proxy headers are not trusted by default
    assert blocked.json['ok'] is False and 'Retry-After' in blocked.headers
    assert client.get('/healthz').status_code == 200


def test_validation_and_safe_upstream_error(settings):
    class Broken(Backend):
        def stream(self, prompt, role, cancelled=None):
            raise RuntimeError('secret-token-should-not-leak')
            yield

    app = create_app(replace(settings, ask_limit='100/minute'), RagEngine(settings, store_loader=lambda: Store([doc()]), provider=Broken()))
    client = app.test_client()
    for payload in [None, [], {'question': 1}, {'question': ' '}, {'question': 'x' * 4001}]:
        r = client.post('/student/api/ask', json=payload)
        assert r.status_code in (400, 415)
    r = client.post('/student/api/ask/stream', json={'question': '问题'})
    assert b'event: error' in r.data and b'secret-token' not in r.data


@pytest.mark.parametrize('role', ['student', 'teacher'])
@pytest.mark.parametrize('streaming', [False, True])
def test_empty_llm_answer_is_not_reported_as_success(settings, role, streaming):
    class Empty(Backend):
        def invoke(self, prompt, role):
            return '   '

        def stream(self, prompt, role, cancelled=None):
            yield '   '

    app = create_app(replace(settings, ask_limit='100/minute'), RagEngine(
        settings, store_loader=lambda: Store([doc()]), provider=Empty()))
    suffix = '/stream' if streaming else ''
    response = app.test_client().post(f'/{role}/api/ask{suffix}', json={'question': '蛋白质的作用是什么'})
    if streaming:
        assert b'event: error' in response.data
        assert b'event: done' not in response.data
    else:
        assert response.status_code == 502
        assert response.json['ok'] is False
