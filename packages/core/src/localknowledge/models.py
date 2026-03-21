"""Core data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
import unicodedata
from typing import Any, Optional


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    normalized = (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    )
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized.strip("-")


@dataclass(slots=True)
class Document:
    id: str
    title: str
    source_type: str
    source_product: str
    created_at: str
    updated_at: str
    content: Optional[str] = None
    summary: Optional[str] = None
    content_type: str = "text/plain"
    language: Optional[str] = None
    source_uri: Optional[str] = None
    canonical_uri: Optional[str] = None
    parent_document_id: Optional[str] = None
    content_hash: Optional[str] = None
    ingest_status: str = "raw"
    metadata: Optional[dict[str, Any]] = None
    deleted_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Document:
        payload = dict(data)
        meta = payload.get("metadata")
        if isinstance(meta, str):
            payload["metadata"] = json.loads(meta) if meta else None
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in payload.items() if k in known})

    @classmethod
    def from_row(cls, row) -> Document:
        return cls.from_dict(dict(row))


@dataclass(slots=True)
class SearchResult:
    document: Document
    score: float
    source: str  # "fts", "semantic", "hybrid"


@dataclass(slots=True)
class ChunkResult:
    document_id: str
    chunk_text: str
    chunk_index: int
    chunk_start: int
    chunk_end: int
    score: float
