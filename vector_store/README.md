# vector_store/

The production FAISS index is built from a private pediatric-nutrition corpus and is **not** included in this repository.

At runtime the app expects three files here:

| File | Content |
| --- | --- |
| `index.faiss` | FAISS index of 1024-d, L2-normalized `BAAI/bge-large-zh` embeddings |
| `index.pkl` | LangChain docstore (chunk text + metadata such as `doc_type`, `title`, `pmid`) |
| `manifest.json` | `{"model", "revision", "normalize_embeddings", "dimension", "sha256": {file: digest}}` |

On startup the engine verifies the SHA-256 digests, the embedding model and the vector dimension before
unpickling the index, so a mismatched or tampered index is rejected instead of silently loaded.
Documents whose `doc_type` is `word_document` (the expert-written textbook) are given retrieval priority.

To deploy, copy your own three files into this folder before `docker compose build`.
