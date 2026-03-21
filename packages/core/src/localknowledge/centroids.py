"""Centroid store — project embedding centroids for similarity scoring."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime

import numpy as np

from .db import Database
from .embeddings.dense import (
    TABLE as DENSE_TABLE,
    DenseBackend,
    cosine_similarity,
    embedding_from_bytes,
    embedding_to_bytes,
)


class CentroidStore:
    def __init__(self, db: Database, dense: DenseBackend):
        self.db = db
        self.dense = dense

    def compute_centroid(self, tag_id: str) -> list[float] | None:
        """Mean of per-document centroids (each doc centroid = mean of its chunks).

        Equal weight per document regardless of chunk count.
        """
        with closing(self.db.connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT e.document_id, e.embedding
                FROM {DENSE_TABLE} e
                JOIN document_tags dt ON dt.document_id = e.document_id
                WHERE dt.tag_id = ?
                """,
                (tag_id,),
            ).fetchall()

        if not rows:
            return None

        # Group embeddings by document, compute per-doc centroid
        doc_embeddings: dict[str, list[np.ndarray]] = {}
        for row in rows:
            doc_id = row[0]
            vec = np.array(embedding_from_bytes(row[1]))
            doc_embeddings.setdefault(doc_id, []).append(vec)

        doc_centroids = []
        for vecs in doc_embeddings.values():
            doc_centroids.append(np.mean(vecs, axis=0))

        centroid = np.mean(doc_centroids, axis=0)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        return centroid.tolist()

    def update_centroid(self, tag_id: str) -> bool:
        """Recompute and store centroid for a project tag."""
        centroid = self.compute_centroid(tag_id)
        if centroid is None:
            return False

        now = datetime.now(UTC).isoformat()
        # Count documents in this project
        with closing(self.db.connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT document_id) FROM document_tags WHERE tag_id = ?",
                (tag_id,),
            ).fetchone()
            doc_count = row[0] if row else 0

            conn.execute(
                """
                INSERT OR REPLACE INTO project_centroids
                    (tag_id, embedding, model, doc_count, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (tag_id, embedding_to_bytes(centroid), self.dense.model_name, doc_count, now),
            )
            conn.commit()
        return True

    def get_centroid(self, tag_id: str) -> list[float] | None:
        """Retrieve stored centroid for a project tag."""
        with closing(self.db.connect()) as conn:
            row = conn.execute(
                "SELECT embedding FROM project_centroids WHERE tag_id = ?",
                (tag_id,),
            ).fetchone()
        if not row:
            return None
        return embedding_from_bytes(row[0])

    def get_all_centroids(self) -> list[tuple[str, str, list[float]]]:
        """Return [(tag_id, project_slug, embedding), ...] for all project centroids."""
        with closing(self.db.connect()) as conn:
            rows = conn.execute(
                """
                SELECT pc.tag_id, t.slug, pc.embedding
                FROM project_centroids pc
                JOIN tags t ON t.id = pc.tag_id
                """
            ).fetchall()
        return [
            (row[0], row[1], embedding_from_bytes(row[2]))
            for row in rows
        ]

    def update_all_centroids(self) -> int:
        """Recompute centroids for all project tags. Returns count updated."""
        with closing(self.db.connect()) as conn:
            rows = conn.execute(
                "SELECT id FROM tags WHERE tag_type = 'project'"
            ).fetchall()

        count = 0
        for row in rows:
            if self.update_centroid(row[0]):
                count += 1
        return count

    def score_document(self, doc_id: str, tag_id: str) -> float | None:
        """Max cosine similarity of doc chunks against project centroid."""
        centroid = self.get_centroid(tag_id)
        if centroid is None:
            return None

        centroid_vec = np.array(centroid)
        with closing(self.db.connect()) as conn:
            rows = conn.execute(
                f"SELECT embedding FROM {DENSE_TABLE} WHERE document_id = ?",
                (doc_id,),
            ).fetchall()

        if not rows:
            return None

        best = max(
            cosine_similarity(centroid_vec, np.array(embedding_from_bytes(row[0])))
            for row in rows
        )
        return best
