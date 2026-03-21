"""Tag store — hierarchical tagging with confidence scoring."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
from typing import Any, Optional
import uuid

from .db import Database
from .models import slugify


class TagStore:
    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        name: str,
        parent_id: Optional[str] = None,
        description: Optional[str] = None,
        color: Optional[str] = None,
        tag_type: str = "topic",
    ) -> dict[str, Any]:
        tag_id = str(uuid.uuid4())
        slug = slugify(name)
        now = datetime.now(UTC).isoformat()
        with closing(self.db.connect()) as conn:
            conn.execute(
                "INSERT INTO tags (id, name, slug, parent_id, description, color, tag_type, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (tag_id, name, slug, parent_id, description, color, tag_type, now),
            )
            conn.commit()
        return {
            "id": tag_id, "name": name, "slug": slug, "parent_id": parent_id,
            "description": description, "color": color, "tag_type": tag_type,
            "created_at": now,
        }

    def create_project(
        self, name: str, description: Optional[str] = None
    ) -> dict[str, Any]:
        """Create a project tag."""
        return self.create(name, description=description, tag_type="project")

    def get(self, tag_id: str) -> Optional[dict[str, Any]]:
        with closing(self.db.connect()) as conn:
            row = conn.execute(
                "SELECT * FROM tags WHERE id = ?", (tag_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_by_slug(self, slug: str) -> Optional[dict[str, Any]]:
        with closing(self.db.connect()) as conn:
            row = conn.execute(
                "SELECT * FROM tags WHERE slug = ?", (slug,)
            ).fetchone()
        return dict(row) if row else None

    def get_or_create(self, name: str, **kwargs) -> dict[str, Any]:
        slug = slugify(name)
        existing = self.get_by_slug(slug)
        if existing:
            return existing
        return self.create(name, **kwargs)

    def list(
        self,
        parent_id: Optional[str] = ...,
        tag_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        with closing(self.db.connect()) as conn:
            if parent_id is ... and tag_type is None:
                rows = conn.execute(
                    "SELECT * FROM tags ORDER BY name"
                ).fetchall()
            elif parent_id is ... and tag_type is not None:
                rows = conn.execute(
                    "SELECT * FROM tags WHERE tag_type = ? ORDER BY name",
                    (tag_type,),
                ).fetchall()
            elif parent_id is None and tag_type is None:
                rows = conn.execute(
                    "SELECT * FROM tags WHERE parent_id IS NULL ORDER BY name"
                ).fetchall()
            elif parent_id is None and tag_type is not None:
                rows = conn.execute(
                    "SELECT * FROM tags WHERE parent_id IS NULL AND tag_type = ? ORDER BY name",
                    (tag_type,),
                ).fetchall()
            elif tag_type is not None:
                rows = conn.execute(
                    "SELECT * FROM tags WHERE parent_id = ? AND tag_type = ? ORDER BY name",
                    (parent_id, tag_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tags WHERE parent_id = ? ORDER BY name",
                    (parent_id,),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_projects(self) -> list[dict[str, Any]]:
        """List all project tags."""
        return self.list(tag_type="project")

    def list_topics(self) -> list[dict[str, Any]]:
        """List all topic tags."""
        return self.list(tag_type="topic")

    def tag_document(
        self,
        document_id: str,
        tag_id: str,
        confidence: float = 1.0,
        source: str = "user",
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with closing(self.db.connect()) as conn:
            conn.execute(
                """
                INSERT INTO document_tags (document_id, tag_id, confidence, source, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (document_id, tag_id) DO UPDATE SET
                    confidence = excluded.confidence, source = excluded.source
                """,
                (document_id, tag_id, confidence, source, now),
            )
            conn.commit()

    def untag_document(self, document_id: str, tag_id: str) -> None:
        with closing(self.db.connect()) as conn:
            conn.execute(
                "DELETE FROM document_tags WHERE document_id = ? AND tag_id = ?",
                (document_id, tag_id),
            )
            conn.commit()

    def get_document_tags(self, document_id: str) -> list[dict[str, Any]]:
        with closing(self.db.connect()) as conn:
            rows = conn.execute(
                """
                SELECT t.*, dt.confidence, dt.source
                FROM tags t
                JOIN document_tags dt ON dt.tag_id = t.id
                WHERE dt.document_id = ?
                ORDER BY t.name
                """,
                (document_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_tagged_documents(
        self, tag_id: str, recursive: bool = False
    ) -> list[str]:
        tag_ids = [tag_id]
        if recursive:
            tag_ids = self._collect_descendant_ids(tag_id)
        placeholders = ",".join("?" for _ in tag_ids)
        with closing(self.db.connect()) as conn:
            rows = conn.execute(
                f"SELECT DISTINCT document_id FROM document_tags WHERE tag_id IN ({placeholders})",
                tag_ids,
            ).fetchall()
        return [row[0] for row in rows]

    def get_documents_with_all_tags(self, tag_ids: list[str]) -> list[str]:
        """Return document IDs that have *all* of the given tags (AND query)."""
        if not tag_ids:
            return []
        placeholders = ",".join("?" for _ in tag_ids)
        with closing(self.db.connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT document_id FROM document_tags
                WHERE tag_id IN ({placeholders})
                GROUP BY document_id
                HAVING COUNT(DISTINCT tag_id) = ?
                """,
                [*tag_ids, len(tag_ids)],
            ).fetchall()
        return [row[0] for row in rows]

    def search_by_tags(
        self, tag_names: list[str], match_all: bool = True
    ) -> list[str]:
        """Return document IDs matching tags by name. AND if *match_all*, else OR."""
        tag_ids = []
        for name in tag_names:
            tag = self.get_by_slug(slugify(name))
            if tag:
                tag_ids.append(tag["id"])
        if not tag_ids:
            return []
        if match_all:
            return self.get_documents_with_all_tags(tag_ids)
        # OR query
        placeholders = ",".join("?" for _ in tag_ids)
        with closing(self.db.connect()) as conn:
            rows = conn.execute(
                f"SELECT DISTINCT document_id FROM document_tags WHERE tag_id IN ({placeholders})",
                tag_ids,
            ).fetchall()
        return [row[0] for row in rows]

    def _collect_descendant_ids(self, tag_id: str) -> list[str]:
        result = [tag_id]
        with closing(self.db.connect()) as conn:
            children = conn.execute(
                "SELECT id FROM tags WHERE parent_id = ?", (tag_id,)
            ).fetchall()
        for child in children:
            result.extend(self._collect_descendant_ids(child[0]))
        return result
