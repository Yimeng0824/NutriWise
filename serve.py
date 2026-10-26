"""Flask application factory; production entrypoint is wsgi:app."""
import json
import logging
import queue
import threading

from flask import Blueprint, Flask, Response, jsonify, render_template, request, stream_with_context
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Settings
from engine import RagEngine


def create_app(settings=None, engine=None):
    settings = settings or Settings.from_env()
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 32 * 1024
    if settings.proxy_hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    engine = engine or RagEngine(settings)
    app.extensions['rag_engine'] = engine
    slots = threading.BoundedSemaphore(settings.max_concurrent)
    limiter = Limiter(get_remote_address, app=app, default_limits=[],
                      storage_uri=settings.rate_storage_uri, headers_enabled=True,
                      swallow_errors=False, strategy='fixed-window')
    quota = limiter.shared_limit(settings.ask_limit, scope='all-ask')

    @app.errorhandler(HTTPException)
    def http_error(error):
        response = error.get_response()
        response.data = json.dumps({'ok': False, 'error': '请求过于频繁，请稍后重试' if error.code == 429 else '请求格式或地址有误'}, ensure_ascii=False)
        response.content_type = 'application/json'
        return response

    @app.errorhandler(Exception)
    def service_error(error):
        app.logger.error('Request dependency failed: %s', type(error).__name__)
        return jsonify(ok=False, error='服务暂时不可用，请稍后重试'), 503

    @app.get('/')
    def home():
        return render_template('home.html')

    @app.get('/healthz')
    def health():
        return jsonify(status='ok')

    @app.get('/readyz')
    @app.get('/student/api/health')
    @app.get('/teacher/api/health')
    def ready():
        try:
            engine.ready()
            return jsonify(status='ok', device=settings.embedding_device, model_loads=engine.load_count)
        except Exception as exc:
            app.logger.error('Model initialization failed: %s', type(exc).__name__)
            return jsonify(status='error'), 503

    def question():
        data = request.get_json()
        if not isinstance(data, dict) or not isinstance(data.get('question'), str):
            return None
        text = data['question'].strip()
        return text if 0 < len(text) <= 4000 else None

    def ask(role):
        text = question()
        if text is None:
            return jsonify(ok=False, error='请输入1至4000字的问题'), 400
        if not slots.acquire(blocking=False):
            return jsonify(ok=False, error='服务正忙，请稍后重试'), 503, {'Retry-After': '5'}
        try:
            return jsonify(engine.ask(role, text))
        except Exception as exc:
            app.logger.warning('Generation failed: %s', type(exc).__name__)
            return jsonify(ok=False, error='暂时无法完成回答，请稍后重试'), 502
        finally:
            slots.release()

    def ask_stream(role):
        text = question()
        if text is None:
            return jsonify(ok=False, error='请输入1至4000字的问题'), 400
        if not slots.acquire(blocking=False):
            return jsonify(ok=False, error='服务正忙，请稍后重试'), 503, {'Retry-After': '5'}
        events, cancelled = queue.Queue(maxsize=32), threading.Event()
        started = threading.Event()
        release_lock = threading.Lock()
        released = False

        def release_slot():
            nonlocal released
            with release_lock:
                if not released:
                    released = True
                    slots.release()

        def close_response():
            cancelled.set()
            if not started.is_set():
                release_slot()

        def put(item):
            while not cancelled.is_set():
                try:
                    events.put(item, timeout=0.2)
                    return True
                except queue.Full:
                    pass
            return False

        def produce():
            iterator = None
            try:
                iterator = engine.stream(role, text, cancelled=cancelled)
                for event in iterator:
                    if not put(event):
                        break
            except Exception as exc:
                app.logger.warning('Stream failed: %s', type(exc).__name__)
                put(('error', {'ok': False, 'error': '暂时无法完成回答，请稍后重试'}))
            finally:
                if iterator is not None:
                    iterator.close()
                release_slot()
                put(None)

        def output():
            started.set()
            try:
                threading.Thread(target=produce, daemon=True, name='llm-stream').start()
            except Exception:
                release_slot()
                raise
            try:
                yield ': connected\n\n'
                while True:
                    try:
                        item = events.get(timeout=settings.heartbeat_seconds)
                    except queue.Empty:
                        yield ': heartbeat\n\n'
                        continue
                    if item is None:
                        return
                    name, data = item
                    yield f'event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'
            finally:
                # Producer closes the upstream iterator itself; no cross-thread generator.close.
                # A silent upstream remains bounded by LLM_TIMEOUT.
                cancelled.set()

        response = Response(stream_with_context(output()), mimetype='text/event-stream',
                            headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'})
        response.call_on_close(close_response)
        return response

    # One Blueprint per audience: identical retrieval core, isolated routes and prompts.
    for role, template in [('student', 'index.html'), ('teacher', 'index_teacher.html')]:
        bp = Blueprint(role, __name__, url_prefix=f'/{role}')
        bp.add_url_rule('/', 'index', lambda t=template: render_template(t))
        bp.add_url_rule('/api/ask', 'ask', quota(lambda r=role: ask(r)), methods=['POST'])
        bp.add_url_rule('/api/ask/stream', 'stream', quota(lambda r=role: ask_stream(r)), methods=['POST'])
        app.register_blueprint(bp)
    if settings.rate_storage_uri == 'memory://':
        logging.getLogger(__name__).warning('Memory rate storage is for local smoke tests only; production uses Redis')
    return app
