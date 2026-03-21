"""Hybrid search — Reciprocal Rank Fusion of FTS5 + dense embeddings."""

from __future__ import annotations

import logging
from typing import Optional

from ..documents import DocumentStore
from ..models import Document, SearchResult
from .dense import DenseBackend

log = logging.getLogger(__name__)


class HybridSearch:
    """Combine FTS5 keyword search with dense embedding similarity using RRF."""

    def __init__(
        self,
        document_store: DocumentStore,
        dense_backend: Optional[DenseBackend] = None,
    ):
        self.document_store = document_store
        self.dense_backend = dense_backend

    def search(self, query: str, limit: int = 20, k: int = 60) -> list[Document]:
        """Hybrid search using RRF. Falls back to FTS-only if dense backend unavailable."""
        fts_results = self.document_store.search(query, limit=limit * 2)
        fts_ids = [doc.id for doc in fts_results]

        sem_ids: list[str] = []
        if self.dense_backend is not None:
            try:
                semantic_results = self.dense_backend.find_similar_by_text(
                    query, top_k=limit * 2
                )
                sem_ids = [doc_id for doc_id, _ in semantic_results]
            except Exception as exc:
                log.warning("Dense search failed, using FTS only: %s", exc)

        # RRF fusion
        scores: dict[str, float] = {}
        for rank, doc_id in enumerate(fts_ids, start=1):
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank)
        for rank, doc_id in enumerate(sem_ids, start=1):
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank)

        ranked_ids = sorted(scores, key=lambda did: scores[did], reverse=True)[:limit]

        documents = []
        for doc_id in ranked_ids:
            doc = self.document_store.get(doc_id)
            if doc:
                documents.append(doc)
        return documents

    def search_with_scores(
        self, query: str, limit: int = 20, k: int = 60
    ) -> list[SearchResult]:
        """Hybrid search returning SearchResult with RRF scores."""
        fts_results = self.document_store.search(query, limit=limit * 2)
        fts_ids = [doc.id for doc in fts_results]

        sem_ids: list[str] = []
        if self.dense_backend is not None:
            try:
                semantic_results = self.dense_backend.find_similar_by_text(
                    query, top_k=limit * 2
                )
                sem_ids = [doc_id for doc_id, _ in semantic_results]
            except Exception as exc:
                log.warning("Dense search failed, using FTS only: %s", exc)

        scores: dict[str, float] = {}
        for rank, doc_id in enumerate(fts_ids, start=1):
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank)
        for rank, doc_id in enumerate(sem_ids, start=1):
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank)

        ranked_ids = sorted(scores, key=lambda did: scores[did], reverse=True)[:limit]

        source = "hybrid" if self.dense_backend is not None else "fts"
        results = []
        for doc_id in ranked_ids:
            doc = self.document_store.get(doc_id)
            if doc:
                results.append(SearchResult(document=doc, score=scores[doc_id], source=source))
        return results
