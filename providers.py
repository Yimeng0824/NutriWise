"""Provider adapters. Importing this module makes no inference requests."""
import json
import time

import httpx
import requests
try:
    from openai import OpenAI
except ImportError:  # Allows mock-only tests to import without the SDK installed.
    OpenAI = None


class DeepSeekProvider:
    def __init__(self, settings):
        self.settings = settings
        self.client = None

    def _client(self):
        # Lazy construction keeps import-time/backend-switch tests independent of the SDK
        # and means the raw SSE path does not need the OpenAI client at all.
        if self.client is None:
            if OpenAI is None:
                raise RuntimeError('openai package is required for the DeepSeek backend')
            self.client = OpenAI(api_key=self.settings.deepseek_api_key,
                                 base_url=self.settings.deepseek_base_url,
                                 timeout=self.settings.llm_timeout, max_retries=0)
        return self.client

    def options(self, prompt, role):
        return dict(model=self.settings.deepseek_model, messages=[{'role': 'user', 'content': prompt}],
                    temperature=0.2 if role == 'student' else 0.7, max_tokens=self.settings.max_tokens,
                    extra_body={'thinking': {'type': 'disabled'}})

    def invoke(self, prompt, role):
        response = self._client().chat.completions.create(**self.options(prompt, role))
        return response.choices[0].message.content or ''

    def stream(self, prompt, role, cancelled=None):
        started = time.monotonic()
        payload = self.options(prompt, role)
        # extra_body is an OpenAI-SDK wrapper; raw HTTP must receive `thinking` directly.
        payload.update(payload.pop('extra_body', {}))
        payload['stream'] = True
        headers = {'Authorization': 'Bearer ' + self.settings.deepseek_api_key,
                   'Accept': 'text/event-stream'}
        # Read raw SSE lines: the OpenAI SDK hides DeepSeek's queued keepalive comments.
        with httpx.Client(timeout=httpx.Timeout(self.settings.llm_timeout, connect=10)) as client:
            with client.stream('POST', self.settings.deepseek_base_url.rstrip('/') + '/chat/completions',
                               headers=headers, json=payload) as response:
                response.raise_for_status()
                data = []
                for line in response.iter_lines():
                    if cancelled is not None and cancelled.is_set():
                        return
                    if time.monotonic() - started > self.settings.llm_timeout:
                        raise TimeoutError('Generation budget exceeded')
                    if line.startswith('data:'):
                        data.append(line[5:].lstrip())
                    elif line == '' and data:
                        value = '\n'.join(data)
                        data.clear()
                        if value == '[DONE]':
                            return
                        body = json.loads(value)
                        if body.get('error'):
                            raise RuntimeError('DeepSeek generation failed')
                        choices = body.get('choices', [])
                        content = choices[0].get('delta', {}).get('content') if choices else None
                        if content:
                            yield content
                raise RuntimeError('Upstream stream ended without completion marker')


class OllamaProvider:
    def __init__(self, settings):
        self.settings = settings

    def call(self, prompt, role, stream):
        headers = {}
        if self.settings.ollama_api_key:
            headers['Authorization'] = 'Bearer ' + self.settings.ollama_api_key
        response = requests.post(self.settings.ollama_base_url.rstrip('/') + '/api/chat',
                                 headers=headers, json={
                                     'model': self.settings.ollama_model, 'stream': stream,
                                     'think': self.settings.ollama_think,
                                     'messages': [{'role': 'user', 'content': prompt}],
                                     'options': {'temperature': 0.2 if role == 'student' else 0.7,
                                                 'num_predict': self.settings.max_tokens,
                                                 'num_thread': self.settings.ollama_num_threads,
                                                 'num_ctx': self.settings.ollama_context_length}},
                                 timeout=(10, self.settings.llm_timeout), stream=stream)
        try:
            response.raise_for_status()
        except Exception:
            response.close()
            raise
        return response

    def invoke(self, prompt, role):
        with self.call(prompt, role, False) as response:
            body = response.json()
            if body.get('error'):
                raise RuntimeError('Ollama generation failed')
            return body.get('message', {}).get('content', '')

    def stream(self, prompt, role, cancelled=None):
        started = time.monotonic()
        with self.call(prompt, role, True) as response:
            for line in response.iter_lines(chunk_size=1):
                if cancelled is not None and cancelled.is_set():
                    return
                if time.monotonic() - started > self.settings.llm_timeout:
                    raise TimeoutError('Generation budget exceeded')
                if not line:
                    continue
                body = json.loads(line)
                if body.get('error'):
                    raise RuntimeError('Ollama generation failed')
                value = body.get('message', {}).get('content', '')
                if value:
                    yield value
                if body.get('done'):
                    return
            raise RuntimeError('Upstream stream ended without completion marker')


def make_provider(settings):
    return (DeepSeekProvider if settings.llm_provider == 'deepseek' else OllamaProvider)(settings)
