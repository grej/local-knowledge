"""Abstract base class for embedding backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..chunker import Chunk
    from ..models import ChunkResult


class EmbeddingBackend(ABC):
    """Base class for all embedding strategies."""

    name: str

    @abstractmethod
    def embed_document(self, doc_id: str, content: str, metadata: dict | None = None) -> None:
        """Compute and store embedding(s) for a document."""
        ...

    @abstractmethod
    def embed_document_chunked(
        self, doc_id: str, content: str, chunks: list[Chunk] | None = None
    ) -> None:
        """Embed a document as multiple chunks. Auto-chunks if *chunks* is None."""
        ...

    @abstractmethod
    def find_similar(self, doc_id: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Find similar documents by ID. Returns (doc_id, score) pairs."""
        ...

    @abstractmethod
    def find_similar_by_text(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Find similar documents by query text."""
        ...

    @abstractmethod
    def find_similar_chunks(self, query: str, top_k: int = 10) -> list[ChunkResult]:
        """Find similar chunks by query text. Returns chunk-level results."""
        ...

    @abstractmethod
    def remove(self, doc_id: str) -> None:
        """Remove embeddings for a document."""
        ...
