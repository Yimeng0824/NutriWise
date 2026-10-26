"""Real HTTP/Gunicorn check. Expects a fresh 2/minute IP quota."""
import json
import sys
import time

import requests

base = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8081'
report = {'base': base, 'routes': {}, 'token_events': 0}
for attempt in range(40):
    try:
        if requests.get(base + '/healthz', timeout=2).status_code == 200:
            break
    except requests.RequestException:
        pass
    time.sleep(0.25)
else:
    raise AssertionError('HTTP server did not become reachable')
for path in ['/', '/student/', '/teacher/', '/healthz', '/readyz']:
    response = requests.get(base + path, timeout=180)
    assert response.status_code == 200, (path, response.status_code)
    report['routes'][path] = response.status_code
started = time.monotonic()
times, parts, done = [], [], False
with requests.post(base + '/student/api/ask/stream', json={'question': '请简要说明儿童早餐为什么要搭配牛奶和鸡蛋。'}, stream=True, timeout=150) as response:
    assert response.status_code == 200
    assert response.headers['Content-Type'].startswith('text/event-stream')
    response.encoding = 'utf-8'
    name = ''
    for line in response.iter_lines(chunk_size=1, decode_unicode=True):
        if line.startswith('event: '):
            name = line[7:]
        elif line.startswith('data: '):
            data = json.loads(line[6:])
            if name == 'token':
                times.append(time.monotonic() - started)
                parts.append(data['text'])
            elif name == 'done':
                assert data['ok'] and len(data['answer']) > 50
                done = True
            elif name == 'error':
                raise AssertionError(data)
assert done and len(parts) > 3 and times[-1] > times[0] + 0.1
report.update(token_events=len(parts), first_token_seconds=round(times[0], 3),
              last_token_seconds=round(times[-1], 3), received_chars=len(''.join(parts)))
response = requests.post(base + '/teacher/api/ask', json={'question': '你好'}, timeout=15)
assert response.status_code == 200 and response.json()['ok']
response = requests.post(base + '/teacher/api/ask', json={'question': '你好'}, headers={'X-Forwarded-For': '203.0.113.99'}, timeout=15)
assert response.status_code == 429, response.status_code
assert response.json()['ok'] is False and 'Retry-After' in response.headers
report['rate_limit'] = {'status': response.status_code, 'retry_after': response.headers['Retry-After'], 'spoofed_xff_cannot_bypass': True}
assert requests.get(base + '/healthz', timeout=10).status_code == 200
print(json.dumps(report, ensure_ascii=False, indent=2))
