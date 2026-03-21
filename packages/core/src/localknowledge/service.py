"""KnowledgeService — shared business logic for CLI, API, and thick client."""

from __future__ import annotations

import hashlib
import logging
from contextlib import closing
from pathlib import Path
from typing import Optional

from .artifacts import ArtifactStore
from .autotag import AutoTagger, TagSuggestion
from .centroids import CentroidStore
from .config import Config
from .db import Database
from .documents import DocumentStore
from .embeddings.dense import DenseBackend
from .embeddings.hybrid import HybridSearch
from .models import ChunkResult, Document, SearchResult
from .tags import TagStore

log = logging.getLogger(__name__)


class KnowledgeService:
    """Facade over all core stores. Both CLI and future API use this."""

    def __init__(
        self,
        base_dir: Path | None = None,
        embed_fn=None,
    ):
        self.config = Config.load(base_dir)
        self.db = Database(self.config.base_dir)
        self.docs = DocumentStore(self.db)
        self.artifacts = ArtifactStore(self.db)
        self.tags = TagStore(self.db)
        self.dense = DenseBackend(
            self.db,
            model_name=self.config.embeddings.model,
            embed_fn=embed_fn,
        )
        self.hybrid = HybridSearch(self.docs, self.dense)
        self.centroids = CentroidStore(self.db, self.dense)
        self.autotagger = AutoTagger(self.db, self.tags, self.dense, self.centroids)

    # -- Document operations ---------------------------------------------------

    def add_text(
        self,
        text: str,
        title: str | None = None,
        source_type: str = "note",
        source_product: str = "lk",
        source_uri: str | None = None,
        metadata: dict | None = None,
        source_conversation: str | None = None,
        parent_document_id: str | None = None,
    ) -> Document:
        if not title:
            title = _derive_title(text)

        # Merge provenance into metadata
        meta = dict(metadata) if metadata else {}
        if source_conversation:
            meta["source_conversation"] = source_conversation

        doc = self.docs.create(
            title=title,
            source_type=source_type,
            source_product=source_product,
            content=text,
            source_uri=source_uri,
            metadata=meta or None,
            parent_document_id=parent_document_id,
        )
        if self.config.embeddings.auto_embed:
            try:
                self.dense.embed_document_chunked(doc.id, text)
            except Exception as exc:
                log.warning("Auto-embed failed for %s: %s", doc.id, exc)
            else:
                # Auto-tag after successful embedding
                if self.config.embeddings.auto_tag:
                    try:
                        self.autotagger.auto_tag(doc.id)
                    except Exception as exc:
                        log.warning("Auto-tag failed for %s: %s", doc.id, exc)
        return doc

    def add_file(self, path: Path) -> Document:
        text = path.read_text(encoding="utf-8")
        title = path.stem.replace("-", " ").replace("_", " ").title()
        return self.add_text(
            text, title=title, source_type="note", source_uri=f"file://{path}"
        )

    def get_document(self, doc_id: str) -> Document | None:
        return self.docs.get(doc_id)

    def list_documents(
        self, source_type: str | None = None, source_product: str | None = None, limit: int = 50
    ) -> list[Document]:
        return self.docs.list(source_type=source_type, source_product=source_product, limit=limit)

    def delete_document(self, doc_id: str) -> bool:
        return self.docs.delete(doc_id)

    # -- Search ----------------------------------------------------------------

    def search(
        self, query: str, mode: str = "hybrid", limit: int = 20
    ) -> list[SearchResult]:
        if mode == "fts":
            results = self.docs.search_with_scores(query, limit=limit)
            return [
                SearchResult(document=doc, score=score, source="fts")
                for doc, score in results
            ]
        if mode == "semantic":
            results = self.dense.find_similar_by_text(query, top_k=limit)
            out = []
            for doc_id, score in results:
                doc = self.docs.get(doc_id)
                if doc:
                    out.append(SearchResult(document=doc, score=score, source="semantic"))
            return out
        # hybrid (default)
        return self.hybrid.search_with_scores(query, limit=limit)

    def search_chunks(self, query: str, limit: int = 20) -> list[ChunkResult]:
        """Chunk-level semantic search."""
        return self.dense.find_similar_chunks(query, top_k=limit)

    def search_by_tags(
        self, tag_names: list[str], match_all: bool = True
    ) -> list[Document]:
        """Find documents matching tags."""
        doc_ids = self.tags.search_by_tags(tag_names, match_all=match_all)
        docs = []
        for doc_id in doc_ids:
            doc = self.docs.get(doc_id)
            if doc:
                docs.append(doc)
        return docs

    # -- Tags ------------------------------------------------------------------

    def list_tags(self) -> list[dict]:
        return self.tags.list()

    def tag_document(self, doc_id: str, tag_name: str) -> dict:
        tag = self.tags.get_or_create(tag_name)
        self.tags.tag_document(doc_id, tag["id"])
        return tag

    def get_document_tags(self, doc_id: str) -> list[dict]:
        return self.tags.get_document_tags(doc_id)

    # -- Projects --------------------------------------------------------------

    def create_project(
        self, name: str, description: str | None = None
    ) -> dict:
        """Create a project tag."""
        return self.tags.create_project(name, description=description)

    def list_projects(self) -> list[dict]:
        """List all projects with doc_count per project."""
        projects = self.tags.list_projects()
        for p in projects:
            doc_ids = self.tags.get_tagged_documents(p["id"])
            p["doc_count"] = len(doc_ids)
        return projects

    def get_project_documents(
        self, project_slug: str, limit: int = 50
    ) -> list[Document]:
        """Get documents belonging to a project."""
        tag = self.tags.get_by_slug(project_slug)
        if not tag:
            return []
        doc_ids = self.tags.get_tagged_documents(tag["id"])
        docs = []
        for doc_id in doc_ids[:limit]:
            doc = self.docs.get(doc_id)
            if doc:
                docs.append(doc)
        return docs

    def get_project_topics(self, project_slug: str) -> list[dict]:
        """Get topic tags co-occurring with project documents."""
        tag = self.tags.get_by_slug(project_slug)
        if not tag:
            return []
        doc_ids = set(self.tags.get_tagged_documents(tag["id"]))
        if not doc_ids:
            return []

        # Find all topic tags on these documents
        topic_counts: dict[str, dict] = {}
        for doc_id in doc_ids:
            doc_tags = self.tags.get_document_tags(doc_id)
            for dt in doc_tags:
                if dt.get("tag_type") == "topic":
                    tid = dt["id"]
                    if tid not in topic_counts:
                        topic_counts[tid] = {
                            "id": tid,
                            "name": dt["name"],
                            "slug": dt["slug"],
                            "doc_count": 0,
                        }
                    topic_counts[tid]["doc_count"] += 1

        return sorted(topic_counts.values(), key=lambda t: t["doc_count"], reverse=True)

    # -- Auto-tagging ----------------------------------------------------------

    def suggest_topics(self, doc_id: str) -> list[TagSuggestion]:
        return self.autotagger.suggest_topics(doc_id)

    def suggest_projects(self, doc_id: str) -> list[TagSuggestion]:
        return self.autotagger.suggest_projects(doc_id)

    def auto_tag(self, doc_id: str) -> list[TagSuggestion]:
        return self.autotagger.auto_tag(doc_id)

    def refresh_project_centroid(self, project_slug: str) -> bool:
        tag = self.tags.get_by_slug(project_slug)
        if not tag or tag.get("tag_type") != "project":
            return False
        return self.centroids.update_centroid(tag["id"])

    def refresh_all_centroids(self) -> int:
        return self.centroids.update_all_centroids()

    # -- Embeddings ------------------------------------------------------------

    def embed_document(self, doc_id: str) -> bool:
        doc = self.docs.get(doc_id)
        if not doc or not doc.content:
            return False
        self.dense.embed_document_chunked(doc_id, doc.content)
        return True

    def embed_all(self) -> int:
        unembedded = self.docs.list_unembedded()
        count = 0
        for doc in unembedded:
            try:
                self.dense.embed_document_chunked(doc.id, doc.content)
                count += 1
            except Exception as exc:
                log.warning("Failed to embed %s: %s", doc.id, exc)
        return count

    def embedding_stats(self) -> dict:
        all_docs = self.docs.list(limit=100000)
        unembedded = self.docs.list_unembedded()
        return {
            "total": len(all_docs),
            "embedded": len(all_docs) - len(unembedded),
            "unembedded": len(unembedded),
        }

    # -- Config ----------------------------------------------------------------

    def get_config(self) -> dict:
        return {
            "base_dir": str(self.config.base_dir),
            "database": {"path": self.config.database.path},
            "embeddings": {
                "model": self.config.embeddings.model,
                "dimensions": self.config.embeddings.dimensions,
                "auto_embed": self.config.embeddings.auto_embed,
                "auto_tag": self.config.embeddings.auto_tag,
            },
            "tts": {"voice": self.config.tts.voice, "model": self.config.tts.model},
            "llm": {"provider": self.config.llm.provider, "model": self.config.llm.local_model},
        }

    def set_config(self, key: str, value: str) -> None:
        self.config.set_value(key, value)


def _derive_title(text: str, limit: int = 80) -> str:
    """Derive a title from the first line of text."""
    first_line = text.strip().split("\n", 1)[0].strip()
    # Strip markdown heading prefix
    if first_line.startswith("#"):
        first_line = first_line.lstrip("#").strip()
    if len(first_line) > limit:
        first_line = first_line[:limit].rsplit(" ", 1)[0] + "..."
    return first_line or "Untitled"
