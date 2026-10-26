"""Shared BGE/FAISS runtime with the original retrieval and role prompts."""
import hashlib
import json
import threading
from pathlib import Path

from prompts import PROMPTS, GREETINGS, WELCOME, EMPTY, format_answer
from providers import make_provider


def weighted_retrieve(store, query, k=8):
    docs = store.similarity_search(query, k=k * 2)
    words = [d for d in docs if d.metadata.get('doc_type') == 'word_document'][:4]
    others = [d for d in docs if d.metadata.get('doc_type') != 'word_document']
    return words + others[:k - len(words)]


class RagEngine:
    def __init__(self, settings, store_loader=None, provider=None):
        self.settings = settings
        self.provider = provider or make_provider(settings)
        self._loader = store_loader or self._load_store
        self._store = None
        self._load_lock = threading.Lock()
        self._search_lock = threading.Lock()
        self.embedding = None
        self.load_count = 0

    def _load_store(self):
        import torch
        from langchain_community.embeddings import HuggingFaceBgeEmbeddings
        from langchain_community.vectorstores import FAISS

        folder = Path(self.settings.vector_dir)
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        for filename, expected in manifest['sha256'].items():
            if hashlib.sha256((folder / filename).read_bytes()).hexdigest() != expected:
                raise ValueError('Packaged index checksum mismatch')
        if manifest['model'] != 'BAAI/bge-large-zh' or not manifest['normalize_embeddings']:
            raise ValueError('Index embedding contract mismatch')
        if not Path(self.settings.embedding_model).is_dir() and self.settings.embedding_model != manifest['model']:
            raise ValueError('Changing the embedding model requires rebuilding the index')
        torch.set_num_threads(self.settings.cpu_threads)
        self.embedding = HuggingFaceBgeEmbeddings(
            model_name=self.settings.embedding_model,
            model_kwargs={'device': self.settings.embedding_device,
                          'revision': self.settings.embedding_revision},
            encode_kwargs={'normalize_embeddings': True})
        # Pinned old loader: unpickle only our hash-checked, packaged index.
        store = FAISS.load_local(str(folder), self.embedding)
        if store.index.d != manifest['dimension']:
            raise ValueError('FAISS dimension mismatch')
        return store

    def ready(self):
        with self._load_lock:
            if self._store is None:
                self._store = self._loader()
                self.load_count += 1
        return self._store

    def prepare(self, role, query):
        if len(query) <= 10 and any(g in query.lower() for g in GREETINGS[role]):
            return WELCOME[role], None
        with self._search_lock:
            docs = weighted_retrieve(self.ready(), query)
        if not docs:
            return EMPTY[role], None
        context = ''
        for doc in docs[:5]:
            title, pmid = doc.metadata.get('title', ''), doc.metadata.get('pmid')
            doc_id = f'学术文献 - PMID: {pmid}' if pmid else f'科普文章 - {title[:50]}...'
            context += f'【{doc_id}】\n标题: {title}\n内容: {doc.page_content}\n\n'
        return None, PROMPTS[role].format(context=context, question=query)

    @staticmethod
    def result(answer):
        # Preserve the API contract; retrieved passages are not verified citations.
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError('LLM returned no answer content')
        return {'ok': True, 'answer': answer, 'sources': []}

    def ask(self, role, query):
        shortcut, prompt = self.prepare(role, query)
        answer = shortcut if prompt is None else format_answer(role, self.provider.invoke(prompt, role))
        return self.result(answer)

    def stream(self, role, query, cancelled=None):
        shortcut, prompt = self.prepare(role, query)
        if cancelled is not None and cancelled.is_set():
            return
        if prompt is None:
            yield 'token', {'text': shortcut}
            yield 'done', self.result(shortcut)
            return
        parts = []
        stream = self.provider.stream(prompt, role, cancelled=cancelled)
        try:
            for token in stream:
                parts.append(token)
                yield 'token', {'text': token}
        finally:
            stream.close()
        yield 'done', self.result(format_answer(role, ''.join(parts)))
