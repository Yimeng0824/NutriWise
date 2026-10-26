"""Runtime configuration. Secrets come only from environment variables."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    embedding_device: str = 'cpu'
    embedding_model: str = 'BAAI/bge-large-zh'
    embedding_revision: str = 'b5d9f5c027e87b6f0b6fa4b614f8f9cdc45ce0e8'
    vector_dir: str = str(ROOT / 'vector_store')
    llm_provider: str = 'deepseek'
    deepseek_api_key: str = field(default='', repr=False)
    deepseek_base_url: str = 'https://api.deepseek.com'
    deepseek_model: str = 'deepseek-flash'
    ollama_base_url: str = 'http://127.0.0.1:11434'
    ollama_model: str = 'qwen3:32b'
    ollama_api_key: str = field(default='', repr=False)
    ollama_think: bool = False
    ollama_num_threads: int = 2
    ollama_context_length: int = 4096
    pubmed_api_key: str = field(default='', repr=False)
    llm_timeout: int = 120
    max_tokens: int = 1600
    cpu_threads: int = 2
    max_concurrent: int = 2
    ask_limit: str = '10/minute;100/day'
    rate_storage_uri: str = field(default='memory://', repr=False)
    proxy_hops: int = 0
    heartbeat_seconds: int = 10

    @classmethod
    def from_env(cls, load_file=True):
        if load_file:
            load_dotenv(ROOT / '.env', override=False)
        defaults = cls()
        values = {}
        for name in cls.__dataclass_fields__:
            value = os.environ.get(name.upper(), getattr(defaults, name))
            if isinstance(getattr(defaults, name), bool):
                if str(value).lower() not in ('true', 'false', '1', '0'):
                    raise ValueError(f'{name.upper()} must be true or false')
                values[name] = str(value).lower() in ('true', '1')
            else:
                values[name] = int(value) if isinstance(getattr(defaults, name), int) else value
        result = cls(**values)
        if result.llm_provider not in ('deepseek', 'ollama'):
            raise ValueError('LLM_PROVIDER must be deepseek or ollama')
        if result.llm_provider == 'deepseek' and not result.deepseek_api_key.strip():
            raise ValueError('DEEPSEEK_API_KEY is required for DeepSeek')
        if result.proxy_hops not in (0, 1):
            raise ValueError('PROXY_HOPS must be 0 or 1 for an isolated Caddy upstream')
        for name in ('llm_timeout', 'max_tokens', 'cpu_threads', 'max_concurrent', 'heartbeat_seconds',
                     'ollama_num_threads', 'ollama_context_length'):
            if getattr(result, name) <= 0:
                raise ValueError(f'{name.upper()} must be positive')
        return result
