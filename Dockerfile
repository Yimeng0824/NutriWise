FROM python:3.10-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-web.txt requirements-ml.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install pip==25.3 \
    && pip install --no-deps torch==2.11.0+cpu --index-url https://download.pytorch.org/whl/cpu
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-web.txt -r requirements-ml.txt \
    && python -c "import torch; assert torch.version.cuda is None" \
    && pip check
ARG HF_ENDPOINT=https://huggingface.co
ARG BGE_REVISION=b5d9f5c027e87b6f0b6fa4b614f8f9cdc45ce0e8
RUN --mount=type=cache,target=/root/.cache/huggingface \
    HF_ENDPOINT=${HF_ENDPOINT} python -c "import shutil; from huggingface_hub import snapshot_download; p=snapshot_download('BAAI/bge-large-zh', revision='${BGE_REVISION}', allow_patterns=['*.json','*.txt','*.safetensors','1_Pooling/*']); shutil.copytree(p, '/opt/models/bge-large-zh')"
COPY config.py providers.py engine.py prompts.py serve.py wsgi.py gunicorn.conf.py ./
COPY templates ./templates
COPY static ./static
COPY vector_store ./vector_store
RUN useradd --create-home --uid 10001 appuser
ENV EMBEDDING_DEVICE=cpu EMBEDDING_MODEL=/opt/models/bge-large-zh \
    EMBEDDING_REVISION=${BGE_REVISION} VECTOR_DIR=/app/vector_store \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)"
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
