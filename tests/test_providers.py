from types import SimpleNamespace

from config import Settings
from providers import DeepSeekProvider, OllamaProvider


def test_deepseek_invokes_and_streams_without_exposing_key(monkeypatch):
    calls = []

    class Stream:
        def __enter__(self):
            return self

        def raise_for_status(self):
            pass

        def iter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"第一段"}}]}'
            yield ''
            yield ': keep-alive'
            yield 'data: {"choices":[{"delta":{"content":"第二段"}}]}'
            yield ''
            yield 'data: [DONE]'
            yield ''

        def __exit__(self, *args):
            calls.append('closed')

    def create(**kwargs):
        calls.append(kwargs)
        if kwargs.get('stream'):
            return Stream()
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='回答'))])

    monkeypatch.setattr('providers.OpenAI', lambda **kw: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def stream(self, method, url, **kwargs):
            calls.append(kwargs['json'])
            return Stream()

    monkeypatch.setattr('providers.httpx.Client', lambda **kwargs: Client())
    provider = DeepSeekProvider(Settings(deepseek_api_key='secret'))
    assert provider.invoke('资料', 'student') == '回答'
    assert list(provider.stream('资料', 'teacher')) == ['第一段', '第二段']
    assert calls[0]['temperature'] == 0.2 and calls[1]['temperature'] == 0.7
    assert calls[-1] == 'closed'


def test_ollama_protocol_and_response_cleanup(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append('closed')

        def json(self):
            return {'message': {'content': '普通回答'}}

        def iter_lines(self, **kwargs):
            yield b'{"message":{"content":"one"},"done":false}'
            yield b'{"message":{"content":"two"},"done":true}'

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr('providers.requests.post', post)
    provider = OllamaProvider(Settings(llm_provider='ollama', ollama_api_key='local-secret'))
    assert provider.invoke('资料', 'student') == '普通回答'
    assert list(provider.stream('资料', 'teacher')) == ['one', 'two']
    assert calls[0][0].endswith('/api/chat')
    assert calls[0][1]['json']['stream'] is False
    assert calls[2][1]['json']['stream'] is True
    assert calls[0][1]['json']['think'] is False
    assert calls[0][1]['json']['options']['num_thread'] == 2
    assert calls[0][1]['json']['options']['num_ctx'] == 4096
    assert calls.count('closed') == 2


def test_ollama_runtime_config_from_environment(monkeypatch):
    import pytest

    monkeypatch.setenv('LLM_PROVIDER', 'ollama')
    monkeypatch.setenv('OLLAMA_THINK', 'true')
    monkeypatch.setenv('OLLAMA_NUM_THREADS', '3')
    monkeypatch.setenv('OLLAMA_CONTEXT_LENGTH', '2048')
    settings = Settings.from_env(load_file=False)
    assert settings.ollama_think is True
    assert settings.ollama_num_threads == 3
    assert settings.ollama_context_length == 2048
    monkeypatch.setenv('OLLAMA_THINK', 'invalid')
    with pytest.raises(ValueError):
        Settings.from_env(load_file=False)
