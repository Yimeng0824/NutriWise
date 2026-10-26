import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

from config import Settings
from engine import RagEngine
from serve import create_app
from werkzeug.test import create_environ


def settings():
    return Settings(deepseek_api_key='test', ask_limit='100/minute', max_concurrent=1, heartbeat_seconds=1)


def test_single_model_under_parallel_readiness():
    calls = []

    def load():
        time.sleep(0.03)
        calls.append(1)
        return object()

    engine = RagEngine(settings(), store_loader=load, provider=object())
    with ThreadPoolExecutor(max_workers=8) as executor:
        stores = list(executor.map(lambda _: engine.ready(), range(16)))
    assert len(calls) == engine.load_count == 1
    assert all(x is stores[0] for x in stores)


def test_stream_is_incremental_and_disconnect_releases_slot():
    entered, proceed, closed = threading.Event(), threading.Event(), threading.Event()

    class Engine:
        def stream(self, role, query, cancelled=None):
            try:
                yield 'token', {'text': '第一段'}
                entered.set()
                proceed.wait(3)
                yield 'token', {'text': '第二段'}
                yield 'done', {'answer': '完成'}
            finally:
                closed.set()

        def ask(self, role, query):
            return {'ok': True, 'answer': '恢复可用'}

    app = create_app(settings(), Engine())
    client = app.test_client()
    response = client.post('/student/api/ask/stream', json={'question': '问题'}, buffered=False)
    iterator = iter(response.response)
    assert b'connected' in next(iterator)
    assert '第一段' in next(iterator).decode()
    assert entered.wait(1)
    assert client.post('/teacher/api/ask', json={'question': '问题'}).status_code == 503
    response.close()
    proceed.set()
    assert closed.wait(2)
    for _ in range(20):
        if client.post('/teacher/api/ask', json={'question': '问题'}).status_code == 200:
            break
        time.sleep(0.02)
    else:
        raise AssertionError('Generation slot was not released')


def test_trusted_proxy_keeps_distinct_ips():
    class Engine:
        def ask(self, role, query):
            return {'ok': True, 'answer': 'ok'}

    app = create_app(replace(settings(), proxy_hops=1, ask_limit='1/minute'), Engine())
    client = app.test_client()
    for ip in ('192.0.2.1', '192.0.2.2'):
        r = client.post('/student/api/ask', json={'question': '问题'}, headers={'X-Forwarded-For': ip})
        assert r.status_code == 200
    assert client.post('/teacher/api/ask', json={'question': '问题'}, headers={'X-Forwarded-For': '192.0.2.1'}).status_code == 429


def test_unconsumed_stream_does_not_leak_generation_slot():
    class Engine:
        def ask(self, role, query):
            return {'ok': True}

    app = create_app(settings(), Engine())
    environ = create_environ(path='/student/api/ask/stream', method='POST',
                             data='{"question":"test"}', content_type='application/json')
    body = app.wsgi_app(environ, lambda status, headers, exc_info=None: None)
    body.close()  # client disappeared before the server pulled its first SSE frame
    assert app.test_client().post('/teacher/api/ask', json={'question': '问题'}).status_code == 200


def test_unavailable_rate_storage_returns_safe_json():
    app = create_app(replace(settings(), rate_storage_uri='redis://127.0.0.1:1/0'), object())
    r = app.test_client().post('/student/api/ask', json={'question': '问题'})
    assert r.status_code == 503
    assert r.json['ok'] is False
