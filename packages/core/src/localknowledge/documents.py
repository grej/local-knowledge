"""Document store — CRUD, FTS5 search, and content-hash dedup."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
import hashlib
import json
from typing import Optional
import uuid

from .db import Database
from .models import Document


class DocumentStore:
    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        title: str,
        source_type: str,
        source_product: str,
        *,
        id: Optional[str] = None,
        content: Optional[str] = None,
        summary: Optional[str] = None,
        content_type: str = "text/plain",
        language: Optional[str] = None,
        source_uri: Optional[str] = None,
        canonical_uri: Optional[str] = None,
        parent_document_id: Optional[str] = None,
        content_hash: Optional[str] = None,
        ingest_status: str = "raw",
        metadata: Optional[dict] = None,
    ) -> Document:
        now = datetime.now(UTC).isoformat()
        doc_id = id or str(uuid.uuid4())

        if content and not content_hash:
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        doc = Document(
            id=doc_id,
            title=title,
            source_type=source_type,
            source_product=source_product,
            created_at=now,
            updated_at=now,
            content=content,
            summary=summary,
            content_type=content_type,
            language=language,
            source_uri=source_uri,
            canonical_uri=canonical_uri,
            parent_document_id=parent_document_id,
            content_hash=content_hash,
            ingest_status=ingest_status,
            metadata=metadata,
        )

        with closing(self.db.connect()) as conn:
            conn.execute(
                """
                INSERT INTO documents (
                    id, title, content, summary, content_type, language,
                    source_type, source_uri, canonical_uri, source_product,
                    parent_document_id, content_hash, ingest_status, metadata,
                    created_at, updated_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc.id, doc.title, doc.content, doc.summary, doc.content_type,
                    doc.language, doc.source_type, doc.source_uri, doc.canonical_uri,
                    doc.source_product, doc.parent_document_id, doc.content_hash,
                    doc.ingest_status, json.dumps(doc.metadata) if doc.metadata else None,
                    doc.created_at, doc.updated_at, doc.deleted_at,
                ),
            )
            conn.commit()
        return doc

    def get(self, doc_id: str, include_deleted: bool = False) -> Optional[Document]:
        with closing(self.db.connect()) as conn:
            if include_deleted:
                row = conn.execute(
                    "SELECT * FROM documents WHERE id = ?", (doc_id,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM documents WHERE id = ? AND deleted_at IS NULL",
                    (doc_id,),
                ).fetchone()
        return Document.from_row(row) if row else None

    def list(
        self,
        source_type: Optional[str] = None,
        source_product: Optional[str] = None,
        limit: int = 50,
        include_deleted: bool = False,
    ) -> list[Document]:
        query = "SELECT * FROM documents"
        conditions: list[str] = []
        params: list[object] = []

        if not include_deleted:
            conditions.append("deleted_at IS NULL")
        if source_type:
            conditions.append("source_type = ?")
            params.append(source_type)
        if source_product:
            conditions.append("source_product = ?")
            params.append(source_product)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with closing(self.db.connect()) as conn:
            rows = conn.execute(query, params).fetchall()
        return [Document.from_row(row) for row in rows]

    def update(self, doc: Document) -> None:
        doc.updated_at = datetime.now(UTC).isoformat()
        with closing(self.db.connect()) as conn:
            conn.execute(
                """
                UPDATE documents SET
                    title = ?, content = ?, summary = ?, content_type = ?,
                    language = ?, source_type = ?, source_uri = ?, canonical_uri = ?,
                    source_product = ?, parent_document_id = ?, content_hash = ?,
                    ingest_status = ?, metadata = ?, updated_at = ?, deleted_at = ?
                WHERE id = ?
                """,
                (
                    doc.title, doc.content, doc.summary, doc.content_type,
                    doc.language, doc.source_type, doc.source_uri, doc.canonical_uri,
                    doc.source_product, doc.parent_document_id, doc.content_hash,
                    doc.ingest_status, json.dumps(doc.metadata) if doc.metadata else None,
                    doc.updated_at, doc.deleted_at, doc.id,
                ),
            )
            conn.commit()

    def delete(self, doc_id: str, hard: bool = False) -> bool:
        with closing(self.db.connect()) as conn:
            if hard:
                cursor = conn.execute(
                    "DELETE FROM documents WHERE id = ?", (doc_id,)
                )
            else:
                now = datetime.now(UTC).isoformat()
                cursor = conn.execute(
                    "UPDATE documents SET deleted_at = ?, updated_at = ? "
                    "WHERE id = ? AND deleted_at IS NULL",
                    (now, now, doc_id),
                )
            conn.commit()
        return cursor.rowcount > 0

    def search(self, query: str, limit: int = 20) -> list[Document]:
        with closing(self.db.connect()) as conn:
            rows = conn.execute(
                """
                SELECT d.* FROM documents_fts
                JOIN documents d ON d.rowid = documents_fts.rowid
                WHERE documents_fts MATCH ?
                AND d.deleted_at IS NULL
                ORDER BY documents_fts.rank
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        return [Document.from_row(row) for row in rows]

    def search_with_scores(
        self, query: str, limit: int = 20
    ) -> list[tuple[Document, float]]:
        with closing(self.db.connect()) as conn:
            rows = conn.execute(
                """
                SELECT d.*, documents_fts.rank AS fts_rank
                FROM documents_fts
                JOIN documents d ON d.rowid = documents_fts.rowid
                WHERE documents_fts MATCH ?
                AND d.deleted_at IS NULL
                ORDER BY documents_fts.rank
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            rank = data.pop("fts_rank", 0.0)
            score = -float(rank) if rank else 0.0
            results.append((Document.from_dict(data), score))
        return results

    def list_unembedded(self) -> list[Document]:
        with closing(self.db.connect()) as conn:
            rows = conn.execute(
                """
                SELECT d.* FROM documents d
                LEFT JOIN embeddings_dense_v2 e ON d.id = e.document_id
                WHERE e.document_id IS NULL
                AND d.deleted_at IS NULL
                AND d.content IS NOT NULL
                ORDER BY d.created_at ASC
                """
            ).fetchall()
        return [Document.from_row(row) for row in rows]

    def get_by_content_hash(self, content_hash: str) -> Optional[Document]:
        with closing(self.db.connect()) as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE content_hash = ? AND deleted_at IS NULL",
                (content_hash,),
            ).fetchone()
        return Document.from_row(row) if row else None
