"""Regression for real provider keepalive-only SSE while queued."""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from config import Settings
from providers import DeepSeekProvider


@pytest.fixture
def queued_server():
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            try:
                for _ in range(60):
                    self.wfile.write(b': keep-alive\n\n')
                    self.wfile.flush()
                    time.sleep(0.05)
                self.wfile.write(b'data: [DONE]\n\n')
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    server.server_close()


def test_cancel_observes_upstream_comment_frames(queued_server):
    provider = DeepSeekProvider(Settings(deepseek_api_key='test', deepseek_base_url=queued_server, llm_timeout=1))
    cancelled = threading.Event()
    timer = threading.Timer(0.2, cancelled.set)
    timer.start()
    started = time.monotonic()
    try:
        assert list(provider.stream('问题', 'student', cancelled=cancelled)) == []
        assert time.monotonic() - started < 1.2
    finally:
        timer.cancel()


def test_comment_frames_do_not_reset_generation_budget(queued_server):
    provider = DeepSeekProvider(Settings(deepseek_api_key='test', deepseek_base_url=queued_server, llm_timeout=1))
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        list(provider.stream('问题', 'student'))
    assert time.monotonic() - started < 1.8
