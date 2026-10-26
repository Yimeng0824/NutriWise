"""Stage 1: real CPU embedding + real configured LLM, without a web server."""
import json
import time

from config import Settings
from engine import RagEngine

settings = Settings.from_env()
assert settings.embedding_device == 'cpu'
engine = RagEngine(settings)
started = time.monotonic()
engine.ready()
device = str(engine.embedding.client.device)
assert device == 'cpu', device
report = {'device': device, 'provider': settings.llm_provider, 'checks': []}
for role, query in [('student', '小学生早餐为什么需要牛奶和鸡蛋？'),
                    ('teacher', '请说明儿童早餐中优质蛋白质的作用及教学建议。')]:
    mark = time.monotonic()
    result = engine.ask(role, query)
    assert result['ok'] and len(result['answer']) > 100
    report['checks'].append({'role': role, 'answer_chars': len(result['answer']),
                             'seconds': round(time.monotonic() - mark, 2)})
report.update(model_loads=engine.load_count, total_seconds=round(time.monotonic() - started, 2))
assert engine.load_count == 1
print(json.dumps(report, ensure_ascii=False, indent=2))
