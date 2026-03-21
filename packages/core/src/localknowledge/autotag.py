"""Auto-tagging engine — topic and project suggestions via embedding similarity."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass

import numpy as np

from .centroids import CentroidStore
from .db import Database
from .embeddings.dense import (
    TABLE as DENSE_TABLE,
    DenseBackend,
    cosine_similarity,
    embedding_from_bytes,
)
from .tags import TagStore

TOPIC_AUTO_THRESHOLD = 0.7
TOPIC_SUGGEST_THRESHOLD = 0.5
PROJECT_SUGGEST_THRESHOLD = 0.5


@dataclass(slots=True)
class TagSuggestion:
    tag_id: str
    tag_name: str
    tag_slug: str
    tag_type: str       # "topic" or "project"
    score: float
    action: str         # "auto" or "suggest"


class AutoTagger:
    def __init__(
        self,
        db: Database,
        tags: TagStore,
        dense: DenseBackend,
        centroids: CentroidStore,
    ):
        self.db = db
        self.tags = tags
        self.dense = dense
        self.centroids = centroids
        self._topic_embeddings: dict[str, np.ndarray] | None = None

    def _get_doc_embeddings(self, doc_id: str) -> list[np.ndarray]:
        """Fetch all chunk embeddings for a document."""
        with closing(self.db.connect()) as conn:
            rows = conn.execute(
                f"SELECT embedding FROM {DENSE_TABLE} WHERE document_id = ?",
                (doc_id,),
            ).fetchall()
        return [np.array(embedding_from_bytes(row[0])) for row in rows]

    def _get_topic_embeddings(self) -> dict[str, np.ndarray]:
        """Embed each topic name+description, cached in memory."""
        if self._topic_embeddings is not None:
            return self._topic_embeddings

        topics = self.tags.list_topics()
        if not topics:
            self._topic_embeddings = {}
            return self._topic_embeddings

        texts = []
        tag_ids = []
        for t in topics:
            label = t["name"]
            if t.get("description"):
                label = f"{label}: {t['description']}"
            texts.append(label)
            tag_ids.append(t["id"])

        vectors = self.dense._embed_fn(texts)
        self._topic_embeddings = {
            tag_id: np.array(vec)
            for tag_id, vec in zip(tag_ids, vectors)
        }
        return self._topic_embeddings

    def invalidate_topic_cache(self) -> None:
        """Clear cached topic embeddings (call when tags change)."""
        self._topic_embeddings = None

    def suggest_topics(self, doc_id: str) -> list[TagSuggestion]:
        """Score document against topic tag embeddings."""
        doc_vecs = self._get_doc_embeddings(doc_id)
        if not doc_vecs:
            return []

        topic_vecs = self._get_topic_embeddings()
        if not topic_vecs:
            return []

        topics = self.tags.list_topics()
        topic_map = {t["id"]: t for t in topics}

        suggestions = []
        for tag_id, topic_vec in topic_vecs.items():
            # Max similarity across doc chunks
            score = max(cosine_similarity(topic_vec, dv) for dv in doc_vecs)

            if score < TOPIC_SUGGEST_THRESHOLD:
                continue

            tag = topic_map[tag_id]
            action = "auto" if score >= TOPIC_AUTO_THRESHOLD else "suggest"
            suggestions.append(TagSuggestion(
                tag_id=tag_id,
                tag_name=tag["name"],
                tag_slug=tag["slug"],
                tag_type="topic",
                score=score,
                action=action,
            ))

        suggestions.sort(key=lambda s: s.score, reverse=True)
        return suggestions

    def suggest_projects(self, doc_id: str) -> list[TagSuggestion]:
        """Score document against project centroids. Always suggest, never auto-assign."""
        all_centroids = self.centroids.get_all_centroids()
        if not all_centroids:
            return []

        doc_vecs = self._get_doc_embeddings(doc_id)
        if not doc_vecs:
            return []

        projects = self.tags.list_projects()
        project_map = {p["id"]: p for p in projects}

        suggestions = []
        for tag_id, slug, centroid in all_centroids:
            centroid_vec = np.array(centroid)
            score = max(cosine_similarity(centroid_vec, dv) for dv in doc_vecs)

            if score < PROJECT_SUGGEST_THRESHOLD:
                continue

            tag = project_map.get(tag_id)
            if not tag:
                continue

            suggestions.append(TagSuggestion(
                tag_id=tag_id,
                tag_name=tag["name"],
                tag_slug=slug,
                tag_type="project",
                score=score,
                action="suggest",  # Never auto-assign projects
            ))

        suggestions.sort(key=lambda s: s.score, reverse=True)
        return suggestions

    def suggest_all(self, doc_id: str) -> list[TagSuggestion]:
        """Combined topic + project suggestions, sorted by score."""
        results = self.suggest_topics(doc_id) + self.suggest_projects(doc_id)
        results.sort(key=lambda s: s.score, reverse=True)
        return results

    def auto_tag(self, doc_id: str) -> list[TagSuggestion]:
        """Apply topics with action='auto' (score >= threshold).

        Returns all suggestions including unapplied ones.
        """
        suggestions = self.suggest_all(doc_id)

        for s in suggestions:
            if s.action == "auto":
                self.tags.tag_document(
                    doc_id, s.tag_id,
                    confidence=s.score, source="auto_tag",
                )

        return suggestions
