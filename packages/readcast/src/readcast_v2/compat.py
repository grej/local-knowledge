"""Bidirectional mapping between readcast's Article and localknowledge's Document."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from localknowledge.models import Document

# Readcast-specific fields that live in Document.metadata
_METADATA_FIELDS = (
    "author", "publication", "published_date", "word_count",
    "estimated_read_min", "description", "image_url", "site_name",
    "voice", "tts_model", "speed", "audio_duration_sec",
    "listened_at", "listen_count", "listened_complete",
    "last_digested_at", "digest_status", "error_message", "source_file",
)

_STATUS_TO_INGEST = {
    "queued": "raw",
    "synthesizing": "processed",
    "done": "indexed",
    "error": "error",
}

_INGEST_TO_STATUS = {v: k for k, v in _STATUS_TO_INGEST.items()}


@dataclass(slots=True)
class Article:
    """Readcast v1 Article representation for adapter layer."""

    id: str
    source_url: Optional[str]
    source_file: Optional[str]
    title: str
    author: Optional[str]
    publication: Optional[str]
    published_date: Optional[str]
    ingested_at: str
    word_count: int
    estimated_read_min: int
    description: Optional[str] = None
    image_url: Optional[str] = None
    canonical_url: Optional[str] = None
    site_name: Optional[str] = None
    language: str = "en"
    status: str = "queued"
    error_message: Optional[str] = None
    audio_duration_sec: Optional[float] = None
    voice: Optional[str] = None
    tts_model: Optional[str] = None
    speed: Optional[float] = None
    tags: list[str] = field(default_factory=list)
    listened_at: Optional[str] = None
    listen_count: int = 0
    listened_complete: int = 0
    last_digested_at: Optional[str] = None
    digest_status: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Article:
        payload = dict(data)
        payload["tags"] = list(payload.get("tags") or [])
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in payload.items() if k in known})


def article_to_document(article: Article) -> Document:
    """Convert a readcast Article to a core Document.

    Readcast-specific fields are stored in Document.metadata.
    """
    metadata: dict[str, Any] = {}
    for field_name in _METADATA_FIELDS:
        value = getattr(article, field_name, None)
        if value is not None:
            metadata[field_name] = value
    if article.tags:
        metadata["tags"] = article.tags

    return Document(
        id=article.id,
        title=article.title,
        source_type="article",
        source_product="readcast",
        created_at=article.ingested_at,
        updated_at=article.ingested_at,
        content_type="text/plain",
        language=article.language,
        source_uri=article.source_url,
        canonical_uri=article.canonical_url,
        ingest_status=_STATUS_TO_INGEST.get(article.status, "raw"),
        metadata=metadata,
    )


def document_to_article(doc: Document) -> Article:
    """Convert a core Document back to a readcast Article."""
    meta = doc.metadata or {}

    return Article(
        id=doc.id,
        source_url=doc.source_uri,
        source_file=meta.get("source_file"),
        title=doc.title,
        author=meta.get("author"),
        publication=meta.get("publication"),
        published_date=meta.get("published_date"),
        ingested_at=doc.created_at,
        word_count=meta.get("word_count", 0),
        estimated_read_min=meta.get("estimated_read_min", 0),
        description=meta.get("description"),
        image_url=meta.get("image_url"),
        canonical_url=doc.canonical_uri,
        site_name=meta.get("site_name"),
        language=doc.language or "en",
        status=_INGEST_TO_STATUS.get(doc.ingest_status, "queued"),
        error_message=meta.get("error_message"),
        audio_duration_sec=meta.get("audio_duration_sec"),
        voice=meta.get("voice"),
        tts_model=meta.get("tts_model"),
        speed=meta.get("speed"),
        tags=meta.get("tags", []),
        listened_at=meta.get("listened_at"),
        listen_count=meta.get("listen_count", 0),
        listened_complete=meta.get("listened_complete", 0),
        last_digested_at=meta.get("last_digested_at"),
        digest_status=meta.get("digest_status"),
    )
