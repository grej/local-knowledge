"""Dense embedding backend — chunk-aware with numpy cosine search."""

from __future__ import annotations

import logging
import struct
from contextlib import closing
from datetime import UTC, datetime

import numpy as np

from ..chunker import Chunk, chunk_text
from ..db import Database
from ..models import ChunkResult
from .base import EmbeddingBackend

log = logging.getLogger(__name__)

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

TABLE = "embeddings_dense_v2"

# Keyed by model_name → (model, tokenizer)
_model_cache: dict[str, tuple[object, object]] = {}


def embedding_to_bytes(embedding: list[float]) -> bytes:
    """Convert a list of floats to a compact bytes blob (float32)."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def embedding_from_bytes(data: bytes) -> list[float]:
    """Convert a bytes blob back to a list of floats."""
    count = len(data) // 4
    return list(struct.unpack(f"{count}f", data))


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot = float(np.dot(a, b))
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _load_model(model_name: str = DEFAULT_MODEL):
    """Lazy-load the embedding model, keyed by model_name."""
    if model_name not in _model_cache:
        from mlx_embeddings.utils import load

        model, tokenizer = load(model_name)
        _model_cache[model_name] = (model, tokenizer)
    return _model_cache[model_name]


def _embed_texts(texts: list[str], model_name: str = DEFAULT_MODEL) -> list[list[float]]:
    """Embed a batch of texts, returning normalized vectors."""
    import mlx.core as mx
    from mlx_embeddings.utils import generate

    model, tokenizer = _load_model(model_name)
    result = generate(model, tokenizer, texts)
    embeddings = result.text_embeds
    norms = mx.sqrt(mx.sum(embeddings * embeddings, axis=1, keepdims=True))
    norms = mx.maximum(norms, 1e-12)
    embeddings = embeddings / norms
    return embeddings.tolist()


def get_embedding_dim(model_name: str = DEFAULT_MODEL) -> int:
    """Discover the embedding dimension for a model by running a probe."""
    vecs = _embed_texts(["probe"], model_name=model_name)
    return len(vecs[0])


class DenseBackend(EmbeddingBackend):
    name = "dense"

    def __init__(self, db: Database, model_name: str = DEFAULT_MODEL, embed_fn=None):
        self.db = db
        self.model_name = model_name
        self._embed_fn = embed_fn or (lambda texts: _embed_texts(texts, model_name))

    # -- Embed -----------------------------------------------------------------

    def embed_document(self, doc_id: str, content: str, metadata: dict | None = None) -> None:
        """Backward-compatible: embed as a single chunk (chunk_index=0)."""
        vectors = self._embed_fn([content])
        embedding_bytes = embedding_to_bytes(vectors[0])
        now = datetime.now(UTC).isoformat()
        with closing(self.db.connect()) as conn:
            conn.execute(f"DELETE FROM {TABLE} WHERE document_id = ?", (doc_id,))
            conn.execute(
                f"""
                INSERT INTO {TABLE}
                    (document_id, chunk_index, chunk_text, embedding, model, created_at)
                VALUES (?, 0, ?, ?, ?, ?)
                """,
                (doc_id, content, embedding_bytes, self.model_name, now),
            )
            conn.commit()

    def embed_document_chunked(
        self, doc_id: str, content: str, chunks: list[Chunk] | None = None
    ) -> None:
        """Embed a document as multiple chunks."""
        if chunks is None:
            chunks = chunk_text(content)
        if not chunks:
            self.embed_document(doc_id, content)
            return

        texts = [c.text for c in chunks]
        vectors = self._embed_fn(texts)
        now = datetime.now(UTC).isoformat()

        with closing(self.db.connect()) as conn:
            conn.execute(f"DELETE FROM {TABLE} WHERE document_id = ?", (doc_id,))
            for chunk, vec in zip(chunks, vectors):
                conn.execute(
                    f"""
                    INSERT INTO {TABLE}
                        (document_id, chunk_index, chunk_text, chunk_start, chunk_end,
                         embedding, model, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id, chunk.index, chunk.text, chunk.start, chunk.end,
                        embedding_to_bytes(vec), self.model_name, now,
                    ),
                )
            conn.commit()

    # -- Search ----------------------------------------------------------------

    def find_similar(self, doc_id: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Find similar documents by ID. Scores per-chunk, aggregates max per document."""
        with closing(self.db.connect()) as conn:
            ref_rows = conn.execute(
                f"SELECT embedding FROM {TABLE} WHERE document_id = ?",
                (doc_id,),
            ).fetchall()
            if not ref_rows:
                return []
            ref_vecs = [np.array(embedding_from_bytes(r[0])) for r in ref_rows]

            rows = conn.execute(
                f"SELECT document_id, embedding FROM {TABLE} WHERE document_id != ? AND model = ?",
                (doc_id, self.model_name),
            ).fetchall()

        doc_scores: dict[str, float] = {}
        for row in rows:
            vec = np.array(embedding_from_bytes(row[1]))
            best = max(cosine_similarity(ref_vec, vec) for ref_vec in ref_vecs)
            did = row[0]
            if did not in doc_scores or best > doc_scores[did]:
                doc_scores[did] = best

        results = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def find_similar_by_text(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Find similar documents by query. Scores per-chunk, returns max per document."""
        vectors = self._embed_fn([query])
        query_vec = np.array(vectors[0])
        with closing(self.db.connect()) as conn:
            rows = conn.execute(
                f"SELECT document_id, embedding FROM {TABLE} WHERE model = ?",
                (self.model_name,),
            ).fetchall()

        doc_scores: dict[str, float] = {}
        for row in rows:
            vec = np.array(embedding_from_bytes(row[1]))
            score = cosine_similarity(query_vec, vec)
            did = row[0]
            if did not in doc_scores or score > doc_scores[did]:
                doc_scores[did] = score

        results = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def find_similar_chunks(self, query: str, top_k: int = 10) -> list[ChunkResult]:
        """Find similar chunks by query text. Returns chunk-level results."""
        vectors = self._embed_fn([query])
        query_vec = np.array(vectors[0])
        with closing(self.db.connect()) as conn:
            rows = conn.execute(
                f"""SELECT document_id, chunk_index, chunk_text,
                       chunk_start, chunk_end, embedding
                FROM {TABLE} WHERE model = ?""",
                (self.model_name,),
            ).fetchall()

        results = []
        for row in rows:
            vec = np.array(embedding_from_bytes(row[5]))
            score = cosine_similarity(query_vec, vec)
            results.append(ChunkResult(
                document_id=row[0],
                chunk_text=row[2] or "",
                chunk_index=row[1],
                chunk_start=row[3] or 0,
                chunk_end=row[4] or 0,
                score=score,
            ))
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    # -- Remove ----------------------------------------------------------------

    def remove(self, doc_id: str) -> None:
        """Remove all chunks for a document."""
        with closing(self.db.connect()) as conn:
            conn.execute(f"DELETE FROM {TABLE} WHERE document_id = ?", (doc_id,))
            conn.commit()
