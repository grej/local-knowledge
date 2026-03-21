"""Artifact store — generated outputs (audio, transcripts, images) linked to documents."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
import json
from typing import Any, Optional
import uuid

from .db import Database


class ArtifactStore:
    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        document_id: str,
        artifact_type: str,
        path: Optional[str] = None,
        status: str = "queued",
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        artifact_id = str(uuid.uuid4())
        with closing(self.db.connect()) as conn:
            conn.execute(
                """
                INSERT INTO artifacts (id, document_id, artifact_type, path, status, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id, document_id, artifact_type, path, status,
                    json.dumps(metadata) if metadata else None, now, now,
                ),
            )
            conn.commit()
        return {
            "id": artifact_id, "document_id": document_id,
            "artifact_type": artifact_type, "path": path, "status": status,
            "metadata": metadata, "created_at": now, "updated_at": now,
        }

    def get(self, artifact_id: str) -> Optional[dict[str, Any]]:
        with closing(self.db.connect()) as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_for_document(
        self, document_id: str, artifact_type: Optional[str] = None
    ) -> list[dict[str, Any]]:
        with closing(self.db.connect()) as conn:
            if artifact_type:
                rows = conn.execute(
                    "SELECT * FROM artifacts WHERE document_id = ? AND artifact_type = ? "
                    "ORDER BY created_at DESC",
                    (document_id, artifact_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM artifacts WHERE document_id = ? ORDER BY created_at DESC",
                    (document_id,),
                ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_latest(
        self, document_id: str, artifact_type: str
    ) -> Optional[dict[str, Any]]:
        with closing(self.db.connect()) as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE document_id = ? AND artifact_type = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (document_id, artifact_type),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def update_status(
        self,
        artifact_id: str,
        status: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with closing(self.db.connect()) as conn:
            if metadata is not None:
                conn.execute(
                    "UPDATE artifacts SET status = ?, metadata = ?, updated_at = ? WHERE id = ?",
                    (status, json.dumps(metadata), now, artifact_id),
                )
            else:
                conn.execute(
                    "UPDATE artifacts SET status = ?, updated_at = ? WHERE id = ?",
                    (status, now, artifact_id),
                )
            conn.commit()

    def delete(self, artifact_id: str) -> bool:
        with closing(self.db.connect()) as conn:
            cursor = conn.execute(
                "DELETE FROM artifacts WHERE id = ?", (artifact_id,)
            )
            conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        data = dict(row)
        meta = data.get("metadata")
        if isinstance(meta, str):
            data["metadata"] = json.loads(meta) if meta else None
        return data
